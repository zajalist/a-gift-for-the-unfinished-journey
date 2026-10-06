"""Root embedded-Python fallback: policy-visible direct JSON source triangles.

Set CHUNK for each bounded read. No filesystem, encoded transport, hashes,
process modules or UObject modifications. Every number remains reviewable.
"""
import json
import math
import unreal

CHUNK = 0
TRIANGLE_SAMPLES = 1200
MAX_CHARACTERS = 7400
ASSET = '/Game/SaskartaGaea/Characters/Carrier/Full/SK_CarrierFull'
mesh = unreal.load_asset(ASSET)
assert isinstance(mesh, unreal.SkeletalMesh)
dm = unreal.DynamicMesh()
lod = unreal.GeometryScriptMeshReadLOD()
lod.lod_type = unreal.GeometryScriptLODType.SOURCE_MODEL
lod.lod_index = 0
dm, outcome = unreal.GeometryScript_AssetUtils.copy_mesh_from_skeletal_mesh(mesh, dm, unreal.GeometryScriptCopyMeshFromAssetOptions(), lod)
assert outcome == unreal.GeometryScriptOutcomePins.SUCCESS
vertices = unreal.GeometryScript_MeshQueries.get_all_vertex_positions(dm, False)
assert not vertices[2]
points = unreal.GeometryScript_List.convert_vector_list_to_array(vertices[1])
triangles = unreal.GeometryScript_MeshQueries.get_all_triangle_indices(dm, False)
assert not triangles[2]
faces = unreal.GeometryScript_List.convert_triangle_list_to_array(triangles[1])
assert 3 <= len(points) <= 250000 and 1 <= len(faces) <= 350000
mid = unreal.GeometryScript_Materials.get_all_triangle_material_i_ds(dm)
ids = unreal.GeometryScript_List.convert_index_list_to_array(mid[1]) if mid[2] else [0]*len(faces)
assert len(ids) == len(faces)
materials = []
for slot in mesh.get_editor_property('materials'):
    mat = slot.get_editor_property('material_interface')
    materials.append({'slot': str(slot.get_editor_property('material_slot_name')), 'material': mat.get_path_name() if mat else None})
low = [min(p.x for p in points), min(p.y for p in points), min(p.z for p in points)]
high = [max(p.x for p in points), max(p.y for p in points), max(p.z for p in points)]
origin = [(a+b)*.5 for a, b in zip(low, high)]
quantum_cm = .5
cumulative = []
area = 0.
for face in faces:
    a, b, c = points[face.x], points[face.y], points[face.z]
    u, v = b-a, c-a
    cross = [u.y*v.z-u.z*v.y, u.z*v.x-u.x*v.z, u.x*v.y-u.y*v.x]
    area += math.sqrt(sum(x*x for x in cross))*.5
    cumulative.append(area)
assert area > 0
rows = []
index = 0
for sample in range(TRIANGLE_SAMPLES):
    target_area = area*(sample+.5)/TRIANGLE_SAMPLES
    while index < len(faces)-1 and cumulative[index] < target_area:
        index += 1
    face = faces[index]
    row = []
    for vertex in (face.x, face.y, face.z):
        p = points[vertex]
        row.extend(int(round((x-o)/quantum_cm)) for x, o in zip((p.x, p.y, p.z), origin))
    row.append(ids[index])
    rows.append(row)
metadata = {'source_asset': ASSET, 'source_lod': 0,
    'source_kind': 'skeletal_source_model_reference_pose', 'source_vertices': len(points), 'source_triangles': len(faces),
    'source_bounds_cm': [low, high], 'quantum_cm': quantum_cm, 'origin_cm': origin,
    'materials': materials, 'sample_triangles': TRIANGLE_SAMPLES,
    'packing': 'direct integer JSON rows: 9 actual UE coordinate offsets/quantum, then material ID',
    'sampling': 'deterministic area-stratified source triangle subset'}
metadata_size = len(json.dumps(metadata,separators=(',',':')))
chunks = []
current = []
current_size = metadata_size + 160
for row in rows:
    row_size = len(json.dumps(row,separators=(',',':'))) + 1
    if current and current_size + row_size > MAX_CHARACTERS:
        chunks.append(current)
        current = []
        current_size = metadata_size + 160
    current.append(row)
    current_size += row_size
if current:
    chunks.append(current)
assert 0 <= CHUNK < len(chunks)
metadata.update({'chunk': CHUNK, 'chunks': len(chunks),
    'offset': sum(len(c) for c in chunks[:CHUNK]), 'rows': chunks[CHUNK]})
text = json.dumps(metadata,separators=(',',':'))
assert len(text) <= MAX_CHARACTERS
print('LOADING_CAR_SURFACE_CHUNK '+text)
