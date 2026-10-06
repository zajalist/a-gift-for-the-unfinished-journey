"""A failed or unconfirmed package save must preserve pending deletions."""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import place_setdress as placement


def v2_selection(site):
    row = placement.site_of(placement.load_doc(True), site)
    args = SimpleNamespace(approve='', with_optional=False, skip_story=False, no_ism=False)
    return placement.selection_token(placement.select(row, args)[0], True)


@pytest.mark.parametrize("failure", ["actor_false", "actor_missing", "deletion_false", "deletion_missing", "deletion_zero"])
def test_v2_save_refuses_failed_or_missing_receipt(tmp_path, monkeypatch, failure):
    site = "R02_Verge1080"
    monkeypatch.setattr(placement, "STATE_DIR", str(tmp_path))
    placement.write_state(site, {
        "loaded": [],
        "dirty": False,
        "check2": {"measured": 4, "expected": 4, "selection": v2_selection(site), "ism_measured": 0, "ism_expected": 0,
                   "ism_hosts_measured": 0, "ism_hosts_expected": 0, "violations": []},
        "deleted_pkgs": ["/Game/Test/OldR02Actor"],
        "deletions_pending": True,
    })
    sent = []

    class OfflineRunner:
        def __init__(self, _args):
            pass

        def send(self, name, _script):
            sent.append(name)
            if len(sent) == 1:
                if failure == "actor_false":
                    return "SAVE 4 ok=False total=8 DONE"
                if failure == "actor_missing":
                    return "no receipt"
                return "SAVE 4 ok=True total=8 DONE"
            if failure == "deletion_false":
                return "SAVE deleted_packages=1\nSAVE 0 ok=False total=8 DONE"
            if failure == "deletion_zero":
                return "SAVE deleted_packages=0\nSAVE 0 ok=True total=8 DONE"
            return "no receipt"

    monkeypatch.setattr(placement, "Runner", OfflineRunner)
    monkeypatch.setattr(placement, "gate_check", lambda *_: None)
    monkeypatch.setattr(sys, "argv", ["place_setdress.py", "save", site, "--v2"])

    with pytest.raises(SystemExit, match="SAVE"):
        placement.main()
    state = placement.read_state(site)
    assert state["deleted_pkgs"] == ["/Game/Test/OldR02Actor"]
    assert state["deletions_pending"] is True
    assert state["dirty"] is False
    assert len(sent) == (1 if failure.startswith("actor_") else 2)


def test_v2_save_clears_deletions_only_after_both_success_receipts(tmp_path, monkeypatch):
    site = "R02_Verge1080"
    monkeypatch.setattr(placement, "STATE_DIR", str(tmp_path))
    placement.write_state(site, {
        "dirty": False,
        "check2": {"measured": 4, "expected": 4, "selection": v2_selection(site), "ism_measured": 0, "ism_expected": 0,
                   "ism_hosts_measured": 0, "ism_hosts_expected": 0, "violations": []},
        "deleted_pkgs": ["/Game/Test/OldR02Actor"],
        "deletions_pending": True,
    })
    replies = iter(("SAVE 8 ok=True total=8 DONE", "SAVE deleted_packages=1\nSAVE 0 ok=True total=8 DONE"))

    class OfflineRunner:
        def __init__(self, _args):
            pass

        def send(self, _name, _script):
            return next(replies)

    monkeypatch.setattr(placement, "Runner", OfflineRunner)
    monkeypatch.setattr(placement, "gate_check", lambda *_: None)
    monkeypatch.setattr(sys, "argv", ["place_setdress.py", "save", site, "--v2"])
    placement.main()

    state = placement.read_state(site)
    assert state["deleted_pkgs"] == []
    assert state["deletions_pending"] is False
