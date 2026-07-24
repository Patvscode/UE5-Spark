#!/usr/bin/env bash
set -euo pipefail
umask 077

usage() {
    printf 'Usage: %s EXPECTED_UNREAL_EXE LIVE_ROOT [WAIT_SECONDS] [FPS]\n' "${0##*/}" >&2
    printf 'Publishes atomic JPEGs from one exact 1280x720 packaged Unreal window.\n' >&2
}

fail() {
    printf 'error: %s\n' "$*" >&2
    exit 1
}

if (( $# < 2 || $# > 4 )); then
    usage
    exit 64
fi
if [[ $(uname -s) != Linux || $(uname -m) != aarch64 ]]; then
    fail 'the live preview producer must run on Linux/aarch64 DGX Spark'
fi
if (( ${EUID:-$(id -u)} == 0 )); then
    fail 'run the live preview producer as the normal desktop owner, not root'
fi

expected_exe_input=$1
live_root_input=$2
wait_seconds=${3:-120}
preview_fps=${4:-12}
[[ $wait_seconds =~ ^[1-9][0-9]*$ && $wait_seconds -le 600 ]] || \
    fail 'WAIT_SECONDS must be an integer from 1 through 600'
[[ $preview_fps =~ ^([5-9]|1[0-5])$ ]] || \
    fail 'FPS must be an integer from 5 through 15'

for command_name in awk date ffmpeg ffprobe flock grep id readlink realpath rm \
    seq sleep stat systemctl xdotool xprop xwininfo; do
    command -v "$command_name" >/dev/null 2>&1 || fail "missing command: $command_name"
done

expected_exe=$(realpath "$expected_exe_input")
[[ -x $expected_exe && ${expected_exe##*/} == FayAvatarRuntime ]] || \
    fail 'EXPECTED_UNREAL_EXE is not the packaged FayAvatarRuntime binary'
ffmpeg_exe=$(realpath "$(command -v ffmpeg)")

runtime_dir_input=${XDG_RUNTIME_DIR:-"/run/user/$(id -u)"}
runtime_dir=$(realpath "$runtime_dir_input")
[[ -d $runtime_dir && -O $runtime_dir ]] || \
    fail 'the local user runtime directory is missing or not owned by this user'
live_root=$(realpath "$live_root_input")
[[ -d $live_root && ! -L $live_root && -O $live_root ]] || \
    fail 'LIVE_ROOT must be a real directory owned by this user'
case "$live_root/" in
    "$runtime_dir/"*) ;;
    *) fail 'LIVE_ROOT must be below the current user runtime directory' ;;
esac
[[ $(stat -c '%a' "$live_root") == 700 ]] || \
    fail 'LIVE_ROOT must have mode 0700'

frame_path="$live_root/frame.jpg"
lock_path="$live_root/.producer.lock"
exec 9>"$lock_path"
flock -n 9 || fail 'another live preview producer already owns LIVE_ROOT'
[[ ! -L $frame_path ]] || fail 'refusing to replace a symlinked live frame'
if [[ -e $frame_path ]]; then
    [[ -f $frame_path && -O $frame_path ]] || \
        fail 'the existing live frame is not a regular file owned by this user'
    [[ $(stat -c '%a' "$frame_path") == 600 ]] || \
        fail 'the existing live frame must have mode 0600'
fi

ffmpeg -hide_banner -h muxer=image2 2>&1 | grep -F atomic_writing >/dev/null || \
    fail 'ffmpeg image2 atomic writing support is unavailable'
ffmpeg -hide_banner -encoders 2>/dev/null | \
    grep -E '^[[:space:]]*V[^[:space:]]*[[:space:]]+mjpeg[[:space:]]' >/dev/null || \
    fail 'ffmpeg MJPEG encoding support is unavailable'

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
    local pid=$1 expected_starttime=$2 expected_binary=$3
    local actual_exe actual_starttime
    actual_exe=$(readlink "/proc/$pid/exe" 2>/dev/null || true)
    [[ $actual_exe == "$expected_binary" ]] || return 1
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
    candidate_authority="$runtime_dir/gdm/Xauthority"
    [[ -r $candidate_authority && -O $candidate_authority ]] || \
        fail 'the selected display has no same-user readable XAUTHORITY'
    export XAUTHORITY="$candidate_authority"
fi
[[ -r $XAUTHORITY && -O $XAUTHORITY ]] || fail 'XAUTHORITY is unreadable or unsafe'

deadline=$(( $(date +%s) + wait_seconds ))
runtime_pid=''
runtime_starttime=''
while (( $(date +%s) < deadline )); do
    mapfile -t runtime_pids < <(find_runtime_pids)
    (( ${#runtime_pids[@]} <= 1 )) || fail 'multiple exact package processes appeared'
    if (( ${#runtime_pids[@]} == 1 )); then
        candidate_pid=${runtime_pids[0]}
        candidate_starttime=$(read_process_starttime "$candidate_pid" || true)
        if [[ -n $candidate_starttime ]] && \
            process_matches_identity "$candidate_pid" "$candidate_starttime" "$expected_exe"; then
            runtime_pid=$candidate_pid
            runtime_starttime=$candidate_starttime
            break
        fi
    fi
    sleep 0.1
done
[[ -n $runtime_pid ]] || fail 'the expected packaged runtime did not appear'

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
    process_matches_identity "$runtime_pid" "$runtime_starttime" "$expected_exe" || \
        fail 'the packaged runtime changed identity before window selection'
    window_id=$(find_exact_window || true)
    [[ -n $window_id ]] && break
    sleep 0.1
done
[[ $window_id =~ ^[0-9]+$ ]] || \
    fail 'one exact visible 1280x720 Unreal client was not found'

producer_pid=''
producer_starttime=''
stop_owned_producer() {
    [[ -n ${producer_pid:-} && -n ${producer_starttime:-} ]] || return 0
    if ! process_matches_identity "$producer_pid" "$producer_starttime" "$ffmpeg_exe"; then
        return 0
    fi
    kill -TERM "$producer_pid" 2>/dev/null || true
    for _ in $(seq 1 50); do
        process_matches_identity "$producer_pid" "$producer_starttime" "$ffmpeg_exe" || return 0
        sleep 0.1
    done
    if process_matches_identity "$producer_pid" "$producer_starttime" "$ffmpeg_exe"; then
        kill -KILL "$producer_pid" 2>/dev/null || true
    fi
}

cleanup() {
    local status=$?
    trap - EXIT HUP INT TERM
    stop_owned_producer
    if [[ -f $frame_path && ! -L $frame_path && -O $frame_path ]]; then
        rm -f -- "$frame_path"
    fi
    exit "$status"
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

"$ffmpeg_exe" -nostdin -hide_banner -nostats -loglevel warning -y \
    -f x11grab -framerate "$preview_fps" -draw_mouse 0 \
    -window_id "$window_id" -i "$DISPLAY" \
    -an -vf 'scale=960:540:flags=lanczos,format=yuvj420p' \
    -c:v mjpeg -q:v 7 -threads:v 2 \
    -f image2 -update 1 -atomic_writing 1 "$frame_path" &
producer_pid=$!
producer_starttime=$(read_process_starttime "$producer_pid" || true)
[[ -n $producer_starttime ]] && \
    process_matches_identity "$producer_pid" "$producer_starttime" "$ffmpeg_exe" || \
    fail 'the ffmpeg live preview producer did not start with a stable identity'

frame_ready=0
for _ in $(seq 1 100); do
    process_matches_identity "$producer_pid" "$producer_starttime" "$ffmpeg_exe" || \
        fail 'the ffmpeg live preview producer exited before its first frame'
    if [[ -f $frame_path && ! -L $frame_path && -O $frame_path ]] && \
        [[ $(stat -c '%a' "$frame_path") == 600 ]]; then
        frame_probe=$(ffprobe -v error -select_streams v:0 \
            -show_entries stream=codec_name,width,height \
            -of csv=p=0 "$frame_path" 2>/dev/null || true)
        if [[ $frame_probe == mjpeg,960,540 ]]; then
            frame_ready=1
            break
        fi
    fi
    sleep 0.1
done
(( frame_ready == 1 )) || fail 'the live preview producer did not publish a valid frame'

printf 'live_preview_status=ready\n'
printf 'runtime_pid=%s\n' "$runtime_pid"
printf 'window_id=%s\n' "$window_id"
printf 'fps=%s\n' "$preview_fps"

while process_matches_identity "$producer_pid" "$producer_starttime" "$ffmpeg_exe"; do
    process_matches_identity "$runtime_pid" "$runtime_starttime" "$expected_exe" || \
        fail 'the packaged runtime changed identity during live preview'
    [[ $(find_exact_window || true) == "$window_id" ]] || \
        fail 'the exact Unreal client window changed during live preview'
    [[ -f $frame_path && ! -L $frame_path && -O $frame_path ]] || \
        fail 'the live preview frame disappeared or became unsafe'
    current_time=$(date +%s)
    frame_time=$(stat -c '%Y' "$frame_path")
    [[ $frame_time =~ ^[0-9]+$ ]] && \
        (( current_time >= frame_time && current_time - frame_time <= 3 )) || \
        fail 'the live preview frame stopped updating'
    sleep 1
done

set +e
wait "$producer_pid"
producer_status=$?
set -e
producer_pid=''
producer_starttime=''
(( producer_status == 0 )) || fail "the ffmpeg live preview producer exited with status $producer_status"
