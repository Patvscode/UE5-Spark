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
for command_name in chmod cmp cp dirname flock grep id install mkdir mktemp mv ps \
    python3 rm systemctl; do
    command -v "$command_name" >/dev/null 2>&1 || \
        fail "required command is missing: $command_name"
done

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
case "$project_dir/" in
    "$workspace"/fab-acquisition-staging/FayFabAcquisition/) ;;
    *) fail 'the Fab project must be the dedicated acquisition-staging project' ;;
esac
case "$acquisition_manifest" in
    "$workspace"/logs-private/fab-acquisition/*) ;;
    *) fail 'the acquisition baseline must remain in the private Fab log directory' ;;
esac
[[ ${project##*/} == FayFabAcquisition.uproject ]] || \
    fail 'the reviewed project descriptor name is unexpected'

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
acquisition_template="$script_dir/../staging/fab-acquisition-template/FayFabAcquisition.uproject"
offline_template="$script_dir/../staging/fab-offline-template/FayFabAcquisition.uproject"
non_content_tool="$script_dir/fab-staging-manifest.py"
content_tool="$script_dir/fab-content-manifest.py"
inventory_script="$script_dir/inspect-fab-casual-girl.py"
private_logs="$workspace/logs-private/fab-acquisition"
inventory_receipt="$private_logs/casual-girl-inventory.json"
content_manifest="$private_logs/casual-girl-content-before-migration.json"
offline_manifest="$private_logs/offline-before-migration.json"
transition_receipt="$private_logs/offline-transition.json"
backup_parent="$workspace/backups-private/fab-casual-girl"
backup="$backup_parent/acquisition-v1"

for required in "$acquisition_template" "$offline_template" "$non_content_tool" \
    "$content_tool" "$inventory_script" "$inventory_receipt"; do
    [[ -f $required && ! -L $required ]] || fail "required transition input is missing: $required"
done
systemctl --user is-active ue5-spark-avatar-live.service >/dev/null || \
    fail 'the live avatar service is not active; refusing to hide a pre-existing failure'
if ps -u "$(id -u)" -o args= | grep -F "$engine_root/Engine/Binaries/Linux/UnrealEditor" \
    | grep -F "$project" | grep -v grep >/dev/null; then
    fail 'the Fab project is open in Unreal; close it before transitioning phases'
fi

lock_parent="/run/user/$(id -u)"
[[ -d $lock_parent && ! -L $lock_parent ]] || fail 'the private runtime directory is unavailable'
lock="$lock_parent/ue5-spark-fab-phase.lock"
exec 9>>"$lock"
chmod 0600 "$lock"
flock -n 9 || fail 'another Fab phase operation is active'

if cmp -s "$offline_template" "$project"; then
    [[ -f $offline_manifest && ! -L $offline_manifest ]] || \
        fail 'the project is offline but its private non-content seal is missing'
    [[ -f $content_manifest && ! -L $content_manifest ]] || \
        fail 'the project is offline but its private Content seal is missing'
    [[ -f $transition_receipt && ! -L $transition_receipt ]] || \
        fail 'the project is offline but its transition receipt is missing'
    python3 "$non_content_tool" verify "$project_dir" "$offline_manifest"
    python3 "$content_tool" verify "$project_dir" "$content_manifest"
    printf 'Fab project is already sealed in offline review mode.\n'
    exit 0
fi

cmp -s "$acquisition_template" "$project" || \
    fail 'the project descriptor matches neither reviewed phase'
python3 "$non_content_tool" verify "$project_dir" "$acquisition_manifest"
python3 - "$inventory_receipt" "$inventory_script" <<'PY'
from hashlib import sha256
import json
from pathlib import Path
import sys

receipt_path = Path(sys.argv[1])
script_path = Path(sys.argv[2])
value = json.loads(receipt_path.read_text(encoding="utf-8"))
expected = {
    "MESHES_ASSET_COUNT": "19",
    "MAT_ASSET_COUNT": "31",
    "TEX_ASSET_COUNT": "97",
    "EXPECTED_PRODUCT_ASSETS": "OK",
    "ARKIT_EXPECTED_COUNT": "52",
    "ARKIT_BODY_FOUND_COUNT": "52",
    "ARKIT_COMPLETE_FOUND_COUNT": "52",
    "ARKIT_BODY_MISSING": "none",
    "ARKIT_COMPLETE_MISSING": "none",
    "EPIC_BODY_BONE_NAMES_EXPECTED": "21",
    "EPIC_BODY_BONE_NAMES_FOUND": "21",
    "EPIC_BODY_BONE_NAMES_MISSING": "none",
    "FULLY_UNCLOTHED": "disabled",
    "NOAI_BOUNDARY": "deterministic_retarget_only",
    "COMPLETE": "OK",
}
script_hash = sha256(script_path.read_bytes()).hexdigest()
if (
    not isinstance(value, dict)
    or value.get("schema") != 1
    or value.get("status") != "passed"
    or value.get("inventoryScriptSha256") != script_hash
    or value.get("markers") != expected
):
    raise SystemExit("error: the private Casual Girl inventory receipt is stale or invalid")
PY

if [[ -e $content_manifest || -L $content_manifest ]]; then
    python3 "$content_tool" verify "$project_dir" "$content_manifest"
else
    python3 "$content_tool" create "$project_dir" "$content_manifest"
fi

mkdir -p "$backup_parent"
chmod 0700 "$workspace/backups-private" "$backup_parent"
[[ ! -e $backup && ! -L $backup ]] || fail 'the fixed acquisition recovery copy already exists'
temporary_backup=$(mktemp -d "$backup_parent/.acquisition-v1.XXXXXX")
temporary_descriptor=
switched=0
cleanup() {
    local status=$?
    trap - EXIT HUP INT TERM
    if (( status != 0 )); then
        if (( switched == 1 )); then
            install -m 0644 "$acquisition_template" "$project" || true
            rm -f -- "$offline_manifest" "$transition_receipt"
        fi
        if [[ -n ${temporary_backup:-} && -d $temporary_backup ]]; then
            rm -rf -- "$temporary_backup"
        fi
        if [[ -n ${temporary_descriptor:-} ]]; then
            rm -f -- "$temporary_descriptor"
        fi
    fi
    exit "$status"
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

cp -a --reflink=auto "$project_dir/." "$temporary_backup/"
cmp -s "$acquisition_template" "$temporary_backup/FayFabAcquisition.uproject" || \
    fail 'the private recovery copy has an unexpected descriptor'
python3 "$content_tool" verify "$temporary_backup" "$content_manifest"
mv "$temporary_backup" "$backup"
temporary_backup=

temporary_descriptor=$(mktemp "$project_dir/.FayFabAcquisition.XXXXXX.uproject")
install -m 0644 "$offline_template" "$temporary_descriptor"
mv -f "$temporary_descriptor" "$project"
temporary_descriptor=
switched=1
python3 "$non_content_tool" create "$project_dir" "$offline_manifest"

python3 - "$transition_receipt" "$acquisition_template" "$offline_template" \
    "$acquisition_manifest" "$offline_manifest" "$content_manifest" "$backup" <<'PY'
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
import tempfile

output = Path(sys.argv[1])
paths = [Path(value) for value in sys.argv[2:7]]
backup = Path(sys.argv[7])
payload = {
    "schema": 1,
    "status": "passed",
    "acquisitionDescriptorSha256": sha256(paths[0].read_bytes()).hexdigest(),
    "offlineDescriptorSha256": sha256(paths[1].read_bytes()).hexdigest(),
    "acquisitionManifestSha256": sha256(paths[2].read_bytes()).hexdigest(),
    "offlineManifestSha256": sha256(paths[3].read_bytes()).hexdigest(),
    "contentManifestSha256": sha256(paths[4].read_bytes()).hexdigest(),
    "recoveryCopy": str(backup),
}
descriptor, name = tempfile.mkstemp(prefix=f".{output.name}.", dir=output.parent)
try:
    os.fchmod(descriptor, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        descriptor = -1
        json.dump(payload, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(name, output)
finally:
    if descriptor >= 0:
        os.close(descriptor)
    Path(name).unlink(missing_ok=True)
PY

python3 "$non_content_tool" verify "$project_dir" "$offline_manifest"
python3 "$content_tool" verify "$project_dir" "$content_manifest"
systemctl --user is-active ue5-spark-avatar-live.service >/dev/null || \
    fail 'the live avatar service changed state during the offline transition'
switched=0
printf 'Fab acquisition project transitioned to sealed offline review mode.\n'
printf 'Private recovery copy: %s\n' "$backup"
printf 'Private transition receipt: %s\n' "$transition_receipt"
