#!/usr/bin/env bash
set -euo pipefail

case ${0##*/} in
    clang)
        variable_name=UE5_SPARK_NATIVE_CLANG
        compiler=${UE5_SPARK_NATIVE_CLANG:-}
        ;;
    clang++)
        variable_name=UE5_SPARK_NATIVE_CLANGXX
        compiler=${UE5_SPARK_NATIVE_CLANGXX:-}
        ;;
    *)
        printf 'error: native compiler wrapper must be invoked as clang or clang++\n' >&2
        exit 69
        ;;
esac

if [[ -z $compiler || ! -x $compiler ]]; then
    printf 'error: %s does not name an executable native compiler\n' "$variable_name" >&2
    exit 69
fi

exec "$compiler" "$@"
