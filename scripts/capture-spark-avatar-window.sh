#!/usr/bin/env bash
set -euo pipefail
umask 077

usage() {
    printf 'Usage: %s EXPECTED_UNREAL_EXE RUNTIME_LOG CHARACTER OUTPUT_PNG OUTPUT_MP4 WAIT_SECONDS [speech|ardy-explain] [Portrait|FullBody]\n' \
        "${0##*/}" >&2
    printf 'Waits for one fresh reviewed avatar run, then captures only its exact 1280x720 X11 client window.\n' >&2
    printf 'The reviewed camera framing defaults to Portrait when omitted.\n' >&2
}

fail() {
    printf 'error: %s\n' "$*" >&2
    exit 1
}

if (( $# < 6 || $# > 8 )); then
    usage
    exit 64
fi
if [[ $(uname -s) != Linux || $(uname -m) != aarch64 ]]; then
    fail 'the guarded media capture must run on Linux/aarch64 DGX Spark'
fi
if (( ${EUID:-$(id -u)} == 0 )); then
    fail 'run media capture as the normal desktop owner, not root'
fi

expected_exe_input=$1
runtime_log_input=$2
character=$3
output_png_input=$4
output_mp4_input=$5
wait_seconds=$6
capture_phase=${7:-speech}
expected_camera_framing=${8:-Portrait}
[[ $character == Ada || $character == Aoi ]] || \
    fail 'CHARACTER must be a reviewed Ada or Aoi profile'
[[ $capture_phase == speech || $capture_phase == ardy-explain ]] || \
    fail 'capture phase must be speech or ardy-explain'
[[ $expected_camera_framing == Portrait || $expected_camera_framing == FullBody ]] || \
    fail 'camera framing must be the reviewed Portrait or FullBody preset'
[[ $wait_seconds =~ ^[1-9][0-9]*$ && $wait_seconds -le 600 ]] || \
    fail 'WAIT_SECONDS must be an integer from 1 through 600'

for command_name in awk date ffmpeg ffprobe find grep id ln mktemp readlink realpath \
    rm sed seq sha256sum sleep stat systemctl tail timeout xdotool xprop xwininfo; do
    command -v "$command_name" >/dev/null 2>&1 || fail "missing command: $command_name"
done

expected_exe=$(realpath "$expected_exe_input")
[[ -x $expected_exe && ${expected_exe##*/} == FayAvatarRuntime ]] || \
    fail 'EXPECTED_UNREAL_EXE is not the packaged FayAvatarRuntime binary'
runtime_log=$(realpath -m "$runtime_log_input")
runtime_log_parent=$(realpath -m "$(dirname "$runtime_log")")
[[ $runtime_log == "$runtime_log_parent/$(basename "$runtime_log")" ]] || \
    fail 'RUNTIME_LOG could not be normalized safely'
expected_runtime_log=$(realpath -m \
    "$(dirname "$expected_exe")/../../Saved/Logs/FayAvatarRuntime.log")
[[ $runtime_log == "$expected_runtime_log" ]] || \
    fail 'RUNTIME_LOG does not belong to EXPECTED_UNREAL_EXE'

normalize_output() {
    local input=$1 expected_suffix=$2 parent normalized
    parent=$(realpath "$(dirname "$input")")
    [[ -d $parent && ! -L $parent ]] || fail "output parent is unsafe: $parent"
    case "$parent/" in
        */media-private/*) ;;
        *) fail 'media outputs must be below a private media root' ;;
    esac
    normalized="$parent/$(basename "$input")"
    [[ $normalized == *"$expected_suffix" ]] || \
        fail "output must end in $expected_suffix: $normalized"
    [[ ! -e $normalized && ! -L $normalized ]] || \
        fail "refusing to overwrite media output: $normalized"
    printf '%s\n' "$normalized"
}

output_png=$(normalize_output "$output_png_input" .png)
output_mp4=$(normalize_output "$output_mp4_input" .mp4)
[[ $output_png != "$output_mp4" ]] || fail 'PNG and MP4 outputs must differ'

read_process_starttime() {
    local pid=$1 stat_line stat_fields
    [[ -r /proc/$pid/stat ]] || return 1
    IFS= read -r stat_line <"/proc/$pid/stat" || return 1
    stat_fields=${stat_line##*) }
    [[ $stat_fields != "$stat_line" ]] || return 1
    set -- $stat_fields
    [[ ${20:-} =~ ^[0-9]+$ ]] || return 1
    printf '%s\n' "${20}"
}

process_matches_identity() {
    local pid=$1 expected_starttime=$2 actual_exe actual_starttime
    actual_exe=$(readlink "/proc/$pid/exe" 2>/dev/null || true)
    [[ $actual_exe == "$expected_exe" ]] || return 1
    actual_starttime=$(read_process_starttime "$pid" || true)
    [[ -n $actual_starttime && $actual_starttime == "$expected_starttime" ]]
}

find_runtime_pids() {
    local process_dir process_exe
    for process_dir in /proc/[1-9]*; do
        process_exe=$(readlink "$process_dir/exe" 2>/dev/null || true)
        [[ $process_exe == "$expected_exe" ]] && printf '%s\n' "${process_dir##*/}"
    done
}

mapfile -t preexisting_pids < <(find_runtime_pids)
(( ${#preexisting_pids[@]} == 0 )) || \
    fail 'the exact package is already running; arm capture before launch'
runtime_log_prelaunch_identity=missing
if [[ -f $runtime_log && ! -L $runtime_log ]]; then
    runtime_log_prelaunch_identity=$(stat -c '%d:%i:%s:%y' "$runtime_log")
fi

if [[ -z ${DISPLAY:-} ]]; then
    user_environment=$(systemctl --user show-environment 2>/dev/null) || \
        fail 'could not query the existing desktop environment'
    DISPLAY=$(awk -F= '$1 == "DISPLAY" {sub(/^[^=]*=/, ""); print; exit}' \
        <<<"$user_environment")
    export DISPLAY
fi
[[ $DISPLAY =~ ^:([0-9]+)([.][0-9]+)?$ ]] || \
    fail 'DISPLAY is not an unambiguous local X11 display'
display_socket="/tmp/.X11-unix/X${BASH_REMATCH[1]}"
[[ -S $display_socket && -O $display_socket ]] || \
    fail 'the selected X11 socket is missing or not owned by this user'
if [[ -z ${XAUTHORITY:-} ]]; then
    runtime_dir=${XDG_RUNTIME_DIR:-"/run/user/$(id -u)"}
    candidate_authority="$runtime_dir/gdm/Xauthority"
    [[ -r $candidate_authority && -O $candidate_authority ]] || \
        fail 'the selected display has no same-user readable XAUTHORITY'
    export XAUTHORITY="$candidate_authority"
fi
[[ -r $XAUTHORITY && -O $XAUTHORITY ]] || fail 'XAUTHORITY is unreadable or unsafe'

deadline=$(( $(date +%s) + wait_seconds ))
runtime_pid=''
runtime_starttime=''
launch_log_start=''
camera_framing_marker="Selected reviewed character profile '$character' (adapter=UE58MetaHuman, camera_framing=$expected_camera_framing)."
camera_framing_selected_count=0
capture_ready=0
while (( $(date +%s) < deadline )); do
    mapfile -t runtime_pids < <(find_runtime_pids)
    (( ${#runtime_pids[@]} <= 1 )) || fail 'multiple exact package processes appeared'
    if (( ${#runtime_pids[@]} == 1 )); then
        candidate_pid=${runtime_pids[0]}
        candidate_starttime=$(read_process_starttime "$candidate_pid" || true)
        if [[ -n $candidate_starttime ]] && \
            process_matches_identity "$candidate_pid" "$candidate_starttime"; then
            runtime_pid=$candidate_pid
            runtime_starttime=$candidate_starttime
            break
        fi
    fi
    sleep 0.1
done
[[ -n $runtime_pid ]] || fail 'the expected packaged runtime did not appear'

while (( $(date +%s) < deadline )); do
    process_matches_identity "$runtime_pid" "$runtime_starttime" || \
        fail 'the packaged runtime changed identity before capture readiness'
    if [[ -f $runtime_log && ! -L $runtime_log ]]; then
        runtime_log_identity=$(stat -c '%d:%i:%s:%y' "$runtime_log")
        if [[ $runtime_log_identity != "$runtime_log_prelaunch_identity" ]]; then
            latest_log_open=$(grep -n 'Log file open,' "$runtime_log" | tail -n1 || true)
            launch_log_start=${latest_log_open%%:*}
            if [[ $launch_log_start =~ ^[1-9][0-9]*$ ]]; then
                launch_log=$(tail -n "+$launch_log_start" "$runtime_log")
                camera_framing_selected_count=$(grep -Fc "$camera_framing_marker" \
                    <<<"$launch_log" || true)
                phase_ready=0
                if [[ $capture_phase == speech ]] || \
                    grep -Fq "Using ARDY generated motion provider for 'explain'" \
                        <<<"$launch_log"; then
                    phase_ready=1
                fi
                if (( camera_framing_selected_count == 1 )) &&
                    grep -Fq "Spawned character '$character'" <<<"$launch_log" &&
                    grep -Fq 'Connected to the Fay avatar WebSocket.' <<<"$launch_log" &&
                    grep -Fq 'Activated the visible Spark studio camera and lighting rig.' <<<"$launch_log" &&
                    grep -Fq 'Started Fay speech playback' <<<"$launch_log" &&
                    (( phase_ready == 1 )); then
                    capture_ready=1
                    break
                fi
            fi
        fi
    fi
    sleep 0.1
done
(( capture_ready == 1 )) || fail 'the fresh runtime log never reached speech readiness'

find_exact_window() {
    local candidate candidate_pid width height map_state
    local -a matches=()
    while IFS= read -r candidate; do
        [[ $candidate =~ ^[0-9]+$ ]] || continue
        candidate_pid=$(xprop -id "$candidate" _NET_WM_PID 2>/dev/null |
            awk -F'= ' 'NF == 2 {print $2; exit}')
        [[ $candidate_pid == "$runtime_pid" ]] || continue
        width=$(xdotool getwindowgeometry --shell "$candidate" 2>/dev/null |
            awk -F= '$1 == "WIDTH" {print $2; exit}')
        height=$(xdotool getwindowgeometry --shell "$candidate" 2>/dev/null |
            awk -F= '$1 == "HEIGHT" {print $2; exit}')
        [[ $width == 1280 && $height == 720 ]] || continue
        map_state=$(xwininfo -id "$candidate" 2>/dev/null |
            awk -F: '/Map State:/ {gsub(/^[[:space:]]+/, "", $2); print $2; exit}')
        [[ $map_state == IsViewable ]] || continue
        matches+=("$candidate")
    done < <(xdotool search --pid "$runtime_pid" 2>/dev/null || true)
    (( ${#matches[@]} == 1 )) || return 1
    printf '%s\n' "${matches[0]}"
}

window_id=''
while (( $(date +%s) < deadline )); do
    process_matches_identity "$runtime_pid" "$runtime_starttime" || \
        fail 'the packaged runtime changed identity before window selection'
    window_id=$(find_exact_window || true)
    [[ -n $window_id ]] && break
    sleep 0.1
done
[[ $window_id =~ ^[0-9]+$ ]] || fail 'one exact visible 1280x720 Unreal client was not found'
process_matches_identity "$runtime_pid" "$runtime_starttime" || \
    fail 'runtime identity changed immediately before capture'

png_parent=$(dirname "$output_png")
mp4_parent=$(dirname "$output_mp4")
temporary_png=$(mktemp "$png_parent/.partial.XXXXXX.png")
temporary_mp4=$(mktemp "$mp4_parent/.partial.XXXXXX.mp4")
temporary_png_identity=$(stat -c '%d:%i' "$temporary_png")
temporary_mp4_identity=$(stat -c '%d:%i' "$temporary_mp4")
published_png=0
published_mp4=0
publish_complete=0
cleanup() {
    rm -f -- "${temporary_png:-}" "${temporary_mp4:-}"
    if (( ${publish_complete:-0} == 0 )); then
        if (( ${published_png:-0} == 1 )) && [[ -f ${output_png:-} && ! -L ${output_png:-} ]] &&
            [[ $(stat -c '%d:%i' "$output_png") == "${temporary_png_identity:-missing}" ]]; then
            rm -f -- "$output_png"
        fi
        if (( ${published_mp4:-0} == 1 )) && [[ -f ${output_mp4:-} && ! -L ${output_mp4:-} ]] &&
            [[ $(stat -c '%d:%i' "$output_mp4") == "${temporary_mp4_identity:-missing}" ]]; then
            rm -f -- "$output_mp4"
        fi
    fi
}
handle_signal() {
    local signal_name=$1 exit_status=$2
    trap - HUP INT TERM
    printf 'error: interrupted by %s during private media capture\n' "$signal_name" >&2
    exit "$exit_status"
}
trap cleanup EXIT
trap 'handle_signal HUP 129' HUP
trap 'handle_signal INT 130' INT
trap 'handle_signal TERM 143' TERM

timeout --signal=TERM --kill-after=5 15 ffmpeg -nostdin -hide_banner -loglevel error -y \
    -f x11grab -framerate 1 -draw_mouse 0 -window_id "$window_id" -i "$DISPLAY" \
    -frames:v 1 "$temporary_png"
timeout --signal=TERM --kill-after=5 30 ffmpeg -nostdin -hide_banner -loglevel error -y \
    -f x11grab -framerate 30 -draw_mouse 0 -window_id "$window_id" -i "$DISPLAY" \
    -t 8 -an -vf format=yuv420p \
    -c:v h264_nvenc -preset p1 -tune ll -rc constqp -qp 23 \
    -profile:v high -level:v 4.0 -g 60 -movflags +faststart "$temporary_mp4"

process_matches_identity "$runtime_pid" "$runtime_starttime" || \
    fail 'runtime identity changed during capture'
[[ $(find_exact_window || true) == "$window_id" ]] || \
    fail 'the exact client-window identity changed during capture'
png_probe=$(timeout --signal=TERM --kill-after=2 10 ffprobe -v error \
    -select_streams v:0 -show_entries stream=width,height \
    -of csv=p=0:s=x "$temporary_png")
mp4_probe=$(timeout --signal=TERM --kill-after=2 10 ffprobe -v error -select_streams v:0 \
    -show_entries stream=width,height,r_frame_rate -of csv=p=0 "$temporary_mp4")
duration_probe=$(timeout --signal=TERM --kill-after=2 10 ffprobe -v error \
    -show_entries format=duration -of default=nw=1:nk=1 "$temporary_mp4")
[[ $png_probe == 1280x720 ]] || fail "captured PNG has unexpected geometry: $png_probe"
[[ $mp4_probe == 1280,720,30/1 ]] || fail "captured MP4 has unexpected stream: $mp4_probe"
awk -v duration="$duration_probe" 'BEGIN {exit !(duration >= 7.9 && duration <= 8.2)}' || \
    fail "captured MP4 has unexpected duration: $duration_probe"

ln -- "$temporary_png" "$output_png"
published_png=1
ln -- "$temporary_mp4" "$output_mp4"
published_mp4=1
publish_complete=1
rm -- "$temporary_png" "$temporary_mp4"
trap - EXIT HUP INT TERM
printf 'capture_status=passed\n'
printf 'character=%s\n' "$character"
printf 'camera_framing=%s\n' "$expected_camera_framing"
printf 'camera_framing_marker_count=%s\n' "$camera_framing_selected_count"
printf 'capture_phase=%s\n' "$capture_phase"
printf 'runtime_pid=%s\n' "$runtime_pid"
printf 'runtime_starttime=%s\n' "$runtime_starttime"
printf 'window_id=%s\n' "$window_id"
printf 'display=%s\n' "$DISPLAY"
printf 'png=%s\n' "$output_png"
printf 'png_sha256=%s\n' "$(sha256sum "$output_png" | awk '{print $1}')"
printf 'mp4=%s\n' "$output_mp4"
printf 'mp4_sha256=%s\n' "$(sha256sum "$output_mp4" | awk '{print $1}')"
printf 'mp4_duration_seconds=%s\n' "$duration_probe"
