#!/usr/bin/env bash
set -euo pipefail
umask 077

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
idle_measurement_seconds=${FAY_SOAK_IDLE_MEASUREMENT_SECONDS:-300}
max_idle_measurement_growth_kb=${FAY_SOAK_MAX_IDLE_MEASUREMENT_GROWTH_KB:-98304}
max_idle_slope_kb_per_second=${FAY_SOAK_MAX_IDLE_SLOPE_KB_PER_SECOND:-128}
max_idle_step_like_growth_count=${FAY_SOAK_MAX_IDLE_STEP_LIKE_GROWTH_COUNT:-2}
require_rendered=${FAY_SOAK_REQUIRE_RENDERED:-0}
require_normal_audio=${FAY_SOAK_REQUIRE_NORMAL_AUDIO:-$require_rendered}
require_procedural_actions=${FAY_SOAK_REQUIRE_PROCEDURAL_ACTIONS:-$require_rendered}
expected_unreal_input=${FAY_SOAK_EXPECTED_UNREAL_EXE:-}
expected_unreal_starttime=${FAY_SOAK_EXPECTED_UNREAL_STARTTIME:-}
expected_fay_input=${FAY_SOAK_EXPECTED_FAY_EXE:-}
expected_fay_starttime=${FAY_SOAK_EXPECTED_FAY_STARTTIME:-}
expected_character=${FAY_SOAK_EXPECTED_CHARACTER:-Ada}
expected_res_x=${FAY_SOAK_EXPECTED_RES_X:-1280}
expected_res_y=${FAY_SOAK_EXPECTED_RES_Y:-720}
expected_scene_only=${FAY_SOAK_EXPECT_SCENE_ONLY:-0}
expected_avatar_dormancy=${FAY_SOAK_EXPECT_AVATAR_DORMANCY:-0}
expected_avatar_dormancy_delay=${FAY_SOAK_EXPECT_AVATAR_DORMANCY_DELAY_SECONDS:-5}
runtime_log_start_line=${FAY_SOAK_RUNTIME_LOG_START_LINE:-}
requested_evidence_mode=${FAY_SOAK_EVIDENCE_MODE:-}
evidence_mode=$requested_evidence_mode
max_dormancy_cancellations=${FAY_SOAK_MAX_DORMANCY_CANCELLATIONS:-0}
preflight_package_seal_sha256=${FAY_SOAK_PREFLIGHT_PACKAGE_SEAL_SHA256:-}
provided_kernel_cursor=${FAY_SOAK_KERNEL_CURSOR:-}

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
[[ $idle_measurement_seconds =~ ^[1-9][0-9]*$ ]] || \
    fail 'FAY_SOAK_IDLE_MEASUREMENT_SECONDS must be a positive integer'
if (( idle_measurement_seconds < 30 || idle_measurement_seconds > 3600 )); then
    fail 'FAY_SOAK_IDLE_MEASUREMENT_SECONDS must be from 30 through 3600'
fi
[[ $max_idle_slope_kb_per_second =~ ^[0-9]+([.][0-9]+)?$ ]] || \
    fail 'FAY_SOAK_MAX_IDLE_SLOPE_KB_PER_SECOND must be a non-negative number'
[[ $require_rendered =~ ^[01]$ && $require_normal_audio =~ ^[01]$ && \
    $require_procedural_actions =~ ^[01]$ ]] || \
    fail 'rendered, normal-audio, and procedural-action requirements must be 0 or 1'
[[ $expected_res_x =~ ^[1-9][0-9]*$ && $expected_res_y =~ ^[1-9][0-9]*$ ]] || \
    fail 'expected rendered resolution must contain positive integers'
[[ $expected_scene_only =~ ^[01]$ ]] || \
    fail 'FAY_SOAK_EXPECT_SCENE_ONLY must be 0 or 1'
[[ -z $requested_evidence_mode || $requested_evidence_mode == production || \
    $requested_evidence_mode == diagnostic ]] || \
    fail 'FAY_SOAK_EVIDENCE_MODE must be production or diagnostic'
[[ $expected_avatar_dormancy =~ ^[01]$ ]] || \
    fail 'FAY_SOAK_EXPECT_AVATAR_DORMANCY must be 0 or 1'
[[ $expected_avatar_dormancy_delay =~ ^[1-9][0-9]*$ ]] || \
    fail 'FAY_SOAK_EXPECT_AVATAR_DORMANCY_DELAY_SECONDS must be an integer from 2 through 60'
if (( expected_avatar_dormancy_delay < 2 || expected_avatar_dormancy_delay > 60 )); then
    fail 'FAY_SOAK_EXPECT_AVATAR_DORMANCY_DELAY_SECONDS must be an integer from 2 through 60'
fi
if [[ $expected_scene_only == 1 && $expected_avatar_dormancy == 1 ]]; then
    fail 'scene-only and avatar dormancy evidence are mutually exclusive'
fi
if [[ -n $runtime_log_start_line && ! $runtime_log_start_line =~ ^[1-9][0-9]*$ ]]; then
    fail 'FAY_SOAK_RUNTIME_LOG_START_LINE must be a positive integer when supplied'
fi
[[ $max_dormancy_cancellations =~ ^(0|[1-9][0-9]*)$ ]] || \
    fail 'FAY_SOAK_MAX_DORMANCY_CANCELLATIONS must be a non-negative integer'
if [[ $expected_avatar_dormancy == 1 && -z $runtime_log_start_line ]]; then
    fail 'dormancy evidence requires FAY_SOAK_RUNTIME_LOG_START_LINE from the guarded launcher'
fi
(( duration >= turn_count && turn_count <= 100 )) || \
    fail 'duration must cover every turn and turn count must not exceed 100'
if (( turn_count == 0 && duration < idle_warmup_seconds + idle_measurement_seconds )); then
    fail 'an idle diagnostic must include its configured warm-up and measurement windows'
fi
if [[ $require_rendered == 1 && -z $expected_unreal_input ]]; then
    fail 'FAY_SOAK_EXPECTED_UNREAL_EXE is required for a rendered soak'
fi
if [[ -n $expected_unreal_starttime && ! $expected_unreal_starttime =~ ^[0-9]+$ ]]; then
    fail 'FAY_SOAK_EXPECTED_UNREAL_STARTTIME must be a Linux process starttime'
fi
if [[ $require_rendered == 1 && -z $expected_unreal_starttime ]]; then
    fail 'FAY_SOAK_EXPECTED_UNREAL_STARTTIME is required for a rendered soak'
fi
if [[ -n $expected_fay_starttime && ! $expected_fay_starttime =~ ^[0-9]+$ ]]; then
    fail 'FAY_SOAK_EXPECTED_FAY_STARTTIME must be a Linux process starttime'
fi
[[ $expected_character == Ada || $expected_character == Aoi ]] || \
    fail 'FAY_SOAK_EXPECTED_CHARACTER must name a reviewed packaged profile'
if [[ -n $preflight_package_seal_sha256 &&
    ! $preflight_package_seal_sha256 =~ ^[0-9a-f]{64}$ ]]; then
    fail 'FAY_SOAK_PREFLIGHT_PACKAGE_SEAL_SHA256 must be a lowercase SHA-256 digest'
fi

for command_name in awk cp curl date dirname grep head journalctl mkdir nvidia-smi ps \
    readlink realpath sed sha256sum sleep ss tail tr wc; do
    command -v "$command_name" >/dev/null 2>&1 || fail "missing command: $command_name"
done

output_dir=$(mkdir -p "$output_input" && cd "$output_input" && pwd -P)
case "$output_dir/" in
    */media-private/*|*/logs-private/*) ;;
    *) fail 'output directory must be below a private media or log root' ;;
esac
for evidence_name in runtime-argv.nul runtime-argv.txt package-identity.txt \
    runtime-new.log kernel-new.log runtime-failures.log kernel-failures.log \
    soak-metrics.tsv soak-summary.txt facial-summaries.log; do
    if [[ -e $output_dir/$evidence_name || -L $output_dir/$evidence_name ]]; then
        fail "refusing to overwrite existing soak evidence: $evidence_name"
    fi
done

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
    local pid=$1 expected_exe=$2 expected_starttime_value=$3
    local actual_exe actual_starttime
    actual_exe=$(readlink "/proc/$pid/exe" 2>/dev/null || true)
    [[ $actual_exe == "$expected_exe" ]] || return 1
    actual_starttime=$(read_process_starttime "$pid" || true)
    [[ -n $actual_starttime && $actual_starttime == "$expected_starttime_value" ]]
}

unreal_exe=$(readlink "/proc/$unreal_pid/exe" 2>/dev/null || true)
unreal_starttime=$(read_process_starttime "$unreal_pid" || true)
fay_exe=$(readlink "/proc/$fay_pid/exe" 2>/dev/null || true)
fay_starttime=$(read_process_starttime "$fay_pid" || true)
[[ $unreal_exe == */FayAvatarRuntime && -n $unreal_starttime ]] || \
    fail 'UNREAL_PID is not a stable FayAvatarRuntime process'
[[ $fay_exe == */python* && -n $fay_starttime ]] || \
    fail 'FAY_PID is not a stable Python process'
if [[ -n $expected_unreal_input ]]; then
    expected_unreal_exe=$(realpath "$expected_unreal_input")
    [[ $unreal_exe == "$expected_unreal_exe" ]] || \
        fail 'UNREAL_PID does not match FAY_SOAK_EXPECTED_UNREAL_EXE'
fi
if [[ -n $expected_unreal_starttime && $unreal_starttime != "$expected_unreal_starttime" ]]; then
    fail 'UNREAL_PID does not match FAY_SOAK_EXPECTED_UNREAL_STARTTIME'
fi
if [[ -n $expected_fay_input ]]; then
    expected_fay_exe=$(realpath "$expected_fay_input")
    [[ $fay_exe == "$expected_fay_exe" ]] || \
        fail 'FAY_PID does not match FAY_SOAK_EXPECTED_FAY_EXE'
fi
if [[ -n $expected_fay_starttime && $fay_starttime != "$expected_fay_starttime" ]]; then
    fail 'FAY_PID does not match FAY_SOAK_EXPECTED_FAY_STARTTIME'
fi
process_matches_identity "$unreal_pid" "$unreal_exe" "$unreal_starttime" || \
    fail 'UNREAL_PID changed identity during validation'
process_matches_identity "$fay_pid" "$fay_exe" "$fay_starttime" || \
    fail 'FAY_PID changed identity during validation'

runtime_argv_nul="$output_dir/runtime-argv.nul"
runtime_argv_text="$output_dir/runtime-argv.txt"
cp -- "/proc/$unreal_pid/cmdline" "$runtime_argv_nul"
process_matches_identity "$unreal_pid" "$unreal_exe" "$unreal_starttime" || \
    fail 'UNREAL_PID changed identity while its command line was captured'
mapfile -d '' -t unreal_argv <"$runtime_argv_nul"
(( ${#unreal_argv[@]} > 0 )) || fail 'UNREAL_PID has an empty command line'
argv_has_exact() {
    local expected=${1,,} argument
    for argument in "${unreal_argv[@]}"; do
        [[ ${argument,,} == "$expected" ]] && return 0
    done
    return 1
}

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
has_dormancy_argument=0
for argument in "${unreal_argv[@]}"; do
    classify_diagnostic_override "$argument"
    lower_argument=${argument,,}
    if [[ $lower_argument == -fayavatardormancy=* ||
        $lower_argument == -fayavatardormancydelay=* ]]; then
        has_dormancy_argument=1
    fi
done

reviewed_runtime_argv=(
    "$unreal_exe"
    FayAvatarRuntime
    -vulkan
    -log
    "-FayCharacter=$expected_character"
    -FayResetSpeechCache=0
    -FayTrimSpeechMemory=1
    -ResX=1280
    -ResY=720
    -Windowed
    -WinX=0
    -WinY=0
)
if (( expected_avatar_dormancy == 1 )); then
    reviewed_runtime_argv+=(
        -FayAvatarDormancy=1
        -FayAvatarDormancyDelay=5
    )
fi
runtime_matches_reviewed_policy=1
if (( ${#unreal_argv[@]} != ${#reviewed_runtime_argv[@]} )); then
    runtime_matches_reviewed_policy=0
else
    for ((argv_index = 0; argv_index < ${#reviewed_runtime_argv[@]}; ++argv_index)); do
        if [[ ${unreal_argv[$argv_index]} != "${reviewed_runtime_argv[$argv_index]}" ]]; then
            runtime_matches_reviewed_policy=0
            break
        fi
    done
fi
(( runtime_matches_reviewed_policy == 1 )) || \
    add_diagnostic_override nonreviewed-runtime-arguments
if (( expected_res_x != 1280 || expected_res_y != 720 )); then
    add_diagnostic_override resolution-override
fi
if (( expected_avatar_dormancy == 1 && expected_avatar_dormancy_delay != 5 )); then
    add_diagnostic_override dormancy-policy-override
fi
if (( max_dormancy_cancellations != 0 )); then
    add_diagnostic_override dormancy-cancellation-override
fi
if (( max_tail_rss_growth_kb != 131072 ||
    (turn_count > 0 && max_rss_kb != 3145728) ||
    min_mem_available_kb != 50331648 || max_gpu_utilization_percent != 95 )); then
    add_diagnostic_override resource-policy-override
fi
if ! awk -v observed="$max_face_p95_ms" 'BEGIN {exit !(observed == 20)}'; then
    add_diagnostic_override facial-performance-policy-override
fi
if (( require_rendered != 1 || require_normal_audio != 1 ||
    require_procedural_actions != 1 )); then
    add_diagnostic_override incomplete-production-requirements
fi
[[ -n $preflight_package_seal_sha256 ]] || \
    add_diagnostic_override missing-guarded-preflight

if [[ -z $evidence_mode ]]; then
    if (( turn_count == 0 || expected_scene_only == 1 ||
        ${#diagnostic_overrides[@]} != 0 )); then
        evidence_mode=diagnostic
    else
        evidence_mode=production
    fi
fi
if [[ $evidence_mode == production && ( $turn_count == 0 ||
    $expected_scene_only == 1 ) ]]; then
    fail 'production qualification requires at least one turn and a real avatar scene'
fi
if [[ $evidence_mode == production && ${#diagnostic_overrides[@]} -ne 0 ]]; then
    fail "production qualification refuses policy override: ${diagnostic_overrides[*]}"
fi

if [[ $require_rendered == 1 ]]; then
    argv_has_exact '-vulkan' || fail 'rendered soak requires an explicit -vulkan argument'
    argv_has_exact "-ResX=$expected_res_x" || \
        fail "rendered soak requires -ResX=$expected_res_x"
    argv_has_exact "-ResY=$expected_res_y" || \
        fail "rendered soak requires -ResY=$expected_res_y"
    if argv_has_exact '-nullrhi'; then
        fail 'rendered soak refuses -nullrhi'
    fi
fi
if [[ $expected_scene_only == 1 ]]; then
    argv_has_exact '-FaySceneOnly=1' || \
        fail 'scene-only evidence requires the exact -FaySceneOnly=1 argument'
else
    if argv_has_exact '-FaySceneOnly=1'; then
        fail 'ordinary avatar evidence refuses an unexpected -FaySceneOnly=1 argument'
    fi
fi
if [[ $expected_avatar_dormancy == 1 ]]; then
    argv_has_exact '-FayAvatarDormancy=1' || \
        fail 'dormancy evidence requires the exact -FayAvatarDormancy=1 argument'
    argv_has_exact "-FayAvatarDormancyDelay=$expected_avatar_dormancy_delay" || \
        fail 'dormancy evidence requires the exact reviewed delay argument'
elif (( has_dormancy_argument == 1 )); then
    fail 'ordinary avatar evidence refuses unexpected dormancy arguments'
fi

runtime_root=$(realpath "$(dirname "$unreal_exe")/../..")
runtime_log="$runtime_root/Saved/Logs/FayAvatarRuntime.log"
[[ -f $runtime_log ]] || fail "Unreal runtime log is missing: $runtime_log"
if [[ -n $runtime_log_start_line ]]; then
    runtime_log_start_lines=$((runtime_log_start_line - 1))
else
    runtime_log_start_lines=$(wc -l <"$runtime_log")
fi

runtime_argv_sha256=$(sha256sum -- "$runtime_argv_nul")
runtime_argv_sha256=${runtime_argv_sha256%% *}
{
    printf 'Exact byte representation: runtime-argv.nul (NUL-delimited).\n'
    for ((argv_index = 0; argv_index < ${#unreal_argv[@]}; ++argv_index)); do
        printf 'argv[%d]=%q\n' "$argv_index" "${unreal_argv[$argv_index]}"
    done
} >"$runtime_argv_text"

package_root=$(realpath "$runtime_root/..")
package_launcher="$package_root/FayAvatarRuntime-Arm64.sh"
package_seal="$package_root/.ue5-spark-package.sha256"
character_manifest="$package_root/.ue5-spark-characters.json"
[[ -f $package_launcher && ! -L $package_launcher ]] || \
    fail 'the package launcher is missing or is not a regular file'
[[ -s $package_seal && ! -L $package_seal ]] || \
    fail 'the package deep-verification seal is missing or unsafe'
[[ $(head -n1 "$package_seal") == '# UE5-SPARK-PACKAGE-SEAL-V1' ]] || \
    fail 'the package deep-verification seal has an unsupported schema'
package_seal_sha256=$(sha256sum -- "$package_seal")
package_seal_sha256=${package_seal_sha256%% *}
if [[ -n $preflight_package_seal_sha256 &&
    $package_seal_sha256 != "$preflight_package_seal_sha256" ]]; then
    fail 'the package seal changed after guarded preflight verification'
fi
package_executable_sha256=$(sha256sum -- "$unreal_exe")
package_executable_sha256=${package_executable_sha256%% *}
package_launcher_sha256=$(sha256sum -- "$package_launcher")
package_launcher_sha256=${package_launcher_sha256%% *}
package_seal_record_count=$(( $(wc -l <"$package_seal") - 1 ))
(( package_seal_record_count > 0 )) || fail 'the package seal contains no file records'
character_manifest_sha256=absent
if [[ -e $character_manifest || -L $character_manifest ]]; then
    [[ -f $character_manifest && ! -L $character_manifest ]] || \
        fail 'the packaged character manifest is not a regular file'
    character_manifest_sha256=$(sha256sum -- "$character_manifest")
    character_manifest_sha256=${character_manifest_sha256%% *}
fi
package_identity="$output_dir/package-identity.txt"
{
    printf 'schema=1\n'
    printf 'package_root=%s\n' "$package_root"
    printf 'runtime_executable=%s\n' "$unreal_exe"
    printf 'runtime_executable_sha256=%s\n' "$package_executable_sha256"
    printf 'launcher_sha256=%s\n' "$package_launcher_sha256"
    printf 'seal_schema=UE5-SPARK-PACKAGE-SEAL-V1\n'
    printf 'seal_sha256=%s\n' "$package_seal_sha256"
    printf 'seal_record_count=%s\n' "$package_seal_record_count"
    printf 'character_manifest_sha256=%s\n' "$character_manifest_sha256"
} >"$package_identity"

if (( ${#diagnostic_overrides[@]} == 0 )); then
    diagnostic_override_summary=none
else
    diagnostic_override_summary=$(IFS=,; printf '%s' "${diagnostic_overrides[*]}")
fi

runtime_new_log="$output_dir/runtime-new.log"
kernel_new_log="$output_dir/kernel-new.log"
runtime_failures_log="$output_dir/runtime-failures.log"
kernel_failures_log="$output_dir/kernel-failures.log"
kernel_cursor=$provided_kernel_cursor
if [[ -z $kernel_cursor ]]; then
    kernel_cursor=$(journalctl -k -n 0 --show-cursor --no-pager 2>/dev/null |
        sed -n 's/^-- cursor: //p' | tail -n1)
fi
[[ -n $kernel_cursor ]] || fail 'could not capture the kernel journal cursor'

capture_evidence() {
    tail -n "+$((runtime_log_start_lines + 1))" "$runtime_log" >"$runtime_new_log" 2>/dev/null || true
    journalctl -k --after-cursor "$kernel_cursor" --no-pager >"$kernel_new_log" 2>/dev/null || true
}
trap 'capture_evidence' EXIT

listener_owned_by_fay() {
    local port=$1
    local listeners
    process_matches_identity "$fay_pid" "$fay_exe" "$fay_starttime" || \
        fail 'FAY_PID changed identity during listener validation'
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
    process_matches_identity "$unreal_pid" "$unreal_exe" "$unreal_starttime" || \
        fail 'Unreal exited or its PID was reused before resource sampling'
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
        process_matches_identity "$unreal_pid" "$unreal_exe" "$unreal_starttime" || \
            fail 'Unreal exited or its PID was reused during the idle diagnostic'
        process_matches_identity "$fay_pid" "$fay_exe" "$fay_starttime" || \
            fail 'Fay changed identity during the idle diagnostic'
        for fay_port in 5000 5010 8766 10002; do
            listener_owned_by_fay "$fay_port"
        done
        sleep 5
        sample_resources 0
    done
else
    for ((turn = 1; turn <= turn_count; ++turn)); do
        process_matches_identity "$unreal_pid" "$unreal_exe" "$unreal_starttime" || \
            fail "Unreal exited or its PID was reused before turn $turn"
        process_matches_identity "$fay_pid" "$fay_exe" "$fay_starttime" || \
            fail "Fay changed identity before turn $turn"
        for fay_port in 5000 5010 8766 10002; do
            listener_owned_by_fay "$fay_port"
        done
        message=${messages[$(((turn - 1) % ${#messages[@]}))]}
        payload=$(printf '{"user":"User","text":"%s"}' "$message")
        response=$(curl -fsS --noproxy '*' --max-time 60 -H 'Content-Type: application/json' \
            --data "$payload" "http://${fay_host}:5000/transparent-pass") || \
            fail "Fay request failed on turn $turn"
        [[ $response == *'"code":200'* ]] || fail "Fay rejected turn $turn"
        sample_resources "$turn"

        target=$((start + (duration * turn / turn_count)))
        while (( $(date +%s) < target )); do
            process_matches_identity "$unreal_pid" "$unreal_exe" "$unreal_starttime" || \
                fail "Unreal exited or its PID was reused after turn $turn"
            process_matches_identity "$fay_pid" "$fay_exe" "$fay_starttime" || \
                fail "Fay changed identity after turn $turn"
            sleep 5
            sample_resources "$turn"
        done
    done
fi

end=$(date +%s)
capture_evidence
trap - EXIT
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
actual_elapsed_seconds=$((end - start))
half_duration=$((actual_elapsed_seconds / 2))
tail_start_rss=$(awk -v half="$half_duration" 'NR>1 && $1>=half {print $3; exit}' "$metrics")
[[ $tail_start_rss =~ ^[0-9]+$ ]] || tail_start_rss=$first_rss
tail_rss_growth_kb=$((last_rss - tail_start_rss))
(( tail_rss_growth_kb < 0 )) && tail_rss_growth_kb=0

status=passed
if (( turn_count == 0 )); then
    run_mode=idle
    if [[ $expected_scene_only == 1 ]]; then
        run_mode=scene-only-idle
    elif [[ $expected_avatar_dormancy == 1 ]]; then
        run_mode=dormant-idle
    fi
    idle_measurement_window_end=$actual_elapsed_seconds
    idle_measurement_window_start=$((idle_measurement_window_end - idle_measurement_seconds))
    if (( idle_measurement_window_start < idle_warmup_seconds )); then
        idle_measurement_window_start=$idle_warmup_seconds
    fi
    idle_measurement_start_rss=$(awk -v window="$idle_measurement_window_start" \
        'NR>1 && $1>=window {print $3; exit}' "$metrics")
    [[ $idle_measurement_start_rss =~ ^[0-9]+$ ]] || \
        fail 'idle measurement did not contain a post-warm-up RSS sample'
    idle_measurement_sample_count=$(awk -v window="$idle_measurement_window_start" \
        'NR>1 && $1>=window {count++} END {print count+0}' "$metrics")
    (( idle_measurement_sample_count >= 2 )) || \
        fail 'idle measurement window contained fewer than two resource samples'
    idle_measurement_growth_kb=$((last_rss - idle_measurement_start_rss))
    (( idle_measurement_growth_kb < 0 )) && idle_measurement_growth_kb=0
    idle_slope_kb_per_second=$(awk -v window="$idle_measurement_window_start" '
        NR > 1 && $1 >= window {
            n++; sx += $1; sy += $3; sxx += $1 * $1; sxy += $1 * $3
        }
        END {
            denominator = n * sxx - sx * sx
            if (n < 2 || denominator == 0) print "0.00"
            else printf "%.2f\n", (n * sxy - sx * sy) / denominator
        }' "$metrics")
    idle_final_window_start=$idle_measurement_window_start
    idle_final_slope_kb_per_second=$idle_slope_kb_per_second
    idle_step_like_growth_count=$(awk -v window="$idle_measurement_window_start" '
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
    if [[ $expected_avatar_dormancy == 1 ]]; then
        run_mode=dormant-speech
    fi
    idle_measurement_start_rss=0
    idle_measurement_sample_count=0
    idle_measurement_growth_kb=0
    idle_slope_kb_per_second=0.00
    idle_final_window_start=0
    idle_final_slope_kb_per_second=0.00
    idle_step_like_growth_count=0
    idle_measurement_window_start=0
    idle_measurement_window_end=0
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
frame_rate_policy_enforced_count=$(grep -Fc \
    'Enforced reviewed runtime frame cap at 30.00 FPS after GameUserSettings initialization.' \
    "$runtime_new_log" || true)
game_user_settings_policy_verified_count=$(grep -Fc \
    'Verified project-owned FayGameUserSettings runtime policy.' \
    "$runtime_new_log" || true)
frame_rate_policy_violation_count=$(grep -Ec \
    'Reviewed runtime frame cap policy drifted|Could not enforce the reviewed 30.00 FPS runtime frame cap|The packaged runtime is not using project-owned FayGameUserSettings' \
    "$runtime_new_log" || true)
if (( game_user_settings_policy_verified_count != 1 ||
    frame_rate_policy_enforced_count != 1 || frame_rate_policy_violation_count != 0 )); then
    status=failed
fi
dormancy_configured_count=$(grep -Fc \
    'Configured fail-open dormancy for the reviewed avatar.' \
    "$runtime_new_log" || true)
dormancy_enter_count=$(grep -Fc 'Entered MetaHuman idle dormancy' \
    "$runtime_new_log" || true)
dormancy_wake_count=$(grep -Fc 'Woke the MetaHuman from idle dormancy' \
    "$runtime_new_log" || true)
dormancy_cancel_count=$(grep -Fc 'Cancelled MetaHuman dormancy preparation' \
    "$runtime_new_log" || true)
dormancy_enabled_marker="MetaHuman idle dormancy: enabled (delay=${expected_avatar_dormancy_delay}.00 seconds, neutral_prepare_frames=2)."
dormancy_disabled_marker="MetaHuman idle dormancy: disabled (delay=${expected_avatar_dormancy_delay}.00 seconds, neutral_prepare_frames=2)."
dormancy_health_marker='Dormant Live Link health audit ceiling: 1.00 seconds.'
dormancy_enabled_count=$(grep -Fc "$dormancy_enabled_marker" "$runtime_new_log" || true)
dormancy_disabled_count=$(grep -Fc "$dormancy_disabled_marker" "$runtime_new_log" || true)
dormancy_health_count=$(grep -Fc "$dormancy_health_marker" "$runtime_new_log" || true)
dormancy_latest_transition_line=$(grep -E \
    'Entered MetaHuman idle dormancy|Woke the MetaHuman from idle dormancy' \
    "$runtime_new_log" | tail -n1 || true)
dormancy_latest_transition=none
if [[ $dormancy_latest_transition_line == *'Entered MetaHuman idle dormancy'* ]]; then
    dormancy_latest_transition=entered
elif [[ $dormancy_latest_transition_line == *'Woke the MetaHuman from idle dormancy'* ]]; then
    dormancy_latest_transition=woke
fi
dormancy_transition_order_failures=0
dormancy_unexpected_wake_reason_count=0
dormancy_expected_transition=enter
while IFS= read -r transition_line; do
    if [[ $transition_line == *'Entered MetaHuman idle dormancy'* ]]; then
        if [[ $dormancy_expected_transition != enter ]]; then
            ((++dormancy_transition_order_failures))
        fi
        dormancy_expected_transition=wake
    elif [[ $transition_line == *'Woke the MetaHuman from idle dormancy'* ]]; then
        if [[ $dormancy_expected_transition != wake ]]; then
            ((++dormancy_transition_order_failures))
        fi
        if [[ $transition_line != *'Woke the MetaHuman from idle dormancy (accepted Fay message).'* ]]; then
            ((++dormancy_unexpected_wake_reason_count))
        fi
        dormancy_expected_transition=enter
    fi
done < <(grep -E \
    'Entered MetaHuman idle dormancy|Woke the MetaHuman from idle dormancy' \
    "$runtime_new_log" || true)
if [[ $expected_avatar_dormancy == 1 && $dormancy_latest_transition != entered ]]; then
    ((++dormancy_transition_order_failures))
fi
if [[ $expected_avatar_dormancy == 1 ]]; then
    if (( dormancy_enabled_count != 1 || dormancy_disabled_count != 0 ||
        dormancy_health_count != 1 ||
        dormancy_configured_count < 1 || dormancy_enter_count < 1 )); then
        status=failed
    fi
    if (( dormancy_wake_count != turn_count ||
        dormancy_enter_count != dormancy_wake_count + 1 ||
        dormancy_cancel_count > max_dormancy_cancellations ||
        dormancy_transition_order_failures > 0 ||
        dormancy_unexpected_wake_reason_count > 0 )); then
        status=failed
    fi
else
    if (( dormancy_disabled_count != 1 || dormancy_enabled_count != 0 ||
        dormancy_enter_count > 0 || dormancy_wake_count > 0 ||
        dormancy_cancel_count > 0 )); then
        status=failed
    fi
fi
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
        explain_ardy_start_count=$(grep -Fci \
            "Using ARDY generated motion provider for 'explain' (bounded_seconds=" \
            "$runtime_new_log" || true)
        explain_ardy_complete_count=$(grep -Fci \
            "Completed bounded ARDY action 'explain' and returned to baked idle." \
            "$runtime_new_log" || true)
        explain_ardy_completed=0
        if (( explain_ardy_start_count >= 1 && explain_ardy_complete_count >= 1 )); then
            explain_ardy_completed=1
        fi
        if (( explain_fallback_count + explain_ardy_completed < 1 )); then
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

if [[ $evidence_mode == production ]]; then
    evidence_class=production-qualification
    if [[ $status == passed ]]; then
        production_qualification=pending-verified-teardown-and-seal
    else
        production_qualification=failed
    fi
    result_scope=production-candidate-awaiting-verified-teardown-and-seal
    verified_teardown_and_fay_survival=pending
    post_teardown_package_verification=pending
else
    evidence_class=diagnostic
    production_qualification=not-claimed
    result_scope=diagnostic-only-not-production-qualification
    verified_teardown_and_fay_survival=not-verified-by-inner-harness
    post_teardown_package_verification=not-verified-by-inner-harness
fi

{
    printf 'status=%s\n' "$status"
    printf 'mode=%s\n' "$run_mode"
    printf 'evidence_class=%s\n' "$evidence_class"
    printf 'result_scope=%s\n' "$result_scope"
    printf 'production_qualification=%s\n' "$production_qualification"
    printf 'verified_teardown_and_fay_survival=%s\n' \
        "$verified_teardown_and_fay_survival"
    printf 'post_teardown_package_verification=%s\n' \
        "$post_teardown_package_verification"
    printf 'runtime_exit_status=pending\n'
    printf 'runtime_forced_kill=pending\n'
    printf 'post_teardown_package_seal_sha256=pending\n'
    printf 'post_teardown_runtime_failure_count=pending\n'
    printf 'post_teardown_kernel_failure_count=pending\n'
    printf 'diagnostic_overrides=%s\n' "$diagnostic_override_summary"
    printf 'duration_seconds=%s\n' "$((end - start))"
    printf 'turns=%s\n' "$turn_count"
    printf 'rendered_required=%s\n' "$require_rendered"
    printf 'normal_audio_required=%s\n' "$require_normal_audio"
    printf 'procedural_actions_required=%s\n' "$require_procedural_actions"
    printf 'avatar_dormancy_expected=%s\n' "$expected_avatar_dormancy"
    printf 'avatar_dormancy_delay_seconds=%s\n' "$expected_avatar_dormancy_delay"
    printf 'unreal_pid=%s\n' "$unreal_pid"
    printf 'unreal_process_starttime=%s\n' "$unreal_starttime"
    printf 'fay_pid=%s\n' "$fay_pid"
    printf 'fay_executable=%s\n' "$fay_exe"
    printf 'fay_process_starttime=%s\n' "$fay_starttime"
    printf 'runtime_argv_exact_file=runtime-argv.nul\n'
    printf 'runtime_argv_readable_file=runtime-argv.txt\n'
    printf 'runtime_argv_sha256=%s\n' "$runtime_argv_sha256"
    printf 'package_identity_file=package-identity.txt\n'
    printf 'package_executable_sha256=%s\n' "$package_executable_sha256"
    printf 'package_seal_sha256=%s\n' "$package_seal_sha256"
    printf 'package_seal_record_count=%s\n' "$package_seal_record_count"
    printf 'runtime_log_start_line=%s\n' "$((runtime_log_start_lines + 1))"
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
    printf 'game_user_settings_policy_verified_count=%s\n' \
        "$game_user_settings_policy_verified_count"
    printf 'frame_rate_policy_enforced_count=%s\n' \
        "$frame_rate_policy_enforced_count"
    printf 'frame_rate_policy_violation_count=%s\n' \
        "$frame_rate_policy_violation_count"
    printf 'dormancy_configured_count=%s\n' "$dormancy_configured_count"
    printf 'dormancy_enabled_marker_count=%s\n' "$dormancy_enabled_count"
    printf 'dormancy_disabled_marker_count=%s\n' "$dormancy_disabled_count"
    printf 'dormancy_health_marker_count=%s\n' "$dormancy_health_count"
    printf 'dormancy_enter_count=%s\n' "$dormancy_enter_count"
    printf 'dormancy_wake_count=%s\n' "$dormancy_wake_count"
    printf 'dormancy_cancel_count=%s\n' "$dormancy_cancel_count"
    printf 'dormancy_cancel_limit=%s\n' "$max_dormancy_cancellations"
    printf 'dormancy_latest_transition=%s\n' "$dormancy_latest_transition"
    printf 'dormancy_transition_order_failures=%s\n' \
        "$dormancy_transition_order_failures"
    printf 'dormancy_unexpected_wake_reason_count=%s\n' \
        "$dormancy_unexpected_wake_reason_count"
    printf 'procedural_action_failures=%s\n' "$procedural_action_failures"
    printf 'runtime_failure_count=%s\n' "$runtime_failure_count"
    printf 'kernel_failure_count=%s\n' "$kernel_failure_count"
    printf 'idle_warmup_seconds=%s\n' "$idle_warmup_seconds"
    printf 'idle_measurement_seconds=%s\n' "$idle_measurement_seconds"
    printf 'idle_measurement_window_start_seconds=%s\n' \
        "$idle_measurement_window_start"
    printf 'idle_measurement_window_end_seconds=%s\n' \
        "$idle_measurement_window_end"
    printf 'idle_measurement_sample_count=%s\n' "$idle_measurement_sample_count"
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
if [[ $evidence_mode == diagnostic ]]; then
    printf 'Diagnostic-only avatar run passed; no production qualification is claimed.\n'
elif (( turn_count == 0 )); then
    printf 'Idle avatar diagnostic passed over %s second(s).\n' "$((end - start))"
else
    printf 'Soak harness passed: %s turn(s) over %s second(s); production qualification awaits owning-wrapper teardown and seal verification.\n' \
        "$turn_count" "$((end - start))"
fi
printf 'Private metrics: %s\n' "$metrics"
