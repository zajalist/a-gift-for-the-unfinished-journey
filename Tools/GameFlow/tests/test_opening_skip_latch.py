import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys_path = str(ROOT / "Tools/GameFlow")
if sys_path not in sys.path:
    sys.path.insert(0, sys_path)

import gen_loading_specs


def load_graphs(path):
    spec = json.loads(path.read_text(encoding="utf-8"))
    return {item["graph"]: item for item in spec["graphs"]}


def has_link(graph, source, target):
    return [source, target] in graph["links"]


def eval_bool_output(graph, output, physical_held, requested, flow_state):
    incoming = {target: source for source, target in graph["links"]}
    values = {
        "physicalHeld.ReturnValue": physical_held,
        "requested.bOpeningSkipRequested": requested,
        "isBooting.ReturnValue": flow_state == "Booting",
    }

    def resolve(endpoint):
        if endpoint in incoming:
            return resolve(incoming[endpoint])
        if endpoint in values:
            return values[endpoint]
        node_name, pin = endpoint.split(".", 1)
        node = graph["nodes"][node_name]
        operation = node.get("call")
        if operation not in {"BooleanAND", "BooleanOR"}:
            raise AssertionError(f"cannot evaluate {endpoint}: {node}")
        a = resolve(incoming[f"{node_name}.A"])
        b = resolve(incoming[f"{node_name}.B"])
        return a and b if operation == "BooleanAND" else a or b

    return resolve(output)


def should_skip_boot(graph, physical_held, requested, flow_state):
    # PollOpeningSkip gates the flow sequence on active, then evaluates the
    # Booting-specific condition before calling SkipBoot.
    active = eval_bool_output(graph, "active.ReturnValue", physical_held, requested, flow_state)
    boot_condition = eval_bool_output(graph, "bootBranch.Condition", physical_held, requested, flow_state)
    return active and boot_condition


class OpeningSkipLatchTests(unittest.TestCase):
    def test_boot_skip_requires_a_current_physical_hold(self):
        generated = load_graphs(ROOT / "Tools/GameFlow/specs/PC_Saskarta.loading.json")["PollOpeningSkip"]
        source = gen_loading_specs.POLL_OPENING_SKIP
        self.assertEqual(generated, source)

        for graph in (source, generated):
            self.assertEqual(graph["nodes"].get("bootHeld"), {
                "call": "BooleanAND", "class": "/Script/Engine.KismetMathLibrary"
            })
            self.assertIn(["physicalHeld.ReturnValue", "bootHeld.A"], graph["links"])
            self.assertIn(["isBooting.ReturnValue", "bootHeld.B"], graph["links"])
            self.assertIn(["bootHeld.ReturnValue", "bootBranch.Condition"], graph["links"])
            self.assertNotIn(["isBooting.ReturnValue", "bootBranch.Condition"], graph["links"])

        active = generated
        self.assertIn(["requested.bOpeningSkipRequested", "active.B"], active["links"])
        self.assertIn(["flowBranch.then", "setRequested.execute"], active["links"])
        self.assertTrue(has_link(load_graphs(ROOT / "Tools/GameFlow/specs/PC_Saskarta.loading.json")["PollRoad"],
                                 "skipRequested.bOpeningSkipRequested", "skipOrMin.B"))
        self.assertTrue(has_link(load_graphs(ROOT / "Tools/GameFlow/specs/PC_Saskarta.loading.json")["PollTitle"],
                                 "skipRequested.bOpeningSkipRequested", "skipOrMin.B"))

    def test_deliberate_hold_during_boot_still_skips_the_crt(self):
        generated = load_graphs(ROOT / "Tools/GameFlow/specs/PC_Saskarta.loading.json")["PollOpeningSkip"]
        self.assertIn(["physicalHeld.ReturnValue", "bootHeld.A"], generated["links"])
        self.assertIn(["isBooting.ReturnValue", "bootHeld.B"], generated["links"])
        self.assertIn(["bootHeld.ReturnValue", "bootBranch.Condition"], generated["links"])
        cases = [
            ("latched only during Booting", False, True, "Booting", False),
            ("physical hold during Booting", True, False, "Booting", True),
            ("physical hold during Playing", True, False, "Playing", False),
            ("neither during Booting", False, False, "Booting", False),
        ]
        for label, physical_held, requested, flow_state, expected in cases:
            with self.subTest(label=label):
                self.assertEqual(should_skip_boot(generated, physical_held, requested, flow_state), expected)


if __name__ == "__main__":
    unittest.main()
