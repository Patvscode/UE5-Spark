#!/usr/bin/env bash
set -euo pipefail

fail() {
    printf 'error: %s\n' "$*" >&2
    exit 1
}

[[ $(uname -s) == Linux && $(uname -m) == aarch64 ]] || \
    fail 'install ARDY Blender on the Linux ARM64 DGX Spark'
(( ${EUID:-$(id -u)} != 0 )) || fail 'run as the normal desktop user'

for command_name in docker install mktemp mv readlink sed; do
    command -v "$command_name" >/dev/null 2>&1 || fail "missing command: $command_name"
done

project_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
cooker_root=$(readlink -f "$project_root/..")
private_root="$cooker_root/models-private/ardy-blender"
desktop_template="$project_root/apps/ardy-blender/ARDY-Blender.desktop.in"
image_name=ue5-spark-blender:5.0.1

[[ -f $project_root/apps/ardy-blender/Dockerfile ]] || \
    fail 'the pinned Blender Dockerfile is missing'
[[ -f $desktop_template ]] || fail 'the Blender desktop template is missing'
[[ -x $project_root/scripts/run-ardy-blender.sh ]] || \
    fail 'the Blender launcher is missing or not executable'

install -d -m 0700 \
    "$private_root" \
    "$private_root/cache" \
    "$private_root/config" \
    "$private_root/exports" \
    "$private_root/home" \
    "$private_root/projects"

docker build --pull --tag "$image_name" "$project_root/apps/ardy-blender"
image_identity=$(docker image inspect \
    --format '{{.Architecture}} {{index .Config.Labels "io.ue5-spark.blender.version"}}' \
    "$image_name")
[[ $image_identity == 'arm64 5.0.1' ]] || \
    fail "built Blender image has an unexpected identity: $image_identity"

icon_path="$private_root/blender.svg"
icon_container=$(docker create "$image_name")
trap 'docker rm -f "$icon_container" >/dev/null 2>&1 || true' EXIT
docker cp "$icon_container:/usr/share/icons/hicolor/scalable/apps/blender.svg" "$icon_path"
docker rm "$icon_container" >/dev/null
trap - EXIT
chmod 0600 "$icon_path"

desktop_dir=$(xdg-user-dir DESKTOP 2>/dev/null || true)
[[ -n $desktop_dir ]] || desktop_dir="$HOME/Desktop"
application_dir="$HOME/.local/share/applications"
[[ -d $desktop_dir ]] || install -d -m 0700 "$desktop_dir"
[[ -d $application_dir ]] || install -d -m 0700 "$application_dir"

render_desktop() {
    local output=$1
    local temporary escaped_exec escaped_icon
    escaped_exec=$(printf '%s' "$project_root/scripts/run-ardy-blender.sh" |
        sed 's/[&|\\]/\\&/g')
    escaped_icon=$(printf '%s' "$icon_path" | sed 's/[&|\\]/\\&/g')
    temporary=$(mktemp "${output%.desktop}.tmp.XXXXXX.desktop")
    sed \
        -e "s|@EXEC@|$escaped_exec|g" \
        -e "s|@ICON@|$escaped_icon|g" \
        "$desktop_template" > "$temporary"
    chmod 0755 "$temporary"
    if command -v desktop-file-validate >/dev/null 2>&1; then
        desktop-file-validate "$temporary"
    fi
    mv "$temporary" "$output"
}

render_desktop "$application_dir/ARDY-Blender.desktop"
render_desktop "$desktop_dir/ARDY-Blender.desktop"

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$application_dir" >/dev/null 2>&1 || true
fi
if command -v gio >/dev/null 2>&1; then
    session_bus="unix:path=/run/user/$(id -u)/bus"
    if ! env DBUS_SESSION_BUS_ADDRESS="$session_bus" \
        XDG_RUNTIME_DIR="/run/user/$(id -u)" \
        gio set "$desktop_dir/ARDY-Blender.desktop" metadata::trusted true \
        >/dev/null 2>&1; then
        printf 'warning: GNOME may ask you to allow launching the desktop icon once\n' >&2
    fi
fi

printf 'Installed real Blender 5.0.1 ARM64 launcher: %s\n' \
    "$desktop_dir/ARDY-Blender.desktop"
printf 'Private Blender projects and exports: %s\n' "$private_root"
