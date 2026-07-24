#!/usr/bin/env bash
set -euo pipefail

usage() {
    printf 'Usage: %s /path/to/cooker-workspace /path/to/isolated/UnrealEngine /path/to/FayFabAcquisition\n' \
        "${0##*/}" >&2
    printf 'Creates or verifies a private, content-only Fab staging project.\n' >&2
}

fail() {
    printf 'error: %s\n' "$*" >&2
    exit 1
}

if (( $# != 3 )); then
    usage
    exit 64
fi
if [[ $(uname -s) != Linux || $(uname -m) != aarch64 ]]; then
    fail "Fab staging preparation requires Linux/aarch64, not $(uname -s)/$(uname -m)"
fi
if (( ${EUID:-$(id -u)} == 0 )); then
    fail 'run Fab staging preparation as the normal workspace owner, not root'
fi
for command_name in cmp dirname file find grep install mkdir mktemp mv rm; do
    command -v "$command_name" >/dev/null 2>&1 || \
        fail "required command is missing: $command_name"
done

workspace_input=$1
engine_input=$2
staging_input=$3
[[ $workspace_input == /* && $engine_input == /* && $staging_input == /* ]] || \
    fail 'workspace, Engine, and staging paths must be absolute'
[[ -d $workspace_input && -d $engine_input ]] || \
    fail 'the cooker workspace and isolated Engine must already exist'
workspace=$(cd "$workspace_input" && pwd -P)
engine_root=$(cd "$engine_input" && pwd -P)
[[ $workspace != / && -O $workspace && -w $workspace ]] || \
    fail 'the cooker workspace must be a user-owned writable directory, not filesystem root'
case "$engine_root/" in
    "$workspace"/*) ;;
    *) fail 'the isolated Engine must remain below the cooker workspace' ;;
esac

staging_parent_input=$(dirname "$staging_input")
mkdir -p "$staging_parent_input"
staging_parent=$(cd "$staging_parent_input" && pwd -P)
[[ -O $staging_parent && -w $staging_parent ]] || \
    fail 'the staging parent must be owned and writable by the invoking user'
case "$staging_parent/" in
    "$workspace"/*) ;;
    *) fail 'the Fab staging project must remain below the cooker workspace' ;;
esac
staging_input="$staging_parent/${staging_input##*/}"
case "$staging_input/" in
    "$engine_root"/*) fail 'the Fab staging project must not be created inside the Engine tree' ;;
esac
[[ ${staging_input##*/} == FayFabAcquisition ]] || \
    fail 'the staging project directory must be named FayFabAcquisition'

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
repo_root=$(cd "$script_dir/.." && pwd -P)
template="$repo_root/staging/fab-acquisition-template"
project_template="$template/FayFabAcquisition.uproject"
editor="$engine_root/Engine/Binaries/Linux/UnrealEditor"
fab_descriptor="$engine_root/Engine/Plugins/Fab/Fab.uplugin"
fab_downloader="$engine_root/Engine/Plugins/Fab/ThirdParty/libBuildPatchInstallerLib.so"
epic_web_helper="$engine_root/Engine/Binaries/Linux/EpicWebHelper"

for required in "$project_template" "$template/Config/DefaultEngine.ini" \
    "$template/Config/DefaultEditorPerProjectUserSettings.ini" \
    "$template/.gitignore" "$template/README.md" "$editor" "$fab_descriptor" \
    "$fab_downloader" "$epic_web_helper"; do
    [[ -f $required && ! -L $required ]] || fail "required staging input is missing: $required"
done
file "$editor" | grep -q 'x86-64' || fail 'the isolated Unreal Editor is not x86-64'
file "$fab_downloader" | grep -q 'x86-64' || fail 'the Fab downloader is not x86-64'
file "$epic_web_helper" | grep -q 'x86-64' || fail 'EpicWebHelper is not x86-64'
grep -q '"Name"[[:space:]]*:[[:space:]]*"Fab"' "$project_template" || \
    fail 'the staging descriptor does not explicitly enable Fab'

temporary=
cleanup() {
    if [[ -n $temporary && -d $temporary ]]; then
        rm -rf -- "$temporary"
    fi
}
trap cleanup EXIT HUP INT TERM

if [[ ! -e $staging_input && ! -L $staging_input ]]; then
    temporary=$(mktemp -d "$staging_parent/.FayFabAcquisition.XXXXXX")
    install -d -m 0755 "$temporary/Config" "$temporary/Content"
    install -m 0644 "$project_template" "$temporary/FayFabAcquisition.uproject"
    install -m 0644 "$template/Config/DefaultEngine.ini" \
        "$temporary/Config/DefaultEngine.ini"
    install -m 0644 "$template/Config/DefaultEditorPerProjectUserSettings.ini" \
        "$temporary/Config/DefaultEditorPerProjectUserSettings.ini"
    install -m 0644 "$template/.gitignore" "$temporary/.gitignore"
    install -m 0644 "$template/README.md" "$temporary/README.md"
    mv "$temporary" "$staging_input"
    temporary=
else
    [[ -d $staging_input && ! -L $staging_input ]] || \
        fail 'the existing staging path must be a real directory'
fi

staging_root=$(cd "$staging_input" && pwd -P)
case "$staging_root/" in
    "$workspace"/*) ;;
    *) fail 'the resolved staging project escapes the cooker workspace' ;;
esac
[[ -O $staging_root && -w $staging_root ]] || \
    fail 'the staging project must be owned and writable by the invoking user'

compare_template() {
    local source=$1
    local destination=$2
    [[ -f $destination && ! -L $destination ]] || \
        fail "staging file is missing or unsafe: $destination"
    cmp -s "$source" "$destination" || \
        fail "staging file differs from the reviewed template: $destination"
}
compare_template "$project_template" "$staging_root/FayFabAcquisition.uproject"
compare_template "$template/Config/DefaultEngine.ini" \
    "$staging_root/Config/DefaultEngine.ini"
compare_template "$template/Config/DefaultEditorPerProjectUserSettings.ini" \
    "$staging_root/Config/DefaultEditorPerProjectUserSettings.ini"
compare_template "$template/.gitignore" "$staging_root/.gitignore"
compare_template "$template/README.md" "$staging_root/README.md"

project_count=$(find "$staging_root" -maxdepth 1 -type f -name '*.uproject' -printf . | wc -c)
(( project_count == 1 )) || fail 'staging root must contain exactly one .uproject'
for forbidden in Source Plugins; do
    [[ ! -e $staging_root/$forbidden && ! -L $staging_root/$forbidden ]] || \
        fail "the content-only staging project must not contain $forbidden"
done

private_state="$workspace/state/fab-acquisition"
private_logs="$workspace/logs-private/fab-acquisition"
install -d -m 0700 "$private_state" "$private_state/home" \
    "$private_state/config" "$private_state/cache" "$private_state/data" \
    "$private_state/state" "$private_logs"

printf 'Prepared isolated Fab acquisition project: %s\n' "$staging_root"
printf 'No Editor was launched, no account was accessed, and no content was downloaded.\n'
printf 'Private state root: %s\n' "$private_state"
printf 'Private log root: %s\n' "$private_logs"
