"""Offline checks for the ambient motion data (task CINEPOI; docs/world/AMBIENT_ANIMATION.md). No editor.

    python -m pytest Tools/World/tests/test_ambient_anim.py -q
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
WORLD = os.path.dirname(HERE)
sys.path.insert(0, WORLD)
import gen_ambient_anim as ga  # noqa: E402

DATA = json.load(open(os.path.join(WORLD, "ambient_anim.json"), encoding="utf-8"))
SITES = {s["id"]: s for s in json.load(open(os.path.join(WORLD, "setdress_sites.json"), encoding="utf-8"))["sites"]}
SITES["S17_DryCistern"] = next(
    s for s in json.load(open(os.path.join(WORLD, "setdress_v2_groups", "water_stone_features.json"), encoding="utf-8"))["sites"]
    if s["id"] == "S17_DryCistern"
)


def test_file_is_current():
    assert ga.dump(ga.build()) == open(os.path.join(WORLD, "ambient_anim.json"), encoding="utf-8").read()


def test_every_item_references_a_placed_actor():
    for s in DATA["sites"]:
        ids = {p["id"]: p for p in SITES[s["site"]]["placements"]}
        for it in s["items"]:
            ref = it["placement"] or it.get("anchor")
            if it.get("new") and it.get("anchor") is None:
                assert any(p["group"] == it["group"] for p in ids.values())
                continue
            assert ref in ids, (s["site"], ref)
            if it["placement"]:
                assert ids[ref]["key"] == it["key"] and ids[ref]["group"] == it["group"]


def test_s17_board_uses_v2_head_placement():
    site = next(s for s in DATA["sites"] if s["site"] == "S17_DryCistern")
    board = [it for it in site["items"] if it["key"] == "B01_sign02"]
    assert len(board) == 1
    assert board[0]["placement"] == "S17_DryCistern_v2_989"
    assert board[0]["group"] == "head"
    assert board[0]["folder"] == "Set/S17_DryCistern/head"


def test_distance_culled_and_no_heavy_methods():
    for s in DATA["sites"]:
        for it in s["items"]:
            assert it["method"] in ga.METHODS
            d = it.get("wpo_disable_distance_cm") or it.get("card", {}).get("max_draw_distance_cm")
            if it["method"] == "rotating_component":
                continue
            assert d, (s["site"], it["method"])
            if s["site"] in ga.FAR:
                assert d == ga.FAR[s["site"]][0] and it["distance_note"]
            else:
                assert d == ga.NEAR_CM
            if "wpo_disable_distance_cm" in it:
                assert it["shadow_cache_invalidation"] == "Static"
            assert "niagara" not in json.dumps(it).lower() and "skeletal" not in json.dumps(it).lower()


def test_lanterns_unlit_and_no_smoke():
    for s in DATA["sites"]:
        for it in s["items"]:
            if it.get("key") == "PH_lantern":
                assert it["params"]["lit"] is False
            if it["method"] == "card_dust_wisp":
                assert "not smoke" in it["note"]


def test_budget_inside_the_cap():
    b = DATA["budget"]
    assert b["worst_site_ms_all_on_screen"] <= b["ambient_cap_ms"]
    assert DATA["totals"]["entries"] == sum(len(s["items"]) for s in DATA["sites"])
    assert DATA["totals"]["objects"] >= DATA["totals"]["entries"]
