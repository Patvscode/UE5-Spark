#!/usr/bin/env bash
set -euo pipefail

usage() {
    printf 'Usage: %s /path/to/cooker-workspace /path/to/isolated/UnrealEngine /path/to/FayFabAcquisition.uproject\n' \
        "${0##*/}" >&2
    printf 'Installs and builds the fixed Casual Girl Fab listing command in the isolated Editor.\n' >&2
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
    fail "the Fab listing adapter requires Linux/aarch64, not $(uname -s)/$(uname -m)"
fi
if (( ${EUID:-$(id -u)} == 0 )); then
    fail 'run the Fab listing adapter as the normal workspace owner, not root'
fi
for command_name in awk cat chmod cp dirname file flock grep id install mktemp patch ps python3 rm \
    sha256sum systemctl; do
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

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
builder="$script_dir/build-fex-fab-staging.sh"
source_file="$engine_root/Engine/Plugins/Fab/Source/Fab/Private/FabConsoleCommands.cpp"
fab_binary="$engine_root/Engine/Plugins/Fab/Binaries/Linux/libUnrealEditor-Fab.so"
fab_modules="$engine_root/Engine/Plugins/Fab/Binaries/Linux/UnrealEditor.modules"
editor="$engine_root/Engine/Binaries/Linux/UnrealEditor"
private_root="$workspace/logs-private/fab-acquisition"
backup_root="$private_root/fab-listing-command-backup"
readonly ORIGINAL_SOURCE_SHA256='0b76f9e4abf8286daa87cd46d63529cacb168fb754c4a3db4e398c0bcb2aaeee'
readonly COMMAND_NAME='Fab.OpenReviewedCasualGirl'
readonly LISTING_URL='https://www.fab.com/plugins/ue5/listings/1da38c7b-c197-4cc4-a02f-9f63f480e300'

verify_binary_literals() {
    python3 - "$fab_binary" "$COMMAND_NAME" "$LISTING_URL" <<'PY'
from pathlib import Path
import sys

data = Path(sys.argv[1]).read_bytes()
encodings = ("utf-8", "utf-16-le", "utf-16-be", "utf-32-le", "utf-32-be")
for value in sys.argv[2:]:
    if not any(value.encode(encoding) in data for encoding in encodings):
        raise SystemExit("error: rebuilt Fab module is missing a reviewed literal")
PY
}

for required in "$builder" "$source_file" "$fab_binary" "$fab_modules" "$editor"; do
    [[ -f $required && ! -L $required ]] || fail "required input is missing: $required"
done
[[ -x $builder && -x $editor ]] || fail 'the guarded builder and Editor must be executable'
file "$fab_binary" | grep -q 'x86-64' || fail 'the existing Fab module is not x86-64'
systemctl --user is-active ue5-spark-avatar-live.service >/dev/null || \
    fail 'the live avatar service is not active; refusing to hide a pre-existing failure'
if ps -u "$(id -u)" -o args= | grep -F "$editor $project" | grep -v grep >/dev/null; then
    fail 'the Fab staging Editor is running; close it before rebuilding the module'
fi

lock_parent="/run/user/$(id -u)"
[[ -d $lock_parent && ! -L $lock_parent ]] || fail 'the private runtime directory is unavailable'
lock_file="$lock_parent/ue5-spark-fab-listing-command.lock"
exec 9>>"$lock_file"
chmod 0600 "$lock_file"
flock -n 9 || fail 'another Fab listing adapter operation is already running'

install -d -m 0700 "$private_root" "$backup_root"
backup_dir="$backup_root/$ORIGINAL_SOURCE_SHA256"
install -d -m 0700 "$backup_dir"
source_backup="$backup_dir/FabConsoleCommands.cpp"
binary_backup="$backup_dir/libUnrealEditor-Fab.so"
modules_backup="$backup_dir/UnrealEditor.modules"

source_hash=$(sha256sum "$source_file" | awk '{print $1}')
if grep -Fq "TEXT(\"$COMMAND_NAME\")" "$source_file"; then
    [[ $(grep -Fc "TEXT(\"$COMMAND_NAME\")" "$source_file") == 1 ]] || \
        fail 'the reviewed Fab listing command appears more than once'
    [[ $(grep -Fc "\"$LISTING_URL\"" "$source_file") == 1 ]] || \
        fail 'the installed Fab listing command does not contain the one reviewed URL'
    verify_binary_literals
    printf 'The reviewed Casual Girl Fab listing command is already installed.\n'
    exit 0
fi
[[ $source_hash == "$ORIGINAL_SOURCE_SHA256" ]] || \
    fail 'FabConsoleCommands.cpp differs from the reviewed UE 5.8/Fab 0.0.13 source'

if [[ ! -e $source_backup ]]; then
    cp -p "$source_file" "$source_backup"
    cp -p "$fab_binary" "$binary_backup"
    cp -p "$fab_modules" "$modules_backup"
    chmod 0600 "$source_backup" "$binary_backup" "$modules_backup"
else
    [[ -f $source_backup && ! -L $source_backup && \
       $(sha256sum "$source_backup" | awk '{print $1}') == "$ORIGINAL_SOURCE_SHA256" ]] || \
        fail 'the private Fab source backup is missing or untrusted'
    [[ -f $binary_backup && ! -L $binary_backup && -f $modules_backup && ! -L $modules_backup ]] || \
        fail 'the private Fab binary backup is incomplete'
fi

patch_file=$(mktemp "$private_root/fab-listing-command.XXXXXX.patch")
chmod 0600 "$patch_file"
cleanup_patch() {
    rm -f -- "$patch_file"
}
trap cleanup_patch EXIT HUP INT TERM
cat >"$patch_file" <<'PATCH'
--- FabConsoleCommands.cpp
+++ FabConsoleCommands.cpp
@@ -35,0 +36,12 @@
+static FAutoConsoleCommand ConsoleCmd_FabOpenReviewedCasualGirl(
+	TEXT("Fab.OpenReviewedCasualGirl"),
+	TEXT("Open the reviewed Free Casual Girl Sample listing in the Fab plugin"),
+	FConsoleCommandDelegate::CreateLambda([]()
+	{
+		static const FString ListingUrl = TEXT(
+			"https://www.fab.com/plugins/ue5/listings/1da38c7b-c197-4cc4-a02f-9f63f480e300");
+		FAB_LOG("Opening the reviewed Free Casual Girl Sample listing");
+		FFabBrowser::OpenInNewTab(ListingUrl);
+	})
+);
+
PATCH

rollback_armed=1
rollback() {
    local status=$?
    trap - EXIT HUP INT TERM
    rm -f -- "$patch_file"
    if (( status != 0 && rollback_armed == 1 )); then
        cp -p "$source_backup" "$source_file" || true
        cp -p "$binary_backup" "$fab_binary" || true
        cp -p "$modules_backup" "$fab_modules" || true
        printf 'Restored the reviewed Fab source, binary, and module manifest after failure.\n' >&2
    fi
    exit "$status"
}
trap rollback EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

patch --batch --forward --fuzz=0 "$source_file" "$patch_file"
[[ $(grep -Fc "TEXT(\"$COMMAND_NAME\")" "$source_file") == 1 ]] || \
    fail 'the Fab listing command patch did not produce the exact reviewed marker'

"$builder" "$workspace" "$engine_root" "$project"
verify_binary_literals
file "$fab_binary" | grep -q 'x86-64' || fail 'the rebuilt Fab module is not x86-64'
systemctl --user is-active ue5-spark-avatar-live.service >/dev/null || \
    fail 'the live avatar service changed state during the isolated Fab rebuild'

result="$private_root/fab-listing-command-installed.txt"
umask 077
printf 'status=passed\ncommand=%s\nsource_sha256=%s\nbinary_sha256=%s\n' \
    "$COMMAND_NAME" "$(sha256sum "$source_file" | awk '{print $1}')" \
    "$(sha256sum "$fab_binary" | awk '{print $1}')" >"$result"
rollback_armed=0
printf 'Installed and verified the reviewed Casual Girl Fab listing command.\n'
printf 'Private rollback copy: %s\n' "$backup_dir"
