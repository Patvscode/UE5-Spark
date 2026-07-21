#!/usr/bin/env bash
set -euo pipefail

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
[[ $idle_warmup_seconds =~ ^[0-9]+$ ]] || \
    fail 'FAY_SOAK_IDLE_WARMUP_SECONDS must be a non-negative integer'
if (( turn_count == 0 && duration < idle_warmup_seconds + 300 )); then
    fail 'an idle diagnostic must include its warm-up plus at least 300 measured seconds'
fi

for command_name in basename grep kill mkdir ps readlink realpath seq sleep ss stat tail; do
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

res_x=${FAY_SOAK_EXPECTED_RES_X:-1280}
res_y=${FAY_SOAK_EXPECTED_RES_Y:-720}
character=${FAY_SOAK_CHARACTER:-Ada}
scene_only=${FAY_SOAK_SCENE_ONLY:-0}
enable_csv=${FAY_SOAK_ENABLE_CSV:-0}
csv_capture_frames=${FAY_SOAK_CSV_CAPTURE_FRAMES:-60000}
csv_compression=${FAY_SOAK_CSV_COMPRESSION:-0}
[[ $res_x =~ ^[1-9][0-9]*$ && $res_y =~ ^[1-9][0-9]*$ ]] || \
    fail 'FAY_SOAK_EXPECTED_RES_X/Y must be positive integers'
[[ $character == Ada || $character == Aoi ]] || \
    fail 'FAY_SOAK_CHARACTER must name a reviewed packaged profile'
[[ $scene_only =~ ^[01]$ ]] || fail 'FAY_SOAK_SCENE_ONLY must be 0 or 1'
if (( scene_only == 1 && turn_count != 0 )); then
    fail 'FAY_SOAK_SCENE_ONLY is restricted to zero-turn idle diagnostics'
fi
[[ $enable_csv =~ ^[01]$ ]] || fail 'FAY_SOAK_ENABLE_CSV must be 0 or 1'
[[ $csv_capture_frames =~ ^[1-9][0-9]*$ ]] || \
    fail 'FAY_SOAK_CSV_CAPTURE_FRAMES must be a positive integer'
[[ $csv_compression =~ ^[01]$ ]] || \
    fail 'FAY_SOAK_CSV_COMPRESSION must be 0 or 1'
for argument in "$@"; do
    case "${argument,,}" in
        -nullrhi|-resx=*|-resy=*|-csvcaptureframes=*|-csvcompression=*|-faysceneonly|-faysceneonly=*)
            fail 'the soak runner owns RHI, resolution, CSV, and scene-only arguments'
            ;;
    esac
done

runtime_log="$package_launcher_dir/FayAvatarRuntime/Saved/Logs/FayAvatarRuntime.log"
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

mapfile -t existing_runtime_pids < <(find_runtime_pids)
(( ${#existing_runtime_pids[@]} == 0 )) || \
    fail 'the selected package already has a running Unreal process'
kill -0 "$fay_pid" 2>/dev/null || fail 'Fay is not alive before launch'

launcher_pid=''
runtime_pid=''
cleanup_completed=0
cleanup_runtime() {
    local cleanup_status=0
    if [[ -n $runtime_pid ]] && kill -0 "$runtime_pid" 2>/dev/null; then
        kill -TERM "$runtime_pid" 2>/dev/null || cleanup_status=1
        for _ in $(seq 1 30); do
            if ! kill -0 "$runtime_pid" 2>/dev/null; then
                break
            fi
            sleep 1
        done
        if kill -0 "$runtime_pid" 2>/dev/null; then
            printf 'error: Unreal did not stop within 30 seconds after TERM\n' >&2
            cleanup_status=1
        fi
    fi
    if [[ -n $launcher_pid && $launcher_pid != "$runtime_pid" ]] &&
        kill -0 "$launcher_pid" 2>/dev/null; then
        kill -TERM "$launcher_pid" 2>/dev/null || cleanup_status=1
    fi
    mapfile -t remaining_runtime_pids < <(find_runtime_pids)
    if (( ${#remaining_runtime_pids[@]} != 0 )); then
        printf 'error: a project-owned Unreal process remains after teardown\n' >&2
        cleanup_status=1
    fi
    if ! kill -0 "$fay_pid" 2>/dev/null; then
        printf 'error: the externally managed Fay process exited during the soak\n' >&2
        cleanup_status=1
    fi
    for port in 5000 5010 8766 10002; do
        listeners=$(ss -H -ltnp "sport = :$port" 2>/dev/null || true)
        if [[ $listeners != *"pid=$fay_pid,"* ]]; then
            printf 'error: Fay no longer owns required port %s\n' "$port" >&2
            cleanup_status=1
        fi
    done
    if ! "$package_verifier" "$package_launcher_dir"; then
        cleanup_status=1
    fi
    cleanup_completed=1
    return "$cleanup_status"
}

handle_exit() {
    local original_status=$?
    if (( cleanup_completed == 0 )); then
        cleanup_runtime || true
    fi
    exit "$original_status"
}
trap handle_exit EXIT

runtime_arguments=(
    "-FayCharacter=$character"
    -FayResetSpeechCache=0
    -FayTrimSpeechMemory=1
    "-ResX=$res_x" "-ResY=$res_y" -Windowed -WinX=0 -WinY=0
)
if [[ $scene_only == 1 ]]; then
    runtime_arguments+=("-FaySceneOnly=1")
fi
if [[ $enable_csv == 1 ]]; then
    runtime_arguments+=(
        "-csvCaptureFrames=$csv_capture_frames"
        "-csvCompression=$csv_compression"
    )
fi
"$digital_human_launcher" "$package_launcher" \
    "${runtime_arguments[@]}" "$@" >"$launcher_log" 2>&1 &
launcher_pid=$!

for _ in $(seq 1 90); do
    mapfile -t discovered_runtime_pids < <(find_runtime_pids)
    if (( ${#discovered_runtime_pids[@]} > 1 )); then
        fail 'more than one matching Unreal process appeared during launch'
    fi
    if (( ${#discovered_runtime_pids[@]} == 1 )); then
        runtime_pid=${discovered_runtime_pids[0]}
        break
    fi
    if ! kill -0 "$launcher_pid" 2>/dev/null; then
        fail "the guarded launcher exited before Unreal started; inspect $launcher_log"
    fi
    sleep 1
done
[[ -n $runtime_pid ]] || fail 'Unreal did not start within 90 seconds'

runtime_ready=0
for _ in $(seq 1 90); do
    kill -0 "$runtime_pid" 2>/dev/null || \
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
                if grep -Fq 'Connected to the Fay avatar WebSocket.' <<<"$current_launch_log" &&
                    grep -Fq 'Activated the visible Spark studio camera and lighting rig.' <<<"$current_launch_log" &&
                    grep -Fq "$readiness_marker" <<<"$current_launch_log"; then
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
export FAY_SOAK_EXPECTED_RES_X="$res_x"
export FAY_SOAK_EXPECTED_RES_Y="$res_y"
export FAY_SOAK_EXPECT_SCENE_ONLY="$scene_only"
export FAY_SOAK_MAX_TAIL_RSS_GROWTH_KB=${FAY_SOAK_MAX_TAIL_RSS_GROWTH_KB:-131072}
if (( turn_count == 0 )); then
    export FAY_SOAK_MAX_RSS_KB=${FAY_SOAK_MAX_RSS_KB:-3040870}
else
    export FAY_SOAK_MAX_RSS_KB=${FAY_SOAK_MAX_RSS_KB:-3145728}
fi
export FAY_SOAK_MIN_MEM_AVAILABLE_KB=${FAY_SOAK_MIN_MEM_AVAILABLE_KB:-50331648}
export FAY_SOAK_MAX_GPU_UTILIZATION_PERCENT=${FAY_SOAK_MAX_GPU_UTILIZATION_PERCENT:-95}

"$soak_runner" "$runtime_pid" "$fay_pid" "$output_dir" "$duration" "$turn_count"
cleanup_runtime
trap - EXIT
if (( turn_count == 0 )); then
    printf 'Rendered avatar idle diagnostic and verified teardown passed.\n'
else
    printf 'Rendered avatar soak and verified teardown passed.\n'
fi
