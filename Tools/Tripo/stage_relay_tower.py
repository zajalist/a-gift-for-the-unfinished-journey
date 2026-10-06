"""Validate the S26 relay tower and prepare its guarded Unreal import packet.

No command in this file starts Unreal. The current 1.86M-triangle review GLB is
valid for dimensional review only; `packet` requires a distinct optimized
derivative and an explicitly approved triangle ceiling.

    python Tools/Tripo/stage_relay_tower.py validate
    python Tools/Tripo/stage_relay_tower.py validate --mesh PATH --max-triangles N
    python Tools/Tripo/stage_relay_tower.py packet --mesh PATH --max-triangles N \
        --x X --y Y --z Z --support-receipt RECEIPT.json
"""
import argparse
import json
import math
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOWER = ROOT / 'SourceArt/Tripo/20261003/S26_VictorianRadioStation'
REVIEW = ROOT / 'Saved/Ending/RelayTower/SM_S26_RelayTower_Review.glb'
MAPS = {
    'BC': TOWER / 'extracted/tower_basecolor_S26_RelayTower_ReUV_Fine_8k_refined.png',
    'N': TOWER / 'extracted/tower_normal_S26_RelayTower_ReUV_Fine_8k.png',
    'ORM': TOWER / 'extracted/tower_orm_S26_RelayTower_ReUV_Fine_8k.png',
}
OUT = ROOT / 'Saved/Ending/RelayTower/import_packet'
DEST = '/Game/SaskartaGaea/Environment/SummitRelay'
REVIEW_TRIS = 1_861_164
TARGET_HEIGHT_CM = 2000.0
REJECTED_PLAN_XY_CM = (296649.5, 484541.1)


def glb_json(path):
    with path.open('rb') as handle:
        header = handle.read(20)
        if len(header) != 20:
            raise ValueError(f'Incomplete GLB: {path}')
        magic, version, total, chunk_len, chunk_type = struct.unpack('<IIIII', header)
        if magic != 0x46546C67 or version != 2 or total != path.stat().st_size or chunk_type != 0x4E4F534A:
            raise ValueError(f'Invalid GLB 2 JSON header: {path}')
        return json.loads(handle.read(chunk_len))


def png_size(path):
    with path.open('rb') as handle:
        head = handle.read(24)
    if len(head) != 24 or head[:8] != b'\x89PNG\r\n\x1a\n' or head[12:16] != b'IHDR':
        raise ValueError(f'Not a PNG: {path}')
    return struct.unpack('>II', head[16:24])


def validate(mesh, max_triangles=None):
    if not mesh.is_file():
        raise FileNotFoundError(f'Bottom-pivot tower mesh missing: {mesh}')
    doc = glb_json(mesh)
    meshes = doc.get('meshes', [])
    if len(meshes) != 1 or len(meshes[0].get('primitives', [])) != 1:
        raise ValueError('Expected one mesh and one PBR material section')
    prim = meshes[0]['primitives'][0]
    attrs = prim.get('attributes', {})
    if not {'POSITION', 'NORMAL', 'TEXCOORD_0'} <= attrs.keys():
        raise ValueError('Runtime mesh must preserve positions, normals and UV0')
    position = doc['accessors'][attrs['POSITION']]
    indices = doc['accessors'][prim['indices']]
    if indices['count'] % 3:
        raise ValueError('Non-triangle indices')
    triangles = indices['count'] // 3
    low, high = position['min'], position['max']
    for node in doc.get('nodes', []):
        if node.get('mesh') == 0 and any(key in node for key in ('matrix', 'translation', 'rotation', 'scale')):
            raise ValueError('Bake node transforms before tower import so bottom pivot is measurable')
    if abs(low[1]) > 0.005 or abs(low[0] + high[0]) > 0.015 or abs(low[2] + high[2]) > 0.015:
        raise ValueError(f'Expected bottom-centre pivot in glTF Y-up coordinates, got {low=} {high=}')
    height = high[1] - low[1]
    if not 0.9 <= height <= 1.1:
        raise ValueError(f'Expected ~1-source-unit bottom-pivot derivative, got height {height}')
    textures = {}
    for role, path in MAPS.items():
        if png_size(path) != (8192, 8192):
            raise ValueError(f'{role} map is not 8192x8192: {path}')
        textures[role] = {'path': str(path), 'bytes': path.stat().st_size, 'pixels': [8192, 8192]}
    actor_scale = TARGET_HEIGHT_CM / (height * 100.0)
    local_cm = [(high[0] - low[0]) * 100, (high[2] - low[2]) * 100, height * 100]
    placed_cm = [value * actor_scale for value in local_cm]
    is_review = mesh.resolve() == REVIEW.resolve()
    optimized = not is_review and triangles < REVIEW_TRIS and max_triangles is not None and triangles <= max_triangles
    return {
        'mesh': str(mesh), 'triangle_count': triangles, 'review_only': is_review,
        'approved_triangle_ceiling': max_triangles, 'optimized_gate_pass': optimized,
        'uv0': True, 'normal_attribute': True, 'material_sections': 1,
        'source_bounds_gltf_m': {'min': low, 'max': high},
        'imported_local_size_cm_expected': local_cm,
        'actor_uniform_scale_for_20m': actor_scale,
        'placed_size_cm_expected': placed_cm,
        'rejected_diagnostic_xy_cm': REJECTED_PLAN_XY_CM,
        'placement_status': 'Unsurveyed here; the rejected XY had 6/9 no support and 3 HLOD-only probes',
        'maps': textures,
    }


def validated_origin(x, y, z, receipt_path):
    if any(value is None or not math.isfinite(value) for value in (x, y, z)) or receipt_path is None:
        raise ValueError('Packet requires finite --x --y --z and --support-receipt')
    origin = [x, y, z]
    if math.dist(origin[:2], REJECTED_PLAN_XY_CM) < 100.0:
        raise ValueError('The proposed tower XY was rejected by support survey')
    receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
    recorded = receipt.get('tower_actor_origin_cm')
    if not isinstance(recorded, list) or len(recorded) != 3 or any(
            not isinstance(value, (float, int)) or not math.isfinite(value) for value in recorded):
        raise ValueError('Support receipt must record numeric tower_actor_origin_cm [x,y,z]')
    if math.dist(origin, recorded) > 2.0:
        raise ValueError('Requested tower origin differs from support receipt by more than 2cm')
    gates = ('landscape_supported', 'foundation_clearance_pass', 'yard_clearance_pass', 'cin24_frame_pass')
    if any(receipt.get(key) is not True for key in gates):
        raise ValueError('Support receipt lacks passing landscape/foundation/yard/CIN24 gates')
    return {'origin_cm': origin, 'receipt': str(receipt_path.resolve()), 'gates': list(gates)}


EDITOR = r'''
import unreal
eal = unreal.EditorAssetLibrary
mel = unreal.MaterialEditingLibrary
at = unreal.AssetToolsHelpers.get_asset_tools()
ses = unreal.get_editor_subsystem(unreal.StaticMeshEditorSubsystem)
dest = __DEST__
mesh_file = __MESH__
files = __MAPS__
expected = __EXPECTED__
mesh_path = dest + '/SM_S26_RelayTower_Runtime'
mat_path = dest + '/Materials/M_S26_RelayTower_PBR'
paths = [mesh_path, mat_path] + [dest + '/Textures/T_S26_RelayTower_' + key for key in ('BC', 'N', 'ORM')]
if any(eal.does_asset_exist(path) for path in paths):
    raise RuntimeError('Relay destination already contains assets; inspect them before rerunning')
for folder in (dest, dest + '/Textures', dest + '/Materials', dest + '/_Import'):
    if not eal.does_directory_exist(folder):
        eal.make_directory(folder)
textures = {}
for role, filename in files.items():
    task = unreal.AssetImportTask()
    task.set_editor_property('filename', filename)
    task.set_editor_property('destination_path', dest + '/Textures')
    task.set_editor_property('destination_name', 'T_S26_RelayTower_' + role)
    task.set_editor_property('automated', True)
    task.set_editor_property('replace_existing', False)
    task.set_editor_property('save', False)
    at.import_asset_tasks([task])
    texture = eal.load_asset(dest + '/Textures/T_S26_RelayTower_' + role)
    if not isinstance(texture, unreal.Texture2D):
        raise RuntimeError('Texture import failed: ' + role)
    texture.set_editor_property('srgb', role == 'BC')
    texture.set_editor_property('compression_settings', {
        'BC': unreal.TextureCompressionSettings.TC_DEFAULT,
        'N': unreal.TextureCompressionSettings.TC_NORMALMAP,
        'ORM': unreal.TextureCompressionSettings.TC_MASKS}[role])
    texture.set_editor_property('max_texture_size', 8192)
    texture.set_editor_property('lod_group', unreal.TextureGroup.TEXTUREGROUP_WORLD)
    if role == 'N':
        texture.set_editor_property('flip_green_channel', True)
    textures[role] = texture
mat = at.create_asset('M_S26_RelayTower_PBR', dest + '/Materials', unreal.Material, unreal.MaterialFactoryNew())
if mat is None:
    raise RuntimeError('PBR material creation failed')
samplers = {'BC': unreal.MaterialSamplerType.SAMPLERTYPE_COLOR,
            'N': unreal.MaterialSamplerType.SAMPLERTYPE_NORMAL,
            'ORM': unreal.MaterialSamplerType.SAMPLERTYPE_MASKS}
nodes = {}
for index, role in enumerate(('BC', 'N', 'ORM')):
    node = mel.create_material_expression(mat, unreal.MaterialExpressionTextureSampleParameter2D, -450, index * 250)
    node.set_editor_property('parameter_name', role)
    node.set_editor_property('texture', textures[role])
    node.set_editor_property('sampler_type', samplers[role])
    nodes[role] = node
for role, channel, output in [('BC', 'RGB', unreal.MaterialProperty.MP_BASE_COLOR),
                              ('N', 'RGB', unreal.MaterialProperty.MP_NORMAL),
                              ('ORM', 'R', unreal.MaterialProperty.MP_AMBIENT_OCCLUSION),
                              ('ORM', 'G', unreal.MaterialProperty.MP_ROUGHNESS),
                              ('ORM', 'B', unreal.MaterialProperty.MP_METALLIC)]:
    if not mel.connect_material_property(nodes[role], channel, output):
        raise RuntimeError('PBR channel connection failed: ' + role + '/' + channel)
errors = mel.recompile_material(mat)
if errors:
    raise RuntimeError('PBR material compile failed: ' + str(errors))
task = unreal.AssetImportTask()
task.set_editor_property('filename', mesh_file)
task.set_editor_property('destination_path', dest + '/_Import')
task.set_editor_property('destination_name', 'SM_S26_RelayTower_Runtime')
task.set_editor_property('automated', True)
task.set_editor_property('replace_existing', False)
task.set_editor_property('save', False)
at.import_asset_tasks([task])
imports = task.get_editor_property('imported_object_paths')
meshes = [p for p in imports if isinstance(eal.load_asset(p), unreal.StaticMesh)]
if len(meshes) != 1 or not eal.rename_asset(meshes[0], mesh_path):
    raise RuntimeError('Expected exactly one imported static mesh: ' + str(imports))
mesh = eal.load_asset(mesh_path)
box = mesh.get_bounding_box()
size = [box.max.x - box.min.x, box.max.y - box.min.y, box.max.z - box.min.z]
if any(abs(a - b) > max(2.0, b * 0.02) for a, b in zip(size, expected)):
    raise RuntimeError('Wrong imported tower bounds: ' + str(size) + ' expected ' + str(expected))
if abs(box.min.z) > 2 or abs(box.min.x + box.max.x) > 2 or abs(box.min.y + box.max.y) > 2:
    raise RuntimeError('Tower pivot is not bottom-centre')
if len(mesh.get_editor_property('static_materials')) != 1:
    raise RuntimeError('Tower material-section count changed')
mesh.set_material(0, mat)
nanite = ses.get_nanite_settings(mesh)
nanite.set_editor_property('enabled', True)
ses.set_nanite_settings(mesh, nanite, True)
for asset in list(textures.values()) + [mat, mesh]:
    if not eal.save_loaded_asset(asset, False):
        raise RuntimeError('Could not save ' + asset.get_path_name())
print('RELAY_IMPORT_READY ' + str({'mesh': mesh_path, 'size_cm': size, 'actor_scale_for_20m': __SCALE__,
                                    'maps_max_texture_size': 8192, 'material': mat_path,
                                    'placement': 'deferred until yard/ground/camera survey'}))
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('validate', 'packet'))
    parser.add_argument('--mesh', type=Path, default=REVIEW)
    parser.add_argument('--max-triangles', type=int)
    parser.add_argument('--x', type=float)
    parser.add_argument('--y', type=float)
    parser.add_argument('--z', type=float)
    parser.add_argument('--support-receipt', type=Path)
    args = parser.parse_args()
    mesh = args.mesh if args.mesh.is_absolute() else ROOT / args.mesh
    result = validate(mesh, args.max_triangles)
    print(json.dumps(result, indent=2))
    if args.command == 'packet':
        if not result['optimized_gate_pass']:
            raise SystemExit('Packet blocked: supply an optimized non-review GLB and an approved --max-triangles ceiling')
        result['validated_placement'] = validated_origin(args.x, args.y, args.z, args.support_receipt)
        if OUT.exists():
            raise SystemExit(f'Packet destination exists; inspect before replacing: {OUT}')
        OUT.mkdir(parents=True)
        source = EDITOR.replace('__DEST__', repr(DEST)).replace('__MESH__', repr(str(mesh)))
        source = source.replace('__MAPS__', repr({role: str(path) for role, path in MAPS.items()}))
        source = source.replace('__EXPECTED__', repr(result['imported_local_size_cm_expected']))
        source = source.replace('__SCALE__', repr(result['actor_uniform_scale_for_20m']))
        (OUT / '20_import_relay_tower.py').write_text(source, encoding='utf-8')
        (OUT / 'manifest.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
        print(f'RELAY_PACKET {OUT}')


if __name__ == '__main__':
    main()
