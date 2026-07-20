#!/usr/bin/env bash
set -euo pipefail

usage() {
    printf 'Usage: %s /path/to/project.uproject /path/to/LinuxArm64/ShaderCompileWorker\n' \
        "${0##*/}" >&2
    printf 'Creates a project-local ShaderCompileWorker link without changing the Engine.\n' >&2
}

fail() {
    printf 'error: %s\n' "$*" >&2
    exit 1
}

if [[ $# -ne 2 ]]; then
    usage
    exit 64
fi

if [[ "$(uname -s)" != "Linux" || "$(uname -m)" != "aarch64" ]]; then
    fail "the native worker adapter is only meaningful on Linux/aarch64"
fi

project_input=$1
worker_input=$2
[[ -f "$project_input" ]] || fail "project does not exist: $project_input"
[[ -x "$worker_input" ]] || fail "native ShaderCompileWorker is missing or not executable: $worker_input"
file "$worker_input" | grep -q 'ARM aarch64' || fail 'ShaderCompileWorker is not an AArch64 ELF'

project_dir=$(cd "$(dirname "$project_input")" && pwd -P)
worker_dir=$(cd "$(dirname "$worker_input")" && pwd -P)
native_worker="$worker_dir/$(basename "$worker_input")"
adapter_dir="$project_dir/Binaries/Linux"
adapter_path="$adapter_dir/ShaderCompileWorker"

if [[ -e "$adapter_path" || -L "$adapter_path" ]]; then
    if [[ -L "$adapter_path" && "$(readlink "$adapter_path")" == "$native_worker" ]]; then
        printf 'Native ShaderCompileWorker adapter is already configured: %s\n' "$adapter_path"
        exit 0
    fi
    fail "adapter path already exists; it was not changed: $adapter_path"
fi

mkdir -p "$adapter_dir"
ln -s "$native_worker" "$adapter_path"

printf 'Created project-local native worker adapter:\n'
printf '  %s -> %s\n' "$adapter_path" "$native_worker"
printf 'The x86-64 Editor checks the project path before its Engine worker.\n'
printf 'FEX should hand this AArch64 ELF directly to the Spark kernel.\n'
printf 'Treat the first cook as a protocol-compatibility test; the adapter is experimental.\n'
