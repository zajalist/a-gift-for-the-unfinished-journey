"""Offline skinning of the authored Traveller body for animation contact checks.

Only the source body is used: the radio and staff are independent props. Source
FBX centimetres map to imported component space as (x, -y, z). A bounded editor
probe compares real imported vertex positions/weights before installation.
"""
from functools import lru_cache
from pathlib import Path
import sys

import numpy as np

import samyor_reveal as rig

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "Tools/ModelReview"))
from fbx_reader import read_fbx


def rotation(q):
    q = rig.qnorm(q)
    return np.array([rig.qrot(q, v) for v in ((1, 0, 0), (0, 1, 0), (0, 0, 1))]).T


@lru_cache(maxsize=3)
def source_mesh(mesh_name="tripo_mesh_8efd9b8d.001"):
    scene = read_fbx(str(ROOT / "SourceArt/Characters/Traveller/traveller01_animated.fbx"))
    bodies = [g for g in scene.geometries.values() if g.name == mesh_name]
    assert len(bodies) == 1
    body = bodies[0]
    points = body.vertices * (100.0, -100.0, 100.0)
    objects = {n.props[0]: n for n in scene.root.find("Objects").children
               if n.props and isinstance(n.props[0], int)}
    skins = {c[1] for c in scene.connections if c[2] == body.id
             and c[1] in objects and objects[c[1]].name == "Deformer"}
    clusters = [objects[c[1]] for c in scene.connections if c[2] in skins
                and c[1] in objects and objects[c[1]].name == "Deformer"]
    entries, total = [], np.zeros(len(points))
    for cluster in clusters:
        indices = cluster.value("Indexes")
        if indices is None or len(indices) == 0:
            continue
        name = cluster.props[1].split("\x00")[0].removeprefix("mixamorig:")
        name = {"staff01":"staff011", "recorder01":"recorder011"}.get(name,name)
        assert name in rig.REF_W, name
        indices = indices.astype(int)
        weights = cluster.value("Weights")
        reference = rig.REF_W[name]
        source_bind = cluster.value("TransformLink").reshape(4, 4).T[:3, 3] * (-1, 1, 1)
        assert np.linalg.norm(source_bind - reference[0]) < 0.01, (name, source_bind, reference[0])
        offsets = ((points[indices] - reference[0]) @ rotation(reference[1])) / reference[2]
        entries.append((name, indices, weights, offsets))
        total[indices] += weights
    assert np.max(np.abs(total - 1.0)) < 0.001, (total.min(), total.max())
    polygon_indices, _, _ = body.polygons()
    corners, _ = body.triangulate()
    return points, entries, polygon_indices[corners]


def source_body():
    return source_mesh()


def skin(pose, mesh_name="tripo_mesh_8efd9b8d.001"):
    """Actual source body vertices after linear blend skinning, component cm."""
    points, entries, _ = source_mesh(mesh_name)
    result = np.zeros_like(points)
    world = rig.fk(pose)
    for bone, indices, weights, offsets in entries:
        position, quat, scale = world[bone]
        posed = (offsets * scale) @ rotation(quat).T + position
        result[indices] += posed * weights[:, None]
    return result


def shift_root(pose, offset):
    """Move every bone and attached prop by a component-space offset."""
    local = dict(pose)
    world = rig.fk(local)
    parent = world[rig.PARENT['root']]
    delta = rig.qrot(rig.qconj(parent[1]), offset)
    delta = tuple(delta[i] / parent[2][i] for i in range(3))
    position, quat, scale = local['root']
    local['root'] = (rig.vadd(position, delta), quat, scale)
    return local


def ground(pose, clearance=0.4):
    """Support the skinned body on its lowest real surface; no pivot estimate."""
    return shift_root(pose, (0, 0, float(clearance - skin(pose)[:, 2].min())))
