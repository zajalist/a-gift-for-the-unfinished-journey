"""Regression checks for widget polling during player/world teardown.

These inspect the executable generated graphs: owner validity must branch before
any pure input-query results are consumed, and recurring timers must be cleared
from Destruct. A BooleanAND cannot act as a guard because Blueprint pure inputs
may be evaluated eagerly.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "Tools" / "GameFlow"))

import gen_keyprompt_specs  # noqa: E402
import gen_radio_specs  # noqa: E402


def graph_for(spec: dict, name: str) -> dict:
    return next(graph for graph in spec["graphs"] if graph["graph"] == name)


def node_id(graph: dict, kind: str, value: str) -> str:
    matches = [key for key, node in graph["nodes"].items() if node.get(kind) == value]
    if len(matches) != 1:
        raise AssertionError(f"expected one {kind}={value!r}, got {matches}")
    return matches[0]


def has_link(graph: dict, src: str, dst: str) -> bool:
    return [src, dst] in graph["links"]


class WidgetPollLifetimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.radio = gen_radio_specs.graph()
        self.keyprompt = gen_keyprompt_specs.build()

    def assert_owner_gate(self, graph: dict, next_exec: str) -> None:
        owner = node_id(graph, "call", "GetOwningPlayer")
        valid = next(key for key, node in graph["nodes"].items()
                     if node.get("call") == "IsValid" and
                     has_link(graph, f"{owner}.ReturnValue", f"{key}.Object"))
        gate = "ifOwnerValid"
        entry = node_id(graph, "entry", True)
        self.assertIs(graph["nodes"].get(gate, {}).get("branch"), True)
        self.assertTrue(has_link(graph, f"{owner}.ReturnValue", f"{valid}.Object"))
        self.assertTrue(has_link(graph, f"{valid}.ReturnValue", f"{gate}.Condition"))
        self.assertTrue(has_link(graph, f"{entry}.then", f"{gate}.execute"))
        self.assertTrue(has_link(graph, f"{gate}.then", f"{next_exec}.execute"))
        self.assertFalse(any(src == f"{gate}.else" for src, _ in graph["links"]))
        owner_valid_targets = [dst for src, dst in graph["links"]
                               if src == f"{valid}.ReturnValue"]
        self.assertEqual(owner_valid_targets, [f"{gate}.Condition"])

    def test_radio_poll_guards_owner_before_poll_work(self) -> None:
        poll = graph_for(self.radio, "Poll")
        self.assert_owner_gate(poll, "ifStationValid")
        self.assertTrue(has_link(poll, "ifStationValid.then", "ifRunnerValid.execute"))
        self.assertTrue(has_link(poll, "ifRunnerValid.then", "ifPressed.execute"))

    def test_radio_toggle_gates_station_and_runner_before_reads(self) -> None:
        toggle = graph_for(self.radio, "Toggle")
        self.assertTrue(has_link(toggle, "entry.then", "ifRunnerValid.execute"))
        self.assertTrue(has_link(toggle, "ifRunnerValid.then", "ifStationValid.execute"))
        self.assertTrue(has_link(toggle, "ifStationValid.then", "ifPlaying.execute"))
        self.assertFalse(any(src in ("ifRunnerValid.else", "ifStationValid.else")
                             for src, _ in toggle["links"]))

    def test_keyprompt_device_poll_guards_owner_before_poll_work(self) -> None:
        poll = graph_for(self.keyprompt, "PollDevice")
        self.assert_owner_gate(poll, "ifChanged")

    def test_destruct_clears_radio_poll_timer(self) -> None:
        event_graph = graph_for(self.radio, "EventGraph")
        destruct = node_id(event_graph, "event", "Destruct")
        clear = node_id(event_graph, "call", "K2_ClearAndInvalidateTimerHandle")
        timer = node_id(event_graph, "get", "PollTimer")
        self.assertTrue(has_link(event_graph, f"{destruct}.then", f"{clear}.execute"))
        self.assertTrue(has_link(event_graph, f"{timer}.PollTimer", f"{clear}.Handle"))

    def test_destruct_clears_keyprompt_poll_and_pulse_timers(self) -> None:
        event_graph = graph_for(self.keyprompt, "EventGraph")
        destruct = node_id(event_graph, "event", "Destruct")
        clear_poll = "clearPollOnDestruct"
        clear_pulse = "clearPulseOnDestruct"
        self.assertTrue(has_link(event_graph, f"{destruct}.then", f"{clear_poll}.execute"))
        self.assertTrue(has_link(event_graph, f"{clear_poll}.then", f"{clear_pulse}.execute"))
        self.assertEqual(event_graph["nodes"][clear_poll].get("call"), "K2_ClearAndInvalidateTimerHandle")
        self.assertEqual(event_graph["nodes"][clear_pulse].get("call"), "K2_ClearAndInvalidateTimerHandle")
        for timer_name, clear_name in (("PollTimer", clear_poll), ("PulseTimer", clear_pulse)):
            timer = node_id(event_graph, "get", timer_name)
            self.assertTrue(has_link(event_graph, f"{timer}.{timer_name}", f"{clear_name}.Handle"))

    def test_generated_graph_specs_match_checked_in_specs(self) -> None:
        specs = ROOT / "Tools" / "GameFlow" / "specs"
        expected = {
            "WBP_Saskarta_Radio.graph.json": self.radio,
            "WBP_Saskarta_KeyPrompt.graph.json": self.keyprompt,
        }
        for filename, generated in expected.items():
            with self.subTest(filename=filename):
                checked_in = json.loads((specs / filename).read_text(encoding="utf-8"))
                self.assertEqual(generated, checked_in)


if __name__ == "__main__":
    unittest.main()
