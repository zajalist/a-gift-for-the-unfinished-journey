"""Offline tests for check_pcg_culls.evaluate and the editor script's python_run safety (Task V5)."""
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import check_pcg_culls as cpc  # noqa: E402


def row(kind, start, end):
    return [kind, "/Game/G", "Node", "entry0", "/Game/M", float(start), float(end), 0.0]


def test_default_zero_culls_fail():
    assert len(cpc.evaluate([row("static", 0, 0)])) == 1
    assert len(cpc.evaluate([row("skinned", 0, 0)])) == 1


def test_static_needs_start_and_end():
    assert len(cpc.evaluate([row("static", 0, 30000)])) == 1
    assert len(cpc.evaluate([row("static", 25000, 0)])) == 1
    assert cpc.evaluate([row("static", 6500, 30000)]) == []


def test_skinned_r24_start_zero_is_allowed_but_end_is_not():
    assert cpc.evaluate([row("skinned", 0, 7000)]) == []
    assert len(cpc.evaluate([row("skinned", 0, 0)])) == 1


def test_inverted_range_fails():
    assert len(cpc.evaluate([row("static", 30000, 6500)])) == 1


def test_unknown_selector_fails():
    assert len(cpc.evaluate([row("static", -1, -1)])) == 1


def test_editor_script_obeys_python_run_rules():
    banned = [r"\btry\b", r"\bgetattr\b", r"import time", r"open\(", r"\.replace\(", r"new_level\("]
    for pattern in banned:
        assert not re.search(pattern, cpc.EDITOR_SCRIPT), pattern


def test_fill_rewrites_graphs_line():
    s = cpc.fill(cpc.EDITOR_SCRIPT, "GRAPHS", ["/Game/A"])
    assert "GRAPHS = ['/Game/A']" in s
