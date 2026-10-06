"""Guarded installer for the four isolated supported-exit review clips.

Preflight is offline. Install needs an idle editor and the caller's existing
Hayba lease; it never edits the production CIN19 animation sections.
"""

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "Saved/Verification/ending_focus_20261001/side_exit_supported_v7"
RECEIPTS = BASE / "install_review_receipts"
OWNER = "codex-saskarta-goal"
sys.path.insert(0, str(ROOT / "Tools/GameFlow"))
import editor_gate  # noqa: E402

CLIPS = (
    ("early/inline", "A_Samyor_ReachLatch_SideSupportedV7_ReviewOnly_InlineV7"),
    ("early/inline", "A_Samyor_PushLid_SideSupportedV7_ReviewOnly_InlineV7"),
    ("early/inline", "A_Samyor_PullUp_SideSupportedV7_ReviewOnly_InlineV7"),
    ("tail_clear_carry/inline", "A_Samyor_StaffStand_SideSupportedV7_ClearCarry_ReviewOnly_InlineV7"),
)


def steps():
    for packet, clip in CLIPS:
        base = BASE / packet
        folder = base / clip
        manifest = json.loads((base / "manifest.json").read_text(encoding="utf-8"))
        ordered = [folder / "00_create.py", *sorted(folder.glob("10_keys_*.py")), folder / "90_save.py"]
        for path in ordered:
            key = str(path.relative_to(base)).replace("/", "\\")
            expected = manifest["files"].get(key)
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if digest != expected:
                raise RuntimeError(f"Packet hash mismatch: {path}: {digest} != {expected}")
            yield path, digest


def install(ordered, through):
    if editor_gate.pie_running():
        raise RuntimeError("PIE is running; stop the session before importing review clips")
    lease = editor_gate.mirrored_token(OWNER)
    if not lease:
        raise RuntimeError("Acquire the existing Hayba editor lease first")
    RECEIPTS.mkdir(parents=True, exist_ok=True)
    for index, (path, digest) in enumerate(ordered):
        if through is not None and index >= through:
            return
        receipt = RECEIPTS / f"{index:02d}_{path.parent.name}_{path.stem}.json"
        if receipt.exists():
            previous = json.loads(receipt.read_text(encoding="utf-8"))
            if previous.get("ok") is not True or previous.get("source_sha256") != digest:
                raise RuntimeError(f"Prior outcome uncertain: {receipt}")
            print(f"SKIP_VERIFIED {index + 1}/{len(ordered)} {path.parent.name}/{path.name}")
            continue
        result = editor_gate.hayba("python_run", {"script": path.read_text(encoding="utf-8")},
                                   owner=OWNER, lease=lease, timeout_s=30)
        output = result.get("stdout", "")
        if not result.get("ok") or result.get("stderr") or (path.name == "90_save.py" and "EXIT_SAVED " not in output):
            raise RuntimeError(f"Review clip packet uncertain/failed: {path}: {result}")
        receipt.write_text(json.dumps({"ok": True, "source_sha256": digest, "stdout": output}, indent=2), encoding="utf-8")
        print(f"INSTALLED {index + 1}/{len(ordered)} {path.parent.name}/{path.name}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("preflight", "install"))
    parser.add_argument("--through", type=int, help="stop before this zero-based packet index")
    args = parser.parse_args()
    ordered = list(steps())
    if len(ordered) != 38:
        raise RuntimeError(f"Expected 38 native packets, got {len(ordered)}")
    print(f"PREFLIGHT_OK {len(ordered)} packets across {len(CLIPS)} isolated review clips")
    if args.mode == "install":
        install(ordered, args.through)


if __name__ == "__main__":
    main()
