"""Pure-Python reader for binary FBX files (7.x), numpy + zlib only.

Parses the node tree, then extracts a small scene model:
Geometry (positions, polygons, UVs, normals), Model (local TRS),
Material, Texture, Video (embedded bytes), Connections and GlobalSettings.

Usage:
    from fbx_reader import read_fbx
    scene = read_fbx("bench01.fbx")
    print(scene.summary())
"""
from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass, field

import numpy as np

MAGIC = b"Kaydara FBX Binary  \x00"

_ARRAY_DTYPES = {"f": "<f4", "d": "<f8", "l": "<i8", "i": "<i4", "b": "<u1"}


class FBXError(Exception):
    pass


@dataclass
class Node:
    name: str
    props: list
    children: list = field(default_factory=list)

    def find(self, name):
        for c in self.children:
            if c.name == name:
                return c
        return None

    def find_all(self, name):
        return [c for c in self.children if c.name == name]

    def value(self, name, default=None):
        c = self.find(name)
        if c is None or not c.props:
            return default
        return c.props[0]


# ----------------------------------------------------------------- low level

def _read_property(buf, pos):
    t = chr(buf[pos])
    pos += 1
    if t == "Y":
        return struct.unpack_from("<h", buf, pos)[0], pos + 2
    if t == "C":
        return bool(buf[pos]), pos + 1
    if t == "I":
        return struct.unpack_from("<i", buf, pos)[0], pos + 4
    if t == "F":
        return struct.unpack_from("<f", buf, pos)[0], pos + 4
    if t == "D":
        return struct.unpack_from("<d", buf, pos)[0], pos + 8
    if t == "L":
        return struct.unpack_from("<q", buf, pos)[0], pos + 8
    if t in ("S", "R"):
        n = struct.unpack_from("<I", buf, pos)[0]
        pos += 4
        raw = bytes(buf[pos:pos + n])
        pos += n
        if t == "S":
            # FBX joins "Name\x00\x01Class" -> keep the name part readable
            return raw.decode("utf-8", "replace"), pos
        return raw, pos
    if t in _ARRAY_DTYPES:
        length, enc, clen = struct.unpack_from("<III", buf, pos)
        pos += 12
        data = bytes(buf[pos:pos + clen])
        pos += clen
        if enc == 1:
            data = zlib.decompress(data)
        elif enc != 0:
            raise FBXError(f"unknown array encoding {enc}")
        arr = np.frombuffer(data, dtype=_ARRAY_DTYPES[t], count=length)
        if t == "b":
            arr = arr.astype(bool)
        return arr, pos
    raise FBXError(f"unknown property type {t!r} at {pos - 1}")


def _read_node(buf, pos, wide):
    if wide:
        end, nprops, plen = struct.unpack_from("<QQQ", buf, pos)
        pos += 24
    else:
        end, nprops, plen = struct.unpack_from("<III", buf, pos)
        pos += 12
    nlen = buf[pos]
    pos += 1
    if end == 0:
        return None, pos + nlen
    name = bytes(buf[pos:pos + nlen]).decode("ascii", "replace")
    pos += nlen
    props = []
    pend = pos + plen
    for _ in range(nprops):
        v, pos = _read_property(buf, pos)
        props.append(v)
    if pos != pend:
        raise FBXError(f"property list size mismatch in {name}: {pos} vs {pend}")
    node = Node(name, props)
    while pos < end:
        child, pos = _read_node(buf, pos, wide)
        if child is None:
            break
        node.children.append(child)
    return node, end


def parse_tree(path_or_bytes):
    """Return (version, root Node) of a binary FBX."""
    if isinstance(path_or_bytes, (bytes, bytearray, memoryview)):
        buf = memoryview(path_or_bytes)
    else:
        with open(path_or_bytes, "rb") as f:
            buf = memoryview(f.read())
    if bytes(buf[:21]) != MAGIC:
        if bytes(buf[:5]) == b"; FBX":
            raise FBXError("ASCII FBX is not supported")
        raise FBXError("not a binary FBX")
    version = struct.unpack_from("<I", buf, 23)[0]
    wide = version >= 7500
    pos = 27
    root = Node("<root>", [])
    while pos < len(buf):
        node, pos = _read_node(buf, pos, wide)
        if node is None:
            break
        root.children.append(node)
    return version, root


# ----------------------------------------------------------------- scene model

def _props70(node):
    """Properties70 -> {name: [values...]}"""
    out = {}
    if node is None:
        return out
    p = node.find("Properties70")
    if p is None:
        return out
    for P in p.find_all("P"):
        if P.props:
            out[P.props[0]] = P.props[4:]
    return out


def _clean_name(s):
    if isinstance(s, str):
        return s.split("\x00\x01")[0]
    return s


@dataclass
class LayerUV:
    name: str
    uv: np.ndarray          # (N,2)
    index: np.ndarray | None
    mapping: str
    reference: str


@dataclass
class Geometry:
    id: int
    name: str
    vertices: np.ndarray            # (V,3) float64
    poly_index: np.ndarray          # raw PolygonVertexIndex
    uv_layers: list = field(default_factory=list)
    normals: np.ndarray | None = None
    normal_index: np.ndarray | None = None
    normal_mapping: str = ""
    normal_reference: str = ""
    material_ids: np.ndarray | None = None
    material_mapping: str = ""

    # derived --------------------------------------------------------------
    def polygons(self):
        """Return (poly_vertex_indices, poly_start, poly_size)."""
        pvi = self.poly_index.astype(np.int64)
        ends = pvi < 0
        idx = np.where(ends, ~pvi, pvi)
        end_pos = np.nonzero(ends)[0]
        starts = np.concatenate(([0], end_pos[:-1] + 1))
        sizes = end_pos - starts + 1
        return idx, starts, sizes

    def triangulate(self):
        """Fan-triangulate. Returns (tri_corner (T,3) indices into polygon-vertex
        array, poly_of_tri (T,))."""
        idx, starts, sizes = self.polygons()
        ntri = np.maximum(sizes - 2, 0)
        total = int(ntri.sum())
        poly_of_tri = np.repeat(np.arange(len(sizes)), ntri)
        # k-th triangle within its polygon
        first = np.repeat(np.cumsum(ntri) - ntri, ntri)
        k = np.arange(total) - first
        s = starts[poly_of_tri]
        corners = np.stack([s, s + k + 1, s + k + 2], axis=1)
        return corners, poly_of_tri

    def _per_corner(self, data, index, mapping, reference, n_corner, corner_vertex, poly_of_corner):
        if data is None:
            return None
        if reference in ("IndexToDirect", "Index") and index is not None:
            src = index.astype(np.int64)
        else:
            src = None
        if mapping == "ByPolygonVertex":
            sel = src if src is not None else np.arange(n_corner)
        elif mapping in ("ByVertice", "ByVertex", "ByControlPoint"):
            sel = src[corner_vertex] if src is not None else corner_vertex
        elif mapping == "ByPolygon":
            sel = src[poly_of_corner] if src is not None else poly_of_corner
        elif mapping == "AllSame":
            sel = np.zeros(n_corner, dtype=np.int64)
        else:
            return None
        sel = np.clip(sel, 0, len(data) - 1)
        return data[sel]

    def corner_attributes(self):
        """Per polygon-vertex (corner) vertex index, uv (layer 0), normal."""
        idx, starts, sizes = self.polygons()
        n = len(idx)
        poly_of_corner = np.repeat(np.arange(len(sizes)), sizes)
        uv = None
        if self.uv_layers:
            L = self.uv_layers[0]
            uv = self._per_corner(L.uv, L.index, L.mapping, L.reference, n, idx, poly_of_corner)
        nrm = self._per_corner(self.normals, self.normal_index, self.normal_mapping,
                               self.normal_reference, n, idx, poly_of_corner)
        return idx, uv, nrm


@dataclass
class Model:
    id: int
    name: str
    kind: str
    translation: np.ndarray
    rotation: np.ndarray
    scaling: np.ndarray
    pre_rotation: np.ndarray
    rotation_order: int = 0
    geometric_translation: np.ndarray | None = None
    geometric_rotation: np.ndarray | None = None
    geometric_scaling: np.ndarray | None = None


@dataclass
class Material:
    id: int
    name: str
    props: dict


@dataclass
class Texture:
    id: int
    name: str
    filename: str
    relative_filename: str


@dataclass
class Video:
    id: int
    name: str
    filename: str
    relative_filename: str
    content: bytes


@dataclass
class Scene:
    path: str
    version: int
    root: Node
    geometries: dict
    models: dict
    materials: dict
    textures: dict
    videos: dict
    connections: list       # (type, child, parent, prop)
    global_settings: dict

    # connection helpers ----------------------------------------------------
    def parents(self, cid):
        return [(p, t, prop) for t, c, p, prop in self.connections if c == cid]

    def children(self, pid):
        return [(c, t, prop) for t, c, p, prop in self.connections if p == pid]

    def model_of_geometry(self, gid):
        for p, _, _ in self.parents(gid):
            if p in self.models:
                return self.models[p]
        return None

    def model_parent(self, mid):
        for p, _, _ in self.parents(mid):
            if p in self.models:
                return self.models[p]
        return None

    def materials_of_model(self, mid):
        return [self.materials[c] for c, _, _ in self.children(mid) if c in self.materials]

    def textures_of_material(self, matid):
        """Return [(texture, property_name)]"""
        return [(self.textures[c], prop) for c, _, prop in self.children(matid) if c in self.textures]

    def video_of_texture(self, tid):
        for c, _, _ in self.children(tid):
            if c in self.videos:
                return self.videos[c]
        return None

    @property
    def unit_scale(self):
        return float(self.global_settings.get("UnitScaleFactor", 1.0))

    def summary(self, depth=2):
        lines = [f"{self.path}  FBX v{self.version}"]

        def walk(n, d):
            if d > depth:
                return
            ps = []
            for p in n.props[:3]:
                if isinstance(p, np.ndarray):
                    ps.append(f"arr[{p.dtype}x{len(p)}]")
                elif isinstance(p, bytes):
                    ps.append(f"bytes[{len(p)}]")
                else:
                    ps.append(repr(_clean_name(p))[:40])
            lines.append("  " * d + f"{n.name} ({', '.join(ps)}) children={len(n.children)}")
            for c in n.children:
                walk(c, d + 1)

        for c in self.root.children:
            walk(c, 0)
        lines.append(f"GlobalSettings: {self.global_settings}")
        for g in self.geometries.values():
            _, _, sizes = g.polygons()
            lines.append(f"Geometry {g.name!r}: {len(g.vertices)} verts, {len(sizes)} polys, "
                         f"{int(np.maximum(sizes - 2, 0).sum())} tris, uv layers={len(g.uv_layers)}, "
                         f"normals={'yes' if g.normals is not None else 'no'}")
        for m in self.models.values():
            lines.append(f"Model {m.name!r} [{m.kind}] T={m.translation.tolist()} "
                         f"R={m.rotation.tolist()} S={m.scaling.tolist()} Pre={m.pre_rotation.tolist()}")
        for m in self.materials.values():
            lines.append(f"Material {m.name!r}: textures="
                         f"{[(t.name, p) for t, p in self.textures_of_material(m.id)]}")
        for v in self.videos.values():
            lines.append(f"Video {v.name!r}: {v.relative_filename!r} embedded={len(v.content)} bytes")
        return "\n".join(lines)


def _vec3(props, key, default):
    v = props.get(key)
    if not v:
        return np.array(default, dtype=np.float64)
    return np.array([float(x) for x in v[:3]], dtype=np.float64)


def _parse_geometry(n):
    gid = n.props[0]
    name = _clean_name(n.props[1]) if len(n.props) > 1 else ""
    verts_node = n.find("Vertices")
    pvi_node = n.find("PolygonVertexIndex")
    if verts_node is None or pvi_node is None:
        return None
    verts = np.asarray(verts_node.props[0], dtype=np.float64).reshape(-1, 3)
    geo = Geometry(gid, name, verts, np.asarray(pvi_node.props[0]))
    for L in n.find_all("LayerElementUV"):
        uv = L.find("UV")
        if uv is None:
            continue
        ui = L.find("UVIndex")
        geo.uv_layers.append(LayerUV(
            name=L.value("Name", ""),
            uv=np.asarray(uv.props[0], dtype=np.float64).reshape(-1, 2),
            index=np.asarray(ui.props[0]) if ui is not None else None,
            mapping=L.value("MappingInformationType", ""),
            reference=L.value("ReferenceInformationType", ""),
        ))
    L = n.find("LayerElementNormal")
    if L is not None and L.find("Normals") is not None:
        geo.normals = np.asarray(L.find("Normals").props[0], dtype=np.float64).reshape(-1, 3)
        ni = L.find("NormalsIndex") or L.find("NormalIndex")
        geo.normal_index = np.asarray(ni.props[0]) if ni is not None else None
        geo.normal_mapping = L.value("MappingInformationType", "")
        geo.normal_reference = L.value("ReferenceInformationType", "")
    L = n.find("LayerElementMaterial")
    if L is not None and L.find("Materials") is not None:
        geo.material_ids = np.asarray(L.find("Materials").props[0])
        geo.material_mapping = L.value("MappingInformationType", "")
    return geo


def read_fbx(path):
    version, root = parse_tree(path)
    gs = {}
    gsn = root.find("GlobalSettings")
    if gsn is not None:
        for k, v in _props70(gsn).items():
            if k in ("UpAxis", "UpAxisSign", "FrontAxis", "FrontAxisSign", "CoordAxis",
                     "CoordAxisSign", "UnitScaleFactor", "OriginalUnitScaleFactor",
                     "OriginalUpAxis", "OriginalUpAxisSign") and v:
                gs[k] = v[0]
    geometries, models, materials, textures, videos = {}, {}, {}, {}, {}
    objs = root.find("Objects")
    if objs is not None:
        for n in objs.children:
            if n.name == "Geometry" and len(n.props) >= 3 and n.props[2] == "Mesh":
                g = _parse_geometry(n)
                if g is not None:
                    geometries[g.id] = g
            elif n.name == "Model":
                p = _props70(n)
                models[n.props[0]] = Model(
                    id=n.props[0], name=_clean_name(n.props[1]),
                    kind=n.props[2] if len(n.props) > 2 else "",
                    translation=_vec3(p, "Lcl Translation", (0, 0, 0)),
                    rotation=_vec3(p, "Lcl Rotation", (0, 0, 0)),
                    scaling=_vec3(p, "Lcl Scaling", (1, 1, 1)),
                    pre_rotation=_vec3(p, "PreRotation", (0, 0, 0)),
                    rotation_order=int(p.get("RotationOrder", [0])[0]),
                    geometric_translation=_vec3(p, "GeometricTranslation", (0, 0, 0)),
                    geometric_rotation=_vec3(p, "GeometricRotation", (0, 0, 0)),
                    geometric_scaling=_vec3(p, "GeometricScaling", (1, 1, 1)),
                )
            elif n.name == "Material":
                materials[n.props[0]] = Material(n.props[0], _clean_name(n.props[1]), _props70(n))
            elif n.name == "Texture":
                textures[n.props[0]] = Texture(
                    n.props[0], _clean_name(n.props[1]),
                    n.value("FileName", "") or "", n.value("RelativeFilename", "") or "")
            elif n.name == "Video":
                c = n.find("Content")
                content = c.props[0] if (c is not None and c.props and isinstance(c.props[0], bytes)) else b""
                videos[n.props[0]] = Video(
                    n.props[0], _clean_name(n.props[1]),
                    n.value("Filename", "") or "", n.value("RelativeFilename", "") or "", content)
    conns = []
    cn = root.find("Connections")
    if cn is not None:
        for C in cn.find_all("C"):
            t = C.props[0]
            prop = C.props[3] if (t == "OP" and len(C.props) > 3) else None
            conns.append((t, C.props[1], C.props[2], prop))
    return Scene(str(path), version, root, geometries, models, materials, textures,
                 videos, conns, gs)


# ----------------------------------------------------------------- transforms

def _euler_matrix(deg, order=0):
    """FBX Euler (degrees) -> 3x3. order 0 = eXYZ (R = Rz*Ry*Rx)."""
    x, y, z = np.radians(deg)
    cx, sx, cy, sy, cz, sz = np.cos(x), np.sin(x), np.cos(y), np.sin(y), np.cos(z), np.sin(z)
    Rx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    Ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    Rz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
    seq = {0: (Rx, Ry, Rz), 1: (Rx, Rz, Ry), 2: (Ry, Rz, Rx), 3: (Ry, Rx, Rz),
           4: (Rz, Rx, Ry), 5: (Rz, Ry, Rx)}.get(order, (Rx, Ry, Rz))
    # first applied is seq[0]
    return seq[2] @ seq[1] @ seq[0]


def model_local_matrix(m: Model):
    M = np.eye(4)
    R = _euler_matrix(m.pre_rotation) @ _euler_matrix(m.rotation, m.rotation_order)
    M[:3, :3] = R @ np.diag(m.scaling)
    M[:3, 3] = m.translation
    return M


def model_geometric_matrix(m: Model):
    M = np.eye(4)
    M[:3, :3] = _euler_matrix(m.geometric_rotation) @ np.diag(m.geometric_scaling)
    M[:3, 3] = m.geometric_translation
    return M


def model_world_matrix(scene: Scene, m: Model):
    M = model_local_matrix(m)
    seen = {m.id}
    p = scene.model_parent(m.id)
    while p is not None and p.id not in seen:
        seen.add(p.id)
        M = model_local_matrix(p) @ M
        p = scene.model_parent(p.id)
    return M


def axis_to_zup_matrix(gs: dict):
    """Rotation mapping the file's axis system to right-handed Z-up (X right,
    Y forward-ish).  Uses UpAxis/UpAxisSign/FrontAxis/CoordAxis."""
    up = int(gs.get("UpAxis", 1))
    up_s = int(gs.get("UpAxisSign", 1))
    front = int(gs.get("FrontAxis", 2))
    front_s = int(gs.get("FrontAxisSign", 1))
    coord = int(gs.get("CoordAxis", 0))
    coord_s = int(gs.get("CoordAxisSign", 1))
    B = np.zeros((3, 3))
    # rows of B = file axes expressed in target frame: target X=right(coord), Y=front, Z=up
    B[0, coord] = coord_s
    B[1, front] = front_s
    B[2, up] = up_s
    # B maps file coords -> (right, front, up). Right-handed check: if det<0 flip Y.
    if np.linalg.det(B) < 0:
        B[1] *= -1
    return B


if __name__ == "__main__":
    import sys
    for p in sys.argv[1:]:
        print(read_fbx(p).summary(depth=int(2)))
