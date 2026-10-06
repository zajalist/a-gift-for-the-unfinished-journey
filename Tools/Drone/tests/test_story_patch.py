"""Execute emitted story patch chunks against fake Unreal assets, without the editor."""
import copy
import contextlib
import io
import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch as mock_patch

HERE = Path(__file__).resolve().parents[1]
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
import patch_story as story_patch  # noqa: E402


def plain(value):
    if isinstance(value, Asset):
        return {"asset": value.path}
    if isinstance(value, Struct):
        return {k: plain(v) for k, v in sorted(value.props.items())}
    if isinstance(value, list):
        return [plain(v) for v in value]
    if isinstance(value, dict):
        return {k: plain(v) for k, v in sorted(value.items())}
    return value


class Struct:
    def __init__(self, **props):
        self.props = props
        self.writes = 0

    def get_editor_property(self, name):
        return self.props[name]

    def set_editor_property(self, name, value):
        self.props[name] = value
        self.writes += 1

    def copy(self):
        return copy.deepcopy(self)

    def export_text(self):
        return json.dumps(plain(self), sort_keys=True)


class Asset(Struct):
    def __init__(self, path, **props):
        super().__init__(**props)
        self.path = path


class RoadPoint:
    def __init__(self, x, y):
        self.x, self.y = x, y

    def export_text(self):
        return f"(X={self.x},Y={self.y})"


def row(name, **props):
    return Struct(id=name, **props)


def fake_world(data, absent=(), shift=0.0):
    beats = [
        row("OTHER_BEAT", trigger=Struct(road_m=212.0, ue_distance_m=3020.0, one_shot=False),
            requires_tags=["Old"], excludes_tags=["Drone"], priority="Normal"),
        row("OA1_OPTICS_FAIL", trigger=Struct(road_m=3700.0, ue_distance_m=0.0, one_shot=False),
            requires_tags=["Old"], excludes_tags=[], priority="Normal"),
        row("OA2_OPTICS_BACK", trigger=Struct(road_m=4440.0), excludes_tags=["Drone"]),
        row("OB1_DRONE", trigger=Struct(road_m=4015.0, ue_distance_m=0.0, one_shot=False),
            requires_tags=[], excludes_tags=[], priority="Normal"),
        row("OB1_DRONE_SOLO", trigger=Struct(road_m=4015.0), excludes_tags=["AuxSensors"]),
    ]
    cines = [row("OTHER_CINE", duration_s=11.0, hand_back="CarrierPOV"),
             row("CIN_A1_OPTICS_FAIL", duration_s=8.0, hand_back="CarrierPOV"),
             row("CIN_B1_DRONE", duration_s=8.0, hand_back="CarrierPOV")]
    lines = [row("OTHER_LINE", english="Keep this line", sound=None, duration_s=1.0),
             row("CV_DRONE_02", english="old singular line", sound=None, duration_s=0.0)]
    road = [RoadPoint(3700.0, data["beats"]["OA1_OPTICS_FAIL"]["ue_distance_m"] + shift),
            RoadPoint(3770.0, data["beats"]["OB1_DRONE"]["ue_distance_m"] + shift)]
    story = Asset(data["asset"], beats=beats, cinematics=cines, lines=lines,
                  enabled_tags=["FirstLight", "Keeper"], glances=[row("KEEP_GLANCE", value=42)],
                  road_m_to_ue_m=road, gap_s=2.5, drive_lighting_road_progress=True)
    assets = {story.path: story}
    for cine in data["cinematics"].values():
        assets[cine["sequence"]] = Asset(cine["sequence"])
    for line in data["lines"].values():
        assets[line["sound"]] = Asset(line["sound"], duration=2.62)
    for path in absent:
        assets.pop(path, None)
    unreal = types.ModuleType("unreal")
    unreal.load_asset = lambda path: assets.get(path)
    unreal.Name = str
    unreal.Text = str
    unreal.SaskartaEventAction = Struct
    unreal.SaskartaActionType = types.SimpleNamespace(PLAY_CARRIER_LINE="PlayCarrierLine",
                                                      SET_MODE="SetMode", SHOW_CAPTION="ShowCaption")
    unreal.SaskartaSkipRule = types.SimpleNamespace(HOLD_AFTER_SEEN="HoldAfterSeen")
    unreal.SaskartaEventPriority = types.SimpleNamespace(CINEMATIC="Cinematic")
    saved = []
    unreal.EditorAssetLibrary = types.SimpleNamespace(save_loaded_asset=lambda asset, dirty: saved.append(asset) or True)
    return story, unreal, saved


def run_chunk(source, unreal):
    with mock_patch.dict(sys.modules, {"unreal": unreal}), contextlib.redirect_stdout(io.StringIO()):
        exec(compile(source, "emitted_story_chunk", "exec"), {})


class StoryPatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = story_patch.load_patch()
        cls.chunks = story_patch.chunks(cls.data)

    def test_apply_verify_preserve_unowned_rows_tags_and_idempotence(self):
        story, unreal, saved = fake_world(self.data)
        unowned_before = {field: [r.export_text() for r in story.props[field]
                                  if r.props["id"] not in self.data[field]]
                          for field in ("beats", "cinematics", "lines")}
        guard = (story.props["glances"][0].export_text(),
                 [p.export_text() for p in story.props["road_m_to_ue_m"]],
                 story.props["gap_s"], story.props["drive_lighting_road_progress"])
        run_chunk(self.chunks["10_apply.py"], unreal)
        run_chunk(self.chunks["20_verify.py"], unreal)
        first = story.export_text()
        run_chunk(self.chunks["10_apply.py"], unreal)
        run_chunk(self.chunks["20_verify.py"], unreal)
        self.assertEqual(story.export_text(), first)
        self.assertEqual(saved, [])
        for field in unowned_before:
            after = [r.export_text() for r in story.props[field]
                     if r.props["id"] not in self.data[field]]
            self.assertEqual(after, unowned_before[field])
        self.assertEqual(story.props["enabled_tags"], ["FirstLight", "Keeper", "AuxSensors", "Drone"])
        self.assertEqual(guard, (story.props["glances"][0].export_text(),
                                 [p.export_text() for p in story.props["road_m_to_ue_m"]],
                                 story.props["gap_s"], story.props["drive_lighting_road_progress"]))

    def test_missing_dependency_and_profile_mismatch_fail_before_mutation(self):
        for missing, shift in (([self.data["cinematics"]["CIN_B1_DRONE"]["sequence"]], 0.0),
                               ([self.data["lines"]["CV_DRONE_02"]["sound"]], 0.0),
                               ([], 2.0)):
            with self.subTest(missing=missing, shift=shift):
                story, unreal, saved = fake_world(self.data, missing, shift)
                before = story.export_text()
                with self.assertRaises(RuntimeError):
                    run_chunk(self.chunks["10_apply.py"], unreal)
                self.assertEqual(story.export_text(), before)
                self.assertEqual(story.writes, 0)
                self.assertEqual(saved, [])

    def test_mode_cues_and_skip_final_states(self):
        a = self.data["cinematics"]["CIN_A1_OPTICS_FAIL"]
        b = self.data["cinematics"]["CIN_B1_DRONE"]
        self.assertEqual((a["skip_rule"], b["skip_rule"]), ("HoldAfterSeen", "HoldAfterSeen"))
        self.assertEqual((a["skip_min_s"], b["skip_min_s"]), (1.0, 1.0))
        self.assertEqual((a["blend_out_s"], b["blend_out_s"]), (0.0, 0.0))
        self.assertEqual([(c["at_s"], c["id"], c["value"]) for c in b["cues"] if c["type"] == "SetMode"],
                         [(12.0, "AuxSensors", 0.0), (13.8, "DroneCam", 1.0)])
        self.assertEqual([(c["id"], c["value"]) for c in b["final_state"]],
                         [("AuxSensors", 0.0), ("DroneCam", 1.0)])
        self.assertTrue(all(c["reapply_on_load"] for c in b["final_state"]))
        self.assertTrue(all(c["type"] != "PlaySfx" for scene in (a, b)
                            for c in scene["cues"] + scene["final_state"]))
        source = (ROOT / "Plugins/SaskartaCore/Source/SaskartaCore/Private/SaskartaEventRunner.cpp").read_text()
        end = source[source.index("void USaskartaEventRunner::EndCinematic("):
                     source.index("void USaskartaEventRunner::FinishBlendOut(")]
        self.assertLess(end.index("for (const FSaskartaEventAction& A : C->FinalState)"),
                        end.index("AActor* ViewTarget = ResolveCinematicHandback(*C)"))
        finish = source[source.index("void USaskartaEventRunner::FinishBlendOut("):
                        source.index("void USaskartaEventRunner::PlayCinematicById(", source.index("void USaskartaEventRunner::FinishBlendOut("))]
        self.assertLess(finish.index("CineActor->Destroy()"),
                        finish.index("AActor* ViewTarget = ResolveCinematicHandback(*C)"))


if __name__ == "__main__":
    unittest.main()
