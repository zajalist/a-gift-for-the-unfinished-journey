"""Block until the editor is free: not in PIE, and quiet for a settle period.

PIE state comes from the editor log: PIE is running when the last "Creating play world
package" line comes after the last "Shutting down PIE" line. Agents run this before
any editor command so they never collide with the user's play-testing.

    python Tools/GameFlow/wait_for_editor.py [--timeout-min 20] [--settle-s 20]

Exit 0 when free, 1 on timeout (then stop and report instead of touching the editor).
"""
import argparse
import pathlib
import sys
import time

LOG = pathlib.Path(__file__).resolve().parents[2] / "Saved" / "Logs" / "saskartarad.log"
START = "Creating play world package"
STOP = "Shutting down PIE"


def pie_running():
    text = LOG.read_text(encoding="utf-8", errors="replace")
    return text.rfind(START) > text.rfind(STOP)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout-min", type=float, default=20.0)
    parser.add_argument("--settle-s", type=float, default=20.0)
    args = parser.parse_args()
    deadline = time.monotonic() + args.timeout_min * 60
    free_since = None
    announced = False
    while time.monotonic() < deadline:
        if pie_running():
            free_since = None
            if not announced:
                print("PIE is running; waiting for the user to stop playing...", flush=True)
                announced = True
        else:
            free_since = free_since or time.monotonic()
            if time.monotonic() - free_since >= args.settle_s:
                print("editor free", flush=True)
                return 0
        time.sleep(3)
    print(f"timeout: PIE still running after {args.timeout_min} min", flush=True)
    return 1


if __name__ == "__main__":
    sys.exit(main())
