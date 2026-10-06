"""Offline checks; these do not execute Unreal or establish visible grounding."""
import importlib.util
from pathlib import Path
import types
import unittest

SPEC = importlib.util.spec_from_file_location("survey", Path(__file__).parents[1] / "prepare_ground_contact_survey.py")
survey = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(survey)


class Point:
    def __init__(self, x=0, y=0, z=0):
        self.x, self.y, self.z = x, y, z


class Actor:
    def __init__(self, name):
        self.name = name
    def get_class(self):
        return self
    def get_name(self):
        return self.name


class Hit:
    def __init__(self, actor, z):
        self.actor, self.z = actor, z
    def to_tuple(self):
        data = [None] * 10
        data[0], data[5], data[7], data[9] = True, Point(z=self.z), Point(z=1), self.actor
        return tuple(data)


def trace_env(hits, expired=False):
    pending = iter(hits)
    fake = types.SimpleNamespace(Vector=Point, HitResult=Hit,
        TraceTypeQuery=types.SimpleNamespace(TRACE_TYPE_QUERY1=1),
        DrawDebugTrace=types.SimpleNamespace(NONE=0),
        SystemLibrary=types.SimpleNamespace(line_trace_single=lambda *args: next(pending, None)))
    env = {"unreal": fake, "world": object(), "expired": lambda: expired,
           "vec": lambda p: [p.x, p.y, p.z], "identity": lambda a: {"path": a.name}}
    body = "trace_count = 0\n" + survey.MEASURE.split("trace_count = 0\n", 1)[1].split("rows = []", 1)[0]
    exec(body, env)
    return env


class SurveyTests(unittest.TestCase):
    def test_catalog_scanner_and_scope(self):
        code = survey.catalog_script(survey.ANCHORS["quarry_approx"])
        self.assertIn("get_instances_overlapping_sphere", code)
        self.assertIn("GPU transforms unavailable", code)
        self.assertIn("pcg_caches", code)
        self.assertIn("after_component", code)
        self.assertNotIn("load_actors(", code)
        self.assertNotIn("_ism_", code)

    def test_selection_requires_current_pose_and_small_batch(self):
        row = {"component": "/Game/C", "mesh": "/Game/M", "instance": 1, "transform": "Current"}
        code = survey.measure_script([row])
        self.assertIn("transform_changed_recatalog", code)
        self.assertIn("heightmap_fallback': False", code)
        with self.assertRaises(ValueError):
            survey.measure_script([row] * 3)

    def test_missing_terrain_stays_unknown(self):
        env = trace_env([])
        result = env["hit_below"](Point(z=100), Actor("Owner"), 200)
        self.assertEqual(result, {"status": "no_landscape_hit", "hits": []})

    def test_prop_support_preserved_before_landscape(self):
        env = trace_env([Hit(Actor("SupportRock"), 95), Hit(Actor("LandscapeStreamingProxy"), 0)])
        result = env["hit_below"](Point(z=100), Actor("Owner"), 200)
        self.assertEqual(result["status"], "landscape")
        self.assertEqual([h["clearance_cm"] for h in result["hits"]], [5, 100])
        self.assertEqual([h["landscape"] for h in result["hits"]], [False, True])

    def test_occlusion_and_time_are_bounded(self):
        env = trace_env([Hit(Actor("Rock"), 90)] * 10)
        self.assertEqual(env["hit_below"](Point(), Actor("Owner"), 200)["status"], "occluder_limit")
        self.assertEqual(env["trace_count"], 6)
        env = trace_env([], expired=True)
        self.assertEqual(env["hit_below"](Point(), Actor("Owner"), 200)["status"], "budget")
        self.assertEqual(env["trace_count"], 0)

    def test_read_only_check_rejects_mutation(self):
        with self.assertRaises(ValueError):
            survey.checked("object.set_editor_property('x', 1)")


if __name__ == "__main__":
    unittest.main()
