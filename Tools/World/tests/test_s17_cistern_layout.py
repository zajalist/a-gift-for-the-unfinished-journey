"""Composition guard for the ruined cistern silhouette and road-facing cues."""

import math
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "Tools" / "World" / "setdress_v2_groups"))
import water_stone_features as S17  # noqa: E402


def test_s17_ruined_arcade_and_safe_contact():
    world = S17.B.World()
    sites, _, composers = S17.build(world, ["S17_DryCistern"])
    site = sites[0]
    placements = site["placements"]
    actors = [p for p in placements if not p.get("ism") and not p.get("optional")]

    assert S17.soundness(site, composers[site["id"]]) == []
    assert site["offline_check"]["violations"] == []
    assert site["story_owned"] == []
    assert len(actors) <= 150
    assert all(p["road_clear_m"] >= 5.0 for p in placements)

    # An inner bay has fallen: two arches still meet, while the other is a
    # visibly separate remnant. Both piers have lower, unequal broken crowns.
    arches = [p for p in actors if p.get("state") == "arcade"]
    piers = [p for p in actors if p.get("state") == "pier"]
    corners = [p for p in actors if p.get("state") == "pillar" and p["group"] == "rim"]
    assert len(arches) == 3 and len(piers) == 2 and len(corners) == 2
    arch_xy = [(p["x_cm"], p["y_cm"]) for p in arches]
    gaps_m = sorted(math.dist(a, b) / 100.0 for a, b in zip(arch_xy, arch_xy[1:]))
    assert 2.8 <= gaps_m[0] <= 3.2
    assert 5.8 <= gaps_m[1] <= 6.2
    assert max(p["vis_h"] for p in piers) < min(p["vis_h"] for p in arches)
    assert abs(piers[0]["vis_h"] - piers[1]["vis_h"]) > 1.0

    # The cistern's authored approach and CIN_P17 board remain in place.
    assert len([p for p in actors if p.get("state") == "board" and p["key"] == "B01_sign02"]) == 1
    assert len([p for p in placements if p.get("state") == "step"]) >= 10

    # Field walls are two short staggered remains, not a repeated full-width grid.
    terraces = [p for p in actors if p.get("state") == "terrace"]
    assert 3 <= len(terraces) <= 9
    assert max(p["road_clear_m"] for p in terraces) - min(p["road_clear_m"] for p in terraces) >= 8.0
