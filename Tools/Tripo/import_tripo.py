"""Tripo02 import, one model per editor call. Run prepare/check offline first.

Editor order (hold editor_gate): mesh KEY, textures KEY, master (once), finish KEY,
verify [KEY]. `verify` writes measured, saved asset data to Saved/Tripo/imported_bounds.json.
Original GLBs stay intact; staging removes generated materials and extracts their images.
"""
import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'Tools' / 'Look'))
from apply_look import check_banned, python_run
from tripo_ingest import read_glb, write_glb, _view_bytes, glb_stats

DEST = '/Game/SaskartaGaea/Environment/Tripo02'
BLEND = '/Game/SaskartaGaea/Environment/SetDress/Materials/MF_SD_PropGroundBlend'
STAGE = ROOT / 'Saved' / 'Tripo' / 'import'
REPORT = ROOT / 'Saved' / 'Tripo' / 'imported_bounds.json'


def models():
    rows = json.loads((ROOT / 'SourceArt/Tripo/manifest.json').read_text())['models']
    return [r for r in rows if r['verdict'] == 'use']


def prepare(row):
    folder = STAGE / row['key']
    folder.mkdir(parents=True, exist_ok=True)
    doc, blob = read_glb(ROOT / row['import_file'])
    assert len(doc['meshes']) == len(doc['materials']) == 1, row['key']
    mat = doc['materials'][0]
    pbr = mat['pbrMetallicRoughness']
    refs = {'BC': pbr['baseColorTexture'], 'N': mat['normalTexture'],
            'ORM': pbr['metallicRoughnessTexture']}
    for role, ref in refs.items():
        img = doc['images'][doc['textures'][ref['index']]['source']]
        ext = {'image/png': '.png', 'image/jpeg': '.jpg'}[img['mimeType']]
        data, _ = _view_bytes(doc, blob, img['bufferView'])
        (folder / ('T_T2_' + row['t2'] + '_' + role + ext)).write_bytes(data)
    # Same geometry/transforms; avoid importing unused generated materials/textures.
    for mesh in doc['meshes']:
        for prim in mesh['primitives']:
            prim.pop('material', None)
    for field in ('materials', 'textures', 'images', 'samplers'):
        doc.pop(field, None)
    write_glb(folder / ('SM_T2_' + row['t2'] + '.glb'), doc, blob)


COMMON = '''
import unreal
import json
eal = unreal.EditorAssetLibrary
mel = unreal.MaterialEditingLibrary
at = unreal.AssetToolsHelpers.get_asset_tools()
ses = unreal.get_editor_subsystem(unreal.StaticMeshEditorSubsystem)
dest = "__DEST__"
name = "SM_T2___T2__"
path = dest + '/' + name
'''

MESH = COMMON + '''
if not eal.does_asset_exist(path):
    task = unreal.AssetImportTask()
    task.set_editor_property('filename', __FILE__)
    task.set_editor_property('destination_path', dest + '/_Import/__KEY__')
    task.set_editor_property('destination_name', name)
    task.set_editor_property('automated', True)
    task.set_editor_property('replace_existing', True)
    task.set_editor_property('save', False)
    at.import_asset_tasks([task])
    paths = task.get_editor_property('imported_object_paths')
    meshes = [p for p in paths if isinstance(eal.load_asset(p), unreal.StaticMesh)]
    if len(meshes) != 1:
        raise RuntimeError('Expected one mesh: ' + str(paths))
    if not eal.rename_asset(meshes[0], path):
        raise RuntimeError('Mesh rename failed')
mesh = eal.load_asset(path)
if not eal.save_loaded_asset(mesh, False):
    raise RuntimeError('Mesh save failed')
print('TRIPO_MESH ' + path + ' saved=True')
'''

TEXTURES = COMMON + '''
for role, filename in __TEXTURES__:
    tname = 'T_T2___T2___' + role
    tp = dest + '/Textures/' + tname
    if not eal.does_asset_exist(tp):
        task = unreal.AssetImportTask()
        task.set_editor_property('filename', filename)
        task.set_editor_property('destination_path', dest + '/Textures')
        task.set_editor_property('destination_name', tname)
        task.set_editor_property('automated', True)
        task.set_editor_property('replace_existing', True)
        task.set_editor_property('save', False)
        at.import_asset_tasks([task])
    tex = eal.load_asset(tp)
    if tex is None:
        raise RuntimeError('Missing texture ' + tp)
    tex.set_editor_property('srgb', role == 'BC')
    mode = {'BC': unreal.TextureCompressionSettings.TC_DEFAULT,
            'N': unreal.TextureCompressionSettings.TC_NORMALMAP,
            'ORM': unreal.TextureCompressionSettings.TC_MASKS}[role]
    tex.set_editor_property('compression_settings', mode)
    tex.set_editor_property('max_texture_size', 2048)
    tex.set_editor_property('virtual_texture_streaming', False)
    tex.set_editor_property('lod_group', unreal.TextureGroup.TEXTUREGROUP_WORLD)
    if role == 'N':
        tex.set_editor_property('flip_green_channel', True)
    if not eal.save_loaded_asset(tex, False):
        raise RuntimeError('Texture save failed ' + tp)
print('TRIPO_TEXTURES __KEY__ saved=True')
'''

MASTER = COMMON + '''
fn = eal.load_asset('__BLEND__')
if fn is None:
    raise RuntimeError('Build MF_SD_PropGroundBlend first')
mp = dest + '/Materials/M_T2_Master'
mat = eal.load_asset(mp)
if mat is None:
    mat = at.create_asset('M_T2_Master', dest + '/Materials', unreal.Material, unreal.MaterialFactoryNew())
mel.delete_all_material_expressions(mat)
mat.set_editor_property('used_with_instanced_static_meshes', True)
mel.set_material_usage(mat, unreal.MaterialUsage.MATUSAGE_NANITE)
def node(cls, x, y):
    return mel.create_material_expression(mat, cls, x, y)
def scalar(n, v, y):
    a = node(unreal.MaterialExpressionScalarParameter, -600, y)
    a.set_editor_property('parameter_name', n)
    a.set_editor_property('default_value', v)
    return a
def link(a, ao, b, bi):
    if not mel.connect_material_expressions(a, ao, b, bi):
        raise RuntimeError('Material pin failed ' + bi)
tex = {}
for role, parameter, sampler, y in [('BC', 'BaseColor', unreal.MaterialSamplerType.SAMPLERTYPE_COLOR, -400),
                                    ('N', 'Normal', unreal.MaterialSamplerType.SAMPLERTYPE_NORMAL, 0),
                                    ('ORM', 'ORM', unreal.MaterialSamplerType.SAMPLERTYPE_MASKS, 350)]:
    t = node(unreal.MaterialExpressionTextureSampleParameter2D, -1000, y)
    t.set_editor_property('parameter_name', parameter)
    t.set_editor_property('texture', eal.load_asset(dest + '/Textures/T_T2___T2___' + role))
    t.set_editor_property('sampler_type', sampler)
    tex[role] = t
tint = node(unreal.MaterialExpressionVectorParameter, -900, -650)
tint.set_editor_property('parameter_name', 'Tint')
tint.set_editor_property('default_value', unreal.LinearColor(1, 1, 1, 1))
color = node(unreal.MaterialExpressionMultiply, -350, -400)
link(tex['BC'], 'RGB', color, 'A')
link(tint, 'RGB', color, 'B')
rough = node(unreal.MaterialExpressionMultiply, -350, 350)
link(tex['ORM'], 'G', rough, 'A')
link(scalar('RoughnessScale', 1.0, 600), '', rough, 'B')
ao = node(unreal.MaterialExpressionLinearInterpolate, -350, 700)
ao.set_editor_property('const_a', 1.0)
link(tex['ORM'], 'R', ao, 'B')
link(scalar('AOStrength', 1.0, 850), '', ao, 'Alpha')
blend = node(unreal.MaterialExpressionMaterialFunctionCall, 0, -300)
blend.set_material_function(fn)
link(color, '', blend, 'Colour')
link(rough, '', blend, 'Roughness')
P = unreal.MaterialProperty
for a, output, prop in [(blend, 'Colour', P.MP_BASE_COLOR), (blend, 'Roughness', P.MP_ROUGHNESS),
                        (tex['N'], 'RGB', P.MP_NORMAL), (tex['ORM'], 'B', P.MP_METALLIC), (ao, '', P.MP_AMBIENT_OCCLUSION)]:
    if not mel.connect_material_property(a, output, prop):
        raise RuntimeError('Material output failed ' + str(prop))
errors = mel.recompile_material(mat)
if errors:
    raise RuntimeError(str(errors))
if not eal.save_loaded_asset(mat, False):
    raise RuntimeError('Master save failed')
print('TRIPO_MASTER saved=True')
'''

FINISH = COMMON + '''
mesh = eal.load_asset(path)
master = eal.load_asset(dest + '/Materials/M_T2_Master')
if mesh is None or master is None:
    raise RuntimeError('Mesh/master missing')
mip = dest + '/Materials/MI_T2___T2__'
mi = eal.load_asset(mip)
if mi is None:
    mi = at.create_asset('MI_T2___T2__', dest + '/Materials', unreal.MaterialInstanceConstant, unreal.MaterialInstanceConstantFactoryNew())
mel.set_material_instance_parent(mi, master)
for role, parameter in [('BC', 'BaseColor'), ('N', 'Normal'), ('ORM', 'ORM')]:
    tex = eal.load_asset(dest + '/Textures/T_T2___T2___' + role)
    if tex is None:
        raise RuntimeError('Missing texture ' + role)
    mel.set_material_instance_texture_parameter_value(mi, parameter, tex)
mel.update_material_instance(mi)
mesh.set_material(0, mi)
ns = ses.get_nanite_settings(mesh)
if not ns.get_editor_property('enabled'):
    ns.set_editor_property('enabled', True)
    ses.set_nanite_settings(mesh, ns, True)
bs = ses.get_lod_build_settings(mesh, 0)
# The Interchange import already produces these settings. Rebuilding a loaded
# mesh to set them again is unsafe in this editor; stop if import settings differ.
if (bs.get_editor_property('generate_lightmap_u_vs') or bs.get_editor_property('recompute_normals')
        or not bs.get_editor_property('recompute_tangents') or not bs.get_editor_property('use_mikk_t_space')):
    raise RuntimeError('Unexpected mesh build settings; correct the Interchange import configuration before finishing')
body = mesh.get_editor_property('body_setup')
body.set_editor_property('collision_trace_flag', unreal.CollisionTraceFlag.CTF_USE_COMPLEX_AS_SIMPLE)
if not eal.save_loaded_asset(mi, False) or not eal.save_loaded_asset(mesh, False):
    raise RuntimeError('Mesh/MI save failed')
print('TRIPO_FINISH __KEY__ saved=True')
'''

VERIFY = COMMON + '''
mesh = eal.load_asset(path)
if mesh is None:
    raise RuntimeError('Missing mesh ' + path)
b = mesh.get_bounding_box()
size = [b.max.x - b.min.x, b.max.y - b.min.y, b.max.z - b.min.z]
expected = __SIZE__
if any(abs(a - b) > max(2, b * 0.02) for a, b in zip(size, expected)):
    raise RuntimeError('Wrong bounds ' + str(size) + ' expected ' + str(expected))
if abs(b.min.z) > 2 or abs(b.min.x + b.max.x) > 2 or abs(b.min.y + b.max.y) > 2:
    raise RuntimeError('Pivot not at bottom center')
if not ses.get_nanite_settings(mesh).get_editor_property('enabled'):
    raise RuntimeError('Nanite disabled')
bs = ses.get_lod_build_settings(mesh, 0)
if (bs.get_editor_property('generate_lightmap_u_vs') or bs.get_editor_property('recompute_normals')
        or not bs.get_editor_property('recompute_tangents') or not bs.get_editor_property('use_mikk_t_space')):
    raise RuntimeError('Wrong imported normals/tangents/lightmap build settings')
mi = eal.load_asset(dest + '/Materials/MI_T2___T2__')
if mi is None or mesh.get_material(0) != mi or len(mesh.get_editor_property('static_materials')) != 1:
    raise RuntimeError('Wrong material assignment')
if mi.get_editor_property('parent') != eal.load_asset(dest + '/Materials/M_T2_Master'):
    raise RuntimeError('Wrong master')
for role, parameter in [('BC', 'BaseColor'), ('N', 'Normal'), ('ORM', 'ORM')]:
    t = eal.load_asset(dest + '/Textures/T_T2___T2___' + role)
    if t is None or mel.get_material_instance_texture_parameter_value(mi, parameter) != t:
        raise RuntimeError('Wrong texture ' + role)
    if t.get_editor_property('srgb') != (role == 'BC') or t.get_editor_property('max_texture_size') != 2048:
        raise RuntimeError('Wrong texture settings ' + role)
    if role == 'N' and not t.get_editor_property('flip_green_channel'):
        raise RuntimeError('Normal green channel not converted')
dirty = [p.get_name() for p in unreal.EditorLoadingAndSavingUtils.get_dirty_content_packages() if p.get_name().startswith(dest + '/')]
if dirty:
    raise RuntimeError('Unsaved Tripo assets ' + str(dirty))
print('TRIPO_VERIFIED ' + json.dumps({'key': '__KEY__', 'path': path, 'size_cm': size, 'nanite': True,
                                     'tris': __TRIS__, 'material': mi.get_path_name(), 'saved': True}))
'''


def script(step, row):
    folder = STAGE / row['key']
    textures = [(role, p.as_posix()) for role in ('BC', 'N', 'ORM')
                for p in folder.glob('T_T2_' + row['t2'] + '_' + role + '.*')]
    result = globals()[step.upper()]
    values = {'DEST': DEST, 'BLEND': BLEND, 'T2': row['t2'], 'KEY': row['key'],
              'FILE': repr((folder / ('SM_T2_' + row['t2'] + '.glb')).as_posix()),
              'SIZE': repr(row['import_size_cm_wdh']), 'TRIS': row['tris'], 'TEXTURES': repr(textures)}
    for key, value in values.items():
        result = result.replace('__' + key + '__', str(value))
    check_banned(result)
    compile(result, '<editor>', 'exec')
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('step', choices=['prepare', 'check', 'mesh', 'textures', 'master', 'finish', 'verify'])
    ap.add_argument('key', nargs='?')
    args = ap.parse_args()
    rows = [r for r in models() if not args.key or args.key in (r['key'], r['t2'])]
    if not rows:
        ap.error('Unknown use-model key')
    if args.step in ('mesh', 'textures', 'finish') and not args.key:
        ap.error('One model key required per editor step')
    if args.step == 'prepare':
        for row in rows:
            prepare(row)
        print('Prepared', len(rows), 'mesh files and', len(rows) * 3, 'textures')
        return
    if args.step == 'check':
        for row in rows:
            folder = STAGE / row['key']
            stats = glb_stats(folder / ('SM_T2_' + row['t2'] + '.glb'))
            assert stats['tris'] == row['tris'], row['key']
            assert all(abs(a-b) < 1 for a,b in zip(stats['native_size_cm_wdh'], row['import_size_cm_wdh'])), row['key']
            assert len(list(folder.glob('T_T2_*'))) == 3, row['key']
            for step in ('mesh', 'textures', 'master', 'finish', 'verify'):
                script(step, row)
        print('PASS', len(rows), 'source dimensions/triangles, texture roles, editor script compilation')
        return
    if args.step == 'master':
        rows = rows[:1]
    report = json.loads(REPORT.read_text()) if REPORT.exists() else {}
    for row in rows:
        ok, out, err = python_run(script(args.step, row))
        print(out.strip() if out else err)
        if not ok:
            raise SystemExit(err)
        marker = 'TRIPO_VERIFIED ' if args.step == 'verify' else 'TRIPO_' + args.step.upper() + ' '
        if marker not in out:
            raise SystemExit('Missing success marker; stop and inspect editor log')
        if args.step == 'verify':
            data = json.loads(next(line.split(marker, 1)[1] for line in out.splitlines() if marker in line))
            asset = ROOT / 'Content' / (data['path'][6:] + '.uasset')
            if not asset.is_file() or asset.stat().st_size == 0:
                raise SystemExit('Verified asset missing on disk: ' + str(asset))
            data['file_mb'] = asset.stat().st_size / 1e6
            report[data['path']] = data
            REPORT.parent.mkdir(parents=True, exist_ok=True)
            REPORT.write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
