"""Run one editor build command and kill it the moment Play-in-Editor starts.

    python Tools/GameFlow/pie_guard.py <command ...>
    python Tools/GameFlow/pie_guard.py node Tools/GameFlow/bpgraph.mjs build --reset-graphs Tools/GameFlow/specs/WBP_Saskarta_Settings.graph.json

Why: pressing Play in the middle of a bpgraph / build_settings_ui build compiles the half-built
blueprint for PIE, and the build then keeps sending commands into it. On 2026-09-28 that left
WBP_Saskarta_Settings with 26 functions placed but never wired; the editor's autosave kept the
dirty package and "Restore Packages" put it back into Content (README_MenuInput.md, section 3).

What it does:
- refuses to start (exit 97) when the editor log says PIE is running now;
- starts the command in the project root and forwards its exit code;
- once a second, reads what the editor log gained since the start, and kills the command
  (exit 98) at the first PIE marker (MARKERS), printing what to do with the half-built asset.

It reads the editor log only (Saved/Logs/saskartarad.log, or EDITOR_LOG), so it needs no editor
connection and never touches the editor. Python 3.8+, no dependencies.
"""
import os
import pathlib
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[2]
LOG = pathlib.Path(os.environ.get("EDITOR_LOG", ROOT / "Saved" / "Logs" / "saskartarad.log"))
# Any of these after the start means Play was pressed (the first one is the earliest: PIE compiles
# the dirty blueprints before it creates the play world).
MARKERS = (
    "[PlayLevel] Compiling",
    "Creating play world package",
    "Play in editor total start",
    "Repeating last play command",
)
PIE_END = "Shutting down PIE"


def pie_running(text):
    start = max(text.rfind(m) for m in MARKERS)
    return start >= 0 and start > text.rfind(PIE_END)


def read_from(offset):
    """Text the log gained after offset, and the new offset (restarts at 0 if the log was rotated)."""
    try:
        size = LOG.stat().st_size
    except OSError:
        return "", offset
    if size < offset:
        offset = 0
    with LOG.open("rb") as f:
        f.seek(offset)
        data = f.read()
    return data.decode("utf-8", errors="replace"), offset + len(data)


def kill_tree(proc):
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
    else:
        proc.kill()


def main(argv):
    if not argv:
        print(__doc__)
        return 2
    whole = LOG.read_text(encoding="utf-8", errors="replace") if LOG.exists() else ""
    if pie_running(whole):
        print("PIE GUARD: the editor is in Play-in-Editor now. Stop PIE (and ask the user not to press Play), then rerun.")
        return 97
    offset = LOG.stat().st_size if LOG.exists() else 0
    started = time.strftime("%H:%M:%S")
    print(f"PIE GUARD: {started} running {' '.join(argv)} (watching {LOG} every 1 s)", flush=True)
    proc = subprocess.Popen(argv, cwd=str(ROOT))
    tail = ""
    while proc.poll() is None:
        time.sleep(1.0)
        new, offset = read_from(offset)
        # Keep a little of the previous chunk so a marker split across two reads is still seen.
        window = tail + new
        hit = next((m for m in MARKERS if m in window), None)
        if hit:
            kill_tree(proc)
            print(f"PIE GUARD: '{hit}' in the editor log at {time.strftime('%H:%M:%S')}: the build was KILLED (exit 98).")
            print("PIE GUARD: the asset in the editor is now half-built. Do NOT save it, and do not let autosave keep it:")
            print("  1. stop PIE; 2. File > Exit, 'Don't Save' for the asset (or reload it from disk);")
            print("  3. delete Saved/Autosaves/.../<asset>_Auto*.uasset; 4. decline 'Restore Packages' for it at the next launch;")
            print("  5. rerun the same command (with --reset-graphs it rebuilds from the start).")
            return 98
        tail = window[-200:]
    return proc.returncode


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
