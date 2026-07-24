#!/usr/bin/env bash
set -euo pipefail

usage() {
    printf 'Usage: %s [--check] /path/to/cooker-workspace /path/to/isolated/UnrealEngine /path/to/FayFabAcquisition.uproject\n' \
        "${0##*/}" >&2
    printf 'Builds Epic\x27s x86-64 Fab Editor module with the prepared native cross toolchain.\n' >&2
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
if (( $# != 3 )); then
    usage
    exit 64
fi
if [[ $(uname -s) != Linux || $(uname -m) != aarch64 ]]; then
    fail "the Fab Editor builder requires Linux/aarch64, not $(uname -s)/$(uname -m)"
fi
if (( ${EUID:-$(id -u)} == 0 )); then
    fail 'run the Fab Editor builder as the normal workspace owner, not root'
fi
for command_name in cmp file grep mktemp python3 tee; do
    command -v "$command_name" >/dev/null 2>&1 || \
        fail "required command is missing: $command_name"
done

workspace=$(cd "$1" && pwd -P)
engine_root=$(cd "$2" && pwd -P)
project_input=$3
[[ -f $project_input && ! -L $project_input ]] || fail "project does not exist: $project_input"
project_dir=$(cd "$(dirname "$project_input")" && pwd -P)
project="$project_dir/$(basename "$project_input")"
case "$engine_root/" in
    "$workspace"/*) ;;
    *) fail 'the isolated Engine must remain below the cooker workspace' ;;
esac
case "$project_dir/" in
    "$workspace"/fab-acquisition-staging/FayFabAcquisition/) ;;
    *) fail 'the Fab project must be the dedicated acquisition-staging project' ;;
esac
[[ ${project##*/} == FayFabAcquisition.uproject ]] || \
    fail 'the reviewed staging descriptor must be named FayFabAcquisition.uproject'
for forbidden in Source Plugins; do
    [[ ! -e $project_dir/$forbidden && ! -L $project_dir/$forbidden ]] || \
        fail "the content-only staging project must not contain $forbidden"
done

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
metadata_tool="$script_dir/fab-module-metadata.py"
project_template="$script_dir/../staging/fab-acquisition-template/FayFabAcquisition.uproject"
dotnet="$engine_root/.spark-tools/dotnet/dotnet"
ubt="$engine_root/Engine/Binaries/DotNET/UnrealBuildTool/UnrealBuildTool.dll"
native_llvm="$engine_root/.spark-tools/llvm-20.1.8/bin"
native_clang="$native_llvm/clang"
native_clangxx="$native_llvm/clang++"
toolchain="$workspace/toolchains/native-cross-v26"
build_version="$engine_root/Engine/Build/Build.version"
editor_target="$engine_root/Engine/Source/UnrealEditor.Target.cs"
fab_descriptor="$engine_root/Engine/Plugins/Fab/Fab.uplugin"
fab_downloader="$engine_root/Engine/Plugins/Fab/ThirdParty/libBuildPatchInstallerLib.so"
epic_web_helper="$engine_root/Engine/Binaries/Linux/EpicWebHelper"
fab_binary="$engine_root/Engine/Plugins/Fab/Binaries/Linux/libUnrealEditor-Fab.so"
fab_modules="$engine_root/Engine/Plugins/Fab/Binaries/Linux/UnrealEditor.modules"
engine_version="$engine_root/Engine/Binaries/Linux/UnrealEditor.version"
engine_metadata="$project_dir/Intermediate/Build/Linux/x64/UnrealEditor/Development/EngineMetadata.json"
parallel_actions=${UE5_SPARK_BUILD_JOBS:-2}

[[ $parallel_actions =~ ^[1-4]$ ]] || \
    fail 'UE5_SPARK_BUILD_JOBS must be an integer from one through four'
for required in "$dotnet" "$ubt" "$native_clang" "$native_clangxx" \
    "$build_version" "$editor_target" "$fab_descriptor" \
    "$fab_downloader" "$epic_web_helper" "$engine_version" \
    "$metadata_tool" "$project_template" \
    "$toolchain/ToolchainVersion.txt" \
    "$toolchain/x86_64-unknown-linux-gnu/bin/clang" \
    "$toolchain/x86_64-unknown-linux-gnu/bin/clang++"; do
    [[ -e $required ]] || fail "required build input is missing: $required"
done

grep -Fxq 'v26_clang-20.1.8-rockylinux8' "$toolchain/ToolchainVersion.txt" || \
    fail 'the isolated Epic v26 cross-toolchain marker is incompatible'
grep -Eq '"MajorVersion"[[:space:]]*:[[:space:]]*5' "$build_version" &&
    grep -Eq '"MinorVersion"[[:space:]]*:[[:space:]]*8' "$build_version" &&
    grep -Eq '"PatchVersion"[[:space:]]*:[[:space:]]*0' "$build_version" || \
    fail 'the isolated Engine must remain Unreal Engine 5.8.0 exactly'
file -L "$dotnet" | grep -q 'ARM aarch64' || fail 'the prepared dotnet host is not ARM64'
file -L "$native_clang" | grep -q 'ARM aarch64' || fail 'the prepared clang is not ARM64'
"$native_clang" --version | grep -q 'clang version 20\.1\.8' || \
    fail 'the prepared native compiler is not clang 20.1.8'
file "$fab_downloader" | grep -q 'x86-64' || fail 'the Fab downloader is not x86-64'
file "$epic_web_helper" | grep -q 'x86-64' || fail 'EpicWebHelper is not x86-64'
cmp -s "$project_template" "$project" || \
    fail 'the staging descriptor differs from the reviewed template'

python3 - "$project" <<'PY'
import json
from pathlib import Path
import sys

project = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
plugins = project.get("Plugins")
expected = [{"Name": "Fab", "Enabled": True, "TargetAllowList": ["Editor"]}]
if project.get("DisableEnginePluginsByDefault") is not True or plugins != expected:
    raise SystemExit("error: staging descriptor must enable only the Editor-scoped Fab plugin")
if project.get("Modules"):
    raise SystemExit("error: Fab acquisition staging must remain content-only")
PY

export PATH="$native_llvm:$PATH"
export LINUX_MULTIARCH_ROOT="$toolchain"
export UE5_SPARK_NATIVE_CLANG="$native_clang"
export UE5_SPARK_NATIVE_CLANGXX="$native_clangxx"
export UE_LOCAL_DDC_PATH="$workspace/state/fab-acquisition/build-ddc"

if (( check_only == 1 )); then
    "$dotnet" "$ubt" UnrealEditor Linux Development -Project="$project" \
        -SkipBuild -NoUBA -NoDumpSyms
    uht_manifest="$project_dir/Intermediate/Build/Linux/UnrealEditor/UnrealEditor.uhtmanifest"
    [[ -f $uht_manifest && ! -L $uht_manifest ]] || \
        fail 'generic UnrealEditor target setup did not emit a UHT manifest'
    python3 - "$uht_manifest" "$engine_root/Engine/Plugins/Fab/Source/Fab" <<'PY'
import json
from pathlib import Path
import sys

manifest = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
expected = Path(sys.argv[2]).resolve(strict=True)
fab_modules = [module for module in manifest.get("Modules", []) if module.get("Name") == "Fab"]
if len(fab_modules) != 1:
    raise SystemExit("error: generic UnrealEditor target setup did not include exactly one Fab module")
if Path(fab_modules[0].get("BaseDirectory", "")).resolve() != expected:
    raise SystemExit("error: generic UnrealEditor target resolved Fab from an unexpected source")
PY
    printf 'Fab staging target-rules preflight passed; no compile action was executed.\n'
    printf 'Fab module is present in the generated UnrealEditor UHT manifest.\n'
    if [[ -f $fab_binary && -f $fab_modules ]]; then
        file "$fab_binary" | grep -q 'x86-64' || fail 'the existing Fab module is not x86-64'
        printf 'An existing x86-64 Fab Editor module is present.\n'
    else
        printf 'Fab Editor module is not built yet; a guarded build is still required.\n'
    fi
    exit 0
fi

log_dir="$workspace/logs-private/fab-acquisition"
mkdir -p "$log_dir"
chmod 0700 "$log_dir"
umask 077
log=$(mktemp "$log_dir/build-fab-editor.XXXXXX.log")

printf 'Building the x86-64 Unreal Editor with the isolated Fab staging descriptor.\n'
set +e
"$dotnet" "$ubt" UnrealEditor Linux Development -Project="$project" \
    -Module=Fab -NoUBA -NoDumpSyms -MaxParallelActions="$parallel_actions" \
    2>&1 | tee "$log"
status=${PIPESTATUS[0]}
set -e
(( status == 0 )) || fail "Fab Editor build failed with status $status; inspect $log"

[[ -f $fab_binary && ! -L $fab_binary ]] || \
    fail 'the build finished without producing the Fab Editor module'
file "$fab_binary" | grep -q 'x86-64' || fail 'the built Fab module is not x86-64'

# -Module=Fab deliberately avoids thousands of unrelated Editor actions. UBT
# therefore does not execute the target-wide metadata action. Reduce UBT's own
# generated EngineMetadata.json to the one reviewed Fab entry, pin the existing
# Editor BuildId explicitly, then ask UBT's WriteMetadata mode to create the
# normal manifest. This avoids hand-authoring Unreal's metadata format, a stale
# manifest changing the BuildId, or touching any other Engine/plugin manifest.
[[ -f $engine_metadata && ! -L $engine_metadata ]] || \
    fail 'UBT did not emit the expected EngineMetadata.json'
fab_metadata_dir=$(mktemp -d "$log_dir/fab-metadata.XXXXXX")
chmod 0700 "$fab_metadata_dir"
fab_metadata="$fab_metadata_dir/EngineMetadata-Fab.json"
"$metadata_tool" "$engine_metadata" "$fab_metadata" "$fab_modules" \
    "$fab_binary" "$engine_version"
"$dotnet" "$ubt" -Mode=WriteMetadata -Input="$fab_metadata" -Version=2

[[ -f $fab_modules && ! -L $fab_modules ]] || \
    fail 'UBT WriteMetadata did not produce the Fab module manifest'
read_build_id() {
    sed -n 's/.*"BuildId"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$1" | head -1
}
engine_build_id=$(read_build_id "$engine_version")
[[ -n $engine_build_id && $(read_build_id "$fab_modules") == "$engine_build_id" ]] || \
    fail 'the Fab module manifest does not match the isolated Editor build ID'
printf 'Built and verified the x86-64 Fab Editor module: %s\n' "$fab_binary"
printf 'No Editor was launched and no account or licensed content was accessed.\n'
