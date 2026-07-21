#!/usr/bin/env python3
"""Generate the reviewed ARDY text embeddings into an atomic private cache."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
from typing import Any

import numpy as np

from embedding_contract import (
    APPROVED_EMBEDDING_BEHAVIORS,
    APPROVED_EMBEDDING_PROMPTS,
    ARDY_SOURCE_COMMIT,
    BASE_ENCODER_REPOSITORY,
    EMBEDDING_SCHEMA_VERSION,
    EMBEDDING_WIDTH,
    SUPERVISED_ENCODER_REPOSITORY,
    UPSTREAM_LLAMA_REPOSITORY,
    prompt_sha256,
)


class EmbeddingCacheError(RuntimeError):
    """Raised when generated data would violate the sealed cache contract."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _encoded_arrays(encoder: Any, prompt: str) -> tuple[np.ndarray, np.ndarray]:
    encoded, lengths = encoder([prompt])
    values = encoded.detach().cpu()
    if hasattr(values, "float"):
        values = values.float()
    features = np.asarray(values.numpy(), dtype=np.float32)
    if features.shape != (1, 1, EMBEDDING_WIDTH):
        raise EmbeddingCacheError(
            f"encoder returned {features.shape}; expected (1, 1, {EMBEDDING_WIDTH})"
        )
    if list(lengths) != [1]:
        raise EmbeddingCacheError(f"encoder returned invalid lengths: {lengths!r}")
    features = np.ascontiguousarray(features[0], dtype=np.float32)
    mask = np.ones((1,), dtype=np.bool_)
    if not np.isfinite(features).all():
        raise EmbeddingCacheError("encoder returned a non-finite value")
    return features, mask


def generate_cache(models_root: Path, encoder: Any, precision: str) -> Path:
    """Create a complete immutable-by-convention cache or fail without replacing one."""

    if models_root.is_symlink():
        raise EmbeddingCacheError("models root must not be a symlink")
    models_root = models_root.resolve(strict=True)
    if not models_root.is_dir():
        raise EmbeddingCacheError("models root must be a real directory")
    target = models_root / "embeddings"
    if target.exists() or target.is_symlink():
        raise EmbeddingCacheError("embedding cache already exists; refusing to overwrite it")

    staging = models_root / f".embeddings-staging-{os.getpid()}"
    if staging.exists() or staging.is_symlink():
        raise EmbeddingCacheError("private embedding staging path already exists")
    staging.mkdir(mode=0o700)
    manifest_entries: dict[str, dict[str, object]] = {}
    try:
        for behavior in APPROVED_EMBEDDING_BEHAVIORS:
            features, mask = _encoded_arrays(
                encoder, APPROVED_EMBEDDING_PROMPTS[behavior]
            )
            filename = f"{behavior}.npz"
            destination = staging / filename
            np.savez_compressed(
                destination,
                text_feat=features,
                text_pad_mask=mask,
            )
            destination.chmod(0o600)
            manifest_entries[behavior] = {
                "file": filename,
                "fileSha256": _sha256(destination),
                "promptSha256": prompt_sha256(behavior),
                "shape": [1, EMBEDDING_WIDTH],
            }

        manifest = {
            "schemaVersion": EMBEDDING_SCHEMA_VERSION,
            "ardySourceCommit": ARDY_SOURCE_COMMIT,
            "approvedBehaviors": list(APPROVED_EMBEDDING_BEHAVIORS),
            "encoder": {
                "baseRepository": BASE_ENCODER_REPOSITORY,
                "supervisedRepository": SUPERVISED_ENCODER_REPOSITORY,
                "upstreamRepository": UPSTREAM_LLAMA_REPOSITORY,
                "precision": precision,
                "outputDtype": "float32",
            },
            "embeddings": manifest_entries,
        }
        manifest_path = staging / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        manifest_path.chmod(0o600)
        os.rename(staging, target)
    except BaseException:
        if staging.is_dir() and not staging.is_symlink():
            shutil.rmtree(staging)
        raise
    return target


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--models-root", type=Path, default=Path("/models"))
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    parser.add_argument("--fp32", action="store_true")
    args = parser.parse_args()

    # The reviewed ARDY commit intentionally does not re-export this helper
    # from ardy.model; use its stable defining module just like upstream's
    # run_text_encoder_server.py.
    from ardy.model.load_model import load_text_encoder

    precision = "float32" if args.fp32 else "bfloat16"
    encoder = load_text_encoder(
        mode="local",
        fp32=args.fp32,
        device=args.device,
    )
    destination = generate_cache(args.models_root, encoder, precision)
    print(
        "generated reviewed ARDY embeddings: "
        + ", ".join(APPROVED_EMBEDDING_BEHAVIORS)
        + f" ({destination})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
