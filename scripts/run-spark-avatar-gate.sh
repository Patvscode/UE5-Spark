#!/usr/bin/env bash
set -euo pipefail
umask 077
last_error=''

usage() {
    printf 'Usage: %s PACKAGE_LAUNCHER FAY_PID PRIVATE_GATE_DIR DURATION_SECONDS TURN_COUNT\n' \
        "${0##*/}" >&2
    printf 'The only pausable user unit is codex-studio-voxtral-realtime.service.\n' >&2
    printf 'Soak policy is inherited through the existing FAY_SOAK_* environment.\n' >&2
}

fail() {
    last_error=$*
    printf 'error: %s\n' "$*" >&2
    exit 1
}

if (( $# != 5 )); then
    usage
    exit 64
fi
if [[ $(uname -s) != Linux || $(uname -m) != aarch64 ]]; then
    fail 'the guarded avatar gate requires Linux/aarch64 on DGX Spark'
fi
if (( ${EUID:-$(id -u)} == 0 )); then
    fail 'run the guarded avatar gate as the normal workspace owner, not root'
fi

readonly VOXTRAL_UNIT='codex-studio-voxtral-realtime.service'
readonly ARDY_CONTAINER='ue5-spark-ardy'
readonly ARDY_IMAGE='ue5-spark-ardy:0.3.0'

package_launcher_input=$1
fay_pid=$2
gate_root_input=$3
duration_seconds=$4
turn_count=$5

[[ $fay_pid =~ ^[1-9][0-9]*$ ]] || fail 'FAY_PID must be a positive integer'
[[ $duration_seconds =~ ^[1-9][0-9]*$ ]] || \
    fail 'DURATION_SECONDS must be a positive integer'
[[ $turn_count =~ ^[0-9]+$ ]] || fail 'TURN_COUNT must be a non-negative integer'

for command_name in awk bash basename chmod curl date dirname docker find flock grep id \
    kill ln mkdir mktemp python3 readlink realpath rm seq setsid sha256sum sleep \
    sort ss systemctl timeout tr; do
    command -v "$command_name" >/dev/null 2>&1 || fail "missing command: $command_name"
done

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
soak_runner="$script_dir/run-spark-avatar-soak.sh"
package_verifier="$script_dir/verify-cooked-package.sh"
runner_bash_exe=$(readlink -f "$(command -v bash)")
[[ -x $soak_runner && ! -L $soak_runner ]] || \
    fail 'the guarded rendered-soak runner is missing or unsafe'
[[ -x $package_verifier && ! -L $package_verifier ]] || \
    fail 'the cooked-package verifier is missing or unsafe'
[[ -x $runner_bash_exe ]] || fail 'the canonical Bash executable is unavailable'

package_launcher_dir=$(cd "$(dirname "$package_launcher_input")" && pwd -P)
package_launcher="$package_launcher_dir/$(basename "$package_launcher_input")"
[[ -x $package_launcher && ! -L $package_launcher && \
    ${package_launcher##*/} == FayAvatarRuntime-Arm64.sh ]] || \
    fail 'expected a real executable FayAvatarRuntime-Arm64.sh package launcher'
expected_unreal_exe=$(realpath \
    "$package_launcher_dir/FayAvatarRuntime/Binaries/LinuxArm64/FayAvatarRuntime")
[[ -x $expected_unreal_exe && ! -L $expected_unreal_exe ]] || \
    fail 'the packaged Unreal executable is missing or unsafe'

gate_parent_input=$(dirname "$gate_root_input")
gate_name=$(basename "$gate_root_input")
[[ $gate_name =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$ ]] || \
    fail 'PRIVATE_GATE_DIR must end in a simple unique run name'
[[ -d $gate_parent_input ]] || fail 'the private gate parent directory does not exist'
gate_parent=$(cd "$gate_parent_input" && pwd -P)
gate_root="$gate_parent/$gate_name"
case "$gate_root/" in
    */logs-private/*)
        private_root=${gate_root%%/logs-private/*}/logs-private
        ;;
    */media-private/*)
        private_root=${gate_root%%/media-private/*}/media-private
        ;;
    *)
        fail 'PRIVATE_GATE_DIR must be below a private media or log root'
        ;;
esac
[[ -d $private_root && ! -L $private_root ]] || \
    fail 'the selected private evidence root is missing or unsafe'
[[ ! -e $gate_root && ! -L $gate_root ]] || \
    fail 'PRIVATE_GATE_DIR must not already exist; every gate requires unique evidence'

lock_file="$private_root/.spark-avatar-gate.lock"
[[ ! -L $lock_file ]] || fail 'the private gate lock path is a symlink'
exec 9>>"$lock_file"
chmod 600 "$lock_file"
flock -n 9 || fail 'another guarded avatar gate already owns this private evidence root'
[[ ! -e $gate_root && ! -L $gate_root ]] || \
    fail 'PRIVATE_GATE_DIR appeared while acquiring the gate lock'
mkdir -m 700 -- "$gate_root"
[[ $(cd "$gate_root" && pwd -P) == "$gate_root" ]] || \
    fail 'could not establish the exact private gate directory'

soak_output="$gate_root/soak"
runner_console="$gate_root/runner-console.log"

write_record() {
    local destination=$1
    shift
    local temporary
    [[ $destination == "$gate_root/"* && ! -e $destination && ! -L $destination ]] || \
        return 1
    temporary=$(mktemp "$gate_root/.record.XXXXXX") || return 1
    if ! printf '%s\n' "$@" >"$temporary"; then
        rm -f -- "$temporary"
        return 1
    fi
    chmod 600 "$temporary" || {
        rm -f -- "$temporary"
        return 1
    }
    if ! ln -- "$temporary" "$destination"; then
        rm -f -- "$temporary"
        return 1
    fi
    rm -f -- "$temporary"
}

capture_process_record() {
    local -n destination=$1
    local pid=$2 stat_line stat_fields
    destination=()
    [[ -r /proc/$pid/stat ]] || return 1
    IFS= read -r stat_line <"/proc/$pid/stat" || return 1
    stat_fields=${stat_line##*) }
    [[ $stat_fields != "$stat_line" ]] || return 1
    set -- $stat_fields
    [[ ${1:-} =~ ^[A-Za-z]$ && ${2:-} =~ ^[0-9]+$ && \
        ${3:-} =~ ^[0-9]+$ && ${4:-} =~ ^[0-9]+$ && \
        ${20:-} =~ ^[0-9]+$ ]] || return 1
    destination=("${1}" "${2}" "${3}" "${4}" "${20}")
}

read_process_starttime() {
    local -a record=()
    capture_process_record record "$1" || return 1
    [[ ${record[0]} != Z && ${record[0]} != X ]] || return 1
    printf '%s\n' "${record[4]}"
}

process_matches_identity() {
    local pid=$1 expected_exe=$2 expected_starttime=$3
    local actual_exe actual_starttime
    actual_exe=$(readlink -f "/proc/$pid/exe" 2>/dev/null || true)
    [[ $actual_exe == "$expected_exe" ]] || return 1
    actual_starttime=$(read_process_starttime "$pid" || true)
    [[ -n $actual_starttime && $actual_starttime == "$expected_starttime" ]]
}

process_matches_starttime() {
    local pid=$1 expected_starttime=$2 actual_starttime
    actual_starttime=$(read_process_starttime "$pid" || true)
    [[ -n $actual_starttime && $actual_starttime == "$expected_starttime" ]]
}

loopback_listener_owned_by_pid() {
    local port=$1 pid=$2 listeners line endpoint other_owner count=0
    listeners=$(ss -H -ltnp "sport = :$port" 2>/dev/null || true)
    while IFS= read -r line; do
        [[ -n $line ]] || continue
        [[ $line == *"pid=$pid,"* ]] || return 1
        other_owner=$(grep -oE 'pid=[0-9]+,' <<<"$line" | \
            grep -Fvx "pid=$pid," || true)
        [[ -z $other_owner ]] || return 1
        endpoint=$(awk '{print $4}' <<<"$line")
        case $endpoint in
            127.0.0.1:"$port"|'[::1]':"$port") ;;
            *) return 1 ;;
        esac
        count=$((count + 1))
    done <<<"$listeners"
    (( count == 1 ))
}

port_has_listener() {
    [[ -n $(ss -H -ltn "sport = :$1" 2>/dev/null || true) ]]
}

voxtral_is_fully_inactive() {
    local active_state main_pid
    active_state=$(systemctl --user show --property=ActiveState --value \
        "$VOXTRAL_UNIT" | tr -d '[:space:]') || return 1
    main_pid=$(systemctl --user show --property=MainPID --value \
        "$VOXTRAL_UNIT" | tr -d '[:space:]') || return 1
    [[ $active_state == inactive && $main_pid == 0 ]] || return 1
    ! port_has_listener 4395
}

fay_listener_host() {
    local port=$1 listeners endpoint host
    listeners=$(ss -H -ltnp "sport = :$port" 2>/dev/null || true)
    endpoint=$(awk -v owner="pid=$fay_pid," '$0 ~ owner {print $4; exit}' \
        <<<"$listeners")
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
    local port=$1 path=$2 expected_exe=$3 expected_starttime=$4
    local host formatted_host code
    process_matches_identity "$fay_pid" "$expected_exe" "$expected_starttime" || return 1
    host=$(fay_listener_host "$port") || return 1
    formatted_host=$(url_host "$host")
    code=$(curl --silent --show-error --output /dev/null --noproxy '*' \
        --connect-timeout 2 --max-time 5 --write-out '%{http_code}' \
        "http://$formatted_host:$port$path" 2>/dev/null || true)
    [[ $code =~ ^[23][0-9][0-9]$ ]] || return 1
    process_matches_identity "$fay_pid" "$expected_exe" "$expected_starttime"
}

validate_fay_identity() {
    local expected_exe=$1 expected_starttime=$2
    local -a listener_bindings=()
    process_matches_identity "$fay_pid" "$expected_exe" "$expected_starttime" || return 1
    capture_fay_listener_bindings listener_bindings || return 1
    fay_http_ready 5000 / "$expected_exe" "$expected_starttime" || return 1
    fay_http_ready 5010 / "$expected_exe" "$expected_starttime" || return 1
    fay_http_ready 8766 /sse "$expected_exe" "$expected_starttime" || return 1
}

probe_ardy_health() {
    local body
    local -a health=()
    body=$(curl --fail --silent --show-error --noproxy '*' \
        --connect-timeout 2 --max-time 5 http://127.0.0.1:8777/healthz) || return 1
    (( ${#body} <= 65536 )) || return 1
    mapfile -t health < <(
        printf '%s' "$body" | python3 -c '
import json
import math
import sys

value = json.load(sys.stdin)
expected_keys = {
    "status",
    "provider",
    "protocolVersion",
    "fps",
    "bufferFrames",
    "facialControl",
    "coordinateSystem",
    "source",
    "motionCatalog",
    "checkpoint",
    "embeddingCount",
    "p95GenerationMs",
}
if not isinstance(value, dict) or set(value) != expected_keys:
    raise SystemExit(1)
if value.get("status") != "ready":
    raise SystemExit(1)
if value.get("provider") != "ardy":
    raise SystemExit(1)
if type(value.get("protocolVersion")) is not int or value["protocolVersion"] != 2:
    raise SystemExit(1)
if type(value.get("fps")) is not int or value["fps"] != 20:
    raise SystemExit(1)
if type(value.get("bufferFrames")) is not int or value["bufferFrames"] != 8:
    raise SystemExit(1)
if value.get("facialControl") != "excluded":
    raise SystemExit(1)
expected_source = {
    "system": "nv-tlabs/ardy",
    "revision": "693f74d13b3d04a0a22ce127ee79c929dd89756b",
    "skeleton": "Core27",
    "jointOrder": [
        "Hips", "Spine", "Spine1", "Spine2", "Spine3", "Neck", "Head",
        "RightShoulder", "RightArm", "RightForeArm", "RightHand", "RightHandEnd",
        "RightHandThumb1", "LeftShoulder", "LeftArm", "LeftForeArm", "LeftHand",
        "LeftHandEnd", "LeftHandThumb1", "RightUpLeg", "RightLeg", "RightFoot",
        "RightToeBase", "LeftUpLeg", "LeftLeg", "LeftFoot", "LeftToeBase",
    ],
    "rotationSpace": "local",
    "quaternionOrder": "xyzw",
    "positionSpace": "global",
    "contactOrder": ["left_heel", "left_toe", "right_heel", "right_toe"],
}
expected_catalog = [
    "idle", "listen", "explain", "wave", "jog_in_place", "run_in_place",
    "jumping_jacks", "stretch", "dance_relaxed",
]
if value.get("coordinateSystem") != "ardy-rh-x-left-y-up-z-forward-meters":
    raise SystemExit(1)
if value.get("source") != expected_source or value.get("motionCatalog") != expected_catalog:
    raise SystemExit(1)
if value.get("checkpoint") != "ARDY-Core-RP-20FPS-Horizon8":
    raise SystemExit(1)
if type(value.get("embeddingCount")) is not int or value["embeddingCount"] != 9:
    raise SystemExit(1)
p95 = value.get("p95GenerationMs")
if isinstance(p95, bool) or not isinstance(p95, (int, float)):
    raise SystemExit(1)
p95 = float(p95)
if not math.isfinite(p95) or not 0.0 < p95 < 400.0:
    raise SystemExit(1)
print(value["provider"])
print(value["checkpoint"])
print(value["embeddingCount"])
print(p95)
'
    )
    (( ${#health[@]} == 4 )) || return 1
    printf '%s\n' "${health[@]}"
}

resolve_fixed_ardy_image_id() {
    local value
    value=$(docker image inspect --format '{{.Id}}' "$ARDY_IMAGE" 2>/dev/null) || return 1
    [[ $value =~ ^sha256:[0-9a-f]{64}$ ]] || return 1
    printf '%s\n' "$value"
}

ardy_image_tag_matches_expected() {
    local current_image_id
    current_image_id=$(resolve_fixed_ardy_image_id) || return 1
    [[ $current_image_id == "$ardy_expected_image_id" ]]
}

ardy_image_reference_is_expected() {
    local config_image_reference=$1 runtime_image_id=$2
    [[ $ardy_expected_image_id =~ ^sha256:[0-9a-f]{64}$ ]] || return 1
    [[ $runtime_image_id == "$ardy_expected_image_id" ]] || return 1
    [[ $config_image_reference == "$ARDY_IMAGE" ||
        $config_image_reference == "$ardy_expected_image_id" ]]
}

capture_ardy_snapshot() {
    local -n destination=$1
    local ardy_pid ardy_exe ardy_starttime
    local -a ardy_health=()
    destination=()
    mapfile -t destination < <(
        docker inspect --type container "$ARDY_CONTAINER" | python3 -c '
import json
import sys

records = json.load(sys.stdin)
if not isinstance(records, list) or len(records) != 1:
    raise SystemExit(1)
record = records[0]
mounts = [mount for mount in record.get("Mounts", []) if mount.get("Destination") == "/models"]
if len(mounts) != 1:
    raise SystemExit(1)
mount = mounts[0]
values = (
    record.get("Name", ""),
    record.get("Id", ""),
    record.get("Config", {}).get("Image", ""),
    record.get("State", {}).get("Running", False),
    record.get("State", {}).get("Pid", 0),
    record.get("State", {}).get("StartedAt", ""),
    record.get("HostConfig", {}).get("AutoRemove", False),
    record.get("HostConfig", {}).get("NetworkMode", ""),
    record.get("HostConfig", {}).get("ReadonlyRootfs", False),
    record.get("RestartCount", -1),
    mount.get("Source", ""),
    mount.get("RW", True),
    record.get("Image", ""),
)
for value in values:
    if isinstance(value, bool):
        print(str(value).lower())
    else:
        print(value)
'
    )
    (( ${#destination[@]} == 13 )) || return 1
    [[ ${destination[0]} == "/$ARDY_CONTAINER" ]] || return 1
    [[ ${destination[1]} =~ ^[0-9a-f]{64}$ ]] || return 1
    ardy_image_reference_is_expected "${destination[2]}" "${destination[12]}" || return 1
    [[ ${destination[3]} == true ]] || return 1
    [[ ${destination[4]} =~ ^[1-9][0-9]*$ && -n ${destination[5]} ]] || return 1
    [[ ${destination[6]} == true && ${destination[7]} == host && \
        ${destination[8]} == true && ${destination[9]} == 0 ]] || return 1
    [[ -d ${destination[10]} && ! -L ${destination[10]} && \
        ${destination[11]} == false ]] || return 1
    ardy_pid=${destination[4]}
    ardy_exe=$(readlink -f "/proc/$ardy_pid/exe" 2>/dev/null || true)
    ardy_starttime=$(read_process_starttime "$ardy_pid" || true)
    [[ $ardy_exe == */python* && -n $ardy_starttime ]] || return 1
    process_matches_identity "$ardy_pid" "$ardy_exe" "$ardy_starttime" || return 1
    loopback_listener_owned_by_pid 8777 "$ardy_pid" || return 1
    mapfile -t ardy_health < <(probe_ardy_health)
    (( ${#ardy_health[@]} == 4 )) || return 1
    destination+=("$ardy_exe" "$ardy_starttime" "${ardy_health[@]}")
}

arrays_are_equal() {
    local -n left=$1 right=$2
    local index
    (( ${#left[@]} == ${#right[@]} )) || return 1
    for index in "${!left[@]}"; do
        [[ ${left[$index]} == "${right[$index]}" ]] || return 1
    done
}

ardy_immutable_snapshot_is_equal() {
    local -n left=$1 right=$2
    local index
    (( ${#left[@]} == 19 && ${#right[@]} == 19 )) || return 1
    for index in $(seq 0 17); do
        [[ ${left[$index]} == "${right[$index]}" ]] || return 1
    done
}

array_digest() {
    local -n values=$1
    local digest
    digest=$(printf '%s\0' "${values[@]}" | sha256sum) || return 1
    printf '%s\n' "${digest%% *}"
}

capture_fay_listener_bindings() {
    local -n destination=$1
    local port listeners line local_endpoint peer_endpoint other_owner
    local per_port_count
    local -a unsorted=()
    destination=()
    for port in 5000 5010 8766 10002; do
        listeners=$(ss -H -ltnp "sport = :$port" 2>/dev/null || true)
        per_port_count=0
        while IFS= read -r line; do
            [[ -n $line ]] || continue
            [[ $line == *"pid=$fay_pid,"* ]] || return 1
            other_owner=$(grep -oE 'pid=[0-9]+,' <<<"$line" | \
                grep -Fvx "pid=$fay_pid," || true)
            [[ -z $other_owner ]] || return 1
            local_endpoint=$(awk '{print $4}' <<<"$line")
            peer_endpoint=$(awk '{print $5}' <<<"$line")
            [[ -n $local_endpoint && -n $peer_endpoint ]] || return 1
            unsorted+=("$port|$local_endpoint|$peer_endpoint")
            per_port_count=$((per_port_count + 1))
        done <<<"$listeners"
        (( per_port_count > 0 )) || return 1
    done
    mapfile -t destination < <(printf '%s\n' "${unsorted[@]}" | LC_ALL=C sort)
    (( ${#destination[@]} == ${#unsorted[@]} ))
}

probe_voxtral_health() {
    curl --fail --silent --show-error --output /dev/null --noproxy '*' \
        --connect-timeout 2 --max-time 5 http://127.0.0.1:4395/health
}

capture_voxtral_snapshot() {
    local -n destination=$1
    local main_pid process_exe process_starttime active_state sub_state
    destination=()
    systemctl --user is-active --quiet "$VOXTRAL_UNIT" || return 1
    active_state=$(systemctl --user show --property=ActiveState --value "$VOXTRAL_UNIT" | \
        tr -d '[:space:]')
    sub_state=$(systemctl --user show --property=SubState --value "$VOXTRAL_UNIT" | \
        tr -d '[:space:]')
    main_pid=$(systemctl --user show --property=MainPID --value "$VOXTRAL_UNIT" | \
        tr -d '[:space:]')
    [[ $active_state == active && $sub_state == running && \
        $main_pid =~ ^[1-9][0-9]*$ ]] || return 1
    process_exe=$(readlink -f "/proc/$main_pid/exe" 2>/dev/null || true)
    process_starttime=$(read_process_starttime "$main_pid" || true)
    [[ $process_exe == */python3.* && -n $process_starttime ]] || return 1
    process_matches_identity "$main_pid" "$process_exe" "$process_starttime" || return 1
    loopback_listener_owned_by_pid 4395 "$main_pid" || return 1
    probe_voxtral_health || return 1
    destination=("$VOXTRAL_UNIT" "$main_pid" "$process_exe" "$process_starttime")
}

find_expected_unreal_pids() {
    local process_dir process_exe
    for process_dir in /proc/[1-9]*; do
        process_exe=$(readlink -f "$process_dir/exe" 2>/dev/null || true)
        if [[ $process_exe == "$expected_unreal_exe" ]]; then
            printf '%s\n' "${process_dir##*/}"
        fi
    done
}

runner_leader_is_live() {
    (( runner_identity_committed == 1 )) || return 1
    [[ -n $runner_pid && -n $runner_starttime && -n $runner_exe ]] || return 1
    process_matches_identity "$runner_pid" "$runner_exe" "$runner_starttime"
}

cleanup_errors=()
note_cleanup_error() {
    cleanup_errors+=("$*")
    printf 'error: %s\n' "$*" >&2
}

runner_pid=''
runner_starttime=''
runner_session_id=''
runner_exe=''
runner_provisional_starttime=''
supervisor_pid=$BASHPID
runner_reaped=0
runner_exit_status=not-started
runner_forced_kill=0
runner_started=0
runner_identity_committed=0
runner_identity_capture_in_progress=0
deferred_signal_name=''
deferred_signal_status=0
fay_snapshot_ready=0
ardy_snapshot_ready=0
voxtral_snapshot_ready=0
voxtral_restore_required=0
voxtral_pause_verified=0
voxtral_pause_continuity=not-checked
voxtral_restore_verified=0
runner_group_post_exit_policy=not-reached
fay_identity_unchanged=not-checked
ardy_identity_unchanged=not-checked
ardy_image_tag_unchanged=not-checked
unreal_absent_after=not-checked
gate_started_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)
fay_exe=''
fay_starttime=''
declare -a ardy_before=()
declare -a ardy_after=()
declare -a voxtral_before=()
declare -a voxtral_after=()
declare -a fay_listener_bindings_before=()
declare -a fay_listener_bindings_after=()
declare -a runner_initial_record=()
declare -a runner_candidate_record=()
declare -a runner_confirm_record=()

cancel_and_reap_runner() {
    local wait_status=0 session_is_owned=0 leader_stopped=0
    (( runner_started == 1 && runner_reaped == 0 )) || return 0
    if (( runner_identity_committed == 1 )) && \
        [[ $runner_session_id =~ ^[1-9][0-9]*$ && \
        $runner_session_id == "$runner_pid" ]]; then
        session_is_owned=1
    fi
    if (( session_is_owned == 0 )); then
        runner_group_post_exit_policy=not-signaled-uncommitted-identity
        runner_exit_status=identity-not-committed
        return 1
    fi
    if (( session_is_owned == 1 )) && runner_leader_is_live; then
        kill -TERM -- "-$runner_session_id" 2>/dev/null || true
    fi
    for _ in $(seq 1 150); do
        if ! runner_leader_is_live; then
            break
        fi
        sleep 1
    done
    if runner_leader_is_live; then
        runner_forced_kill=1
        kill -KILL -- "-$runner_session_id" 2>/dev/null || true
        for _ in $(seq 1 10); do
            if ! runner_leader_is_live; then
                break
            fi
            sleep 1
        done
    fi
    if runner_leader_is_live; then
        leader_stopped=0
    elif process_matches_starttime "$runner_pid" "$runner_starttime"; then
        runner_group_post_exit_policy=not-signaled-unexpected-live-identity
        runner_exit_status=unexpected-live-identity
        return 1
    else
        leader_stopped=1
    fi
    if (( leader_stopped == 0 )); then
        runner_group_post_exit_policy=not-scanned-live-leader-kill-timeout
        runner_exit_status=kill-timeout
        return 1
    fi
    runner_group_post_exit_policy=not-scanned-after-exact-leader-exit
    if wait "$runner_pid"; then
        wait_status=0
    else
        wait_status=$?
    fi
    runner_exit_status=$wait_status
    runner_reaped=1
    (( runner_forced_kill == 0 && leader_stopped == 1 ))
}

restore_voxtral() {
    local attempt
    for attempt in 1 2 3; do
        timeout --signal=TERM --kill-after=5 60 \
            systemctl --user start "$VOXTRAL_UNIT" >/dev/null 2>&1 || true
        for _ in $(seq 1 40); do
            if capture_voxtral_snapshot voxtral_after; then
                [[ ${voxtral_after[2]} == "${voxtral_before[2]}" ]] || return 1
                if [[ ${voxtral_after[1]} == "${voxtral_before[1]}" && \
                    ${voxtral_after[3]} == "${voxtral_before[3]}" ]]; then
                    return 1
                fi
                voxtral_restore_verified=1
                return 0
            fi
            sleep 1
        done
    done
    return 1
}

write_final_record() {
    local entry_status=$1 final_status=$2 result=failed error_count index
    local -a records=()
    (( final_status == 0 )) && result=passed
    error_count=${#cleanup_errors[@]}
    records=(
        'schema=1' \
        "status=$result" \
        "entry_status=$entry_status" \
        "final_status=$final_status" \
        "primary_failure=${last_error:-none}" \
        "runner_exit_status=$runner_exit_status" \
        "runner_forced_kill=$runner_forced_kill" \
        "runner_reaped=$runner_reaped" \
        "runner_group_post_exit_policy=$runner_group_post_exit_policy" \
        "voxtral_pause_verified=$voxtral_pause_verified" \
        "voxtral_pause_continuity=$voxtral_pause_continuity" \
        "voxtral_restore_verified=$voxtral_restore_verified" \
        "fay_identity_unchanged=$fay_identity_unchanged" \
        "ardy_identity_unchanged=$ardy_identity_unchanged" \
        "ardy_image_tag_unchanged=$ardy_image_tag_unchanged" \
        "unreal_absent_after=$unreal_absent_after" \
        "cleanup_error_count=$error_count" \
        "finished_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    )
    for index in "${!cleanup_errors[@]}"; do
        records+=("cleanup_error_$((index + 1))=${cleanup_errors[$index]}")
    done
    write_record "$gate_root/gate-result.txt" "${records[@]}"
}

write_after_record() {
    local models_mount_sha256=not-available fay_listener_bindings_sha256=not-available
    if (( ${#ardy_after[@]} == 19 )); then
        models_mount_sha256=$(printf '%s' "${ardy_after[10]}" | sha256sum)
        models_mount_sha256=${models_mount_sha256%% *}
    fi
    if (( ${#fay_listener_bindings_after[@]} >= 4 )); then
        fay_listener_bindings_sha256=$(array_digest fay_listener_bindings_after) || return 1
    fi
    write_record "$gate_root/gate-after.txt" \
        'schema=1' \
        "fay_pid=$fay_pid" \
        "fay_executable=$fay_exe" \
        "fay_starttime=$fay_starttime" \
        "fay_listener_bindings_sha256=$fay_listener_bindings_sha256" \
        "fay_identity_unchanged=$fay_identity_unchanged" \
        "ardy_container_id=${ardy_after[1]:-not-available}" \
        "ardy_image=${ardy_after[2]:-not-available}" \
        "ardy_pid=${ardy_after[4]:-not-available}" \
        "ardy_container_started_at=${ardy_after[5]:-not-available}" \
        "ardy_auto_remove=${ardy_after[6]:-not-available}" \
        "ardy_network_mode=${ardy_after[7]:-not-available}" \
        "ardy_read_only=${ardy_after[8]:-not-available}" \
        "ardy_restart_count=${ardy_after[9]:-not-available}" \
        "ardy_models_mount_sha256=$models_mount_sha256" \
        "ardy_image_id=${ardy_after[12]:-not-available}" \
        "ardy_process_executable=${ardy_after[13]:-not-available}" \
        "ardy_process_starttime=${ardy_after[14]:-not-available}" \
        "ardy_provider=${ardy_after[15]:-not-available}" \
        "ardy_checkpoint=${ardy_after[16]:-not-available}" \
        "ardy_embedding_count=${ardy_after[17]:-not-available}" \
        "ardy_p95_generation_ms=${ardy_after[18]:-not-available}" \
        "ardy_identity_unchanged=$ardy_identity_unchanged" \
        "ardy_image_tag_unchanged=$ardy_image_tag_unchanged" \
        "voxtral_unit=$VOXTRAL_UNIT" \
        "voxtral_pid=${voxtral_after[1]:-not-available}" \
        "voxtral_executable=${voxtral_after[2]:-not-available}" \
        "voxtral_starttime=${voxtral_after[3]:-not-available}" \
        "voxtral_restore_verified=$voxtral_restore_verified"
}

on_exit() {
    local entry_status=$1 final_status=$1
    local -a remaining_unreal_pids=()
    trap - EXIT
    trap '' HUP INT TERM
    set +e

    if (( runner_started == 1 && runner_reaped == 0 )); then
        if ! cancel_and_reap_runner; then
            note_cleanup_error 'the owned rendered-soak runner session did not stop and reap cleanly'
        fi
    fi
    if (( runner_started == 1 )) && [[ ! -e $gate_root/runner-result.txt ]]; then
        write_record "$gate_root/runner-result.txt" \
            'schema=1' \
            "runner_pid=${runner_pid:-not-established}" \
            "runner_executable=${runner_exe:-not-established}" \
            "runner_starttime=${runner_starttime:-not-established}" \
            "runner_session_id=${runner_session_id:-not-established}" \
            "runner_exit_status=$runner_exit_status" \
            "runner_forced_kill=$runner_forced_kill" \
            "runner_reaped=$runner_reaped" || \
            note_cleanup_error 'could not publish the private runner result'
    fi

    if (( voxtral_pause_verified == 1 )); then
        if voxtral_is_fully_inactive; then
            [[ $voxtral_pause_continuity == failed ]] || voxtral_pause_continuity=passed
        else
            voxtral_pause_continuity=failed
            note_cleanup_error 'the allowlisted Voxtral unit or listener returned before restoration'
        fi
    fi

    mapfile -t remaining_unreal_pids < <(find_expected_unreal_pids)
    if (( ${#remaining_unreal_pids[@]} == 0 )); then
        unreal_absent_after=passed
    else
        unreal_absent_after=failed
        note_cleanup_error 'the exact packaged Unreal executable remained after runner cleanup'
    fi

    if (( voxtral_restore_required == 1 )); then
        if ! restore_voxtral; then
            note_cleanup_error 'the allowlisted Voxtral user unit did not restore with a healthy new identity'
        fi
    fi

    if (( fay_snapshot_ready == 1 )); then
        if validate_fay_identity "$fay_exe" "$fay_starttime" &&
            capture_fay_listener_bindings fay_listener_bindings_after &&
            arrays_are_equal fay_listener_bindings_before fay_listener_bindings_after; then
            fay_identity_unchanged=passed
        else
            fay_identity_unchanged=failed
            note_cleanup_error 'Fay did not preserve its exact process and listener identity'
        fi
    fi

    if (( ardy_snapshot_ready == 1 )); then
        if [[ $ardy_image_tag_unchanged != failed ]] &&
            ardy_image_tag_matches_expected; then
            ardy_image_tag_unchanged=passed
        else
            ardy_image_tag_unchanged=failed
            note_cleanup_error 'the fixed ARDY production image tag changed identity'
        fi
        if capture_ardy_snapshot ardy_after && \
            ardy_immutable_snapshot_is_equal ardy_before ardy_after; then
            ardy_identity_unchanged=passed
        else
            ardy_identity_unchanged=failed
            note_cleanup_error 'ARDY did not preserve its exact container and process identity'
        fi
    fi

    if ! write_after_record; then
        note_cleanup_error 'could not publish the private post-gate identity record'
    fi

    if (( ${#cleanup_errors[@]} != 0 )); then
        final_status=1
    fi
    if (( final_status == 0 )) && \
        [[ ! $runner_exit_status =~ ^[0-9]+$ || $runner_exit_status != 0 ]]; then
        final_status=1
    fi
    write_final_record "$entry_status" "$final_status" || {
        printf 'error: could not publish the private gate result record\n' >&2
        final_status=1
    }
    if (( final_status == 0 )); then
        printf 'Guarded DGX Spark avatar gate passed; private evidence: %s\n' "$gate_root"
    fi
    trap - EXIT
    exit "$final_status"
}

handle_signal() {
    local signal_name=$1 status=$2
    if (( runner_identity_capture_in_progress == 1 )); then
        if (( deferred_signal_status == 0 )); then
            deferred_signal_name=$signal_name
            deferred_signal_status=$status
            printf 'Deferring %s until the owned runner identity is committed.\n' \
                "$signal_name" >&2
        fi
        return 0
    fi
    last_error="received-$signal_name"
    printf 'error: received %s; cancelling the owned gate session\n' "$signal_name" >&2
    exit "$status"
}

trap 'on_exit $?' EXIT
trap 'handle_signal HUP 129' HUP
trap 'handle_signal INT 130' INT
trap 'handle_signal TERM 143' TERM

ardy_expected_image_id=$(resolve_fixed_ardy_image_id) || \
    fail 'the fixed ARDY production image tag did not resolve to one immutable image ID'

mapfile -t existing_unreal_pids < <(find_expected_unreal_pids)
(( ${#existing_unreal_pids[@]} == 0 )) || \
    fail 'the selected package already has a running Unreal process'

fay_exe=$(readlink -f "/proc/$fay_pid/exe" 2>/dev/null || true)
fay_starttime=$(read_process_starttime "$fay_pid" || true)
[[ $fay_exe == */python* && -n $fay_starttime ]] || \
    fail 'FAY_PID is not a stable Python process'
validate_fay_identity "$fay_exe" "$fay_starttime" || \
    fail 'FAY_PID did not pass exact listener and health validation'
capture_fay_listener_bindings fay_listener_bindings_before || \
    fail 'could not snapshot Fay listener bindings'
fay_snapshot_ready=1

capture_ardy_snapshot ardy_before || \
    fail 'the fixed ARDY container did not pass read-only identity and health validation'
ardy_snapshot_ready=1

capture_voxtral_snapshot voxtral_before || \
    fail 'the allowlisted Voxtral user unit did not pass identity and health validation'
voxtral_snapshot_ready=1

launcher_sha256=$(sha256sum -- "$package_launcher")
launcher_sha256=${launcher_sha256%% *}
unreal_sha256=$(sha256sum -- "$expected_unreal_exe")
unreal_sha256=${unreal_sha256%% *}
models_mount_sha256=$(printf '%s' "${ardy_before[10]}" | sha256sum)
models_mount_sha256=${models_mount_sha256%% *}
fay_listener_bindings_sha256=$(array_digest fay_listener_bindings_before)
write_record "$gate_root/gate-before.txt" \
    'schema=1' \
    "started_utc=$gate_started_utc" \
    "package_launcher_sha256=$launcher_sha256" \
    "unreal_executable_sha256=$unreal_sha256" \
    "fay_pid=$fay_pid" \
    "fay_executable=$fay_exe" \
    "fay_starttime=$fay_starttime" \
    'fay_ports=5000,5010,8766,10002' \
    "fay_listener_bindings_sha256=$fay_listener_bindings_sha256" \
    "ardy_container_id=${ardy_before[1]}" \
    "ardy_image=${ardy_before[2]}" \
    "ardy_pid=${ardy_before[4]}" \
    "ardy_container_started_at=${ardy_before[5]}" \
    "ardy_auto_remove=${ardy_before[6]}" \
    "ardy_network_mode=${ardy_before[7]}" \
    "ardy_read_only=${ardy_before[8]}" \
    "ardy_restart_count=${ardy_before[9]}" \
    "ardy_image_id=${ardy_before[12]}" \
    "ardy_starttime=${ardy_before[14]}" \
    "ardy_process_executable=${ardy_before[13]}" \
    "ardy_provider=${ardy_before[15]}" \
    "ardy_checkpoint=${ardy_before[16]}" \
    "ardy_embedding_count=${ardy_before[17]}" \
    "ardy_p95_generation_ms=${ardy_before[18]}" \
    "ardy_models_mount_sha256=$models_mount_sha256" \
    "voxtral_unit=$VOXTRAL_UNIT" \
    "voxtral_pid=${voxtral_before[1]}" \
    "voxtral_executable=${voxtral_before[2]}" \
    "voxtral_starttime=${voxtral_before[3]}" || \
    fail 'could not publish the private preflight identity record'

: >"$gate_root/package-preflight.log"
chmod 600 "$gate_root/package-preflight.log"
if ! "$package_verifier" "$package_launcher_dir" \
    >"$gate_root/package-preflight.log" 2>&1; then
    fail 'the cooked package failed verification before the service pause'
fi
validate_fay_identity "$fay_exe" "$fay_starttime" || \
    fail 'Fay changed identity during package verification'
capture_fay_listener_bindings fay_listener_bindings_after || \
    fail 'Fay listener bindings changed during package verification'
arrays_are_equal fay_listener_bindings_before fay_listener_bindings_after || \
    fail 'Fay listener bindings changed during package verification'
capture_ardy_snapshot ardy_after || fail 'ARDY changed during package verification'
ardy_immutable_snapshot_is_equal ardy_before ardy_after || \
    fail 'ARDY changed during package verification'
if ! ardy_image_tag_matches_expected; then
    ardy_image_tag_unchanged=failed
    fail 'the fixed ARDY production image tag changed during package verification'
fi
capture_voxtral_snapshot voxtral_after || fail 'Voxtral changed during package verification'
[[ ${voxtral_after[1]} == "${voxtral_before[1]}" && \
    ${voxtral_after[2]} == "${voxtral_before[2]}" && \
    ${voxtral_after[3]} == "${voxtral_before[3]}" ]] || \
    fail 'Voxtral changed identity during package verification'

voxtral_restore_required=1
if ! timeout --signal=TERM --kill-after=5 60 \
    systemctl --user stop "$VOXTRAL_UNIT"; then
    fail 'could not stop the allowlisted Voxtral user unit'
fi
for _ in $(seq 1 30); do
    if voxtral_is_fully_inactive &&
        ! process_matches_identity "${voxtral_before[1]}" "${voxtral_before[2]}" \
            "${voxtral_before[3]}"; then
        voxtral_pause_verified=1
        break
    fi
    sleep 1
done
(( voxtral_pause_verified == 1 )) || \
    fail 'the allowlisted Voxtral user unit did not become fully inactive'

mem_available_kb=$(awk '$1 == "MemAvailable:" {print $2; found=1} END {exit !found}' \
    /proc/meminfo)
[[ $mem_available_kb =~ ^[1-9][0-9]*$ ]] || \
    fail 'could not record available unified memory after the service pause'
write_record "$gate_root/voxtral-pause.txt" \
    'schema=1' \
    "unit=$VOXTRAL_UNIT" \
    'state=inactive' \
    'port_4395=unbound' \
    "mem_available_kb=$mem_available_kb" || \
    fail 'could not publish the private service-pause record'

: >"$runner_console"
chmod 600 "$runner_console"
runner_identity_capture_in_progress=1
(
    exec 9>&-
    exec setsid "$soak_runner" "$package_launcher" "$fay_pid" "$soak_output" \
        "$duration_seconds" "$turn_count" >"$runner_console" 2>&1
) &
runner_pid=$!
runner_started=1
runner_identity_committed=0
if capture_process_record runner_initial_record "$runner_pid" &&
    [[ ${runner_initial_record[0]} != Z && ${runner_initial_record[0]} != X && \
    ${runner_initial_record[1]} == "$supervisor_pid" ]]; then
    runner_provisional_starttime=${runner_initial_record[4]}
    for _ in $(seq 1 20); do
        if ! capture_process_record runner_candidate_record "$runner_pid"; then
            break
        fi
        if [[ ${runner_candidate_record[0]} == Z || \
            ${runner_candidate_record[0]} == X || \
            ${runner_candidate_record[1]} != "$supervisor_pid" || \
            ${runner_candidate_record[4]} != "$runner_provisional_starttime" ]]; then
            break
        fi
        if [[ ${runner_candidate_record[2]} == "$runner_pid" && \
            ${runner_candidate_record[3]} == "$runner_pid" ]]; then
            runner_candidate_exe=$(readlink -f "/proc/$runner_pid/exe" 2>/dev/null || true)
            if capture_process_record runner_confirm_record "$runner_pid" &&
                [[ ${runner_confirm_record[0]} != Z && \
                ${runner_confirm_record[0]} != X && \
                ${runner_confirm_record[1]} == "$supervisor_pid" && \
                ${runner_confirm_record[2]} == "$runner_pid" && \
                ${runner_confirm_record[3]} == "$runner_pid" && \
                ${runner_confirm_record[4]} == "$runner_provisional_starttime" && \
                $runner_candidate_exe == "$runner_bash_exe" ]]; then
                runner_exe=$runner_candidate_exe
                runner_starttime=$runner_provisional_starttime
                runner_session_id=$runner_pid
                runner_identity_committed=1
                break
            fi
            if [[ ${runner_confirm_record[4]:-} != "$runner_provisional_starttime" || \
                ${runner_confirm_record[1]:-} != "$supervisor_pid" ]]; then
                break
            fi
        fi
        sleep 1 || true
    done
fi
runner_identity_capture_in_progress=0
if (( deferred_signal_status != 0 )); then
    handle_signal "$deferred_signal_name" "$deferred_signal_status"
fi
(( runner_identity_committed == 1 )) || \
    fail 'could not establish the rendered-soak runner session identity'

voxtral_pause_continuity=passed
while runner_leader_is_live; do
    if ! voxtral_is_fully_inactive; then
        voxtral_pause_continuity=failed
        cancel_and_reap_runner || true
        break
    fi
    sleep 5
done
if (( runner_reaped == 0 )); then
    if ! runner_leader_is_live && \
        process_matches_starttime "$runner_pid" "$runner_starttime"; then
        runner_exit_status=unexpected-live-identity
        fail 'the rendered-soak runner changed executable while remaining live'
    fi
    if wait "$runner_pid"; then
        runner_exit_status=0
    else
        runner_exit_status=$?
    fi
    runner_reaped=1
    runner_group_post_exit_policy=not-scanned-after-exact-leader-exit
fi
write_record "$gate_root/runner-result.txt" \
    'schema=1' \
    "runner_pid=$runner_pid" \
    "runner_executable=$runner_exe" \
    "runner_starttime=$runner_starttime" \
    "runner_session_id=$runner_session_id" \
    "runner_exit_status=$runner_exit_status" \
    "runner_group_post_exit_policy=$runner_group_post_exit_policy" \
    'runner_reaped=1' || fail 'could not publish the private runner result'

[[ $voxtral_pause_continuity == passed ]] || \
    fail 'the allowlisted Voxtral unit became active during the rendered gate'
(( runner_exit_status == 0 )) || fail 'the guarded rendered-soak runner failed'
[[ -f $soak_output/soak-summary.txt && ! -L $soak_output/soak-summary.txt ]] || \
    fail 'the rendered-soak runner did not publish a safe summary'
[[ $(grep -Fxc 'status=passed' "$soak_output/soak-summary.txt") == 1 ]] || \
    fail 'the rendered-soak summary did not preserve exactly one passing status'
