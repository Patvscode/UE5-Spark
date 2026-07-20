#!/usr/bin/env bash
set -euo pipefail

failed=0

fail() {
    printf 'FAIL: %s\n' "$*" >&2
    failed=1
}

if [[ "$(uname -s)" != "Linux" || "$(uname -m)" != "aarch64" ]]; then
    printf 'error: expected Linux/aarch64, found %s/%s\n' "$(uname -s)" "$(uname -m)" >&2
    exit 69
fi
printf 'Host architecture: Linux/aarch64\n'

if [[ ${EUID:-$(id -u)} -eq 0 ]]; then
    fail 'run packaged applications as a normal user, not root'
fi

if ! command -v nvidia-smi >/dev/null 2>&1; then
    fail 'nvidia-smi is unavailable'
elif ! nvidia-smi >/dev/null 2>&1; then
    fail 'nvidia-smi could not communicate with the NVIDIA driver'
else
    printf 'NVIDIA driver: available\n'
fi

if ! command -v vulkaninfo >/dev/null 2>&1; then
    fail 'vulkaninfo is unavailable; this script does not install it'
else
    vulkan_summary=$(vulkaninfo --summary 2>&1) || {
        printf '%s\n' "$vulkan_summary" >&2
        fail 'Vulkan enumeration failed'
        vulkan_summary=
    }

    if [[ -n "$vulkan_summary" ]]; then
        printf '%s\n' "$vulkan_summary" | sed -n '1,100p'
        if grep -Eqi 'llvmpipe|software rasterizer' <<<"$vulkan_summary"; then
            fail 'Vulkan selected a software renderer instead of NVIDIA'
        elif ! grep -Eqi 'NVIDIA|vendorID[[:space:]]*=[[:space:]]*0x10de' <<<"$vulkan_summary"; then
            fail 'Vulkan did not report an NVIDIA physical device'
        fi
    fi
fi

printf '\nMemory:\n'
free -h || true
printf '\nFilesystem containing this checkout:\n'
df -h . || true

if (( failed != 0 )); then
    exit 1
fi

printf '\nDGX Spark read-only preflight passed. No system settings were changed.\n'
