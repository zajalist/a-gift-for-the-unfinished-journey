"""Root-only editor execution: read the actual carrier source surface into JSON.

No actor creation, capture, source mesh edits, Content saves, or GPU work.
GeometryScript signatures were read from the installed UE 5.8 headers.
"""
import datetime
import hashlib
import json
from pathlib import Path
import unreal

ROOT = Path('D:/UnrealEngine/saskartarad')
OUT = ROOT / 'Saved/Verification/gaussian_memory_20261001/loading_car'
ASSET = '/Game/SaskartaGaea/Characters/Carrier/Full/SK_CarrierFull'
mesh = unreal.load_asset(ASSET)
assert isinstance(mesh, unreal.SkeletalMesh), ASSET
dm = unreal.DynamicMesh()
lod = unreal.GeometryScriptMeshReadLOD()
lod.lod_type = unreal.GeometryScriptLODType.SOURCE_MODEL
lod.lod_index = 0
dm, outcome = unreal.GeometryScript_AssetUtils.copy_mesh_from_skeletal_mesh(
    mesh, dm, unreal.GeometryScriptCopyMeshFromAssetOptions(), lod)
assert outcome == unreal.GeometryScriptOutcomePins.SUCCESS, outcome
vertices = unreal.GeometryScript_MeshQueries.get_all_vertex_positions(dm, False)
assert not vertices[2], 'Vertex ID gaps require explicit mapping'
points = unreal.GeometryScript_List.convert_vector_list_to_array(vertices[1])
triangles = unreal.GeometryScript_MeshQueries.get_all_triangle_indices(dm, False)
assert not triangles[2], 'Triangle ID gaps require explicit mapping'
faces = unreal.GeometryScript_List.convert_triangle_list_to_array(triangles[1])
assert 3 <= len(points) <= 250000 and 1 <= len(faces) <= 350000
material_ids = unreal.GeometryScript_Materials.get_all_triangle_material_i_ds(dm)
ids = unreal.GeometryScript_List.convert_index_list_to_array(material_ids[1]) if material_ids[2] else [0] * len(faces)
assert len(ids) == len(faces)
materials = []
for slot in mesh.get_editor_property('materials'):
    material = slot.get_editor_property('material_interface')
    materials.append({'slot': str(slot.get_editor_property('material_slot_name')),
                      'material': material.get_path_name() if material else None})
data = {'representation': 'actual_mesh_surface_source', 'trained': False,
        'source_asset': mesh.get_path_name(), 'source_lod': 0,
        'source_kind': 'skeletal_source_model_reference_pose', 'units': 'UE_local_centimeters',
        'engine': unreal.SystemLibrary.get_engine_version(),
        'extracted_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'vertices': [[p.x, p.y, p.z] for p in points],
        'triangles': [[t.x, t.y, t.z] for t in faces],
        'triangle_material_ids': ids, 'materials': materials,
        'source_mesh_modified': False, 'actors_spawned': False}
OUT.mkdir(parents=True, exist_ok=True)
target = OUT / 'carrier_geometry.json'
assert not target.exists(), 'Retain the original export; do not silently overwrite'
target.write_text(json.dumps(data, separators=(',', ':'), allow_nan=False), encoding='utf-8')
print('LOADING_CAR_GEOMETRY ' + json.dumps({'path': str(target), 'source_asset': ASSET,
    'vertices': len(points), 'triangles': len(faces), 'materials': materials,
    'sha256': hashlib.sha256(target.read_bytes()).hexdigest()}))
