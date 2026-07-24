from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "analyze-unreal-csv.py"
SPEC = importlib.util.spec_from_file_location("analyze_unreal_csv", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("could not load analyze-unreal-csv.py")
ANALYZER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = ANALYZER
SPEC.loader.exec_module(ANALYZER)


class UnrealCsvAnalyzerTests(unittest.TestCase):
    def write_capture(self, directory: Path, content: str) -> Path:
        path = directory / "capture.csv"
        path.write_text(content, encoding="utf-8", newline="")
        return path

    def test_locates_header_trims_rows_and_reports_json(self) -> None:
        content = (
            "[Platform],Linux\n"
            "[CsvStatCounts],FrameTime,8\n"
            "Frame, FrameTime ,GPUFrameTime\n"
            "1,10,1\n"
            "2,20,2\n"
            "3,30,3\n"
            "4,33.33,4\n"
            "5,34,5\n"
            "6,50,6\n"
            "7,60,7\n"
            "8,100,8\n"
        )
        with tempfile.TemporaryDirectory() as temporary:
            path = self.write_capture(Path(temporary), content)
            stdout = io.StringIO()
            stderr = io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                status = ANALYZER.main(
                    [str(path), "--trim-start", "1", "--trim-end", "1"]
                )

        self.assertEqual(status, 0)
        self.assertEqual(stderr.getvalue(), "")
        report = json.loads(stdout.getvalue())
        self.assertEqual(
            report["source_sha256"], hashlib.sha256(content.encode("utf-8")).hexdigest()
        )
        self.assertNotIn("capture.csv", stdout.getvalue())
        self.assertEqual(report["total_frames"], 8)
        self.assertEqual(report["used_frames"], 6)
        self.assertEqual(report["trim_start_rows"], 1)
        self.assertEqual(report["trim_end_rows"], 1)
        self.assertAlmostEqual(report["mean_frame_time_ms"], 37.888333, places=6)
        self.assertAlmostEqual(report["average_fps"], 26.393349, places=6)
        self.assertEqual(report["p95_frame_time_ms"], 60.0)
        self.assertEqual(report["p99_frame_time_ms"], 60.0)
        self.assertEqual(
            report["over_30_fps_budget"],
            {"threshold_ms": 33.333333, "count": 3, "share": 0.5},
        )
        self.assertEqual(
            report["over_50_ms"], {"count": 1, "share": 0.166667}
        )

    def test_nearest_rank_percentiles_are_deterministic(self) -> None:
        values = [float(value) for value in range(1, 101)]
        self.assertEqual(ANALYZER.nearest_rank(values, 0.95), 95.0)
        self.assertEqual(ANALYZER.nearest_rank(values, 0.99), 99.0)
        self.assertEqual(
            ANALYZER.PERCENTILE_METHOD,
            "nearest-rank (ceil(p * n), 1-indexed)",
        )

    def test_rejects_bad_frame_time_values(self) -> None:
        bad_values = ("", "not-a-number", "nan", "inf", "0", "-0.01")
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            for index, value in enumerate(bad_values):
                with self.subTest(value=value):
                    path = directory / f"bad-{index}.csv"
                    path.write_text(
                        f"Frame,FrameTime\n1,{value}\n",
                        encoding="utf-8",
                        newline="",
                    )
                    with self.assertRaises(ANALYZER.AnalysisError):
                        ANALYZER.analyze_csv(path)

    def test_rejects_missing_value_repeated_header_and_malformed_csv(self) -> None:
        captures = (
            "Frame,FrameTime\n1\n",
            "Frame,FrameTime\n1,10\nFrame,FrameTime\nFrame,FrameTime\n",
            'Frame,FrameTime\n1,"unterminated\n',
        )
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            for index, content in enumerate(captures):
                with self.subTest(index=index):
                    path = directory / f"malformed-{index}.csv"
                    path.write_text(content, encoding="utf-8", newline="")
                    with self.assertRaises(ANALYZER.AnalysisError):
                        ANALYZER.analyze_csv(path)

    def test_accepts_one_identical_trailing_header_then_metadata(self) -> None:
        content = (
            "[Platform],Linux\n"
            "Frame, FrameTime ,GPUFrameTime\n"
            "1,10,1\n"
            "2,20,2\n"
            "Frame, FrameTime ,GPUFrameTime\n"
            "[HasHeaderRowAtEnd],1\n"
            "[CsvStatCounts],FrameTime,2\n"
        )
        with tempfile.TemporaryDirectory() as temporary:
            path = self.write_capture(Path(temporary), content)
            report = ANALYZER.analyze_csv(path)

        self.assertEqual(report["total_frames"], 2)
        self.assertEqual(report["used_frames"], 2)
        self.assertEqual(report["mean_frame_time_ms"], 15.0)

    def test_accepts_trailing_header_with_appended_dynamic_stats(self) -> None:
        content = (
            "Frame,FrameTime,GPUFrameTime\n"
            "1,10,1\n"
            "2,20,2,3,4\n"
            "Frame,FrameTime,GPUFrameTime,LateStat,LaterStat\n"
            "[HasHeaderRowAtEnd],1\n"
        )
        with tempfile.TemporaryDirectory() as temporary:
            path = self.write_capture(Path(temporary), content)
            report = ANALYZER.analyze_csv(path)

        self.assertEqual(report["total_frames"], 2)
        self.assertEqual(report["mean_frame_time_ms"], 15.0)

    def test_rejects_invalid_trailing_header_state(self) -> None:
        captures = (
            # A logical header is not an end header until frame data exists.
            "Frame,FrameTime\nFrame,FrameTime\n",
            # End headers must preserve the normalized initial header prefix.
            "Frame,FrameTime,GPU\n1,10,1\nOther,FrameTime,GPU\n",
            # FrameTime may not move when dynamic stats extend the end header.
            "Frame,FrameTime,GPU\n1,10,1\nFrame,GPU,FrameTime,LateStat\n",
            # A second end header is non-metadata after the accepted one.
            "Frame,FrameTime\n1,10\nFrame,FrameTime\nFrame,FrameTime\n",
            # Frame data may not resume after the end header.
            "Frame,FrameTime\n1,10\nFrame,FrameTime\n2,20\n",
            # Bracketed metadata may not terminate data without an end header.
            "Frame,FrameTime\n1,10\n[HasHeaderRowAtEnd],1\n",
        )
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            for index, content in enumerate(captures):
                with self.subTest(index=index):
                    path = directory / f"bad-trailing-{index}.csv"
                    path.write_text(content, encoding="utf-8", newline="")
                    with self.assertRaises(ANALYZER.AnalysisError):
                        ANALYZER.analyze_csv(path)

    def test_rejects_missing_header_and_trims_that_remove_every_frame(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            missing_header = self.write_capture(directory, "Frame,GPU\n1,10\n")
            with self.assertRaises(ANALYZER.AnalysisError):
                ANALYZER.analyze_csv(missing_header)

            valid = directory / "valid.csv"
            valid.write_text("FrameTime\n10\n20\n", encoding="utf-8", newline="")
            with self.assertRaises(ANALYZER.AnalysisError):
                ANALYZER.analyze_csv(valid, trim_start=1, trim_end=1)
            with self.assertRaises(ANALYZER.AnalysisError):
                ANALYZER.analyze_csv(valid, trim_start=-1)

    def test_acceptance_checks_fps_samples_p95_and_duration(self) -> None:
        content = (
            "Frame,FrameTime\n"
            "1,33.3\n"
            "2,33.4\n"
            "3,33.3\n"
            "4,33.4\n"
            "Frame,FrameTime\n"
            "[HasHeaderRowAtEnd],1,[captureduration],0.1334\n"
        )
        with tempfile.TemporaryDirectory() as temporary:
            path = self.write_capture(Path(temporary), content)
            report = ANALYZER.analyze_csv(
                path,
                min_used_frames=4,
                expected_total_frames=4,
                min_average_fps=29.0,
                max_average_fps=31.0,
                max_p95_frame_time_ms=40.0,
                require_capture_duration=True,
            )

        self.assertEqual(report["capture_duration_seconds"], 0.1334)
        self.assertEqual(report["summed_frame_time_ms"], 133.4)
        self.assertEqual(report["duration_difference_ms"], 0.0)
        self.assertAlmostEqual(report["average_fps"], 29.985007, places=6)

    def test_acceptance_rejects_uncapped_short_and_incomplete_captures(self) -> None:
        captures_and_arguments = (
            (
                "FrameTime\n5.8\n5.8\nFrameTime\n"
                "[captureduration],0.0116\n",
                {"max_average_fps": 31.0, "require_capture_duration": True},
            ),
            (
                "FrameTime\n33.3\nFrameTime\n[captureduration],0.0333\n",
                {"min_used_frames": 2, "require_capture_duration": True},
            ),
            (
                "FrameTime\n33.3\n33.3\nFrameTime\n"
                "[captureduration],1.0\n",
                {"require_capture_duration": True},
            ),
            (
                "FrameTime\n33.3\n33.3\nFrameTime\n",
                {"require_capture_duration": True},
            ),
            (
                "FrameTime\n33.3\n33.3\nFrameTime\n"
                "[HasHeaderRowAtEnd],1,[captureduration],0.0666\n",
                {"expected_total_frames": 3, "require_capture_duration": True},
            ),
            (
                "FrameTime\n33.3\n33.3\n33.3\n33.3\nFrameTime\n"
                "[HasHeaderRowAtEnd],1,[captureduration],0.1332\n",
                {"expected_total_frames": 3, "require_capture_duration": True},
            ),
        )
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            for index, (content, arguments) in enumerate(captures_and_arguments):
                with self.subTest(index=index):
                    path = directory / f"rejected-{index}.csv"
                    path.write_text(content, encoding="utf-8", newline="")
                    with self.assertRaises(ANALYZER.AnalysisError):
                        ANALYZER.analyze_csv(path, **arguments)


if __name__ == "__main__":
    unittest.main()
