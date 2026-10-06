"""Launch the Saskarta performance flythrough and report the result.

    python Tools/Perf/flythrough.py --preset High --res 2560x1440
    python Tools/Perf/flythrough.py --preset High --res 2560x1440 --dry-run   # print the command, don't run it

This runs `/Game/level/Saskarta_WP` standalone (`-game`, not PIE), possessed by
`BP_Saskarta_Flythrough` (see `Tools/GameFlow/specs/BP_Saskarta_Flythrough.json`), which
drives the camera the length of `RoadSpline` at 8 m/s, starts the CSV profiler at
distance 0 and stops it at the spline's end, then quits. `parse_csvprofile.summarize()`
turns the resulting CSV into `Saved/Perf/flythrough-<preset>-<n>.md`, a pass/fail row per
line of `docs/performance-budget.md`.

**This is the user's button, not an agent's.** The run holds the GPU for about 11
minutes (5.1 km of road at 8 m/s) — see the P5 brief's Global Constraints ("the user
presses these buttons, never an agent" / "every performance flythrough run"). Nothing in
this repo's automation calls `main()` unattended; it is invoked by a person from a shell.
"""
from __future__ import annotations

import argparse
import datetime
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
UPROJECT = ROOT / "saskartarad.uproject"
LEVEL = "/Game/level/Saskarta_WP"
SAVED_PERF = ROOT / "Saved" / "Perf"
CSV_PROFILE_DIR = ROOT / "Saved" / "Profiling" / "CSV"

# Standard UE scalability levels (Config/DefaultScalability.ini, Task P4): Low..Cinematic.
# High (level 2) is the 80 fps target preset (see the P5 brief's Global Constraints).
PRESETS = {"Low": 0, "Medium": 1, "High": 2, "Epic": 3, "Cinematic": 4}

DEFAULT_ENGINE_ROOT = Path("C:/Program Files/Epic Games/UE_5.8")

# Budget lines from the P5 brief's Global Constraints / docs/performance-budget.md.
# (report label, pass_ms_p95 key or None for the totals, budget ms)
BUDGET_ROWS = [
    ("Nanite geometry", "GPU/BasePass", 2.5),
    ("Foliage + shadows", "GPU/ShadowDepths", 3.0),
    ("VSM", "GPU/VSM", 1.5),
    ("Lumen", "GPU/Lumen", 3.0),
    ("Sky/fog/clouds", "GPU/VolumetricCloud", 1.0),
    ("Post", "GPU/PostProcessing", 1.0),
]
GPU_TOTAL_BUDGET_MS = 12.5  # 80 fps at 1440p, TSR/DLSS Quality, frame generation excluded
GAME_THREAD_BUDGET_MS = 8.0
RENDER_THREAD_BUDGET_MS = 10.0
VRAM_BUDGET_MB = 8.5 * 1024  # 8.5 GB
HITCH_BUDGET_MS = 50.0


def parse_resolution(res: str) -> tuple[int, int]:
    m = re.fullmatch(r"(\d+)x(\d+)", res)
    if not m:
        raise ValueError(f"--res must look like 2560x1440, got {res!r}")
    return int(m.group(1)), int(m.group(2))


def find_unreal_editor(engine_root: Path | None) -> Path:
    root = engine_root or DEFAULT_ENGINE_ROOT
    exe = root / "Engine" / "Binaries" / "Win64" / "UnrealEditor.exe"
    if not exe.exists():
        raise FileNotFoundError(
            f"UnrealEditor.exe not found at {exe}; pass --engine-root to point at the UE 5.8 install"
        )
    return exe


def build_command(exe: Path, preset: str, res_x: int, res_y: int) -> list:
    if preset not in PRESETS:
        raise ValueError(f"--preset must be one of {sorted(PRESETS)}, got {preset!r}")
    return [
        str(exe),
        str(UPROJECT),
        LEVEL,
        "-game",
        "-windowed",
        f"-ResX={res_x}",
        f"-ResY={res_y}",
        "-csvprofile",
        f"-ExecCmds=sg.overall {PRESETS[preset]}",
    ]


def newest_csv(since: datetime.datetime):
    """The CSV profiler writes under Saved/Profiling/CSV. Return the newest .csv written
    at or after `since`, or None if the run produced none (e.g. it crashed before the
    pawn ever called `csvprofile start`)."""
    if not CSV_PROFILE_DIR.exists():
        return None
    candidates = [p for p in CSV_PROFILE_DIR.rglob("*.csv") if datetime.datetime.fromtimestamp(p.stat().st_mtime) >= since]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def _budget_row(label: str, value, budget: float) -> str:
    if value is None:
        return f"| {label} | n/a | {budget:g} | SKIP |"
    status = "PASS" if value <= budget else "FAIL"
    return f"| {label} | {value:.2f} | {budget:g} | {status} |"


def build_report_text(preset: str, res_x: int, res_y: int, csv_path: Path, summary: dict) -> str:
    passes = summary.get("pass_ms_p95", {})
    lines = [
        f"# Flythrough report: {preset} @ {res_x}x{res_y}",
        "",
        f"CSV: `{csv_path}`",
        f"Frames: {summary.get('frame_count', 'n/a')}",
        "",
        "| Budget line | p95 ms | Budget ms | Pass |",
        "|---|---|---|---|",
    ]
    for label, key, budget in BUDGET_ROWS:
        lines.append(_budget_row(label, passes.get(key), budget))
    lines.append(_budget_row("GPU total (80 fps @ 1440p)", summary.get("gpu_ms_p95"), GPU_TOTAL_BUDGET_MS))
    lines.append(_budget_row("Game thread", summary.get("game_ms_p95"), GAME_THREAD_BUDGET_MS))
    lines.append(_budget_row("Render thread", summary.get("render_ms_p95"), RENDER_THREAD_BUDGET_MS))
    lines.append(_budget_row("VRAM peak (MB)", summary.get("vram_peak_mb"), VRAM_BUDGET_MB))
    hitches = summary.get("hitches_over_50ms")
    hitch_status = "PASS" if hitches == 0 else ("FAIL" if hitches is not None else "SKIP")
    lines.append(f"| Hitches > {HITCH_BUDGET_MS:g} ms | {hitches if hitches is not None else 'n/a'} | 0 | {hitch_status} |")
    return "\n".join(lines) + "\n"


def next_report_path(preset: str) -> Path:
    SAVED_PERF.mkdir(parents=True, exist_ok=True)
    n = 1
    while (SAVED_PERF / f"flythrough-{preset}-{n}.md").exists():
        n += 1
    return SAVED_PERF / f"flythrough-{preset}-{n}.md"


def run_and_report(exe: Path, preset: str, res_x: int, res_y: int) -> int:
    command = build_command(exe, preset, res_x, res_y)
    print("Launching (this holds the GPU for ~11 minutes: 5.1 km of road at 8 m/s):")
    print(subprocess.list2cmdline(command))

    started_at = datetime.datetime.now()
    result = subprocess.run(command, cwd=ROOT)
    if result.returncode != 0:
        print(f"UnrealEditor exited with code {result.returncode}", file=sys.stderr)
        return result.returncode

    csv_path = newest_csv(started_at)
    if csv_path is None:
        print(f"No CSV profile appeared under {CSV_PROFILE_DIR} after the run", file=sys.stderr)
        return 1

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import parse_csvprofile  # noqa: E402  (deferred: --dry-run stays free of this import)

    summary = parse_csvprofile.summarize(csv_path)
    report_path = next_report_path(preset)
    report_path.write_text(build_report_text(preset, res_x, res_y, csv_path, summary), encoding="utf-8")

    print(f"Report: {report_path}")
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--preset", required=True, choices=sorted(PRESETS))
    parser.add_argument("--res", required=True, help="WIDTHxHEIGHT, e.g. 2560x1440")
    parser.add_argument("--engine-root", type=Path, default=None,
                         help="UE 5.8 install root (default: C:/Program Files/Epic Games/UE_5.8)")
    parser.add_argument("--dry-run", action="store_true",
                         help="print the launch command and exit without running it")
    args = parser.parse_args(argv)

    res_x, res_y = parse_resolution(args.res)
    exe = find_unreal_editor(args.engine_root)
    command = build_command(exe, args.preset, res_x, res_y)

    if args.dry_run:
        print(subprocess.list2cmdline(command))
        return 0

    return run_and_report(exe, args.preset, res_x, res_y)


if __name__ == "__main__":
    raise SystemExit(main())
