#!/usr/bin/env bash
set -euo pipefail

fail() {
    local message=$1
    printf 'error: %s\n' "$message" >&2
    if command -v zenity >/dev/null 2>&1; then
        zenity --error \
            --title='Unreal Editor 5.8 (Experimental)' \
            --text="$message" >/dev/null 2>&1 || true
    fi
    exit 1
}

[[ $(uname -s) == Linux && $(uname -m) == aarch64 ]] || \
    fail 'Run this Editor launcher on the Linux ARM64 DGX Spark'
(( ${EUID:-$(id -u)} != 0 )) || \
    fail 'Run this Editor launcher as the normal desktop user'

project_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
cooker_root=$(cd -- "$project_root/.." && pwd -P)
engine_root="$cooker_root/engine-build/UnrealEngine-5.8.0-x86-cooker-v2"
uproject="$project_root/Project/FayAvatarRuntime/FayAvatarRuntime.uproject"
editor="$engine_root/Engine/Binaries/Linux/UnrealEditor"

[[ -x $project_root/scripts/run-fex-editor.sh ]] || \
    fail 'The reviewed FEX Editor adapter is missing'
[[ -x $editor ]] || fail 'The prepared Unreal Editor 5.8 build is missing'
[[ -f $uproject ]] || fail 'The FayAvatarRuntime project is missing'

if pgrep -u "$(id -u)" -f "$editor" >/dev/null 2>&1; then
    fail 'Unreal Editor is already running'
fi

display_value=${DISPLAY:-}
xauthority_path=${XAUTHORITY:-}
if [[ -z $display_value || -z $xauthority_path ]]; then
    gnome_pid=$(pgrep -u "$(id -u)" -n gnome-shell || true)
    [[ -n $gnome_pid ]] || fail 'No active GNOME desktop session was found'
    while IFS='=' read -r key value; do
        case "$key" in
            DISPLAY) [[ -n $display_value ]] || display_value=$value ;;
            XAUTHORITY) [[ -n $xauthority_path ]] || xauthority_path=$value ;;
        esac
    done < <(tr '\0' '\n' < "/proc/$gnome_pid/environ")
fi
[[ -n $display_value ]] || fail 'The desktop DISPLAY is unavailable'
[[ -r $xauthority_path ]] || fail 'The desktop Xauthority file is unavailable'

export DISPLAY=$display_value
export XAUTHORITY=$xauthority_path
export XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR:-"/run/user/$(id -u)"}
export DBUS_SESSION_BUS_ADDRESS=${DBUS_SESSION_BUS_ADDRESS:-"unix:path=$XDG_RUNTIME_DIR/bus"}
export UE5_SPARK_EDITOR_TIMEOUT=${UE5_SPARK_EDITOR_TIMEOUT:-30m}

if command -v notify-send >/dev/null 2>&1; then
    notify-send \
        'Unreal Editor 5.8 (Experimental)' \
        'Starting through FEX. The first window can take several minutes.' \
        >/dev/null 2>&1 || true
fi

exec "$project_root/scripts/run-fex-editor.sh" \
    "$cooker_root" \
    "$engine_root" \
    "$uproject"
