#!/usr/bin/env bash
set -euo pipefail
umask 077

last_error='unexpected-command-failure'
activation_complete=0
rollback_armed=0
rollback_verified=0
canary_container_id=''
target_container_id=''
old_container_id=''
evidence_root=''

usage() {
    printf 'Usage: %s MODELS_ROOT PRIVATE_EVIDENCE_DIR\n' "${0##*/}" >&2
}

fail() {
    last_error=$*
    printf 'error: %s\n' "$*" >&2
    exit 1
}

if (( $# != 2 )); then
    usage
    exit 64
fi
[[ $(uname -s) == Linux && $(uname -m) == aarch64 ]] || \
    fail 'the guarded ARDY activation requires Linux/aarch64 on DGX Spark'
(( ${EUID:-$(id -u)} != 0 )) || \
    fail 'run the guarded ARDY activation as the normal workspace owner, not root'

readonly PRODUCTION_CONTAINER='ue5-spark-ardy'
readonly CANARY_CONTAINER='ue5-spark-ardy-canary'
readonly TARGET_IMAGE='ue5-spark-ardy:0.2.0'
readonly ROLLBACK_IMAGE='ue5-spark-ardy:0.1.0'
readonly PRODUCTION_PORT=8777
readonly CANARY_PORT=18777
readonly TARGET_PROVIDER='ardy'
readonly ROLLBACK_PROVIDER='mock'

for command_name in awk chmod curl date dirname docker flock grep id ln mkdir mktemp \
    python3 readlink rm seq sleep ss; do
    command -v "$command_name" >/dev/null 2>&1 || fail "missing command: $command_name"
done

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
repository=$(cd "$script_dir/.." && pwd -P)
validator="$repository/tools/validate_ardy_service.py"
[[ -x $validator && -f $validator && ! -L $validator ]] || \
    fail 'the strict ARDY validator is missing or unsafe'

models_root=$(cd "$1" && pwd -P)
[[ -d $models_root && ! -L $models_root ]] || \
    fail 'MODELS_ROOT must be a real private directory'
[[ -d $models_root/embeddings && ! -L $models_root/embeddings ]] || \
    fail 'the sealed embedding directory is missing'

evidence_parent_input=$(dirname "$2")
evidence_name=${2##*/}
[[ $evidence_name =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$ ]] || \
    fail 'PRIVATE_EVIDENCE_DIR must end in a simple unique run name'
[[ -d $evidence_parent_input ]] || fail 'the private evidence parent does not exist'
evidence_parent=$(cd "$evidence_parent_input" && pwd -P)
evidence_root="$evidence_parent/$evidence_name"
case "$evidence_root/" in
    */logs-private/*) private_root=${evidence_root%%/logs-private/*}/logs-private ;;
    *) fail 'PRIVATE_EVIDENCE_DIR must be below a logs-private root' ;;
esac
[[ -d $private_root && ! -L $private_root ]] || \
    fail 'the selected logs-private root is missing or unsafe'
[[ ! -e $evidence_root && ! -L $evidence_root ]] || \
    fail 'PRIVATE_EVIDENCE_DIR must not already exist'

lock_file="$private_root/.ardy-activation.lock"
[[ ! -L $lock_file ]] || fail 'the ARDY activation lock is a symlink'
exec 9>>"$lock_file"
chmod 600 "$lock_file"
flock -n 9 || fail 'another guarded ARDY activation owns this private root'
[[ ! -e $evidence_root && ! -L $evidence_root ]] || \
    fail 'PRIVATE_EVIDENCE_DIR appeared while acquiring the lock'
mkdir -m 700 -- "$evidence_root"
[[ $(cd "$evidence_root" && pwd -P) == "$evidence_root" ]] || \
    fail 'could not establish the exact private evidence directory'

write_record() {
    local destination=$1
    shift
    local temporary
    [[ $destination == "$evidence_root/"* && ! -e $destination && ! -L $destination ]] || \
        return 1
    temporary=$(mktemp "$evidence_root/.record.XXXXXX") || return 1
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

image_id() {
    local value
    value=$(docker image inspect --format '{{.Id}}' "$1" 2>/dev/null) || return 1
    [[ $value =~ ^sha256:[0-9a-f]{64}$ ]] || return 1
    printf '%s\n' "$value"
}

container_id_for_name() {
    local value
    value=$(docker inspect --type container --format '{{.Id}}' "$1" 2>/dev/null) || return 1
    [[ $value =~ ^[0-9a-f]{64}$ ]] || return 1
    printf '%s\n' "$value"
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

capture_verified_container() {
    local -n destination=$1
    local identifier=$2 expected_name=$3 expected_tag=$4 expected_image_id=$5
    local expected_provider=$6 expected_port=$7 expected_auto_remove=$8 label=$9
    local inspect_file parsed_file pid
    inspect_file="$evidence_root/$label-inspect.json"
    parsed_file="$evidence_root/$label-container.txt"
    [[ ! -e $inspect_file && ! -L $inspect_file && \
        ! -e $parsed_file && ! -L $parsed_file ]] || return 1
    docker inspect --type container "$identifier" >"$inspect_file" || return 1
    chmod 600 "$inspect_file"
    if ! python3 - "$identifier" "$expected_name" "$expected_tag" \
        "$expected_image_id" "$expected_provider" "$expected_port" \
        "$expected_auto_remove" "$models_root" "$(id -u):$(id -g)" \
        "$inspect_file" >"$parsed_file" <<'PY'
import json
import re
import sys

(
    identifier,
    expected_name,
    expected_tag,
    expected_image_id,
    expected_provider,
    expected_port,
    expected_auto_remove,
    expected_models_root,
    expected_user,
    inspect_file,
) = sys.argv[1:]
with open(inspect_file, encoding="utf-8") as stream:
    records = json.load(stream)
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
    or config.get("Image") != expected_tag
    or record.get("Image") != expected_image_id
    or state.get("Running") is not True
    or state.get("Dead") is not False
    or state.get("OOMKilled") is not False
    or state.get("Error") not in {None, ""}
    or not isinstance(state.get("Pid"), int)
    or state.get("Pid", 0) <= 0
    or record.get("RestartCount") != 0
    or host.get("AutoRemove") is not (expected_auto_remove == "true")
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
    or mount.get("Source") != expected_models_root
    or mount.get("Destination") != "/models"
    or mount.get("RW") is not False
):
    raise SystemExit(1)
expected_command = [
    "--host", "127.0.0.1",
    "--port", expected_port,
    "--provider", expected_provider,
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
    container_id,
    str(state["Pid"]),
    state.get("StartedAt", ""),
    record["Image"],
    config["Image"],
    expected_provider,
    expected_port,
    mount["Source"],
)
print("\n".join(values))
PY
    then
        return 1
    fi
    chmod 600 "$parsed_file"
    mapfile -t destination <"$parsed_file"
    (( ${#destination[@]} == 8 )) || return 1
    pid=${destination[1]}
    [[ ${destination[0]} == "$identifier" || $identifier == "$expected_name" ]] || return 1
    [[ $pid =~ ^[1-9][0-9]*$ ]] || return 1
    loopback_listener_owned_by_pid "$expected_port" "$pid"
}

probe_mock_health() {
    local port=$1 output=$2 body
    body=$(curl --fail --silent --show-error --noproxy '*' \
        --connect-timeout 2 --max-time 5 "http://127.0.0.1:$port/healthz") || return 1
    (( ${#body} <= 65536 )) || return 1
    if ! printf '%s' "$body" | python3 -c '
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
'; then
        return 1
    fi
    write_record "$output" "$body"
}

wait_for_mock_health() {
    local port=$1 output=$2 attempt
    for attempt in $(seq 1 60); do
        if probe_mock_health "$port" "$output"; then
            return 0
        fi
        sleep 1
    done
    return 1
}

launch_container() {
    local name=$1 image=$2 port=$3 provider=$4 auto_remove=$5
    local -a arguments=(docker run --detach)
    if [[ $auto_remove == true ]]; then
        arguments+=(--rm)
    fi
    arguments+=(
        --name "$name"
        --gpus all
        --network host
        --read-only
        --cap-drop ALL
        --security-opt no-new-privileges:true
        --pids-limit 512
        --shm-size 4g
        --tmpfs /tmp:rw,noexec,nosuid,size=1g
        --user "$(id -u):$(id -g)"
        --mount "type=bind,src=$models_root,dst=/models,readonly"
        "$image"
        --host 127.0.0.1 --port "$port" --provider "$provider" --models-root /models
    )
    "${arguments[@]}"
}

capture_container_logs() {
    local container_id=$1 destination=$2
    [[ $container_id =~ ^[0-9a-f]{64}$ && \
        $destination == "$evidence_root/"* && ! -e $destination ]] || return 1
    docker logs "$container_id" >"$destination" 2>&1 || true
    chmod 600 "$destination"
}

cleanup_canary() {
    local current_id
    [[ -n $canary_container_id ]] || return 0
    capture_container_logs "$canary_container_id" "$evidence_root/canary-container.log"
    if docker inspect --type container "$canary_container_id" >/dev/null 2>&1; then
        docker stop --time 20 "$canary_container_id" >/dev/null 2>&1 || true
    fi
    if docker inspect --type container "$canary_container_id" >/dev/null 2>&1; then
        docker rm "$canary_container_id" >/dev/null 2>&1 || return 1
    fi
    current_id=$(container_id_for_name "$CANARY_CONTAINER" 2>/dev/null || true)
    [[ -z $current_id ]]
}

restore_rollback() {
    local current_id rollback_id
    local -a rollback_snapshot=()
    if [[ -n $old_container_id ]] && \
        docker inspect --type container "$old_container_id" >/dev/null 2>&1; then
        current_id=$(container_id_for_name "$PRODUCTION_CONTAINER" 2>/dev/null || true)
        if [[ $current_id == "$old_container_id" ]]; then
            if probe_mock_health "$PRODUCTION_PORT" \
                "$evidence_root/rollback-existing-health.json"; then
                rollback_verified=1
                return 0
            fi
            return 1
        fi
    fi
    if [[ -n $target_container_id ]] && \
        docker inspect --type container "$target_container_id" >/dev/null 2>&1; then
        capture_container_logs "$target_container_id" \
            "$evidence_root/failed-target-container.log"
        docker stop --time 20 "$target_container_id" >/dev/null 2>&1 || true
    fi
    current_id=$(container_id_for_name "$PRODUCTION_CONTAINER" 2>/dev/null || true)
    [[ -z $current_id ]] || return 1
    rollback_id=$(launch_container "$PRODUCTION_CONTAINER" "$ROLLBACK_IMAGE" \
        "$PRODUCTION_PORT" "$ROLLBACK_PROVIDER" true) || return 1
    [[ $rollback_id =~ ^[0-9a-f]{64}$ ]] || return 1
    if ! wait_for_mock_health "$PRODUCTION_PORT" \
        "$evidence_root/rollback-health.json"; then
        return 1
    fi
    capture_verified_container rollback_snapshot "$rollback_id" "$PRODUCTION_CONTAINER" \
        "$ROLLBACK_IMAGE" "$rollback_image_id" "$ROLLBACK_PROVIDER" \
        "$PRODUCTION_PORT" true rollback || return 1
    rollback_verified=1
}

on_exit() {
    local status=$?
    set +e
    cleanup_canary
    if (( status != 0 && rollback_armed == 1 && activation_complete == 0 )); then
        restore_rollback
    fi
    if [[ -n $evidence_root && -d $evidence_root && \
        ! -e $evidence_root/activation-result.txt ]]; then
        write_record "$evidence_root/activation-result.txt" \
            'schema=1' \
            "completed_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
            "status=$([[ $status == 0 ]] && printf passed || printf failed)" \
            "error=$last_error" \
            "activation_complete=$activation_complete" \
            "rollback_armed=$rollback_armed" \
            "rollback_verified=$rollback_verified" \
            "old_container_id=$old_container_id" \
            "target_container_id=$target_container_id" \
            "target_image_id=${target_image_id:-unavailable}" \
            "rollback_image_id=${rollback_image_id:-unavailable}"
    fi
    trap - EXIT
    exit "$status"
}

handle_signal() {
    last_error="received-$1"
    exit "$2"
}

trap 'on_exit' EXIT
trap 'handle_signal HUP 129' HUP
trap 'handle_signal INT 130' INT
trap 'handle_signal TERM 143' TERM

target_image_id=$(image_id "$TARGET_IMAGE") || fail "missing target image: $TARGET_IMAGE"
rollback_image_id=$(image_id "$ROLLBACK_IMAGE") || fail "missing rollback image: $ROLLBACK_IMAGE"
[[ $target_image_id != "$rollback_image_id" ]] || fail 'target and rollback resolve to one image'

existing_canary_id=$(container_id_for_name "$CANARY_CONTAINER" 2>/dev/null || true)
[[ -z $existing_canary_id ]] || \
    fail 'the fixed canary container name is already in use; it was not touched'
old_container_id=$(container_id_for_name "$PRODUCTION_CONTAINER") || \
    fail 'the fixed production ARDY container is not running'

current_image_tag=$(docker inspect --type container --format '{{.Config.Image}}' \
    "$old_container_id") || fail 'could not identify the production ARDY image tag'
declare -a production_before=() production_reverified=() production_after=()
if [[ $current_image_tag == "$TARGET_IMAGE" ]]; then
    capture_verified_container production_before "$old_container_id" \
        "$PRODUCTION_CONTAINER" "$TARGET_IMAGE" "$target_image_id" "$TARGET_PROVIDER" \
        "$PRODUCTION_PORT" true production-already-active || \
        fail 'the existing real production container failed its identity contract'
    "$validator" --port "$PRODUCTION_PORT" --batches 30 --startup-timeout 180 \
        >"$evidence_root/production-already-active-validation.json" \
        2>"$evidence_root/production-already-active-validation.stderr" || \
        fail 'the existing real production provider failed qualification'
    chmod 600 "$evidence_root"/production-already-active-validation.*
    activation_complete=1
    last_error='none-already-active'
    printf 'ARDY was already real and passed qualification; private evidence: %s\n' \
        "$evidence_root"
    exit 0
fi
[[ $current_image_tag == "$ROLLBACK_IMAGE" ]] || \
    fail 'production uses neither the sealed rollback nor target image tag'
capture_verified_container production_before "$old_container_id" \
    "$PRODUCTION_CONTAINER" "$ROLLBACK_IMAGE" "$rollback_image_id" "$ROLLBACK_PROVIDER" \
    "$PRODUCTION_PORT" true production-before || \
    fail 'the current mock rollback failed its identity and isolation contract'
wait_for_mock_health "$PRODUCTION_PORT" "$evidence_root/production-before-health.json" || \
    fail 'the current mock rollback failed its exact health contract'

write_record "$evidence_root/activation-before.txt" \
    'schema=1' \
    "started_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    "models_root=$models_root" \
    "old_container_id=$old_container_id" \
    "target_image=$TARGET_IMAGE" \
    "target_image_id=$target_image_id" \
    "rollback_image=$ROLLBACK_IMAGE" \
    "rollback_image_id=$rollback_image_id" || \
    fail 'could not publish the activation preflight record'

canary_container_id=$(launch_container "$CANARY_CONTAINER" "$TARGET_IMAGE" \
    "$CANARY_PORT" "$TARGET_PROVIDER" false) || fail 'could not launch the retained real canary'
[[ $canary_container_id =~ ^[0-9a-f]{64}$ ]] || fail 'canary returned an invalid container ID'
"$validator" --port "$CANARY_PORT" --batches 30 --startup-timeout 180 \
    >"$evidence_root/canary-validation.json" \
    2>"$evidence_root/canary-validation.stderr" || \
    fail 'the retained real canary failed strict qualification'
chmod 600 "$evidence_root"/canary-validation.*
declare -a canary_snapshot=()
capture_verified_container canary_snapshot "$canary_container_id" "$CANARY_CONTAINER" \
    "$TARGET_IMAGE" "$target_image_id" "$TARGET_PROVIDER" "$CANARY_PORT" false canary || \
    fail 'the qualified canary failed its identity and isolation contract'
cleanup_canary || fail 'the exact retained canary could not be removed safely'
canary_container_id=''

capture_verified_container production_reverified "$old_container_id" \
    "$PRODUCTION_CONTAINER" "$ROLLBACK_IMAGE" "$rollback_image_id" "$ROLLBACK_PROVIDER" \
    "$PRODUCTION_PORT" true production-reverified || \
    fail 'production changed while the isolated canary was qualifying'
[[ ${production_before[0]} == "${production_reverified[0]}" && \
    ${production_before[1]} == "${production_reverified[1]}" && \
    ${production_before[2]} == "${production_reverified[2]}" ]] || \
    fail 'production identity changed while the isolated canary was qualifying'
wait_for_mock_health "$PRODUCTION_PORT" \
    "$evidence_root/production-reverified-health.json" || \
    fail 'the mock rollback health changed during canary qualification'

rollback_armed=1
docker stop --time 20 "$old_container_id" >"$evidence_root/production-stop.txt" || \
    fail 'could not stop the exact recorded mock rollback container'
chmod 600 "$evidence_root/production-stop.txt"
for _ in $(seq 1 30); do
    if ! docker inspect --type container "$old_container_id" >/dev/null 2>&1 && \
        ! container_id_for_name "$PRODUCTION_CONTAINER" >/dev/null 2>&1; then
        break
    fi
    sleep 1
done
! docker inspect --type container "$old_container_id" >/dev/null 2>&1 || \
    fail 'the exact mock rollback container did not disappear after stop'
! container_id_for_name "$PRODUCTION_CONTAINER" >/dev/null 2>&1 || \
    fail 'the production container name was unexpectedly reclaimed'

target_container_id=$(launch_container "$PRODUCTION_CONTAINER" "$TARGET_IMAGE" \
    "$PRODUCTION_PORT" "$TARGET_PROVIDER" true) || fail 'could not launch the real provider'
[[ $target_container_id =~ ^[0-9a-f]{64}$ ]] || fail 'target returned an invalid container ID'
"$validator" --port "$PRODUCTION_PORT" --batches 30 --startup-timeout 180 \
    >"$evidence_root/production-validation.json" \
    2>"$evidence_root/production-validation.stderr" || \
    fail 'the real production provider failed strict qualification'
chmod 600 "$evidence_root"/production-validation.*
capture_verified_container production_after "$target_container_id" "$PRODUCTION_CONTAINER" \
    "$TARGET_IMAGE" "$target_image_id" "$TARGET_PROVIDER" "$PRODUCTION_PORT" true \
    production-after || fail 'the real provider failed its final identity and isolation contract'

last_error='none'
write_record "$evidence_root/activation-after.txt" \
    'schema=1' \
    "completed_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    'status=passed' \
    "old_container_id=$old_container_id" \
    "target_container_id=$target_container_id" \
    "target_image_id=$target_image_id" \
    'provider=ardy' \
    'checkpoint=ARDY-Core-RP-20FPS-Horizon8' \
    'embedding_count=3' || fail 'could not publish the activation success record'
activation_complete=1
printf 'Guarded ARDY real-provider activation passed; private evidence: %s\n' \
    "$evidence_root"
