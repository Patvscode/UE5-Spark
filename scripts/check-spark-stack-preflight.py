#!/usr/bin/env python3
"""Fail closed before loading the project-owned heavy DGX Spark stack."""

from __future__ import annotations

import argparse
import platform
import re
import sys
from pathlib import Path


GIB_IN_KIB = 1024 * 1024
MEMINFO_PATH = Path("/proc/meminfo")


def parse_mem_available_kib(value: str) -> int:
    match = re.search(r"^MemAvailable:\s+([0-9]+)\s+kB$", value, re.MULTILINE)
    if match is None:
        raise ValueError("MemAvailable is missing from /proc/meminfo")
    return int(match.group(1))


def bounded_gib(value: str) -> int:
    try:
        amount = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("memory threshold must be an integer") from exc
    if not 1 <= amount <= 128:
        raise argparse.ArgumentTypeError("memory threshold must be between 1 and 128 GiB")
    return amount


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--minimum-available-gib", type=bounded_gib, default=20)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if sys.platform != "linux" or platform.machine() != "aarch64":
        print(
            "error: the managed companion stack may start only on Linux/aarch64 DGX Spark",
            file=sys.stderr,
        )
        return 1
    try:
        available_kib = parse_mem_available_kib(
            MEMINFO_PATH.read_text(encoding="utf-8")
        )
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"error: could not verify available unified memory: {exc}", file=sys.stderr)
        return 1
    required_kib = args.minimum_available_gib * GIB_IN_KIB
    if available_kib < required_kib:
        print(
            "error: companion startup was not attempted because only "
            f"{available_kib / GIB_IN_KIB:.1f} GiB is available; "
            f"{args.minimum_available_gib} GiB is required. Stop or unload another "
            "large model, then use Start companion again.",
            file=sys.stderr,
        )
        return 1
    print(
        f"DGX Spark preflight passed with {available_kib / GIB_IN_KIB:.1f} GiB available."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
