"""ISM ground contact and host coverage are part of the V2 save contract."""

import ast
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import place_setdress as placement
import setdress_contact


@pytest.mark.parametrize(
    "contact,gaps,code",
    [
        (None, [12, 18, 16, 20, 14], "FLOAT"),
        (None, [None] * 5, "NOGROUND"),
        (None, [15, 18, -2, 20, 14], None),
        ("rigid", [-3, -2, 9, -1, 0], "FLOAT"),
        ("rigid", [-3, None, -2, -1, 0], "NOGROUND"),
    ],
)
def test_ism_gap_judge_includes_rubble_and_requires_ground(contact, gaps, code):
    item = {"cat": "rubble", "contact": contact}
    result = placement.ism_gap_violation(gaps, item)
    assert (result[0] if result else None) == code


def test_ism_host_jobs_preserve_each_instance_once():
    site = next(s for s in placement.load_doc(True)["sites"] if s["id"] == "S15_Works")
    jobs = list(placement.ism_jobs(site["id"], site["placements"], 60))
    ids = [p["id"] for _, _, batch in jobs for p in batch]
    assert len(jobs) == 33
    assert len(ids) == 335 == len(set(ids))
    assert all(len(batch) <= 60 for _, _, batch in jobs)


@pytest.mark.parametrize(
    "cat,attach,gaps,code",
    [("rubble", False, [None] * 9, "NOGROUND"),
     ("shrub", False, [12, 19, None], "FLOAT"),
     ("rubble", False, [18, 0, None], None),  # stacked on another rock
     ("rubble", True, [20] * 9, None),       # intentional attachment
     ("fx", False, [20] * 9, None)],
)
def test_solo_scatter_needs_a_support_but_allows_stacks(cat, attach, gaps, code):
    result = placement.solo_scatter_gap_violation({"gaps": gaps}, {"cat": cat, "attach": attach})
    assert (result[0] if result else None) == code


def test_v2_selection_distinguishes_story_skip_and_no_ism():
    doc = placement.load_doc(True)
    story = placement.site_of(doc, "S19_LastWaystation")
    base = SimpleNamespace(approve="", with_optional=False, skip_story=False, no_ism=False)
    skipped = SimpleNamespace(approve="", with_optional=False, skip_story=True, no_ism=False)
    full = placement.select(story, base)[0]
    without_story = placement.select(story, skipped)[0]
    assert len(full) - len(without_story) == 3
    assert placement.selection_token(full, True) != placement.selection_token(without_story, True)
    assert placement.selection_token(full, True) != placement.selection_token(full, False)
    ism_site = placement.site_of(doc, "S15_Works")
    assert placement.selection_token(placement.select(ism_site, base)[0], True) != placement.selection_token(
        placement.select(ism_site, SimpleNamespace(approve="", with_optional=False,
                                                   skip_story=False, no_ism=True))[0], True)


def test_check2_detects_an_unreported_ism_and_blocks_save(tmp_path, monkeypatch):
    site = "S15_Works"
    monkeypatch.setattr(placement, "STATE_DIR", str(tmp_path))
    placement.write_state(site, {"loaded": [], "ism_batch_size": 60})
    monkeypatch.setattr(placement, "gate_check", lambda *_: None)
    monkeypatch.setattr(setdress_contact, "judge", lambda *_: ([], []))
    dropped = False

    def embedded(script, key):
        return ast.literal_eval(next(line.split(" = ", 1)[1] for line in script.splitlines()
                                     if line.startswith(key + " = ")))

    class OfflineRunner:
        def __init__(self, _args):
            pass

        def send(self, name, script):
            nonlocal dropped
            if name.endswith("_ism_check2"):
                group, count, pairs = (embedded(script, key) for key in ("GROUP_ID", "EXPECTED", "ITEMS"))
                lines = ["C2IHOST " + str({"id": group, "count": count, "expected": count})]
                for _, item in pairs:
                    if not dropped:
                        dropped = True
                        continue
                    lines.append("C2I " + str({"id": item["id"], "gaps": [-2, -1, 0, -1, -2]}))
                return "\n".join(lines)
            items = embedded(script, "ITEMS")
            return "\n".join("C2 " + str({"id": item["id"]}) for item in items)

    monkeypatch.setattr(placement, "Runner", OfflineRunner)
    monkeypatch.setattr(sys, "argv", ["place_setdress.py", "check2", site, "--v2"])
    placement.main()
    state = placement.read_state(site)
    report = state["check2"]
    assert report["measured"] == report["expected"] == 51
    assert report["ism_measured"] == 334
    assert report["ism_expected"] == 335
    assert any(v[1] == "NOGROUND" for v in report["violations"])

    monkeypatch.setattr(sys, "argv", ["place_setdress.py", "save", site, "--v2"])
    with pytest.raises(SystemExit, match="refusing to save"):
        placement.main()


@pytest.mark.parametrize("fault", ["host_count", "partial_solo"])
def test_check2_cannot_authorize_bad_host_or_partial_solo(tmp_path, monkeypatch, fault):
    site = "S15_Works"
    monkeypatch.setattr(placement, "STATE_DIR", str(tmp_path))
    placement.write_state(site, {"loaded": [], "ism_batch_size": 60})
    monkeypatch.setattr(placement, "gate_check", lambda *_: None)
    monkeypatch.setattr(setdress_contact, "judge", lambda *_: ([], []))

    def embedded(script, key):
        return ast.literal_eval(next(line.split(" = ", 1)[1] for line in script.splitlines()
                                     if line.startswith(key + " = ")))

    class OfflineRunner:
        def __init__(self, _args):
            pass

        def send(self, name, script):
            if name.endswith("_ism_check2"):
                group, count, pairs = (embedded(script, key) for key in ("GROUP_ID", "EXPECTED", "ITEMS"))
                actual = count - 1 if fault == "host_count" else count
                lines = ["C2IHOST " + str({"id": group, "count": actual, "expected": count})]
                lines += ["C2I " + str({"id": item["id"], "gaps": [0] * 5}) for _, item in pairs]
                return "\n".join(lines)
            items = embedded(script, "ITEMS")
            return "\n".join("C2 " + str({"id": item["id"]}) for item in items)

    monkeypatch.setattr(placement, "Runner", OfflineRunner)
    argv = ["place_setdress.py", "check2", site]
    if fault == "partial_solo":
        row = placement.site_of(placement.load_doc(True), site)
        argv.append(next(p["id"] for p in row["placements"] if not p["ism"]))
    monkeypatch.setattr(sys, "argv", argv + ["--v2"])
    placement.main()
    report = placement.read_state(site)["check2"]
    if fault == "host_count":
        assert any(v[1] == "ISM_COUNT" for v in report["violations"])
    else:
        assert report["expected"] < 51
    monkeypatch.setattr(sys, "argv", ["place_setdress.py", "save", site, "--v2"])
    with pytest.raises(SystemExit, match="refusing to save"):
        placement.main()


def test_check2_dry_run_validates_ism_scripts(tmp_path, monkeypatch):
    site = "S15_Works"
    monkeypatch.setattr(placement, "STATE_DIR", str(tmp_path))
    monkeypatch.setattr(placement, "gate_check", lambda *_: None)
    sent = []

    class OfflineRunner:
        def __init__(self, _args):
            pass

        def send(self, name, script):
            placement.validate(script)
            sent.append(name)
            return ""

    monkeypatch.setattr(placement, "Runner", OfflineRunner)
    monkeypatch.setattr(sys, "argv", ["place_setdress.py", "check2", site, "--v2", "--dry-run"])
    placement.main()
    assert any(name.endswith("_ism_check2") for name in sent)
    assert any(name.endswith("_check2") and not name.endswith("_ism_check2") for name in sent)


@pytest.mark.parametrize("site,readback_flag", [("S19_LastWaystation", "--skip-story"),
                                                 ("S15_Works", "--no-ism")])
def test_save_rejects_different_story_or_ism_selection(tmp_path, monkeypatch, site, readback_flag):
    monkeypatch.setattr(placement, "STATE_DIR", str(tmp_path))
    row = placement.site_of(placement.load_doc(True), site)
    readback_args = SimpleNamespace(approve="", with_optional=False, skip_story=readback_flag == "--skip-story",
                                    no_ism=readback_flag == "--no-ism")
    selected = placement.select(row, readback_args)[0]
    solo = sum(not p["ism"] for p in selected)
    isms = len(selected) - solo
    placement.write_state(site, {"dirty": False, "check2": {
        "selection": placement.selection_token(selected, True),
        "measured": solo, "expected": solo, "ism_measured": isms, "ism_expected": isms,
        "ism_hosts_measured": 0, "ism_hosts_expected": 0, "violations": []}})
    monkeypatch.setattr(placement, "gate_check", lambda *_: None)

    class OfflineRunner:
        def __init__(self, _args):
            pass

        def send(self, _name, _script):
            raise AssertionError("save should have been gated before editor contact")

    monkeypatch.setattr(placement, "Runner", OfflineRunner)
    monkeypatch.setattr(sys, "argv", ["place_setdress.py", "save", site, "--v2"])
    with pytest.raises(SystemExit, match="placement selection"):
        placement.main()
