"""Prepare (and optionally send) Tools/Road/build_road_material.py for Hayba python_run.

    python Tools/Road/prepare_road_material.py            # write Saved/Road/build_road_material.sub.py
    python Tools/Road/prepare_road_material.py --send     # ... and run it in the live editor

python_run scripts may not read files, so this host-side step fills the build
script's three placeholders before it is sent:

    HLSL_SOURCE = r'''__HLSL__'''   <- the full text of Shaders/RoadRVT.hlsl, with its
                                       ROAD_NPTS / ROAD_POINTS markers filled (V1b)
    MASK_ORIGIN_CM = None           <- (X0, Y0) from Tools/Terrain/MASKS.md
    MASK_EXTENT_CM = None           <- the extent from Tools/Terrain/MASKS.md

The road polyline (V1b) is RoadSpline's control points, read from
Tools/Story/build_road_profile.py SPLINE_POINTS_CM (the source the masks were baked
from, so the shader's road frame and T_Saskarta_RoadInfluence agree), converted to
metres in the mask frame (x, y minus the mask origin).

The mask UV mapping is read from MASKS.md's "UV = (WorldXY - (X0, Y0)) / EXTENT"
line on every run (Ruling R5: never hardcode the extent), so a re-bake that
changes the extent only needs MASKS.md updated and this script re-run.

--send uses Hayba's raw TCP framing (4-byte big-endian length, then JSON
{"cmd": "python_run", "id": ..., "params": {"script": ...}}) on 127.0.0.1:52342.
The caller must hold the editor gate (Tools/GameFlow/editor_gate.py).
"""
import argparse
import json
import pathlib
import re
import socket
import struct
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "Tools" / "Story"))
NUM = r"[-−]?\d+(?:\.\d+)?"
UV_LINE = re.compile(r"UV\s*=\s*\(\s*WorldXY\s*[-−]\s*\(\s*(" + NUM + r")\s*,\s*(" + NUM + r")\s*\)\s*\)\s*/\s*(" + NUM + r")")


def _num(text):
    return float(text.replace("−", "-"))


def mask_mapping(masks_md):
    """Return ((X0, Y0), EXTENT) in cm from MASKS.md's UV formula."""
    hits = UV_LINE.findall(pathlib.Path(masks_md).read_text(encoding="utf-8"))
    values = {tuple(_num(v) for v in hit) for hit in hits}
    if len(values) != 1:
        raise ValueError(f"expected one UV mapping in {masks_md}, found {sorted(values)}")
    x0, y0, extent = values.pop()
    if extent <= 0:
        raise ValueError(f"bad mask extent {extent}")
    return (x0, y0), extent


def road_polyline_m(origin):
    """RoadSpline control points as (x, y, z) metres, x and y relative to the mask origin."""
    import build_road_profile as brp
    pts = brp.SPLINE_POINTS_CM
    return [((float(x) - origin[0]) / 100.0, (float(y) - origin[1]) / 100.0, float(z) / 100.0) for x, y, z in pts]


def fill_polyline(hlsl, points):
    """Fill RoadRVT.hlsl's ROAD_NPTS and ROAD_POINTS markers."""
    if hlsl.count("ROAD_POINTS") != 1 or "ROAD_NPTS" not in hlsl:
        raise ValueError("RoadRVT.hlsl must hold one ROAD_POINTS marker and ROAD_NPTS")
    body = ", ".join(f"float3({x:.3f}, {y:.3f}, {z:.3f})" for x, y, z in points)
    return hlsl.replace("ROAD_POINTS", body).replace("ROAD_NPTS", str(len(points)))


def prepared_hlsl(root=ROOT):
    root = pathlib.Path(root)
    hlsl = (root / "Shaders" / "RoadRVT.hlsl").read_text(encoding="ascii")
    if "'''" in hlsl or "\\" in hlsl:
        raise ValueError("RoadRVT.hlsl must not contain triple quotes or backslashes")
    origin, _ = mask_mapping(root / "Tools" / "Terrain" / "MASKS.md")
    return fill_polyline(hlsl, road_polyline_m(origin))


def _fill(script, name, value):
    lines = script.split("\n")
    hits = [i for i, l in enumerate(lines) if l.startswith(name + " = ")]
    if len(hits) != 1:
        raise ValueError(f'expected one "{name} = " line, found {len(hits)}')
    lines[hits[0]] = f"{name} = {value}"
    return "\n".join(lines)


def prepare(root=ROOT):
    root = pathlib.Path(root)
    script = (root / "Tools" / "Road" / "build_road_material.py").read_text(encoding="utf-8")
    hlsl = prepared_hlsl(root)
    parts = script.split("__HLSL__")
    if len(parts) != 2:
        raise ValueError(f"expected exactly one __HLSL__ marker, found {len(parts) - 1}")
    script = hlsl.join(parts)
    origin, extent = mask_mapping(root / "Tools" / "Terrain" / "MASKS.md")
    script = _fill(script, "MASK_ORIGIN_CM", repr(origin))
    script = _fill(script, "MASK_EXTENT_CM", repr(extent))
    return script


def send(script, port=52342, timeout=120):
    payload = json.dumps({"cmd": "python_run", "id": "road_v1", "params": {"script": script}}).encode("utf-8")
    with socket.create_connection(("127.0.0.1", port), timeout=timeout) as s:
        s.sendall(struct.pack(">I", len(payload)) + payload)
        head = b""
        while len(head) < 4:
            head += s.recv(4 - len(head))
        size = struct.unpack(">I", head)[0]
        body = b""
        while len(body) < size:
            body += s.recv(size - len(body))
    return json.loads(body.decode("utf-8"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--send", action="store_true", help="run it in the live editor (hold the editor gate)")
    ap.add_argument("--out", default=str(ROOT / "Saved" / "Road" / "build_road_material.sub.py"))
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
