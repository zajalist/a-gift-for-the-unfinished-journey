"""Prepare (and optionally send) Tools/Road/build_ground_material.py for Hayba python_run.

    python Tools/Road/prepare_ground_material.py                   # write Saved/Road/build_ground_material.sub.py
    python Tools/Road/prepare_ground_material.py --send            # ... and build M/MI_Saskarta_Ground in the editor
    python Tools/Road/prepare_ground_material.py --send --assign   # ... and put MI_Saskarta_Ground on the Landscape

python_run scripts may not read files, so this host-side step fills the build
script's placeholders before it is sent:

    AUTO_HLSL = r'''__AUTO__'''   <- the full text of Shaders/GroundAuto.hlsl
    READ_HLSL = r'''__READ__'''   <- the full text of Shaders/GroundRead.hlsl
    NOTILE_HLSL = r'''__NOTILE__''' <- the full text of Shaders/GroundNoTile.hlsl
    NOTILE_N_HLSL = r'''__NOTILE_N__''' <- the full text of Shaders/GroundNoTileNormal.hlsl
    MASK_ORIGIN_CM = None         <- (X0, Y0) from Tools/Terrain/MASKS.md
    MASK_EXTENT_CM = None         <- the extent from Tools/Terrain/MASKS.md (Ruling R5)
    MODE = 'build'                <- 'assign' with --assign

The caller must hold the editor gate (Tools/GameFlow/editor_gate.py).
"""
import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from prepare_road_material import _fill, mask_mapping, send  # noqa: E402  (shared with Task V1)

ROOT = pathlib.Path(__file__).resolve().parents[2]


def _hlsl(path):
    text = pathlib.Path(path).read_text(encoding="ascii")
    if "'''" in text or "\\" in text:
        raise ValueError(f"{path} must not contain triple quotes or backslashes")
    return text


def _put(script, marker, text):
    parts = script.split(marker)
    if len(parts) != 2:
        raise ValueError(f"expected exactly one {marker} marker, found {len(parts) - 1}")
    return text.join(parts)


def prepare(root=ROOT, mode="build"):
    root = pathlib.Path(root)
    script = (root / "Tools" / "Road" / "build_ground_material.py").read_text(encoding="utf-8")
    script = _put(script, "__AUTO__", _hlsl(root / "Shaders" / "GroundAuto.hlsl"))
    script = _put(script, "__READ__", _hlsl(root / "Shaders" / "GroundRead.hlsl"))
    script = _put(script, "__NOTILE__", _hlsl(root / "Shaders" / "GroundNoTile.hlsl"))
    script = _put(script, "__NOTILE_N__", _hlsl(root / "Shaders" / "GroundNoTileNormal.hlsl"))
    origin, extent = mask_mapping(root / "Tools" / "Terrain" / "MASKS.md")
    script = _fill(script, "MASK_ORIGIN_CM", repr(origin))
    script = _fill(script, "MASK_EXTENT_CM", repr(extent))
    script = _fill(script, "MODE", repr(mode))
    return script


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--send", action="store_true", help="run it in the live editor (hold the editor gate)")
    ap.add_argument("--assign", action="store_true", help="assign MI_Saskarta_Ground to the Landscape actor")
    ap.add_argument("--out", default=str(ROOT / "Saved" / "Road" / "build_ground_material.sub.py"))
    a = ap.parse_args()
    script = prepare(ROOT, "assign" if a.assign else "build")
    out = pathlib.Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(script, encoding="utf-8")
    print(f"wrote {out} ({len(script)} chars)")
    if a.send:
        reply = send(script)
        data = reply.get("data") or {}
        print(data.get("stdout", ""))
        if data.get("stderr"):
            print("STDERR", data["stderr"])
        if not reply.get("ok"):
            print(json.dumps(reply)[:2000])
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
