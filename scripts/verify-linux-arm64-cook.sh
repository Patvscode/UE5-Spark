#!/usr/bin/env bash
set -euo pipefail

usage() {
    printf 'Usage: %s /path/to/Saved/Cooked/LinuxArm64 --project /path/to/project.uproject --profile-tool /path/to/character-profiles.py [--character ID]...\n' "${0##*/}" >&2
}

fail() {
    printf 'error: %s\n' "$*" >&2
    exit 1
}

if (( $# < 5 )); then
    usage
    exit 64
fi

for command_name in find grep python3; do
    command -v "$command_name" >/dev/null 2>&1 || \
        fail "required command is missing: $command_name"
done

cook_input=$1
shift
project=
profile_tool=
characters=()
while (( $# > 0 )); do
    case $1 in
        --project)
            (( $# >= 2 )) || fail '--project requires a .uproject path'
            project=$2
            shift 2
            ;;
        --profile-tool)
            (( $# >= 2 )) || fail '--profile-tool requires an executable path'
            profile_tool=$2
            shift 2
            ;;
        --character)
            (( $# >= 2 )) || fail '--character requires a reviewed profile ID'
            characters+=("$2")
            shift 2
            ;;
        *)
            usage
            fail "unknown loose-cook verifier argument: $1"
            ;;
    esac
done
[[ -d $cook_input ]] || fail "LinuxArm64 cook directory does not exist: $cook_input"
cook_root=$(cd "$cook_input" && pwd -P)
[[ -f $project && -x $profile_tool ]] || \
    fail 'the project or character-profile helper is missing'
project=$(cd "$(dirname "$project")" && pwd -P)/$(basename "$project")
profile_config="$(dirname "$project")/Config/DefaultGame.ini"
profile_prefix=(python3 "$profile_tool" --config "$profile_config")
for character in "${characters[@]}"; do
    profile_prefix+=(--character "$character")
done
"${profile_prefix[@]}" validate >/dev/null

profile_json=$("${profile_prefix[@]}" json) || \
    fail 'the reviewed character helper could not describe the selected profiles'
profile_contract_rows=$(python3 -c '
import json
import re
import sys

try:
    profiles = json.load(sys.stdin)
except (UnicodeError, json.JSONDecodeError) as exc:
    raise SystemExit(f"invalid selected character profile JSON: {exc}")
if not isinstance(profiles, list) or not 1 <= len(profiles) <= 16:
    raise SystemExit("invalid selected character profile count")

identifier = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,31}$")
meta_actor = re.compile(
    r"^/Game/FayMetaHumans/Built/"
    r"(?P<directory>[A-Za-z][A-Za-z0-9_-]{0,63})/"
    r"(?P<blueprint>BP_[A-Za-z][A-Za-z0-9_-]{0,63})\."
    r"(?P=blueprint)_C$"
)
meta_package = re.compile(
    r"^FayAvatarRuntime/Content/FayMetaHumans/Built/"
    r"(?P<directory>[A-Za-z][A-Za-z0-9_-]{0,63})/"
    r"(?P<blueprint>BP_[A-Za-z][A-Za-z0-9_-]{0,63})\.uasset$"
)
casual_id = "CasualGirl"
casual_actor = (
    "/Game/FayFab/CasualGirl/Runtime/"
    "BP_CasualGirlFay.BP_CasualGirlFay_C"
)
casual_package = (
    "FayAvatarRuntime/Content/FayFab/CasualGirl/Runtime/"
    "BP_CasualGirlFay.uasset"
)
seen_ids = set()
seen_assets = set()
for profile in profiles:
    if not isinstance(profile, dict):
        raise SystemExit("invalid selected character profile")
    character_id = profile.get("id")
    adapter = profile.get("adapter")
    actor_class = profile.get("actor_class")
    package_asset = profile.get("package_asset")
    cook_directories = profile.get("cook_directories")
    if not isinstance(character_id, str) or identifier.fullmatch(character_id) is None:
        raise SystemExit("invalid selected character ID")
    if character_id in seen_ids:
        raise SystemExit("duplicate selected character ID")
    if not isinstance(cook_directories, list) or not all(
        isinstance(directory, str) for directory in cook_directories
    ):
        raise SystemExit("invalid selected character cook contract")
    if adapter == "UE58MetaHuman":
        actor_match = meta_actor.fullmatch(actor_class or "")
        package_match = meta_package.fullmatch(package_asset or "")
        if actor_match is None or package_match is None:
            raise SystemExit("unsafe selected UE58MetaHuman profile paths")
        if (
            actor_match.group("directory"),
            actor_match.group("blueprint"),
        ) != (
            package_match.group("directory"),
            package_match.group("blueprint"),
        ):
            raise SystemExit("cross-adapter or mismatched MetaHuman profile paths")
        if "/Game/FayMetaHumans/Common_UE58" not in cook_directories:
            raise SystemExit("UE58MetaHuman cook contract omits its common assets")
        if "/StreamingADA" not in cook_directories:
            raise SystemExit("UE58MetaHuman cook contract omits StreamingADA")
    elif adapter == "UE5EpicArkit":
        if character_id != casual_id:
            raise SystemExit("unreviewed UE5EpicArkit character ID")
        if actor_class != casual_actor or package_asset != casual_package:
            raise SystemExit("unsafe selected UE5EpicArkit profile paths")
        if "/Game/FayFab/CasualGirl" not in cook_directories:
            raise SystemExit("UE5EpicArkit cook contract omits the Casual Girl root")
        if "/StreamingADA" not in cook_directories:
            raise SystemExit(
                "the current reviewed UE5EpicArkit cook contract requires StreamingADA"
            )
    else:
        raise SystemExit("unsupported selected character adapter")
    if package_asset in seen_assets:
        raise SystemExit("duplicate selected character asset")
    seen_ids.add(character_id)
    seen_assets.add(package_asset)
    print(f"{character_id}\t{adapter}\t{package_asset}")
' <<<"$profile_json") || fail 'the selected character cook contract is unsafe'
mapfile -t profile_contracts <<<"$profile_contract_rows"
(( ${#profile_contracts[@]} > 0 )) || \
    fail 'the character selection produced no reviewed profile contracts'

if ! find "$cook_root" -type f -size +0c -print -quit | grep -q .; then
    fail 'the LinuxArm64 cook contains no nonempty files'
fi

requires_metahuman=0
requires_epic_arkit=0
requires_streaming_ada=0
character_asset_count=0
for profile_contract in "${profile_contracts[@]}"; do
    IFS=$'\t' read -r character_id adapter character_package_asset \
        <<<"$profile_contract"
    [[ -n $character_id && -n $adapter && -n $character_package_asset ]] || \
        fail 'the character profile helper produced an empty contract field'
    case $adapter in
        UE58MetaHuman)
            requires_metahuman=1
            requires_streaming_ada=1
            ;;
        UE5EpicArkit)
            requires_epic_arkit=1
            requires_streaming_ada=1
            ;;
        *)
            fail 'the character profile helper produced an unsupported adapter'
            ;;
    esac
    mapfile -t cooked_character_assets < <(
        find "$cook_root" -type f -path "*/$character_package_asset" -print
    )
    if (( ${#cooked_character_assets[@]} != 1 )); then
        fail "expected exactly one cooked character asset $character_package_asset; found ${#cooked_character_assets[@]}"
    fi
    [[ -s ${cooked_character_assets[0]} ]] || \
        fail "the cooked character asset is empty: $character_package_asset"
    character_asset_count=$((character_asset_count + 1))
done

if (( requires_streaming_ada == 1 )); then
    mapfile -t streaming_models < <(
        find "$cook_root" -type f \
            -path '*/StreamingADA/Content/xsada_face_base_fp32_v2_0_0.uasset' \
            -print
    )
    if (( ${#streaming_models[@]} != 1 )); then
        fail "the selected character adapter contract requires exactly one cooked StreamingADA v2 model; found ${#streaming_models[@]}"
    fi
    [[ -s ${streaming_models[0]} ]] || fail 'the cooked StreamingADA model is empty'
fi

if (( requires_metahuman == 1 )); then
    if ! find "$cook_root" -type f \
        -path '*/FayAvatarRuntime/Content/FayMetaHumans/Common_UE58/*' \
        -size +0c -print -quit | grep -q .; then
        fail 'the cooked MetaHuman common asset directory is missing or empty'
    fi

    mapfile -t garment_material_functions < <(
        find "$cook_root" -type f \
            -path '*/Engine/Plugins/Interchange/Assets/Content/Functions/MF_PhongToMetalRoughness.uasset' \
            -print
    )
    if (( ${#garment_material_functions[@]} != 1 )); then
        fail "expected exactly one cooked MetaHuman garment material function; found ${#garment_material_functions[@]}"
    fi
    [[ -s ${garment_material_functions[0]} ]] || \
        fail 'the cooked MetaHuman garment material function is empty'
fi

if (( requires_epic_arkit == 1 )); then
    if ! find "$cook_root" -type f \
        -path '*/FayAvatarRuntime/Content/FayFab/CasualGirl/*' \
        -size +0c -print -quit | grep -q .; then
        fail 'the cooked Casual Girl content root is missing or empty'
    fi
fi

if find "$cook_root" -iname '*FayMetaHumanEditorTools*' -print -quit | grep -q .; then
    fail 'the Editor-only FayMetaHumanEditorTools plugin leaked into the cook'
fi

printf 'Loose LinuxArm64 cook verification passed.\n'
printf '  Reviewed character Blueprint(s): present (%s)\n' "$character_asset_count"
if (( requires_streaming_ada == 1 )); then
    printf '  StreamingADA v2 model: present (required by selected adapter contract)\n'
fi
if (( requires_metahuman == 1 )); then
    printf '  MetaHuman common and garment dependencies: present\n'
fi
if (( requires_epic_arkit == 1 )); then
    printf '  Casual Girl content root and reviewed wrapper: present\n'
fi
printf '  Editor-only helper: absent\n'
