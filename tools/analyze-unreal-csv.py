#!/usr/bin/env python3
"""Summarize frame timing from an Unreal CSVProfiler capture.

The percentile method is nearest rank: for percentile ``p`` and ``n`` samples,
sort the samples and select the one-based rank ``ceil(p * n)``.  This avoids
interpolation and makes the result deterministic for every input sample set.

Only the source content digest is emitted.  The source filename is deliberately
excluded so reports can be shared without disclosing a private capture path.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Sequence


FRAME_TIME_COLUMN = "FrameTime"
PERCENTILE_METHOD = "nearest-rank (ceil(p * n), 1-indexed)"
THIRTY_FPS_BUDGET_MS = 1000.0 / 30.0
DURATION_ABSOLUTE_TOLERANCE_MS = 5.0
DURATION_RELATIVE_TOLERANCE = 0.0001


class AnalysisError(ValueError):
    """The capture cannot produce a trustworthy frame-time summary."""


def non_negative_integer(value: str) -> int:
    """Parse one non-negative command-line row count."""

    try:
        parsed = int(value, 10)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be a non-negative integer") from error
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be a non-negative integer")
    return parsed


def positive_integer(value: str) -> int:
    """Parse one positive command-line sample count."""

    parsed = non_negative_integer(value)
    if parsed == 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def positive_float(value: str) -> float:
    """Parse one finite positive command-line limit."""

    try:
        parsed = float(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be a positive number") from error
    if not math.isfinite(parsed) or parsed <= 0.0:
        raise argparse.ArgumentTypeError("must be a positive number")
    return parsed


def source_sha256(path: Path) -> str:
    """Return the raw-file SHA-256 without loading the whole capture in memory."""

    digest = hashlib.sha256()
    try:
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as error:
        raise AnalysisError("could not read the source CSV") from error
    return digest.hexdigest()


def normalized_cells(row: Sequence[str]) -> list[str]:
    """Normalize header cells without altering numeric frame data."""

    return [cell.strip().lstrip("\ufeff") for cell in row]


def is_unreal_metadata_row(cells: Sequence[str]) -> bool:
    """Recognize CSVProfiler's bracketed metadata records."""

    return bool(cells) and cells[0].startswith("[") and cells[0].endswith("]")


def record_unreal_metadata(
    metadata: dict[str, list[str]], cells: Sequence[str]
) -> None:
    """Record bracketed CSVProfiler key/value fields without guessing groups."""

    for index, cell in enumerate(cells[:-1]):
        if cell.startswith("[") and cell.endswith("]"):
            key = cell[1:-1].strip().lower()
            if key:
                metadata.setdefault(key, []).append(cells[index + 1].strip())


def read_capture(path: Path) -> tuple[list[float], dict[str, list[str]], bool]:
    """Locate the real header and validate data plus UE's optional end header.

    CSVProfiler can discover additional stats after capture starts.  In that
    case its final header is the original header followed by the newly observed
    columns.  The original prefix, including ``FrameTime`` at the same index,
    must remain unchanged.
    """

    header_found = False
    header_cells: list[str] = []
    frame_time_index = -1
    trailing_header_found = False
    frame_times: list[float] = []
    metadata: dict[str, list[str]] = {}
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as source:
            reader = csv.reader(source, strict=True)
            for row_number, row in enumerate(reader, start=1):
                cells = normalized_cells(row)
                if not any(cells):
                    continue

                frame_time_columns = [
                    index for index, cell in enumerate(cells) if cell == FRAME_TIME_COLUMN
                ]
                if not header_found:
                    if is_unreal_metadata_row(cells):
                        record_unreal_metadata(metadata, cells)
                        continue
                    if not frame_time_columns:
                        continue
                    if len(frame_time_columns) != 1:
                        raise AnalysisError(
                            f"row {row_number} contains duplicate FrameTime columns"
                        )
                    header_found = True
                    header_cells = cells
                    frame_time_index = frame_time_columns[0]
                    continue

                if trailing_header_found:
                    if is_unreal_metadata_row(cells):
                        record_unreal_metadata(metadata, cells)
                        continue
                    raise AnalysisError(
                        f"row {row_number} contains non-metadata after the trailing header"
                    )
                if is_unreal_metadata_row(cells):
                    raise AnalysisError(
                        f"row {row_number} contains metadata before the trailing header"
                    )
                if frame_time_columns:
                    if not frame_times:
                        raise AnalysisError(
                            f"row {row_number} contains a trailing header before any frame data"
                        )
                    if (
                        len(frame_time_columns) != 1
                        or frame_time_columns[0] != frame_time_index
                        or len(cells) < len(header_cells)
                        or cells[: len(header_cells)] != header_cells
                    ):
                        raise AnalysisError(
                            f"row {row_number} contains an incompatible trailing header"
                        )
                    trailing_header_found = True
                    continue
                if frame_time_index >= len(row):
                    raise AnalysisError(
                        f"row {row_number} is missing its FrameTime value"
                    )
                raw_value = row[frame_time_index].strip()
                if not raw_value:
                    raise AnalysisError(
                        f"row {row_number} has an empty FrameTime value"
                    )
                try:
                    frame_time = float(raw_value)
                except ValueError as error:
                    raise AnalysisError(
                        f"row {row_number} has a malformed FrameTime value"
                    ) from error
                if not math.isfinite(frame_time):
                    raise AnalysisError(
                        f"row {row_number} has a non-finite FrameTime value"
                    )
                if frame_time <= 0.0:
                    raise AnalysisError(
                        f"row {row_number} has a non-positive FrameTime value"
                    )
                frame_times.append(frame_time)
    except (OSError, UnicodeError, csv.Error) as error:
        raise AnalysisError("could not parse the source as strict UTF-8 CSV") from error

    if not header_found:
        raise AnalysisError("the CSV has no real header containing FrameTime")
    if not frame_times:
        raise AnalysisError("the CSV contains no frame rows after its FrameTime header")
    return frame_times, metadata, trailing_header_found


def read_frame_times(path: Path) -> list[float]:
    """Return validated frame times for callers that do not need metadata."""

    frame_times, _, _ = read_capture(path)
    return frame_times


def nearest_rank(values: Sequence[float], percentile: float) -> float:
    """Return a nearest-rank percentile from a non-empty finite sample."""

    if not values:
        raise AnalysisError("a percentile requires at least one frame")
    if not 0.0 < percentile <= 1.0:
        raise ValueError("percentile must be greater than zero and at most one")
    ordered = sorted(values)
    rank = max(1, math.ceil(percentile * len(ordered)))
    return ordered[rank - 1]


def rounded(value: float) -> float:
    """Keep reports compact while retaining sub-microsecond millisecond precision."""

    return round(value, 6)


def analyze_csv(
    path: Path,
    trim_start: int = 0,
    trim_end: int = 0,
    min_used_frames: int = 1,
    expected_total_frames: int | None = None,
    min_average_fps: float | None = None,
    max_average_fps: float | None = None,
    max_p95_frame_time_ms: float | None = None,
    require_capture_duration: bool = False,
) -> dict[str, object]:
    """Validate and summarize one CSVProfiler capture."""

    if trim_start < 0 or trim_end < 0:
        raise AnalysisError("trim counts must be non-negative")
    if min_used_frames <= 0:
        raise AnalysisError("minimum used frames must be positive")
    if expected_total_frames is not None and expected_total_frames <= 0:
        raise AnalysisError("expected total frames must be positive")
    for label, limit in (
        ("minimum average FPS", min_average_fps),
        ("maximum average FPS", max_average_fps),
        ("maximum p95 frame time", max_p95_frame_time_ms),
    ):
        if limit is not None and (not math.isfinite(limit) or limit <= 0.0):
            raise AnalysisError(f"{label} must be finite and positive")
    if (
        min_average_fps is not None
        and max_average_fps is not None
        and min_average_fps > max_average_fps
    ):
        raise AnalysisError("minimum average FPS exceeds maximum average FPS")

    digest = source_sha256(path)
    all_frame_times, metadata, trailing_header_found = read_capture(path)
    total_frames = len(all_frame_times)
    if expected_total_frames is not None and total_frames != expected_total_frames:
        raise AnalysisError(
            f"capture has {total_frames} total frames; exactly "
            f"{expected_total_frames} were requested"
        )
    if trim_start + trim_end >= total_frames:
        raise AnalysisError("trim counts remove every available frame")

    stop = total_frames - trim_end if trim_end else total_frames
    used_frame_times = all_frame_times[trim_start:stop]
    used_frames = len(used_frame_times)
    if used_frames < min_used_frames:
        raise AnalysisError(
            f"capture has {used_frames} used frames; at least {min_used_frames} are required"
        )
    mean_frame_time = math.fsum(used_frame_times) / used_frames
    average_fps = 1000.0 / mean_frame_time
    p95_frame_time = nearest_rank(used_frame_times, 0.95)
    over_30_fps_budget = sum(
        value > THIRTY_FPS_BUDGET_MS for value in used_frame_times
    )
    over_50 = sum(value > 50.0 for value in used_frame_times)

    duration_values = metadata.get("captureduration", [])
    end_header_values = metadata.get("hasheaderrowatend", [])
    if require_capture_duration and (
        not trailing_header_found or end_header_values != ["1"]
    ):
        raise AnalysisError("a complete CSVProfiler end header is required")
    if len(duration_values) > 1:
        raise AnalysisError("CSV metadata contains duplicate capture durations")
    capture_duration_seconds: float | None = None
    duration_difference_ms: float | None = None
    summed_frame_time_ms = math.fsum(all_frame_times)
    if duration_values:
        try:
            capture_duration_seconds = float(duration_values[0])
        except ValueError as error:
            raise AnalysisError("CSV metadata has a malformed capture duration") from error
        if not math.isfinite(capture_duration_seconds) or capture_duration_seconds <= 0.0:
            raise AnalysisError("CSV metadata has an invalid capture duration")
        metadata_duration_ms = capture_duration_seconds * 1000.0
        duration_difference_ms = abs(summed_frame_time_ms - metadata_duration_ms)
        duration_tolerance_ms = max(
            DURATION_ABSOLUTE_TOLERANCE_MS,
            metadata_duration_ms * DURATION_RELATIVE_TOLERANCE,
        )
        if duration_difference_ms > duration_tolerance_ms:
            raise AnalysisError(
                "summed FrameTime does not match CSV capture-duration metadata"
            )
    elif require_capture_duration:
        raise AnalysisError("CSV capture-duration metadata is required")

    if min_average_fps is not None and average_fps < min_average_fps:
        raise AnalysisError(
            f"average FPS {average_fps:.6f} is below required {min_average_fps:.6f}"
        )
    if max_average_fps is not None and average_fps > max_average_fps:
        raise AnalysisError(
            f"average FPS {average_fps:.6f} exceeds allowed {max_average_fps:.6f}"
        )
    if (
        max_p95_frame_time_ms is not None
        and p95_frame_time > max_p95_frame_time_ms
    ):
        raise AnalysisError(
            f"p95 frame time {p95_frame_time:.6f} ms exceeds allowed "
            f"{max_p95_frame_time_ms:.6f} ms"
        )

    return {
        "schema_version": 1,
        "source_sha256": digest,
        "percentile_method": PERCENTILE_METHOD,
        "trim_start_rows": trim_start,
        "trim_end_rows": trim_end,
        "total_frames": total_frames,
        "used_frames": used_frames,
        "expected_total_frames": expected_total_frames,
        "capture_duration_seconds": (
            rounded(capture_duration_seconds)
            if capture_duration_seconds is not None
            else None
        ),
        "summed_frame_time_ms": rounded(summed_frame_time_ms),
        "duration_difference_ms": (
            rounded(duration_difference_ms)
            if duration_difference_ms is not None
            else None
        ),
        "mean_frame_time_ms": rounded(mean_frame_time),
        "average_fps": rounded(average_fps),
        "p95_frame_time_ms": rounded(p95_frame_time),
        "p99_frame_time_ms": rounded(nearest_rank(used_frame_times, 0.99)),
        "over_30_fps_budget": {
            "threshold_ms": rounded(THIRTY_FPS_BUDGET_MS),
            "count": over_30_fps_budget,
            "share": rounded(over_30_fps_budget / used_frames),
        },
        "over_50_ms": {
            "count": over_50,
            "share": rounded(over_50 / used_frames),
        },
    }


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, metavar="CSVPROFILER_FILE")
    parser.add_argument(
        "--trim-start",
        type=non_negative_integer,
        default=0,
        metavar="ROWS",
        help="discard this many parsed frame rows from the start (default: 0)",
    )
    parser.add_argument(
        "--trim-end",
        type=non_negative_integer,
        default=0,
        metavar="ROWS",
        help="discard this many parsed frame rows from the end (default: 0)",
    )
    parser.add_argument(
        "--min-used-frames",
        type=positive_integer,
        default=1,
        metavar="FRAMES",
        help="require at least this many frames after trimming (default: 1)",
    )
    parser.add_argument(
        "--expected-total-frames",
        type=positive_integer,
        metavar="FRAMES",
        help="require exactly this many parsed frame rows",
    )
    parser.add_argument(
        "--min-average-fps",
        type=positive_float,
        metavar="FPS",
        help="fail when the post-trim average FPS is lower",
    )
    parser.add_argument(
        "--max-average-fps",
        type=positive_float,
        metavar="FPS",
        help="fail when the post-trim average FPS is higher",
    )
    parser.add_argument(
        "--max-p95-frame-time-ms",
        type=positive_float,
        metavar="MILLISECONDS",
        help="fail when the post-trim p95 FrameTime is higher",
    )
    parser.add_argument(
        "--require-capture-duration",
        action="store_true",
        help="require duration metadata and verify it against summed FrameTime",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_argument_parser()
    args = parser.parse_args(argv)
    try:
        report = analyze_csv(
            args.source,
            args.trim_start,
            args.trim_end,
            args.min_used_frames,
            args.expected_total_frames,
            args.min_average_fps,
            args.max_average_fps,
            args.max_p95_frame_time_ms,
            args.require_capture_duration,
        )
    except AnalysisError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
