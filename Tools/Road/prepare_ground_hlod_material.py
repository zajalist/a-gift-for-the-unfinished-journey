"""Prepare (and optionally send) Tools/Road/build_ground_hlod_material.py for Hayba python_run.

    python Tools/Road/prepare_ground_hlod_material.py           # write Saved/Road/build_ground_hlod_material.sub.py
    python Tools/Road/prepare_ground_hlod_material.py --send    # ... and build M/MI_Saskarta_GroundHLOD in the editor

Fills GROUND_HLOD_HLSL (Shaders/GroundHLOD.hlsl) and the mask mapping (Tools/Terrain/MASKS.md).
The caller should hold the editor gate (Tools/GameFlow/editor_gate.py).
"""
import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from prepare_road_material import _fill, mask_mapping, send  # noqa: E402
from prepare_ground_material import _hlsl, _put  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[2]


def prepare(root=ROOT):
    root = pathlib.Path(root)
    script = (root / "Tools" / "Road" / "build_ground_hlod_material.py").read_text(encoding="utf-8")
    script = _put(script, "__GROUND_HLOD__", _hlsl(root / "Shaders" / "GroundHLOD.hlsl"))
    origin, extent = mask_mapping(root / "Tools" / "Terrain" / "MASKS.md")
    script = _fill(script, "MASK_ORIGIN_CM", repr(origin))
    script = _fill(script, "MASK_EXTENT_CM", repr(extent))
    return script


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--send", action="store_true", help="run it in the live editor")
    ap.add_argument("--out", default=str(ROOT / "Saved" / "Road" / "build_ground_hlod_material.sub.py"))
    a = ap.parse_args()
    script = prepare(ROOT)
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
