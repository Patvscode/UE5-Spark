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
target_image_id=''
rollback_image_id=''
evidence_root=''
recovery_mode=0
rollback_attempted=0
rollback_status='not-required'
cleanup_status='not-required'
exit_cleanup_signals_masked=0
exit_cleanup_started_utc='not-started'
activation_run_id=''
pending_launch_active=0
pending_launch_name=''
pending_launch_image=''
pending_launch_port=''
pending_launch_provider=''
pending_launch_auto_remove=''
pending_launch_role=''
pending_launch_cidfile=''
pending_launch_absence_verified=0
pending_launch_absent_id=''
rollback_models_root=''
rollback_models_seal=''
target_models_seal=''

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
readonly TARGET_IMAGE='ue5-spark-ardy:0.3.0'
readonly ROLLBACK_IMAGE='ue5-spark-ardy:0.2.0'
readonly PRODUCTION_PORT=8777
readonly CANARY_PORT=18777
readonly TARGET_PROVIDER='ardy'
readonly ROLLBACK_PROVIDER='ardy'
readonly RUN_LABEL_KEY='com.ue5-spark.ardy.activation-run'
readonly ROLE_LABEL_KEY='com.ue5-spark.ardy.activation-role'

for command_name in awk chmod curl date dirname docker flock grep id ln mkdir mktemp \
    python3 readlink rm seq setsid sleep ss timeout; do
    command -v "$command_name" >/dev/null 2>&1 || fail "missing command: $command_name"
done

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
repository=$(cd "$script_dir/.." && pwd -P)
validator="$repository/tools/validate_ardy_service.py"
[[ -x $validator && -f $validator && ! -L $validator ]] || \
    fail 'the strict ARDY validator is missing or unsafe'

models_root=$(cd "$1" && pwd -P)
[[ -d $models_root && ! -L $models_root ]] || \
    fail 'MODELS_ROOT must be a real private v2 candidate directory'
[[ -d $models_root/embeddings && ! -L $models_root/embeddings ]] || \
    fail 'the sealed v2 candidate embedding directory is missing'

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

lock_parent="/run/user/$(id -u)"
[[ -d $lock_parent && ! -L $lock_parent ]] || \
    fail 'the fixed per-user runtime directory is missing or unsafe'
lock_parent=$(cd "$lock_parent" && pwd -P)
[[ $lock_parent == "/run/user/$(id -u)" ]] || \
    fail 'the fixed per-user runtime directory resolved unexpectedly'
lock_file="$lock_parent/ue5-spark-ardy.activation.lock"
[[ ! -L $lock_file ]] || fail 'the ARDY activation lock is a symlink'
inherited_lock_fd=${ARDY_ACTIVATION_LOCK_FD:-}
if [[ -n $inherited_lock_fd ]]; then
    [[ $inherited_lock_fd =~ ^[3-9]$|^[1-9][0-9]$ ]] || \
        fail 'ARDY_ACTIVATION_LOCK_FD must name an inherited descriptor from 3 through 99'
    [[ -e /proc/self/fdinfo/$inherited_lock_fd ]] || \
        fail 'the inherited ARDY activation lock descriptor is not open'
    inherited_lock_path=$(readlink -f "/proc/self/fd/$inherited_lock_fd" 2>/dev/null || true)
    [[ $inherited_lock_path == "$lock_file" ]] || \
        fail 'the inherited ARDY activation lock descriptor resolves to an unexpected path'
    [[ -f $lock_file && -O $lock_file ]] || \
        fail 'the inherited ARDY activation lock is missing or not user-owned'
    flock -n "$inherited_lock_fd" || \
        fail 'the inherited ARDY activation lock descriptor is not usable'
else
    exec 9>>"$lock_file"
    chmod 600 "$lock_file"
    flock -n 9 || fail 'another guarded ARDY activation is already running for this user'
fi
[[ ! -e $evidence_root && ! -L $evidence_root ]] || \
    fail 'PRIVATE_EVIDENCE_DIR appeared while acquiring the lock'
mkdir -m 700 -- "$evidence_root"
[[ $(cd "$evidence_root" && pwd -P) == "$evidence_root" ]] || \
    fail 'could not establish the exact private evidence directory'
activation_run_id=$(python3 -c 'import secrets; print(secrets.token_hex(32))')
[[ $activation_run_id =~ ^[0-9a-f]{64}$ ]] || \
    fail 'could not generate the private activation ownership nonce'

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

run_bounded_isolated() {
    local timeout_seconds=$1
    shift
    # Keep every bounded Docker/inspection child outside the caller's terminal
    # process group. EXIT cleanup ignores HUP/INT/TERM in this shell; the new
    # session also prevents a repeated Ctrl-C/TERM from killing the child that
    # is restoring the sealed rollback endpoint.
    setsid --wait timeout --foreground --signal=TERM --kill-after=5 \
        "$timeout_seconds" "$@"
}

sleep_isolated() {
    setsid --wait sleep "$@"
}

docker_read_bounded() {
    run_bounded_isolated 20 docker "$@"
}

docker_stop_bounded() {
    local container_id=$1
    [[ $container_id =~ ^[0-9a-f]{64}$ ]] || return 1
    run_bounded_isolated 30 docker stop --time 20 "$container_id"
}

docker_remove_bounded() {
    local container_id=$1
    [[ $container_id =~ ^[0-9a-f]{64}$ ]] || return 1
    run_bounded_isolated 20 docker rm "$container_id"
}

docker_logs_bounded() {
    local container_id=$1
    [[ $container_id =~ ^[0-9a-f]{64}$ ]] || return 1
    run_bounded_isolated 20 docker logs "$container_id"
}

docker_run_bounded() {
    run_bounded_isolated 90 docker run "$@"
}

ss_bounded() {
    run_bounded_isolated 10 ss "$@"
}

image_id() {
    local value
    value=$(docker_read_bounded image inspect --format '{{.Id}}' "$1" \
        2>/dev/null) || return 1
    [[ $value =~ ^sha256:[0-9a-f]{64}$ ]] || return 1
    printf '%s\n' "$value"
}

discover_readonly_models_root() {
    local -n destination=$1
    local identifier=$2 label=$3 inspect_file parsed_file resolved
    local -a discovered=()
    destination=''
    inspect_file="$evidence_root/$label-mount-inspect.json"
    parsed_file="$evidence_root/$label-models-root.txt"
    [[ ! -e $inspect_file && ! -L $inspect_file && \
        ! -e $parsed_file && ! -L $parsed_file ]] || return 1
    docker_read_bounded inspect --type container "$identifier" >"$inspect_file" || \
        return 1
    chmod 600 "$inspect_file"
    if ! python3 - "$inspect_file" >"$parsed_file" <<'PY'
import json
import os
import sys

with open(sys.argv[1], encoding="utf-8") as stream:
    records = json.load(stream)
if not isinstance(records, list) or len(records) != 1:
    raise SystemExit(1)
mounts = records[0].get("Mounts")
if not isinstance(mounts, list) or len(mounts) != 1:
    raise SystemExit(1)
mount = mounts[0]
source = mount.get("Source")
if (
    mount.get("Type") != "bind"
    or not isinstance(source, str)
    or not os.path.isabs(source)
    or source in {"", "/"}
    or mount.get("Destination") != "/models"
    or mount.get("RW") is not False
    or mount.get("Mode") not in {None, ""}
    or mount.get("Propagation") not in {None, "rprivate"}
):
    raise SystemExit(1)
print(source)
PY
    then
        return 1
    fi
    chmod 600 "$parsed_file"
    mapfile -t discovered <"$parsed_file"
    (( ${#discovered[@]} == 1 )) || return 1
    [[ -d ${discovered[0]} && ! -L ${discovered[0]} ]] || return 1
    resolved=$(cd "${discovered[0]}" && pwd -P) || return 1
    [[ $resolved == "${discovered[0]}" ]] || return 1
    [[ -d $resolved/embeddings && ! -L $resolved/embeddings ]] || return 1
    destination=$resolved
}

seal_models_tree() {
    local -n destination=$1
    local root=$2 output=$3 report
    destination=''
    [[ -d $root && ! -L $root && \
        $output == "$evidence_root/"* && ! -e $output && ! -L $output ]] || return 1
    report=$(python3 - "$root" <<'PY'
import hashlib
import json
import os
import stat
import sys

root = os.path.realpath(sys.argv[1])
if root != sys.argv[1] or root == "/" or not os.path.isdir(root):
    raise SystemExit(1)
sensitive_names = {
    ".env", ".token", "token", "hf_token", "huggingface_token",
    "credentials", "credentials.json", "secrets", "secrets.json",
}
entries = []
for current, directories, files in os.walk(root, topdown=True, followlinks=False):
    directories.sort()
    files.sort()
    for name in directories:
        path = os.path.join(current, name)
        metadata = os.lstat(path)
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise SystemExit(1)
    for name in files:
        path = os.path.join(current, name)
        relative = os.path.relpath(path, root)
        if name.casefold() in sensitive_names or name.casefold().endswith((".key", ".pem")):
            raise SystemExit(1)
        metadata = os.lstat(path)
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise SystemExit(1)
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        try:
            opened = os.fstat(descriptor)
            if (
                (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns)
                != (metadata.st_dev, metadata.st_ino, metadata.st_size, metadata.st_mtime_ns)
                or not stat.S_ISREG(opened.st_mode)
            ):
                raise SystemExit(1)
            digest = hashlib.sha256()
            while True:
                block = os.read(descriptor, 8 * 1024 * 1024)
                if not block:
                    break
                digest.update(block)
            closed = os.fstat(descriptor)
            if (
                closed.st_dev,
                closed.st_ino,
                closed.st_size,
                closed.st_mtime_ns,
            ) != (
                opened.st_dev,
                opened.st_ino,
                opened.st_size,
                opened.st_mtime_ns,
            ):
                raise SystemExit(1)
        finally:
            os.close(descriptor)
        entries.append((relative, opened.st_size, digest.hexdigest()))
aggregate = hashlib.sha256()
for relative, size, digest in entries:
    aggregate.update(relative.encode("utf-8"))
    aggregate.update(b"\0")
    aggregate.update(str(size).encode("ascii"))
    aggregate.update(b"\0")
    aggregate.update(digest.encode("ascii"))
    aggregate.update(b"\n")
print(json.dumps({
    "schema": 1,
    "root": root,
    "fileCount": len(entries),
    "totalBytes": sum(entry[1] for entry in entries),
    "treeSha256": aggregate.hexdigest(),
}, sort_keys=True, separators=(",", ":")))
PY
    ) || return 1
    [[ ${#report} -le 65536 ]] || return 1
    write_record "$output" "$report" || return 1
    destination=$(python3 -c '
import json, sys
value = json.load(sys.stdin)
digest = value.get("treeSha256")
if not isinstance(digest, str) or len(digest) != 64:
    raise SystemExit(1)
print(digest)
' <<<"$report") || return 1
    [[ $destination =~ ^[0-9a-f]{64}$ ]]
}

container_id_for_name() {
    local value
    value=$(docker_read_bounded inspect --type container --format '{{.Id}}' "$1" \
        2>/dev/null) || return 1
    [[ $value =~ ^[0-9a-f]{64}$ ]] || return 1
    printf '%s\n' "$value"
}

loopback_listener_owned_by_pid() {
    local port=$1 pid=$2 listeners line endpoint other_owner count=0
    listeners=$(ss_bounded -H -ltnp "sport = :$port" 2>/dev/null) || return 1
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

loopback_port_is_unused() {
    local listeners
    listeners=$(ss_bounded -H -ltn "sport = :$1" 2>/dev/null) || return 1
    [[ -z $listeners ]]
}

capture_verified_container() {
    local -n destination=$1
    local identifier=$2 expected_name=$3 expected_tag=$4 expected_image_id=$5
    local expected_provider=$6 expected_port=$7 expected_auto_remove=$8 label=$9
    local expected_models_root=${10}
    local expected_role=${11:-preexisting}
    local inspect_file parsed_file pid
    inspect_file="$evidence_root/$label-inspect.json"
    parsed_file="$evidence_root/$label-container.txt"
    [[ ! -e $inspect_file && ! -L $inspect_file && \
        ! -e $parsed_file && ! -L $parsed_file ]] || return 1
    docker_read_bounded inspect --type container "$identifier" >"$inspect_file" || return 1
    chmod 600 "$inspect_file"
    if ! python3 - "$identifier" "$expected_name" "$expected_tag" \
        "$expected_image_id" "$expected_provider" "$expected_port" \
        "$expected_auto_remove" "$expected_models_root" "$(id -u):$(id -g)" \
        "$activation_run_id" "$expected_role" "$RUN_LABEL_KEY" "$ROLE_LABEL_KEY" \
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
    activation_run_id,
    expected_role,
    run_label_key,
    role_label_key,
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
labels = config.get("Labels") or {}
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
    or host.get("SecurityOpt") != ["no-new-privileges:true"]
    or host.get("PidsLimit") != 512
    or host.get("ShmSize") != 4 * 1024**3
    or host.get("Tmpfs") != {"/tmp": "rw,noexec,nosuid,size=1g"}
    or config.get("User") != expected_user
):
    raise SystemExit(1)
if expected_role != "preexisting" and (
    not isinstance(labels, dict)
    or labels.get(run_label_key) != activation_run_id
    or labels.get(role_label_key) != expected_role
):
    raise SystemExit(1)
device_requests = host.get("DeviceRequests")
if device_requests != [{
    "Driver": "",
    "Count": -1,
    "DeviceIDs": None,
    "Capabilities": [["gpu"]],
    "Options": {},
}]:
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
    or mount.get("Mode") not in {None, ""}
    or mount.get("Propagation") not in {None, "rprivate"}
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

qualify_v1_rollback() {
    local port=$1 output=$2 report
    [[ $port == "$PRODUCTION_PORT" && \
        $output == "$evidence_root/"* && ! -e $output && ! -L $output ]] || return 1
    report=$(python3 - "$port" <<'PY'
import json
import math
import sys
import time
import urllib.error
import urllib.request

port = int(sys.argv[1])
if port != 8777:
    raise SystemExit(1)
behaviors = ("idle", "listen", "explain")
expected_health = {
    "status": "ready",
    "provider": "ardy",
    "protocolVersion": 1,
    "fps": 20,
    "bufferFrames": 8,
    "facialControl": "excluded",
    "checkpoint": "ARDY-Core-RP-20FPS-Horizon8",
    "embeddingCount": 3,
}
coordinate_system = "ardy-y-up-z-forward-meters"
identity = [0.0, 0.0, 0.0, 1.0]
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def request(path, payload=None, timeout=5.0):
    body = None
    headers = {"Accept": "application/json"}
    method = "GET"
    if payload is not None:
        body = json.dumps(payload, separators=(",", ":"), allow_nan=False).encode()
        headers["Content-Type"] = "application/json"
        method = "POST"
    value = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=body,
        headers=headers,
        method=method,
    )
    with opener.open(value, timeout=timeout) as response:
        if response.status != 200 or response.headers.get_content_type() != "application/json":
            raise RuntimeError("invalid HTTP response")
        response_body = response.read(8 * 1024 * 1024 + 1)
    if len(response_body) > 8 * 1024 * 1024:
        raise RuntimeError("response exceeded size bound")
    return json.loads(response_body.decode("utf-8"))


def finite_number(value):
    return type(value) in {int, float} and math.isfinite(float(value))


def health(require_latency):
    value = request("/healthz")
    if not isinstance(value, dict) or set(value) != {*expected_health, "p95GenerationMs"}:
        raise RuntimeError("invalid v1 health envelope")
    for key, expected in expected_health.items():
        if value.get(key) != expected or type(value.get(key)) is not type(expected):
            raise RuntimeError(f"invalid v1 health field: {key}")
    latency = value.get("p95GenerationMs")
    if not finite_number(latency) or float(latency) < 0.0:
        raise RuntimeError("invalid v1 p95 latency")
    if require_latency and not 0.0 < float(latency) < 400.0:
        raise RuntimeError("v1 p95 latency exceeds the playback buffer")
    return value


def normalized_quaternion(value):
    return (
        isinstance(value, list)
        and len(value) == 4
        and all(finite_number(component) for component in value)
        and 0.995 <= math.sqrt(sum(float(component) ** 2 for component in value)) <= 1.005
    )


def finite_vector(value, length):
    return (
        isinstance(value, list)
        and len(value) == length
        and all(finite_number(component) for component in value)
    )


initial_health = None
deadline = time.monotonic() + 60.0
last_error = "v1 service did not answer"
while time.monotonic() < deadline:
    try:
        initial_health = health(False)
        break
    except (RuntimeError, ValueError, OSError, urllib.error.URLError) as error:
        last_error = str(error)
        time.sleep(1.0)
if initial_health is None:
    raise RuntimeError(last_error)

after_sequence = 0
previous_time = None
elapsed_ms = []
behavior_counts = {behavior: 0 for behavior in behaviors}
for index in range(30):
    behavior = behaviors[index % len(behaviors)]
    started = time.perf_counter()
    batch = request(
        "/v1/poses",
        {
            "behavior": behavior,
            "intensity": 0.65,
            "duration": 1.0,
            "afterSequence": after_sequence,
        },
        timeout=30.0,
    )
    elapsed_ms.append((time.perf_counter() - started) * 1000.0)
    if not isinstance(batch, dict) or set(batch) != {
        "version", "sequence", "fps", "coordinateSystem", "frames"
    }:
        raise RuntimeError("invalid v1 pose envelope")
    if (
        type(batch["version"]) is not int
        or batch["version"] != 1
        or type(batch["sequence"]) is not int
        or batch["sequence"] <= after_sequence
        or type(batch["fps"]) is not int
        or batch["fps"] != 20
        or batch["coordinateSystem"] != coordinate_system
        or not isinstance(batch["frames"], list)
        or len(batch["frames"]) != 8
    ):
        raise RuntimeError("v1 pose metadata is outside the sealed contract")
    first_time = float(batch["frames"][0].get("time", -1.0))
    if previous_time is not None and not math.isclose(
        first_time - previous_time, 0.05, abs_tol=1e-5
    ):
        raise RuntimeError("v1 frame time did not advance across batches")
    for frame_index, frame in enumerate(batch["frames"]):
        if not isinstance(frame, dict) or set(frame) != {"time", "root", "joints", "contacts"}:
            raise RuntimeError("invalid v1 frame envelope")
        if not finite_number(frame["time"]) or not finite_vector(frame["root"], 7):
            raise RuntimeError("invalid v1 frame root")
        if not normalized_quaternion(frame["root"][3:]):
            raise RuntimeError("invalid v1 root quaternion")
        joints = frame["joints"]
        if (
            not isinstance(joints, list)
            or len(joints) != 27
            or not all(normalized_quaternion(rotation) for rotation in joints)
            or joints[5] != identity
            or joints[6] != identity
        ):
            raise RuntimeError("invalid v1 joint payload or face ownership")
        contacts = frame["contacts"]
        if (
            not isinstance(contacts, list)
            or len(contacts) != 4
            or not all(type(contact) is float and 0.0 <= contact <= 1.0 for contact in contacts)
        ):
            raise RuntimeError("invalid v1 contact payload")
        if frame_index and not math.isclose(
            float(frame["time"]) - float(batch["frames"][frame_index - 1]["time"]),
            0.05,
            abs_tol=1e-5,
        ):
            raise RuntimeError("v1 frames are not exactly 20 FPS")
    after_sequence = batch["sequence"]
    previous_time = float(batch["frames"][-1]["time"])
    behavior_counts[behavior] += 1

final_health = health(True)
steady = sorted(elapsed_ms[1:])
p95 = steady[max(0, math.ceil(0.95 * len(steady)) - 1)]
if not 0.0 < p95 < 400.0:
    raise RuntimeError("observed v1 p95 latency exceeds the playback buffer")
print(json.dumps({
    "schemaVersion": 1,
    "status": "passed",
    "protocolVersion": 1,
    "host": "127.0.0.1",
    "port": port,
    "batches": 30,
    "frames": 240,
    "behaviorCounts": behavior_counts,
    "finalSequence": after_sequence,
    "finalFrameTime": previous_time,
    "steadyP95Ms": round(p95, 3),
    "initialHealth": initial_health,
    "finalHealth": final_health,
}, sort_keys=True, separators=(",", ":"), allow_nan=False))
PY
    ) || return 1
    (( ${#report} <= 1048576 )) || return 1
    write_record "$output" "$report"
}

capture_owned_run_container() {
    local -n destination=$1
    local expected_name=$2 expected_image=$3 expected_role=$4
    local expected_auto_remove=$5 inspect_file
    local -a owned_fields=()
    destination=''
    case "$expected_role:$expected_name:$expected_image:$expected_auto_remove" in
        "canary:$CANARY_CONTAINER:$target_image_id:false") ;;
        "target:$PRODUCTION_CONTAINER:$target_image_id:true") ;;
        "rollback:$PRODUCTION_CONTAINER:$rollback_image_id:true") ;;
        *) return 1 ;;
    esac
    [[ $expected_image =~ ^sha256:[0-9a-f]{64}$ && \
        $activation_run_id =~ ^[0-9a-f]{64}$ ]] || return 1
    inspect_file=$(mktemp "$evidence_root/.owned-launch-inspect.XXXXXX") || return 1
    if ! docker_read_bounded inspect --type container "$expected_name" >"$inspect_file"; then
        rm -f -- "$inspect_file"
        return 1
    fi
    mapfile -t owned_fields < <(
        python3 - "$expected_name" "$expected_image" "$activation_run_id" \
            "$expected_role" "$expected_auto_remove" "$RUN_LABEL_KEY" \
            "$ROLE_LABEL_KEY" "$inspect_file" <<'PY'
import json
import re
import sys

(
    expected_name,
    expected_image,
    activation_run_id,
    expected_role,
    expected_auto_remove,
    run_label_key,
    role_label_key,
    inspect_file,
) = sys.argv[1:]
with open(inspect_file, encoding="utf-8") as stream:
    records = json.load(stream)
if not isinstance(records, list) or len(records) != 1:
    raise SystemExit(1)
record = records[0]
config = record.get("Config", {})
host = record.get("HostConfig", {})
labels = config.get("Labels") or {}
container_id = record.get("Id", "")
if (
    not re.fullmatch(r"[0-9a-f]{64}", container_id)
    or record.get("Name") != f"/{expected_name}"
    or record.get("Image") != expected_image
    or config.get("Image") != expected_image
    or host.get("AutoRemove") is not (expected_auto_remove == "true")
    or not isinstance(labels, dict)
    or labels.get(run_label_key) != activation_run_id
    or labels.get(role_label_key) != expected_role
):
    raise SystemExit(1)
print(container_id)
PY
    )
    rm -f -- "$inspect_file"
    (( ${#owned_fields[@]} == 1 )) || return 1
    [[ ${owned_fields[0]} =~ ^[0-9a-f]{64}$ ]] || return 1
    destination=${owned_fields[0]}
}

reconcile_pending_launch() {
    local -n destination=$1
    local owned_id=''
    destination=''
    (( pending_launch_active == 1 )) || return 1
    capture_owned_run_container owned_id "$pending_launch_name" \
        "$pending_launch_image" "$pending_launch_role" \
        "$pending_launch_auto_remove" || return 1
    case $pending_launch_role in
        canary) canary_container_id=$owned_id ;;
        target) target_container_id=$owned_id ;;
        rollback) ;;
        *) return 1 ;;
    esac
    pending_launch_active=0
    destination=$owned_id
}

reconcile_pending_launch_bounded() {
    local destination_name=$1 attempt adopted_id=''
    printf -v "$destination_name" '%s' ''
    (( pending_launch_active == 1 )) || return 1
    for attempt in $(seq 1 30); do
        if reconcile_pending_launch adopted_id; then
            printf -v "$destination_name" '%s' "$adopted_id"
            return 0
        fi
        (( pending_launch_active == 1 )) || return 1
        sleep_isolated 1 || true
    done
    return 1
}

container_name_and_id_are_absent() {
    local expected_name=$1 expected_id=$2 rows container_id container_name extra
    [[ $expected_name == "$PRODUCTION_CONTAINER" && \
        $expected_id =~ ^[0-9a-f]{64}$ ]] || return 1
    rows=$(docker_read_bounded container ls --all --no-trunc \
        --format '{{.ID}} {{.Names}}') || return 1
    while read -r container_id container_name extra; do
        [[ -n $container_id ]] || continue
        [[ $container_id =~ ^[0-9a-f]{64}$ && \
            $container_name =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ && \
            -z $extra ]] || return 1
        [[ $container_id != "$expected_id" && \
            $container_name != "$expected_name" ]] || return 1
    done <<<"$rows"
}

clear_stably_absent_auto_remove_launch() {
    local expected_cidfile cidfile_id attempt absence_record
    (( pending_launch_active == 1 )) || return 1
    [[ $pending_launch_auto_remove == true ]] || return 1
    case "$pending_launch_role:$pending_launch_name:$pending_launch_port" in
        "target:$PRODUCTION_CONTAINER:$PRODUCTION_PORT"|\
        "rollback:$PRODUCTION_CONTAINER:$PRODUCTION_PORT") ;;
        *) return 1 ;;
    esac
    expected_cidfile="$evidence_root/${pending_launch_role}-container.cid"
    [[ $pending_launch_cidfile == "$expected_cidfile" && \
        -f $expected_cidfile && ! -L $expected_cidfile ]] || return 1
    cidfile_id=$(<"$expected_cidfile")
    [[ $cidfile_id =~ ^[0-9a-f]{64}$ ]] || return 1
    for attempt in $(seq 1 5); do
        container_name_and_id_are_absent "$pending_launch_name" "$cidfile_id" || \
            return 1
        loopback_port_is_unused "$pending_launch_port" || return 1
        (( attempt == 5 )) || sleep_isolated 1 || return 1
    done
    absence_record="$evidence_root/${pending_launch_role}-auto-remove-absence.txt"
    write_record "$absence_record" \
        'schema=1' \
        'status=verified-stably-absent' \
        "role=$pending_launch_role" \
        "container_id=$cidfile_id" \
        'lifecycle_action_from_cidfile=none' \
        'consecutive_absence_samples=5' || return 1
    pending_launch_absence_verified=1
    pending_launch_absent_id=$cidfile_id
    pending_launch_active=0
}

launch_container() {
    local -n destination=$1
    local name=$2 image=$3 port=$4 provider=$5 auto_remove=$6 role=$7
    local launch_status=0 resolved_id='' cidfile stdout_file cidfile_id=''
    local launch_models_root=''
    local -a arguments=(--detach)
    destination=''
    case "$role:$name:$image:$port:$provider:$auto_remove" in
        "canary:$CANARY_CONTAINER:$target_image_id:$CANARY_PORT:$TARGET_PROVIDER:false") ;;
        "target:$PRODUCTION_CONTAINER:$target_image_id:$PRODUCTION_PORT:$TARGET_PROVIDER:true") ;;
        "rollback:$PRODUCTION_CONTAINER:$rollback_image_id:$PRODUCTION_PORT:$ROLLBACK_PROVIDER:true") ;;
        *) return 1 ;;
    esac
    case $role in
        canary|target) launch_models_root=$models_root ;;
        rollback) launch_models_root=$rollback_models_root ;;
        *) return 1 ;;
    esac
    [[ -d $launch_models_root && ! -L $launch_models_root ]] || return 1
    cidfile="$evidence_root/$role-container.cid"
    stdout_file="$evidence_root/$role-launch.stdout"
    [[ ! -e $cidfile && ! -L $cidfile && \
        ! -e $stdout_file && ! -L $stdout_file ]] || return 1
    pending_launch_name=$name
    pending_launch_image=$image
    pending_launch_port=$port
    pending_launch_provider=$provider
    pending_launch_auto_remove=$auto_remove
    pending_launch_role=$role
    pending_launch_cidfile=$cidfile
    pending_launch_active=1
    if [[ $auto_remove == true ]]; then
        arguments+=(--rm)
    fi
    arguments+=(
        --cidfile "$cidfile"
        --name "$name"
        --label "$RUN_LABEL_KEY=$activation_run_id"
        --label "$ROLE_LABEL_KEY=$role"
        --gpus all
        --network host
        --read-only
        --cap-drop ALL
        --security-opt no-new-privileges:true
        --pids-limit 512
        --shm-size 4g
        --tmpfs /tmp:rw,noexec,nosuid,size=1g
        --user "$(id -u):$(id -g)"
        --mount "type=bind,src=$launch_models_root,dst=/models,readonly"
        "$image"
        --host 127.0.0.1 --port "$port" --provider "$provider" --models-root /models
    )
    if docker_run_bounded "${arguments[@]}" >"$stdout_file"; then
        launch_status=0
    else
        launch_status=$?
    fi
    chmod 600 "$stdout_file" || return 1
    if [[ -e $cidfile ]]; then
        [[ -f $cidfile && ! -L $cidfile ]] || return 1
        chmod 600 "$cidfile" || return 1
        cidfile_id=$(<"$cidfile")
        [[ $cidfile_id =~ ^[0-9a-f]{64}$ ]] || return 1
    fi
    if reconcile_pending_launch_bounded resolved_id; then
        [[ -z $cidfile_id || $cidfile_id == "$resolved_id" ]] || return 1
        destination=$resolved_id
        return 0
    fi
    if clear_stably_absent_auto_remove_launch; then
        (( launch_status != 0 )) && return "$launch_status"
        return 1
    fi
    (( launch_status != 0 )) && return "$launch_status"
    return 1
}

capture_container_logs() {
    local container_id=$1 destination=$2
    [[ $container_id =~ ^[0-9a-f]{64}$ && \
        $destination == "$evidence_root/"* && ! -e $destination ]] || return 1
    docker_logs_bounded "$container_id" >"$destination" 2>&1 || true
    chmod 600 "$destination"
}

cleanup_canary() {
    local current_id='' verified_id=''
    (( pending_launch_active == 0 )) || return 1
    if capture_owned_run_container verified_id "$CANARY_CONTAINER" \
        "$target_image_id" canary false; then
        if [[ -n $canary_container_id && \
            ( ! $canary_container_id =~ ^[0-9a-f]{64}$ || \
            $canary_container_id != "$verified_id" ) ]]; then
            return 1
        fi
        canary_container_id=$verified_id
        pending_launch_active=0
    else
        current_id=$(container_id_for_name "$CANARY_CONTAINER" 2>/dev/null || true)
        [[ -z $current_id && -z $canary_container_id ]] && return 0
        return 1
    fi
    capture_container_logs "$canary_container_id" "$evidence_root/canary-container.log"
    docker_stop_bounded "$canary_container_id" >/dev/null 2>&1 || true
    verified_id=''
    capture_owned_run_container verified_id "$CANARY_CONTAINER" \
        "$target_image_id" canary false || return 1
    [[ $verified_id == "$canary_container_id" ]] || return 1
    docker_remove_bounded "$canary_container_id" >/dev/null 2>&1 || return 1
    current_id=$(container_id_for_name "$CANARY_CONTAINER" 2>/dev/null || true)
    [[ -z $current_id ]]
}

restore_rollback() {
    local current_id rollback_id='' attempt owned_target_id='' restored_models_seal=''
    local -a rollback_snapshot=()
    # Do not overwrite an unresolved ownership record with a rollback launch.
    # A late daemon publication must remain fail-closed and auditable.
    (( pending_launch_active == 0 )) || return 1
    if [[ $old_container_id =~ ^[0-9a-f]{64}$ ]] && \
        docker_read_bounded inspect --type container "$old_container_id" \
            >/dev/null 2>&1; then
        current_id=$(container_id_for_name "$PRODUCTION_CONTAINER" 2>/dev/null || true)
        if [[ $current_id == "$old_container_id" ]]; then
            capture_verified_container rollback_snapshot "$old_container_id" \
                "$PRODUCTION_CONTAINER" "$current_image_reference" \
                "$rollback_image_id" "$ROLLBACK_PROVIDER" "$PRODUCTION_PORT" true \
                rollback-existing "$rollback_models_root" || return 1
            [[ ${rollback_snapshot[0]} == "${production_before[0]}" && \
                ${rollback_snapshot[1]} == "${production_before[1]}" && \
                ${rollback_snapshot[2]} == "${production_before[2]}" && \
                ${rollback_snapshot[3]} == "${production_before[3]}" && \
                ${rollback_snapshot[4]} == "${production_before[4]}" && \
                ${rollback_snapshot[5]} == "${production_before[5]}" && \
                ${rollback_snapshot[6]} == "${production_before[6]}" && \
                ${rollback_snapshot[7]} == "${production_before[7]}" ]] || return 1
            qualify_v1_rollback "$PRODUCTION_PORT" \
                "$evidence_root/rollback-existing-validation.json" || return 1
            seal_models_tree restored_models_seal "$rollback_models_root" \
                "$evidence_root/rollback-existing-models.json" || return 1
            [[ $restored_models_seal == "$rollback_models_seal" ]] || return 1
            rollback_verified=1
            return 0
        fi
    fi
    if capture_owned_run_container owned_target_id "$PRODUCTION_CONTAINER" \
        "$target_image_id" target true; then
        if [[ -n $target_container_id && \
            ( ! $target_container_id =~ ^[0-9a-f]{64}$ || \
            $target_container_id != "$owned_target_id" ) ]]; then
            return 1
        fi
        target_container_id=$owned_target_id
        pending_launch_active=0
        capture_container_logs "$target_container_id" \
            "$evidence_root/failed-target-container.log"
        docker_stop_bounded "$target_container_id" >/dev/null 2>&1 || true
    fi
    for attempt in $(seq 1 30); do
        current_id=$(container_id_for_name "$PRODUCTION_CONTAINER" 2>/dev/null || true)
        if [[ -z $current_id ]] && loopback_port_is_unused "$PRODUCTION_PORT"; then
            break
        fi
        if [[ -n $current_id ]]; then
            owned_target_id=''
            if ! capture_owned_run_container owned_target_id "$PRODUCTION_CONTAINER" \
                "$target_image_id" target true || \
                [[ $owned_target_id != "$target_container_id" ]]; then
                break
            fi
        fi
        sleep 1
    done
    current_id=$(container_id_for_name "$PRODUCTION_CONTAINER" 2>/dev/null || true)
    if [[ -n $current_id ]]; then
        owned_target_id=''
        if capture_owned_run_container owned_target_id "$PRODUCTION_CONTAINER" \
            "$target_image_id" target true && \
            [[ $owned_target_id == "$target_container_id" ]]; then
            write_record "$evidence_root/rollback-blocked.txt" \
                'reason=exact-failed-target-still-exists' \
                "observed_container_id=$owned_target_id" || true
            return 1
        fi
        write_record "$evidence_root/rollback-blocked.txt" \
            'reason=production-container-name-is-owned' \
            "observed_container_id=$current_id" || true
        return 1
    fi
    if ! loopback_port_is_unused "$PRODUCTION_PORT"; then
        write_record "$evidence_root/rollback-blocked.txt" \
            'reason=production-port-is-owned-or-could-not-be-inspected' || true
        return 1
    fi
    launch_container rollback_id "$PRODUCTION_CONTAINER" "$rollback_image_id" \
        "$PRODUCTION_PORT" "$ROLLBACK_PROVIDER" true rollback || return 1
    [[ $rollback_id =~ ^[0-9a-f]{64}$ ]] || return 1
    qualify_v1_rollback "$PRODUCTION_PORT" \
        "$evidence_root/rollback-validation.json" || return 1
    capture_verified_container rollback_snapshot "$rollback_id" "$PRODUCTION_CONTAINER" \
        "$rollback_image_id" "$rollback_image_id" "$ROLLBACK_PROVIDER" \
        "$PRODUCTION_PORT" true rollback "$rollback_models_root" rollback || return 1
    [[ ${rollback_snapshot[3]} == "${production_before[3]}" && \
        ${rollback_snapshot[5]} == "${production_before[5]}" && \
        ${rollback_snapshot[6]} == "${production_before[6]}" && \
        ${rollback_snapshot[7]} == "${production_before[7]}" ]] || return 1
    seal_models_tree restored_models_seal "$rollback_models_root" \
        "$evidence_root/rollback-restored-models.json" || return 1
    [[ $restored_models_seal == "$rollback_models_seal" ]] || return 1
    rollback_verified=1
}

on_exit() {
    local status=$? reconciled_id=''
    trap - EXIT
    trap '' HUP INT TERM
    set +e
    exit_cleanup_signals_masked=1
    exit_cleanup_started_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)
    if (( pending_launch_active == 1 )); then
        if ! reconcile_pending_launch_bounded reconciled_id >/dev/null 2>&1; then
            if ! clear_stably_absent_auto_remove_launch; then
                write_record "$evidence_root/pending-launch-unresolved.txt" \
                    'reason=daemon-publication-not-observed-within-bounded-reconciliation' \
                    "pending_launch_name=$pending_launch_name" \
                    "pending_launch_role=$pending_launch_role" || true
            fi
        fi
    fi
    if cleanup_canary; then
        cleanup_status='verified'
    else
        cleanup_status='failed'
        printf 'EMERGENCY: the exact ARDY canary could not be cleaned up; inspect %s\n' \
            "$evidence_root" >&2
        if (( status == 0 )); then
            status=1
            last_error='canary-cleanup-failed-during-exit'
        fi
    fi
    if (( status != 0 && rollback_armed == 1 && activation_complete == 0 )); then
        rollback_attempted=1
        if restore_rollback; then
            rollback_status='verified'
        else
            rollback_status='failed'
            printf 'EMERGENCY: sealed ARDY rollback could not be verified; inspect %s\n' \
                "$evidence_root" >&2
        fi
    fi
    if (( pending_launch_active == 1 )); then
        cleanup_status='failed'
        if [[ ! -e $evidence_root/pending-launch-unresolved.txt ]]; then
            write_record "$evidence_root/pending-launch-unresolved.txt" \
                'reason=daemon-publication-not-observed-within-bounded-reconciliation' \
                "pending_launch_name=$pending_launch_name" \
                "pending_launch_role=$pending_launch_role" || true
        fi
        if (( status == 0 )); then
            status=1
            last_error='pending-launch-unresolved-during-exit'
        fi
    fi
    if [[ -n $evidence_root && -d $evidence_root && \
        ! -e $evidence_root/activation-result.txt ]]; then
        write_record "$evidence_root/activation-result.txt" \
            'schema=2' \
            "completed_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
            "status=$([[ $status == 0 ]] && printf passed || printf failed)" \
            "error=$last_error" \
            "activation_complete=$activation_complete" \
            "recovery_mode=$recovery_mode" \
            "rollback_armed=$rollback_armed" \
            "rollback_attempted=$rollback_attempted" \
            "rollback_verified=$rollback_verified" \
            "rollback_status=$rollback_status" \
            "cleanup_status=$cleanup_status" \
            "exit_cleanup_signals_masked=$exit_cleanup_signals_masked" \
            "exit_cleanup_started_utc=$exit_cleanup_started_utc" \
            "activation_run_id=$activation_run_id" \
            "pending_launch_active=$pending_launch_active" \
            "pending_launch_role=${pending_launch_role:-none}" \
            "pending_launch_absence_verified=$pending_launch_absence_verified" \
            "pending_launch_absent_id=${pending_launch_absent_id:-none}" \
            "old_container_id=$old_container_id" \
            "target_container_id=$target_container_id" \
            "target_image_id=${target_image_id:-unavailable}" \
            "rollback_image_id=${rollback_image_id:-unavailable}" \
            "target_models_root=${models_root:-unavailable}" \
            "target_models_sha256=${target_models_seal:-unavailable}" \
            "rollback_models_root=${rollback_models_root:-unavailable}" \
            "rollback_models_sha256=${rollback_models_seal:-unavailable}"
    fi
    exit "$status"
}

handle_signal() {
    trap '' HUP INT TERM
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
declare -a production_before=() production_reverified=() production_after=()
old_container_id=$(container_id_for_name "$PRODUCTION_CONTAINER" 2>/dev/null || true)
if [[ -z $old_container_id ]]; then
    loopback_port_is_unused "$PRODUCTION_PORT" || \
        fail 'production ARDY is absent but its fixed loopback port is unexpectedly owned'
    fail 'production ARDY 0.2.0 is absent; no exact live rollback can be captured'
fi
current_image_reference=$(docker_read_bounded inspect --type container \
    --format '{{.Config.Image}}' "$old_container_id") || \
    fail 'could not identify the production ARDY image reference'
current_runtime_image_id=$(docker_read_bounded inspect --type container \
    --format '{{.Image}}' "$old_container_id") || \
    fail 'could not identify the production ARDY image ID'
[[ $current_runtime_image_id =~ ^sha256:[0-9a-f]{64}$ ]] || \
    fail 'the production ARDY image ID is malformed'
if [[ $current_runtime_image_id == "$target_image_id" ]]; then
    [[ $current_image_reference == "$TARGET_IMAGE" || \
        $current_image_reference == "$target_image_id" ]] || \
        fail 'the real production container uses an unexpected image reference'
    capture_verified_container production_before "$old_container_id" \
        "$PRODUCTION_CONTAINER" "$current_image_reference" "$target_image_id" \
        "$TARGET_PROVIDER" \
        "$PRODUCTION_PORT" true production-already-active "$models_root" || \
        fail 'the existing real production container failed its identity contract'
    "$validator" --port "$PRODUCTION_PORT" --batches 30 --startup-timeout 180 \
        >"$evidence_root/production-already-active-validation.json" \
        2>"$evidence_root/production-already-active-validation.stderr" || \
        fail 'the existing real production provider failed qualification'
    chmod 600 "$evidence_root"/production-already-active-validation.*
    seal_models_tree target_models_seal "$models_root" \
        "$evidence_root/production-already-active-models.json" || \
        fail 'the active v2 model tree could not be sealed'
    activation_complete=1
    last_error='none-already-active'
    printf 'ARDY was already real and passed qualification; private evidence: %s\n' \
        "$evidence_root"
    exit 0
fi
[[ $current_runtime_image_id == "$rollback_image_id" ]] || \
    fail 'production uses neither the sealed 0.2.0 rollback nor 0.3.0 target image'
[[ $current_image_reference == "$ROLLBACK_IMAGE" || \
    $current_image_reference == "$rollback_image_id" ]] || \
    fail 'the v1 production container uses an unexpected image reference'
discover_readonly_models_root rollback_models_root "$old_container_id" \
    production-before || \
    fail 'the current v1 production models mount is not exact and read-only'
[[ $models_root != "$rollback_models_root" ]] || \
    fail 'the v2 candidate models must be isolated from the preserved v1 rollback models'
case "$models_root/" in
    "$rollback_models_root/"*) \
        fail 'the v2 candidate models cannot be nested below the v1 rollback models' ;;
esac
case "$rollback_models_root/" in
    "$models_root/"*) \
        fail 'the v1 rollback models cannot be nested below the v2 candidate models' ;;
esac
capture_verified_container production_before "$old_container_id" \
    "$PRODUCTION_CONTAINER" "$current_image_reference" "$rollback_image_id" \
    "$ROLLBACK_PROVIDER" "$PRODUCTION_PORT" true production-before \
    "$rollback_models_root" || \
    fail 'the current v1 rollback failed its identity, isolation, and mount contract'
qualify_v1_rollback "$PRODUCTION_PORT" \
    "$evidence_root/production-before-v1-validation.json" || \
    fail 'the current real v1 rollback failed strict 30-batch qualification'
seal_models_tree rollback_models_seal "$rollback_models_root" \
    "$evidence_root/rollback-models-before.json" || \
    fail 'the preserved v1 rollback model tree could not be sealed'
seal_models_tree target_models_seal "$models_root" \
    "$evidence_root/target-models-before.json" || \
    fail 'the v2 candidate model tree could not be sealed'

write_record "$evidence_root/activation-before.txt" \
    'schema=1' \
    "started_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    "target_models_root=$models_root" \
    "target_models_sha256=$target_models_seal" \
    "rollback_models_root=$rollback_models_root" \
    "rollback_models_sha256=$rollback_models_seal" \
    "old_container_id=$old_container_id" \
    "recovery_mode=$recovery_mode" \
    "activation_run_id=$activation_run_id" \
    "target_image=$TARGET_IMAGE" \
    "target_image_id=$target_image_id" \
    "rollback_image=$ROLLBACK_IMAGE" \
    "rollback_image_id=$rollback_image_id" || \
    fail 'could not publish the activation preflight record'

launch_container canary_container_id "$CANARY_CONTAINER" "$target_image_id" \
    "$CANARY_PORT" "$TARGET_PROVIDER" false canary || \
    fail 'could not launch the retained real canary'
[[ $canary_container_id =~ ^[0-9a-f]{64}$ ]] || fail 'canary returned an invalid container ID'
"$validator" --port "$CANARY_PORT" --batches 30 --startup-timeout 180 \
    >"$evidence_root/canary-validation.json" \
    2>"$evidence_root/canary-validation.stderr" || \
    fail 'the retained real canary failed strict qualification'
chmod 600 "$evidence_root"/canary-validation.*
declare -a canary_snapshot=()
capture_verified_container canary_snapshot "$canary_container_id" "$CANARY_CONTAINER" \
    "$target_image_id" "$target_image_id" "$TARGET_PROVIDER" "$CANARY_PORT" false \
    canary "$models_root" canary || \
    fail 'the qualified canary failed its identity and isolation contract'
cleanup_canary || fail 'the exact retained canary could not be removed safely'
canary_container_id=''

capture_verified_container production_reverified "$old_container_id" \
    "$PRODUCTION_CONTAINER" "$current_image_reference" "$rollback_image_id" \
    "$ROLLBACK_PROVIDER" "$PRODUCTION_PORT" true production-reverified \
    "$rollback_models_root" || \
    fail 'production changed while the isolated v2 canary was qualifying'
[[ ${production_before[0]} == "${production_reverified[0]}" && \
    ${production_before[1]} == "${production_reverified[1]}" && \
    ${production_before[2]} == "${production_reverified[2]}" && \
    ${production_before[3]} == "${production_reverified[3]}" && \
    ${production_before[4]} == "${production_reverified[4]}" && \
    ${production_before[5]} == "${production_reverified[5]}" && \
    ${production_before[6]} == "${production_reverified[6]}" && \
    ${production_before[7]} == "${production_reverified[7]}" ]] || \
    fail 'production identity changed while the isolated v2 canary was qualifying'
qualify_v1_rollback "$PRODUCTION_PORT" \
    "$evidence_root/production-reverified-v1-validation.json" || \
    fail 'the real v1 rollback changed during v2 canary qualification'
rollback_models_reverified=''
target_models_reverified=''
seal_models_tree rollback_models_reverified "$rollback_models_root" \
    "$evidence_root/rollback-models-reverified.json" || \
    fail 'the v1 rollback model tree could not be reverified'
seal_models_tree target_models_reverified "$models_root" \
    "$evidence_root/target-models-reverified.json" || \
    fail 'the v2 target model tree could not be reverified'
[[ $rollback_models_reverified == "$rollback_models_seal" ]] || \
    fail 'the preserved v1 rollback models changed during canary qualification'
[[ $target_models_reverified == "$target_models_seal" ]] || \
    fail 'the sealed v2 target models changed during canary qualification'
[[ $(image_id "$rollback_image_id") == "$rollback_image_id" ]] || \
    fail 'the immutable v1 rollback image disappeared before cutover'
[[ $(image_id "$target_image_id") == "$target_image_id" ]] || \
    fail 'the immutable v2 target image disappeared before cutover'

rollback_armed=1
docker_stop_bounded "$old_container_id" >"$evidence_root/production-stop.txt" || \
    fail 'could not stop the exact recorded real v1 rollback container'
chmod 600 "$evidence_root/production-stop.txt"
for _ in $(seq 1 30); do
    if ! docker_read_bounded inspect --type container "$old_container_id" \
        >/dev/null 2>&1 && \
        ! container_id_for_name "$PRODUCTION_CONTAINER" >/dev/null 2>&1; then
        break
    fi
    sleep 1
done
! docker_read_bounded inspect --type container "$old_container_id" \
    >/dev/null 2>&1 || \
    fail 'the exact real v1 rollback container did not disappear after stop'
! container_id_for_name "$PRODUCTION_CONTAINER" >/dev/null 2>&1 || \
    fail 'the production container name was unexpectedly reclaimed'
loopback_port_is_unused "$PRODUCTION_PORT" || \
    fail 'the production loopback port was unexpectedly reclaimed'

launch_container target_container_id "$PRODUCTION_CONTAINER" "$target_image_id" \
    "$PRODUCTION_PORT" "$TARGET_PROVIDER" true target || \
    fail 'could not launch the real provider'
[[ $target_container_id =~ ^[0-9a-f]{64}$ ]] || fail 'target returned an invalid container ID'
"$validator" --port "$PRODUCTION_PORT" --batches 30 --startup-timeout 180 \
    >"$evidence_root/production-validation.json" \
    2>"$evidence_root/production-validation.stderr" || \
    fail 'the real production provider failed strict qualification'
chmod 600 "$evidence_root"/production-validation.*
capture_verified_container production_after "$target_container_id" "$PRODUCTION_CONTAINER" \
    "$target_image_id" "$target_image_id" "$TARGET_PROVIDER" "$PRODUCTION_PORT" true \
    production-after "$models_root" target || \
    fail 'the real provider failed its final identity and isolation contract'
target_models_after=''
seal_models_tree target_models_after "$models_root" \
    "$evidence_root/target-models-after.json" || \
    fail 'the active v2 target model tree could not be sealed after qualification'
[[ $target_models_after == "$target_models_seal" ]] || \
    fail 'the v2 target models changed during production qualification'

last_error='none'
write_record "$evidence_root/activation-after.txt" \
    'schema=1' \
    "completed_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    'status=passed' \
    "old_container_id=$old_container_id" \
    "recovery_mode=$recovery_mode" \
    "activation_run_id=$activation_run_id" \
    "target_container_id=$target_container_id" \
    "target_image_id=$target_image_id" \
    'provider=ardy' \
    'protocol_version=2' \
    'checkpoint=ARDY-Core-RP-20FPS-Horizon8' \
    'embedding_count=9' || fail 'could not publish the activation success record'
activation_complete=1
printf 'Guarded ARDY v1-to-v2 migration passed; private evidence: %s\n' \
    "$evidence_root"
