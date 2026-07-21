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

for command_name in find grep; do
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

if ! find "$cook_root" -type f -size +0c -print -quit | grep -q .; then
    fail 'the LinuxArm64 cook contains no nonempty files'
fi

mapfile -t character_package_assets < <("${profile_prefix[@]}" package-assets)
(( ${#character_package_assets[@]} > 0 )) || \
    fail 'the character selection produced no package assets'
for character_package_asset in "${character_package_assets[@]}"; do
    mapfile -t cooked_character_assets < <(
        find "$cook_root" -type f -path "*/$character_package_asset" -print
    )
    if (( ${#cooked_character_assets[@]} != 1 )); then
        fail "expected exactly one cooked character asset $character_package_asset; found ${#cooked_character_assets[@]}"
    fi
    [[ -s ${cooked_character_assets[0]} ]] || \
        fail "the cooked character asset is empty: $character_package_asset"
done

mapfile -t streaming_models < <(
    find "$cook_root" -type f \
        -path '*/StreamingADA/Content/xsada_face_base_fp32_v2_0_0.uasset' \
        -print
)
if (( ${#streaming_models[@]} != 1 )); then
    fail "expected exactly one cooked StreamingADA v2 model; found ${#streaming_models[@]}"
fi
[[ -s ${streaming_models[0]} ]] || fail 'the cooked StreamingADA model is empty'

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
    fail "expected exactly one cooked Ada garment material function; found ${#garment_material_functions[@]}"
fi
[[ -s ${garment_material_functions[0]} ]] || \
    fail 'the cooked Ada garment material function is empty'

if find "$cook_root" -iname '*FayMetaHumanEditorTools*' -print -quit | grep -q .; then
    fail 'the Editor-only FayMetaHumanEditorTools plugin leaked into the cook'
fi

printf 'Loose LinuxArm64 cook verification passed.\n'
printf '  Reviewed character Blueprint(s): present (%s)\n' "${#character_package_assets[@]}"
printf '  StreamingADA v2 model: present\n'
printf '  MetaHuman common assets: present\n'
printf '  Ada garment material dependency: present\n'
printf '  Editor-only helper: absent\n'
