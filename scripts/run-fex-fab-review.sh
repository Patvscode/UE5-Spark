#!/usr/bin/env bash
set -euo pipefail

usage() {
    printf 'Usage: %s [--check] /path/to/cooker-workspace /path/to/isolated/UnrealEngine /path/to/FayFabAcquisition.uproject /path/to/private-baseline.json\n' \
        "${0##*/}" >&2
    printf 'Runs the fixed read-only Casual Girl inventory through rootless FEX.\n' >&2
}

fail() {
    printf 'error: %s\n' "$*" >&2
    exit 1
}

check_only=0
if [[ ${1:-} == --check ]]; then
    check_only=1
    shift
fi
if (( $# != 4 )); then
    usage
    exit 64
fi
if [[ $(uname -s) != Linux || $(uname -m) != aarch64 ]]; then
    fail "the Fab review requires Linux/aarch64, not $(uname -s)/$(uname -m)"
fi
if (( ${EUID:-$(id -u)} == 0 )); then
    fail 'run the Fab review as the normal workspace owner, not root'
fi
for command_name in cmp file grep id mkdir mktemp nice python3 sed systemctl timeout; do
    command -v "$command_name" >/dev/null 2>&1 || \
        fail "required command is missing: $command_name"
done

workspace=$(cd "$1" && pwd -P)
engine_root=$(cd "$2" && pwd -P)
project_input=$3
manifest_input=$4
[[ -f $project_input && ! -L $project_input ]] || fail "project does not exist: $project_input"
[[ -f $manifest_input && ! -L $manifest_input ]] || fail 'private baseline manifest is missing'
project_dir=$(cd "$(dirname "$project_input")" && pwd -P)
project="$project_dir/$(basename "$project_input")"
manifest=$(cd "$(dirname "$manifest_input")" && pwd -P)/$(basename "$manifest_input")
case "$engine_root/" in
    "$workspace"/*) ;;
    *) fail 'the isolated Engine must remain below the cooker workspace' ;;
esac
case "$project_dir/" in
    "$workspace"/fab-acquisition-staging/FayFabAcquisition/) ;;
    *) fail 'the Fab project must be the dedicated acquisition-staging project' ;;
esac
case "$manifest" in
    "$workspace"/logs-private/fab-acquisition/*) ;;
    *) fail 'the baseline manifest must remain in the private Fab log directory' ;;
esac
[[ ${project##*/} == FayFabAcquisition.uproject ]] || \
    fail 'the reviewed staging descriptor must be named FayFabAcquisition.uproject'
for forbidden in Source Plugins; do
    [[ ! -e $project_dir/$forbidden && ! -L $project_dir/$forbidden ]] || \
        fail "the content-only staging project must not contain $forbidden"
done

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
runner="$script_dir/run-fex-rootless.sh"
manifest_tool="$script_dir/fab-staging-manifest.py"
inventory_script="$script_dir/inspect-fab-casual-girl.py"
project_template="$script_dir/../staging/fab-acquisition-template/FayFabAcquisition.uproject"
editor="$engine_root/Engine/Binaries/Linux/UnrealEditor-Cmd"
engine_version="$engine_root/Engine/Binaries/Linux/UnrealEditor.version"
python_binary="$engine_root/Engine/Plugins/Experimental/PythonScriptPlugin/Binaries/Linux/libUnrealEditor-PythonScriptPlugin.so"
python_modules="$engine_root/Engine/Plugins/Experimental/PythonScriptPlugin/Binaries/Linux/UnrealEditor.modules"
scripting_binary="$engine_root/Engine/Plugins/Editor/EditorScriptingUtilities/Binaries/Linux/libUnrealEditor-EditorScriptingUtilities.so"
scripting_modules="$engine_root/Engine/Plugins/Editor/EditorScriptingUtilities/Binaries/Linux/UnrealEditor.modules"
chaos_binary="$engine_root/Engine/Plugins/ChaosCloth/Binaries/Linux/libUnrealEditor-ChaosCloth.so"
chaos_editor_binary="$engine_root/Engine/Plugins/ChaosCloth/Binaries/Linux/libUnrealEditor-ChaosClothEditor.so"
chaos_modules="$engine_root/Engine/Plugins/ChaosCloth/Binaries/Linux/UnrealEditor.modules"

for required in "$runner" "$manifest_tool" "$inventory_script" "$project_template" \
    "$editor" "$engine_version" "$python_binary" "$python_modules" \
    "$scripting_binary" "$scripting_modules" "$chaos_binary" \
    "$chaos_editor_binary" "$chaos_modules"; do
    [[ -f $required && ! -L $required ]] || fail "required review input is missing: $required"
done
[[ -x $runner && -x $editor ]] || fail 'the FEX runner and commandlet Editor must be executable'
for binary in "$editor" "$python_binary" "$scripting_binary" \
    "$chaos_binary" "$chaos_editor_binary"; do
    file "$binary" | grep -q 'x86-64' || fail "review binary is not x86-64: $binary"
done
cmp -s "$project_template" "$project" || \
    fail 'the staging descriptor differs from the reviewed acquisition template'

read_build_id() {
    sed -n 's/.*"BuildId"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$1" | head -1
}
engine_build_id=$(read_build_id "$engine_version")
[[ -n $engine_build_id ]] || fail 'the isolated Editor BuildId is missing'
for modules in "$python_modules" "$scripting_modules" "$chaos_modules"; do
    [[ $(read_build_id "$modules") == "$engine_build_id" ]] || \
        fail "review module manifest does not match the Editor BuildId: $modules"
done

python3 "$manifest_tool" verify "$project_dir" "$manifest"
for anchor in SK_Body SK_Complete SK_Underwear; do
    path="$project_dir/Content/Sample/Meshes/$anchor.uasset"
    [[ -f $path && ! -L $path ]] || fail "imported Casual Girl anchor is missing: $anchor"
done
systemctl --user is-active ue5-spark-avatar-live.service >/dev/null || \
    fail 'the live avatar service is not active; refusing to hide a pre-existing failure'
if (( check_only == 1 )); then
    printf 'Fab review preflight passed; Unreal was not started.\n'
    exit 0
fi

private_state="$workspace/state/fab-review"
private_logs="$workspace/logs-private/fab-acquisition"
mkdir -p "$private_state/home" "$private_state/config" "$private_state/cache" \
    "$private_state/data" "$private_state/state" "$private_logs"
chmod 0700 "$private_state" "$private_state/home" "$private_state/config" \
    "$private_state/cache" "$private_state/data" "$private_state/state" "$private_logs"
export HOME="$private_state/home"
export XDG_CONFIG_HOME="$private_state/config"
export XDG_CACHE_HOME="$private_state/cache"
export XDG_DATA_HOME="$private_state/data"
export XDG_STATE_HOME="$private_state/state"
export FEX_SILENTLOG=${FEX_SILENTLOG:-1}
export FAY_FAB_STAGING_BASELINE_VERIFIED=1

session_limit=${UE5_SPARK_FAB_REVIEW_TIMEOUT:-30m}
[[ $session_limit =~ ^[1-9][0-9]*[smhd]$ ]] || \
    fail 'UE5_SPARK_FAB_REVIEW_TIMEOUT must be a positive duration such as 30m'
umask 077
log=$(mktemp "$private_logs/review-session.XXXXXX.log")
editor_args=(
    "$project"
    -run=pythonscript
    "-script=$inventory_script"
    -EnablePlugins=PythonScriptPlugin,EditorScriptingUtilities,ChaosCloth
    -DisablePlugins=Fab
    -unattended
    -nullrhi
    -stdout
    -FullStdOutLogOutput
    -NoSplash
    -NoSound
    -NoSourceControl
    -NoCompile
    -NoCompileEditor
    -corelimit=2
    -onethread
    -norhithread
)

printf 'Starting the isolated read-only Casual Girl inventory.\n'
printf 'Unreal output is restricted to a private mode-0600 log.\n'
set +e
nice -n 15 timeout --signal=TERM --kill-after=20s "$session_limit" \
    "$runner" "$workspace" -- "$editor" "${editor_args[@]}" >"$log" 2>&1
status=$?
set -e

python3 "$manifest_tool" verify "$project_dir" "$manifest" || \
    fail 'the review changed non-content staging state; preserve and inspect the private evidence'
systemctl --user is-active ue5-spark-avatar-live.service >/dev/null || \
    fail 'the live avatar service changed state during the isolated review'
if (( status == 124 || status == 137 )); then
    fail "the read-only review reached its $session_limit safety stop; inspect the private log"
elif (( status != 0 )); then
    fail "the read-only review exited with status $status; inspect the private log"
fi
if grep -Fq 'FAY_FAB_INVENTORY_ERROR=' "$log"; then
    fail 'the Casual Girl inventory emitted an error; inspect the private log'
fi
grep -Fq 'FAY_FAB_INVENTORY_COMPLETE=OK' "$log" || \
    fail 'the Casual Girl inventory completion marker is missing'

receipt="$private_logs/casual-girl-inventory.json"
python3 - "$inventory_script" "$log" "$receipt" <<'PY'
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import sys
import tempfile

script = Path(sys.argv[1])
log = Path(sys.argv[2])
output = Path(sys.argv[3])
required = {
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
found = {}
pattern = re.compile(r"FAY_FAB_INVENTORY_([A-Z0-9_]+)=([^\r\n]+)")
for match in pattern.finditer(log.read_text(encoding="utf-8", errors="replace")):
    if match.group(1) in required:
        found[match.group(1)] = match.group(2).strip()
if found != required:
    raise SystemExit("error: fixed Casual Girl inventory markers are incomplete")
payload = {
    "schema": 1,
    "status": "passed",
    "inventoryScriptSha256": sha256(script.read_bytes()).hexdigest(),
    "logSha256": sha256(log.read_bytes()).hexdigest(),
    "markers": found,
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

printf 'Casual Girl read-only inventory passed.\n'
printf 'Private inventory log: %s\n' "$log"
