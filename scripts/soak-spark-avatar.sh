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
[[ $unreal_pid =~ ^[1-9][0-9]*$ && $fay_pid =~ ^[1-9][0-9]*$ ]] || \
    fail 'PIDs must be positive integers'
[[ $duration =~ ^[1-9][0-9]*$ && $turn_count =~ ^[1-9][0-9]*$ ]] || \
    fail 'duration and turn count must be positive integers'
[[ $max_tail_rss_growth_kb =~ ^[0-9]+$ ]] || \
    fail 'FAY_SOAK_MAX_TAIL_RSS_GROWTH_KB must be a non-negative integer'
(( duration >= turn_count && turn_count <= 100 )) || \
    fail 'duration must cover every turn and turn count must not exceed 100'
for command_name in curl date mkdir nvidia-smi ps readlink ss; do
    command -v "$command_name" >/dev/null 2>&1 || fail "missing command: $command_name"
done

unreal_exe=$(readlink "/proc/$unreal_pid/exe" 2>/dev/null || true)
fay_exe=$(readlink "/proc/$fay_pid/exe" 2>/dev/null || true)
[[ $unreal_exe == */FayAvatarRuntime ]] || fail 'UNREAL_PID is not FayAvatarRuntime'
[[ $fay_exe == */python* ]] || fail 'FAY_PID is not a Python process'

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
printf 'elapsed_seconds\tturn\tunreal_rss_kb\tgpu_memory_mib\n' >"$metrics"
messages=(
    '例如, Ada can explain this reusable digital human pipeline clearly.'
    '欢迎, this is a dependable live speech and avatar reliability check.'
    '其实, facial expression and body motion remain separate and modular.'
    '比如, each approved character uses the same reviewed runtime adapter.'
    '具体来说, the Spark keeps audio, face, and movement synchronized.'
)

start=$(date +%s)
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
    printf '%s\t%s\t%s\t%s\n' "$elapsed" "$turn" "$rss" "$gpu" >>"$metrics"

    target=$((start + (duration * turn / turn_count)))
    while (( $(date +%s) < target )); do
        kill -0 "$unreal_pid" 2>/dev/null || fail "Unreal exited after turn $turn"
        kill -0 "$fay_pid" 2>/dev/null || fail "Fay exited after turn $turn"
        sleep 5
    done
done

end=$(date +%s)
first_rss=$(awk 'NR==2 {print $3}' "$metrics")
last_rss=$(awk 'END {print $3}' "$metrics")
max_rss=$(awk 'NR>1 && $3>m {m=$3} END {print m+0}' "$metrics")
tail_start_row=$((2 + turn_count / 2))
tail_start_rss=$(awk -v row="$tail_start_row" 'NR==row {print $3}' "$metrics")
tail_rss_growth_kb=$((last_rss - tail_start_rss))
(( tail_rss_growth_kb < 0 )) && tail_rss_growth_kb=0
status=passed
if (( tail_rss_growth_kb > max_tail_rss_growth_kb )); then
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
} >"$summary"
if [[ $status != passed ]]; then
    fail "Unreal RSS grew by ${tail_rss_growth_kb} KB in the latter half of the soak (limit: ${max_tail_rss_growth_kb} KB)"
fi
printf 'Soak test passed: %s turn(s) over %s second(s).\n' "$turn_count" "$((end - start))"
printf 'Private metrics: %s\n' "$metrics"
