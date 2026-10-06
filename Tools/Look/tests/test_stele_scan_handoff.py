"""Cross-check the opening-frame stele reading against the authored boot camera."""

import json
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def _bearing_delta_deg(origin, target, yaw):
    angle = math.degrees(math.atan2(target["y"] - origin[1], target["x"] - origin[0]))
    return (angle - yaw + 180) % 360 - 180


def test_teaching_post_is_in_opening_frame_and_repeat_is_not():
    story = json.loads((ROOT / "docs/story/story-events.json").read_text(encoding="utf-8"))
    data = json.loads((ROOT / "docs/story/inscriptions.json").read_text(encoding="utf-8"))
    boot = next(beat for beat in story["beats"] if beat["id"] == "B01_BOOT_HANDOVER")
    posts = {row["id"]: row for row in data["steles"] if row["id"].startswith("Stele_DockPost_")}
    origin = boot["world"]
    teaching = posts["Stele_DockPost_B"]
    repeat = posts["Stele_DockPost_A"]
    teaching_delta = _bearing_delta_deg(origin, teaching["world_cm_planned"], -160)
    repeat_delta = _bearing_delta_deg(origin, repeat["world_cm_planned"], -160)
    gate = data["tuning"]["dock_view_deg"]

    assert teaching["planned_read"] == "full" and teaching["wear"] < data["tuning"]["worn_wear"]
    assert repeat["planned_read"] == "match" and repeat["wear"] >= data["tuning"]["worn_wear"]
    assert teaching["side"] == "L" and repeat["side"] == "R"
    assert abs(teaching_delta) < 10 < gate < abs(repeat_delta)
    assert abs(repeat_delta) > 45  # outside the 90-degree opening view
