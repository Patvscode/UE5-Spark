#!/usr/bin/env bash
set -euo pipefail

fail() {
    printf 'error: %s\n' "$*" >&2
    exit 1
}

[[ $(uname -s) == Linux && $(uname -m) == aarch64 ]] || \
    fail 'Install these launchers on the Linux ARM64 DGX Spark'
(( ${EUID:-$(id -u)} != 0 )) || fail 'Run as the normal desktop user'

for command_name in install mktemp mv sed; do
    command -v "$command_name" >/dev/null 2>&1 || \
        fail "Required command is missing: $command_name"
done

project_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
template_root="$project_root/apps/spark-desktop"
web_launcher="$project_root/scripts/open-spark-web-app.sh"
unreal_launcher="$project_root/scripts/open-unreal-editor-spark.sh"
cooker_root=$(cd -- "$project_root/.." && pwd -P)
unreal_icon="$cooker_root/engine-build/UnrealEngine-5.8.0-x86-cooker-v2/Engine/Content/Editor/Slate/About/UnrealLogo.svg"

[[ -x $web_launcher ]] || fail 'The web-app launcher is missing or not executable'
[[ -x $unreal_launcher ]] || fail 'The Unreal launcher is missing or not executable'
[[ -f /usr/share/pixmaps/nvidia-logo_64x64.png ]] || \
    fail 'The installed NVIDIA logo is missing'

desktop_dir=$(xdg-user-dir DESKTOP 2>/dev/null || true)
[[ -n $desktop_dir ]] || desktop_dir="$HOME/Desktop"
application_dir="$HOME/.local/share/applications"
[[ -d $desktop_dir ]] || install -d -m 0700 "$desktop_dir"
[[ -d $application_dir ]] || install -d -m 0700 "$application_dir"

render_desktop() {
    local template=$1
    local output=$2
    local temporary escaped_web escaped_unreal escaped_icon
    escaped_web=$(printf '%s' "$web_launcher" | sed 's/[&|\\]/\\&/g')
    escaped_unreal=$(printf '%s' "$unreal_launcher" | sed 's/[&|\\]/\\&/g')
    escaped_icon=$(printf '%s' "$unreal_icon" | sed 's/[&|\\]/\\&/g')
    temporary=$(mktemp "${output%.desktop}.tmp.XXXXXX.desktop")
    sed \
        -e "s|@WEB_LAUNCHER@|$escaped_web|g" \
        -e "s|@UNREAL_LAUNCHER@|$escaped_unreal|g" \
        -e "s|@UNREAL_ICON@|$escaped_icon|g" \
        "$template" > "$temporary"
    chmod 0755 "$temporary"
    if command -v desktop-file-validate >/dev/null 2>&1; then
        desktop-file-validate "$temporary"
    fi
    mv "$temporary" "$output"
}

render_desktop \
    "$template_root/UE5-Spark-Avatar.desktop.in" \
    "$application_dir/ue5-spark-avatar.desktop"
render_desktop \
    "$template_root/UE5-Spark-Avatar.desktop.in" \
    "$desktop_dir/UE5 Spark Avatar.desktop"
render_desktop \
    "$template_root/ARDY-Character-Lab.desktop.in" \
    "$application_dir/ardy-character-lab.desktop"
render_desktop \
    "$template_root/ARDY-Character-Lab.desktop.in" \
    "$desktop_dir/NVIDIA ARDY Character Lab.desktop"
unreal_installed=0
if [[ -f $unreal_icon && ! -L $unreal_icon ]]; then
    render_desktop \
        "$template_root/Unreal-Editor-5.8-Spark.desktop.in" \
        "$application_dir/unreal-editor-5.8-spark.desktop"
    render_desktop \
        "$template_root/Unreal-Editor-5.8-Spark.desktop.in" \
        "$desktop_dir/Unreal Editor 5.8 (Experimental).desktop"
    unreal_installed=1
else
    printf 'warning: Unreal Editor is not prepared; skipping its launcher\n' >&2
fi

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$application_dir" >/dev/null 2>&1 || true
fi

if command -v gio >/dev/null 2>&1; then
    session_bus="unix:path=/run/user/$(id -u)/bus"
    trusted_desktops=(
        "$desktop_dir/UE5 Spark Avatar.desktop"
        "$desktop_dir/NVIDIA ARDY Character Lab.desktop"
    )
    if (( unreal_installed == 1 )); then
        trusted_desktops+=(
            "$desktop_dir/Unreal Editor 5.8 (Experimental).desktop"
        )
    fi
    for desktop_file in "${trusted_desktops[@]}"; do
        env \
            DBUS_SESSION_BUS_ADDRESS="$session_bus" \
            XDG_RUNTIME_DIR="/run/user/$(id -u)" \
            gio set "$desktop_file" metadata::trusted true \
            >/dev/null 2>&1 || \
            printf 'warning: GNOME may ask you to allow launching %s once\n' \
                "${desktop_file##*/}" >&2
    done
fi

printf 'Installed desktop applications:\n'
printf '  %s\n' \
    'UE5 Spark Avatar' \
    'NVIDIA ARDY Character Lab' \
    'ARDY Blender (already installed)'
if (( unreal_installed == 1 )); then
    printf '  %s\n' 'Unreal Editor 5.8 (Experimental)'
fi
