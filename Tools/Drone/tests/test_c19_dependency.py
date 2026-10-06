"""Offline gate for the existing human interior reveal after drone/C18 playback."""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "Tools/Cinematics"))
import build_cinematics as cine  # noqa: E402
import samyor_reveal as reveal  # noqa: E402


class HumanRevealDependency(unittest.TestCase):
    def test_c18_black_hands_to_c19_interior_before_clear(self):
        story = json.loads((ROOT / "docs/story/story-events.json").read_text(encoding="utf-8"))
        c18 = story["cinematics"]["CIN_18_COLLAPSE"]
        c19 = story["cinematics"]["CIN_19_HATCH"]
        plan = cine.plan_cin19()
        self.assertIn((9.0, "Cine_ShowBlack"),
                      [(cue["at_s"], cue.get("id")) for cue in c18["cues"]])
        self.assertEqual((c19["cues"][0]["at_s"], c19["cues"][0]["id"]),
                         (0.0, "Cine_ClearBlack"))
        self.assertEqual(c19["hand_back"], "Traveller")
        self.assertEqual((plan["asset"], plan["duration"], plan["shots"][0]),
                         ("LS_CIN_19_Hatch", 36.0, (0.0, 36.0, "CIN19_FP_Eye")))
        for t in (0.0, 4.8, 8.2):
            eye, _ = reveal.camera(t)
            self.assertLess(reveal.CAP_X[0], eye[0])
            self.assertLess(eye[0], reveal.CAP_X[1])
            self.assertLess(abs(eye[1]), reveal.CAP_Y)
            self.assertLess(reveal.G0 + reveal.CAP_FLOOR, eye[2])
            self.assertLess(eye[2], reveal.G0 + reveal.lid_under(eye[0]))
        self.assertEqual(plan["fade"]["keys"][0][:2], (0.0, 0.0))
        self.assertEqual(plan["fade"]["keys"][-1][:2], (11.9, 0.0))

    def test_interior_and_reveal_cameras_clear_landscape_and_stop_window(self):
        self.assertIsNotNone(cine.terrain(), "C19 must not pass without the terrain heightmap")
        self.assertEqual(cine.check("CIN_19_HATCH", strict=True, quiet=True), 0)
        self.assertEqual(cine.terrain_check("CIN_19_HATCH", quiet=True), 0)
        self.assertEqual(cine.window_check("CIN_19_HATCH", quiet=True), 0)


if __name__ == "__main__":
    unittest.main()
