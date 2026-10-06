"""Read-only editor check for the four isolated V7 review animations."""

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "Tools/GameFlow"))
import editor_gate  # noqa: E402

OWNER = "codex-saskarta-goal"
NAMES = [
    "A_Samyor_ReachLatch_SideSupportedV7_ReviewOnly_InlineV7",
    "A_Samyor_PushLid_SideSupportedV7_ReviewOnly_InlineV7",
    "A_Samyor_PullUp_SideSupportedV7_ReviewOnly_InlineV7",
    "A_Samyor_StaffStand_SideSupportedV7_ClearCarry_ReviewOnly_InlineV7",
]
FRAMES = [210, 195, 240, 255]


def main():
    token = editor_gate.mirrored_token(OWNER)
    if not token:
        raise RuntimeError("Read with the owned editor lease")
    for name, frames in zip(NAMES, FRAMES):
        path = f"/Game/SaskartaGaea/Characters/Traveller/Anims/{name}"
        script = f"""import unreal,json
an=unreal.load_asset({path!r});assert an
tracks=[str(n) for n in unreal.AnimationLibrary.get_animation_track_names(an)]
print('EXIT_READBACK '+json.dumps(dict(name={name!r},frames={frames},length=an.get_play_length(),track_count=len(tracks),unique_tracks=len(set(t.casefold() for t in tracks)),root_motion=an.get_editor_property('enable_root_motion')),separators=(',',':')))
"""
        result = editor_gate.hayba("python_run", {"script": script}, owner=OWNER, lease=token, timeout_s=30)
        if not result.get("ok") or result.get("stderr"):
            raise RuntimeError(f"Readback failed for {name}: {result}")
        line = next((line for line in result.get("stdout", "").splitlines() if line.startswith("EXIT_READBACK ")), None)
        if not line:
            raise RuntimeError(f"No readback line for {name}: {result}")
        data = json.loads(line.removeprefix("EXIT_READBACK "))
        if data["track_count"] != 68 or data["unique_tracks"] != 68 or abs(data["length"] - frames / 30) > 0.001 or data["root_motion"]:
            raise RuntimeError(f"Invalid review clip: {data}")
        print(json.dumps(data, separators=(",", ":")))


if __name__ == "__main__":
    main()
