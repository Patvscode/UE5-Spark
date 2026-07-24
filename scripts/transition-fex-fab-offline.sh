#!/usr/bin/env bash
set -euo pipefail

usage() {
    printf 'Usage: %s /path/to/cooker-workspace /path/to/isolated/UnrealEngine /path/to/FayFabAcquisition.uproject /path/to/private-acquisition-baseline.json\n' \
        "${0##*/}" >&2
    printf 'Backs up the acquired project and seals its transition to offline review.\n' >&2
}

fail() {
    printf 'error: %s\n' "$*" >&2
    exit 1
}

if (( $# != 4 )); then
    usage
    exit 64
fi
if [[ $(uname -s) != Linux || $(uname -m) != aarch64 ]]; then
    fail "the Fab offline transition requires Linux/aarch64, not $(uname -s)/$(uname -m)"
fi
if (( ${EUID:-$(id -u)} == 0 )); then
    fail 'run the Fab offline transition as the normal workspace owner, not root'
fi
for command_name in basename chmod cmp cp dirname grep id install mkdir mktemp mv \
    ps rm sync systemctl; do
    command -v "$command_name" >/dev/null 2>&1 || \
        fail "required command is missing: $command_name"
done
host_python=/usr/bin/python3
[[ -x $host_python ]] || fail "fixed host Python is unavailable: $host_python"

workspace=$(cd "$1" && pwd -P)
engine_root=$(cd "$2" && pwd -P)
project_input=$3
acquisition_manifest_input=$4
[[ -f $project_input && ! -L $project_input ]] || fail "project does not exist: $project_input"
[[ -f $acquisition_manifest_input && ! -L $acquisition_manifest_input ]] || \
    fail 'private acquisition baseline is missing'
project_dir=$(cd "$(dirname "$project_input")" && pwd -P)
project="$project_dir/$(basename "$project_input")"
acquisition_manifest=$(cd "$(dirname "$acquisition_manifest_input")" && pwd -P)/$(basename "$acquisition_manifest_input")
case "$engine_root/" in
    "$workspace"/*) ;;
    *) fail 'the isolated Engine must remain below the cooker workspace' ;;
esac
expected_project="$workspace/fab-acquisition-staging/FayFabAcquisition/FayFabAcquisition.uproject"
[[ $project == "$expected_project" ]] || \
    fail "the Fab project must use the fixed acquisition path: $expected_project"

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
acquisition_template="$script_dir/../staging/fab-acquisition-template/FayFabAcquisition.uproject"
offline_template="$script_dir/../staging/fab-offline-template/FayFabAcquisition.uproject"
non_content_tool="$script_dir/fab-staging-manifest.py"
content_tool="$script_dir/fab-content-manifest.py"
inventory_script="$script_dir/inspect-fab-casual-girl.py"
transition_verifier="$script_dir/verify-fab-offline-transition.py"
phase_lock_tool="$script_dir/fab-phase-lock.sh"
private_logs="$workspace/logs-private/fab-acquisition"
inventory_receipt="$private_logs/casual-girl-inventory.json"
content_manifest="$private_logs/casual-girl-content-before-migration.json"
offline_manifest="$private_logs/offline-before-migration.json"
transition_receipt="$private_logs/offline-transition.json"
expected_acquisition_manifest="$private_logs/before-import.json"
backup_root="$workspace/backups-private"
backup_parent="$backup_root/fab-casual-girl"
backup_generation="$backup_parent/acquisition-v1"
backup="$backup_generation/FayFabAcquisition"

[[ $acquisition_manifest == "$expected_acquisition_manifest" ]] || \
    fail "the acquisition baseline must use the fixed path: $expected_acquisition_manifest"
for required in "$acquisition_template" "$offline_template" "$non_content_tool" \
    "$content_tool" "$inventory_script" "$transition_verifier" "$phase_lock_tool" \
    "$inventory_receipt" "$content_manifest"; do
    [[ -f $required && ! -L $required ]] || fail "required transition input is missing: $required"
done

# shellcheck source=./fab-phase-lock.sh
source "$phase_lock_tool"
fab_phase_lock_acquire "$workspace" || exit 1

temporary_backup_generation=
switched=0

atomic_replace_descriptor() {
    "$host_python" - "$1" "$2" <<'PY'
import os
from pathlib import Path
import stat
import sys
import tempfile

source = Path(sys.argv[1])
target = Path(sys.argv[2])
source_metadata = source.lstat()
if stat.S_ISLNK(source_metadata.st_mode) or not stat.S_ISREG(source_metadata.st_mode):
    raise SystemExit("error: descriptor template must be one real regular file")
parent = target.parent
parent_metadata = parent.lstat()
if stat.S_ISLNK(parent_metadata.st_mode) or not stat.S_ISDIR(parent_metadata.st_mode):
    raise SystemExit("error: descriptor parent must be one real directory")
if target.is_symlink():
    raise SystemExit("error: descriptor target must not be a symlink")
payload = source.read_bytes()
descriptor, name = tempfile.mkstemp(prefix=f".{target.name}.", dir=parent)
temporary = Path(name)
try:
    os.fchmod(descriptor, 0o644)
    with os.fdopen(descriptor, "wb") as stream:
        descriptor = -1
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, target)
    temporary = None
    directory = os.open(parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    if target.read_bytes() != payload:
        raise SystemExit("error: atomic descriptor verification failed")
finally:
    if descriptor >= 0:
        os.close(descriptor)
    if temporary is not None:
        temporary.unlink(missing_ok=True)
PY
}

remove_transition_evidence() {
    "$host_python" - "$offline_manifest" "$transition_receipt" <<'PY'
import os
from pathlib import Path
import stat
import sys

paths = [Path(value) for value in sys.argv[1:]]
parent = paths[0].parent
for path in paths:
    if path.parent != parent:
        raise SystemExit("error: transition evidence paths do not share their fixed parent")
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        continue
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise SystemExit(f"error: refusing to remove unexpected transition evidence: {path}")
    path.unlink()
directory = os.open(parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
try:
    os.fsync(directory)
finally:
    os.close(directory)
PY
}

fsync_directory() {
    "$host_python" - "$1" <<'PY'
import os
from pathlib import Path
import sys

path = Path(sys.argv[1])
descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
try:
    os.fsync(descriptor)
finally:
    os.close(descriptor)
PY
}

validate_owned_tree() {
    "$host_python" - "$1" "$(id -u)" <<'PY'
import os
from pathlib import Path
import stat
import sys

root = Path(sys.argv[1])
expected_uid = int(sys.argv[2])
metadata = root.lstat()
if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
    raise SystemExit("error: private recovery generation must be one real directory")
if metadata.st_uid != expected_uid:
    raise SystemExit("error: private recovery generation is not user-owned")
entries = 0
for directory, directory_names, file_names in os.walk(root, followlinks=False):
    base = Path(directory)
    for name in tuple(directory_names) + tuple(file_names):
        child = base / name
        child_metadata = child.lstat()
        if stat.S_ISLNK(child_metadata.st_mode):
            raise SystemExit(f"error: private recovery generation contains a symlink: {child}")
        if child_metadata.st_uid != expected_uid:
            raise SystemExit(f"error: private recovery path is not user-owned: {child}")
    entries += len(directory_names) + len(file_names)
    if entries > 1_000_000:
        raise SystemExit("error: private recovery generation contains too many entries")
PY
}

recover_descriptor_temps() {
    "$host_python" - "$transition_verifier" "$workspace" "$engine_root" \
        "$project" "$acquisition_manifest" <<'PY'
import importlib.util
from pathlib import Path
import sys

verifier_path = Path(sys.argv[1])
spec = importlib.util.spec_from_file_location("_fab_descriptor_temp_recovery", verifier_path)
if spec is None or spec.loader is None:
    raise SystemExit("error: could not load descriptor-temp recovery verifier")
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
layout = module.resolve_layout(*[Path(value) for value in sys.argv[2:6]])
removed = module.recover_descriptor_temps(layout)
if removed:
    print(f"Recovered {removed} interrupted descriptor temporary file(s).")
PY
}

verify_recovery_copy() {
    validate_owned_tree "$backup_generation"
    [[ -f $backup/FayFabAcquisition.uproject && ! -L $backup/FayFabAcquisition.uproject ]] || \
        fail 'the fixed acquisition recovery descriptor is missing'
    cmp -s "$acquisition_template" "$backup/FayFabAcquisition.uproject" || \
        fail 'the private recovery copy has an unexpected descriptor'
    "$host_python" "$non_content_tool" verify "$backup" "$acquisition_manifest"
    "$host_python" "$content_tool" verify "$backup" "$content_manifest"
}

cleanup() {
    local status=$?
    local rollback_failed=0
    trap - EXIT
    # A second signal must not interrupt the fsynced rollback once cleanup owns
    # the descriptor. SIG_IGN is inherited by the Python verification helpers.
    trap '' HUP INT TERM
    set +e
    if (( status != 0 && switched == 1 )); then
        if ! atomic_replace_descriptor "$acquisition_template" "$project"; then
            printf 'error: atomic acquisition-descriptor rollback failed\n' >&2
            rollback_failed=1
        fi
        if ! remove_transition_evidence; then
            printf 'error: transition-evidence rollback failed\n' >&2
            rollback_failed=1
        fi
        if ! "$host_python" "$non_content_tool" verify "$project_dir" "$acquisition_manifest"; then
            printf 'error: acquisition non-content rollback verification failed\n' >&2
            rollback_failed=1
        fi
        if ! "$host_python" "$content_tool" verify "$project_dir" "$content_manifest"; then
            printf 'error: Content rollback verification failed\n' >&2
            rollback_failed=1
        fi
    fi
    if [[ -n ${temporary_backup_generation:-} ]]; then
        case "$temporary_backup_generation" in
            "$backup_parent"/.acquisition-v1.*)
                rm -rf -- "$temporary_backup_generation"
                ;;
            *)
                printf 'error: refusing to remove an unexpected temporary recovery path\n' >&2
                rollback_failed=1
                ;;
        esac
    fi
    if (( rollback_failed == 1 && status == 0 )); then
        status=1
    fi
    exit "$status"
}

# Install all signal handling immediately after taking the common phase lock.
# `switched` is set before the atomic rename so a signal can never strand the
# offline descriptor without an attempted verified rollback.
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

systemctl --user is-active ue5-spark-avatar-live.service >/dev/null || \
    fail 'the live avatar service is not active; refusing to hide a pre-existing failure'
if ps -u "$(id -u)" -o args= | grep -F "$engine_root/Engine/Binaries/Linux/UnrealEditor" \
    | grep -F "$project" | grep -v grep >/dev/null; then
    fail 'the Fab project is open in Unreal; close it before transitioning phases'
fi
recover_descriptor_temps

verifier_args=(
    --workspace "$workspace"
    --engine "$engine_root"
    --project "$project"
    --acquisition-manifest "$acquisition_manifest"
)

if cmp -s "$offline_template" "$project"; then
    if [[ -f $transition_receipt && ! -L $transition_receipt ]]; then
        "$host_python" "$transition_verifier" "${verifier_args[@]}"
        systemctl --user is-active ue5-spark-avatar-live.service >/dev/null || \
            fail 'the live avatar service changed state while verifying the offline transition'
        printf 'Fab project is already sealed in offline review mode.\n'
        exit 0
    fi
    if [[ ! -e $transition_receipt && ! -L $transition_receipt ]]; then
        # The descriptor swap is atomic but power loss/SIGKILL can occur before
        # the manifest and receipt are committed. Recover only this unambiguous
        # no-receipt state, and only from a fully verified acquisition snapshot.
        verify_recovery_copy
        "$host_python" "$content_tool" verify "$project_dir" "$content_manifest"
        remove_transition_evidence
        atomic_replace_descriptor "$acquisition_template" "$project"
        "$host_python" "$non_content_tool" verify "$project_dir" "$acquisition_manifest"
        "$host_python" "$content_tool" verify "$project_dir" "$content_manifest"
        systemctl --user is-active ue5-spark-avatar-live.service >/dev/null || \
            fail 'the live avatar service changed state during interrupted-transition recovery'
        printf 'Recovered an interrupted Fab transition to the sealed acquisition phase.\n' >&2
        printf 'Run the transition command again to enter offline review mode.\n' >&2
        exit 75
    fi
    fail 'the offline descriptor has unsafe or ambiguous transition evidence'
fi

cmp -s "$acquisition_template" "$project" || \
    fail 'the project descriptor matches neither reviewed phase'
[[ ! -e $offline_manifest && ! -L $offline_manifest ]] || \
    fail 'offline non-content evidence already exists while the project is in acquisition mode'
[[ ! -e $transition_receipt && ! -L $transition_receipt ]] || \
    fail 'transition evidence already exists while the project is in acquisition mode'
"$host_python" "$transition_verifier" "${verifier_args[@]}" --review-only

umask 077
if [[ -e $backup_root || -L $backup_root ]]; then
    [[ -d $backup_root && ! -L $backup_root && -O $backup_root ]] || \
        fail "shared recovery root must be one user-owned real directory: $backup_root"
else
    install -d -m 0700 "$backup_root"
fi
for private_directory in "$backup_parent"; do
    if [[ -e $private_directory || -L $private_directory ]]; then
        [[ -d $private_directory && ! -L $private_directory && -O $private_directory ]] || \
            fail "private recovery path must be one user-owned real directory: $private_directory"
    else
        install -d -m 0700 "$private_directory"
    fi
    chmod 0700 "$private_directory"
done

if [[ -e $backup_generation || -L $backup_generation ]]; then
    verify_recovery_copy
else
    temporary_backup_generation=$(mktemp -d "$backup_parent/.acquisition-v1.XXXXXX")
    temporary_project="$temporary_backup_generation/FayFabAcquisition"
    mkdir -m 0700 "$temporary_project"
    cp -a --reflink=auto "$project_dir/." "$temporary_project/"
    validate_owned_tree "$temporary_backup_generation"
    cmp -s "$acquisition_template" "$temporary_project/FayFabAcquisition.uproject" || \
        fail 'the temporary acquisition recovery descriptor is invalid'
    "$host_python" "$non_content_tool" verify "$temporary_project" "$acquisition_manifest"
    "$host_python" "$content_tool" verify "$temporary_project" "$content_manifest"
    # Persist the copied files themselves before publishing the fixed recovery
    # generation and before making the offline descriptor visible.
    sync -f "$temporary_project"
    mv "$temporary_backup_generation" "$backup_generation"
    temporary_backup_generation=
    fsync_directory "$backup_parent"
    verify_recovery_copy
fi

# Reusable snapshots are revalidated above; flush their backing filesystem
# before the atomic phase switch so rollback data cannot lag the descriptor.
sync -f "$backup_generation"

# Mark the rollback obligation before entering the atomic descriptor helper.
switched=1
atomic_replace_descriptor "$offline_template" "$project"
"$host_python" "$non_content_tool" create "$project_dir" "$offline_manifest"

"$host_python" - "$transition_verifier" "$workspace" "$engine_root" "$project" \
    "$acquisition_manifest" "$transition_receipt" <<'PY'
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys
import tempfile

verifier_path = Path(sys.argv[1])
spec = importlib.util.spec_from_file_location("_fab_offline_transition_verifier", verifier_path)
if spec is None or spec.loader is None:
    raise SystemExit("error: could not load the offline-transition verifier")
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
layout = module.resolve_layout(*[Path(value) for value in sys.argv[2:6]])
output = Path(sys.argv[6])
if output != layout.transition_receipt:
    raise SystemExit("error: transition receipt output is not the fixed private path")
if output.exists() or output.is_symlink():
    raise SystemExit("error: transition receipt already exists")
payload = module.expected_transition_payload(layout)
encoded = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
descriptor, name = tempfile.mkstemp(prefix=f".{output.name}.", dir=output.parent)
temporary = Path(name)
try:
    os.fchmod(descriptor, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        descriptor = -1
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, output)
    temporary = None
    directory = os.open(output.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    metadata = output.lstat()
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or output.read_bytes() != encoded
    ):
        raise SystemExit("error: atomic transition-receipt verification failed")
finally:
    if descriptor >= 0:
        os.close(descriptor)
    if temporary is not None:
        temporary.unlink(missing_ok=True)
PY

# The same strict verifier is authoritative for a fresh transition and every
# later idempotent invocation.
"$host_python" "$transition_verifier" "${verifier_args[@]}"
systemctl --user is-active ue5-spark-avatar-live.service >/dev/null || \
    fail 'the live avatar service changed state during the offline transition'
switched=0
printf 'Fab acquisition project transitioned to sealed offline review mode.\n'
printf 'Private recovery copy: %s\n' "$backup"
printf 'Private transition receipt: %s\n' "$transition_receipt"
