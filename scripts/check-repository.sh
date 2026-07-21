#!/usr/bin/env bash
set -euo pipefail

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
repo_root=$(cd "$script_dir/.." && pwd -P)
cd "$repo_root"

failed=0

fail() {
    printf 'error: %s\n' "$*" >&2
    failed=1
}

for script in scripts/*.sh; do
    bash -n "$script"
    [[ -x "$script" ]] || fail "script is not executable: $script"
done

python_bin=
for candidate in "$(command -v python3 2>/dev/null || true)" /usr/bin/python3; do
    if [[ -n "$candidate" && -x "$candidate" ]] && "$candidate" -c 'import ast' >/dev/null 2>&1; then
        python_bin=$candidate
        break
    fi
done
if [[ -z "$python_bin" ]]; then
    fail 'no runnable Python 3 interpreter is available for repository validation'
else
    "$python_bin" - <<'PY'
import ast
import ipaddress
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from pathlib import PurePosixPath


MAX_PUBLIC_SOURCE_BYTES = 5 * 1024 * 1024
PROJECT_ROOT = PurePosixPath("Project/FayAvatarRuntime")
PROJECT_CONTENT_ROOT = PROJECT_ROOT / "Content"
PROJECT_PLUGINS_ROOT = PROJECT_ROOT / "Plugins"
OWNED_PROJECT_PLUGINS = {
    "FayAvatarBridge",
    "FayBodyMotion",
    "FayMetaHumanEditorTools",
    "FayMetaHumanRuntime",
}

FORBIDDEN_DIRECTORY_NAMES = {
    "binaries",
    "captures",
    "deriveddatacache",
    "intermediate",
    "saved",
    "screenshots",
    "stagedbuilds",
}
FORBIDDEN_ENGINE_DIRECTORY_NAMES = {
    "engine",
    "unrealengine",
    "engine-patches",
    "spark-engine",
}
FORBIDDEN_SUFFIXES = {
    ".7z",
    ".a",
    ".abc",
    ".appimage",
    ".bin",
    ".blend",
    ".bmp",
    ".core",
    ".diff",
    ".docx",
    ".dll",
    ".dmp",
    ".dna",
    ".dylib",
    ".deb",
    ".exe",
    ".exr",
    ".fbx",
    ".gif",
    ".glb",
    ".gltf",
    ".gz",
    ".hdr",
    ".jpeg",
    ".jpg",
    ".jks",
    ".key",
    ".keystore",
    ".lib",
    ".log",
    ".ma",
    ".mb",
    ".mobileprovision",
    ".mov",
    ".mp3",
    ".mp4",
    ".node",
    ".npz",
    ".obj",
    ".o",
    ".onnx",
    ".orig",
    ".p12",
    ".p8",
    ".pak",
    ".patch",
    ".pem",
    ".pfx",
    ".png",
    ".pdf",
    ".pptx",
    ".pt",
    ".pth",
    ".rar",
    ".rej",
    ".rpm",
    ".safetensors",
    ".sig",
    ".so",
    ".stl",
    ".svg",
    ".tar",
    ".tga",
    ".tgz",
    ".tif",
    ".tiff",
    ".token",
    ".txz",
    ".uasset",
    ".ubulk",
    ".ucas",
    ".uexp",
    ".umap",
    ".uptnl",
    ".usd",
    ".usda",
    ".usdc",
    ".ushaderbytecode",
    ".utoc",
    ".wav",
    ".webp",
    ".xlsx",
    ".xz",
    ".zip",
}
FORBIDDEN_CREDENTIAL_NAMES = {
    ".git-credentials",
    ".netrc",
    ".npmrc",
    ".pypirc",
    "stored_tokens",
    "token",
}
FORBIDDEN_CREDENTIAL_PREFIXES = (
    "credentials",
    "secrets.",
)

PRIVATE_NETWORKS = tuple(
    ipaddress.ip_network(network)
    for network in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10")
)
IPV4_PATTERN = re.compile(
    r"(?<![0-9])(?:[0-9]{1,3}\.){3}[0-9]{1,3}(?![0-9])"
)
PRIVATE_IPV6_PATTERN = re.compile(
    r"(?i)(?<![0-9a-f])(?:f[cd][0-9a-f]{2}|fe[89ab][0-9a-f])"
    r"(?::[0-9a-f]{0,4}){1,7}(?![0-9a-f:])"
)
MACHINE_PATH_PATTERNS = (
    re.compile(r"/Users/[^/\s'\"`]+"),
    re.compile(r"/home/[^/\s'\"`]+"),
    re.compile(r"/Volumes/[^/\s'\"`]+"),
    re.compile(r"(?i)[a-z]:[\\/]Users[\\/][^\\/\s'\"`]+"),
)
SECRET_PATTERNS = (
    ("private-key marker", re.compile(r"BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY")),
    ("GitHub token", re.compile(r"(?:github_pat_[A-Za-z0-9_]{20,}|gh[pousr]_[A-Za-z0-9]{20,})")),
    ("OpenAI token", re.compile(r"sk-(?:proj-)?[A-Za-z0-9_-]{20,}")),
    ("AWS access key", re.compile(r"(?:AKIA|ASIA)[A-Z0-9]{16}")),
    ("Slack token", re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}")),
    ("Hugging Face token", re.compile(r"hf_[A-Za-z0-9]{20,}")),
    (
        "Authorization credential",
        re.compile(r"(?i)authorization\s*:\s*(?:basic|bearer)\s+[A-Za-z0-9._~+/=-]{8,}"),
    ),
    (
        "credential assignment",
        re.compile(
            r"(?i)\b(?:api[_-]?key|access[_-]?token|client[_-]?secret|password|passwd)"
            r"\s*[:=]\s*(?P<value>[^\s#;,]+)"
        ),
    ),
)
PLACEHOLDER_VALUES = {
    "changeme",
    "example",
    "placeholder",
    "redacted",
    "replace-me",
    "replace_me",
    "secret",
    "your-api-key",
    "your_api_key",
}


errors = []


def reject(message):
    errors.append(message)


def git_output(*arguments):
    return subprocess.check_output(("git", *arguments))


def candidate_paths():
    output = git_output(
        "ls-files",
        "--cached",
        "--others",
        "--exclude-standard",
        "-z",
    )
    return [os.fsdecode(value) for value in output.split(b"\0") if value]


def is_below(path, parent):
    return path == parent or parent in path.parents


def credential_path_is_forbidden(path):
    name = path.name.lower()
    if name == ".env.example":
        return False
    if name == ".env" or name.startswith(".env.") or name.endswith(".env"):
        return True
    if name in FORBIDDEN_CREDENTIAL_NAMES:
        return True
    if name.startswith(FORBIDDEN_CREDENTIAL_PREFIXES):
        return True
    if name.startswith("id_rsa") or name.startswith("id_ed25519"):
        return True
    return False


def assignment_is_placeholder(match):
    value = match.groupdict().get("value")
    if value is None:
        return False
    value = value.strip("'\"").lower()
    return (
        value in PLACEHOLDER_VALUES
        or value.startswith("${")
        or value.startswith("<")
        or value.startswith("your-")
        or value.startswith("your_")
    )


def scan_text(path, text):
    if path.as_posix() == "scripts/check-repository.sh":
        return

    for line_number, line in enumerate(text.splitlines(), start=1):
        for description, pattern in SECRET_PATTERNS:
            for match in pattern.finditer(line):
                if description == "credential assignment" and assignment_is_placeholder(match):
                    continue
                reject(f"{path}:{line_number}: contains a {description}")

        if any(pattern.search(line) for pattern in MACHINE_PATH_PATTERNS):
            reject(f"{path}:{line_number}: contains a machine-specific home or volume path")

        for value in IPV4_PATTERN.findall(line):
            try:
                address = ipaddress.ip_address(value)
            except ValueError:
                continue
            if any(address in network for network in PRIVATE_NETWORKS):
                reject(f"{path}:{line_number}: contains a private network address")

        if PRIVATE_IPV6_PATTERN.search(line):
            reject(f"{path}:{line_number}: contains a private or link-local IPv6 address")


def validate_candidate(path_string):
    path = PurePosixPath(path_string)
    filesystem_path = Path(path_string)

    if not filesystem_path.exists() and not filesystem_path.is_symlink():
        return

    if filesystem_path.is_symlink():
        reject(f"tracked or publishable symlink is forbidden: {path}")
        return
    if not filesystem_path.is_file():
        return

    if any(part.lower() in FORBIDDEN_DIRECTORY_NAMES for part in path.parts):
        reject(f"generated/private directory is publishable: {path}")
    if any(part.lower() in FORBIDDEN_ENGINE_DIRECTORY_NAMES for part in path.parts):
        reject(f"Epic Engine or private-patch directory is publishable: {path}")
    if is_below(path, PROJECT_CONTENT_ROOT):
        reject(f"project Content is licensed/generated and must remain private: {path}")
    if len(path.parts) > len(PROJECT_PLUGINS_ROOT.parts) and is_below(path, PROJECT_PLUGINS_ROOT):
        plugin_name = path.parts[len(PROJECT_PLUGINS_ROOT.parts)]
        if plugin_name not in OWNED_PROJECT_PLUGINS:
            reject(f"unreviewed project plugin is publishable: {path}")
    if "Plugins" in path.parts and "Marketplace" in path.parts:
        reject(f"Marketplace plugin content is publishable: {path}")
    if credential_path_is_forbidden(path):
        reject(f"credential-bearing filename is publishable: {path}")
    if path.suffix.lower() in FORBIDDEN_SUFFIXES:
        reject(f"binary, asset, archive, log, patch, model, or private-media file is publishable: {path}")

    byte_count = filesystem_path.stat().st_size
    if byte_count > MAX_PUBLIC_SOURCE_BYTES:
        reject(f"public-source file exceeds 5 MiB: {path} ({byte_count} bytes)")
        return

    data = filesystem_path.read_bytes()
    if b"\0" in data:
        reject(f"non-text file is publishable in this source-only repository: {path}")
        return
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        reject(f"non-UTF-8 file is publishable in this source-only repository: {path}")
        return
    scan_text(path, text)


for candidate_path in candidate_paths():
    validate_candidate(candidate_path)

for record in git_output("ls-files", "--stage", "-z").split(b"\0"):
    if not record:
        continue
    metadata, _, raw_path = record.partition(b"\t")
    mode = metadata.split(b" ", 1)[0]
    if mode in {b"120000", b"160000"}:
        reject(
            f"tracked symlink or gitlink is forbidden: {PurePosixPath(os.fsdecode(raw_path))}"
        )

python_sources = (
    Path("tools/fay-avatar-smoke-test.py"),
    Path("tools/tests/test_run_spark_avatar_gate.py"),
    Path("scripts/character-profiles.py"),
    Path("scripts/cook-state.py"),
    Path("scripts/inspect-metahuman-runtime-contract.py"),
    Path("scripts/metahuman-preflight.py"),
    Path("services/ardy/service/ardy_pose_service.py"),
    Path("services/ardy/service/cache_embeddings.py"),
    Path("services/ardy/service/download_checkpoint.py"),
    Path("services/ardy/service/embedding_contract.py"),
    Path("services/ardy/service/pose_protocol.py"),
    Path("services/ardy/service/providers.py"),
    Path("services/ardy/tests/test_pose_protocol.py"),
    Path("services/ardy/tests/test_cache_embeddings.py"),
    Path(
        "Project/FayAvatarRuntime/Plugins/FayMetaHumanEditorTools/"
        "Scripts/build_ada.py"
    ),
)
for source in python_sources:
    ast.parse(source.read_text(), filename=str(source))

json_sources = (
    Path("Project/FayAvatarRuntime/FayAvatarRuntime.uproject"),
    Path(
        "Project/FayAvatarRuntime/Plugins/FayAvatarBridge/"
        "FayAvatarBridge.uplugin"
    ),
    Path(
        "Project/FayAvatarRuntime/Plugins/FayBodyMotion/"
        "FayBodyMotion.uplugin"
    ),
    Path(
        "Project/FayAvatarRuntime/Plugins/FayMetaHumanEditorTools/"
        "FayMetaHumanEditorTools.uplugin"
    ),
    Path(
        "Project/FayAvatarRuntime/Plugins/FayMetaHumanRuntime/"
        "FayMetaHumanRuntime.uplugin"
    ),
    Path("scripts/fex-vulkan-thunks.json"),
)
parsed_json = {source: json.loads(source.read_text()) for source in json_sources}

project = parsed_json[Path("Project/FayAvatarRuntime/FayAvatarRuntime.uproject")]
if project.get("DisableEnginePluginsByDefault") is not True:
    reject("FayAvatarRuntime.uproject must keep DisableEnginePluginsByDefault=true")

plugins = {entry["Name"]: entry for entry in project.get("Plugins", [])}
expected_project_plugins = {
    "AnimationData",
    "ControlRigSpline",
    "FayAvatarBridge",
    "FayBodyMotion",
    "FayMetaHumanEditorTools",
    "FayMetaHumanRuntime",
    "InterchangeAssets",
    "MetaHumanCharacter",
}
if len(project.get("Plugins", [])) != len(plugins) or set(plugins) != expected_project_plugins:
    reject(
        "FayAvatarRuntime.uproject plugin list must contain only the reviewed bridge, "
        "body-motion/runtime plugins, Editor helper, AnimationData, ControlRigSpline, "
        "InterchangeAssets, and MetaHumanCharacter entries"
    )

for plugin_name in (
    "ControlRigSpline",
    "FayAvatarBridge",
    "FayBodyMotion",
    "FayMetaHumanRuntime",
    "InterchangeAssets",
    "MetaHumanCharacter",
):
    plugin = plugins.get(plugin_name)
    if not plugin or not plugin.get("Enabled"):
        reject(f"{plugin_name} must be enabled for packaged Game targets")
        continue
    if "TargetAllowList" in plugin or "TargetDenyList" in plugin:
        reject(f"{plugin_name} must not be restricted away from Game targets")

animation_data = plugins.get("AnimationData")
if not animation_data or not animation_data.get("Enabled"):
    reject("AnimationData must be enabled for Editor targets")
elif animation_data.get("TargetAllowList") != ["Editor"]:
    reject("AnimationData must be restricted to Editor targets")

project_helper = plugins.get("FayMetaHumanEditorTools")
if not project_helper or not project_helper.get("Enabled"):
    reject("FayMetaHumanEditorTools must be enabled for Editor targets")
elif project_helper.get("TargetAllowList") != ["Editor"]:
    reject("FayMetaHumanEditorTools must be restricted to Editor targets")


def validate_contentless_plugin(plugin, path, module_name, module_type):
    if plugin.get("CanContainContent") is not False:
        reject(f"{path} must keep CanContainContent=false")
    modules = plugin.get("Modules", [])
    if len(modules) != 1:
        reject(f"{path} must declare exactly one module")
        return
    module = modules[0]
    if module.get("Name") != module_name or module.get("Type") != module_type:
        reject(f"{path} must keep {module_name} as an {module_type} module")
    if module_type == "Runtime" and (
        "TargetAllowList" in module or "TargetDenyList" in module
    ):
        reject(f"{path} runtime module must remain available to Game targets")


bridge_path = Path(
    "Project/FayAvatarRuntime/Plugins/FayAvatarBridge/FayAvatarBridge.uplugin"
)
validate_contentless_plugin(
    parsed_json[bridge_path],
    bridge_path,
    "FayAvatarBridge",
    "Runtime",
)

body_motion_path = Path(
    "Project/FayAvatarRuntime/Plugins/FayBodyMotion/FayBodyMotion.uplugin"
)
validate_contentless_plugin(
    parsed_json[body_motion_path],
    body_motion_path,
    "FayBodyMotion",
    "Runtime",
)
body_motion_dependencies = {
    entry.get("Name"): entry
    for entry in parsed_json[body_motion_path].get("Plugins", [])
}
if set(body_motion_dependencies) != {"FayAvatarBridge"} or not body_motion_dependencies[
    "FayAvatarBridge"
].get("Enabled"):
    reject("FayBodyMotion must keep only its enabled FayAvatarBridge dependency")

helper_path = Path(
    "Project/FayAvatarRuntime/Plugins/FayMetaHumanEditorTools/"
    "FayMetaHumanEditorTools.uplugin"
)
helper = parsed_json[helper_path]
validate_contentless_plugin(
    helper,
    helper_path,
    "FayMetaHumanEditorTools",
    "Editor",
)
helper_dependencies = {entry.get("Name"): entry for entry in helper.get("Plugins", [])}
if (
    len(helper.get("Plugins", [])) != len(helper_dependencies)
    or set(helper_dependencies) != {"MetaHumanCharacter", "PythonScriptPlugin"}
):
    reject("FayMetaHumanEditorTools must keep only its reviewed Editor dependencies")
for dependency in helper.get("Plugins", []):
    if not dependency.get("Enabled") or dependency.get("TargetAllowList") != ["Editor"]:
        reject("FayMetaHumanEditorTools plugin dependencies must remain enabled and Editor-only")

runtime_path = Path(
    "Project/FayAvatarRuntime/Plugins/FayMetaHumanRuntime/"
    "FayMetaHumanRuntime.uplugin"
)
runtime = parsed_json[runtime_path]
validate_contentless_plugin(
    runtime,
    runtime_path,
    "FayMetaHumanRuntime",
    "Runtime",
)
runtime_dependencies = {entry.get("Name"): entry for entry in runtime.get("Plugins", [])}
expected_runtime_dependencies = {
    "FayAvatarBridge",
    "LiveLink",
    "MetaHumanCharacter",
    "MetaHumanCoreTech",
    "StreamingADA",
}
if (
    len(runtime.get("Plugins", [])) != len(runtime_dependencies)
    or set(runtime_dependencies) != expected_runtime_dependencies
):
    reject("FayMetaHumanRuntime must keep its reviewed runtime plugin dependencies")
for dependency in runtime.get("Plugins", []):
    if not dependency.get("Enabled"):
        reject("FayMetaHumanRuntime plugin dependencies must remain enabled")
    if "TargetAllowList" in dependency or "TargetDenyList" in dependency:
        reject("FayMetaHumanRuntime plugin dependencies must remain available to Game targets")

main_build = Path(
    "Project/FayAvatarRuntime/Source/FayAvatarRuntime/FayAvatarRuntime.Build.cs"
).read_text()
runtime_build = Path(
    "Project/FayAvatarRuntime/Plugins/FayMetaHumanRuntime/Source/"
    "FayMetaHumanRuntime/FayMetaHumanRuntime.Build.cs"
).read_text()
body_motion_build = Path(
    "Project/FayAvatarRuntime/Plugins/FayBodyMotion/Source/"
    "FayBodyMotion/FayBodyMotion.Build.cs"
).read_text()
if '"FayMetaHumanRuntime"' not in main_build:
    reject("the Game module must depend on FayMetaHumanRuntime")
if '"FayBodyMotion"' not in main_build:
    reject("the Game module must depend on FayBodyMotion")
for module_name in ("Core", "CoreUObject", "Engine", "FayAvatarBridge", "HTTP", "Json"):
    if f'"{module_name}"' not in body_motion_build:
        reject(f"FayBodyMotion.Build.cs is missing {module_name}")
for module_name in (
    "AudioPlatformConfiguration",
    "FayAvatarBridge",
    "LiveLink",
    "LiveLinkInterface",
    "MetaHumanCoreTech",
    "NNE",
    "SpeechAnimationSolver",
):
    if f'"{module_name}"' not in runtime_build:
        reject(f"FayMetaHumanRuntime.Build.cs is missing {module_name}")
if "FayMetaHumanEditorTools" in main_build or "FayMetaHumanEditorTools" in runtime_build:
    reject("Editor-only MetaHuman tools must not be a Game/runtime module dependency")

runtime_launcher = Path("scripts/run-cooked-package.sh").read_text()
runtime_launcher_code_lines = [
    line.strip()
    for line in runtime_launcher.splitlines()
    if line.strip() and not line.lstrip().startswith("#")
]
direct_runtime_exec = 'exec "$game_binary" FayAvatarRuntime -vulkan -log "$@"'
if runtime_launcher_code_lines[-1:] != [direct_runtime_exec]:
    reject("the guarded package runner must exec the verified game binary as its stable PID")
if re.search(r'(?m)^\s*exec\s+(?:--\s+)?["\']?\$launcher["\']?(?:\s|$)', runtime_launcher) or re.search(
    r'(?m)^\s*["\']?\$launcher["\']?\s+(?![<>|&])', runtime_launcher
):
    reject("the guarded package runner must not leave AutomationTool's shell launcher as a parent")

soak_wrapper = Path("scripts/run-spark-avatar-soak.sh").read_text()
soak_harness = Path("scripts/soak-spark-avatar.sh").read_text()
avatar_gate = Path("scripts/run-spark-avatar-gate.sh").read_text()
csv_analyzer = Path("tools/analyze-unreal-csv.py").read_text()
for marker in (
    "add_diagnostic_override extra-unreal-arguments",
    "add_diagnostic_override resolution-override",
    "add_diagnostic_override resource-policy-override",
    'setsid "$soak_runner"',
    "harness_timeout_seconds=",
    "promote_expected_launcher_transition",
    "observe_allowed_launcher_transition",
    "process_matches_starttime",
    "process_is_live_with_starttime",
    "launcher_env_exe=$(readlink -f /usr/bin/env)",
    "launcher_reached_unreal=0",
    "launcher_identity_capture_in_progress=1",
    "deferred_signal_status",
    "discovered_runtime_pid=${discovered_runtime_pids[0]}",
    '"$launcher_bash_exe" "$digital_human_launcher"',
    'kill -TERM "$runtime_pid"',
    'kill -KILL "$runtime_pid"',
    'wait "$launcher_pid"',
    "capture_post_teardown_evidence",
    'fay_http_ready 5000 /',
    'fay_http_ready 5010 /',
    'fay_http_ready 8766 /sse',
    "Verified project-owned FayGameUserSettings runtime policy.",
    "Enforced reviewed runtime frame cap at 30.00 FPS after GameUserSettings initialization.",
    "validate_csv_evidence",
    "--min-average-fps",
    "--max-average-fps",
    "--expected-total-frames",
    "--max-p95-frame-time-ms",
    "--require-capture-duration",
    'ln -- "$temporary_csv" "$csv_evidence"',
    "csv_capture_sha256",
    "cleanup_runtime 1\nif (( enable_csv == 1 )); then\n    validate_csv_evidence\nfi\nfinalize_evidence_summary",
):
    if marker not in soak_wrapper:
        reject(f"the guarded soak wrapper is missing its reliability contract: {marker}")
cleanup_start = soak_wrapper.find("cleanup_runtime()")
cleanup_end = soak_wrapper.find("finalize_evidence_summary()", cleanup_start)
cleanup_body = soak_wrapper[cleanup_start:cleanup_end]
if 'process_matches_identity "$launcher_pid" "$launcher_exe"' in cleanup_body:
    reject("bootstrap cleanup must follow immutable PID/start time, not a transient executable")
if re.search(
    r'current_launcher_exe\s*!=\s*"\$launcher_exe"', soak_wrapper
):
    reject("launcher discovery must allow reviewed env/bash transitions before Unreal")
if re.search(
    r'(?m)^\s*runtime_pid=\$\{discovered_runtime_pids\[0\]\}', soak_wrapper
):
    reject("runtime discovery must not adopt a scanned PID before ownership validation")
discovery_exe_commit = soak_wrapper.find("runtime_exe=$discovered_runtime_exe")
discovery_start_commit = soak_wrapper.find("runtime_starttime=$discovered_runtime_starttime")
discovery_pid_commit = soak_wrapper.find("runtime_pid=$discovered_runtime_pid")
if min(discovery_exe_commit, discovery_start_commit, discovery_pid_commit) < 0 or not (
    discovery_exe_commit < discovery_start_commit < discovery_pid_commit
):
    reject("runtime discovery must commit executable and start time before its PID")
term_position = cleanup_body.find('kill -TERM "$runtime_pid"')
kill_position = cleanup_body.find('kill -KILL "$runtime_pid"')
capture_position = cleanup_body.find("capture_post_teardown_evidence")
verify_position = cleanup_body.find('"$package_verifier" "$package_launcher_dir"')
if min(term_position, kill_position, capture_position, verify_position) < 0:
    reject("the guarded soak teardown sequence is incomplete")
elif not term_position < kill_position < capture_position < verify_position:
    reject("the guarded soak teardown must TERM, escalate, capture evidence, then verify the seal")
for marker in (
    "FAY_SOAK_EXPECTED_FAY_EXE",
    "FAY_SOAK_EXPECTED_FAY_STARTTIME",
    "process_matches_identity \"$fay_pid\" \"$fay_exe\" \"$fay_starttime\"",
    "reviewed_runtime_argv=(",
    "nonreviewed-runtime-arguments",
    "actual_elapsed_seconds=$((end - start))",
    "idle_measurement_window_start=",
    "idle_measurement_sample_count",
    "runtime_exit_status=pending",
    "post_teardown_runtime_failure_count=pending",
    "game_user_settings_policy_verified_count",
    "frame_rate_policy_enforced_count",
    "frame_rate_policy_violation_count",
):
    if marker not in soak_harness:
        reject(f"the strict soak harness is missing its reliability contract: {marker}")
for marker in (
    "--expected-total-frames",
    "--min-average-fps",
    "--max-average-fps",
    "--max-p95-frame-time-ms",
    "--require-capture-duration",
    'metadata.get("captureduration", [])',
    'metadata.get("hasheaderrowatend", [])',
    "summed FrameTime does not match CSV capture-duration metadata",
):
    if marker not in csv_analyzer:
        reject(f"the strict Unreal CSV analyzer is missing its contract: {marker}")

for marker in (
    "if (( $# != 5 )); then",
    "readonly VOXTRAL_UNIT='codex-studio-voxtral-realtime.service'",
    "readonly ARDY_CONTAINER='ue5-spark-ardy'",
    "PRIVATE_GATE_DIR must not already exist",
    'flock -n 9',
    'voxtral_restore_required=1',
    'systemctl --user stop "$VOXTRAL_UNIT"',
    'systemctl --user start "$VOXTRAL_UNIT"',
    'docker inspect --type container "$ARDY_CONTAINER"',
    'exec setsid "$soak_runner"',
    'kill -TERM -- "-$runner_session_id"',
    'wait "$runner_pid"',
    "runner_identity_capture_in_progress=1",
    "deferred_signal_status",
    "Deferring %s until the owned runner identity is committed.",
    'capture_process_record runner_initial_record "$runner_pid"',
    '${runner_initial_record[1]} == "$supervisor_pid"',
    '${runner_candidate_record[2]} == "$runner_pid"',
    '${runner_candidate_record[3]} == "$runner_pid"',
    '$runner_candidate_exe == "$runner_bash_exe"',
    '${runner_confirm_record[4]} == "$runner_provisional_starttime"',
    "runner_identity_committed=1",
    "while runner_leader_is_live; do",
    "if ! voxtral_is_fully_inactive; then",
    "voxtral_pause_continuity=failed",
    "trap 'on_exit $?' EXIT",
    "trap '' HUP INT TERM",
    "capture_fay_listener_bindings fay_listener_bindings_after",
    "arrays_are_equal fay_listener_bindings_before fay_listener_bindings_after",
    "other_owner=$(grep -oE 'pid=[0-9]+,'",
    "capture_ardy_snapshot ardy_after",
    "arrays_are_equal ardy_before ardy_after",
    '"$gate_root/gate-before.txt"',
    '"$gate_root/gate-after.txt"',
    '"$gate_root/gate-result.txt"',
    "runner_group_post_exit_policy=not-scanned-after-exact-leader-exit",
    "runner_exit_status=kill-timeout",
    "the rendered-soak runner changed executable while remaining live",
    "the allowlisted Voxtral unit or listener returned before restoration",
):
    if marker not in avatar_gate:
        reject(f"the guarded Spark avatar gate is missing its safety contract: {marker}")
if re.search(
    r"\bdocker\s+(?:run|start|stop|restart|rm|kill|pause|unpause|update|exec)\b",
    avatar_gate,
):
    reject("the guarded Spark avatar gate must never mutate ARDY container lifecycle")
lifecycle_calls = re.findall(
    r"systemctl\s+--user\s+"
    r"(start|stop|restart|enable|disable|mask|unmask)\s+([^\s;]+)",
    avatar_gate,
)
if lifecycle_calls != [
    ("start", '"$VOXTRAL_UNIT"'),
    ("stop", '"$VOXTRAL_UNIT"'),
]:
    reject("the guarded Spark avatar gate may mutate only its fixed Voxtral user unit")
restore_arm = avatar_gate.find("voxtral_restore_required=1")
stop_voxtral = avatar_gate.find('systemctl --user stop "$VOXTRAL_UNIT"')
if min(restore_arm, stop_voxtral) < 0 or restore_arm >= stop_voxtral:
    reject("the guarded Spark avatar gate must arm restoration before stopping Voxtral")
if re.search(r"(?m)^\s*FAY_SOAK_[A-Z0-9_]+=", avatar_gate):
    reject("the guarded Spark avatar gate must pass existing soak policy through unchanged")
if "process_group_has_live_members" in avatar_gate or "clear_residual_runner_group" in avatar_gate:
    reject("the guarded Spark avatar gate must never rescan a vanished leader's numeric PGID")
gate_cancel_handler = avatar_gate[
    avatar_gate.find("cancel_and_reap_runner() {"):
    avatar_gate.find("restore_voxtral() {")
]
if gate_cancel_handler.count('kill -TERM -- "-$runner_session_id"') != 1 or \
    gate_cancel_handler.count('kill -KILL -- "-$runner_session_id"') != 1:
    reject("the guarded Spark avatar gate must confine group signals to exact-leader cleanup")
if 'kill -TERM "$runner_pid"' in gate_cancel_handler or \
    'kill -KILL "$runner_pid"' in gate_cancel_handler:
    reject("the guarded Spark avatar gate must never signal a provisional runner PID")
if "if (( session_is_owned == 1 )) && runner_leader_is_live; then" not in gate_cancel_handler:
    reject("the guarded Spark avatar gate must require a live exact leader before group TERM")
gate_final_record = avatar_gate[
    avatar_gate.find("write_final_record() {"):
    avatar_gate.find("write_after_record() {")
]
if gate_final_record.count("voxtral_restore_verified=") != 1:
    reject("the guarded Spark avatar gate result must record Voxtral restoration exactly once")

media_capture = Path("scripts/capture-spark-avatar-window.sh").read_text()
for marker in (
    "process_matches_identity",
    "runtime_log_prelaunch_identity",
    "RUNTIME_LOG does not belong to EXPECTED_UNREAL_EXE",
    "Selected reviewed character profile",
    "Spawned character",
    "Connected to the Fay avatar WebSocket.",
    "Started Fay speech playback",
    "_NET_WM_PID",
    "width == 1280 && $height == 720",
    'xwininfo -id "$candidate"',
    '-window_id "$window_id"',
    "-t 8 -an -vf format=yuv420p",
    "png_probe == 1280x720",
    "mp4_probe == 1280,720,30/1",
    'timeout --signal=TERM --kill-after=5 15 ffmpeg',
    'timeout --signal=TERM --kill-after=5 30 ffmpeg',
    'ln -- "$temporary_png" "$output_png"',
    'ln -- "$temporary_mp4" "$output_mp4"',
    "publish_complete=1",
    "handle_signal HUP 129",
):
    if marker not in media_capture:
        reject(f"the guarded media capture is missing its safety contract: {marker}")
if re.search(r'-f\s+(?:pulse|alsa|avfoundation)', media_capture, re.IGNORECASE):
    reject("private progress capture must not record desktop audio")

speech_header = Path(
    "Project/FayAvatarRuntime/Plugins/FayMetaHumanRuntime/Source/"
    "FayMetaHumanRuntime/Public/FayMetaHumanSpeechDriverComponent.h"
).read_text()
speech_source = Path(
    "Project/FayAvatarRuntime/Plugins/FayMetaHumanRuntime/Source/"
    "FayMetaHumanRuntime/Private/FayMetaHumanSpeechDriverComponent.cpp"
).read_text()
game_mode_source = Path(
    "Project/FayAvatarRuntime/Source/FayAvatarRuntime/Private/"
    "FayAvatarBootstrapGameMode.cpp"
).read_text()
game_mode_header = Path(
    "Project/FayAvatarRuntime/Source/FayAvatarRuntime/Private/"
    "FayAvatarBootstrapGameMode.h"
).read_text()
game_user_settings_header = Path(
    "Project/FayAvatarRuntime/Source/FayAvatarRuntime/Public/"
    "FayGameUserSettings.h"
).read_text()
game_user_settings_source = Path(
    "Project/FayAvatarRuntime/Source/FayAvatarRuntime/Private/"
    "FayGameUserSettings.cpp"
).read_text()
for marker in (
    "EFayMetaHumanLiveLinkState::RecoveryBackoff",
    "EFayMetaHumanLiveLinkState::TerminalFailure",
    "OnLiveLinkStateChanged.Broadcast",
    "TWeakObjectPtr<AActor> ReviewedAvatar",
    "bAvatarMutationPermanentlyBlocked",
    "EFayMetaHumanLiveLinkFailure::AvatarUnavailable",
    "bool RetryLastAvatarConfiguration()",
):
    if marker not in speech_header and marker not in speech_source:
        reject(f"the sealed Live Link recovery contract is missing: {marker}")
if re.search(r"RetryLastAvatarConfiguration\s*\([^)]*[A-Za-z_]", speech_header):
    reject("Live Link recovery must remain parameterless and reject arbitrary avatars")
configure_start = speech_source.find(
    "bool UFayMetaHumanSpeechDriverComponent::ConfigureAvatar"
)
configure_end = speech_source.find(
    "bool UFayMetaHumanSpeechDriverComponent::TryConfigurePendingAvatar",
    configure_start,
)
configure_body = speech_source[configure_start:configure_end]
invalid_end = configure_body.find("if (bAvatarMutationPermanentlyBlocked)")
if configure_start < 0 or configure_end < 0 or invalid_end < 0:
    reject("the sealed ConfigureAvatar contract is missing")
elif "EnterTerminalFailure" in configure_body[:invalid_end]:
    reject("invalid ConfigureAvatar input must not change an existing valid state")
if "Degraded states do no Live Link polling" not in speech_source:
    reject("degraded Live Link states must return before heartbeat and health polling")
if "const bool bRestored = RestoreConfiguredAvatar();" not in speech_source:
    reject("runtime Live Link failure must record its single verified restore attempt")
for marker in (
    "if (!bAvatarMutationPermanentlyBlocked)",
    "if (bAvatarMutationPermanentlyBlocked)",
    "Bridge != nullptr && Bridge->HasPendingSpeechWork()",
    "without changing the current runtime state",
):
    if marker not in speech_source:
        reject(f"the fail-closed Live Link lifecycle is missing: {marker}")
configuring_tick = speech_source.find(
    "if (LiveLinkState == EFayMetaHumanLiveLinkState::Configuring)"
)
pending_budget = speech_source.find(
    "PendingConfigurationElapsedSeconds += SafeDeltaSeconds",
    configuring_tick,
)
speech_pause = speech_source.find(
    "Bridge != nullptr && Bridge->HasPendingSpeechWork()",
    configuring_tick,
)
if min(configuring_tick, pending_budget, speech_pause) < 0 or speech_pause > pending_budget:
    reject("speech work must pause the pending Live Link timeout before it advances")
if "Ada's" in speech_source or "Keeping Ada configured" in speech_source:
    reject("Live Link runtime diagnostics must remain character-neutral")
if "SpeechDriver->IsAvatarConfigured()" in game_mode_source:
    reject("GameMode must consume transition events instead of allocating exact-state polls")
for marker in (
    "{1.0, 2.0, 4.0, 8.0, 16.0}",
    "LiveLinkRecoveryHealthyResetSeconds = 10.0",
    "SpeechDriver->IsLiveLinkHealthyCached()",
    "SpeechDriver->GetConsecutiveLiveLinkHealthySeconds()",
    "Bridge->HasPendingSpeechWork()",
    "BodyMotion->CanEnterDormancy()",
    "SpeechDriver->RetryLastAvatarConfiguration()",
    "FaceMesh->SetMorphTarget(JawMorphTarget, 0.0f, false)",
):
    if marker not in game_mode_source:
        reject(f"the bounded Live Link recovery orchestrator is missing: {marker}")
handler_start = game_mode_source.find(
    "void AFayAvatarBootstrapGameMode::HandleLiveLinkStateChanged"
)
handler_end = game_mode_source.find(
    "void AFayAvatarBootstrapGameMode::TickLiveLinkRecovery",
    handler_start,
)
if handler_start < 0 or handler_end < 0:
    reject("GameMode Live Link transition handler is missing")
elif "LiveLinkRecoveryAttemptCount = 0" in game_mode_source[handler_start:handler_end]:
    reject("a transient Configured event must not reset the Live Link recovery episode")

for marker in (
    'TEXT("t.MaxFPS")',
    "ECVF_SetByCode",
    "SetWithCurrentPriority",
    "FrameRatePolicyAuditIntervalSeconds = 5.0",
    "TickFrameRatePolicy(DeltaSeconds);",
    "Verified project-owned FayGameUserSettings runtime policy.",
    "Enforced reviewed runtime frame cap at 30.00 FPS after GameUserSettings initialization.",
    "Reviewed runtime frame cap policy drifted",
):
    if marker not in game_mode_source:
        reject(f"the reviewed runtime frame-rate policy is missing: {marker}")
for marker in (
    "ApplyReviewedFrameRateLimit() const",
    "TickFrameRatePolicy(float DeltaSeconds)",
    "bFrameRatePolicyViolationLogged",
    "FrameRatePolicyAuditElapsedSeconds",
):
    if marker not in game_mode_header:
        reject(f"the reviewed frame-rate policy state is missing: {marker}")
begin_play_start = game_mode_source.find("void AFayAvatarBootstrapGameMode::BeginPlay()")
begin_play_end = game_mode_source.find(
    "void AFayAvatarBootstrapGameMode::EndPlay", begin_play_start
)
begin_play_body = game_mode_source[begin_play_start:begin_play_end]
initial_frame_cap = begin_play_body.find("ApplyReviewedFrameRateLimit()")
scene_only_parse = begin_play_body.find('TEXT("FaySceneOnly=")')
if min(begin_play_start, begin_play_end, initial_frame_cap, scene_only_parse) < 0:
    reject("BeginPlay is missing its reviewed frame-rate initialization contract")
elif initial_frame_cap > scene_only_parse:
    reject("the frame-rate cap must be enforced before the scene-only early return")
for forbidden in ("SetFrameRateLimit(", "ApplySettings(", "SaveSettings("):
    if forbidden in game_mode_source:
        reject(f"GameMode must not persist or apply user settings: {forbidden}")
for marker in (
    "class FAYAVATARRUNTIME_API UFayGameUserSettings final",
    "virtual void SetToDefaults() override",
    "virtual float GetEffectiveFrameRateLimit() override",
):
    if marker not in game_user_settings_header:
        reject(f"the project-owned GameUserSettings contract is missing: {marker}")
for marker in (
    "ReviewedFrameRateLimit = 30.0f",
    "SetFrameRateLimit(ReviewedFrameRateLimit)",
    "return ReviewedFrameRateLimit",
):
    if marker not in game_user_settings_source:
        reject(f"the project-owned GameUserSettings policy is missing: {marker}")

engine_config = Path("Project/FayAvatarRuntime/Config/DefaultEngine.ini").read_text()
if len(re.findall(r"(?m)^bUseFixedFrameRate=False$", engine_config)) != 1:
    reject("DefaultEngine.ini must disable fixed-frame-rate simulation exactly once")
if len(re.findall(r"(?m)^t[.]MaxFPS=30$", engine_config)) != 1:
    reject("DefaultEngine.ini must define the reviewed 30 FPS early-boot cap exactly once")
if len(re.findall(
    r"(?m)^GameUserSettingsClassName=/Script/FayAvatarRuntime[.]FayGameUserSettings$",
    engine_config,
)) != 1:
    reject("DefaultEngine.ini must select the project-owned GameUserSettings class")
game_user_settings_config = Path(
    "Project/FayAvatarRuntime/Config/DefaultGameUserSettings.ini"
).read_text()
if len(re.findall(r"(?m)^FrameRateLimit=30[.]000000$", game_user_settings_config)) != 1:
    reject("DefaultGameUserSettings.ini must define the reviewed 30 FPS default")
if len(re.findall(r"(?m)^Version=5$", game_user_settings_config)) != 1:
    reject("DefaultGameUserSettings.ini must carry Unreal's current settings version")

game_config_path = Path("Project/FayAvatarRuntime/Config/DefaultGame.ini")
game_config = game_config_path.read_text()
always_cook_paths = re.findall(
    r'^\+DirectoriesToAlwaysCook=\(Path="([^"]+)"\)$',
    game_config,
    flags=re.MULTILINE,
)
if always_cook_paths:
    reject("DefaultGame.ini must not hard-code character cook paths")
profile_check = subprocess.run(
    (
        sys.executable,
        "scripts/character-profiles.py",
        "--config",
        str(game_config_path),
        "validate",
    ),
    check=False,
    text=True,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
)
if profile_check.returncode != 0:
    reject(
        "DefaultGame.ini character profiles failed validation: "
        + profile_check.stderr.strip()
    )
if re.search(
    r"(?im)^(?:\+)?(?:DirectoriesToAlwaysStageAsNonUFS|"
    r"DirectoriesToAlwaysStageAsUFS|AdditionalAssetDirectoriesToCook|"
    r"AdditionalNonAssetDirectoriesToCopy|AdditionalNonAssetDirectoriesToPackage)\s*=",
    game_config,
):
    reject("DefaultGame.ini must not stage or copy arbitrary non-asset directories")

ignore_probes = (
    "Project/FayAvatarRuntime/Content/FayMetaHumans/Built/AdaFay/BP_AdaFay.uasset",
    "Project/FayAvatarRuntime/Content/AnyProjectAsset.uasset",
    "Project/FayAvatarRuntime/Plugins/FayMetaHumanRuntime/Content/Model.uasset",
    "secrets-private/hf-ardy-device/token",
    "models-private/.hf-text-encoder-cache/hub/model.safetensors",
    "models-private/ardy/embeddings/idle.npz",
)
for probe in ignore_probes:
    ignored = subprocess.run(
        ("git", "check-ignore", "--quiet", "--no-index", probe),
        check=False,
    ).returncode == 0
    if not ignored:
        reject(f".gitignore must exclude generated/licensed content: {probe}")
env_example_ignored = subprocess.run(
    ("git", "check-ignore", "--quiet", "--no-index", ".env.example"),
    check=False,
).returncode == 0
if env_example_ignored:
    reject(".env.example must remain available for intentional placeholder configuration")

if errors:
    for error in errors:
        print(f"error: {error}", file=sys.stderr)
    raise SystemExit(1)
PY
fi

if [[ -n $python_bin ]] && ! "$python_bin" -m unittest \
    tools.tests.test_run_spark_avatar_gate; then
    fail 'guarded Spark avatar gate tests failed'
fi

if [[ -n $python_bin ]] && ! "$python_bin" -m unittest discover \
    -s services/ardy/tests -p 'test_*.py'; then
    fail 'ARDY service tests failed'
fi

if git grep --untracked -I -n -E '[[:blank:]]+$' -- .; then
    fail 'tracked or untracked source text contains trailing whitespace'
fi

git diff --check HEAD --

if (( failed != 0 )); then
    exit 1
fi

printf 'Repository source checks passed.\n'
