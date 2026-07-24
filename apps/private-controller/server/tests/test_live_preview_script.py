from __future__ import annotations

import subprocess
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPT_PATH = REPO_ROOT / "scripts" / "run-avatar-live-preview.sh"


class LivePreviewScriptStaticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = SCRIPT_PATH.read_text(encoding="utf-8")

    def test_bash_syntax(self) -> None:
        result = subprocess.run(
            ("bash", "-n", str(SCRIPT_PATH)),
            cwd=REPO_ROOT,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_exact_window_and_private_output_contract(self) -> None:
        for marker in (
            "Linux/aarch64 DGX Spark",
            "EXPECTED_UNREAL_EXE is not the packaged FayAvatarRuntime binary",
            "LIVE_ROOT must be below the current user runtime directory",
            "LIVE_ROOT must have mode 0700",
            "_NET_WM_PID",
            "[[ $width == 1280 && $height == 720 ]]",
            "[[ $map_state == IsViewable ]]",
            '-window_id "$window_id"',
            "-draw_mouse 0",
            "-update 1 -atomic_writing 1",
            "-c:v mjpeg",
        ):
            self.assertIn(marker, self.source)

    def test_producer_is_bounded_and_opens_no_network_listener(self) -> None:
        for marker in (
            'process_matches_identity "$runtime_pid" "$runtime_starttime" "$expected_exe"',
            'process_matches_identity "$producer_pid" "$producer_starttime" "$ffmpeg_exe"',
            'kill -TERM "$producer_pid"',
            'kill -KILL "$producer_pid"',
        ):
            self.assertIn(marker, self.source)
        for forbidden in ("killall", "pkill", "docker stop", "podman stop", "-listen"):
            self.assertNotIn(forbidden, self.source)

    def test_ffmpeg_capability_probes_do_not_trip_pipefail(self) -> None:
        self.assertIn("grep -F atomic_writing >/dev/null", self.source)
        self.assertIn("+mjpeg[[:space:]]' >/dev/null", self.source)
        self.assertNotIn("grep -Fq atomic_writing", self.source)
        self.assertNotIn("grep -Eq '^[[:space:]]*V", self.source)


if __name__ == "__main__":
    unittest.main()
