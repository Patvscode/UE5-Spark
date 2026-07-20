#!/usr/bin/env bash
set -euo pipefail

usage() {
    printf 'Usage: %s /path/to/Saved/Cooked/LinuxArm64\n' "${0##*/}" >&2
}

fail() {
    printf 'error: %s\n' "$*" >&2
    exit 1
}

if (( $# != 1 )); then
    usage
    exit 64
fi

for command_name in find grep; do
    command -v "$command_name" >/dev/null 2>&1 || \
        fail "required command is missing: $command_name"
done

cook_input=$1
[[ -d $cook_input ]] || fail "LinuxArm64 cook directory does not exist: $cook_input"
cook_root=$(cd "$cook_input" && pwd -P)

if ! find "$cook_root" -type f -size +0c -print -quit | grep -q .; then
    fail 'the LinuxArm64 cook contains no nonempty files'
fi

mapfile -t ada_assets < <(
    find "$cook_root" -type f \
        -path '*/FayAvatarRuntime/Content/FayMetaHumans/Built/AdaFay/BP_AdaFay.uasset' \
        -print
)
if (( ${#ada_assets[@]} != 1 )); then
    fail "expected exactly one cooked Ada Blueprint; found ${#ada_assets[@]}"
fi
[[ -s ${ada_assets[0]} ]] || fail 'the cooked Ada Blueprint is empty'

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

if find "$cook_root" -iname '*FayMetaHumanEditorTools*' -print -quit | grep -q .; then
    fail 'the Editor-only FayMetaHumanEditorTools plugin leaked into the cook'
fi

printf 'Loose LinuxArm64 cook verification passed.\n'
printf '  Ada Blueprint: present\n'
printf '  StreamingADA v2 model: present\n'
printf '  MetaHuman common assets: present\n'
printf '  Editor-only helper: absent\n'
