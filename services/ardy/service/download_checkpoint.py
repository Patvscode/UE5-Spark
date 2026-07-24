#!/usr/bin/env python3
"""Download an approved ARDY checkpoint without persisting its access token."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from huggingface_hub import snapshot_download


APPROVED_MODELS = {
    "ARDY-Core-RP-20FPS-Horizon40": "nvidia/ARDY-Core-RP-20FPS-Horizon40",
    "ARDY-Core-RP-20FPS-Horizon8": "nvidia/ARDY-Core-RP-20FPS-Horizon8",
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", choices=tuple(APPROVED_MODELS), required=True)
    parser.add_argument("--models-root", type=Path, default=Path("/models"))
    parser.add_argument("--token-file", type=Path, default=Path("/run/secrets/hf_token"))
    args = parser.parse_args()
    token_path = args.token_file.resolve(strict=True)
    if not token_path.is_file() or token_path.is_symlink():
        raise SystemExit("token file must be a regular read-only mount")
    token = token_path.read_text(encoding="utf-8").strip()
    if not token:
        raise SystemExit("token file is empty")
    models_root = args.models_root.resolve(strict=True)
    destination = models_root / args.model
    if destination.exists() and destination.is_symlink():
        raise SystemExit("model destination must not be a symlink")
    destination.mkdir(mode=0o700, parents=False, exist_ok=True)
    os.environ["HF_HOME"] = "/tmp/huggingface"
    snapshot_download(
        repo_id=APPROVED_MODELS[args.model],
        local_dir=destination,
        token=token,
    )
    print(f"downloaded approved checkpoint: {args.model}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
