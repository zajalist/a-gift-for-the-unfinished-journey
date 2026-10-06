"""Offline framing, terrain and handoff checks for the two natively staged drone scenes."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import drone_cinematics as drone  # noqa: E402


class DroneCinematics(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        drone.register()

    def test_camera_plans_are_visible_and_above_ground(self):
        for name in drone.NAMES:
            with self.subTest(name=name):
                self.assertEqual(drone.cine.check(name, strict=True, quiet=True), 0)
                self.assertEqual(drone.cine.terrain_check(name, quiet=True), 0)

    def test_native_staging_milestones(self):
        a = drone.plan_a1()
        b = drone.plan_b1()
        self.assertEqual((a["road_m"], b["road_m"]), (3700.0, 3770.0))
        self.assertEqual((a["duration"], b["duration"]), (9.0, 14.0))
        self.assertTrue(12.0 <= b["duration"] <= 15.0)
        # The carrier's own view (fall) and the native drone feed (arrival) stay the view targets.
        self.assertEqual((a["cams"], a["shots"], b["cams"], b["shots"]), ([], [], [], []))
        self.assertEqual(b["blend_out"], 0.0)
        fade_a = {k[0]: k[1] for k in a["fade"]["keys"]}
        self.assertEqual(fade_a[2.40], 1.0)             # black after the torn frames
        self.assertLess(drone.FALL_IMPACT_S, 2.30)       # impact lands before the torn signal
        boot = [k for k in b["fade"]["keys"] if 11.9 <= k[0] <= 12.3]
        self.assertTrue(any(k[1] == 1.0 for k in boot) and b["fade"]["keys"][-1][1] == 0.0)

    def test_story_sidecar_matches_plans(self):
        import json
        data = json.loads((drone.ROOT / "Tools/Drone/story_sidecar.json").read_text(encoding="utf-8"))
        b1 = data["cinematics"]["CIN_B1_DRONE"]
        self.assertEqual(b1["duration_s"], drone.plan_b1()["duration"])
        self.assertFalse(b1["stop_pawn"])               # the carrier keeps driving
        cues = {c["id"]: c["at_s"] for c in b1["cues"] if c["type"] == "SetMode"}
        self.assertLessEqual(cues["AuxSensors"], drone.ARRIVAL_BOOT_S)
        self.assertLess(cues["DroneCam"], b1["duration_s"])

    def test_fall_lens_stays_above_the_dirt_on_the_regraded_road(self):
        report = drone.fall_ground(3700.0)
        if report is None:
            self.skipTest("heightmap missing")
        self.assertGreater(report["lens_clearance_cm"], 5.0)
        for m in range(3450, 3951, 50):
            self.assertGreater(drone.fall_ground(float(m))["lens_clearance_cm"], 0.0)


if __name__ == "__main__":
    unittest.main()
