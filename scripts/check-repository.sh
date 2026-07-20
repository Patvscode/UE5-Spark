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

while IFS= read -r -d '' path; do
    case "$path" in
        */Binaries/*|*/DerivedDataCache/*|*/Intermediate/*|*/Saved/*|*/StagedBuilds/*|\
        Engine/*|UnrealEngine/*|spark-engine/*|engine-patches/*|\
        */Content/MetaHumans/*|*/Content/MetaHumanCommon/*|*/Plugins/Marketplace/*|\
        *.pak|*.utoc|*.ucas|*.patch|*.key|*.pem|*.p12|*.pfx|.env|.env.*)
            fail "forbidden generated, licensed, or sensitive path is tracked: $path"
            ;;
    esac

    bytes=$(wc -c <"$path" | tr -d ' ')
    if (( bytes > 5242880 )); then
        fail "tracked file exceeds 5 MiB public-source limit: $path ($bytes bytes)"
    fi
done < <(git ls-files -z)

if git grep -I -n -E '(/Users/[^/[:space:]]+|/home/[^/[:space:]]+|BEGIN (RSA |OPENSSH |EC )?PRIVATE KEY|github_pat_[A-Za-z0-9_]+|gho_[A-Za-z0-9]+)' -- . \
    ':(exclude)scripts/check-repository.sh'; then
    fail 'tracked content contains a machine path, private key marker, or token-like value'
fi

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
    fail 'no runnable Python 3 interpreter is available for the smoke-test syntax check'
else
    "$python_bin" -c 'import ast, pathlib; ast.parse(pathlib.Path("tools/fay-avatar-smoke-test.py").read_text())'
    "$python_bin" -c 'import json, pathlib; [json.loads(pathlib.Path(p).read_text()) for p in ("Project/FayAvatarRuntime/FayAvatarRuntime.uproject", "Project/FayAvatarRuntime/Plugins/FayAvatarBridge/FayAvatarBridge.uplugin")]'
fi

if git grep -I -n -E '[[:blank:]]+$' -- .; then
    fail 'tracked text contains trailing whitespace'
fi

git diff --check

if (( failed != 0 )); then
    exit 1
fi

printf 'Repository source checks passed.\n'
