"""Read-only ending log evidence extraction; never contacts the editor."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--log", default="Saved/Logs/saskartarad.log")
    parser.add_argument("--out", default="Saved/Verification/human_profile_analysis_20261001/ending_v12")
    args = parser.parse_args()
    out = Path(args.out).resolve()
    permitted = Path("Saved/Verification/human_profile_analysis_20261001/ending_v12").resolve()
    if out != permitted:
        raise SystemExit("Output must be the assigned ending_v12 evidence directory")
    out.mkdir(parents=True, exist_ok=True)
    raw = Path(args.log).read_bytes()  # one bounded snapshot of the growing log
    (out / "log_snapshot.log").write_bytes(raw)
    lines = raw.decode("utf-8", errors="replace").splitlines()
    pattern = re.compile(r"^\[(\d{4}\.\d{2}\.\d{2}-\d{2}\.\d{2}\.\d{2}:\d{3})\]\[\s*(\d+)\](.*)")
    records = []
    for number, line in enumerate(lines, 1):
        match = pattern.match(line)
        if match:
            stamp = datetime.strptime(match[1], "%Y.%m.%d-%H.%M.%S:%f").replace(tzinfo=timezone.utc)
            records.append({"line": number, "utc": stamp.isoformat(), "frame_mod1000": int(match[2]), "text": match[3]})
    begin = "2026-10-02T01:10:00+00:00"
    # Restrict the human run to its first BeginTearingDown; later PIE is separate.
    run = [r for r in records if r["utc"] >= begin]
    stop = next(r for r in run if "BeginTearingDown" in r["text"])
    ending = [r for r in run if r["utc"] <= stop["utc"]]
    compact = [r for r in ending if "Compacting FUObjectHashTables" in r["text"]]
    waits = [r for r in ending if "ready before playing" in r["text"]]
    commands = [r for r in ending if "Processing command:" in r["text"]]
    groups = []
    for record in ending:
        if not groups or groups[-1][-1]["frame_mod1000"] != record["frame_mod1000"]:
            groups.append([])
        groups[-1].append(record)
    bounds = []
    for group in groups:
        seconds = (datetime.fromisoformat(group[-1]["utc"]) - datetime.fromisoformat(group[0]["utc"])).total_seconds()
        if seconds >= 0.5 and len(group) > 1:
            bounds.append({"kind": "same_contiguous_logged_frame_span", "seconds": seconds,
                           "first": group[0], "last": group[-1], "not_exclusive_cpu_time": True})
    for left, right in zip(groups, groups[1:]):
        if (right[0]["frame_mod1000"] - left[-1]["frame_mod1000"]) % 1000 == 1:
            seconds = (datetime.fromisoformat(right[0]["utc"]) - datetime.fromisoformat(left[-1]["utc"])).total_seconds()
            if seconds >= 0.5:
                bounds.append({"kind": "adjacent_modulo_logged_frame_gap", "seconds": seconds,
                               "first": left[-1], "last": right[0], "frame_wrap_or_missing_logs_possible": True})
    timeout_rows = [r for r in run if "GPU timeout:" in r["text"]]
    summary = {
        "acquired_utc": datetime.now(timezone.utc).isoformat(),
        "source": str(Path(args.log).resolve()), "snapshot_bytes": len(raw),
        "snapshot_sha256": hashlib.sha256(raw).hexdigest(), "snapshot_line_count": len(lines),
        "human_run_start": begin, "human_run_teardown": stop,
        "ending_foreground_classification": "unknown: no contemporaneous host focus samples",
        "modulo_frame_warning": "Sparse modulo-1000 log IDs do not establish FPS, frame duration, or exclusive CPU costs.",
        "ending_records": len(ending), "hash_compaction_rows": compact, "hlod_ready_waits": waits,
        "observer_commands": commands, "bounded_logged_stall_candidates": bounds,
        "gpu_timeouts_separate_from_ending": timeout_rows,
        "ending_sync_sound_warnings": [r for r in ending if "sync load of" in r["text"]],
        "ending_flush_async_rows": [r for r in ending if "FlushAsyncLoading" in r["text"]],
        "ending_add_to_world_warning_rows": [r for r in ending if "AddToWorld" in r["text"]],
    }
    (out / "analysis.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    first = next(r["line"] for r in records if r["utc"] >= begin)
    (out / "log_extract.txt").write_text("\n".join(f"{i}: {line}" for i, line in enumerate(lines, 1) if i >= first) + "\n", encoding="utf-8")
    print(json.dumps({"snapshot_sha256": summary["snapshot_sha256"], "line_count": len(lines),
                      "ending_records": len(ending), "hash_compactions": len(compact), "hlod_waits": len(waits),
                      "gpu_timeouts": len(timeout_rows), "stall_candidates": bounds}, indent=2))


if __name__ == "__main__":
    main()
