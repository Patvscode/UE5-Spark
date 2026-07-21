#!/usr/bin/env bash
set -euo pipefail

fail() {
    printf 'error: %s\n' "$*" >&2
    exit 1
}

if (( $# != 5 )); then
    printf 'Usage: %s UNREAL_PID FAY_PID PRIVATE_OUTPUT_DIR DURATION_SECONDS TURN_COUNT\n' "${0##*/}" >&2
    printf '       TURN_COUNT=0 samples an idle avatar without sending Fay turns.\n' >&2
    exit 64
fi

unreal_pid=$1
fay_pid=$2
output_input=$3
duration=$4
turn_count=$5
max_tail_rss_growth_kb=${FAY_SOAK_MAX_TAIL_RSS_GROWTH_KB:-262144}
max_rss_kb=${FAY_SOAK_MAX_RSS_KB:-0}
min_mem_available_kb=${FAY_SOAK_MIN_MEM_AVAILABLE_KB:-0}
max_gpu_utilization_percent=${FAY_SOAK_MAX_GPU_UTILIZATION_PERCENT:-85}
max_face_p95_ms=${FAY_SOAK_MAX_FACE_P95_MS:-20}
idle_warmup_seconds=${FAY_SOAK_IDLE_WARMUP_SECONDS:-120}
max_idle_measurement_growth_kb=${FAY_SOAK_MAX_IDLE_MEASUREMENT_GROWTH_KB:-98304}
max_idle_slope_kb_per_second=${FAY_SOAK_MAX_IDLE_SLOPE_KB_PER_SECOND:-128}
max_idle_step_like_growth_count=${FAY_SOAK_MAX_IDLE_STEP_LIKE_GROWTH_COUNT:-2}
require_rendered=${FAY_SOAK_REQUIRE_RENDERED:-0}
require_normal_audio=${FAY_SOAK_REQUIRE_NORMAL_AUDIO:-$require_rendered}
require_procedural_actions=${FAY_SOAK_REQUIRE_PROCEDURAL_ACTIONS:-$require_rendered}
expected_unreal_input=${FAY_SOAK_EXPECTED_UNREAL_EXE:-}
expected_res_x=${FAY_SOAK_EXPECTED_RES_X:-1280}
expected_res_y=${FAY_SOAK_EXPECTED_RES_Y:-720}
expected_scene_only=${FAY_SOAK_EXPECT_SCENE_ONLY:-0}

[[ $unreal_pid =~ ^[1-9][0-9]*$ && $fay_pid =~ ^[1-9][0-9]*$ ]] || \
    fail 'PIDs must be positive integers'
[[ $duration =~ ^[1-9][0-9]*$ && $turn_count =~ ^[0-9]+$ ]] || \
    fail 'duration must be positive and turn count must be a non-negative integer'
[[ $max_tail_rss_growth_kb =~ ^[0-9]+$ ]] || \
    fail 'FAY_SOAK_MAX_TAIL_RSS_GROWTH_KB must be a non-negative integer'
[[ $max_rss_kb =~ ^[0-9]+$ ]] || \
    fail 'FAY_SOAK_MAX_RSS_KB must be a non-negative integer'
[[ $min_mem_available_kb =~ ^[0-9]+$ ]] || \
    fail 'FAY_SOAK_MIN_MEM_AVAILABLE_KB must be a non-negative integer'
[[ $max_gpu_utilization_percent =~ ^([0-9]|[1-9][0-9]|100)$ ]] || \
    fail 'FAY_SOAK_MAX_GPU_UTILIZATION_PERCENT must be an integer from 0 through 100'
[[ $max_face_p95_ms =~ ^[0-9]+([.][0-9]+)?$ ]] || \
    fail 'FAY_SOAK_MAX_FACE_P95_MS must be a non-negative number'
[[ $idle_warmup_seconds =~ ^[0-9]+$ && \
    $max_idle_measurement_growth_kb =~ ^[0-9]+$ && \
    $max_idle_step_like_growth_count =~ ^[0-9]+$ ]] || \
    fail 'idle warm-up, growth, and step-count settings must be non-negative integers'
[[ $max_idle_slope_kb_per_second =~ ^[0-9]+([.][0-9]+)?$ ]] || \
    fail 'FAY_SOAK_MAX_IDLE_SLOPE_KB_PER_SECOND must be a non-negative number'
[[ $require_rendered =~ ^[01]$ && $require_normal_audio =~ ^[01]$ && \
    $require_procedural_actions =~ ^[01]$ ]] || \
    fail 'rendered, normal-audio, and procedural-action requirements must be 0 or 1'
[[ $expected_res_x =~ ^[1-9][0-9]*$ && $expected_res_y =~ ^[1-9][0-9]*$ ]] || \
    fail 'expected rendered resolution must contain positive integers'
[[ $expected_scene_only =~ ^[01]$ ]] || \
    fail 'FAY_SOAK_EXPECT_SCENE_ONLY must be 0 or 1'
(( duration >= turn_count && turn_count <= 100 )) || \
    fail 'duration must cover every turn and turn count must not exceed 100'
if (( turn_count == 0 && duration < idle_warmup_seconds + 300 )); then
    fail 'an idle diagnostic must include its warm-up plus at least 300 measured seconds'
fi
if [[ $require_rendered == 1 && -z $expected_unreal_input ]]; then
    fail 'FAY_SOAK_EXPECTED_UNREAL_EXE is required for a rendered soak'
fi

for command_name in awk curl date dirname grep head journalctl mkdir nvidia-smi ps \
    readlink realpath sed sleep ss tail tr wc; do
    command -v "$command_name" >/dev/null 2>&1 || fail "missing command: $command_name"
done

unreal_exe=$(readlink "/proc/$unreal_pid/exe" 2>/dev/null || true)
fay_exe=$(readlink "/proc/$fay_pid/exe" 2>/dev/null || true)
[[ $unreal_exe == */FayAvatarRuntime ]] || fail 'UNREAL_PID is not FayAvatarRuntime'
[[ $fay_exe == */python* ]] || fail 'FAY_PID is not a Python process'
if [[ -n $expected_unreal_input ]]; then
    expected_unreal_exe=$(realpath "$expected_unreal_input")
    [[ $unreal_exe == "$expected_unreal_exe" ]] || \
        fail 'UNREAL_PID does not match FAY_SOAK_EXPECTED_UNREAL_EXE'
fi

unreal_arguments=$(tr '\0' '\n' <"/proc/$unreal_pid/cmdline")
if [[ $require_rendered == 1 ]]; then
    grep -Fxiq -- '-vulkan' <<<"$unreal_arguments" || \
        fail 'rendered soak requires an explicit -vulkan argument'
    grep -Fxiq -- "-ResX=$expected_res_x" <<<"$unreal_arguments" || \
        fail "rendered soak requires -ResX=$expected_res_x"
    grep -Fxiq -- "-ResY=$expected_res_y" <<<"$unreal_arguments" || \
        fail "rendered soak requires -ResY=$expected_res_y"
    if grep -Fxiq -- '-nullrhi' <<<"$unreal_arguments"; then
        fail 'rendered soak refuses -nullrhi'
    fi
fi
if [[ $expected_scene_only == 1 ]]; then
    grep -Fxiq -- '-FaySceneOnly=1' <<<"$unreal_arguments" || \
        fail 'scene-only evidence requires the exact -FaySceneOnly=1 argument'
else
    if grep -Fxiq -- '-FaySceneOnly=1' <<<"$unreal_arguments"; then
        fail 'ordinary avatar evidence refuses an unexpected -FaySceneOnly=1 argument'
    fi
fi

runtime_root=$(realpath "$(dirname "$unreal_exe")/../..")
runtime_log="$runtime_root/Saved/Logs/FayAvatarRuntime.log"
[[ -f $runtime_log ]] || fail "Unreal runtime log is missing: $runtime_log"
runtime_log_start_lines=$(wc -l <"$runtime_log")

output_dir=$(mkdir -p "$output_input" && cd "$output_input" && pwd -P)
case "$output_dir/" in
    */media-private/*|*/logs-private/*) ;;
    *) fail 'output directory must be below a private media or log root' ;;
esac

runtime_new_log="$output_dir/runtime-new.log"
kernel_new_log="$output_dir/kernel-new.log"
runtime_failures_log="$output_dir/runtime-failures.log"
kernel_failures_log="$output_dir/kernel-failures.log"
kernel_cursor=$(journalctl -k -n 0 --show-cursor --no-pager 2>/dev/null |
    sed -n 's/^-- cursor: //p' | tail -n1)
[[ -n $kernel_cursor ]] || fail 'could not capture the kernel journal cursor'

capture_evidence() {
    tail -n "+$((runtime_log_start_lines + 1))" "$runtime_log" >"$runtime_new_log" 2>/dev/null || true
    journalctl -k --after-cursor "$kernel_cursor" --no-pager >"$kernel_new_log" 2>/dev/null || true
}
trap 'capture_evidence' EXIT

listener_owned_by_fay() {
    local port=$1
    local listeners
    listeners=$(ss -H -ltnp "sport = :$port" 2>/dev/null || true)
    [[ $listeners == *"pid=$fay_pid,"* ]] || \
        fail "FAY_PID does not own the required listener on port $port"
}

for fay_port in 5000 5010 8766 10002; do
    listener_owned_by_fay "$fay_port"
done
read -r _ _ _ fay_address _ < <(ss -H -ltnp "sport = :5000" | head -n1)
fay_host=${fay_address%:5000}
[[ -n $fay_host && $fay_host != 0.0.0.0 && $fay_host != \* ]] || \
    fail 'Fay must have one concrete private listener on port 5000'

metrics="$output_dir/soak-metrics.tsv"
summary="$output_dir/soak-summary.txt"
printf 'elapsed_seconds\tturn\tunreal_rss_kb\tgpu_memory_mib\tgpu_utilization_percent\tmem_available_kb\tprivate_dirty_kb\tanonymous_kb\tswap_kb\n' >"$metrics"
messages=(
    '再见, Ada is completing the reviewed wave reliability check.'
    '欢迎, Ada is completing the reviewed invitation reliability check.'
    '让我想想, Ada is completing the reviewed thinking reliability check.'
    '注意, Ada is completing the reviewed warning reliability check.'
    '其实, Ada is completing the reviewed explanation reliability check.'
    '你好, Ada is completing the reviewed head gesture reliability check.'
)

start=$(date +%s)
high_gpu_samples=0
sample_resources() {
    local current_turn=$1
    local now elapsed rss gpu gpu_utilization available_memory_kb
    local private_dirty_kb anonymous_kb swap_kb
    now=$(date +%s)
    elapsed=$((now - start))
    rss=$(ps -o rss= -p "$unreal_pid" | tr -d ' ')
    [[ $rss =~ ^[0-9]+$ ]] || fail 'could not read Unreal resident memory'
    gpu=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits 2>/dev/null \
        | head -n1 | tr -d ' ' || true)
    [[ $gpu =~ ^[0-9]+$ ]] || gpu=-1
    gpu_utilization=$(nvidia-smi --query-gpu=utilization.gpu \
        --format=csv,noheader,nounits 2>/dev/null | head -n1 | tr -d ' ' || true)
    [[ $gpu_utilization =~ ^([0-9]|[1-9][0-9]|100)$ ]] || gpu_utilization=-1
    available_memory_kb=$(awk '/^MemAvailable:/ {print $2; exit}' /proc/meminfo)
    [[ $available_memory_kb =~ ^[0-9]+$ ]] || available_memory_kb=-1
    if [[ -r /proc/$unreal_pid/smaps_rollup ]]; then
        read -r private_dirty_kb anonymous_kb swap_kb < <(
            awk '
                /^Private_Dirty:/ {private_dirty=$2}
                /^Anonymous:/ {anonymous=$2}
                /^Swap:/ {swap=$2}
                END {print private_dirty+0, anonymous+0, swap+0}
            ' "/proc/$unreal_pid/smaps_rollup")
    else
        private_dirty_kb=-1
        anonymous_kb=-1
        swap_kb=-1
    fi
    [[ $private_dirty_kb =~ ^-?[0-9]+$ ]] || private_dirty_kb=-1
    [[ $anonymous_kb =~ ^-?[0-9]+$ ]] || anonymous_kb=-1
    [[ $swap_kb =~ ^-?[0-9]+$ ]] || swap_kb=-1
    printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
        "$elapsed" "$current_turn" "$rss" "$gpu" "$gpu_utilization" \
        "$available_memory_kb" "$private_dirty_kb" "$anonymous_kb" "$swap_kb" >>"$metrics"

    if [[ $gpu_utilization =~ ^([0-9]|[1-9][0-9]|100)$ ]] &&
        (( gpu_utilization > max_gpu_utilization_percent )); then
        ((++high_gpu_samples))
    else
        high_gpu_samples=0
    fi
    if (( high_gpu_samples >= 3 )); then
        fail "shared GPU utilization exceeded ${max_gpu_utilization_percent}% for three consecutive samples"
    fi
    if (( max_rss_kb > 0 && rss > max_rss_kb )); then
        fail "Unreal RSS exceeded the ${max_rss_kb} KiB safety ceiling"
    fi
    if (( min_mem_available_kb > 0 && available_memory_kb >= 0 &&
        available_memory_kb < min_mem_available_kb )); then
        fail "MemAvailable fell below the ${min_mem_available_kb} KiB safety floor"
    fi
}

if (( turn_count == 0 )); then
    sample_resources 0
    target=$((start + duration))
    while (( $(date +%s) < target )); do
        kill -0 "$unreal_pid" 2>/dev/null || fail 'Unreal exited during the idle diagnostic'
        kill -0 "$fay_pid" 2>/dev/null || fail 'Fay exited during the idle diagnostic'
        for fay_port in 5000 5010 8766 10002; do
            listener_owned_by_fay "$fay_port"
        done
        sleep 5
        sample_resources 0
    done
else
    for ((turn = 1; turn <= turn_count; ++turn)); do
        kill -0 "$unreal_pid" 2>/dev/null || fail "Unreal exited before turn $turn"
        kill -0 "$fay_pid" 2>/dev/null || fail "Fay exited before turn $turn"
        for fay_port in 5000 5010 8766 10002; do
            listener_owned_by_fay "$fay_port"
        done
        message=${messages[$(((turn - 1) % ${#messages[@]}))]}
        payload=$(printf '{"user":"User","text":"%s"}' "$message")
        response=$(curl -fsS --max-time 60 -H 'Content-Type: application/json' \
            --data "$payload" "http://${fay_host}:5000/transparent-pass") || \
            fail "Fay request failed on turn $turn"
        [[ $response == *'"code":200'* ]] || fail "Fay rejected turn $turn"
        sample_resources "$turn"

        target=$((start + (duration * turn / turn_count)))
        while (( $(date +%s) < target )); do
            kill -0 "$unreal_pid" 2>/dev/null || fail "Unreal exited after turn $turn"
            kill -0 "$fay_pid" 2>/dev/null || fail "Fay exited after turn $turn"
            sleep 5
            sample_resources "$turn"
        done
    done
fi

end=$(date +%s)
capture_evidence
first_rss=$(awk 'NR==2 {print $3}' "$metrics")
last_rss=$(awk 'END {print $3}' "$metrics")
max_rss=$(awk 'NR>1 && $3>m {m=$3} END {print m+0}' "$metrics")
max_gpu_utilization=$(awk 'NR>1 && $5>m {m=$5} END {print m+0}' "$metrics")
min_available_memory_kb=$(awk 'NR>1 && (m==0 || $6<m) {m=$6} END {print m+0}' "$metrics")
private_dirty_first_kb=$(awk 'NR==2 {print $7}' "$metrics")
private_dirty_last_kb=$(awk 'END {print $7}' "$metrics")
anonymous_first_kb=$(awk 'NR==2 {print $8}' "$metrics")
anonymous_last_kb=$(awk 'END {print $8}' "$metrics")
swap_max_kb=$(awk 'NR>1 && $9>m {m=$9} END {print m+0}' "$metrics")
rss_slope_kb_per_second=$(awk '
    NR > 1 {n++; sx += $1; sy += $3; sxx += $1 * $1; sxy += $1 * $3}
    END {
        denominator = n * sxx - sx * sx
        if (n < 2 || denominator == 0) print "0.00"
        else printf "%.2f\n", (n * sxy - sx * sy) / denominator
    }' "$metrics")
half_duration=$((duration / 2))
tail_start_rss=$(awk -v half="$half_duration" 'NR>1 && $1>=half {print $3; exit}' "$metrics")
[[ $tail_start_rss =~ ^[0-9]+$ ]] || tail_start_rss=$first_rss
tail_rss_growth_kb=$((last_rss - tail_start_rss))
(( tail_rss_growth_kb < 0 )) && tail_rss_growth_kb=0

status=passed
if (( turn_count == 0 )); then
    run_mode=idle
    if [[ $expected_scene_only == 1 ]]; then
        run_mode=scene-only-idle
    fi
    idle_measurement_start_rss=$(awk -v warmup="$idle_warmup_seconds" \
        'NR>1 && $1>=warmup {print $3; exit}' "$metrics")
    [[ $idle_measurement_start_rss =~ ^[0-9]+$ ]] || \
        fail 'idle measurement did not contain a post-warm-up RSS sample'
    idle_measurement_growth_kb=$((last_rss - idle_measurement_start_rss))
    (( idle_measurement_growth_kb < 0 )) && idle_measurement_growth_kb=0
    idle_slope_kb_per_second=$(awk -v warmup="$idle_warmup_seconds" '
        NR > 1 && $1 >= warmup {
            n++; sx += $1; sy += $3; sxx += $1 * $1; sxy += $1 * $3
        }
        END {
            denominator = n * sxx - sx * sx
            if (n < 2 || denominator == 0) print "0.00"
            else printf "%.2f\n", (n * sxy - sx * sy) / denominator
        }' "$metrics")
    idle_final_window_start=$((duration - 300))
    idle_final_slope_kb_per_second=$(awk -v window="$idle_final_window_start" '
        NR > 1 && $1 >= window {
            n++; sx += $1; sy += $3; sxx += $1 * $1; sxy += $1 * $3
        }
        END {
            denominator = n * sxx - sx * sx
            if (n < 2 || denominator == 0) print "0.00"
            else printf "%.2f\n", (n * sxy - sx * sy) / denominator
        }' "$metrics")
    idle_step_like_growth_count=$(awk -v window="$idle_final_window_start" '
        NR > 1 && $1 >= window {
            if (have_previous) {
                delta = $3 - previous
                if (delta >= 7168 && delta <= 18432) count++
            }
            previous = $3
            have_previous = 1
        }
        END {print count + 0}' "$metrics")
else
    run_mode=speech
    idle_measurement_start_rss=0
    idle_measurement_growth_kb=0
    idle_slope_kb_per_second=0.00
    idle_final_window_start=0
    idle_final_slope_kb_per_second=0.00
    idle_step_like_growth_count=0
fi
if (( tail_rss_growth_kb > max_tail_rss_growth_kb )); then
    status=failed
fi
if (( max_rss_kb > 0 && max_rss > max_rss_kb )); then
    status=failed
fi
if (( min_mem_available_kb > 0 && min_available_memory_kb >= 0 &&
    min_available_memory_kb < min_mem_available_kb )); then
    status=failed
fi
if (( turn_count == 0 )); then
    if (( idle_measurement_growth_kb > max_idle_measurement_growth_kb ||
        idle_step_like_growth_count > max_idle_step_like_growth_count )); then
        status=failed
    fi
    if awk -v observed="$idle_slope_kb_per_second" \
        -v limit="$max_idle_slope_kb_per_second" \
        'BEGIN {exit !(observed > limit)}'; then
        status=failed
    fi
    if awk -v observed="$idle_final_slope_kb_per_second" \
        -v limit="$max_idle_slope_kb_per_second" \
        'BEGIN {exit !(observed > limit)}'; then
        status=failed
    fi
fi

facial_summaries="$output_dir/facial-summaries.log"
grep 'Fay facial solve summary' "$runtime_new_log" >"$facial_summaries" || true
facial_summary_count=0
facial_frame_failures=0
facial_p95_failures=0
worst_face_p95_ms=0
while IFS= read -r line; do
    [[ $line =~ frames=([0-9]+),[[:space:]]speech_seconds=([0-9]+([.][0-9]+)?),.*p95_ms=([0-9]+([.][0-9]+)?) ]] || continue
    ((++facial_summary_count))
    actual_frames=${BASH_REMATCH[1]}
    speech_seconds=${BASH_REMATCH[2]}
    face_p95_ms=${BASH_REMATCH[4]}
    expected_frames=$(awk -v seconds="$speech_seconds" \
        'BEGIN { printf "%.0f", seconds * 50.0 + 10.0 }')
    if (( actual_frames != expected_frames )); then
        ((++facial_frame_failures))
    fi
    if awk -v observed="$face_p95_ms" -v limit="$max_face_p95_ms" \
        'BEGIN { exit !(observed > limit) }'; then
        ((++facial_p95_failures))
    fi
    worst_face_p95_ms=$(awk -v previous="$worst_face_p95_ms" -v observed="$face_p95_ms" \
        'BEGIN { print (observed > previous ? observed : previous) }')
done <"$facial_summaries"
if (( facial_summary_count != turn_count || facial_frame_failures > 0 ||
    facial_p95_failures > 0 )); then
    status=failed
fi

runtime_failure_pattern='Fatal error|Assertion failed|Out of memory|GPU Crashed|VK_ERROR_DEVICE_LOST|LogVulkanRHI: Error|queue overflow|LogFay[^:]*: Error'
grep -Ein "$runtime_failure_pattern" "$runtime_new_log" >"$runtime_failures_log" || true
runtime_failure_count=$(wc -l <"$runtime_failures_log")
if (( runtime_failure_count > 0 )); then
    status=failed
fi

kernel_failure_pattern='NVRM: Xid|CTX SWITCH TIMEOUT|NV_ERR_NO_MEMORY|GPU has fallen off the bus'
grep -Ein "$kernel_failure_pattern" "$kernel_new_log" >"$kernel_failures_log" || true
kernel_failure_count=$(wc -l <"$kernel_failures_log")
if (( kernel_failure_count > 0 )); then
    status=failed
fi

finished_playback_count=$(grep -Fc 'Finished Fay speech playback' "$runtime_new_log" || true)
allocator_release_count=$(grep -Fc 'Released completed-utterance allocator pools' "$runtime_new_log" || true)
delayed_collection_count=$(grep -Fc 'Collected completed speech objects and released delayed' "$runtime_new_log" || true)
audio_watchdog_count=$(grep -Ec 'Procedural PCM did not drain|Unreal did not report audio completion' "$runtime_new_log" || true)
bridge_warning_count=$(grep -Fc 'LogFayAvatarBridge: Warning' "$runtime_new_log" || true)
if [[ $require_normal_audio == 1 ]]; then
    if (( finished_playback_count != turn_count || allocator_release_count != turn_count ||
        delayed_collection_count != turn_count || audio_watchdog_count > 0 ||
        bridge_warning_count > 0 )); then
        status=failed
    fi
fi

procedural_action_failures=0
if [[ $require_procedural_actions == 1 ]]; then
    deterministic_behaviors=(wave invite think warn)
    deterministic_required_count=$turn_count
    (( deterministic_required_count > ${#deterministic_behaviors[@]} )) && \
        deterministic_required_count=${#deterministic_behaviors[@]}
    for behavior in "${deterministic_behaviors[@]:0:deterministic_required_count}"; do
        marker="Using character-neutral procedural fallback for '$behavior'."
        behavior_count=$(grep -Fci "$marker" "$runtime_new_log" || true)
        if (( behavior_count < 1 )); then
            ((++procedural_action_failures))
        fi
    done
    if (( turn_count >= 5 )); then
        explain_fallback_count=$(grep -Fci \
            "Using character-neutral procedural fallback for 'explain'." \
            "$runtime_new_log" || true)
        explain_ardy_count=$(grep -Fci \
            "Using ARDY generated motion provider for 'explain'." \
            "$runtime_new_log" || true)
        if (( explain_fallback_count + explain_ardy_count < 1 )); then
            ((++procedural_action_failures))
        fi
    fi
    if (( turn_count >= 6 )); then
        nod_count=$(grep -Fci \
            "Using character-neutral procedural fallback for 'nod'." \
            "$runtime_new_log" || true)
        if (( nod_count < 1 )); then
            ((++procedural_action_failures))
        fi
    fi
    if (( procedural_action_failures > 0 )); then
        status=failed
    fi
fi

{
    printf 'status=%s\n' "$status"
    printf 'mode=%s\n' "$run_mode"
    printf 'duration_seconds=%s\n' "$((end - start))"
    printf 'turns=%s\n' "$turn_count"
    printf 'rendered_required=%s\n' "$require_rendered"
    printf 'normal_audio_required=%s\n' "$require_normal_audio"
    printf 'procedural_actions_required=%s\n' "$require_procedural_actions"
    printf 'unreal_pid=%s\n' "$unreal_pid"
    printf 'fay_pid=%s\n' "$fay_pid"
    printf 'rss_first_kb=%s\n' "$first_rss"
    printf 'rss_last_kb=%s\n' "$last_rss"
    printf 'rss_max_kb=%s\n' "$max_rss"
    printf 'rss_max_limit_kb=%s\n' "$max_rss_kb"
    printf 'rss_tail_start_kb=%s\n' "$tail_start_rss"
    printf 'rss_tail_growth_kb=%s\n' "$tail_rss_growth_kb"
    printf 'rss_tail_growth_limit_kb=%s\n' "$max_tail_rss_growth_kb"
    printf 'rss_slope_kb_per_second=%s\n' "$rss_slope_kb_per_second"
    printf 'mem_available_min_kb=%s\n' "$min_available_memory_kb"
    printf 'mem_available_min_limit_kb=%s\n' "$min_mem_available_kb"
    printf 'private_dirty_first_kb=%s\n' "$private_dirty_first_kb"
    printf 'private_dirty_last_kb=%s\n' "$private_dirty_last_kb"
    printf 'anonymous_first_kb=%s\n' "$anonymous_first_kb"
    printf 'anonymous_last_kb=%s\n' "$anonymous_last_kb"
    printf 'swap_max_kb=%s\n' "$swap_max_kb"
    printf 'gpu_utilization_max_percent=%s\n' "$max_gpu_utilization"
    printf 'gpu_utilization_sustained_threshold_percent=%s\n' \
        "$max_gpu_utilization_percent"
    printf 'gpu_utilization_consecutive_failure_samples=3\n'
    printf 'facial_summary_count=%s\n' "$facial_summary_count"
    printf 'facial_summary_required=%s\n' "$turn_count"
    printf 'facial_frame_failures=%s\n' "$facial_frame_failures"
    printf 'facial_p95_failures=%s\n' "$facial_p95_failures"
    printf 'facial_p95_worst_ms=%s\n' "$worst_face_p95_ms"
    printf 'facial_p95_limit_ms=%s\n' "$max_face_p95_ms"
    printf 'finished_playback_count=%s\n' "$finished_playback_count"
    printf 'allocator_release_count=%s\n' "$allocator_release_count"
    printf 'delayed_collection_count=%s\n' "$delayed_collection_count"
    printf 'audio_watchdog_count=%s\n' "$audio_watchdog_count"
    printf 'bridge_warning_count=%s\n' "$bridge_warning_count"
    printf 'procedural_action_failures=%s\n' "$procedural_action_failures"
    printf 'runtime_failure_count=%s\n' "$runtime_failure_count"
    printf 'kernel_failure_count=%s\n' "$kernel_failure_count"
    printf 'idle_warmup_seconds=%s\n' "$idle_warmup_seconds"
    printf 'idle_measurement_start_rss_kb=%s\n' "$idle_measurement_start_rss"
    printf 'idle_measurement_growth_kb=%s\n' "$idle_measurement_growth_kb"
    printf 'idle_measurement_growth_limit_kb=%s\n' "$max_idle_measurement_growth_kb"
    printf 'idle_slope_kb_per_second=%s\n' "$idle_slope_kb_per_second"
    printf 'idle_final_window_start_seconds=%s\n' "$idle_final_window_start"
    printf 'idle_final_slope_kb_per_second=%s\n' "$idle_final_slope_kb_per_second"
    printf 'idle_slope_limit_kb_per_second=%s\n' "$max_idle_slope_kb_per_second"
    printf 'idle_step_like_growth_count=%s\n' "$idle_step_like_growth_count"
    printf 'idle_step_like_growth_limit=%s\n' "$max_idle_step_like_growth_count"
} >"$summary"

if [[ $status != passed ]]; then
    fail "avatar soak failed; inspect $summary, $runtime_new_log, and $kernel_new_log"
fi
if (( turn_count == 0 )); then
    printf 'Idle avatar diagnostic passed over %s second(s).\n' "$((end - start))"
else
    printf 'Soak test passed: %s turn(s) over %s second(s).\n' "$turn_count" "$((end - start))"
fi
printf 'Private metrics: %s\n' "$metrics"
