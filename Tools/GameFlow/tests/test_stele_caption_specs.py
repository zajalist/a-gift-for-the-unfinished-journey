"""The stele reading must have its own CRT caption surface and cookable data."""

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def test_scan_caption_does_not_replace_hud_query_or_subtitle():
    tree = json.loads((ROOT / "Tools/GameFlow/specs/WBP_Saskarta_Caption.tree.json").read_text(encoding="utf-8"))
    graph = json.loads((ROOT / "Tools/GameFlow/specs/WBP_Saskarta_Caption.graph.json").read_text(encoding="utf-8"))
    names = {node["name"] for node in tree["tree"]}
    assert {"HudLine", "ScanBlock", "CaptionBox", "SubtitleBox"} <= names
    assert tree["slots"]["ScanBlock"]["position"][1] > tree["slots"]["HudLine"]["position"][1]
    for fn in ("ShowCaption", "HideCaption"):
        route = next(row for row in graph["graphs"] if row["graph"] == fn)
        assert route["nodes"]["ifScan"] == {"branch": True}
        assert any(node.get("get") == "ScanBlock" for node in route["nodes"].values())


def test_stele_assets_have_cook_path():
    data = json.loads((ROOT / "docs/story/inscriptions.json").read_text(encoding="utf-8"))
    config = (ROOT / "Config/DefaultGame.ini").read_text(encoding="utf-8")
    assert data["tuning"]["caption_target"] == "Scan"
    assert '+DirectoriesToAlwaysCook=(Path="/Game/SaskartaGaea/Inscriptions")' in config


def test_scan_prompt_has_its_own_crt_line():
    tree = json.loads((ROOT / "Tools/GameFlow/specs/WBP_Saskarta_Caption.tree.json").read_text(encoding="utf-8"))
    graph = json.loads((ROOT / "Tools/GameFlow/specs/WBP_Saskarta_Caption.graph.json").read_text(encoding="utf-8"))
    names = {node["name"] for node in tree["tree"]}
    assert "ScanPromptLine" in names and "ScanPromptLine" in tree["variables"]
    assert tree["slots"]["ScanPromptLine"]["position"] == tree["slots"]["ScanBlock"]["position"]
    for fn in ("ShowCaption", "HideCaption"):
        route = next(row for row in graph["graphs"] if row["graph"] == fn)
        assert route["nodes"]["ifScanPrompt"] == {"branch": True}
        assert any(node.get("get") == "ScanPromptLine" for node in route["nodes"].values())
    data = json.loads((ROOT / "docs/story/inscriptions.json").read_text(encoding="utf-8"))
    assert data["tuning"]["prompted"] is True
    assert data["tuning"]["prompt_target"] == "ScanPrompt"
    assert 10 <= data["tuning"]["prompt_range_m"] <= 14


def test_author_saskartan_is_in_the_inscription_rows():
    rows = {r["id"]: r for r in json.loads((ROOT / "docs/story/inscriptions.json").read_text(encoding="utf-8"))["inscriptions"]}
    texts = json.loads((ROOT / "docs/story/pillar-texts-saskartan.json").read_text(encoding="utf-8"))["new"]
    supplied = {k: v for k, v in texts.items() if v["saskartan"]}
    assert len(supplied) == 10
    for key, text in supplied.items():
        assert rows[key]["saskartan"] == text["saskartan"]
        assert rows[key]["voice_line_id"] == f"INSCR_{key}"
