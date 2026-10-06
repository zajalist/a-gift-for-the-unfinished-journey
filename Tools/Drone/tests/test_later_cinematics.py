"""Offline continuity and location gates for later drone camera alternatives."""
import copy
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import later_cinematics as later  # noqa: E402
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "Look"))
from apply_look import check_banned  # noqa: E402


class LaterCinematics(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source_15 = copy.deepcopy(later.cine.plan_cin15())
        cls.source_18 = copy.deepcopy(later.cine.plan_cin18())
        cls.source_later = {name: later.cine.PLANS[name]
                            for name in ("CIN_19_HATCH", "CIN_24_TRANSMISSION")}
        later.register()

    def test_only_camera_plan_overrides_are_registered(self):
        for name, source in self.source_later.items():
            self.assertIs(later.cine.PLANS[name], source)
        self.assertEqual(later.cine.plan_cin15(), self.source_15)
        self.assertEqual(later.cine.plan_cin18(), self.source_18)

    def test_cin15_crane_and_relay_preserve_middle_shot_and_window(self):
        p = later.plan_cin15()
        old = self.source_15
        self.assertEqual((p["asset"], p["duration"], p["road_m"], p["window_m"]),
                         (old["asset"], old["duration"], old["road_m"], old["window_m"]))
        self.assertEqual(p["cams"][1], old["cams"][4])
        self.assertEqual(p["shots"], [(0.0, 5.0, "CIN15_S1_DroneCrane"),
                                      (5.0, 8.0, "CIN15_S2_Long"),
                                      (8.0, 10.0, "CIN15_S3_DroneRelay")])
        self.assertTrue(all("POV" not in cam["name"] for cam in p["cams"]))
        self.assertEqual([key[0] for key in p["cams"][0]["keys"]], [0.0, 1.2, 2.4, 5.0])

    def test_cin18_feed_dropout_preserves_exterior_and_black(self):
        p = later.plan_cin18()
        old = self.source_18
        self.assertEqual((p["asset"], p["duration"], p["road_m"], p["window_m"], p["blend_out"]),
                         (old["asset"], old["duration"], old["road_m"], old["window_m"], old["blend_out"]))
        exterior = copy.deepcopy(p["cams"][2])
        old_exterior = copy.deepcopy(old["cams"][1])
        self.assertEqual(exterior, old_exterior)
        for key in exterior["keys"]:
            pos = key[1:4]
            for target in ("capsule", "carrier", "crown"):
                x, y = later.cine._frame_xy(exterior, pos, key[5], key[6], exterior["targets"][target])
                self.assertLess(abs(x), 0.95, target)
                self.assertLess(abs(y), 1.0, target)
        self.assertEqual(p["shots"], [(0.0, 1.5, "CIN18_S1_DroneLurch"),
                                      (1.5, 3.5, "CIN18_S2_DroneDropout"),
                                      (3.5, 28.0, "CIN18_S3_ExtShutdown")])
        self.assertEqual(p["note"], old["note"])
        self.assertTrue(all("POV" not in cam["name"] for cam in p["cams"][:2]))

    def test_strict_framing_landscape_and_every_stop(self):
        for name in later.NAMES:
            with self.subTest(name=name):
                self.assertEqual(later.cine.check(name, strict=True, quiet=True), 0)
                self.assertEqual(later.cine.terrain_check(name, quiet=True), 0)
                self.assertEqual(later.cine.window_check(name, quiet=True), 0)

    def test_emitted_editor_chunks_are_runnable_and_bridge_safe(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name in later.NAMES:
                with self.subTest(name=name):
                    out = Path(tmp) / name
                    self.assertEqual(later.cine.emit(name, out), 0)
                    chunks = sorted(out.glob("*.py"))
                    self.assertEqual(len(chunks), 7)
                    for chunk in chunks:
                        source = chunk.read_text(encoding="utf-8")
                        compile(source, str(chunk), "exec")
                        check_banned(source)


if __name__ == "__main__":
    unittest.main()
