from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

try:
    import numpy as np
except ModuleNotFoundError:  # The macOS system Python used by source checks is minimal.
    np = None  # type: ignore[assignment]


SERVICE_ROOT = Path(__file__).resolve().parents[1] / "service"
sys.path.insert(0, str(SERVICE_ROOT))

from embedding_contract import APPROVED_EMBEDDING_BEHAVIORS  # noqa: E402
from providers import load_embedding_cache  # noqa: E402

if np is not None:
    from cache_embeddings import (  # noqa: E402
        EmbeddingCacheError,
        _encoded_arrays,
        generate_cache,
        verify_encoder_revisions,
    )


class EmbeddingSourceContractTests(unittest.TestCase):
    def test_generator_uses_the_pinned_upstream_import_path(self) -> None:
        source = (SERVICE_ROOT / "cache_embeddings.py").read_text(encoding="utf-8")
        self.assertIn("from ardy.model.load_model import load_text_encoder", source)
        self.assertNotIn("from ardy.model import load_text_encoder", source)


@unittest.skipIf(np is None, "numpy is unavailable in the source-check interpreter")
class FakeTensor:
    def __init__(self, values: np.ndarray) -> None:
        self.values = values

    def detach(self) -> "FakeTensor":
        return self

    def cpu(self) -> "FakeTensor":
        return self

    def float(self) -> "FakeTensor":
        return self

    def numpy(self) -> np.ndarray:
        return self.values


@unittest.skipIf(np is None, "numpy is unavailable in the source-check interpreter")
class FakeEncoder:
    def __init__(self, shape: tuple[int, ...] = (1, 1, 4096)) -> None:
        self.shape = shape

    def __call__(self, prompts: list[str]) -> tuple[FakeTensor, list[int]]:
        seed = sum(ord(character) for character in prompts[0]) % 97
        values = np.full(self.shape, seed / 97.0, dtype=np.float32)
        return FakeTensor(values), [1]


@unittest.skipIf(np is None, "numpy is unavailable in the source-check interpreter")
class EmbeddingCacheTests(unittest.TestCase):
    def test_encoder_envelope_is_exact(self) -> None:
        features, mask = _encoded_arrays(FakeEncoder(), "reviewed prompt")
        self.assertEqual(features.shape, (1, 4096))
        self.assertEqual(features.dtype, np.float32)
        self.assertEqual(mask.tolist(), [True])
        with self.assertRaises(EmbeddingCacheError):
            _encoded_arrays(FakeEncoder((1, 2, 4096)), "reviewed prompt")

    def test_cache_is_complete_sealed_and_not_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache = generate_cache(root, FakeEncoder(), "bfloat16")
            self.assertEqual(cache.name, "embeddings")
            manifest = json.loads((cache / "manifest.json").read_text())
            self.assertEqual(
                manifest["approvedBehaviors"], list(APPROVED_EMBEDDING_BEHAVIORS)
            )
            loaded = load_embedding_cache(cache, np)
            self.assertEqual(set(loaded), set(APPROVED_EMBEDDING_BEHAVIORS))
            with self.assertRaises(EmbeddingCacheError):
                generate_cache(root, FakeEncoder(), "bfloat16")

    def test_encoder_revisions_are_exact(self) -> None:
        from embedding_contract import ENCODER_REVISIONS

        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            for repository, revision in ENCODER_REVISIONS.items():
                repository_cache = cache / ("models--" + repository.replace("/", "--"))
                (repository_cache / "refs").mkdir(parents=True)
                (repository_cache / "refs" / "main").write_text(revision)
                (repository_cache / "snapshots" / revision).mkdir(parents=True)
            self.assertEqual(verify_encoder_revisions(cache), ENCODER_REVISIONS)
            first_repository = next(iter(ENCODER_REVISIONS))
            repository_cache = cache / (
                "models--" + first_repository.replace("/", "--")
            )
            (repository_cache / "refs" / "main").write_text("0" * 40)
            with self.assertRaises(EmbeddingCacheError):
                verify_encoder_revisions(cache)

    def test_tampered_embedding_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cache = generate_cache(Path(directory), FakeEncoder(), "bfloat16")
            with (cache / "idle.npz").open("ab") as stream:
                stream.write(b"tampered")
            with self.assertRaises(RuntimeError):
                load_embedding_cache(cache, np)


if __name__ == "__main__":
    unittest.main()
