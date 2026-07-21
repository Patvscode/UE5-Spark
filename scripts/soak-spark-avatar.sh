#!/usr/bin/env bash
set -euo pipefail

fail() {
    printf 'error: %s\n' "$*" >&2
    exit 1
}

if (( $# != 5 )); then
    printf 'Usage: %s UNREAL_PID FAY_PID PRIVATE_OUTPUT_DIR DURATION_SECONDS TURN_COUNT\n' "${0##*/}" >&2
    exit 64
fi

unreal_pid=$1
fay_pid=$2
output_input=$3
duration=$4
turn_count=$5
max_tail_rss_growth_kb=${FAY_SOAK_MAX_TAIL_RSS_GROWTH_KB:-262144}
max_gpu_utilization_percent=${FAY_SOAK_MAX_GPU_UTILIZATION_PERCENT:-85}
max_face_p95_ms=${FAY_SOAK_MAX_FACE_P95_MS:-20}
[[ $unreal_pid =~ ^[1-9][0-9]*$ && $fay_pid =~ ^[1-9][0-9]*$ ]] || \
    fail 'PIDs must be positive integers'
[[ $duration =~ ^[1-9][0-9]*$ && $turn_count =~ ^[1-9][0-9]*$ ]] || \
    fail 'duration and turn count must be positive integers'
[[ $max_tail_rss_growth_kb =~ ^[0-9]+$ ]] || \
    fail 'FAY_SOAK_MAX_TAIL_RSS_GROWTH_KB must be a non-negative integer'
[[ $max_gpu_utilization_percent =~ ^([0-9]|[1-9][0-9]|100)$ ]] || \
    fail 'FAY_SOAK_MAX_GPU_UTILIZATION_PERCENT must be an integer from 0 through 100'
[[ $max_face_p95_ms =~ ^[0-9]+([.][0-9]+)?$ ]] || \
    fail 'FAY_SOAK_MAX_FACE_P95_MS must be a non-negative number'
(( duration >= turn_count && turn_count <= 100 )) || \
    fail 'duration must cover every turn and turn count must not exceed 100'
for command_name in awk curl date dirname grep head mkdir nvidia-smi ps readlink realpath \
    sleep ss tail tr wc; do
    command -v "$command_name" >/dev/null 2>&1 || fail "missing command: $command_name"
done

unreal_exe=$(readlink "/proc/$unreal_pid/exe" 2>/dev/null || true)
fay_exe=$(readlink "/proc/$fay_pid/exe" 2>/dev/null || true)
[[ $unreal_exe == */FayAvatarRuntime ]] || fail 'UNREAL_PID is not FayAvatarRuntime'
[[ $fay_exe == */python* ]] || fail 'FAY_PID is not a Python process'
runtime_root=$(realpath "$(dirname "$unreal_exe")/../..")
runtime_log="$runtime_root/Saved/Logs/FayAvatarRuntime.log"
[[ -f $runtime_log ]] || fail "Unreal runtime log is missing: $runtime_log"
runtime_log_start_lines=$(wc -l <"$runtime_log")

output_dir=$(mkdir -p "$output_input" && cd "$output_input" && pwd -P)
case "$output_dir/" in
    */media-private/*|*/logs-private/*) ;;
    *) fail 'output directory must be below a private media or log root' ;;
esac

read -r _ _ _ fay_address _ < <(ss -H -ltn "sport = :5000" | head -n1)
fay_host=${fay_address%:5000}
[[ -n $fay_host && $fay_host != 0.0.0.0 && $fay_host != \* ]] || \
    fail 'Fay must have one concrete private listener on port 5000'

metrics="$output_dir/soak-metrics.tsv"
summary="$output_dir/soak-summary.txt"
printf 'elapsed_seconds\tturn\tunreal_rss_kb\tgpu_memory_mib\tgpu_utilization_percent\n' >"$metrics"
messages=(
    '例如, Ada can explain this reusable digital human pipeline clearly.'
    '欢迎, this is a dependable live speech and avatar reliability check.'
    '其实, facial expression and body motion remain separate and modular.'
    '比如, each approved character uses the same reviewed runtime adapter.'
    '具体来说, the Spark keeps audio, face, and movement synchronized.'
)

start=$(date +%s)
high_gpu_samples=0
for ((turn = 1; turn <= turn_count; ++turn)); do
    kill -0 "$unreal_pid" 2>/dev/null || fail "Unreal exited before turn $turn"
    kill -0 "$fay_pid" 2>/dev/null || fail "Fay exited before turn $turn"
    message=${messages[$(((turn - 1) % ${#messages[@]}))]}
    payload=$(printf '{"user":"User","text":"%s"}' "$message")
    response=$(curl -fsS --max-time 60 -H 'Content-Type: application/json' \
        --data "$payload" "http://${fay_host}:5000/transparent-pass") || \
        fail "Fay request failed on turn $turn"
    [[ $response == *'"code":200'* ]] || fail "Fay rejected turn $turn"

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
    printf '%s\t%s\t%s\t%s\t%s\n' \
        "$elapsed" "$turn" "$rss" "$gpu" "$gpu_utilization" >>"$metrics"

    target=$((start + (duration * turn / turn_count)))
    while (( $(date +%s) < target )); do
        kill -0 "$unreal_pid" 2>/dev/null || fail "Unreal exited after turn $turn"
        kill -0 "$fay_pid" 2>/dev/null || fail "Fay exited after turn $turn"
        gpu_utilization=$(nvidia-smi --query-gpu=utilization.gpu \
            --format=csv,noheader,nounits 2>/dev/null | head -n1 | tr -d ' ' || true)
        if [[ $gpu_utilization =~ ^([0-9]|[1-9][0-9]|100)$ ]] &&
            (( gpu_utilization > max_gpu_utilization_percent )); then
            ((++high_gpu_samples))
        else
            high_gpu_samples=0
        fi
        if (( high_gpu_samples >= 3 )); then
            fail "shared GPU utilization exceeded ${max_gpu_utilization_percent}% for three consecutive samples"
        fi
        sleep 5
    done
done

end=$(date +%s)
first_rss=$(awk 'NR==2 {print $3}' "$metrics")
last_rss=$(awk 'END {print $3}' "$metrics")
max_rss=$(awk 'NR>1 && $3>m {m=$3} END {print m+0}' "$metrics")
max_gpu_utilization=$(awk 'NR>1 && $5>m {m=$5} END {print m+0}' "$metrics")
tail_start_row=$((2 + turn_count / 2))
tail_start_rss=$(awk -v row="$tail_start_row" 'NR==row {print $3}' "$metrics")
tail_rss_growth_kb=$((last_rss - tail_start_rss))
(( tail_rss_growth_kb < 0 )) && tail_rss_growth_kb=0
status=passed
if (( tail_rss_growth_kb > max_tail_rss_growth_kb )); then
    status=failed
fi
facial_summaries="$output_dir/facial-summaries.log"
tail -n "+$((runtime_log_start_lines + 1))" "$runtime_log" |
    grep 'Fay facial solve summary' >"$facial_summaries" || true
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
    worst_face_p95_ms=$(awk -v current="$worst_face_p95_ms" -v observed="$face_p95_ms" \
        'BEGIN { print observed > current ? observed : current }')
done <"$facial_summaries"
if (( facial_summary_count < turn_count || facial_frame_failures > 0 ||
    facial_p95_failures > 0 )); then
    status=failed
fi
{
    printf 'status=%s\n' "$status"
    printf 'duration_seconds=%s\n' "$((end - start))"
    printf 'turns=%s\n' "$turn_count"
    printf 'unreal_pid=%s\n' "$unreal_pid"
    printf 'fay_pid=%s\n' "$fay_pid"
    printf 'rss_first_kb=%s\n' "$first_rss"
    printf 'rss_last_kb=%s\n' "$last_rss"
    printf 'rss_max_kb=%s\n' "$max_rss"
    printf 'rss_tail_start_kb=%s\n' "$tail_start_rss"
    printf 'rss_tail_growth_kb=%s\n' "$tail_rss_growth_kb"
    printf 'rss_tail_growth_limit_kb=%s\n' "$max_tail_rss_growth_kb"
    printf 'gpu_utilization_max_percent=%s\n' "$max_gpu_utilization"
    printf 'gpu_utilization_limit_percent=%s\n' "$max_gpu_utilization_percent"
    printf 'facial_summary_count=%s\n' "$facial_summary_count"
    printf 'facial_summary_required=%s\n' "$turn_count"
    printf 'facial_frame_failures=%s\n' "$facial_frame_failures"
    printf 'facial_p95_failures=%s\n' "$facial_p95_failures"
    printf 'facial_p95_worst_ms=%s\n' "$worst_face_p95_ms"
    printf 'facial_p95_limit_ms=%s\n' "$max_face_p95_ms"
} >"$summary"
if [[ $status != passed ]]; then
    fail "avatar soak failed; inspect $summary and $facial_summaries"
fi
printf 'Soak test passed: %s turn(s) over %s second(s).\n' "$turn_count" "$((end - start))"
printf 'Private metrics: %s\n' "$metrics"
