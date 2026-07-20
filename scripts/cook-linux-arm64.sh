#!/usr/bin/env bash
set -euo pipefail

usage() {
    printf 'Usage: %s /path/to/UnrealEngine /path/to/archive\n' "${0##*/}" >&2
    printf 'Run this on an x86-64 Linux host with an editor-capable UE 5.8 build that includes LinuxArm64.\n' >&2
}

if [[ $# -ne 2 ]]; then
    usage
    exit 64
fi

if [[ "$(uname -s)" != "Linux" || "$(uname -m)" != "x86_64" ]]; then
    printf 'error: cooking is intentionally restricted to an x86-64 Linux editor host; this host is %s/%s\n' \
        "$(uname -s)" "$(uname -m)" >&2
    exit 69
fi

engine_input=$1
archive_input=$2

if [[ ! -d "$engine_input" ]]; then
    printf 'error: Unreal Engine directory does not exist: %s\n' "$engine_input" >&2
    exit 66
fi

engine_root=$(cd "$engine_input" && pwd -P)
run_uat="$engine_root/Engine/Build/BatchFiles/RunUAT.sh"
build_version="$engine_root/Engine/Build/Build.version"

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
repo_root=$(cd "$script_dir/.." && pwd -P)
project="$repo_root/Project/FayAvatarRuntime/FayAvatarRuntime.uproject"
plugin="$repo_root/Project/FayAvatarRuntime/Plugins/FayAvatarBridge/FayAvatarBridge.uplugin"

if [[ ! -x "$run_uat" ]]; then
    printf 'error: RunUAT.sh is missing or not executable: %s\n' "$run_uat" >&2
    exit 66
fi
if [[ ! -f "$project" || ! -f "$plugin" ]]; then
    printf 'error: FayAvatarBridge must remain under FayAvatarRuntime/Plugins\n' >&2
    exit 66
fi
if [[ ! -f "$build_version" ]] || \
   ! grep -Eq '"MajorVersion"[[:space:]]*:[[:space:]]*5' "$build_version" || \
   ! grep -Eq '"MinorVersion"[[:space:]]*:[[:space:]]*8' "$build_version"; then
    printf 'error: this project is pinned to Unreal Engine 5.8; Build.version did not match\n' >&2
    exit 65
fi

if [[ -d "$archive_input" ]] && find "$archive_input" -mindepth 1 -print -quit | grep -q .; then
    printf 'error: archive directory must be empty to prevent stale-package validation: %s\n' \
        "$archive_input" >&2
    exit 73
fi

mkdir -p "$archive_input"
archive_root=$(cd "$archive_input" && pwd -P)

printf 'Engine:  %s\n' "$engine_root"
printf 'Project: %s\n' "$project"
printf 'Archive: %s\n' "$archive_root"

exec "$run_uat" BuildCookRun \
    -project="$project" \
    -target=FayAvatarRuntime \
    -platform=LinuxArm64 \
    -clientconfig=Development \
    -build \
    -cook \
    -stage \
    -pak \
    -archive \
    -archivedirectory="$archive_root" \
    -unattended \
    -nop4 \
    -utf8output
