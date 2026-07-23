#!/usr/bin/env bash
set -euo pipefail

usage() {
    printf 'Usage: %s [--check] /path/to/cooker-workspace /path/to/isolated/UnrealEngine /path/to/FayFabAcquisition.uproject /path/to/private-offline-baseline.json\n' \
        "${0##*/}" >&2
    printf 'Runs the fixed Casual Girl inventory with Fab and Internet sockets disabled.\n' >&2
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
    fail "the offline Fab review requires Linux/aarch64, not $(uname -s)/$(uname -m)"
fi
if (( ${EUID:-$(id -u)} == 0 )); then
    fail 'run the offline Fab review as the normal workspace owner, not root'
fi
for command_name in awk basename chmod cmp dirname file flock grep head id \
    install mkdir mktemp ps rm sed systemctl uname; do
    command -v "$command_name" >/dev/null 2>&1 || \
        fail "required command is missing: $command_name"
done
host_python=/usr/bin/python3
host_docker=/usr/bin/docker
[[ -x /usr/bin/env && -x $host_python && -f $host_docker && \
    ! -L $host_docker && -x $host_docker ]] || \
    fail 'the fixed host env, Python, and Docker executables are unavailable'

workspace=$(cd "$1" && pwd -P)
engine_root=$(cd "$2" && pwd -P)
project_input=$3
manifest_input=$4
[[ -f $project_input && ! -L $project_input ]] || fail "project does not exist: $project_input"
[[ -f $manifest_input && ! -L $manifest_input ]] || fail 'private offline baseline is missing'
project_dir=$(cd "$(dirname "$project_input")" && pwd -P)
project="$project_dir/$(basename "$project_input")"
manifest=$(cd "$(dirname "$manifest_input")" && pwd -P)/$(basename "$manifest_input")
case "$engine_root/" in
    "$workspace"/*) ;;
    *) fail 'the isolated Engine must remain below the cooker workspace' ;;
esac
case "$project_dir/" in
    "$workspace"/fab-acquisition-staging/FayFabAcquisition/) ;;
    *) fail 'the Fab project must be the dedicated staging project' ;;
esac
case "$manifest" in
    "$workspace"/logs-private/fab-acquisition/*) ;;
    *) fail 'the offline baseline must remain in the private Fab log directory' ;;
esac
expected_manifest="$workspace/logs-private/fab-acquisition/offline-before-migration.json"
[[ $manifest == "$expected_manifest" ]] || \
    fail 'the offline baseline must be the exact reviewed offline-before-migration.json'

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
phase_lock_tool="$script_dir/fab-phase-lock.sh"
runner="$script_dir/run-fex-rootless.sh"
non_content_tool="$script_dir/fab-staging-manifest.py"
content_tool="$script_dir/fab-content-manifest.py"
inventory_script="$script_dir/inspect-fab-casual-girl.py"
transition_verifier="$script_dir/verify-fab-offline-transition.py"
offline_template="$script_dir/../staging/fab-offline-template/FayFabAcquisition.uproject"
acquisition_manifest="$workspace/logs-private/fab-acquisition/before-import.json"
content_manifest="$workspace/logs-private/fab-acquisition/casual-girl-content-before-migration.json"
transition_receipt="$workspace/logs-private/fab-acquisition/offline-transition.json"
fex_root="$workspace/fex-root"
rootfs_root="$workspace/rootfs/ubuntu-24.04-x86_64"
editor="$engine_root/Engine/Binaries/Linux/UnrealEditor-Cmd"
engine_version="$engine_root/Engine/Binaries/Linux/UnrealEditor.version"
python_binary="$engine_root/Engine/Plugins/Experimental/PythonScriptPlugin/Binaries/Linux/libUnrealEditor-PythonScriptPlugin.so"
python_modules="$engine_root/Engine/Plugins/Experimental/PythonScriptPlugin/Binaries/Linux/UnrealEditor.modules"
scripting_binary="$engine_root/Engine/Plugins/Editor/EditorScriptingUtilities/Binaries/Linux/libUnrealEditor-EditorScriptingUtilities.so"
scripting_modules="$engine_root/Engine/Plugins/Editor/EditorScriptingUtilities/Binaries/Linux/UnrealEditor.modules"
chaos_binary="$engine_root/Engine/Plugins/ChaosCloth/Binaries/Linux/libUnrealEditor-ChaosCloth.so"
chaos_editor_binary="$engine_root/Engine/Plugins/ChaosCloth/Binaries/Linux/libUnrealEditor-ChaosClothEditor.so"
chaos_modules="$engine_root/Engine/Plugins/ChaosCloth/Binaries/Linux/UnrealEditor.modules"

for required in "$phase_lock_tool" "$runner" "$non_content_tool" "$content_tool" \
    "$inventory_script" "$transition_verifier" "$offline_template" \
    "$acquisition_manifest" "$content_manifest" "$transition_receipt" "$editor" \
    "$engine_version" "$python_binary" "$python_modules" "$scripting_binary" \
    "$scripting_modules" "$chaos_binary" "$chaos_editor_binary" "$chaos_modules"; do
    [[ -f $required && ! -L $required ]] || fail "required offline input is missing: $required"
done
[[ -x $runner && -x $editor ]] || fail 'the FEX runner and commandlet Editor must be executable'
for mount_root in "$script_dir" "$fex_root" "$rootfs_root" "$engine_root" "$project_dir"; do
    [[ -d $mount_root && ! -L $mount_root ]] || \
        fail "container input must be one real directory: $mount_root"
done
guest_python_host="$rootfs_root/usr/bin/python3"
[[ -x $guest_python_host ]] || fail 'the x86-64 guest Python executable is unavailable'
file -L "$guest_python_host" | grep -q 'x86-64' || \
    fail 'the guest Python executable is not x86-64'
cmp -s "$offline_template" "$project" || fail 'the project is not in the reviewed offline phase'
for binary in "$editor" "$python_binary" "$scripting_binary" \
    "$chaos_binary" "$chaos_editor_binary"; do
    file "$binary" | grep -q 'x86-64' || fail "offline binary is not x86-64: $binary"
done

read_build_id() {
    sed -n 's/.*"BuildId"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$1" | head -1
}
engine_build_id=$(read_build_id "$engine_version")
[[ -n $engine_build_id ]] || fail 'the isolated Editor BuildId is missing'
for modules in "$python_modules" "$scripting_modules" "$chaos_modules"; do
    [[ $(read_build_id "$modules") == "$engine_build_id" ]] || \
        fail "offline module manifest does not match the Editor BuildId: $modules"
done

# The shared lock is acquired before inspecting live processes and remains open
# in this shell through verifier, preflight, Editor execution, and post-checks.
# shellcheck source=./fab-phase-lock.sh
source "$phase_lock_tool"
fab_phase_lock_acquire "$workspace" || exit 1
process_list=$(ps -u "$(id -u)" -o pid=,args=)
if awk -v current="$$" -v editor="$editor" -v project="$project" '
    $1 != current && index($0, editor) && index($0, project) { found = 1 }
    END { exit found ? 0 : 1 }
' <<<"$process_list"; then
    fail 'the offline Fab project is already open in Unreal'
fi

"$host_python" "$transition_verifier" \
    --workspace "$workspace" \
    --engine "$engine_root" \
    --project "$project" \
    --acquisition-manifest "$acquisition_manifest"
"$host_python" "$non_content_tool" verify "$project_dir" "$manifest"
"$host_python" "$content_tool" verify "$project_dir" "$content_manifest"
systemctl --user is-active ue5-spark-avatar-live.service >/dev/null || \
    fail 'the live avatar service is not active; refusing to hide a pre-existing failure'

private_state="$workspace/state/fab-offline"
private_logs="$workspace/logs-private/fab-offline"
private_log_root="$workspace/logs-private"
offline_fex_state="$private_state/fex"
offline_tmp="$private_state/tmp"
default_offline_image_id='sha256:f3d28607ddd78734bb7f71f117f3c6706c666b8b76cbff7c9ff6e5718d46ff64'
offline_image_id=${UE5_SPARK_FAB_OFFLINE_IMAGE_ID:-$default_offline_image_id}
[[ $offline_image_id =~ ^sha256:[0-9a-f]{64}$ ]] || \
    fail 'UE5_SPARK_FAB_OFFLINE_IMAGE_ID must be one exact local sha256 image ID'
image_facts=$("$host_docker" image inspect \
    --format '{{.Id}} {{.Os}} {{.Architecture}}' "$offline_image_id" 2>/dev/null) || \
    fail "the pinned ARM64 sandbox image is not present locally: $offline_image_id"
read -r inspected_image_id image_os image_architecture image_extra <<<"$image_facts"
[[ $inspected_image_id == "$offline_image_id" && $image_os == linux && \
    $image_architecture == arm64 && -z ${image_extra:-} ]] || \
    fail 'the pinned sandbox image identity or Linux/arm64 platform is invalid'

ensure_private_directory() {
    local path=$1
    if [[ -e $path || -L $path ]]; then
        [[ -d $path && ! -L $path && -O $path ]] || \
            fail "private offline path must be one real user-owned directory: $path"
    else
        install -d -m 0700 "$path"
    fi
    chmod 0700 "$path"
}
ensure_shared_parent() {
    local path=$1
    if [[ -e $path || -L $path ]]; then
        [[ -d $path && ! -L $path && -O $path ]] || \
            fail "shared workspace path must be one real user-owned directory: $path"
    else
        install -d -m 0700 "$path"
    fi
}
ensure_shared_parent "$private_log_root"
for private_directory in "$private_logs" "$private_state" \
    "$offline_fex_state" "$offline_tmp" "$offline_tmp/home" \
    "$offline_tmp/xdg-config" "$offline_tmp/xdg-cache" \
    "$offline_tmp/xdg-data" "$offline_tmp/xdg-state"; do
    ensure_private_directory "$private_directory"
done

project_saved="$project_dir/Saved"
project_intermediate="$project_dir/Intermediate"
project_ddc="$project_dir/DerivedDataCache"
for writable_directory in "$project_saved" "$project_intermediate" "$project_ddc"; do
    ensure_private_directory "$writable_directory"
done

home_directory="$offline_tmp/home"
config_directory="$offline_tmp/xdg-config"
cache_directory="$offline_tmp/xdg-cache"
data_directory="$offline_tmp/xdg-data"
state_directory="$offline_tmp/xdg-state"
[[ ! -e $home_directory/.ssh && ! -L $home_directory/.ssh ]] || \
    fail 'the private sandbox HOME must not contain .ssh'
clean_environment=(
    -i
    'PATH=/usr/bin:/bin'
    'LANG=C.UTF-8'
    "HOME=$home_directory"
    "TMPDIR=$offline_tmp"
    "XDG_CONFIG_HOME=$config_directory"
    "XDG_CACHE_HOME=$cache_directory"
    "XDG_DATA_HOME=$data_directory"
    "XDG_STATE_HOME=$state_directory"
    "FEX_STATE_ROOT=$offline_fex_state"
    'FEX_SILENTLOG=1'
    'FAY_FAB_STAGING_BASELINE_VERIFIED=1'
    'FAY_FAB_EXPECT_OFFLINE=1'
)

for mount_path in "$script_dir" "$fex_root" "$rootfs_root" "$engine_root" \
    "$project_dir" "$project_saved" "$project_intermediate" "$project_ddc" \
    "$offline_fex_state" "$private_logs" "$offline_tmp"; do
    case $mount_path in
        *,*|*$'\n'*) fail "Docker bind path contains an unsupported character: $mount_path" ;;
    esac
done

docker_mounts=(
    --mount "type=bind,src=$script_dir,dst=$script_dir,readonly"
    --mount "type=bind,src=$fex_root,dst=$fex_root,readonly"
    --mount "type=bind,src=$rootfs_root,dst=$rootfs_root,readonly"
    --mount "type=bind,src=$engine_root,dst=$engine_root,readonly"
    --mount "type=bind,src=$project_ddc,dst=$engine_root/Engine/DerivedDataCache"
    --mount "type=bind,src=$project_dir,dst=$project_dir,readonly"
    --mount "type=bind,src=$project_saved,dst=$project_saved"
    --mount "type=bind,src=$project_intermediate,dst=$project_intermediate"
    --mount "type=bind,src=$project_ddc,dst=$project_ddc"
    --mount "type=bind,src=$offline_fex_state,dst=$offline_fex_state"
    --mount "type=bind,src=$private_logs,dst=$private_logs"
    --mount "type=bind,src=$offline_tmp,dst=$offline_tmp"
)
container_name='ue5-spark-fab-offline-review'
container_phase='offline-review-v1'
container_user="$(id -u):$(id -g)"
workspace_digest=$("$host_python" -c \
    'import hashlib, sys; print(hashlib.sha256(sys.argv[1].encode()).hexdigest())' \
    "$workspace")
[[ $workspace_digest =~ ^[0-9a-f]{64}$ ]] || fail 'could not seal the workspace identity'
docker_base=(
    "$host_docker" run --rm --pull=never
    --name "$container_name"
    --label "com.ue5-spark.fab.phase=$container_phase"
    --label "com.ue5-spark.fab.workspace-sha256=$workspace_digest"
    --network none
    --read-only
    --cap-drop ALL
    --security-opt no-new-privileges
    --user "$container_user"
    --workdir "$project_dir"
    --ipc none
    --pids-limit 4096
    --stop-timeout 20
    --tmpfs '/tmp:rw,nosuid,nodev,noexec,size=256m,mode=1777'
    "${docker_mounts[@]}"
    --entrypoint /usr/bin/env
    "$offline_image_id"
    "${clean_environment[@]}"
)

owned_container_id=
inspect_fixed_container() {
    local listing facts
    local fact_id fact_name fact_image fact_config_image fact_phase fact_workspace
    local fact_network fact_readonly fact_user fact_extra
    listing=$("$host_docker" container ls --all --no-trunc \
        --filter "name=^/${container_name}$" --format '{{.ID}}') || return 3
    [[ -n $listing ]] || return 1
    [[ $listing != *$'\n'* && $listing =~ ^[0-9a-f]{64}$ ]] || return 2
    facts=$("$host_docker" container inspect --format \
        '{{.Id}}|{{.Name}}|{{.Image}}|{{.Config.Image}}|{{index .Config.Labels "com.ue5-spark.fab.phase"}}|{{index .Config.Labels "com.ue5-spark.fab.workspace-sha256"}}|{{.HostConfig.NetworkMode}}|{{.HostConfig.ReadonlyRootfs}}|{{.Config.User}}' \
        "$listing") || return 3
    IFS='|' read -r fact_id fact_name fact_image fact_config_image fact_phase \
        fact_workspace fact_network fact_readonly fact_user fact_extra <<<"$facts"
    [[ -z ${fact_extra:-} && $fact_id == "$listing" && \
        $fact_name == "/$container_name" && $fact_image == "$offline_image_id" && \
        $fact_config_image == "$offline_image_id" && $fact_phase == "$container_phase" && \
        $fact_workspace == "$workspace_digest" && $fact_network == none && \
        $fact_readonly == true && $fact_user == "$container_user" ]] || return 2
    owned_container_id=$listing
}

cleanup_exact_container() {
    local inspect_status candidate
    if inspect_fixed_container; then
        candidate=$owned_container_id
    else
        inspect_status=$?
        (( inspect_status == 1 )) && return 0
        return 1
    fi
    "$host_docker" container stop --time 10 "$candidate" >/dev/null 2>&1 || true
    if inspect_fixed_container; then
        candidate=$owned_container_id
        "$host_docker" container kill "$candidate" >/dev/null 2>&1 || true
        "$host_docker" container rm --force "$candidate" >/dev/null 2>&1 || return 1
    else
        inspect_status=$?
        (( inspect_status == 1 )) && return 0
        return 1
    fi
    if inspect_fixed_container; then
        return 1
    else
        inspect_status=$?
    fi
    (( inspect_status == 1 ))
}

prepare_container_slot() {
    local inspect_status
    if inspect_fixed_container; then
        printf 'Recovering an exact orphaned offline-review container.\n' >&2
        cleanup_exact_container || fail 'could not remove the exact owned offline-review orphan'
        return
    else
        inspect_status=$?
    fi
    case $inspect_status in
        1) return ;;
        2) fail "container name is occupied by an unowned container: $container_name" ;;
        *) fail 'Docker container inventory failed' ;;
    esac
}

probe_suffix="$$-${RANDOM}"
forbidden_probe="$project_dir/Content/.fay-offline-forbidden-$probe_suffix"
state_probe="$offline_fex_state/.fay-offline-state-$probe_suffix"
generated_probe="$project_saved/.fay-offline-generated-$probe_suffix"
probe_files=("$forbidden_probe" "$state_probe" "$generated_probe")
for probe_path in "${probe_files[@]}"; do
    [[ ! -e $probe_path && ! -L $probe_path ]] || fail "sandbox probe path already exists: $probe_path"
done

cleanup_probe_files() {
    local probe_path cleanup_failed=0
    for probe_path in "${probe_files[@]}"; do
        if [[ -e $probe_path || -L $probe_path ]]; then
            if [[ -f $probe_path && ! -L $probe_path && -O $probe_path ]]; then
                rm -f -- "$probe_path" || cleanup_failed=1
            else
                cleanup_failed=1
            fi
        fi
    done
    (( cleanup_failed == 0 ))
}

container_exit_cleanup() {
    local status=$? cleanup_failed=0
    trap - EXIT
    trap '' HUP INT TERM
    set +e
    cleanup_exact_container || cleanup_failed=1
    cleanup_probe_files || cleanup_failed=1
    if (( cleanup_failed == 1 && status == 0 )); then
        status=1
    fi
    exit "$status"
}
trap container_exit_cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

run_in_offline_sandbox() {
    prepare_container_slot
    (
        fab_phase_lock_exec_without_fd "${docker_base[@]}" "$@"
    )
}

# Exercise the actual guest x86-64 Python inside the exact ARM64 container and
# private FEX state. The probe proves both network and filesystem boundaries.
sandbox_probe='import errno, os, platform, socket, sys
from pathlib import Path
if platform.machine().lower() not in {"x86_64", "amd64"}:
    raise SystemExit(40)
for variable in ("DBUS_SESSION_BUS_ADDRESS", "DOCKER_HOST", "TAILSCALE_SOCKET"):
    if os.environ.get(variable):
        raise SystemExit(41)
socket_paths = (
    "/run/docker.sock", "/var/run/docker.sock",
    "/run/tailscale/tailscaled.sock", "/var/run/tailscale/tailscaled.sock",
    "/run/dbus/system_bus_socket", f"/run/user/{os.getuid()}/bus",
)
if any(Path(value).exists() or Path(value).is_symlink() for value in socket_paths):
    raise SystemExit(42)
if (Path.home() / ".ssh").exists() or (Path.home() / ".ssh").is_symlink():
    raise SystemExit(43)
allowed_network_errors = {
    errno.EAFNOSUPPORT, errno.ENETUNREACH, errno.EHOSTUNREACH, errno.ENETDOWN,
    errno.ETIMEDOUT, errno.EPERM, errno.EACCES,
}
def unreachable(family, target, reachable_code, wrong_error_code):
    try:
        candidate = socket.socket(family, socket.SOCK_STREAM)
        candidate.settimeout(0.5)
        try:
            candidate.connect(target)
        finally:
            candidate.close()
    except (socket.timeout, TimeoutError):
        return
    except OSError as error:
        if error.errno not in allowed_network_errors:
            raise SystemExit(wrong_error_code)
        return
    raise SystemExit(reachable_code)
unreachable(socket.AF_INET, ("192.0.2.1", 443), 44, 45)
unreachable(socket.AF_INET6, ("2001:db8::1", 443), 46, 47)
forbidden = Path(sys.argv[1])
try:
    descriptor = os.open(forbidden, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
except OSError as error:
    if error.errno not in {errno.EROFS, errno.EACCES, errno.EPERM}:
        raise SystemExit(49)
else:
    os.close(descriptor)
    forbidden.unlink(missing_ok=True)
    raise SystemExit(48)
def write_probe(value, failure_code):
    path = Path(value)
    descriptor = -1
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.write(descriptor, b"sandbox-ok\n")
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        if path.read_bytes() != b"sandbox-ok\n":
            raise OSError("probe payload mismatch")
    except OSError:
        raise SystemExit(failure_code)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        path.unlink(missing_ok=True)
write_probe(sys.argv[2], 50)
write_probe(sys.argv[3], 51)
try:
    unix_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    unix_socket.close()
except OSError:
    raise SystemExit(52)
'
umask 077
preflight_log=$(mktemp "$private_state/preflight.XXXXXX.log")
set +e
run_in_offline_sandbox \
    "$runner" "$workspace" -- /usr/bin/python3 -c "$sandbox_probe" \
    "$forbidden_probe" "$state_probe" "$generated_probe" \
    >"$preflight_log" 2>&1
sandbox_probe_status=$?
set -e
if (( sandbox_probe_status != 0 )); then
    fail "the guest x86 Docker sandbox preflight failed with status $sandbox_probe_status; private diagnostics: $preflight_log"
fi
cleanup_probe_files || fail 'sandbox probe cleanup failed'
[[ -f $preflight_log && ! -L $preflight_log && -O $preflight_log ]] || \
    fail 'the sandbox preflight log identity changed unexpectedly'
rm -f -- "$preflight_log"

if (( check_only == 1 )); then
    printf 'Offline Fab review preflight passed; Unreal was not started.\n'
    exit 0
fi

session_limit=${UE5_SPARK_FAB_OFFLINE_TIMEOUT:-30m}
[[ $session_limit =~ ^[1-9][0-9]*[smhd]$ ]] || \
    fail 'UE5_SPARK_FAB_OFFLINE_TIMEOUT must be a positive duration such as 30m'
log=$(mktemp "$private_logs/review-session.XXXXXX.log")
editor_args=(
    "$project"
    -run=pythonscript
    "-script=$inventory_script"
    -unattended
    -nullrhi
    -stdout
    -FullStdOutLogOutput
    -NoSplash
    -NoSound
    -NoSourceControl
    -NoCompile
    -NoCompileEditor
    -DDC-ForceMemoryCache
    -corelimit=2
    -onethread
    -norhithread
)

printf 'Starting the network-blocked offline Casual Girl inventory.\n'
set +e
run_in_offline_sandbox \
    nice -n 15 timeout --signal=TERM --kill-after=20s "$session_limit" \
    "$runner" "$workspace" -- "$editor" "${editor_args[@]}" >"$log" 2>&1
status=$?
set -e
cleanup_exact_container || fail 'the exact offline-review container did not terminate cleanly'

"$host_python" "$non_content_tool" verify "$project_dir" "$manifest" || \
    fail 'the offline review changed non-content state'
"$host_python" "$content_tool" verify "$project_dir" "$content_manifest" || \
    fail 'the offline review changed staged Content'
systemctl --user is-active ue5-spark-avatar-live.service >/dev/null || \
    fail 'the live avatar service changed state during offline review'
if (( status != 0 )); then
    fail "the offline review exited with status $status; inspect the private log"
fi
if grep -Fq 'FAY_FAB_INVENTORY_ERROR=' "$log"; then
    fail 'the offline inventory emitted an error; inspect the private log'
fi
grep -Fq 'FAY_FAB_INVENTORY_OFFLINE_PLUGINS=OK' "$log" || \
    fail 'the offline plugin-state marker is missing'
grep -Fq 'FAY_FAB_INVENTORY_COMPLETE=OK' "$log" || \
    fail 'the offline inventory completion marker is missing'

printf 'Network-blocked offline Casual Girl inventory passed.\n'
printf 'Private offline log: %s\n' "$log"
