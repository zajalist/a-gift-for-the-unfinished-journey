"""Tests for Tools/Perf/parse_csvprofile.py against a hand-computed fixture.

    python -m pytest Tools/Perf/tests/test_parse_csvprofile.py

The fixture (fixtures/sample.csv) has 20 frames. Every stat column except FrameTime is
laid out sorted ascending with the outlier last, so the p50/p95 values below were
computed by hand (nearest-rank percentile: sort ascending, index = ceil(pct/100*n) - 1):

    n = 20 -> p50 index 9 (10th value), p95 index 18 (19th value, the one just before
    the trailing outlier).

FrameTime carries two deliberate hitches (55.2 ms, 60.5 ms) for the hitch count, and
Memory/GPU peaks on the last row (8420 MB) for vram_peak_mb.
"""
import csv
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import parse_csvprofile  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "sample.csv"


def test_summarize_matches_hand_computed_values():
    result = parse_csvprofile.summarize(FIXTURE)

    assert result["frame_count"] == 20
    assert result["gpu_ms_p50"] == 14
    assert result["gpu_ms_p95"] == 20
    assert result["game_ms_p95"] == 9
    assert result["render_ms_p95"] == 10
    assert result["hitches_over_50ms"] == 2
    assert result["vram_peak_mb"] == 8420

    passes = result["pass_ms_p95"]
    assert passes["GPU/BasePass"] == 2.8
    assert passes["GPU/ShadowDepths"] == 1.8
    assert passes["GPU/Lumen"] == 3.3
    assert passes["GPU/VolumetricCloud"] == 0.9
    assert passes["GPU/PostProcessing"] == 1.0


def test_percentile_is_nearest_rank_not_interpolated():
    # 4 values: p50 -> index ceil(2)-1=1 (the 2nd value); p95 -> index ceil(3.8)-1=3 (the last).
    assert parse_csvprofile._percentile([1, 2, 3, 4], 50) == 2
    assert parse_csvprofile._percentile([1, 2, 3, 4], 95) == 4


def test_missing_pass_column_is_simply_absent():
    # A capture without GPU/VolumetricCloud (e.g. clouds disabled for that preset) must
    # not crash and must not report a value for the pass that was never recorded.
    rows = [
        {"FrameTime": "12", "GameThreadTime": "6", "RenderThreadTime": "7",
         "GPUTime": "11", "GPU/BasePass": "2.0", "Memory/GPU": "7000"},
        {"FrameTime": "13", "GameThreadTime": "7", "RenderThreadTime": "8",
         "GPUTime": "12", "GPU/BasePass": "2.1", "Memory/GPU": "7100"},
    ]
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "partial.csv"
        with open(path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        result = parse_csvprofile.summarize(path)

    assert "GPU/VolumetricCloud" not in result["pass_ms_p95"]
    assert result["pass_ms_p95"]["GPU/BasePass"] == 2.1
    assert result["hitches_over_50ms"] == 0
    assert result["vram_peak_mb"] == 7100


def test_real_ue_csv_header_uses_local_gpu_memory_and_text_events():
    # Column names and the text event form match Saved/Profiling/CSV/Profile(20260928_000701).csv.
    rows = [
        {"EVENTS": "LS_Saskarta_Title##3.620629", "RHI/DrawCalls": "743",
         "GPUMem/LocalBudgetMB": "11175", "GPUMem/LocalUsedMB": "6979.8867",
         "FrameTime": "16.7", "GameThreadTime": "8", "RenderThreadTime": "9", "GPUTime": "7"},
        {"EVENTS": "", "RHI/DrawCalls": "780", "GPUMem/LocalBudgetMB": "11175",
         "GPUMem/LocalUsedMB": "7050.5", "FrameTime": "55.2", "GameThreadTime": "9",
         "RenderThreadTime": "10", "GPUTime": "8"},
    ]
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "ue.csv"
        with open(path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
            # Unreal appends a duplicate header and a metadata record after frames.
            writer.writeheader()
            fh.write("[HasHeaderRowAtEnd],1,[EventTimestamps],1\n")
        result = parse_csvprofile.summarize(path)
    assert result["vram_peak_mb"] == 7050.5
    assert result["hitches_over_50ms"] == 1


def test_missing_vram_column_is_unavailable():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "no_vram.csv"
        path.write_text("FrameTime,GPUTime\n16.7,7\n", encoding="utf-8")
        result = parse_csvprofile.summarize(path)
    assert result["vram_peak_mb"] is None


def test_empty_csv_raises():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "empty.csv"
        path.write_text("FrameTime,GameThreadTime,RenderThreadTime,GPUTime,Memory/GPU\n", encoding="utf-8")
        try:
            parse_csvprofile.summarize(path)
        except ValueError:
            pass
        else:
            raise AssertionError("summarize() should raise ValueError on a header-only CSV")
