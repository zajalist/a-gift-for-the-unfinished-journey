"""A destructive clear must invalidate the prior live-contact verdict."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import place_setdress as placement


def test_clear_invalidates_prior_check2_before_a_v2_save(tmp_path, monkeypatch):
    site = "R02_Verge1080"
    monkeypatch.setattr(placement, "STATE_DIR", str(tmp_path))
    placement.write_state(site, {
        "loaded": [],
        "dirty": False,
        "check2": {"measured": 4, "expected": 4, "violations": []},
    })
    sent = []

    class OfflineRunner:
        def __init__(self, _args):
            pass

        def send(self, name, _script):
            sent.append(name)
            return "CLEARPKG /Game/Test/OldR02Actor" if name.endswith("_clear") else "DONE"

    monkeypatch.setattr(placement, "Runner", OfflineRunner)
    monkeypatch.setattr(placement, "gate_check", lambda *_: None)
    monkeypatch.setattr(sys, "argv", ["place_setdress.py", "clear", site, "--v2", "--yes"])
    placement.main()

    state = placement.read_state(site)
    assert state["deletions_pending"] is True
    assert state["dirty"] is True
    assert sent == [site + "_clear"]

    monkeypatch.setattr(sys, "argv", ["place_setdress.py", "save", site, "--v2"])
    with pytest.raises(SystemExit, match="run check2"):
        placement.main()
    assert sent == [site + "_clear"], "save must not reach the editor with a stale verdict"
