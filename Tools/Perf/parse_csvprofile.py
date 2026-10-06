"""Parse an Unreal Engine CSV Profiler capture (`-csvprofile`) and summarize it against
the Saskarta performance budget (see docs/performance-budget.md and the P5 brief).

    python Tools/Perf/parse_csvprofile.py path/to/capture.csv

Expected columns (a real capture may carry many more; anything not recognised here is
ignored): `FrameTime`, `GameThreadTime`, `RenderThreadTime`, `GPUTime`,
`GPUMem/LocalUsedMB` (or older `Memory/GPU`), and
any number of `GPU/<PassName>` per-pass stats (`GPU/BasePass`, `GPU/ShadowDepths`,
`GPU/Lumen`, `GPU/VolumetricCloud`, `GPU/PostProcessing`, ...). Every value is one frame.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path

GPU_PASS_PREFIX = "GPU/"
GPU_TOTAL_COLUMN = "GPUTime"
HITCH_THRESHOLD_MS = 50.0


def _percentile(values, pct: float) -> float:
    """Nearest-rank percentile (no interpolation): sort ascending, take the value at
    index ceil(pct/100 * n) - 1, clamped to the array. Every returned value is therefore
    a real captured frame's value, never an interpolated one between two frames."""
    if not values:
        raise ValueError("no values to take a percentile of")
    ordered = sorted(values)
    n = len(ordered)
    idx = math.ceil(pct / 100.0 * n) - 1
    idx = max(0, min(n - 1, idx))
    return ordered[idx]


def _read_rows(csv_path):
    with open(csv_path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        fieldnames = reader.fieldnames or []
        rows = []
        for raw in reader:
            if raw.get("EVENTS") == "EVENTS" or (raw.get("EVENTS") or "").startswith("[HasHeaderRowAtEnd]"):
                break  # UE repeats the header and appends metadata after the last frame.
            row = {}
            for key, value in raw.items():
                if key is None or key == "EVENTS" or value in (None, ""):
                    continue
                row[key] = float(value)
            rows.append(row)
    return fieldnames, rows


def summarize(csv_path) -> dict:
    """Summarize one CSV Profiler capture.

    Returns a dict with:
      - `frame_count`
      - `gpu_ms_p50`, `gpu_ms_p95` (from `GPUTime`)
      - `game_ms_p95` (from `GameThreadTime`), `render_ms_p95` (from `RenderThreadTime`)
      - `hitches_over_50ms` (frames with `FrameTime` > 50 ms)
      - `vram_peak_mb` (max of `GPUMem/LocalUsedMB`, falling back to `Memory/GPU`;
        None when neither was recorded)
      - `pass_ms_p95`: a dict of every `GPU/*` pass column PRESENT in this capture,
        mapped to its p95 in ms. A pass a preset disabled (e.g. no VolumetricCloud
        column at all) is simply absent from the dict, not zero.
    """
    fieldnames, rows = _read_rows(csv_path)
    if not rows:
        raise ValueError(f"{csv_path}: no data rows")

    def column(name: str) -> list:
        return [row[name] for row in rows if name in row]

    frame_times = column("FrameTime")
    gpu_times = column(GPU_TOTAL_COLUMN)
    game_times = column("GameThreadTime")
    render_times = column("RenderThreadTime")
    vram = column("GPUMem/LocalUsedMB") or column("Memory/GPU")

    pass_ms_p95 = {}
    for name in fieldnames:
        if name and name.startswith(GPU_PASS_PREFIX) and name != GPU_TOTAL_COLUMN:
            values = column(name)
            if values:
                pass_ms_p95[name] = _percentile(values, 95)

    summary = {
        "frame_count": len(rows),
        "hitches_over_50ms": sum(1 for t in frame_times if t > HITCH_THRESHOLD_MS),
        "vram_peak_mb": max(vram) if vram else None,
        "pass_ms_p95": pass_ms_p95,
    }
    if gpu_times:
        summary["gpu_ms_p50"] = _percentile(gpu_times, 50)
        summary["gpu_ms_p95"] = _percentile(gpu_times, 95)
    if game_times:
        summary["game_ms_p95"] = _percentile(game_times, 95)
    if render_times:
        summary["render_ms_p95"] = _percentile(render_times, 95)
    return summary


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("csv_path", type=Path)
    args = parser.parse_args(argv)
    print(json.dumps(summarize(args.csv_path), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
