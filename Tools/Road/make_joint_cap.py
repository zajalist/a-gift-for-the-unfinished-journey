"""Write the road joint cap mesh: a flat disc with radial UVs (world sprint, Task V1).

    python Tools/Road/make_joint_cap.py      # -> Saved/Road/SM_Saskarta_RoadJointCap.obj

Why: the road ribbon is one straight spline-mesh segment per spline segment
(RoadSpline is a polyline, zero tangents), so where two segments meet at an
angle the outer corner is left uncovered: a wedge of the road core with no
ribbon over it (76 deg at spline point 17, the hairpin at 3,850 m). The mask
(T_Saskarta_RoadInfluence.R) is continuous there, but nothing writes the road
into the RVT. One cap per spline control point fills that wedge.

The disc's radius is the ribbon's half-width (450 cm) and its UV.y runs from
0.5 at the centre to 1.0 at the rim, so M_Saskarta_RoadRVT's RoadFrame
    RoadU = (UV.y * 2 - 1) * RibbonHalfWidth / RoadHalfWidth
gives |RoadU| = distance from the joint in road half-widths, which is exactly
the ribbon's own |RoadU| at a point whose nearest centre-line point is the
joint. UV.x runs once around (0..1), so RoadV follows the circle there.

The OBJ is in a right-handed, Z-up frame with counter-clockwise faces seen from
+Z; the importer converts it to Unreal's frame. Deterministic: no randomness.
"""
import math
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
RADIUS_CM = 450.0
SECTORS = 48
RINGS = 6          # ring 0 is a small inner ring, not a single centre vertex,
INNER_CM = 10.0    # so no triangle has a degenerate UV (RoadFrame divides by det)


def build():
    verts, uvs, faces = [], [], []
    radii = [INNER_CM + (RADIUS_CM - INNER_CM) * k / (RINGS - 1) for k in range(RINGS)]
    # centre fan vertex
    verts.append((0.0, 0.0, 0.0))
    uvs.append((0.5, 0.5))
    for r in radii:
        for s in range(SECTORS + 1):          # duplicate the seam so UV.x runs 0..1
            a = 2.0 * math.pi * s / SECTORS
            verts.append((r * math.cos(a), r * math.sin(a), 0.0))
            uvs.append((s / SECTORS, 0.5 + 0.5 * r / RADIUS_CM))

    def idx(ring, s):
        return 1 + ring * (SECTORS + 1) + s

    for s in range(SECTORS):
        faces.append((0, idx(0, s), idx(0, s + 1)))
    for ring in range(RINGS - 1):
        for s in range(SECTORS):
            a, b = idx(ring, s), idx(ring, s + 1)
            c, d = idx(ring + 1, s), idx(ring + 1, s + 1)
            faces.append((a, c, d))
            faces.append((a, d, b))
    return verts, uvs, faces


def write_obj(path):
    verts, uvs, faces = build()
    lines = ["# SM_Saskarta_RoadJointCap: Tools/Road/make_joint_cap.py", "o SM_Saskarta_RoadJointCap"]
    lines += [f"v {x:.4f} {y:.4f} {z:.4f}" for x, y, z in verts]
    lines += [f"vt {u:.6f} {v:.6f}" for u, v in uvs]
    lines += ["vn 0 0 1"]
    lines += [f"f {a + 1}/{a + 1}/1 {b + 1}/{b + 1}/1 {c + 1}/{c + 1}/1" for a, b, c in faces]
    pathlib.Path(path).write_text("\n".join(lines) + "\n", encoding="ascii")


def read_obj(path):
    verts, uvs, faces = [], [], []
    for line in pathlib.Path(path).read_text(encoding="ascii").splitlines():
        parts = line.split()
        if not parts:
            continue
        if parts[0] == "v":
            verts.append(tuple(float(p) for p in parts[1:4]))
        elif parts[0] == "vt":
            uvs.append(tuple(float(p) for p in parts[1:3]))
        elif parts[0] == "f":
            faces.append(tuple(int(p.split("/")[0]) - 1 for p in parts[1:4]))
    return verts, uvs, faces


def main():
    out = ROOT / "Saved" / "Road" / "SM_Saskarta_RoadJointCap.obj"
    out.parent.mkdir(parents=True, exist_ok=True)
    write_obj(out)
    v, _, f = read_obj(out)
    print(f"wrote {out}: {len(v)} vertices, {len(f)} triangles")
    return 0


if __name__ == "__main__":
    sys.exit(main())
