#!/usr/bin/env bash
set -euo pipefail
umask 077

usage() {
    printf 'Usage: %s PACKAGE_LAUNCHER FAY_PID PRIVATE_OUTPUT_DIR DURATION_SECONDS TURN_COUNT [Unreal arguments...]\n' \
        "${0##*/}" >&2
    printf '       TURN_COUNT=0 runs an idle-only rendered diagnostic.\n' >&2
}

fail() {
    printf 'error: %s\n' "$*" >&2
    exit 1
}

if (( $# < 5 )); then
    usage
    exit 64
fi
if [[ $(uname -s) != Linux || $(uname -m) != aarch64 ]]; then
    fail 'the rendered soak runner requires Linux/aarch64 on DGX Spark'
fi
if (( ${EUID:-$(id -u)} == 0 )); then
    fail 'run the rendered soak as the normal workspace owner, not root'
fi

package_launcher_input=$1
fay_pid=$2
output_input=$3
duration=$4
turn_count=$5
shift 5
[[ $fay_pid =~ ^[1-9][0-9]*$ ]] || fail 'FAY_PID must be a positive integer'
[[ $duration =~ ^[1-9][0-9]*$ && $turn_count =~ ^[0-9]+$ ]] || \
    fail 'duration must be positive and turn count must be a non-negative integer'
idle_warmup_seconds=${FAY_SOAK_IDLE_WARMUP_SECONDS:-120}
idle_measurement_seconds=${FAY_SOAK_IDLE_MEASUREMENT_SECONDS:-300}
[[ $idle_warmup_seconds =~ ^[0-9]+$ ]] || \
    fail 'FAY_SOAK_IDLE_WARMUP_SECONDS must be a non-negative integer'
[[ $idle_measurement_seconds =~ ^[1-9][0-9]*$ ]] || \
    fail 'FAY_SOAK_IDLE_MEASUREMENT_SECONDS must be a positive integer'
if (( idle_measurement_seconds < 30 || idle_measurement_seconds > 3600 )); then
    fail 'FAY_SOAK_IDLE_MEASUREMENT_SECONDS must be from 30 through 3600'
fi
if (( turn_count == 0 && duration < idle_warmup_seconds + idle_measurement_seconds )); then
    fail 'an idle diagnostic must include its configured warm-up and measurement windows'
fi

for command_name in awk basename chmod cp curl date find grep head journalctl kill ln \
    mkdir mktemp mv ps python3 readlink realpath rm sed seq setsid sha256sum sleep \
    ss stat tail tr wc; do
    command -v "$command_name" >/dev/null 2>&1 || fail "missing command: $command_name"
done

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
digital_human_launcher="$script_dir/run-spark-digital-human.sh"
soak_runner="$script_dir/soak-spark-avatar.sh"
package_verifier="$script_dir/verify-cooked-package.sh"
[[ -x $digital_human_launcher && -x $soak_runner && -x $package_verifier ]] || \
    fail 'one or more guarded runtime scripts are unavailable'

package_launcher_dir=$(cd "$(dirname "$package_launcher_input")" && pwd -P)
package_launcher="$package_launcher_dir/$(basename "$package_launcher_input")"
[[ -x $package_launcher && ${package_launcher##*/} == FayAvatarRuntime-Arm64.sh ]] || \
    fail 'expected an executable FayAvatarRuntime-Arm64.sh package launcher'
expected_unreal_exe=$(realpath \
    "$package_launcher_dir/FayAvatarRuntime/Binaries/LinuxArm64/FayAvatarRuntime")
[[ -x $expected_unreal_exe ]] || fail 'the packaged Unreal executable is missing'

output_dir=$(mkdir -p "$output_input" && cd "$output_input" && pwd -P)
case "$output_dir/" in
    */media-private/*|*/logs-private/*) ;;
    *) fail 'output directory must be below a private media or log root' ;;
esac
if find "$output_dir" -mindepth 1 -maxdepth 1 -print -quit | grep -q .; then
    fail 'the private output directory must be empty so evidence cannot mix across runs'
fi

res_x=${FAY_SOAK_EXPECTED_RES_X:-1280}
res_y=${FAY_SOAK_EXPECTED_RES_Y:-720}
character=${FAY_SOAK_CHARACTER:-Ada}
camera_framing=${FAY_SOAK_CAMERA_FRAMING:-Portrait}
scene_only=${FAY_SOAK_SCENE_ONLY:-0}
avatar_dormancy=${FAY_SOAK_AVATAR_DORMANCY:-0}
avatar_dormancy_delay=${FAY_SOAK_AVATAR_DORMANCY_DELAY_SECONDS:-5}
enable_csv=${FAY_SOAK_ENABLE_CSV:-0}
csv_capture_frames=${FAY_SOAK_CSV_CAPTURE_FRAMES:-6000}
csv_compression=${FAY_SOAK_CSV_COMPRESSION:-0}
csv_trim_start_frames=${FAY_SOAK_CSV_TRIM_START_FRAMES:-300}
csv_trim_end_frames=${FAY_SOAK_CSV_TRIM_END_FRAMES:-30}
csv_min_average_fps=${FAY_SOAK_CSV_MIN_AVERAGE_FPS:-29}
csv_max_average_fps=${FAY_SOAK_CSV_MAX_AVERAGE_FPS:-31}
csv_max_p95_frame_time_ms=${FAY_SOAK_CSV_MAX_P95_FRAME_TIME_MS:-40}
requested_evidence_mode=${FAY_SOAK_EVIDENCE_MODE:-}
evidence_mode=$requested_evidence_mode
max_dormancy_cancellations=${FAY_SOAK_MAX_DORMANCY_CANCELLATIONS:-0}
max_tail_rss_growth_kb=${FAY_SOAK_MAX_TAIL_RSS_GROWTH_KB:-131072}
if (( turn_count == 0 )); then
    max_rss_kb=${FAY_SOAK_MAX_RSS_KB:-3040870}
else
    max_rss_kb=${FAY_SOAK_MAX_RSS_KB:-3145728}
fi
min_mem_available_kb=${FAY_SOAK_MIN_MEM_AVAILABLE_KB:-50331648}
max_gpu_utilization_percent=${FAY_SOAK_MAX_GPU_UTILIZATION_PERCENT:-95}
max_face_p95_ms=${FAY_SOAK_MAX_FACE_P95_MS:-20}
min_start_available_memory_gib=${UE5_SPARK_MIN_AVAILABLE_MEMORY_GIB:-48}
max_start_gpu_utilization=${UE5_SPARK_MAX_START_GPU_UTILIZATION:-85}
[[ $res_x =~ ^[1-9][0-9]*$ && $res_y =~ ^[1-9][0-9]*$ ]] || \
    fail 'FAY_SOAK_EXPECTED_RES_X/Y must be positive integers'
case "$character" in
    Ada|Aoi) expected_adapter=UE58MetaHuman ;;
    CasualGirl) expected_adapter=UE5EpicArkit ;;
    *) fail 'FAY_SOAK_CHARACTER must name a reviewed packaged profile' ;;
esac
[[ $camera_framing == Portrait || $camera_framing == FullBody ]] || \
    fail 'FAY_SOAK_CAMERA_FRAMING must be Portrait or FullBody'
[[ $scene_only =~ ^[01]$ ]] || fail 'FAY_SOAK_SCENE_ONLY must be 0 or 1'
if (( scene_only == 1 && turn_count != 0 )); then
    fail 'FAY_SOAK_SCENE_ONLY is restricted to zero-turn idle diagnostics'
fi
[[ -z $requested_evidence_mode || $requested_evidence_mode == production || \
    $requested_evidence_mode == diagnostic ]] || \
    fail 'FAY_SOAK_EVIDENCE_MODE must be production or diagnostic'
[[ $avatar_dormancy =~ ^[01]$ ]] || \
    fail 'FAY_SOAK_AVATAR_DORMANCY must be 0 or 1'
[[ $avatar_dormancy_delay =~ ^[1-9][0-9]*$ ]] || \
    fail 'FAY_SOAK_AVATAR_DORMANCY_DELAY_SECONDS must be an integer from 2 through 60'
if (( avatar_dormancy_delay < 2 || avatar_dormancy_delay > 60 )); then
    fail 'FAY_SOAK_AVATAR_DORMANCY_DELAY_SECONDS must be an integer from 2 through 60'
fi
if (( avatar_dormancy == 0 && avatar_dormancy_delay != 5 )); then
    fail 'FAY_SOAK_AVATAR_DORMANCY_DELAY_SECONDS must remain 5 while dormancy is disabled'
fi
if (( scene_only == 1 && avatar_dormancy == 1 )); then
    fail 'scene-only and avatar dormancy diagnostics are mutually exclusive'
fi
if (( avatar_dormancy == 1 && turn_count > 0 &&
    duration < turn_count * (avatar_dormancy_delay + 15) )); then
    fail 'a dormant speech soak must allow every turn time to wake, finish, and re-enter dormancy'
fi
[[ $enable_csv =~ ^[01]$ ]] || fail 'FAY_SOAK_ENABLE_CSV must be 0 or 1'
[[ $csv_capture_frames =~ ^[1-9][0-9]*$ ]] || \
    fail 'FAY_SOAK_CSV_CAPTURE_FRAMES must be a positive integer'
[[ $csv_compression =~ ^[01]$ ]] || \
    fail 'FAY_SOAK_CSV_COMPRESSION must be 0 or 1'
[[ $csv_trim_start_frames =~ ^[0-9]+$ && $csv_trim_end_frames =~ ^[0-9]+$ ]] || \
    fail 'CSV trim-frame counts must be non-negative integers'
for csv_numeric_limit in "$csv_min_average_fps" "$csv_max_average_fps" \
    "$csv_max_p95_frame_time_ms"; do
    [[ $csv_numeric_limit =~ ^[0-9]+([.][0-9]+)?$ ]] || \
        fail 'CSV performance limits must be non-negative numbers'
done
if (( enable_csv == 1 )); then
    (( csv_compression == 0 )) || \
        fail 'guarded CSV validation requires uncompressed CSVProfiler output'
    (( csv_capture_frames > csv_trim_start_frames + csv_trim_end_frames )) || \
        fail 'CSV trim-frame counts must leave at least one requested frame'
    if ! awk -v minimum="$csv_min_average_fps" -v maximum="$csv_max_average_fps" \
        -v p95="$csv_max_p95_frame_time_ms" \
        'BEGIN {exit !(minimum > 0 && maximum >= minimum && p95 > 0)}'; then
        fail 'CSV FPS/p95 limits must be positive and ordered'
    fi
    minimum_csv_duration=$(awk \
        -v frames="$csv_capture_frames" -v minimum_fps="$csv_min_average_fps" '
        BEGIN {
            seconds = frames / minimum_fps
            rounded_up = int(seconds)
            if (seconds > rounded_up) rounded_up++
            print rounded_up + 30
        }')
    [[ $minimum_csv_duration =~ ^[1-9][0-9]*$ ]] || \
        fail 'could not derive the guarded CSV capture duration'
    (( duration >= minimum_csv_duration )) || \
        fail 'run duration is too short to finish the requested capped CSV capture'
fi
[[ $max_dormancy_cancellations =~ ^(0|[1-9][0-9]*)$ ]] || \
    fail 'FAY_SOAK_MAX_DORMANCY_CANCELLATIONS must be a non-negative integer'
[[ $max_tail_rss_growth_kb =~ ^[0-9]+$ && $max_rss_kb =~ ^[0-9]+$ && \
    $min_mem_available_kb =~ ^[0-9]+$ ]] || \
    fail 'RSS and available-memory limits must be non-negative integers'
[[ $max_gpu_utilization_percent =~ ^([0-9]|[1-9][0-9]|100)$ && \
    $max_start_gpu_utilization =~ ^([0-9]|[1-9][0-9]|100)$ ]] || \
    fail 'GPU utilization limits must be integers from 0 through 100'
[[ $max_face_p95_ms =~ ^[0-9]+([.][0-9]+)?$ ]] || \
    fail 'FAY_SOAK_MAX_FACE_P95_MS must be a non-negative number'
[[ $min_start_available_memory_gib =~ ^([0-9]|[1-9][0-9]|1[01][0-9]|12[0-8])$ ]] || \
    fail 'UE5_SPARK_MIN_AVAILABLE_MEMORY_GIB must be an integer from 0 through 128'

diagnostic_overrides=()
add_diagnostic_override() {
    local candidate=$1 existing
    for existing in "${diagnostic_overrides[@]}"; do
        [[ $existing == "$candidate" ]] && return
    done
    diagnostic_overrides+=("$candidate")
}

classify_diagnostic_override() {
    local argument=${1,,}
    local compact=${argument//[[:space:]]/}
    case $compact in
        *-faysceneonly=1*) add_diagnostic_override scene-only ;;
    esac
    case $compact in
        *showflag.hair=0*|*showflag.hair0*|*r.hairstrands.enable=0*|*r.hairstrands.enable0*|*r.hairstrands.strands=0*|*r.hairstrands.strands0*)
            add_diagnostic_override hair-rendering-disabled
            ;;
    esac
    case $compact in
        *r.hairstrands.simulation=0*|*r.hairstrands.simulation0*|*r.groom.enable=0*|*r.groom.enable0*|*showflag.groom=0*|*showflag.groom0*)
            add_diagnostic_override groom-simulation-disabled
            ;;
    esac
    case $compact in
        *showflag.skeletalmeshes=0*|*showflag.skeletalmeshes0*|*showflag.animation=0*|*showflag.animation0*|*disablefaceoverride=true*|*disablefaceoverride=1*)
            add_diagnostic_override face-rendering-disabled
            ;;
    esac
    case $compact in
        *faylivelinkhealthinterval=*|*faylivelinkidleheartbeat=*)
            add_diagnostic_override livelink-health-override
            ;;
    esac
    case $compact in
        *-trace=memory*|*-trace=memalloc*|*-tracefile=*|*-tracefiletrunc*)
            add_diagnostic_override full-memory-tracing
            ;;
    esac
    case $compact in
        *r.scenerender.cleanupmode=*|*r.scenerender.cleanupmode[0-9]*|\
        *r.vulkan.allowsplitbarriers=*|*r.vulkan.allowsplitbarriers[0-9]*|\
        *r.shadowquality=*|*r.shadowquality[0-9]*|\
        *showflag.dynamicshadows=0*|*showflag.dynamicshadows0*|\
        *r.skincache.mode=*|*r.skincache.mode[0-9]*)
            add_diagnostic_override renderer-policy-override
            ;;
    esac
}

if (( scene_only == 1 )); then
    add_diagnostic_override scene-only
fi
if (( enable_csv == 1 )); then
    add_diagnostic_override csv-profiling
fi
if (( res_x != 1280 || res_y != 720 )); then
    add_diagnostic_override resolution-override
fi
if (( avatar_dormancy == 1 && avatar_dormancy_delay != 5 )); then
    add_diagnostic_override dormancy-policy-override
fi
if (( max_dormancy_cancellations != 0 )); then
    add_diagnostic_override dormancy-cancellation-override
fi
if (( max_tail_rss_growth_kb != 131072 ||
    (turn_count > 0 && max_rss_kb != 3145728) ||
    min_mem_available_kb != 50331648 ||
    max_gpu_utilization_percent != 95 ||
    min_start_available_memory_gib != 48 ||
    max_start_gpu_utilization != 85 )); then
    add_diagnostic_override resource-policy-override
fi
if ! awk -v observed="$max_face_p95_ms" 'BEGIN {exit !(observed == 20)}'; then
    add_diagnostic_override facial-performance-policy-override
fi
if (( $# != 0 )); then
    add_diagnostic_override extra-unreal-arguments
fi
for argument in "$@"; do
    classify_diagnostic_override "$argument"
    case "${argument,,}" in
        -nullrhi|-resx=*|-resy=*|-csvcaptureframes=*|-csvcompression=*|-faycameraframing=*|-faysceneonly|-faysceneonly=*|-fayavatardormancy|-fayavatardormancy=*|-fayavatardormancydelay=*)
            fail 'the soak runner owns RHI, resolution, camera framing, CSV, scene-only, and dormancy arguments'
            ;;
    esac
done
if [[ -z $evidence_mode ]]; then
    if (( turn_count == 0 || scene_only == 1 || ${#diagnostic_overrides[@]} != 0 )); then
        evidence_mode=diagnostic
    else
        evidence_mode=production
    fi
fi
if [[ $evidence_mode == production && ${#diagnostic_overrides[@]} -ne 0 ]]; then
    fail "production qualification refuses policy override: ${diagnostic_overrides[*]}"
fi
if [[ $evidence_mode == production && ( $turn_count == 0 || $scene_only == 1 ) ]]; then
    fail 'production qualification requires at least one turn and a real avatar scene'
fi

runtime_log="$package_launcher_dir/FayAvatarRuntime/Saved/Logs/FayAvatarRuntime.log"
csv_profile_root="$package_launcher_dir/FayAvatarRuntime/Saved/Profiling/CSV"
csv_analyzer="$script_dir/../tools/analyze-unreal-csv.py"
if (( enable_csv == 1 )); then
    [[ -x $csv_analyzer && ! -L $csv_analyzer ]] || \
        fail 'the guarded Unreal CSV analyzer is missing or unsafe'
fi
runtime_log_prelaunch_identity=missing
if [[ -f $runtime_log ]]; then
    runtime_log_prelaunch_identity=$(stat -c '%d:%i:%s:%y' "$runtime_log")
fi
launcher_log="$output_dir/launcher.log"

find_runtime_pids() {
    local process_dir process_exe
    for process_dir in /proc/[1-9]*; do
        process_exe=$(readlink "$process_dir/exe" 2>/dev/null || true)
        if [[ $process_exe == "$expected_unreal_exe" ]]; then
            printf '%s\n' "${process_dir##*/}"
        fi
    done
}

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
    local pid=$1 expected_exe=$2 expected_starttime=$3
    local actual_exe actual_starttime
    actual_exe=$(readlink "/proc/$pid/exe" 2>/dev/null || true)
    [[ $actual_exe == "$expected_exe" ]] || return 1
    actual_starttime=$(read_process_starttime "$pid" || true)
    [[ -n $actual_starttime && $actual_starttime == "$expected_starttime" ]]
}

listener_owned_by_fay() {
    local port=$1 listeners
    process_matches_identity "$fay_pid" "$fay_exe" "$fay_starttime" || return 1
    listeners=$(ss -H -ltnp "sport = :$port" 2>/dev/null || true)
    [[ $listeners == *"pid=$fay_pid,"* ]]
}

fay_listener_host() {
    local port=$1 listeners endpoint host
    listeners=$(ss -H -ltnp "sport = :$port" 2>/dev/null || true)
    endpoint=$(awk -v owner="pid=$fay_pid," '$0 ~ owner {print $4; exit}' <<<"$listeners")
    [[ -n $endpoint ]] || return 1
    host=${endpoint%:"$port"}
    host=${host#[}
    host=${host%]}
    [[ -n $host && $host != \* && $host != 0.0.0.0 && $host != :: ]] || return 1
    printf '%s\n' "$host"
}

url_host() {
    if [[ $1 == *:* ]]; then
        printf '[%s]' "$1"
    else
        printf '%s' "$1"
    fi
}

fay_http_ready() {
    local port=$1 path=$2 host formatted_host code
    process_matches_identity "$fay_pid" "$fay_exe" "$fay_starttime" || return 1
    host=$(fay_listener_host "$port") || return 1
    formatted_host=$(url_host "$host")
    code=$(curl --silent --show-error --output /dev/null --noproxy '*' \
        --connect-timeout 2 --max-time 5 --write-out '%{http_code}' \
        "http://$formatted_host:$port$path" 2>/dev/null || true)
    [[ $code =~ ^[23][0-9][0-9]$ ]] || return 1
    process_matches_identity "$fay_pid" "$fay_exe" "$fay_starttime"
}

mapfile -t existing_runtime_pids < <(find_runtime_pids)
(( ${#existing_runtime_pids[@]} == 0 )) || \
    fail 'the selected package already has a running Unreal process'
fay_exe=$(readlink "/proc/$fay_pid/exe" 2>/dev/null || true)
fay_starttime=$(read_process_starttime "$fay_pid" || true)
[[ $fay_exe == */python* && -n $fay_starttime ]] || \
    fail 'FAY_PID is not a stable Python process before launch'
process_matches_identity "$fay_pid" "$fay_exe" "$fay_starttime" || \
    fail 'FAY_PID changed identity during preflight'
for fay_port in 5000 5010 8766 10002; do
    listener_owned_by_fay "$fay_port" || \
        fail "FAY_PID does not own required listener $fay_port before launch"
done
"$package_verifier" "$package_launcher_dir"
preflight_package_seal="$package_launcher_dir/.ue5-spark-package.sha256"
[[ -s $preflight_package_seal && ! -L $preflight_package_seal ]] || \
    fail 'the preflight package seal is missing or unsafe'
preflight_package_seal_sha256=$(sha256sum -- "$preflight_package_seal")
preflight_package_seal_sha256=${preflight_package_seal_sha256%% *}
process_matches_identity "$fay_pid" "$fay_exe" "$fay_starttime" || \
    fail 'Fay changed identity during package preflight verification'
kernel_cursor=$(journalctl -k -n 0 --show-cursor --no-pager 2>/dev/null |
    sed -n 's/^-- cursor: //p' | tail -n1)
[[ -n $kernel_cursor ]] || fail 'could not capture the pre-launch kernel journal cursor'

launcher_pid=''
launcher_exe=''
launcher_starttime=''
launcher_env_exe=''
launcher_bash_exe=''
launcher_reached_unreal=0
launcher_reaped=0
launcher_identity_capture_in_progress=0
deferred_signal_name=''
deferred_signal_status=0
runtime_pid=''
runtime_exe=''
runtime_starttime=''
runtime_reaped=0
runtime_exit_status=not-reaped
runtime_forced_kill=0
inner_pid=''
inner_exe=''
inner_starttime=''
inner_session_id=''
inner_reaped=0
inner_exit_status=not-started
postflight_package_seal_sha256=not-verified
post_teardown_runtime_failure_count=not-scanned
post_teardown_kernel_failure_count=not-scanned
cleanup_completed=0
csv_prelaunch_identity_file=''

process_matches_starttime() {
    local pid=$1 expected_starttime=$2 actual_starttime
    actual_starttime=$(read_process_starttime "$pid" || true)
    [[ -n $actual_starttime && $actual_starttime == "$expected_starttime" ]]
}

process_is_live_with_starttime() {
    local pid=$1 expected_starttime=$2 stat_line stat_fields
    process_matches_starttime "$pid" "$expected_starttime" || return 1
    IFS= read -r stat_line <"/proc/$pid/stat" || return 1
    stat_fields=${stat_line##*) }
    [[ $stat_fields != "$stat_line" ]] || return 1
    set -- $stat_fields
    [[ -n ${1:-} && ${1:-} != Z ]]
}

observe_allowed_launcher_transition() {
    local current_exe current_starttime
    [[ -n $launcher_pid && -n $launcher_starttime &&
        -n $launcher_env_exe && -n $launcher_bash_exe ]] || return 1
    current_starttime=$(read_process_starttime "$launcher_pid" || true)
    [[ -n $current_starttime && $current_starttime == "$launcher_starttime" ]] || return 1
    current_exe=$(readlink "/proc/$launcher_pid/exe" 2>/dev/null || true)
    [[ -n $current_exe ]] || return 1
    if [[ $current_exe == "$expected_unreal_exe" ]]; then
        launcher_exe=$current_exe
        launcher_reached_unreal=1
        return 0
    fi
    if (( launcher_reached_unreal == 0 )) &&
        [[ $current_exe == "$launcher_env_exe" ||
        $current_exe == "$launcher_bash_exe" ]]; then
        launcher_exe=$current_exe
        return 0
    fi
    return 2
}

promote_expected_launcher_transition() {
    local observation_status
    [[ -z $runtime_pid && -n $launcher_pid &&
        -n $launcher_starttime ]] || return 0
    if observe_allowed_launcher_transition; then
        observation_status=0
    else
        observation_status=$?
    fi
    if (( observation_status == 1 )); then
        return 0
    fi
    if (( observation_status == 2 )); then
        printf 'error: guarded launcher changed to an unexpected executable\n' >&2
        return 1
    fi
    if (( launcher_reached_unreal == 1 )); then
        runtime_exe=$expected_unreal_exe
        runtime_starttime=$launcher_starttime
        runtime_pid=$launcher_pid
    fi
    return 0
}

reap_inner_harness() {
    local wait_status
    (( inner_reaped == 0 )) || return 0
    set +e
    wait "$inner_pid"
    wait_status=$?
    set -e
    inner_exit_status=$wait_status
    inner_reaped=1
}

cancel_inner_harness() {
    local group_alive=0 discovered_session
    [[ -n $inner_pid ]] || return 0
    (( inner_reaped == 0 )) || return 0
    if [[ -z $inner_session_id ]]; then
        discovered_session=$(ps -o sid= -p "$inner_pid" 2>/dev/null | tr -d ' ' || true)
        if [[ $discovered_session == "$inner_pid" ]]; then
            inner_session_id=$discovered_session
        fi
    fi
    if [[ -n $inner_session_id ]] && kill -0 -- "-$inner_session_id" 2>/dev/null; then
        group_alive=1
        kill -TERM -- "-$inner_session_id" 2>/dev/null || true
    elif [[ -n $inner_exe && -n $inner_starttime ]] &&
        process_matches_identity "$inner_pid" "$inner_exe" "$inner_starttime"; then
        kill -TERM "$inner_pid" 2>/dev/null || true
    else
        # This PID is an unreaped direct child, so the kernel cannot have reused
        # it even if interruption arrived before /proc metadata was captured.
        kill -TERM "$inner_pid" 2>/dev/null || true
    fi
    for _ in $(seq 1 10); do
        if (( group_alive == 1 )); then
            kill -0 -- "-$inner_session_id" 2>/dev/null || break
        elif ! process_matches_identity "$inner_pid" "$inner_exe" "$inner_starttime"; then
            break
        fi
        sleep 1
    done
    if (( group_alive == 1 )) && kill -0 -- "-$inner_session_id" 2>/dev/null; then
        kill -KILL -- "-$inner_session_id" 2>/dev/null || true
    elif (( group_alive == 0 )) && [[ -n $inner_exe && -n $inner_starttime ]] &&
        process_matches_identity "$inner_pid" "$inner_exe" "$inner_starttime"; then
        kill -KILL "$inner_pid" 2>/dev/null || true
    fi
    for _ in $(seq 1 5); do
        if (( group_alive == 1 )); then
            kill -0 -- "-$inner_session_id" 2>/dev/null || break
        elif ! process_matches_identity "$inner_pid" "$inner_exe" "$inner_starttime"; then
            break
        fi
        sleep 1
    done
    if ! process_matches_identity "$inner_pid" "$inner_exe" "$inner_starttime"; then
        reap_inner_harness
    fi
    if (( group_alive == 1 )) && kill -0 -- "-$inner_session_id" 2>/dev/null; then
        inner_exit_status=kill-timeout
        return 1
    fi
    if (( group_alive == 0 )) && [[ -n $inner_exe && -n $inner_starttime ]] &&
        process_matches_identity "$inner_pid" "$inner_exe" "$inner_starttime"; then
        inner_exit_status=kill-timeout
        return 1
    fi
    reap_inner_harness
}

capture_post_teardown_evidence() {
    local temporary_runtime temporary_kernel runtime_failure_pattern kernel_failure_pattern
    [[ -n ${current_launch_start:-} && -f $runtime_log ]] || return 1
    temporary_runtime=$(mktemp "$output_dir/.runtime-new.post-teardown.XXXXXX")
    temporary_kernel=$(mktemp "$output_dir/.kernel-new.post-teardown.XXXXXX")
    if ! tail -n "+$current_launch_start" "$runtime_log" >"$temporary_runtime"; then
        rm -f -- "$temporary_runtime" "$temporary_kernel"
        return 1
    fi
    if ! journalctl -k --after-cursor "$kernel_cursor" --no-pager >"$temporary_kernel"; then
        rm -f -- "$temporary_runtime" "$temporary_kernel"
        return 1
    fi
    mv -f -- "$temporary_runtime" "$output_dir/runtime-new.log"
    mv -f -- "$temporary_kernel" "$output_dir/kernel-new.log"
    runtime_failure_pattern='Fatal error|Assertion failed|Out of memory|GPU Crashed|VK_ERROR_DEVICE_LOST|LogVulkanRHI: Error|queue overflow|LogFay[^:]*: Error'
    kernel_failure_pattern='NVRM: Xid|CTX SWITCH TIMEOUT|NV_ERR_NO_MEMORY|GPU has fallen off the bus'
    grep -Ein "$runtime_failure_pattern" "$output_dir/runtime-new.log" \
        >"$output_dir/runtime-failures.log" || true
    grep -Ein "$kernel_failure_pattern" "$output_dir/kernel-new.log" \
        >"$output_dir/kernel-failures.log" || true
    post_teardown_runtime_failure_count=$(wc -l <"$output_dir/runtime-failures.log")
    post_teardown_kernel_failure_count=$(wc -l <"$output_dir/kernel-failures.log")
    (( post_teardown_runtime_failure_count == 0 && post_teardown_kernel_failure_count == 0 ))
}

record_teardown_metadata() {
    local summary="$output_dir/soak-summary.txt" temporary_summary
    [[ -f $summary && ! -L $summary ]] || return 0
    temporary_summary=$(mktemp "$output_dir/.soak-summary.teardown.XXXXXX")
    if ! sed \
        -e "s/^runtime_exit_status=pending$/runtime_exit_status=$runtime_exit_status/" \
        -e "s/^runtime_forced_kill=pending$/runtime_forced_kill=$runtime_forced_kill/" \
        -e "s/^post_teardown_package_seal_sha256=pending$/post_teardown_package_seal_sha256=$postflight_package_seal_sha256/" \
        -e "s/^post_teardown_runtime_failure_count=pending$/post_teardown_runtime_failure_count=$post_teardown_runtime_failure_count/" \
        -e "s/^post_teardown_kernel_failure_count=pending$/post_teardown_kernel_failure_count=$post_teardown_kernel_failure_count/" \
        "$summary" >"$temporary_summary"; then
        rm -f -- "$temporary_summary"
        return 1
    fi
    mv -f -- "$temporary_summary" "$summary"
}

cleanup_runtime() {
    local require_recorded_runtime=${1:-0}
    local cleanup_status=0 wait_status
    [[ $require_recorded_runtime =~ ^[01]$ ]] || \
        fail 'internal cleanup mode must be 0 or 1'
    cancel_inner_harness || cleanup_status=1
    promote_expected_launcher_transition || cleanup_status=1
    if [[ -n $runtime_pid && -n $runtime_exe && -n $runtime_starttime ]] &&
        process_matches_identity "$runtime_pid" "$runtime_exe" "$runtime_starttime"; then
        kill -TERM "$runtime_pid" 2>/dev/null || true
        for _ in $(seq 1 30); do
            if ! process_matches_identity \
                "$runtime_pid" "$runtime_exe" "$runtime_starttime"; then
                break
            fi
            sleep 1
        done
        if process_matches_identity "$runtime_pid" "$runtime_exe" "$runtime_starttime"; then
            printf 'error: Unreal required KILL after the 30-second TERM grace period\n' >&2
            runtime_forced_kill=1
            cleanup_status=1
            kill -KILL "$runtime_pid" 2>/dev/null || true
            for _ in $(seq 1 10); do
                if ! process_matches_identity \
                    "$runtime_pid" "$runtime_exe" "$runtime_starttime"; then
                    break
                fi
                sleep 1
            done
            if process_matches_identity "$runtime_pid" "$runtime_exe" "$runtime_starttime"; then
                printf 'error: Unreal survived identity-checked KILL\n' >&2
                cleanup_status=1
            fi
        fi
    elif (( require_recorded_runtime == 1 )); then
        printf 'error: the recorded Unreal identity disappeared before controlled teardown\n' >&2
        cleanup_status=1
    fi
    if [[ -n $launcher_pid && $launcher_pid == "$runtime_pid" &&
        $runtime_reaped == 0 ]] &&
        ! process_matches_identity "$runtime_pid" "$runtime_exe" "$runtime_starttime"; then
        set +e
        wait "$launcher_pid"
        wait_status=$?
        set -e
        runtime_exit_status=$wait_status
        runtime_reaped=1
        if (( require_recorded_runtime == 1 && wait_status != 0 && wait_status != 143 )); then
            printf 'error: Unreal exited with unexpected status %s during teardown\n' \
                "$wait_status" >&2
            cleanup_status=1
        fi
    elif [[ -n $launcher_pid && -n $launcher_starttime &&
        $launcher_pid != "$runtime_pid" && $launcher_reaped == 0 ]]; then
        local launcher_observation_status=0
        if observe_allowed_launcher_transition; then
            launcher_observation_status=0
        else
            launcher_observation_status=$?
            if (( launcher_observation_status == 2 )); then
                printf 'error: the owned launcher entered an unexpected executable state\n' >&2
                cleanup_status=1
            fi
        fi
        # Recheck the recorded direct-child PID/start-time identity rather than
        # pinning cleanup to a transient env/bash executable that may
        # legitimately change between observation and delivery of TERM.
        if process_is_live_with_starttime "$launcher_pid" "$launcher_starttime"; then
            kill -TERM "$launcher_pid" 2>/dev/null || true
        fi
        for _ in $(seq 1 5); do
            if ! process_is_live_with_starttime \
                "$launcher_pid" "$launcher_starttime"; then
                break
            fi
            sleep 1
        done
        if process_is_live_with_starttime \
            "$launcher_pid" "$launcher_starttime"; then
            kill -KILL "$launcher_pid" 2>/dev/null || true
            cleanup_status=1
        fi
        for _ in $(seq 1 5); do
            process_is_live_with_starttime \
                "$launcher_pid" "$launcher_starttime" || break
            sleep 1
        done
        if process_is_live_with_starttime \
            "$launcher_pid" "$launcher_starttime"; then
            printf 'error: the owned launcher survived identity-checked KILL\n' >&2
            cleanup_status=1
        else
            set +e
            wait "$launcher_pid"
            wait_status=$?
            set -e
            launcher_reaped=1
        fi
    fi
    mapfile -t remaining_runtime_pids < <(find_runtime_pids)
    if (( ${#remaining_runtime_pids[@]} != 0 )); then
        printf 'error: a project-owned Unreal process remains after teardown\n' >&2
        cleanup_status=1
    fi
    if ! process_matches_identity "$fay_pid" "$fay_exe" "$fay_starttime"; then
        printf 'error: the externally managed Fay process changed identity during the soak\n' >&2
        cleanup_status=1
    fi
    for port in 5000 5010 8766 10002; do
        if ! listener_owned_by_fay "$port"; then
            printf 'error: Fay no longer owns required port %s\n' "$port" >&2
            cleanup_status=1
        fi
    done
    if ! fay_http_ready 5000 / || ! fay_http_ready 5010 / || ! fay_http_ready 8766 /sse; then
        printf 'error: Fay failed a post-teardown HTTP health probe\n' >&2
        cleanup_status=1
    fi
    if [[ -f $output_dir/soak-summary.txt ]]; then
        if ! capture_post_teardown_evidence; then
            printf 'error: post-teardown runtime or kernel evidence failed validation\n' >&2
            cleanup_status=1
        fi
    fi
    if ! "$package_verifier" "$package_launcher_dir"; then
        cleanup_status=1
    else
        postflight_package_seal_sha256=$(sha256sum -- "$preflight_package_seal")
        postflight_package_seal_sha256=${postflight_package_seal_sha256%% *}
        if [[ $postflight_package_seal_sha256 != "$preflight_package_seal_sha256" ]]; then
            printf 'error: the package seal identity changed during the soak\n' >&2
            cleanup_status=1
        fi
    fi
    record_teardown_metadata || cleanup_status=1
    cleanup_completed=1
    return "$cleanup_status"
}

finalize_evidence_summary() {
    local summary="$output_dir/soak-summary.txt"
    local temporary_summary finalized_record
    [[ -f $summary && ! -L $summary ]] || \
        fail 'the soak summary is missing or unsafe after verified teardown'
    [[ $(grep -Fxc 'status=passed' "$summary") == 1 ]] || \
        fail 'the soak summary did not preserve exactly one passing harness status'
    if [[ $evidence_mode == production ]]; then
        [[ $(grep -Fxc \
            'production_qualification=pending-verified-teardown-and-seal' \
            "$summary") == 1 ]] || \
            fail 'the production summary is not awaiting verified teardown'
    else
        [[ $(grep -Fxc 'production_qualification=not-claimed' "$summary") == 1 ]] || \
            fail 'the diagnostic summary attempted to claim production qualification'
    fi
    temporary_summary=$(mktemp "$output_dir/.soak-summary.finalizing.XXXXXX")
    if ! sed \
        -e 's/^production_qualification=pending-verified-teardown-and-seal$/production_qualification=passed/' \
        -e 's/^result_scope=production-candidate-awaiting-verified-teardown-and-seal$/result_scope=production-qualification/' \
        -e 's/^verified_teardown_and_fay_survival=pending$/verified_teardown_and_fay_survival=passed/' \
        -e 's/^verified_teardown_and_fay_survival=not-verified-by-inner-harness$/verified_teardown_and_fay_survival=passed/' \
        -e 's/^post_teardown_package_verification=pending$/post_teardown_package_verification=passed/' \
        -e 's/^post_teardown_package_verification=not-verified-by-inner-harness$/post_teardown_package_verification=passed/' \
        -e "s/^runtime_exit_status=pending$/runtime_exit_status=$runtime_exit_status/" \
        -e "s/^runtime_forced_kill=pending$/runtime_forced_kill=$runtime_forced_kill/" \
        -e "s/^post_teardown_package_seal_sha256=pending$/post_teardown_package_seal_sha256=$postflight_package_seal_sha256/" \
        -e "s/^post_teardown_runtime_failure_count=pending$/post_teardown_runtime_failure_count=$post_teardown_runtime_failure_count/" \
        -e "s/^post_teardown_kernel_failure_count=pending$/post_teardown_kernel_failure_count=$post_teardown_kernel_failure_count/" \
        "$summary" >"$temporary_summary"; then
        rm -f -- "$temporary_summary"
        fail 'could not finalize the verified soak summary'
    fi
    if [[ $evidence_mode == production ]]; then
        [[ $(grep -Fxc 'production_qualification=passed' "$temporary_summary") == 1 ]] || {
            rm -f -- "$temporary_summary"
            fail 'the production qualification result could not be finalized'
        }
    fi
    [[ $(grep -Fxc 'verified_teardown_and_fay_survival=passed' \
        "$temporary_summary") == 1 ]] || {
        rm -f -- "$temporary_summary"
        fail 'the verified teardown result could not be finalized'
    }
    [[ $(grep -Fxc 'post_teardown_package_verification=passed' \
        "$temporary_summary") == 1 ]] || {
        rm -f -- "$temporary_summary"
        fail 'the post-teardown package result could not be finalized'
    }
    for finalized_record in \
        "runtime_exit_status=$runtime_exit_status" \
        "runtime_forced_kill=0" \
        "post_teardown_package_seal_sha256=$postflight_package_seal_sha256" \
        "post_teardown_runtime_failure_count=0" \
        "post_teardown_kernel_failure_count=0"; do
        [[ $(grep -Fxc "$finalized_record" "$temporary_summary") == 1 ]] || {
            rm -f -- "$temporary_summary"
            fail "the finalized summary is missing: $finalized_record"
        }
    done
    mv -f -- "$temporary_summary" "$summary"
}

validate_csv_evidence() {
    local csv_source csv_source_sha256 csv_source_sha256_after csv_copy_sha256
    local candidate candidate_identity temporary_csv temporary_analysis
    local temporary_summary summary
    local csv_evidence="$output_dir/unreal-csv-profile.csv"
    local csv_analysis="$output_dir/unreal-csv-analysis.json"
    local csv_min_used_frames=$((
        csv_capture_frames - csv_trim_start_frames - csv_trim_end_frames
    ))
    local -a all_csv_captures new_csv_captures

    [[ -n $csv_prelaunch_identity_file && -f $csv_prelaunch_identity_file &&
        ! -L $csv_prelaunch_identity_file ]] || \
        fail 'the guarded CSV prelaunch identity record is missing or unsafe'
    [[ -d $csv_profile_root && ! -L $csv_profile_root ]] || \
        fail 'Unreal did not create a safe CSVProfiler output directory'
    mapfile -d '' -t all_csv_captures < <(
        find "$csv_profile_root" -maxdepth 1 -type f -name 'Profile*.csv' \
            -print0
    )
    new_csv_captures=()
    for candidate in "${all_csv_captures[@]}"; do
        candidate_identity=$(stat -c '%d:%i' "$candidate")
        if ! grep -Fqx -- "$candidate_identity" "$csv_prelaunch_identity_file"; then
            new_csv_captures+=("$candidate")
        fi
    done
    (( ${#new_csv_captures[@]} == 1 )) || \
        fail "expected exactly one new Unreal CSV capture; found ${#new_csv_captures[@]}"
    csv_source=${new_csv_captures[0]}
    [[ -f $csv_source && ! -L $csv_source && -O $csv_source ]] || \
        fail 'the new Unreal CSV capture is missing, linked, or not user-owned'
    [[ ! -e $csv_evidence && ! -L $csv_evidence &&
        ! -e $csv_analysis && ! -L $csv_analysis ]] || \
        fail 'private CSV evidence destinations already exist'

    csv_source_sha256=$(sha256sum -- "$csv_source")
    csv_source_sha256=${csv_source_sha256%% *}
    temporary_csv=$(mktemp "$output_dir/.unreal-csv-profile.XXXXXX")
    cp -- "$csv_source" "$temporary_csv"
    chmod 600 "$temporary_csv"
    csv_copy_sha256=$(sha256sum -- "$temporary_csv")
    csv_copy_sha256=${csv_copy_sha256%% *}
    csv_source_sha256_after=$(sha256sum -- "$csv_source")
    csv_source_sha256_after=${csv_source_sha256_after%% *}
    if [[ $csv_source_sha256 != "$csv_copy_sha256" ||
        $csv_source_sha256 != "$csv_source_sha256_after" ]]; then
        rm -f -- "$temporary_csv"
        fail 'the Unreal CSV capture changed while private evidence was copied'
    fi
    if ! ln -- "$temporary_csv" "$csv_evidence"; then
        rm -f -- "$temporary_csv"
        fail 'could not publish the private Unreal CSV without clobbering'
    fi
    rm -f -- "$temporary_csv"

    temporary_analysis=$(mktemp "$output_dir/.unreal-csv-analysis.XXXXXX")
    if ! python3 "$csv_analyzer" "$csv_evidence" \
        --trim-start "$csv_trim_start_frames" \
        --trim-end "$csv_trim_end_frames" \
        --min-used-frames "$csv_min_used_frames" \
        --expected-total-frames "$csv_capture_frames" \
        --min-average-fps "$csv_min_average_fps" \
        --max-average-fps "$csv_max_average_fps" \
        --max-p95-frame-time-ms "$csv_max_p95_frame_time_ms" \
        --require-capture-duration >"$temporary_analysis"; then
        rm -f -- "$temporary_analysis"
        fail 'the measured Unreal CSV performance acceptance gate failed'
    fi
    chmod 600 "$temporary_analysis"
    if ! ln -- "$temporary_analysis" "$csv_analysis"; then
        rm -f -- "$temporary_analysis"
        fail 'could not publish the private CSV analysis without clobbering'
    fi
    rm -f -- "$temporary_analysis"

    summary="$output_dir/soak-summary.txt"
    [[ -f $summary && ! -L $summary ]] || \
        fail 'the soak summary is unavailable for CSV evidence binding'
    temporary_summary=$(mktemp "$output_dir/.soak-summary.csv.XXXXXX")
    cp -- "$summary" "$temporary_summary"
    {
        printf 'csv_performance_validation=passed\n'
        printf 'csv_capture_file=unreal-csv-profile.csv\n'
        printf 'csv_analysis_file=unreal-csv-analysis.json\n'
        printf 'csv_capture_sha256=%s\n' "$csv_source_sha256"
        printf 'csv_capture_requested_frames=%s\n' "$csv_capture_frames"
        printf 'csv_trim_start_frames=%s\n' "$csv_trim_start_frames"
        printf 'csv_trim_end_frames=%s\n' "$csv_trim_end_frames"
        printf 'csv_min_average_fps=%s\n' "$csv_min_average_fps"
        printf 'csv_max_average_fps=%s\n' "$csv_max_average_fps"
        printf 'csv_max_p95_frame_time_ms=%s\n' \
            "$csv_max_p95_frame_time_ms"
    } >>"$temporary_summary"
    mv -f -- "$temporary_summary" "$summary"
    rm -f -- "$csv_prelaunch_identity_file"
    csv_prelaunch_identity_file=''
}

handle_exit() {
    local original_status=$? cleanup_status=0
    if (( cleanup_completed == 0 )); then
        cleanup_runtime 0 || cleanup_status=$?
    fi
    if (( original_status == 0 && cleanup_status != 0 )); then
        original_status=$cleanup_status
    fi
    exit "$original_status"
}
handle_signal() {
    local signal_name=$1 exit_status=$2
    if (( launcher_identity_capture_in_progress == 1 )); then
        if (( deferred_signal_status == 0 )); then
            deferred_signal_name=$signal_name
            deferred_signal_status=$exit_status
            printf 'Deferring %s until the owned launcher identity is committed.\n' \
                "$signal_name" >&2
        fi
        return 0
    fi
    trap - HUP INT TERM
    printf 'error: interrupted by %s; cancelling owned children and tearing down Unreal\n' \
        "$signal_name" >&2
    exit "$exit_status"
}
trap handle_exit EXIT
trap 'handle_signal HUP 129' HUP
trap 'handle_signal INT 130' INT
trap 'handle_signal TERM 143' TERM

runtime_arguments=(
    "-FayCharacter=$character"
    "-FayCameraFraming=$camera_framing"
    -FayResetSpeechCache=0
    -FayTrimSpeechMemory=1
    "-ResX=$res_x" "-ResY=$res_y" -Windowed -WinX=0 -WinY=0
)
if [[ $scene_only == 1 ]]; then
    runtime_arguments+=("-FaySceneOnly=1")
fi
if [[ $avatar_dormancy == 1 ]]; then
    runtime_arguments+=(
        "-FayAvatarDormancy=1"
        "-FayAvatarDormancyDelay=$avatar_dormancy_delay"
    )
fi
if [[ $enable_csv == 1 ]]; then
    runtime_arguments+=(
        "-csvCaptureFrames=$csv_capture_frames"
        "-csvCompression=$csv_compression"
    )
    csv_prelaunch_identity_file="$output_dir/.csv-prelaunch-identities"
    [[ ! -e $csv_prelaunch_identity_file &&
        ! -L $csv_prelaunch_identity_file ]] || \
        fail 'the private CSV prelaunch identity record already exists'
    : >"$csv_prelaunch_identity_file"
    chmod 600 "$csv_prelaunch_identity_file"
    if [[ -e $csv_profile_root ]]; then
        [[ -d $csv_profile_root && ! -L $csv_profile_root ]] || \
            fail 'the existing CSVProfiler output directory is unsafe'
        while IFS= read -r -d '' existing_csv_capture; do
            stat -c '%d:%i' "$existing_csv_capture" \
                >>"$csv_prelaunch_identity_file"
        done < <(find "$csv_profile_root" -maxdepth 1 -type f \
            -name 'Profile*.csv' -print0)
    fi
fi
export UE5_SPARK_MIN_AVAILABLE_MEMORY_GIB="$min_start_available_memory_gib"
export UE5_SPARK_MAX_START_GPU_UTILIZATION="$max_start_gpu_utilization"
launcher_env_exe=$(readlink -f /usr/bin/env)
launcher_bash_exe=$(readlink -f "$(command -v bash)")
[[ -x $launcher_env_exe && -x $launcher_bash_exe ]] || \
    fail 'could not resolve the reviewed launcher interpreters'
launcher_identity_capture_in_progress=1
"$launcher_bash_exe" "$digital_human_launcher" "$package_launcher" \
    "${runtime_arguments[@]}" "$@" >"$launcher_log" 2>&1 &
launcher_pid=$!
launcher_exe=$launcher_bash_exe
launcher_identity_stable=0
for _ in $(seq 1 50); do
    launcher_starttime=$(read_process_starttime "$launcher_pid" || true)
    [[ -n $launcher_starttime ]] && break
    sleep 0.1 || true
done
if [[ -n $launcher_starttime ]]; then
    # The reviewed script chain can exec bash -> env -> bash -> Unreal while
    # retaining one PID/start time. Executable is policy state, not ownership.
    for _ in $(seq 1 50); do
        if observe_allowed_launcher_transition; then
            launcher_identity_stable=1
            break
        else
            launcher_observation_status=$?
        fi
        if (( launcher_observation_status == 2 )); then
            break
        fi
        sleep 0.1 || true
    done
fi
launcher_identity_capture_in_progress=0
if (( deferred_signal_status != 0 )); then
    handle_signal "$deferred_signal_name" "$deferred_signal_status"
fi
if (( launcher_identity_stable == 0 )); then
    fail 'could not establish the guarded launcher process identity'
fi

for _ in $(seq 1 90); do
    mapfile -t discovered_runtime_pids < <(find_runtime_pids)
    if (( ${#discovered_runtime_pids[@]} > 1 )); then
        fail 'more than one matching Unreal process appeared during launch'
    fi
    if (( ${#discovered_runtime_pids[@]} == 1 )); then
        discovered_runtime_pid=${discovered_runtime_pids[0]}
        discovered_runtime_exe=$(readlink "/proc/$discovered_runtime_pid/exe" 2>/dev/null || true)
        discovered_runtime_starttime=$(read_process_starttime "$discovered_runtime_pid" || true)
        if [[ $discovered_runtime_exe != "$expected_unreal_exe" ||
            -z $discovered_runtime_starttime ]] ||
            ! process_matches_identity \
                "$discovered_runtime_pid" "$discovered_runtime_exe" \
                "$discovered_runtime_starttime"; then
            sleep 1
            continue
        fi
        if [[ $launcher_pid != "$discovered_runtime_pid" ||
            $launcher_starttime != "$discovered_runtime_starttime" ]]; then
            fail 'the guarded launcher did not exec Unreal with the same PID and start time'
        fi
        runtime_exe=$discovered_runtime_exe
        runtime_starttime=$discovered_runtime_starttime
        runtime_pid=$discovered_runtime_pid
        launcher_exe=$runtime_exe
        launcher_reached_unreal=1
        break
    fi
    if observe_allowed_launcher_transition; then
        :
    else
        launcher_observation_status=$?
        if (( launcher_observation_status == 2 )); then
            fail "the guarded launcher entered an unexpected executable; inspect $launcher_log"
        fi
        if ! process_is_live_with_starttime "$launcher_pid" "$launcher_starttime"; then
            fail "the guarded launcher exited before Unreal started; inspect $launcher_log"
        fi
    fi
    if (( launcher_reached_unreal == 1 )) &&
        ! process_matches_identity \
            "$launcher_pid" "$expected_unreal_exe" "$launcher_starttime"; then
        fail "the guarded launcher exited before Unreal started; inspect $launcher_log"
    fi
    sleep 1
done
[[ -n $runtime_pid ]] || fail 'Unreal did not start within 90 seconds'

runtime_ready=0
for _ in $(seq 1 90); do
    process_matches_identity "$runtime_pid" "$runtime_exe" "$runtime_starttime" || \
        fail "Unreal exited during readiness; inspect $launcher_log"
    if [[ -f $runtime_log ]]; then
        runtime_log_identity=$(stat -c '%d:%i:%s:%y' "$runtime_log")
        if [[ $runtime_log_identity != "$runtime_log_prelaunch_identity" ]]; then
            latest_log_open=$(grep -n 'Log file open,' "$runtime_log" | tail -n1 || true)
            current_launch_start=${latest_log_open%%:*}
            if [[ $current_launch_start =~ ^[1-9][0-9]*$ ]]; then
                current_launch_log=$(tail -n "+$current_launch_start" "$runtime_log")
                if [[ $scene_only == 1 ]]; then
                    readiness_marker='Fay scene-only diagnostic active (character_spawn=off, debug_draw=off, integrations=on).'
                else
                    readiness_marker="Spawned character '$character'"
                fi
                camera_framing_marker="Selected reviewed character profile '$character' (adapter=$expected_adapter, camera_framing=$camera_framing)."
                dormancy_ready=1
                if [[ $avatar_dormancy == 1 ]]; then
                    dormancy_marker="MetaHuman idle dormancy: enabled (delay=${avatar_dormancy_delay}.00 seconds, neutral_prepare_frames=2)."
                    latest_dormancy_transition=$(grep -E \
                        'Entered MetaHuman idle dormancy|Woke the MetaHuman from idle dormancy' \
                        <<<"$current_launch_log" | tail -n1 || true)
                    if ! grep -Fq "$dormancy_marker" <<<"$current_launch_log" ||
                        [[ $latest_dormancy_transition != *'Entered MetaHuman idle dormancy'* ]]; then
                        dormancy_ready=0
                    fi
                fi
                if grep -Fq 'Connected to the Fay avatar WebSocket.' <<<"$current_launch_log" &&
                    grep -Fq 'Activated the visible Spark studio camera and lighting rig.' <<<"$current_launch_log" &&
                    grep -Fq 'Verified project-owned FayGameUserSettings runtime policy.' <<<"$current_launch_log" &&
                    grep -Fq 'Enforced reviewed runtime frame cap at 30.00 FPS after GameUserSettings initialization.' <<<"$current_launch_log" &&
                    grep -Fq "$readiness_marker" <<<"$current_launch_log" &&
                    { [[ $scene_only == 1 ]] || grep -Fq "$camera_framing_marker" <<<"$current_launch_log"; } &&
                    (( dormancy_ready == 1 )); then
                    runtime_ready=1
                    break
                fi
            fi
        fi
    fi
    sleep 1
done
(( runtime_ready == 1 )) || fail 'Unreal did not reach the required Fay/runtime readiness markers'

export FAY_SOAK_REQUIRE_RENDERED=1
if (( turn_count == 0 )); then
    export FAY_SOAK_REQUIRE_NORMAL_AUDIO=0
    export FAY_SOAK_REQUIRE_PROCEDURAL_ACTIONS=0
else
    export FAY_SOAK_REQUIRE_NORMAL_AUDIO=1
    export FAY_SOAK_REQUIRE_PROCEDURAL_ACTIONS=1
fi
export FAY_SOAK_EXPECTED_UNREAL_EXE="$expected_unreal_exe"
export FAY_SOAK_EXPECTED_UNREAL_STARTTIME="$runtime_starttime"
export FAY_SOAK_EXPECTED_FAY_EXE="$fay_exe"
export FAY_SOAK_EXPECTED_FAY_STARTTIME="$fay_starttime"
export FAY_SOAK_EXPECTED_CHARACTER="$character"
export FAY_SOAK_EXPECTED_CAMERA_FRAMING="$camera_framing"
export FAY_SOAK_EXPECTED_RES_X="$res_x"
export FAY_SOAK_EXPECTED_RES_Y="$res_y"
export FAY_SOAK_RUNTIME_LOG_START_LINE="$current_launch_start"
export FAY_SOAK_EXPECT_SCENE_ONLY="$scene_only"
export FAY_SOAK_EXPECT_AVATAR_DORMANCY="$avatar_dormancy"
export FAY_SOAK_EXPECT_AVATAR_DORMANCY_DELAY_SECONDS="$avatar_dormancy_delay"
export FAY_SOAK_EVIDENCE_MODE="$evidence_mode"
export FAY_SOAK_PREFLIGHT_PACKAGE_SEAL_SHA256="$preflight_package_seal_sha256"
export FAY_SOAK_KERNEL_CURSOR="$kernel_cursor"
export FAY_SOAK_MAX_TAIL_RSS_GROWTH_KB="$max_tail_rss_growth_kb"
export FAY_SOAK_MAX_RSS_KB="$max_rss_kb"
export FAY_SOAK_MIN_MEM_AVAILABLE_KB="$min_mem_available_kb"
export FAY_SOAK_MAX_GPU_UTILIZATION_PERCENT="$max_gpu_utilization_percent"
export FAY_SOAK_MAX_FACE_P95_MS="$max_face_p95_ms"

harness_timeout_seconds=$((duration + turn_count * 60 + 300))
setsid "$soak_runner" "$runtime_pid" "$fay_pid" "$output_dir" \
    "$duration" "$turn_count" &
inner_pid=$!
inner_starttime=$(read_process_starttime "$inner_pid" || true)
[[ -n $inner_starttime ]] || fail 'could not capture the owned soak-harness start time'
for _ in $(seq 1 5); do
    current_inner_starttime=$(read_process_starttime "$inner_pid" || true)
    inner_exe=$(readlink "/proc/$inner_pid/exe" 2>/dev/null || true)
    if [[ $current_inner_starttime == "$inner_starttime" && $inner_exe == */bash ]]; then
        break
    fi
    sleep 1
done
[[ $inner_exe == */bash ]] || fail 'the owned soak harness did not exec Bash'
inner_session_id=$(ps -o sid= -p "$inner_pid" | tr -d ' ')
[[ $inner_session_id == "$inner_pid" ]] || \
    fail 'the owned soak harness did not enter its isolated process session'
harness_deadline=$(( $(date +%s) + harness_timeout_seconds ))
harness_timed_out=0
while process_matches_identity "$inner_pid" "$inner_exe" "$inner_starttime"; do
    if (( $(date +%s) >= harness_deadline )); then
        harness_timed_out=1
        cancel_inner_harness
        break
    fi
    sleep 1
done
reap_inner_harness
if (( harness_timed_out == 1 )); then
    fail "the owned soak harness exceeded its ${harness_timeout_seconds}-second wall-clock limit"
fi
if (( inner_exit_status != 0 )); then
    fail "the owned soak harness failed with status $inner_exit_status"
fi
cleanup_runtime 1
if (( enable_csv == 1 )); then
    validate_csv_evidence
fi
finalize_evidence_summary
trap - EXIT HUP INT TERM
if [[ $evidence_mode == diagnostic ]]; then
    printf 'Rendered diagnostic and verified teardown passed; no production qualification is claimed.\n'
elif (( turn_count == 0 )); then
    printf 'Rendered avatar idle diagnostic and verified teardown passed.\n'
else
    printf 'Production rendered-avatar qualification, verified teardown, and package seal passed.\n'
fi
