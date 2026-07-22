#!/usr/bin/env bash
set -euo pipefail
umask 077

last_error='unexpected-command-failure'

usage() {
    printf 'Usage: %s PACKAGE_LAUNCHER FAY_PID PRIVATE_GATE_DIR\n' "${0##*/}" >&2
    printf 'Runs one local-only Ada ARDY outage/recovery diagnostic at 1280x720.\n' >&2
}

fail() {
    last_error=$*
    printf 'error: %s\n' "$*" >&2
    exit 1
}

if (( $# != 3 )); then
    usage
    exit 64
fi
if [[ $(uname -s) != Linux || $(uname -m) != aarch64 ]]; then
    fail 'the ARDY recovery diagnostic requires Linux/aarch64 on DGX Spark'
fi
if (( ${EUID:-$(id -u)} == 0 )); then
    fail 'run the ARDY recovery diagnostic as the normal workspace owner, not root'
fi

readonly VOXTRAL_UNIT='codex-studio-voxtral-realtime.service'
readonly ARDY_CONTAINER='ue5-spark-ardy'
readonly ARDY_IMAGE='ue5-spark-ardy:0.2.0'
readonly ARDY_ROLLBACK_IMAGE='ue5-spark-ardy:0.1.0'
readonly ARDY_PORT=8777
readonly RUN_DURATION_SECONDS=180
readonly RUN_TURN_COUNT=1
readonly FIRST_ACTION_DURATION='10.0'
readonly SECOND_ACTION_DURATION='3.0'
readonly BRIDGE_ACTION_DURATION='1.0'
readonly BRIDGE_ACTION_INTENSITY='0.50'

package_launcher_input=$1
fay_pid=$2
gate_root_input=$3
[[ $fay_pid =~ ^[1-9][0-9]*$ ]] || fail 'FAY_PID must be a positive integer'

for command_name in awk bash basename chmod cp curl date dirname docker find flock grep id \
    kill ln mkdir mkfifo mktemp mv ps python3 readlink realpath rm sed seq setsid sha256sum \
    sleep sort ss stat systemctl timeout tr wc; do
    command -v "$command_name" >/dev/null 2>&1 || fail "missing command: $command_name"
done

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
soak_runner="$script_dir/run-spark-avatar-soak.sh"
package_verifier="$script_dir/verify-cooked-package.sh"
activator="$script_dir/activate-ardy-provider.sh"
runner_bash_exe=$(readlink -f "$(command -v bash)")
for guarded_script in "$soak_runner" "$package_verifier" "$activator"; do
    [[ -x $guarded_script && -f $guarded_script && ! -L $guarded_script ]] || \
        fail "a guarded dependency is missing or unsafe: $guarded_script"
done
[[ -x $runner_bash_exe ]] || fail 'the canonical Bash executable is unavailable'

package_launcher_dir=$(cd "$(dirname "$package_launcher_input")" && pwd -P)
package_launcher="$package_launcher_dir/$(basename "$package_launcher_input")"
[[ -x $package_launcher && -f $package_launcher && ! -L $package_launcher && \
    ${package_launcher##*/} == FayAvatarRuntime-Arm64.sh ]] || \
    fail 'expected a real executable FayAvatarRuntime-Arm64.sh package launcher'
expected_unreal_exe=$(realpath \
    "$package_launcher_dir/FayAvatarRuntime/Binaries/LinuxArm64/FayAvatarRuntime")
[[ -x $expected_unreal_exe && -f $expected_unreal_exe && ! -L $expected_unreal_exe ]] || \
    fail 'the packaged Unreal executable is missing or unsafe'

gate_parent_input=$(dirname "$gate_root_input")
gate_name=$(basename "$gate_root_input")
[[ $gate_name =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$ ]] || \
    fail 'PRIVATE_GATE_DIR must end in a simple unique run name'
[[ -d $gate_parent_input ]] || fail 'the private gate parent directory does not exist'
gate_parent=$(cd "$gate_parent_input" && pwd -P)
gate_root="$gate_parent/$gate_name"
case "$gate_root/" in
    */logs-private/*) private_root=${gate_root%%/logs-private/*}/logs-private ;;
    *) fail 'PRIVATE_GATE_DIR must be below a logs-private root' ;;
esac
[[ -d $private_root && ! -L $private_root ]] || \
    fail 'the selected private evidence root is missing or unsafe'
[[ ! -e $gate_root && ! -L $gate_root ]] || \
    fail 'PRIVATE_GATE_DIR must not already exist; every diagnostic requires unique evidence'

gate_lock_file="$private_root/.spark-avatar-gate.lock"
[[ ! -L $gate_lock_file ]] || fail 'the private gate lock path is a symlink'
exec 9>>"$gate_lock_file"
chmod 600 "$gate_lock_file"
flock -n 9 || fail 'another guarded avatar gate already owns this private evidence root'
[[ ! -e $gate_root && ! -L $gate_root ]] || \
    fail 'PRIVATE_GATE_DIR appeared while acquiring the gate lock'
mkdir -m 700 -- "$gate_root"
[[ $(cd "$gate_root" && pwd -P) == "$gate_root" ]] || \
    fail 'could not establish the exact private gate directory'

activation_lock_parent="/run/user/$(id -u)"
[[ -d $activation_lock_parent && ! -L $activation_lock_parent ]] || \
    fail 'the fixed per-user runtime directory is missing or unsafe'
activation_lock_parent=$(cd "$activation_lock_parent" && pwd -P)
[[ $activation_lock_parent == "/run/user/$(id -u)" ]] || \
    fail 'the fixed per-user runtime directory resolved unexpectedly'
activation_lock_file="$activation_lock_parent/ue5-spark-ardy.activation.lock"
[[ ! -L $activation_lock_file ]] || fail 'the ARDY activation lock is a symlink'
exec 8>>"$activation_lock_file"
chmod 600 "$activation_lock_file"
flock -n 8 || fail 'another guarded ARDY activation is already running for this user'
[[ $(readlink -f /proc/self/fd/8 2>/dev/null || true) == "$activation_lock_file" ]] || \
    fail 'the held ARDY activation lock descriptor resolved unexpectedly'

soak_output="$gate_root/soak"
runner_console="$gate_root/runner-console.log"
activation_evidence="$gate_root/activation"
activation_console="$gate_root/activation-console.log"
primary_activation_evidence=$activation_evidence
primary_activation_console=$activation_console
recovery_log="$gate_root/recovery-runtime.log"

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

run_bounded_isolated() {
    local timeout_seconds=$1
    shift
    [[ $timeout_seconds =~ ^[1-9][0-9]*$ && $# -gt 0 ]] || return 1
    # Keep the exact Docker lifecycle operation outside the diagnostic's
    # process group.  A TERM/INT sent to the gate cannot interrupt Docker
    # between accepting the stop and reporting its result; timeout still
    # bounds the isolated helper and its child.
    setsid --wait timeout --foreground --signal=TERM --kill-after=5 \
        "$timeout_seconds" "$@"
}

docker_stop_exact_bounded() {
    local container_id=$1
    [[ $container_id =~ ^[0-9a-f]{64}$ ]] || return 1
    # The generated action is capped at ten seconds. This stateless, sealed,
    # auto-removed inference container therefore gets a short graceful window
    # so the diagnostic can observe service loss while that action is active.
    run_bounded_isolated 30 docker stop --time 2 "$container_id"
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
    local actual_starttime
    actual_starttime=$(read_process_starttime "$1" || true)
    [[ -n $actual_starttime && $actual_starttime == "$2" ]]
}

loopback_listener_owned_by_pid() {
    local port=$1 pid=$2 listeners line endpoint other_owner count=0
    listeners=$(ss -H -ltnp "sport = :$port" 2>/dev/null) || return 1
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

port_is_unused() {
    local listeners
    listeners=$(ss -H -ltn "sport = :$1" 2>/dev/null) || return 1
    [[ -z $listeners ]]
}

capture_fay_listener_bindings() {
    local -n destination=$1
    local port listeners line other_owner local_endpoint peer_endpoint per_port_count
    local -a unsorted=()
    destination=()
    for port in 5000 5010 8766 10002; do
        listeners=$(ss -H -ltnp "sport = :$port" 2>/dev/null) || return 1
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

fay_listener_host() {
    local listeners line endpoint host count=0 selected=''
    listeners=$(ss -H -ltnp 'sport = :5000' 2>/dev/null) || return 1
    while IFS= read -r line; do
        [[ -n $line ]] || continue
        [[ $line == *"pid=$fay_pid,"* ]] || return 1
        endpoint=$(awk '{print $4}' <<<"$line")
        host=${endpoint%:5000}
        host=${host#[}
        host=${host%]}
        [[ -n $host && $host != \* && $host != 0.0.0.0 && $host != :: ]] || return 1
        selected=$host
        count=$((count + 1))
    done <<<"$listeners"
    (( count == 1 )) || return 1
    python3 - "$selected" <<'PY'
import ipaddress
import sys

address = ipaddress.ip_address(sys.argv[1])
if address.is_unspecified or address.is_multicast or address.is_global:
    raise SystemExit(1)
print(address.compressed)
PY
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
    host=$(fay_listener_host) || return 1
    formatted_host=$(url_host "$host")
    code=$(curl --silent --show-error --output /dev/null --noproxy '*' \
        --connect-timeout 2 --max-time 5 --write-out '%{http_code}' \
        "http://$formatted_host:$port$path" 2>/dev/null || true)
    [[ $code =~ ^[23][0-9][0-9]$ ]] || return 1
    process_matches_identity "$fay_pid" "$expected_exe" "$expected_starttime"
}

validate_fay_identity() {
    local expected_exe=$1 expected_starttime=$2
    local -a bindings=()
    process_matches_identity "$fay_pid" "$expected_exe" "$expected_starttime" || return 1
    capture_fay_listener_bindings bindings || return 1
    fay_http_ready 5000 / "$expected_exe" "$expected_starttime" || return 1
    fay_http_ready 5010 / "$expected_exe" "$expected_starttime" || return 1
    fay_http_ready 8766 /sse "$expected_exe" "$expected_starttime"
}

arrays_are_equal() {
    local -n left=$1 right=$2
    local index
    (( ${#left[@]} == ${#right[@]} )) || return 1
    for index in "${!left[@]}"; do
        [[ ${left[$index]} == "${right[$index]}" ]] || return 1
    done
}

validate_fay_runtime_snapshot() {
    local -a bindings=()
    process_matches_identity "$fay_pid" "$fay_exe" "$fay_starttime" || return 1
    capture_fay_listener_bindings bindings || return 1
    arrays_are_equal fay_listener_bindings_before bindings || return 1
    process_matches_identity "$fay_pid" "$fay_exe" "$fay_starttime"
}

array_digest() {
    local -n values=$1
    local digest
    digest=$(printf '%s\0' "${values[@]}" | sha256sum) || return 1
    printf '%s\n' "${digest%% *}"
}

image_id() {
    local value
    value=$(docker image inspect --format '{{.Id}}' "$1" 2>/dev/null) || return 1
    [[ $value =~ ^sha256:[0-9a-f]{64}$ ]] || return 1
    printf '%s\n' "$value"
}

container_id_for_name() {
    local value
    value=$(docker inspect --type container --format '{{.Id}}' "$ARDY_CONTAINER" \
        2>/dev/null) || return 1
    [[ $value =~ ^[0-9a-f]{64}$ ]] || return 1
    printf '%s\n' "$value"
}

probe_real_ardy_health() {
    local body
    local -a parsed=()
    body=$(curl --fail --silent --show-error --noproxy '*' \
        --connect-timeout 2 --max-time 5 http://127.0.0.1:8777/healthz) || return 1
    (( ${#body} <= 65536 )) || return 1
    mapfile -t parsed < <(
        printf '%s' "$body" | python3 -c '
import json
import math
import sys

value = json.load(sys.stdin)
expected_keys = {
    "status", "provider", "protocolVersion", "fps", "bufferFrames",
    "facialControl", "checkpoint", "embeddingCount", "p95GenerationMs",
}
if not isinstance(value, dict) or set(value) != expected_keys:
    raise SystemExit(1)
if value.get("status") != "ready" or value.get("provider") != "ardy":
    raise SystemExit(1)
if type(value.get("protocolVersion")) is not int or value["protocolVersion"] != 1:
    raise SystemExit(1)
if type(value.get("fps")) is not int or value["fps"] != 20:
    raise SystemExit(1)
if type(value.get("bufferFrames")) is not int or value["bufferFrames"] != 8:
    raise SystemExit(1)
if value.get("facialControl") != "excluded":
    raise SystemExit(1)
if value.get("checkpoint") != "ARDY-Core-RP-20FPS-Horizon8":
    raise SystemExit(1)
if type(value.get("embeddingCount")) is not int or value["embeddingCount"] != 3:
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
    (( ${#parsed[@]} == 4 )) || return 1
    printf '%s\n' "${parsed[@]}"
}

probe_mock_ardy_health() {
    local body
    body=$(curl --fail --silent --show-error --noproxy '*' \
        --connect-timeout 2 --max-time 5 http://127.0.0.1:8777/healthz) || return 1
    (( ${#body} <= 65536 )) || return 1
    printf '%s' "$body" | python3 -c '
import json
import sys

value = json.load(sys.stdin)
expected = {
    "status": "ready",
    "provider": "mock",
    "protocolVersion": 1,
    "fps": 20,
    "bufferFrames": 8,
    "facialControl": "excluded",
    "checkpoint": None,
    "embeddingCount": 0,
    "p95GenerationMs": 0.0,
}
if value != expected:
    raise SystemExit(1)
print("mock")
print("null")
print("0")
print("0.0")
'
}

capture_ardy_container() {
    local -n destination=$1
    local identifier=$2 expected_tag=$3 expected_image_id=$4 expected_provider=$5
    local inspect_json models_source models_resolved ardy_pid ardy_exe ardy_starttime
    local -a health=()
    destination=()
    inspect_json=$(docker inspect --type container "$identifier") || return 1
    mapfile -t destination < <(
        printf '%s' "$inspect_json" | python3 -c '
import json
import re
import sys

(
    identifier,
    expected_name,
    expected_tag,
    expected_image_id,
    expected_provider,
    expected_user,
) = sys.argv[1:]
records = json.load(sys.stdin)
if not isinstance(records, list) or len(records) != 1:
    raise SystemExit(1)
record = records[0]
config = record.get("Config", {})
host = record.get("HostConfig", {})
state = record.get("State", {})
container_id = record.get("Id", "")
if identifier not in {container_id, expected_name}:
    raise SystemExit(1)
if (
    record.get("Name") != f"/{expected_name}"
    or not re.fullmatch(r"[0-9a-f]{64}", container_id)
    or config.get("Image") not in {expected_tag, expected_image_id}
    or record.get("Image") != expected_image_id
    or state.get("Running") is not True
    or state.get("Dead") is not False
    or state.get("OOMKilled") is not False
    or state.get("Error") not in {None, ""}
    or not isinstance(state.get("Pid"), int)
    or state.get("Pid", 0) <= 0
    or not isinstance(state.get("StartedAt"), str)
    or not state.get("StartedAt")
    or record.get("RestartCount") != 0
    or host.get("AutoRemove") is not True
    or host.get("NetworkMode") != "host"
    or host.get("ReadonlyRootfs") is not True
    or host.get("CapDrop") != ["ALL"]
    or "no-new-privileges:true" not in (host.get("SecurityOpt") or [])
    or host.get("PidsLimit") != 512
    or host.get("ShmSize") != 4 * 1024**3
    or host.get("Tmpfs") != {"/tmp": "rw,noexec,nosuid,size=1g"}
    or config.get("User") != expected_user
):
    raise SystemExit(1)
device_requests = host.get("DeviceRequests")
if not isinstance(device_requests, list) or not any(
    ["gpu"] in request.get("Capabilities", []) for request in device_requests
):
    raise SystemExit(1)
mounts = record.get("Mounts")
if not isinstance(mounts, list) or len(mounts) != 1:
    raise SystemExit(1)
mount = mounts[0]
if (
    mount.get("Type") != "bind"
    or mount.get("Destination") != "/models"
    or mount.get("RW") is not False
    or not isinstance(mount.get("Source"), str)
    or not mount.get("Source", "").startswith("/")
):
    raise SystemExit(1)
expected_command = [
    "--host", "127.0.0.1", "--port", "8777", "--provider", expected_provider,
    "--models-root", "/models",
]
if config.get("Cmd") != expected_command:
    raise SystemExit(1)
for entry in config.get("Env") or []:
    name, separator, value = entry.partition("=")
    if not separator:
        raise SystemExit(1)
    if re.search(r"(?:TOKEN|PASSWORD|SECRET|CREDENTIAL|API_KEY)$", name, re.I):
        raise SystemExit(1)
    if re.search(r"(?:^|[^A-Za-z0-9])hf_[A-Za-z0-9]{10,}", value):
        raise SystemExit(1)
values = (
    record["Name"], container_id, config["Image"], str(state["Running"]).lower(),
    state["Pid"], state["StartedAt"], str(host["AutoRemove"]).lower(),
    host["NetworkMode"], str(host["ReadonlyRootfs"]).lower(),
    record["RestartCount"], mount["Source"], str(mount["RW"]).lower(),
    record["Image"],
)
print("\n".join(str(value) for value in values))
' "$identifier" "$ARDY_CONTAINER" "$expected_tag" "$expected_image_id" \
            "$expected_provider" "$(id -u):$(id -g)"
    )
    (( ${#destination[@]} == 13 )) || return 1
    models_source=${destination[10]}
    [[ -d $models_source && ! -L $models_source ]] || return 1
    models_resolved=$(cd "$models_source" && pwd -P) || return 1
    [[ $models_resolved == "$models_source" ]] || return 1
    ardy_pid=${destination[4]}
    ardy_exe=$(readlink -f "/proc/$ardy_pid/exe" 2>/dev/null || true)
    ardy_starttime=$(read_process_starttime "$ardy_pid" || true)
    [[ $ardy_exe == */python* && -n $ardy_starttime ]] || return 1
    process_matches_identity "$ardy_pid" "$ardy_exe" "$ardy_starttime" || return 1
    loopback_listener_owned_by_pid "$ARDY_PORT" "$ardy_pid" || return 1
    if [[ $expected_provider == ardy ]]; then
        mapfile -t health < <(probe_real_ardy_health)
    else
        mapfile -t health < <(probe_mock_ardy_health)
    fi
    (( ${#health[@]} == 4 )) || return 1
    destination+=("$ardy_exe" "$ardy_starttime" "${health[@]}")
}

capture_real_ardy() {
    capture_ardy_container "$1" "$2" "$ARDY_IMAGE" "$ardy_expected_image_id" ardy
}

capture_mock_ardy() {
    capture_ardy_container "$1" "$2" "$ARDY_ROLLBACK_IMAGE" \
        "$ardy_rollback_image_id" mock
}

ardy_immutable_snapshots_equal() {
    local -n left=$1 right=$2
    local index
    (( ${#left[@]} == 19 && ${#right[@]} == 19 )) || return 1
    for index in $(seq 0 17); do
        [[ ${left[$index]} == "${right[$index]}" ]] || return 1
    done
}

probe_voxtral_health() {
    curl --fail --silent --show-error --output /dev/null --noproxy '*' \
        --connect-timeout 2 --max-time 5 http://127.0.0.1:4395/health
}

capture_voxtral_snapshot() {
    local -n destination=$1
    local active_state sub_state main_pid process_exe process_starttime
    destination=()
    systemctl --user is-active --quiet "$VOXTRAL_UNIT" || return 1
    active_state=$(systemctl --user show --property=ActiveState --value \
        "$VOXTRAL_UNIT" | tr -d '[:space:]') || return 1
    sub_state=$(systemctl --user show --property=SubState --value \
        "$VOXTRAL_UNIT" | tr -d '[:space:]') || return 1
    main_pid=$(systemctl --user show --property=MainPID --value \
        "$VOXTRAL_UNIT" | tr -d '[:space:]') || return 1
    [[ $active_state == active && $sub_state == running && \
        $main_pid =~ ^[1-9][0-9]*$ ]] || return 1
    process_exe=$(readlink -f "/proc/$main_pid/exe" 2>/dev/null || true)
    process_starttime=$(read_process_starttime "$main_pid" || true)
    [[ $process_exe == */python3* && -n $process_starttime ]] || return 1
    process_matches_identity "$main_pid" "$process_exe" "$process_starttime" || return 1
    loopback_listener_owned_by_pid 4395 "$main_pid" || return 1
    probe_voxtral_health || return 1
    destination=("$VOXTRAL_UNIT" "$main_pid" "$process_exe" "$process_starttime")
}

voxtral_is_fully_inactive() {
    local active_state main_pid
    active_state=$(systemctl --user show --property=ActiveState --value \
        "$VOXTRAL_UNIT" | tr -d '[:space:]') || return 1
    main_pid=$(systemctl --user show --property=MainPID --value \
        "$VOXTRAL_UNIT" | tr -d '[:space:]') || return 1
    [[ $active_state == inactive && $main_pid == 0 ]] || return 1
    port_is_unused 4395
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

cleanup_errors=()
note_cleanup_error() {
    cleanup_errors+=("$*")
    printf 'error: %s\n' "$*" >&2
}

supervisor_pid=$BASHPID
runner_pid=''
runner_exe=''
runner_starttime=''
runner_session_id=''
runner_provisional_starttime=''
runner_started=0
runner_reaped=0
runner_exit_status=not-started
runner_forced_kill=0
runner_identity_committed=0
runner_start_released=0
runner_barrier_fd_open=0
runner_barrier_token=''
runner_identity_capture_in_progress=0
runner_release_in_progress=0
ardy_stop_in_progress=0
deferred_signal_name=''
deferred_signal_status=0
runner_group_post_exit_policy=not-started
declare -a runner_initial_record=()
declare -a runner_candidate_record=()
declare -a runner_confirm_record=()

runner_leader_is_live() {
    (( runner_identity_committed == 1 )) || return 1
    [[ -n $runner_pid && -n $runner_starttime && -n $runner_exe ]] || return 1
    process_matches_identity "$runner_pid" "$runner_exe" "$runner_starttime"
}

abort_runner_start_barrier() {
    local wait_status=0
    if (( runner_barrier_fd_open == 1 )); then
        printf '%s\n' abort-owned-runner-start >&7 || true
        exec 7>&-
        runner_barrier_fd_open=0
    fi
    if (( runner_started == 1 && runner_reaped == 0 )); then
        if wait "$runner_pid"; then
            wait_status=0
        else
            wait_status=$?
        fi
        runner_exit_status=$wait_status
        runner_reaped=1
    fi
    runner_group_post_exit_policy=start-barrier-aborted-without-signals
    (( runner_start_released == 0 ))
}

release_runner_start_barrier() {
    local release_status=0
    (( runner_identity_committed == 1 && runner_barrier_fd_open == 1 && \
        runner_start_released == 0 )) || return 1
    runner_release_in_progress=1
    # Once release begins, cleanup must treat the exact committed session as
    # launch-capable even if a signal lands between the FIFO write and state
    # bookkeeping.  That routes every failure through bounded exact-session
    # cancellation instead of the no-signal pre-launch abort path.
    runner_start_released=1
    printf '%s\n' "$runner_barrier_token" >&7 || release_status=$?
    exec 7>&- || release_status=$?
    runner_barrier_fd_open=0
    runner_release_in_progress=0
    (( release_status == 0 ))
}

cancel_and_reap_runner() {
    local wait_status=0
    (( runner_started == 1 && runner_reaped == 0 )) || return 0
    if (( runner_start_released == 0 )); then
        abort_runner_start_barrier
        return $?
    fi
    if (( runner_identity_committed != 1 )) || \
        [[ ! $runner_session_id =~ ^[1-9][0-9]*$ || \
        $runner_session_id != "$runner_pid" ]]; then
        runner_group_post_exit_policy=not-signaled-uncommitted-identity
        runner_exit_status=identity-not-committed
        return 1
    fi
    if runner_leader_is_live; then
        kill -TERM -- "-$runner_session_id" 2>/dev/null || true
    fi
    for _ in $(seq 1 45); do
        runner_leader_is_live || break
        sleep 1
    done
    if runner_leader_is_live; then
        runner_forced_kill=1
        kill -KILL -- "-$runner_session_id" 2>/dev/null || true
        for _ in $(seq 1 10); do
            runner_leader_is_live || break
            sleep 1
        done
    fi
    if runner_leader_is_live; then
        runner_group_post_exit_policy=not-scanned-live-leader-kill-timeout
        runner_exit_status=kill-timeout
        return 1
    fi
    if process_matches_starttime "$runner_pid" "$runner_starttime"; then
        runner_group_post_exit_policy=not-signaled-unexpected-live-identity
        runner_exit_status=unexpected-live-identity
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
    (( runner_forced_kill == 0 ))
}

wait_for_runner_completion() {
    local deadline=$(( $(date +%s) + 360 )) wait_status
    while runner_leader_is_live; do
        (( $(date +%s) < deadline )) || return 1
        voxtral_is_fully_inactive || return 1
        validate_fay_runtime_snapshot || return 1
        sleep 2
    done
    if process_matches_starttime "$runner_pid" "$runner_starttime"; then
        return 1
    fi
    if wait "$runner_pid"; then
        wait_status=0
    else
        wait_status=$?
    fi
    runner_exit_status=$wait_status
    runner_reaped=1
    runner_group_post_exit_policy=not-scanned-after-exact-leader-exit
    (( wait_status == 0 ))
}

find_marker_line_after() {
    local marker=$1 after_line=$2
    [[ -f $recovery_log && ! -L $recovery_log ]] || return 1
    awk -v marker="$marker" -v after="$after_line" \
        'NR > after && index($0, marker) {print NR; exit}' "$recovery_log"
}

refresh_recovery_log() {
    local launcher_log="$soak_output/launcher.log" temporary
    [[ -f $launcher_log && ! -L $launcher_log ]] || return 1
    temporary=$(mktemp "$gate_root/.recovery-runtime.XXXXXX") || return 1
    if ! cp -- "$launcher_log" "$temporary"; then
        rm -f -- "$temporary"
        return 1
    fi
    chmod 600 "$temporary" || {
        rm -f -- "$temporary"
        return 1
    }
    mv -f -- "$temporary" "$recovery_log"
}

capture_log_cursor() {
    local line_count
    refresh_recovery_log || return 1
    line_count=$(wc -l <"$recovery_log") || return 1
    [[ $line_count =~ ^[0-9]+$ ]] || return 1
    printf '%s\n' "$line_count"
}

continuity_guard() {
    runner_leader_is_live || return 1
    voxtral_is_fully_inactive || return 1
    validate_fay_runtime_snapshot
}

wait_for_marker_after() {
    local marker=$1 after_line=$2 timeout_seconds=$3
    local deadline=$(( $(date +%s) + timeout_seconds )) observed_line iteration=0
    while (( $(date +%s) < deadline )); do
        if refresh_recovery_log; then
            observed_line=$(find_marker_line_after "$marker" "$after_line" || true)
            if [[ $observed_line =~ ^[1-9][0-9]*$ ]]; then
                printf '%s\n' "$observed_line"
                return 0
            fi
        fi
        continuity_guard || return 1
        iteration=$((iteration + 1))
        sleep 1
    done
    return 1
}

marker_count_after() {
    local marker=$1 after_line=$2
    refresh_recovery_log || return 1
    awk -v marker="$marker" -v after="$after_line" \
        'NR > after && index($0, marker) {count++} END {print count + 0}' "$recovery_log"
}

post_motion_action() {
    local behavior=$1 intensity=$2 duration=$3 label=$4 cursor_name=$5 action_cursor
    local host formatted_host response_file temporary metadata http_code content_type
    local payload
    case "$behavior:$intensity:$duration" in
        "explain:0.65:$FIRST_ACTION_DURATION"|\
        "explain:0.65:$SECOND_ACTION_DURATION"|\
        "idle:$BRIDGE_ACTION_INTENSITY:$BRIDGE_ACTION_DURATION"|\
        "listen:$BRIDGE_ACTION_INTENSITY:$BRIDGE_ACTION_DURATION") ;;
        *) return 1 ;;
    esac
    validate_fay_runtime_snapshot || return 1
    host=$(fay_listener_host) || return 1
    [[ $host == "$fay_http_host" ]] || return 1
    formatted_host=$(url_host "$host")
    payload=$(printf \
        '{"behavior":"%s","intensity":%s,"duration":%s,"user":"User"}' \
        "$behavior" "$intensity" "$duration")
    response_file="$gate_root/$label-action-response.json"
    [[ ! -e $response_file && ! -L $response_file ]] || return 1
    temporary=$(mktemp "$gate_root/.$label-action-response.XXXXXX") || return 1
    action_cursor=$(capture_log_cursor) || {
        rm -f -- "$temporary"
        return 1
    }
    printf -v "$cursor_name" '%s' "$action_cursor"
    if ! metadata=$(curl --fail --silent --show-error --noproxy '*' \
        --connect-timeout 2 --max-time 15 \
        --header 'Content-Type: application/json' --data "$payload" \
        --output "$temporary" --write-out '%{http_code}\n%{content_type}\n' \
        "http://$formatted_host:5000/api/avatar/action"); then
        rm -f -- "$temporary"
        return 1
    fi
    http_code=${metadata%%$'\n'*}
    content_type=${metadata#*$'\n'}
    content_type=${content_type%%$'\n'*}
    [[ $http_code =~ ^2[0-9][0-9]$ && \
        ${content_type,,} == application/json* ]] || {
        rm -f -- "$temporary"
        return 1
    }
    if ! python3 - "$temporary" "$behavior" "$intensity" "$duration" <<'PY'
import json
import math
import sys

with open(sys.argv[1], encoding="utf-8") as stream:
    value = json.load(stream)
if not isinstance(value, dict) or set(value) != {
    "ok", "behavior", "intensity", "duration"
}:
    raise SystemExit(1)
if value["ok"] is not True or type(value["behavior"]) is not str:
    raise SystemExit(1)
if value["behavior"] != sys.argv[2]:
    raise SystemExit(1)
for field, expected in (
    ("intensity", float(sys.argv[3])),
    ("duration", float(sys.argv[4])),
):
    observed = value[field]
    if isinstance(observed, bool) or not isinstance(observed, (int, float)):
        raise SystemExit(1)
    if not math.isfinite(float(observed)) or float(observed) != expected:
        raise SystemExit(1)
PY
    then
        rm -f -- "$temporary"
        return 1
    fi
    chmod 600 "$temporary" || {
        rm -f -- "$temporary"
        return 1
    }
    if ! ln -- "$temporary" "$response_file"; then
        rm -f -- "$temporary"
        return 1
    fi
    rm -f -- "$temporary"
    validate_fay_runtime_snapshot
}

post_explain_action() {
    post_motion_action explain 0.65 "$1" "$2" "$3"
}

post_bridge_action() {
    local behavior=$1 label=$2 cursor_name=$3
    [[ $behavior == idle || $behavior == listen ]] || return 1
    post_motion_action "$behavior" "$BRIDGE_ACTION_INTENSITY" \
        "$BRIDGE_ACTION_DURATION" "$label" "$cursor_name"
}

validate_activation_success_records() {
    local result="$activation_evidence/activation-result.txt"
    local after="$activation_evidence/activation-after.txt"
    local result_run_id after_run_id
    [[ -f $result && ! -L $result && -f $after && ! -L $after ]] || return 1
    for exact_record in status=passed activation_complete=1 recovery_mode=1 \
        cleanup_status=verified; do
        [[ $(grep -Fxc "$exact_record" "$result") == 1 ]] || return 1
    done
    for exact_record in status=passed recovery_mode=1 provider=ardy \
        checkpoint=ARDY-Core-RP-20FPS-Horizon8 embedding_count=3; do
        [[ $(grep -Fxc "$exact_record" "$after") == 1 ]] || return 1
    done
    result_run_id=$(sed -n 's/^activation_run_id=//p' "$result") || return 1
    after_run_id=$(sed -n 's/^activation_run_id=//p' "$after") || return 1
    [[ $result_run_id =~ ^[0-9a-f]{64}$ && \
        $after_run_id == "$result_run_id" ]] || return 1
}

activation_target_records_match() {
    local target_id=$1
    [[ $target_id =~ ^[0-9a-f]{64}$ ]] || return 1
    [[ $(grep -Fxc "target_container_id=$target_id" \
        "$activation_evidence/activation-result.txt") == 1 ]] || return 1
    [[ $(grep -Fxc "target_container_id=$target_id" \
        "$activation_evidence/activation-after.txt") == 1 ]]
}

validate_activation_failure_rollback() {
    local result="$activation_evidence/activation-result.txt"
    local current_id
    [[ -f $result && ! -L $result ]] || return 1
    [[ $(grep -Fxc 'status=failed' "$result") == 1 ]] || return 1
    [[ $(grep -Fxc 'recovery_mode=1' "$result") == 1 ]] || return 1
    [[ $(grep -Fxc 'rollback_attempted=1' "$result") == 1 ]] || return 1
    [[ $(grep -Fxc 'rollback_verified=1' "$result") == 1 ]] || return 1
    [[ $(grep -Fxc 'rollback_status=verified' "$result") == 1 ]] || return 1
    current_id=$(container_id_for_name) || return 1
    capture_mock_ardy ardy_rollback "$current_id" || return 1
    rollback_mock_verified=passed
}

attempt_recovery() {
    local require_cursor=${1:-1} activation_status=0 current_id
    [[ $require_cursor =~ ^[01]$ ]] || return 1
    (( activation_in_progress == 0 )) || return 1
    [[ ! -e $activation_evidence && ! -L $activation_evidence ]] || return 1
    : >"$activation_console"
    chmod 600 "$activation_console"
    if (( require_cursor == 1 )); then
        activation_cursor=$(capture_log_cursor) || return 1
    else
        activation_cursor=not-available-emergency-recovery
    fi
    activation_started=1
    activation_requested=1
    activation_in_progress=1
    activation_attempt_count=$((activation_attempt_count + 1))
    if ARDY_ACTIVATION_LOCK_FD=8 "$activator" "$ardy_models_root" "$activation_evidence" \
        >"$activation_console" 2>&1; then
        activation_status=0
    else
        activation_status=$?
    fi
    activation_in_progress=0
    activation_returned=1
    if (( activation_status != 0 )); then
        validate_activation_failure_rollback || return 1
        return "$activation_status"
    fi
    validate_activation_success_records || return 1
    current_id=$(container_id_for_name) || return 1
    capture_real_ardy ardy_recovered "$current_id" || return 1
    activation_target_records_match "${ardy_recovered[1]}" || return 1
    [[ ${ardy_recovered[1]} != "${ardy_before[1]}" && \
        ${ardy_recovered[4]} != "${ardy_before[4]}" && \
        ${ardy_recovered[14]} != "${ardy_before[14]}" && \
        ${ardy_recovered[10]} == "$ardy_models_root" ]] || return 1
    recovery_verified=1
    outage_committed=0
}

capture_exact_original_real_stably() {
    local -n destination=$1
    local expected_id=$2 attempt current_id
    local -a observed=()
    destination=()
    [[ $expected_id =~ ^[0-9a-f]{64}$ && \
        $expected_id == "${ardy_before[1]}" ]] || return 1
    for attempt in $(seq 1 5); do
        current_id=$(container_id_for_name 2>/dev/null) || return 1
        [[ $current_id == "$expected_id" ]] || return 1
        capture_real_ardy observed "$current_id" || return 1
        ardy_immutable_snapshots_equal ardy_before observed || return 1
        [[ ${observed[10]} == "$ardy_models_root" ]] || return 1
        (( attempt == 5 )) || run_bounded_isolated 2 sleep 1 || return 1
    done
    destination=("${observed[@]}")
}

reconcile_recovery_endpoint() {
    local current_id pass original_stability_attempted=0
    local -a reconciled_real=() reconciled_mock=()
    for pass in 1 2; do
        current_id=$(container_id_for_name 2>/dev/null) || {
            if port_is_unused "$ARDY_PORT"; then
                recovery_reconciliation=absent-port-free
                return 2
            fi
            recovery_blocked=unknown-port-claimant-or-ss-failure
            recovery_reconciliation=blocked-port-or-inspection-failure
            return 1
        }
        reconciled_real=()
        if capture_real_ardy reconciled_real "$current_id"; then
            if [[ ${reconciled_real[1]} != "${ardy_before[1]}" && \
                ${reconciled_real[4]} != "${ardy_before[4]}" && \
                ${reconciled_real[14]} != "${ardy_before[14]}" && \
                ${reconciled_real[10]} == "$ardy_models_root" ]]; then
                ardy_recovered=("${reconciled_real[@]}")
                recovery_verified=1
                outage_committed=0
                recovery_reconciliation=exact-new-real
                return 0
            fi
            if ardy_immutable_snapshots_equal ardy_before reconciled_real && \
                [[ ${reconciled_real[10]} == "$ardy_models_root" ]]; then
                if (( original_stability_attempted == 1 )); then
                    recovery_blocked=original-real-not-stably-verifiable
                    recovery_reconciliation=blocked-unstable-original-real
                    return 1
                fi
                original_stability_attempted=1
                if capture_exact_original_real_stably reconciled_real "$current_id"; then
                    # A bounded stop can fail without changing the original
                    # provider. Accept only its exact identity after five
                    # consecutive healthy samples.
                    outage_committed=0
                    recovery_reconciliation=exact-original-real-stable
                    return 0
                fi
                # The original may have completed an asynchronous stop during
                # the stability window. Re-resolve once so a proven absent,
                # port-free endpoint enters emergency recovery rather than
                # becoming a stale unknown-container result.
                continue
            fi
        elif [[ $current_id == "${ardy_before[1]}" ]]; then
            if (( pass == 1 )); then
                # The exact original can auto-remove between resolving its
                # fixed name and inspecting its identity. Re-resolve once so
                # an absent, port-free endpoint enters emergency recovery.
                continue
            fi
            recovery_blocked=original-real-not-stably-verifiable
            recovery_reconciliation=blocked-unstable-original-real
            return 1
        fi
        reconciled_mock=()
        if capture_mock_ardy reconciled_mock "$current_id" && \
            [[ ${reconciled_mock[10]} == "$ardy_models_root" ]]; then
            ardy_rollback=("${reconciled_mock[@]}")
            rollback_mock_verified=passed
            recovery_reconciliation=exact-sealed-mock
            return 0
        fi
        recovery_blocked=unknown-container-claimant
        recovery_reconciliation=blocked-unqualified-fixed-name
        return 1
    done
    recovery_blocked=original-real-not-stably-verifiable
    recovery_reconciliation=blocked-unstable-original-real
    return 1
}

prepare_emergency_activation_attempt() {
    (( emergency_activation_attempted == 0 )) || return 1
    emergency_activation_attempted=1
    if [[ -e $activation_evidence || -L $activation_evidence || \
        -e $activation_console || -L $activation_console ]]; then
        activation_evidence="$gate_root/activation-emergency"
        activation_console="$gate_root/activation-emergency-console.log"
    fi
    [[ ! -e $activation_evidence && ! -L $activation_evidence && \
        ! -e $activation_console && ! -L $activation_console ]]
}

stop_exact_old_ardy() {
    local current_ardy_id stop_status=0 evidence_status=0
    stop_failure_reason='unknown pre-stop validation failure'
    continuity_guard || {
        stop_failure_reason='guarded local identity changed before the ARDY outage'
        return 1
    }
    current_ardy_id=$(container_id_for_name) || {
        stop_failure_reason='the fixed ARDY name could not be re-resolved before the outage'
        return 1
    }
    [[ $current_ardy_id == "$old_container_id" ]] || {
        stop_failure_reason='the fixed ARDY name no longer resolves to the captured container'
        return 1
    }
    capture_real_ardy ardy_pre_stop "$current_ardy_id" || {
        stop_failure_reason='the captured ARDY container failed exact pre-stop revalidation'
        return 1
    }
    ardy_immutable_snapshots_equal ardy_before ardy_pre_stop || {
        stop_failure_reason='the captured ARDY immutable identity changed before stop'
        return 1
    }
    [[ $(image_id "$ARDY_IMAGE" || true) == "$ardy_expected_image_id" ]] || {
        stop_failure_reason='the fixed ARDY image tag changed before stop'
        return 1
    }
    stop_cursor=$(capture_log_cursor) || {
        stop_failure_reason='the fresh pre-stop Unreal log cursor could not be captured'
        return 1
    }
    # Set the deferral flag before committing the outage so a process-group
    # signal cannot land in the gap immediately before the isolated stop.
    ardy_stop_in_progress=1
    outage_committed=1
    if docker_stop_exact_bounded "$old_container_id" \
        >"$gate_root/old-ardy-stop.txt"; then
        outage_performed=1
        chmod 600 "$gate_root/old-ardy-stop.txt" || evidence_status=$?
    else
        stop_status=$?
    fi
    ardy_stop_in_progress=0
    if (( deferred_signal_status != 0 )); then
        handle_signal "$deferred_signal_name" "$deferred_signal_status"
    fi
    if (( stop_status != 0 )); then
        stop_failure_reason='the exact captured real ARDY container did not stop cleanly'
        return 1
    fi
    if (( evidence_status != 0 )); then
        stop_failure_reason='the exact ARDY stop evidence could not be protected'
        return 1
    fi
}

verify_old_ardy_absent_without_claimant() {
    local claimant_id
    absence_failure_reason='ARDY absence could not be verified'
    for _ in $(seq 1 30); do
        if docker inspect --type container "$old_container_id" >/dev/null 2>&1; then
            sleep 1
            continue
        fi
        if claimant_id=$(container_id_for_name 2>/dev/null); then
            recovery_blocked=unknown-container-claimant
            absence_failure_reason="the fixed ARDY name was claimed by $claimant_id"
            return 1
        fi
        if port_is_unused "$ARDY_PORT"; then
            return 0
        fi
        sleep 1
    done
    recovery_blocked=unknown-port-claimant-or-ss-failure
    absence_failure_reason='ARDY absence or the fixed port could not be verified'
    return 1
}

validate_post_recovery_log() {
    local cursor=$1
    [[ $cursor =~ ^[0-9]+$ ]] || return 1
    refresh_recovery_log || return 1
    late_rejected_count=$(marker_count_after 'Rejected ARDY pose batch' "$cursor") || return 1
    late_unavailable_count=$(marker_count_after \
        'ARDY loopback service is unavailable; baked fallback remains active.' \
        "$cursor") || return 1
    late_generated_fallback_count=$(marker_count_after \
        "began a bounded fallback to baked idle" "$cursor") || return 1
    late_neutral_explain_count=$(marker_count_after \
        "Using character-neutral procedural fallback for 'explain'." "$cursor") || return 1
    (( late_rejected_count == 0 && late_unavailable_count == 0 && \
        late_generated_fallback_count == 0 && late_neutral_explain_count == 0 ))
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
                voxtral_restore_verified=passed
                return 0
            fi
            sleep 1
        done
    done
    return 1
}

verify_package_postflight() {
    local launcher_after unreal_after seal_after
    [[ $package_preflight_ready == 1 ]] || return 1
    : >"$gate_root/package-postflight.log"
    chmod 600 "$gate_root/package-postflight.log"
    if ! "$package_verifier" "$package_launcher_dir" \
        >"$gate_root/package-postflight.log" 2>&1; then
        return 1
    fi
    launcher_after=$(sha256sum -- "$package_launcher")
    launcher_after=${launcher_after%% *}
    unreal_after=$(sha256sum -- "$expected_unreal_exe")
    unreal_after=${unreal_after%% *}
    seal_after=$(sha256sum -- "$package_seal")
    seal_after=${seal_after%% *}
    [[ $launcher_after == "$package_launcher_sha256" && \
        $unreal_after == "$unreal_executable_sha256" && \
        $seal_after == "$package_seal_sha256" ]] || return 1
    package_postflight_verified=passed
}

validate_soak_result() {
    local summary="$soak_output/soak-summary.txt"
    [[ -f $summary && ! -L $summary ]] || return 1
    for exact_record in status=passed evidence_class=diagnostic \
        production_qualification=not-claimed \
        verified_teardown_and_fay_survival=passed \
        post_teardown_package_verification=passed runtime_forced_kill=0; do
        [[ $(grep -Fxc "$exact_record" "$summary") == 1 ]] || return 1
    done
}

write_final_record() {
    local entry_status=$1 final_status=$2 status=failed index
    local -a records=()
    (( final_status == 0 )) && status=passed
    records=(
        'schema=1'
        'scope=diagnostic-only-not-production-qualification'
        "status=$status"
        "entry_status=$entry_status"
        "final_status=$final_status"
        "primary_failure=${last_error:-none}"
        "runner_exit_status=$runner_exit_status"
        "runner_forced_kill=$runner_forced_kill"
        "runner_reaped=$runner_reaped"
        "runner_group_post_exit_policy=$runner_group_post_exit_policy"
        "outage_committed=$outage_committed"
        "outage_performed=$outage_performed"
        "activation_started=$activation_started"
        "activation_requested=$activation_requested"
        "activation_in_progress=$activation_in_progress"
        "activation_returned=$activation_returned"
        "activation_attempt_count=$activation_attempt_count"
        "emergency_activation_attempted=$emergency_activation_attempted"
        "primary_activation_evidence=$primary_activation_evidence"
        "final_activation_evidence=$activation_evidence"
        "recovery_blocked=$recovery_blocked"
        "recovery_reconciliation=$recovery_reconciliation"
        "recovery_verified=$recovery_verified"
        "rollback_mock_verified=$rollback_mock_verified"
        "pre_cleanup_recovery_verified=$pre_cleanup_recovery_verified"
        "pre_cleanup_rollback_mock_verified=$pre_cleanup_rollback_mock_verified"
        "pre_cleanup_recovery_blocked=$pre_cleanup_recovery_blocked"
        "pre_cleanup_recovery_reconciliation=$pre_cleanup_recovery_reconciliation"
        "pre_cleanup_ardy_claim_kind=$pre_cleanup_ardy_claim_kind"
        "pre_cleanup_ardy_claim_container_id=$pre_cleanup_ardy_claim_container_id"
        "pre_cleanup_ardy_claim_pid=$pre_cleanup_ardy_claim_pid"
        "pre_cleanup_ardy_claim_process_starttime=$pre_cleanup_ardy_claim_process_starttime"
        "cleanup_ardy_validation_passes=$cleanup_ardy_validation_passes"
        "fay_identity_unchanged=$fay_identity_unchanged"
        "ardy_final_state=$ardy_final_state"
        "package_postflight_verified=$package_postflight_verified"
        "unreal_absent_after=$unreal_absent_after"
        "voxtral_pause_verified=$voxtral_pause_verified"
        "voxtral_pause_continuity=$voxtral_pause_continuity"
        "voxtral_restore_verified=$voxtral_restore_verified"
        "cleanup_error_count=${#cleanup_errors[@]}"
        "finished_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    )
    for index in "${!cleanup_errors[@]}"; do
        records+=("cleanup_error_$((index + 1))=${cleanup_errors[$index]}")
    done
    write_record "$gate_root/recovery-result.txt" "${records[@]}"
}

package_preflight_ready=0
package_postflight_verified=not-checked
package_launcher_sha256=''
unreal_executable_sha256=''
package_seal_sha256=''
package_seal="$package_launcher_dir/.ue5-spark-package.sha256"
fay_snapshot_ready=0
ardy_snapshot_ready=0
voxtral_snapshot_ready=0
voxtral_restore_required=0
voxtral_pause_verified=not-checked
voxtral_pause_continuity=not-checked
voxtral_restore_verified=not-required
activation_started=0
activation_requested=0
activation_in_progress=0
activation_returned=0
activation_attempt_count=0
emergency_activation_attempted=0
activation_cursor=not-captured
recovery_blocked=none
recovery_reconciliation=not-required
outage_committed=0
outage_performed=0
recovery_verified=0
rollback_mock_verified=not-required
pre_cleanup_recovery_verified=not-captured
pre_cleanup_rollback_mock_verified=not-captured
pre_cleanup_recovery_blocked=not-captured
pre_cleanup_recovery_reconciliation=not-captured
pre_cleanup_ardy_claim_kind=not-captured
pre_cleanup_ardy_claim_container_id=not-captured
pre_cleanup_ardy_claim_pid=not-captured
pre_cleanup_ardy_claim_process_starttime=not-captured
cleanup_ardy_validation_passes=0
fay_identity_unchanged=not-checked
ardy_final_state=not-checked
unreal_absent_after=not-checked
first_action_cursor=not-captured
stop_cursor=not-captured
second_action_cursor=not-captured
idle_action_cursor=not-captured
listen_action_cursor=not-captured
retarget_ready_line=not-captured
late_rejected_count=not-checked
late_unavailable_count=not-checked
late_generated_fallback_count=not-checked
late_neutral_explain_count=not-checked
main_completed=0
fay_exe=''
fay_starttime=''
fay_http_host=''
ardy_models_root=''
ardy_expected_image_id=''
ardy_rollback_image_id=''
declare -a fay_listener_bindings_before=()
declare -a fay_listener_bindings_after=()
declare -a ardy_before=()
declare -a ardy_pre_stop=()
declare -a ardy_recovered=()
declare -a ardy_rollback=()
declare -a ardy_final=()
declare -a voxtral_before=()
declare -a voxtral_after=()

validate_previously_verified_ardy_endpoint() {
    local current_id
    local -a observed=()
    if (( recovery_verified == 1 )); then
        current_id=$(container_id_for_name 2>/dev/null) || return 1
        capture_real_ardy observed "$current_id" || return 1
        ardy_immutable_snapshots_equal ardy_recovered observed || return 1
        [[ $(image_id "$ARDY_IMAGE" || true) == "$ardy_expected_image_id" ]] || \
            return 1
        return 0
    fi
    if [[ $rollback_mock_verified == passed ]]; then
        current_id=$(container_id_for_name 2>/dev/null) || return 1
        capture_mock_ardy observed "$current_id" || return 1
        ardy_immutable_snapshots_equal ardy_rollback observed || return 1
        [[ ${observed[10]} == "$ardy_models_root" && \
            $(image_id "$ARDY_ROLLBACK_IMAGE" || true) == \
            "$ardy_rollback_image_id" ]] || return 1
        return 0
    fi
    return 2
}

ensure_ardy_endpoint_on_exit() {
    local claim_status=2 reconciliation_status=0 emergency_status=0
    (( ardy_snapshot_ready == 1 )) || return 0
    cleanup_ardy_validation_passes=$((cleanup_ardy_validation_passes + 1))
    # EXIT cannot run while a foreground activator call is still being
    # awaited. Preserve requested/returned history but clear the transient
    # handoff flag before any live endpoint reconciliation.
    activation_in_progress=0

    if validate_previously_verified_ardy_endpoint; then
        claim_status=0
    else
        claim_status=$?
    fi
    if (( claim_status == 0 )); then
        return 0
    fi
    if (( claim_status == 1 )); then
        note_cleanup_error \
            'the previously verified ARDY endpoint changed before final cleanup validation'
    elif (( outage_committed == 0 && outage_performed == 0 )); then
        return 0
    fi

    recovery_verified=0
    rollback_mock_verified=not-required
    recovery_blocked=none
    recovery_reconciliation=cleanup-live-revalidation
    outage_committed=1
    reconcile_recovery_endpoint
    reconciliation_status=$?
    if (( reconciliation_status == 2 )); then
        if prepare_emergency_activation_attempt; then
            attempt_recovery 0
            emergency_status=$?
            if (( emergency_status != 0 && recovery_verified == 0 )) && \
                [[ $rollback_mock_verified != passed ]]; then
                reconcile_recovery_endpoint || true
            fi
        else
            emergency_status=1
        fi
        if (( recovery_verified == 0 )); then
            if [[ $rollback_mock_verified == passed ]]; then
                note_cleanup_error \
                    'emergency ARDY recovery restored only the sealed mock provider'
            else
                note_cleanup_error \
                    'emergency ARDY recovery did not restore a verified real or mock provider'
            fi
        fi
    elif (( reconciliation_status != 0 )); then
        note_cleanup_error \
            'ARDY endpoint reconciliation found an unknown fixed-name or port claimant; it was not touched'
    fi
}

on_exit() {
    local entry_status=$1 final_status=$1 current_id
    local -a remaining_unreal_pids=() final_mock=()
    trap - EXIT
    trap '' HUP INT TERM
    set +e

    if (( runner_started == 1 && runner_reaped == 0 )); then
        cancel_and_reap_runner || \
            note_cleanup_error 'the owned rendered diagnostic did not stop and reap cleanly'
    fi
    mapfile -t remaining_unreal_pids < <(find_expected_unreal_pids)
    if (( ${#remaining_unreal_pids[@]} == 0 )); then
        unreal_absent_after=passed
    else
        unreal_absent_after=failed
        note_cleanup_error 'the exact packaged Unreal executable remained after runner cleanup'
    fi

    pre_cleanup_recovery_verified=$recovery_verified
    pre_cleanup_rollback_mock_verified=$rollback_mock_verified
    pre_cleanup_recovery_blocked=$recovery_blocked
    pre_cleanup_recovery_reconciliation=$recovery_reconciliation
    if (( recovery_verified == 1 && ${#ardy_recovered[@]} == 19 )); then
        pre_cleanup_ardy_claim_kind=new-real
        pre_cleanup_ardy_claim_container_id=${ardy_recovered[1]}
        pre_cleanup_ardy_claim_pid=${ardy_recovered[4]}
        pre_cleanup_ardy_claim_process_starttime=${ardy_recovered[14]}
    elif [[ $rollback_mock_verified == passed && ${#ardy_rollback[@]} == 19 ]]; then
        pre_cleanup_ardy_claim_kind=sealed-mock
        pre_cleanup_ardy_claim_container_id=${ardy_rollback[1]}
        pre_cleanup_ardy_claim_pid=${ardy_rollback[4]}
        pre_cleanup_ardy_claim_process_starttime=${ardy_rollback[14]}
    else
        pre_cleanup_ardy_claim_kind=none
        pre_cleanup_ardy_claim_container_id=none
        pre_cleanup_ardy_claim_pid=none
        pre_cleanup_ardy_claim_process_starttime=none
    fi
    ensure_ardy_endpoint_on_exit

    if [[ $package_preflight_ready == 1 && $unreal_absent_after == passed ]]; then
        verify_package_postflight || \
            note_cleanup_error 'the cooked package or its exact seal changed during the diagnostic'
    fi

    if [[ $voxtral_pause_verified == passed ]]; then
        if voxtral_is_fully_inactive; then
            voxtral_pause_continuity=passed
        else
            voxtral_pause_continuity=failed
            note_cleanup_error 'the allowlisted Voxtral unit or listener returned before restoration'
        fi
    fi
    if (( voxtral_restore_required == 1 )); then
        restore_voxtral || \
            note_cleanup_error 'the allowlisted Voxtral user unit did not restore with a healthy new identity'
    fi

    # Validate externally managed services only after Voxtral has returned, so
    # the final evidence represents the fully restored steady state.
    if (( fay_snapshot_ready == 1 )); then
        if validate_fay_identity "$fay_exe" "$fay_starttime" && \
            capture_fay_listener_bindings fay_listener_bindings_after && \
            arrays_are_equal fay_listener_bindings_before fay_listener_bindings_after; then
            fay_identity_unchanged=passed
        else
            fay_identity_unchanged=failed
            note_cleanup_error 'Fay did not preserve its exact process and listener identity'
        fi
    fi

    # Revalidate after restoring the allowlisted speech service. That restore
    # can take long enough that an earlier ARDY claim must not be trusted as
    # the final endpoint state.
    ensure_ardy_endpoint_on_exit

    if (( ardy_snapshot_ready == 1 )); then
        if (( recovery_verified == 1 )); then
            current_id=$(container_id_for_name || true)
            if [[ -n $current_id ]] && capture_real_ardy ardy_final "$current_id" && \
                ardy_immutable_snapshots_equal ardy_recovered ardy_final && \
                [[ $(image_id "$ARDY_IMAGE" || true) == "$ardy_expected_image_id" ]]; then
                ardy_final_state=new-real-healthy
            else
                ardy_final_state=failed
                note_cleanup_error 'the recovered real ARDY provider changed identity or health'
            fi
        elif [[ $rollback_mock_verified == passed ]]; then
            current_id=$(container_id_for_name || true)
            if [[ -n $current_id ]] && capture_mock_ardy final_mock "$current_id" && \
                ardy_immutable_snapshots_equal ardy_rollback final_mock && \
                [[ $(image_id "$ARDY_ROLLBACK_IMAGE" || true) == \
                "$ardy_rollback_image_id" ]]; then
                ardy_final_state=sealed-mock-after-failed-recovery
            else
                ardy_final_state=failed
                note_cleanup_error 'the activator failure did not leave a verified sealed mock'
            fi
        elif (( outage_committed == 0 )); then
            current_id=$(container_id_for_name || true)
            if [[ -n $current_id ]] && capture_real_ardy ardy_final "$current_id" && \
                ardy_immutable_snapshots_equal ardy_before ardy_final && \
                [[ $(image_id "$ARDY_IMAGE" || true) == "$ardy_expected_image_id" ]]; then
                ardy_final_state=original-real-unchanged
            else
                ardy_final_state=failed
                note_cleanup_error 'the original real ARDY provider changed before the outage committed'
            fi
        else
            ardy_final_state=unknown-claimant-untouched
            note_cleanup_error 'ARDY recovery remained blocked by absent or unknown fixed-name state'
        fi
    fi

    if (( main_completed != 1 )); then
        final_status=1
    fi
    if (( ${#cleanup_errors[@]} != 0 )); then
        final_status=1
    fi
    if [[ $runner_started == 1 ]] && \
        { [[ ! $runner_exit_status =~ ^[0-9]+$ ]] || (( runner_exit_status != 0 )); }; then
        final_status=1
    fi
    write_final_record "$entry_status" "$final_status" || {
        printf 'error: could not publish the private recovery result record\n' >&2
        final_status=1
    }
    if (( final_status == 0 )); then
        printf 'Guarded local ARDY recovery diagnostic passed; private evidence: %s\n' \
            "$gate_root"
    fi
    trap - EXIT
    exit "$final_status"
}

handle_signal() {
    local signal_name=$1 status=$2
    if (( runner_identity_capture_in_progress == 1 || \
        runner_release_in_progress == 1 || ardy_stop_in_progress == 1 )); then
        if (( deferred_signal_status == 0 )); then
            deferred_signal_name=$signal_name
            deferred_signal_status=$status
            printf 'Deferring %s until the owned critical handoff is complete.\n' \
                "$signal_name" >&2
        fi
        return 0
    fi
    last_error="received-$signal_name"
    printf 'error: received %s; restoring guarded local state\n' "$signal_name" >&2
    exit "$status"
}

trap 'on_exit $?' EXIT
trap 'handle_signal HUP 129' HUP
trap 'handle_signal INT 130' INT
trap 'handle_signal TERM 143' TERM

: >"$gate_root/package-preflight.log"
chmod 600 "$gate_root/package-preflight.log"
if ! "$package_verifier" "$package_launcher_dir" \
    >"$gate_root/package-preflight.log" 2>&1; then
    fail 'the cooked package failed exact deep verification before the diagnostic'
fi
[[ -s $package_seal && -f $package_seal && ! -L $package_seal ]] || \
    fail 'the exact package seal is missing or unsafe after deep verification'
package_launcher_sha256=$(sha256sum -- "$package_launcher")
package_launcher_sha256=${package_launcher_sha256%% *}
unreal_executable_sha256=$(sha256sum -- "$expected_unreal_exe")
unreal_executable_sha256=${unreal_executable_sha256%% *}
package_seal_sha256=$(sha256sum -- "$package_seal")
package_seal_sha256=${package_seal_sha256%% *}
package_preflight_ready=1

ardy_expected_image_id=$(image_id "$ARDY_IMAGE") || \
    fail 'the fixed real ARDY image tag did not resolve to one immutable image ID'
ardy_rollback_image_id=$(image_id "$ARDY_ROLLBACK_IMAGE") || \
    fail 'the fixed rollback ARDY image tag did not resolve to one immutable image ID'
[[ $ardy_expected_image_id != "$ardy_rollback_image_id" ]] || \
    fail 'the real and rollback ARDY tags resolved to one image ID'

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
    fail 'could not snapshot exact Fay listener bindings'
fay_http_host=$(fay_listener_host) || \
    fail 'Fay port 5000 does not have one exact concrete private listener'
fay_snapshot_ready=1

capture_real_ardy ardy_before "$ARDY_CONTAINER" || \
    fail 'the fixed real ARDY container failed exact identity, mount, listener, or health validation'
old_container_id=${ardy_before[1]}
ardy_models_root=${ardy_before[10]}
ardy_snapshot_ready=1

capture_voxtral_snapshot voxtral_before || \
    fail 'the allowlisted Voxtral user unit failed exact identity and health validation'
voxtral_snapshot_ready=1

fay_listener_bindings_sha256=$(array_digest fay_listener_bindings_before)
models_mount_sha256=$(printf '%s' "$ardy_models_root" | sha256sum)
models_mount_sha256=${models_mount_sha256%% *}
write_record "$gate_root/recovery-before.txt" \
    'schema=1' \
    'scope=diagnostic-only-not-production-qualification' \
    "started_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    'character=Ada' \
    'resolution=1280x720' \
    "package_launcher_sha256=$package_launcher_sha256" \
    "unreal_executable_sha256=$unreal_executable_sha256" \
    "package_seal_sha256=$package_seal_sha256" \
    "fay_pid=$fay_pid" \
    "fay_executable=$fay_exe" \
    "fay_starttime=$fay_starttime" \
    "fay_listener_bindings_sha256=$fay_listener_bindings_sha256" \
    "ardy_container_id=${ardy_before[1]}" \
    "ardy_pid=${ardy_before[4]}" \
    "ardy_container_started_at=${ardy_before[5]}" \
    "ardy_image_id=${ardy_before[12]}" \
    "ardy_process_starttime=${ardy_before[14]}" \
    "ardy_models_mount_sha256=$models_mount_sha256" \
    "ardy_provider=${ardy_before[15]}" \
    "ardy_checkpoint=${ardy_before[16]}" \
    "ardy_embedding_count=${ardy_before[17]}" \
    "voxtral_unit=$VOXTRAL_UNIT" \
    "voxtral_pid=${voxtral_before[1]}" \
    "voxtral_executable=${voxtral_before[2]}" \
    "voxtral_starttime=${voxtral_before[3]}" || \
    fail 'could not publish the private preflight identity record'

validate_fay_identity "$fay_exe" "$fay_starttime" || \
    fail 'Fay changed identity before the service pause'
capture_real_ardy ardy_pre_stop "${ardy_before[1]}" || \
    fail 'ARDY changed identity before the service pause'
ardy_immutable_snapshots_equal ardy_before ardy_pre_stop || \
    fail 'ARDY changed immutable state before the service pause'
capture_voxtral_snapshot voxtral_after || fail 'Voxtral changed before the service pause'
[[ ${voxtral_after[1]} == "${voxtral_before[1]}" && \
    ${voxtral_after[2]} == "${voxtral_before[2]}" && \
    ${voxtral_after[3]} == "${voxtral_before[3]}" ]] || \
    fail 'Voxtral changed identity before the service pause'

voxtral_restore_required=1
if ! timeout --signal=TERM --kill-after=5 60 \
    systemctl --user stop "$VOXTRAL_UNIT"; then
    fail 'could not stop the one allowlisted Voxtral user unit'
fi
for _ in $(seq 1 30); do
    if voxtral_is_fully_inactive && \
        ! process_matches_identity "${voxtral_before[1]}" "${voxtral_before[2]}" \
            "${voxtral_before[3]}"; then
        voxtral_pause_verified=passed
        break
    fi
    sleep 1
done
[[ $voxtral_pause_verified == passed ]] || \
    fail 'the allowlisted Voxtral user unit did not become fully inactive'
voxtral_pause_continuity=passed

: >"$runner_console"
chmod 600 "$runner_console"
runner_barrier_path="$gate_root/.runner-start-barrier"
[[ ! -e $runner_barrier_path && ! -L $runner_barrier_path ]] || \
    fail 'the private runner start-barrier path already exists'
mkfifo -m 600 -- "$runner_barrier_path"
[[ -p $runner_barrier_path && -O $runner_barrier_path && ! -L $runner_barrier_path ]] || \
    fail 'the private runner start barrier is not a safe user-owned FIFO'
exec 7<>"$runner_barrier_path"
runner_barrier_fd_open=1
rm -f -- "$runner_barrier_path"
runner_barrier_token=$(python3 -c 'import secrets; print(secrets.token_hex(32))')
[[ $runner_barrier_token =~ ^[0-9a-f]{64}$ ]] || \
    fail 'could not create the private runner start-barrier token'
runner_identity_capture_in_progress=1
(
    export FAY_SOAK_CHARACTER=Ada
    export FAY_SOAK_EXPECTED_RES_X=1280
    export FAY_SOAK_EXPECTED_RES_Y=720
    export FAY_SOAK_EVIDENCE_MODE=diagnostic
    export FAY_SOAK_SCENE_ONLY=0
    export FAY_SOAK_AVATAR_DORMANCY=0
    export FAY_SOAK_ENABLE_CSV=0
    exec 8>&-
    exec 9>&-
    exec setsid "$runner_bash_exe" -c '
        expected_token=$1
        shift
        IFS= read -r observed_token <&7 || exit 70
        exec 7>&-
        [[ $observed_token == "$expected_token" ]] || exit 70
        exec "$@"
    ' ardy-recovery-runner "$runner_barrier_token" "$soak_runner" \
        "$package_launcher" "$fay_pid" "$soak_output" \
        "$RUN_DURATION_SECONDS" "$RUN_TURN_COUNT" >"$runner_console" 2>&1
) &
runner_pid=$!
runner_started=1
if capture_process_record runner_initial_record "$runner_pid" && \
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
            if capture_process_record runner_confirm_record "$runner_pid" && \
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
        fi
        sleep 1 || true
    done
fi
runner_identity_capture_in_progress=0
if (( deferred_signal_status != 0 )); then
    abort_runner_start_barrier || true
    handle_signal "$deferred_signal_name" "$deferred_signal_status"
fi
if (( runner_identity_committed != 1 )); then
    abort_runner_start_barrier || true
    fail 'could not establish the owned rendered diagnostic session identity before its start barrier'
fi
release_runner_start_barrier || {
    cancel_and_reap_runner || true
    fail 'could not release the exact owned rendered diagnostic start barrier'
}
if (( deferred_signal_status != 0 )); then
    handle_signal "$deferred_signal_name" "$deferred_signal_status"
fi

retarget_ready_line=$(wait_for_marker_after \
    'Configured character-neutral body-motion routing (face/head excluded, generated retarget=ready).' \
    0 120) || \
    fail 'the current Ada launch did not prove its reviewed Core27 generated retarget bridge ready'
initial_ready_line=$(wait_for_marker_after 'ARDY loopback service is ready.' 0 120) || \
    fail 'Unreal did not observe the initial real ARDY provider as ready'
speech_start_line=$(wait_for_marker_after 'Started Fay speech playback (' 0 120) || \
    fail 'the fixed one-turn diagnostic did not start Fay speech playback'
(( speech_start_line > initial_ready_line )) || \
    fail 'speech began before the current launch observed real ARDY readiness'

post_explain_action "$FIRST_ACTION_DURATION" first first_action_cursor || \
    fail 'Fay rejected the fixed ten-second explain action contract'
first_generated_line=$(wait_for_marker_after \
    "Using ARDY generated motion provider for 'explain' (bounded_seconds=10.00)." \
    "$first_action_cursor" 30) || \
    fail 'Unreal did not begin the fixed ten-second generated explain action'
finished_during_dispatch=$(find_marker_line_after 'Finished Fay speech playback' \
    "$speech_start_line" || true)
if [[ $finished_during_dispatch =~ ^[1-9][0-9]*$ && \
    $finished_during_dispatch -le $first_generated_line ]]; then
    fail 'the explain action did not overlap the fixed Fay speech turn'
fi

stop_exact_old_ardy || fail "$stop_failure_reason; nothing except the captured ID was eligible"
verify_old_ardy_absent_without_claimant || \
    fail "$absence_failure_reason; no claimant was touched"

unavailable_line=$(wait_for_marker_after \
    'ARDY loopback service is unavailable; baked fallback remains active.' \
    "$stop_cursor" 45) || \
    fail 'Unreal did not report the exact ARDY-unavailable transition'
fallback_line=$(wait_for_marker_after \
    "ARDY action 'explain' began a bounded fallback to baked idle: generated provider became unavailable during the action." \
    "$unavailable_line" 30) || \
    fail 'Unreal did not begin the exact bounded generated-provider fallback'
fallback_complete_line=$(wait_for_marker_after \
    "Completed bounded ARDY action 'explain' and returned to baked idle." \
    "$fallback_line" 30) || \
    fail 'Unreal did not complete the bounded return to baked idle'
facial_summary_line=$(wait_for_marker_after 'Fay facial solve summary' \
    "$speech_start_line" 90) || \
    fail 'the fixed speech turn did not complete its facial solve'
speech_finished_line=$(wait_for_marker_after 'Finished Fay speech playback' \
    "$speech_start_line" 90) || \
    fail 'the fixed speech turn did not finish audio playback'
(( first_generated_line < unavailable_line && \
    unavailable_line < fallback_line && \
    fallback_line < fallback_complete_line && \
    unavailable_line < facial_summary_line && \
    unavailable_line < speech_finished_line && \
    first_generated_line < speech_finished_line )) || \
    fail 'the generated outage, fallback, baked-idle, or speech events were out of order'

if claimant_id=$(container_id_for_name 2>/dev/null); then
    recovery_blocked=unknown-container-claimant
    fail "the fixed ARDY name was claimed by $claimant_id before recovery; it was not touched"
fi
if ! port_is_unused "$ARDY_PORT"; then
    recovery_blocked=unknown-port-claimant-or-ss-failure
    fail 'the fixed ARDY port was claimed or ss failed before recovery; no claimant was touched'
fi
if ! attempt_recovery 1; then
    fail 'the existing guarded activator failed absent-service recovery; any verified mock remains a failure'
fi
continuity_guard || \
    fail 'Fay, Voxtral pause, or the owned runner changed during ARDY recovery'

recovered_ready_line=$(wait_for_marker_after 'ARDY loopback service is ready.' \
    "$activation_cursor" 90) || \
    fail 'Unreal did not observe the newly recovered real ARDY provider as ready'
post_explain_action "$SECOND_ACTION_DURATION" second second_action_cursor || \
    fail 'Fay rejected the fixed post-recovery explain action contract'
second_generated_line=$(wait_for_marker_after \
    "Using ARDY generated motion provider for 'explain' (bounded_seconds=3.00)." \
    "$second_action_cursor" 30) || \
    fail 'Unreal did not begin generated motion from the recovered provider'
second_complete_line=$(wait_for_marker_after \
    "Completed bounded ARDY action 'explain' and returned to baked idle." \
    "$second_generated_line" 30) || \
    fail 'Unreal did not complete the post-recovery generated explain action'
(( recovered_ready_line < second_generated_line && \
    second_generated_line < second_complete_line && \
    retarget_ready_line < second_generated_line )) || \
    fail 'the post-recovery ready, generated-action, and completion events were out of order'

# These no-outage probes cover the other two retained ARDY embeddings and the
# same reviewed retarget bridge without weakening the explain outage sequence.
post_bridge_action idle idle idle_action_cursor || \
    fail 'Fay rejected the fixed post-recovery generated idle bridge contract'
idle_generated_line=$(wait_for_marker_after \
    "Using ARDY generated motion provider for 'idle' (bounded_seconds=1.00)." \
    "$idle_action_cursor" 30) || \
    fail 'Unreal did not route the retained idle embedding through ARDY'
idle_complete_line=$(wait_for_marker_after \
    "Completed bounded ARDY action 'idle' and returned to baked idle." \
    "$idle_generated_line" 30) || \
    fail 'Unreal did not complete the generated idle bridge cleanly'
post_bridge_action listen listen listen_action_cursor || \
    fail 'Fay rejected the fixed post-recovery generated listen bridge contract'
listen_generated_line=$(wait_for_marker_after \
    "Using ARDY generated motion provider for 'listen' (bounded_seconds=1.00)." \
    "$listen_action_cursor" 30) || \
    fail 'Unreal did not route the retained listen embedding through ARDY'
listen_complete_line=$(wait_for_marker_after \
    "Completed bounded ARDY action 'listen' and returned to baked idle." \
    "$listen_generated_line" 30) || \
    fail 'Unreal did not complete the generated listen bridge cleanly'
(( second_complete_line < idle_generated_line && \
    idle_generated_line < idle_complete_line && \
    idle_complete_line < listen_generated_line && \
    listen_generated_line < listen_complete_line )) || \
    fail 'the post-recovery explain, idle, and listen bridge events were out of order'
wait_for_runner_completion || \
    fail 'the owned one-turn rendered diagnostic did not complete cleanly'
validate_soak_result || \
    fail 'the inner rendered diagnostic did not publish a passing diagnostic-only result'
refresh_recovery_log || fail 'could not finalize the private recovery runtime log'
validate_post_recovery_log "$recovered_ready_line" || \
    fail 'Unreal entered a rejected, unavailable, or degraded ARDY state after recovery'

mapfile -t remaining_unreal_pids < <(find_expected_unreal_pids)
(( ${#remaining_unreal_pids[@]} == 0 )) || \
    fail 'the exact packaged Unreal executable remained after owned teardown'
unreal_absent_after=passed

verify_package_postflight || \
    fail 'the exact cooked package, executable, launcher, or seal changed during the diagnostic'
validate_fay_identity "$fay_exe" "$fay_starttime" || \
    fail 'Fay changed identity after the owned Unreal teardown'
capture_fay_listener_bindings fay_listener_bindings_after || \
    fail 'Fay listeners could not be captured after teardown'
arrays_are_equal fay_listener_bindings_before fay_listener_bindings_after || \
    fail 'Fay listener bindings changed during the diagnostic'
current_ardy_id=$(container_id_for_name) || \
    fail 'the recovered real ARDY container disappeared after Unreal teardown'
capture_real_ardy ardy_final "$current_ardy_id" || \
    fail 'the recovered real ARDY provider failed final identity and health validation'
ardy_immutable_snapshots_equal ardy_recovered ardy_final || \
    fail 'the recovered real ARDY identity changed after recovery'
voxtral_is_fully_inactive || \
    fail 'the allowlisted Voxtral unit returned before controlled restoration'

write_record "$gate_root/recovery-events.txt" \
    'schema=1' \
    'outage_performed=1' \
    "first_action_cursor=$first_action_cursor" \
    "initial_ready_line=$initial_ready_line" \
    "speech_start_line=$speech_start_line" \
    "first_generated_line=$first_generated_line" \
    "stop_cursor=$stop_cursor" \
    "unavailable_line=$unavailable_line" \
    "fallback_line=$fallback_line" \
    "fallback_complete_line=$fallback_complete_line" \
    "facial_summary_line=$facial_summary_line" \
    "speech_finished_line=$speech_finished_line" \
    "activation_cursor=$activation_cursor" \
    "recovered_ready_line=$recovered_ready_line" \
    "second_action_cursor=$second_action_cursor" \
    "second_generated_line=$second_generated_line" \
    "second_complete_line=$second_complete_line" \
    "retarget_ready_line=$retarget_ready_line" \
    "idle_action_cursor=$idle_action_cursor" \
    "idle_generated_line=$idle_generated_line" \
    "idle_complete_line=$idle_complete_line" \
    "listen_action_cursor=$listen_action_cursor" \
    "listen_generated_line=$listen_generated_line" \
    "listen_complete_line=$listen_complete_line" \
    'post_recovery_rejected_pose_batches=0' \
    'post_recovery_unavailable_transitions=0' \
    'post_recovery_generated_fallbacks=0' \
    'post_recovery_neutral_explain_fallbacks=0' \
    "old_ardy_container_id=${ardy_before[1]}" \
    "new_ardy_container_id=${ardy_recovered[1]}" \
    "new_ardy_pid=${ardy_recovered[4]}" \
    "new_ardy_starttime=${ardy_recovered[14]}" || \
    fail 'could not publish ordered private recovery evidence'

main_completed=1
last_error=none
exit 0
