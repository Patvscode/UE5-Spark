from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


SERVICE_ROOT = Path(__file__).resolve().parents[1] / "service"
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(SERVICE_ROOT))

from embedding_contract import (  # noqa: E402
    APPROVED_EMBEDDING_BEHAVIORS,
    APPROVED_EMBEDDING_PROMPTS,
    ARDY_SOURCE_COMMIT,
    EMBEDDING_SCHEMA_VERSION,
)
from motion_catalog import (  # noqa: E402
    CATALOG_ID,
    GENERATED_BEHAVIORS,
    MOTION_CATALOG,
    MotionCatalogError,
    load_motion_catalog,
)
from pose_protocol import source_descriptor  # noqa: E402


EXPECTED_BEHAVIORS = (
    "idle",
    "listen",
    "explain",
    "wave",
    "jog_in_place",
    "run_in_place",
    "jumping_jacks",
    "stretch",
    "dance_relaxed",
)


class MotionCatalogTests(unittest.TestCase):
    def test_shared_catalog_is_complete_and_drives_embedding_contract(self) -> None:
        self.assertEqual(GENERATED_BEHAVIORS, EXPECTED_BEHAVIORS)
        self.assertEqual(APPROVED_EMBEDDING_BEHAVIORS, EXPECTED_BEHAVIORS)
        self.assertEqual(EMBEDDING_SCHEMA_VERSION, 2)
        self.assertEqual(source_descriptor()["revision"], ARDY_SOURCE_COMMIT)
        self.assertEqual(set(APPROVED_EMBEDDING_PROMPTS), set(EXPECTED_BEHAVIORS))
        self.assertEqual(MOTION_CATALOG["wave"]["routeBehavior"], "wave")
        self.assertIn("right hand", MOTION_CATALOG["wave"]["prompt"])

    def test_catalog_loader_fails_closed_on_identity_or_item_drift(self) -> None:
        source = REPOSITORY_ROOT / "config" / "motion-catalog.json"
        document = json.loads(source.read_text(encoding="utf-8"))
        self.assertEqual(document["catalogId"], CATALOG_ID)
        with tempfile.TemporaryDirectory() as directory:
            candidate = Path(directory) / "catalog.json"
            changed = dict(document)
            changed["catalogId"] = "unreviewed"
            candidate.write_text(json.dumps(changed), encoding="utf-8")
            with self.assertRaises(MotionCatalogError):
                load_motion_catalog(candidate)

            changed = json.loads(source.read_text(encoding="utf-8"))
            changed["items"]["wave"]["routeBehavior"] = "run_in_place"
            candidate.write_text(json.dumps(changed), encoding="utf-8")
            with self.assertRaises(MotionCatalogError):
                load_motion_catalog(candidate)

    def test_catalog_path_must_not_be_a_symlink(self) -> None:
        source = REPOSITORY_ROOT / "config" / "motion-catalog.json"
        with tempfile.TemporaryDirectory() as directory:
            linked = Path(directory) / "catalog.json"
            linked.symlink_to(source)
            with self.assertRaises(MotionCatalogError):
                load_motion_catalog(linked)

    def test_container_uses_shared_catalog_as_a_named_build_context(self) -> None:
        dockerfile = (REPOSITORY_ROOT / "services" / "ardy" / "Dockerfile").read_text(
            encoding="utf-8"
        )
        build_script = (
            REPOSITORY_ROOT / "scripts" / "build-ardy-container.sh"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "COPY --from=motion_config motion-catalog.json ",
            dockerfile,
        )
        self.assertIn('--build-context motion_config="$repository/config"', build_script)
        self.assertIn("--tag ue5-spark-ardy:0.3.0", build_script)


if __name__ == "__main__":
    unittest.main()
