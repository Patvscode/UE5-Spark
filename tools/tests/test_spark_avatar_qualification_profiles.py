from __future__ import annotations

import subprocess
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = {
    "capture": (
        REPO_ROOT / "scripts" / "capture-spark-avatar-window.sh",
        "character",
        "expected_camera_framing",
    ),
    "wrapper": (
        REPO_ROOT / "scripts" / "run-spark-avatar-soak.sh",
        "character",
        "camera_framing",
    ),
    "harness": (
        REPO_ROOT / "scripts" / "soak-spark-avatar.sh",
        "expected_character",
        "expected_camera_framing",
    ),
}
EXPECTED_ADAPTERS = {
    "Ada": "UE58MetaHuman",
    "Aoi": "UE58MetaHuman",
    "CasualGirl": "UE5EpicArkit",
}


def adapter_case(source: str, variable: str) -> str:
    start = source.index(f'case "${variable}" in')
    end = source.index("\nesac", start) + len("\nesac")
    return source[start:end]


def run_adapter_case(case_source: str, variable: str, character: str) -> subprocess.CompletedProcess[str]:
    harness = f"""
set -euo pipefail
fail() {{ printf 'error: %s\\n' "$*" >&2; exit 1; }}
{variable}=$1
{case_source}
printf '%s\\n' "$expected_adapter"
"""
    return subprocess.run(
        ("bash", "-c", harness, "qualification-profile-test", character),
        cwd=REPO_ROOT,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


class SparkAvatarQualificationProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.sources = {
            name: path.read_text(encoding="utf-8")
            for name, (path, _, _) in SCRIPTS.items()
        }

    def test_all_scripts_are_valid_bash(self) -> None:
        for name, (path, _, _) in SCRIPTS.items():
            with self.subTest(script=name):
                result = subprocess.run(
                    ("bash", "-n", str(path)),
                    cwd=REPO_ROOT,
                    check=False,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_exact_reviewed_ids_map_to_their_sealed_adapters(self) -> None:
        for script_name, (_, variable, _) in SCRIPTS.items():
            case_source = adapter_case(self.sources[script_name], variable)
            for character, adapter in EXPECTED_ADAPTERS.items():
                with self.subTest(script=script_name, character=character):
                    result = run_adapter_case(case_source, variable, character)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stdout, f"{adapter}\n")

    def test_near_match_and_injection_shaped_ids_fail_closed(self) -> None:
        malicious_ids = (
            "ada",
            "Ada ",
            "Ada/../../CasualGirl",
            "Aoi*",
            "CasualGirl;touch /tmp/unreviewed",
            "UE5EpicArkit",
        )
        for script_name, (_, variable, _) in SCRIPTS.items():
            case_source = adapter_case(self.sources[script_name], variable)
            for character in malicious_ids:
                with self.subTest(script=script_name, character=character):
                    result = run_adapter_case(case_source, variable, character)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(result.stdout, "")
                    self.assertIn("reviewed", result.stderr)

    def test_readiness_markers_use_the_mapped_adapter(self) -> None:
        for script_name, (_, _, framing_variable) in SCRIPTS.items():
            source = self.sources[script_name]
            with self.subTest(script=script_name):
                self.assertIn("adapter=$expected_adapter", source)
                self.assertNotIn(
                    "adapter=UE58MetaHuman, camera_framing=$", source
                )
                self.assertIn(f"camera_framing=${framing_variable}", source)


if __name__ == "__main__":
    unittest.main()
