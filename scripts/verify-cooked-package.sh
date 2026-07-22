#!/usr/bin/env bash
set -euo pipefail

usage() {
    printf 'Usage: %s /path/to/cooked/archive [--camera-framing Portrait|FullBody] [--unrealpak /path/to/UnrealPak] [--seal]\n' \
        "${0##*/}" >&2
    printf 'A package without an existing seal requires --unrealpak and --seal.\n' >&2
}

fail() {
    printf 'error: %s\n' "$*" >&2
    exit 1
}

if (( $# < 1 )); then
    usage
    exit 64
fi

archive_input=$1
shift
unrealpak=
write_seal=0
expected_camera_framing=Portrait
camera_framing_option_seen=0
while (( $# > 0 )); do
    case $1 in
        --camera-framing)
            (( $# >= 2 )) || fail '--camera-framing requires Portrait or FullBody'
            (( camera_framing_option_seen == 0 )) || \
                fail '--camera-framing may be specified only once'
            [[ $2 == Portrait || $2 == FullBody ]] || \
                fail '--camera-framing requires exact Portrait or FullBody'
            expected_camera_framing=$2
            camera_framing_option_seen=1
            shift 2
            ;;
        --unrealpak)
            (( $# >= 2 )) || fail '--unrealpak requires an executable path'
            [[ -z $unrealpak ]] || fail '--unrealpak may be specified only once'
            unrealpak=$2
            shift 2
            ;;
        --seal)
            (( write_seal == 0 )) || fail '--seal may be specified only once'
            write_seal=1
            shift
            ;;
        *)
            usage
            fail "unknown verifier argument: $1"
            ;;
    esac
done

[[ -d $archive_input ]] || fail "cooked archive does not exist: $archive_input"
if (( write_seal == 1 )) && [[ -z $unrealpak ]]; then
    fail '--seal requires --unrealpak so licensed content is inspected first'
fi

for command_name in chmod cut file find grep mktemp mv python3 rm sed sha256sum sort tr wc; do
    command -v "$command_name" >/dev/null 2>&1 || \
        fail "required command is missing: $command_name"
done

archive_root=$(cd "$archive_input" && pwd -P)
mapfile -t launchers < <(find "$archive_root" -type f -name 'FayAvatarRuntime-Arm64.sh' -print)
if [[ ${#launchers[@]} -ne 1 ]]; then
    fail "expected exactly one FayAvatarRuntime-Arm64.sh launcher; found ${#launchers[@]}"
fi

launcher=${launchers[0]}
package_root=$(cd "$(dirname "$launcher")" && pwd -P)
game_root="$package_root/FayAvatarRuntime"
engine_saved_root="$package_root/Engine/Saved"
game_binary="$game_root/Binaries/LinuxArm64/FayAvatarRuntime"
seal_file="$package_root/.ue5-spark-package.sha256"
character_manifest="$package_root/.ue5-spark-characters.json"
allow_legacy_portrait_manifest=$(( 1 - write_seal ))

character_manifest_rows() {
    if [[ ! -e $character_manifest ]]; then
        if (( allow_legacy_portrait_manifest == 1 )) && \
            [[ $expected_camera_framing == Portrait ]]; then
            printf 'Ada\tFayAvatarRuntime/Content/FayMetaHumans/Built/AdaFay/BP_AdaFay.uasset\n'
            return
        fi
        fail 'the packaged character manifest is missing; only sealed legacy Portrait packages may omit it'
    fi
    [[ -f $character_manifest && ! -L $character_manifest ]] || \
        fail 'the packaged character manifest must be a regular file'
    [[ $(wc -c <"$character_manifest") -le 65536 ]] || \
        fail 'the packaged character manifest is unexpectedly large'
    python3 - "$character_manifest" "$expected_camera_framing" \
        "$allow_legacy_portrait_manifest" <<'PY'
import json
import re
import sys
from pathlib import Path

path = Path(sys.argv[1])
expected_camera_framing = sys.argv[2]
allow_legacy_portrait = sys.argv[3] == "1"
if expected_camera_framing not in ("Portrait", "FullBody"):
    raise SystemExit("invalid expected camera framing")
try:
    payload = json.loads(path.read_text(encoding="utf-8"))
except (OSError, UnicodeError, json.JSONDecodeError) as exc:
    raise SystemExit(f"invalid character manifest: {exc}")
if not isinstance(payload, dict):
    raise SystemExit("invalid character manifest root")
schema = payload.get("schema")
if type(schema) is not int or schema not in (1, 2):
    raise SystemExit("unsupported character manifest schema")
if schema == 1:
    if not allow_legacy_portrait:
        raise SystemExit("legacy schema-1 manifests cannot be used to seal new packages")
    if expected_camera_framing != "Portrait":
        raise SystemExit("legacy schema-1 packages support only Portrait framing")
    if set(payload) != {"schema", "profileConfigSha256", "characters"}:
        raise SystemExit("invalid legacy character manifest keys")
else:
    if set(payload) != {
        "schema", "profileConfigSha256", "defaultCameraFraming", "characters"
    }:
        raise SystemExit("invalid character manifest keys")
    if payload["schema"] != 2:
        raise SystemExit("unsupported character manifest schema")
    if payload["defaultCameraFraming"] != "Portrait":
        raise SystemExit("unsupported default camera framing")
if not re.fullmatch(r"[0-9a-f]{64}", payload["profileConfigSha256"]):
    raise SystemExit("invalid character profile digest")
characters = payload["characters"]
if not isinstance(characters, list) or not 1 <= len(characters) <= 16:
    raise SystemExit("invalid character manifest count")
ids = set()
assets = set()
for character in characters:
    expected_character_keys = {"id", "adapter", "actorClass", "packageAsset"}
    if schema == 2:
        expected_character_keys.add("cameraFramings")
    if not isinstance(character, dict) or set(character) != expected_character_keys:
        raise SystemExit("invalid character manifest entry")
    character_id = character["id"]
    package_asset = character["packageAsset"]
    if not isinstance(character_id, str) or not re.fullmatch(
        r"[A-Za-z][A-Za-z0-9_-]{0,31}", character_id
    ):
        raise SystemExit("invalid character ID")
    if character_id in ids:
        raise SystemExit("duplicate character ID")
    if character["adapter"] != "UE58MetaHuman":
        raise SystemExit("unsupported packaged character adapter")
    if schema == 2:
        if character["cameraFramings"] != ["Portrait", "FullBody"]:
            raise SystemExit("unsupported packaged camera framing contract")
        if expected_camera_framing not in character["cameraFramings"]:
            raise SystemExit("requested camera framing is not sealed for the character")
    if not isinstance(character["actorClass"], str) or not character[
        "actorClass"
    ].startswith("/Game/FayMetaHumans/Built/"):
        raise SystemExit("unsafe packaged actor class")
    if not isinstance(package_asset, str) or not re.fullmatch(
        r"FayAvatarRuntime/Content/FayMetaHumans/Built/"
        r"[A-Za-z][A-Za-z0-9_-]{0,63}/"
        r"BP_[A-Za-z][A-Za-z0-9_-]{0,63}\.uasset",
        package_asset,
    ):
        raise SystemExit("unsafe packaged character asset")
    if package_asset in assets:
        raise SystemExit("duplicate packaged character asset")
    ids.add(character_id)
    assets.add(package_asset)
    print(f"{character_id}\t{package_asset}")
PY
}

verify_package_node_types() {
    if find "$package_root" -type l -print -quit | grep -q .; then
        fail 'the packaged Game contains a symlink; seals require self-contained regular files'
    fi
    if find "$package_root" ! -type d ! -type f -print -quit | grep -q .; then
        fail 'the packaged Game contains a non-file filesystem node'
    fi
}

verify_package_node_types
[[ -x $launcher ]] || fail 'the package launcher is not executable'
[[ -x $game_binary ]] || fail 'the packaged Game executable is missing or not executable'
if ! grep -q 'FayAvatarRuntime/Binaries/LinuxArm64/FayAvatarRuntime' "$launcher"; then
    fail 'the ARM64 launcher does not reference the expected staged executable'
fi

description=$(file -b "$game_binary")
if [[ $description != *"ELF 64-bit"* || $description != *"ARM aarch64"* ]]; then
    fail 'the packaged FayAvatarRuntime executable is not a Linux AArch64 ELF'
fi

mapfile -t pak_files < <(find "$game_root/Content/Paks" -type f -name '*.pak' -print 2>/dev/null)
mapfile -t iostore_files < <(
    find "$game_root/Content/Paks" -type f \
        \( -name '*.utoc' -o -name '*.ucas' \) -print 2>/dev/null
)
if (( ${#pak_files[@]} == 0 )); then
    fail 'the packaged Game contains no Pak content container'
fi
if (( ${#iostore_files[@]} != 0 )); then
    fail 'the guarded Spark package must be Pak-only, but IoStore containers were staged'
fi
for pak_file in "${pak_files[@]}"; do
    [[ -s $pak_file ]] || fail 'a cooked Pak container is empty'
done

mapfile -t ort_libraries < <(
    find "$package_root" -type f \
        ! -path "$game_root/Saved/*" \
        -name 'libonnxruntime.so*' -print
)
if (( ${#ort_libraries[@]} == 0 )); then
    fail 'the packaged ARM64 ONNX Runtime shared library is missing'
fi
arm64_ort_count=0
for ort_library in "${ort_libraries[@]}"; do
    ort_description=$(file -Lb "$ort_library")
    if [[ $ort_description == *"x86-64"* ]]; then
        fail 'an x86-64 ONNX Runtime library leaked into the ARM64 package'
    fi
    if [[ $ort_description == *"ELF 64-bit"* && $ort_description == *"ARM aarch64"* ]]; then
        arm64_ort_count=$((arm64_ort_count + 1))
    fi
done
(( arm64_ort_count > 0 )) || fail 'no packaged ONNX Runtime library is an AArch64 ELF'

if find "$package_root" -iname '*FayMetaHumanEditorTools*' -print -quit | grep -q .; then
    fail 'the Editor-only FayMetaHumanEditorTools plugin leaked into the package'
fi

temporary_listing=
temporary_errors=
temporary_seal=
cleanup() {
    [[ -z $temporary_listing ]] || rm -f -- "$temporary_listing"
    [[ -z $temporary_errors ]] || rm -f -- "$temporary_errors"
    [[ -z $temporary_seal ]] || rm -f -- "$temporary_seal"
}
trap cleanup EXIT HUP INT TERM

verify_deep_content() {
    [[ -n $unrealpak && -x $unrealpak ]] || \
        fail 'deep content verification requires an executable UnrealPak'

    [[ -z $temporary_listing ]] || rm -f -- "$temporary_listing"
    [[ -z $temporary_errors ]] || rm -f -- "$temporary_errors"
    temporary_listing=$(mktemp)
    temporary_errors=$(mktemp)
    : >"$temporary_listing"
    for pak_file in "${pak_files[@]}"; do
        if ! "$unrealpak" "$pak_file" -List \
            >>"$temporary_listing" 2>>"$temporary_errors"; then
            fail 'UnrealPak could not list a packaged content container'
        fi
    done

    local manifest_output
    manifest_output=$(character_manifest_rows) || \
        fail 'the packaged character manifest failed validation'
    local character_id package_asset
    while IFS=$'\t' read -r character_id package_asset; do
        [[ -n $character_id && -n $package_asset ]] || \
            fail 'the packaged character manifest produced an empty record'
        grep -Fq "$package_asset" "$temporary_listing" || \
            fail "the sealed package does not contain reviewed character $character_id"
    done <<<"$manifest_output"
    grep -Fq 'FayAvatarRuntime/Content/FayMetaHumans/Common_UE58/' \
        "$temporary_listing" || fail 'the sealed package does not contain the MetaHuman common assets'
    grep -Fq 'StreamingADA/Content/xsada_face_base_fp32_v2_0_0.uasset' \
        "$temporary_listing" || fail 'the sealed package does not contain the StreamingADA v2 model'
    grep -Fq 'Interchange/Assets/Content/Functions/MF_PhongToMetalRoughness.uasset' \
        "$temporary_listing" || fail 'the sealed package does not contain the reviewed garment material dependency'
    if grep -Fiq 'FayMetaHumanEditorTools' "$temporary_listing"; then
        fail 'the Editor-only FayMetaHumanEditorTools plugin leaked into packaged content'
    fi
}

verify_seal() {
    verify_package_node_types
    [[ -s $seal_file ]] || \
        fail 'the package has no deep-verification seal; create it with the guarded packager'

    local line_number=0
    local entry_count=0
    local line digest separator relative output actual component
    while IFS= read -r line || [[ -n $line ]]; do
        line_number=$((line_number + 1))
        if (( line_number == 1 )); then
            [[ $line == '# UE5-SPARK-PACKAGE-SEAL-V1' ]] || \
                fail 'the package verification seal has an unsupported schema'
            continue
        fi
        [[ -n $line ]] || fail 'the package verification seal contains a blank record'
        digest=${line:0:64}
        separator=${line:64:2}
        relative=${line:66}
        [[ $digest =~ ^[0-9a-f]{64}$ && $separator == '  ' && -n $relative ]] || \
            fail 'the package verification seal contains a malformed record'
        [[ $relative != /* && $relative != *'\'* ]] || \
            fail 'the package verification seal contains an unsafe path'
        IFS=/ read -r -a components <<< "$relative"
        for component in "${components[@]}"; do
            [[ -n $component && $component != . && $component != .. ]] || \
                fail 'the package verification seal contains an unsafe path component'
        done
        [[ -f $package_root/$relative && ! -L $package_root/$relative ]] || \
            fail 'a file recorded by the package verification seal is missing or replaced'
        output=$(sha256sum -- "$package_root/$relative")
        actual=${output%% *}
        [[ $actual == "$digest" ]] || fail 'a sealed package file changed after deep verification'
        entry_count=$((entry_count + 1))
    done <"$seal_file"

    (( entry_count > 0 )) || fail 'the package verification seal contains no file records'
    current_count=$(find "$package_root" -type f \
        ! -path "$seal_file" \
        ! -path "$game_root/Saved/*" \
        ! -path "$engine_saved_root/*" \
        -print | wc -l | tr -d ' ')
    [[ $current_count =~ ^[0-9]+$ && $current_count -eq $entry_count ]] || \
        fail 'the package file set changed after deep verification'
}

write_package_seal() {
    verify_package_node_types
    temporary_seal=$(mktemp "$package_root/.ue5-spark-package.sha256.tmp.XXXXXX")
    {
        printf '# UE5-SPARK-PACKAGE-SEAL-V1\n'
        while IFS= read -r -d '' packaged_file; do
            local relative=${packaged_file#"$package_root/"}
            [[ -n $relative && $relative != *'\'* && $relative != *$'\n'* ]] || \
                fail 'the package contains a filename that cannot be safely sealed'
            local output digest
            output=$(sha256sum -- "$packaged_file")
            digest=${output%% *}
            printf '%s  %s\n' "$digest" "$relative"
        done < <(
            find "$package_root" -type f \
                ! -path "$seal_file" \
                ! -path "$game_root/Saved/*" \
                ! -path "$engine_saved_root/*" \
                ! -name '.ue5-spark-package.sha256.tmp.*' \
                -print0 | sort -z
        )
    } >"$temporary_seal"
    chmod 0644 "$temporary_seal"
    mv -f -- "$temporary_seal" "$seal_file"
    temporary_seal=
}

if [[ -n $unrealpak ]]; then
    verify_deep_content
fi
if (( write_seal == 1 )); then
    write_package_seal
    # Re-list after sealing, then verify every recorded hash so a concurrent
    # container or file change cannot be blessed between inspection and exit.
    verify_deep_content
    verify_seal
else
    verify_seal
fi

printf 'Package verification passed.\n'
printf '  ARM64 Game executable: verified\n'
printf '  ARM64 ONNX Runtime: verified\n'
printf '  Content layout: Pak-only (IoStore disabled)\n'
manifest_summary=$(character_manifest_rows | cut -f1 | tr '\n' ',' | sed 's/,$//')
printf '  Character profile(s) and StreamingADA content: deep-verified and hash-sealed (%s)\n' \
    "$manifest_summary"
printf '  Garment material dependency: deep-verified\n'
printf '  Editor-only helper: absent\n'
printf '  Package files: unchanged since deep verification\n'
