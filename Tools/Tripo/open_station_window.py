"""Make the generated station's four painted panes real openings, offline.

Keeps the original GLB intact. Clips only four measured pane prisms; source
positions, UVs and normals interpolate at the cut. The output is still opaque,
with an open window rather than painted glass. No Unreal or network calls.
"""
from pathlib import Path
import copy
import hashlib
import json
import numpy as np

import tripo_ingest as ti

ROOT = Path(__file__).resolve().parents[2]
FOLDER = ROOT / 'SourceArt/Tripo/20261001/S26_radio_station_shell'
SOURCE = FOLDER / 'S26_radio_station_shell_ue.glb'
OUTPUT = FOLDER / 'S26_radio_station_shell_open_window_ue.glb'
# glTF world centimetres after the prepared base pivot/uniform scale.
# Brass borders/mullions are excluded. Depth reaches through the generated
# side wall and interior recess, but cannot reach the opposite station wall.
PANES = [((xa, ya, -210.0), (xb, yb, -85.0))
         for xa, xb in ((-46.0, -11.0), (-2.0, 48.0))
         for ya, yb in ((81.0, 128.0), (136.0, 171.0))]


def split_plane(poly, axis, boundary, positive_inside):
    """Split position/normal/UV rows by one plane, interpolating all fields."""
    inside, outside = [], []
    if len(poly) == 0:
        return inside, outside
    prev = poly[-1]
    pd = (prev[axis] - boundary) * (1 if positive_inside else -1)
    for cur in poly:
        cd = (cur[axis] - boundary) * (1 if positive_inside else -1)
        if (pd >= 0) != (cd >= 0):
            point = prev + (cur - prev) * (pd / (pd - cd))
            inside.append(point)
            outside.append(point)
        (inside if cd >= 0 else outside).append(cur)
        prev, pd = cur, cd
    return inside, outside


def subtract_box(poly, lo, hi):
    """Partition a polygon outside an AABB; discard its inside remainder."""
    remainder, pieces = list(poly), []
    for axis in range(3):
        for boundary, positive in ((lo[axis], True), (hi[axis], False)):
            remainder, outside = split_plane(remainder, axis, boundary, positive)
            if len(outside) >= 3:
                pieces.append(outside)
            if len(remainder) < 3:
                return pieces
    return pieces


def triangulate(poly):
    for i in range(1, len(poly)-1):
        tri = np.array((poly[0], poly[i], poly[i+1]))
        if np.linalg.norm(np.cross(tri[1,:3]-tri[0,:3], tri[2,:3]-tri[0,:3])) > 1e-8:
            yield tri


def cut_triangles(vertices, triangles, boxes=PANES):
    """Keep unchanged vertices shared and append only newly clipped faces."""
    out_vertices = list(vertices)
    out_triangles = []
    changed = 0
    for indices in triangles:
        tri = vertices[indices]
        lo, hi = tri[:,:3].min(0), tri[:,:3].max(0)
        candidates = [(a,b) for a,b in boxes if np.all(hi >= a) and np.all(lo <= b)]
        if not candidates:
            out_triangles.append(indices)
            continue
        pieces = [tri]
        for a,b in candidates:
            pieces = [piece for poly in pieces for piece in subtract_box(poly,a,b)]
        changed += 1
        for poly in pieces:
            for clipped in triangulate(poly):
                first = len(out_vertices)
                out_vertices.extend(clipped)
                out_triangles.append((first, first+1, first+2))
    return np.asarray(out_vertices), np.asarray(out_triangles, dtype=np.uint32), changed


def append_accessor(doc, blob, array, dtype, component_type, kind, bounds=False):
    array = np.ascontiguousarray(array, dtype=dtype)
    blob += b'\0' * (-len(blob) % 4)
    view = len(doc['bufferViews'])
    doc['bufferViews'].append(dict(buffer=0, byteOffset=len(blob), byteLength=array.nbytes))
    blob += array.tobytes()
    acc = dict(bufferView=view, componentType=component_type, count=len(array), type=kind)
    if bounds:
        acc.update(min=array.min(0).tolist(), max=array.max(0).tolist())
    index = len(doc['accessors'])
    doc['accessors'].append(acc)
    return index, blob


def build(source=SOURCE, output=OUTPUT):
    doc, blob = ti.read_glb(source)
    doc = copy.deepcopy(doc)
    instances = ti._mesh_instances(doc)
    assert len(instances) == 1 and len(doc['meshes']) == 1
    mesh_i, transform = instances[0]
    prims = doc['meshes'][mesh_i]['primitives']
    assert len(prims) == 1 and set(prims[0]['attributes']) == {'POSITION','NORMAL','TEXCOORD_0'}
    prim = prims[0]
    pos = ti.read_accessor(doc,blob,prim['attributes']['POSITION'])
    pos = (pos @ transform[:3,:3].T + transform[:3,3]) * 100
    normal = ti.read_accessor(doc,blob,prim['attributes']['NORMAL']) @ np.linalg.inv(transform[:3,:3])
    normal /= np.linalg.norm(normal,axis=1,keepdims=True)
    uv = ti.read_accessor(doc,blob,prim['attributes']['TEXCOORD_0'])
    triangles = ti.read_accessor(doc,blob,prim['indices']).astype(int).reshape(-1,3)
    vertices, faces, changed = cut_triangles(np.column_stack((pos,normal,uv)),triangles)
    vertices[:,3:6] /= np.linalg.norm(vertices[:,3:6],axis=1,keepdims=True)
    attrs = {}
    for name, values, kind in [('POSITION',vertices[:,:3]/100,'VEC3'),
                               ('NORMAL',vertices[:,3:6],'VEC3'),('TEXCOORD_0',vertices[:,6:],'VEC2')]:
        attrs[name], blob = append_accessor(doc,blob,values,np.float32,5126,kind,name=='POSITION')
    index,blob = append_accessor(doc,blob,faces.reshape(-1,1),np.uint32,5125,'SCALAR')
    doc['meshes'] = [dict(name='S26_radio_station_open_window',primitives=[dict(attributes=attrs,indices=index,material=prim['material'],mode=4)])]
    doc['nodes'] = [dict(mesh=0,name='S26_radio_station_open_window')]
    doc['scenes'] = [dict(nodes=[0])]
    doc['scene'] = 0
    doc['buffers'] = [dict(byteLength=len(blob))]
    output = Path(output)
    ti.write_glb(output,doc,blob)
    report = dict(source=str(Path(source).relative_to(ROOT)), output=str(output.relative_to(ROOT)),
                  source_sha256=hashlib.sha256(Path(source).read_bytes()).hexdigest(),
                  output_sha256=hashlib.sha256(output.read_bytes()).hexdigest(),
                  changed_source_faces=changed, source_triangles=len(triangles), output_triangles=len(faces),
                  pane_prisms_cm=PANES, stats=ti.glb_stats(output),
                  acceptance='Offline geometry prepared; editor fit, window sightline and exterior/interior renders pending.')
    (output.parent/'open_window_report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:report[k] for k in ('changed_source_faces','source_triangles','output_triangles','output_sha256')}))
    return report


if __name__ == '__main__':
    build()
