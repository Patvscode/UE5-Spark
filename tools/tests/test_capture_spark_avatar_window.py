from __future__ import annotations

import subprocess
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "capture-spark-avatar-window.sh"


class CaptureSparkAvatarWindowStaticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = SCRIPT_PATH.read_text(encoding="utf-8")

    def test_bash_syntax_and_backwards_compatible_portrait_default(self) -> None:
        syntax = subprocess.run(
            ("bash", "-n", str(SCRIPT_PATH)),
            cwd=REPO_ROOT,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.assertEqual(syntax.returncode, 0, syntax.stderr)
        for marker in (
            "if (( $# < 6 || $# > 8 )); then",
            "capture_phase=${7:-speech}",
            "expected_camera_framing=${8:-Portrait}",
            "[speech|ardy-explain] [Portrait|FullBody]",
        ):
            self.assertIn(marker, self.source)

    def test_only_reviewed_camera_framing_ids_are_accepted(self) -> None:
        self.assertIn(
            "[[ $expected_camera_framing == Portrait || "
            "$expected_camera_framing == FullBody ]]",
            self.source,
        )
        self.assertIn(
            "camera framing must be the reviewed Portrait or FullBody preset",
            self.source,
        )

    def test_capture_readiness_requires_one_exact_camera_framing_marker(self) -> None:
        exact_marker = (
            'camera_framing_marker="Selected reviewed character profile '
            "'$character' (adapter=$expected_adapter, "
            'camera_framing=$expected_camera_framing)."'
        )
        self.assertIn(exact_marker, self.source)
        self.assertIn(
            'camera_framing_selected_count=$(grep -Fc "$camera_framing_marker"',
            self.source,
        )
        self.assertIn("if (( camera_framing_selected_count == 1 )) &&", self.source)
        self.assertNotIn(
            'grep -Fq "Selected reviewed character profile \'$character\'"',
            self.source,
        )

    def test_capture_metadata_records_reviewed_framing_evidence(self) -> None:
        self.assertIn(
            "printf 'camera_framing=%s\\n' \"$expected_camera_framing\"",
            self.source,
        )
        self.assertIn(
            "printf 'camera_framing_marker_count=%s\\n' "
            '"$camera_framing_selected_count"',
            self.source,
        )


if __name__ == "__main__":
    unittest.main()
