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
    Path("scripts/character-profiles.py"),
    Path("scripts/cook-state.py"),
    Path("scripts/inspect-metahuman-runtime-contract.py"),
    Path("scripts/metahuman-preflight.py"),
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
    "FayMetaHumanEditorTools",
    "FayMetaHumanRuntime",
    "InterchangeAssets",
    "MetaHumanCharacter",
}
if len(project.get("Plugins", [])) != len(plugins) or set(plugins) != expected_project_plugins:
    reject(
        "FayAvatarRuntime.uproject plugin list must contain only the reviewed bridge, "
        "runtime, Editor helper, AnimationData, ControlRigSpline, InterchangeAssets, "
        "and MetaHumanCharacter entries"
    )

for plugin_name in (
    "ControlRigSpline",
    "FayAvatarBridge",
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
if '"FayMetaHumanRuntime"' not in main_build:
    reject("the Game module must depend on FayMetaHumanRuntime")
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

if git grep --untracked -I -n -E '[[:blank:]]+$' -- .; then
    fail 'tracked or untracked source text contains trailing whitespace'
fi

git diff --check HEAD --

if (( failed != 0 )); then
    exit 1
fi

printf 'Repository source checks passed.\n'
