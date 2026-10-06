"""Set dressing V2 materials (docs/world/SETDRESS_V2.md section 2 and 4).

    python Tools/World/build_setdress_materials.py check            # offline: HLSL present, every script passes validate()
    python Tools/World/build_setdress_materials.py decal            # M_SD_SiteGround (deferred decal) + MI_SD_Ground_<surface>
    python Tools/World/build_setdress_materials.py blendfn          # MF_SD_PropGroundBlend (Shaders/PropGroundBlend.hlsl)
    python Tools/World/build_setdress_materials.py variants S07_WaitingWater [--only N]
          # for every material on the site's actors (place_setdress.py matsurvey wrote the list to the site
          # state): a _GB copy with the blend inserted before BaseColor/Roughness; the map source -> copy is
          # merged into Tools/World/setdress_material_map.json, which place_setdress.py 'material' applies
          # as per-actor overrides. No pack asset is edited (the copies live in the project).

Ground patches are deferred decals, not landscape paint layers: the landscape has no layer infos at all
(docs/performance-budget.md), its look is procedural (Shaders/GroundAuto.hlsl written into the RVT), and
painting would mean a material change plus the 256-proxy refresh. The decals write colour and roughness
only (DBuffer), never the normal, and use the landscape's own dirt and gravel textures (Tools/Road/GROUND.md)
so they read as the same ground, trodden. Editor calls: 5 s each, the file gate, PIE checked before each.
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
import place_setdress as ps  # noqa: E402

GROUND_DIR = '/Game/SaskartaGaea/Environment/SetDress/Ground'
MAT_DIR = '/Game/SaskartaGaea/Environment/SetDress/Materials'
RVT = '/Game/SaskartaGaea/RVT/RVT_Saskarta_Terrain'
FOLIAGE_DIR = '/Game/SaskartaGaea/Foliage'
DIRT = '/Game/Pallbearer/Terrain/Tex/T_PH_dirt_aerial_02_diff'
GRAVEL = '/Game/Pallbearer/Terrain/Tex/T_PH_forest_ground_04_diff'
# surface -> texture, tile m, tint, (softness, noise amp, strength, saturation), roughness, sort
# V2.1 (S07 review: "the ground decals barely show"): more contrast against the orange-brown ground and a
# crisper edge. Paths darker and smoother, packed earth a shade darker, rubble dust and dry mud paler; the
# strengths near 1 (the per-decal DecalColor alpha scales them down where a patch should be faint); the soft
# edge narrowed (softness is the fraction of the radius that fades) so a patch reads as a shape, not a haze.
# Previous values (V2.0): packed_earth (0.80, 0.74, 0.68) (0.45, 0.18, 0.75, 0.8); path (0.58, 0.50, 0.43)
# (0.35, 0.12, 0.85, 0.7); gravel strength 0.7; rubble_dust (1.08, 1.0, 0.9) (0.55, 0.22, 0.65, 0.5);
# soot strength 0.7; dry_mud (1.18, 1.08, 0.95) strength 0.85.
SURFACES = {
    'packed_earth': (DIRT, 5.2, (0.70, 0.62, 0.53), (0.32, 0.18, 0.95, 0.75), 0.8),
    'path': (DIRT, 3.0, (0.44, 0.37, 0.30), (0.26, 0.12, 1.0, 0.65), 0.62),
    'gravel': (GRAVEL, 2.3, (0.95, 0.90, 0.84), (0.32, 0.15, 0.9, 0.6), 0.9),
    'rubble_dust': (GRAVEL, 2.3, (1.32, 1.22, 1.06), (0.38, 0.24, 0.95, 0.45), 0.95),
    'soot': (DIRT, 3.0, (0.2, 0.18, 0.16), (0.4, 0.2, 0.9, 0.3), 0.95),
    'dry_mud': (DIRT, 7.0, (1.3, 1.18, 1.02), (0.26, 0.25, 0.95, 0.45), 0.96),
}
PROP_DEFAULTS = dict(SD_FadeHeight=0.6, SD_BaseStrength=0.85, SD_PaletteMatch=0.55)


def hlsl(name):
    with open(os.path.join(ROOT, 'Shaders', name), encoding='utf8') as fh:
        return fh.read()


COMMON = r'''
import unreal
mel = unreal.MaterialEditingLibrary
eal = unreal.EditorAssetLibrary
at = unreal.AssetToolsHelpers.get_asset_tools()
QUIET = unreal.PropertyAccessChangeNotifyMode.NEVER
fails = []
def link(a, ao, b, bi):
    if not mel.connect_material_expressions(a, ao, b, bi):
        fails.append(str(bi))
def ensure_dir(d):
    if not eal.does_directory_exist(d):
        eal.make_directory(d)
'''

DECAL = COMMON + r'''
ensure_dir(GDIR)
path = GDIR + '/M_SD_SiteGround'
if eal.does_asset_exist(path):
    mat = eal.load_asset(path)
else:
    mat = at.create_asset('M_SD_SiteGround', GDIR, unreal.Material, unreal.MaterialFactoryNew())
mat.set_editor_property('material_domain', unreal.MaterialDomain.MD_DEFERRED_DECAL)
mat.set_editor_property('blend_mode', unreal.BlendMode.BLEND_TRANSLUCENT)
for old in mel.get_material_expressions(mat):
    mel.delete_material_expression(mat, old)
def add(cls, x, y):
    return mel.create_material_expression(mat, cls, x, y)
def scal(name, v, x, y):
    n = add(unreal.MaterialExpressionScalarParameter, x, y)
    n.set_editor_property('parameter_name', name)
    n.set_editor_property('default_value', v)
    n.set_editor_property('group', 'SiteGround')
    return n
def vec(name, c, x, y):
    n = add(unreal.MaterialExpressionVectorParameter, x, y)
    n.set_editor_property('parameter_name', name)
    n.set_editor_property('default_value', unreal.LinearColor(c[0], c[1], c[2], c[3]))
    n.set_editor_property('group', 'SiteGround')
    return n
uv = add(unreal.MaterialExpressionTextureCoordinate, -1400, -300)
wp = add(unreal.MaterialExpressionWorldPosition, -1600, 0)
wxy = add(unreal.MaterialExpressionComponentMask, -1400, 0)
wxy.set_editor_property('r', True)
wxy.set_editor_property('g', True)
wxy.set_editor_property('b', False)
wxy.set_editor_property('a', False)
link(wp, '', wxy, '')
tile = scal('TileM', 5.0, -1600, 120)
tcm = add(unreal.MaterialExpressionMultiply, -1400, 120)
tcm.set_editor_property('const_b', 100.0)
link(tile, '', tcm, 'A')
tuv = add(unreal.MaterialExpressionDivide, -1250, 40)
link(wxy, '', tuv, 'A')
link(tcm, '', tuv, 'B')
tex = add(unreal.MaterialExpressionTextureSampleParameter2D, -1050, 40)
tex.set_editor_property('parameter_name', 'GroundTex')
tex.set_editor_property('texture', eal.load_asset(TEXDEF))
tex.set_editor_property('group', 'SiteGround')
link(tuv, '', tex, 'UVs')
noise = add(unreal.MaterialExpressionNoise, -1050, 300)
noise.set_editor_property('scale', 0.004)
noise.set_editor_property('levels', 3)
noise.set_editor_property('output_min', -1.0)
noise.set_editor_property('output_max', 1.0)
dc = add(unreal.MaterialExpressionDecalColor, -1050, 450)
shape = vec('Shape', (0.45, 0.18, 0.75, 0.8), -1050, 600)
tint = vec('Tint', (0.8, 0.74, 0.68, 1.0), -1050, 760)
c = add(unreal.MaterialExpressionCustom, -600, 200)
c.set_editor_property('description', 'SetDressGround', QUIET)
c.set_editor_property('output_type', unreal.CustomMaterialOutputType.CMOT_FLOAT4, QUIET)
c.set_editor_property('code', CODE, QUIET)
arr = []
for p in ['UV', 'Tex', 'Noise', 'DC', 'DA', 'P', 'Tint']:
    ci = unreal.CustomInput()
    ci.set_editor_property('input_name', p)
    arr.append(ci)
c.set_editor_property('inputs', arr, QUIET)
link(uv, '', c, 'UV')
link(tex, 'RGB', c, 'Tex')
link(noise, '', c, 'Noise')
link(dc, '', c, 'DC')
link(dc, 'A', c, 'DA')
link(shape, 'RGBA', c, 'P')
link(tint, 'RGB', c, 'Tint')
rgb = add(unreal.MaterialExpressionComponentMask, -350, 150)
rgb.set_editor_property('r', True)
rgb.set_editor_property('g', True)
rgb.set_editor_property('b', True)
rgb.set_editor_property('a', False)
link(c, '', rgb, '')
al = add(unreal.MaterialExpressionComponentMask, -350, 300)
al.set_editor_property('r', False)
al.set_editor_property('g', False)
al.set_editor_property('b', False)
al.set_editor_property('a', True)
link(c, '', al, '')
rough = scal('Roughness', 0.8, -350, 450)
P = unreal.MaterialProperty
ok = [mel.connect_material_property(rgb, '', P.MP_BASE_COLOR), mel.connect_material_property(al, '', P.MP_OPACITY),
      mel.connect_material_property(rough, '', P.MP_ROUGHNESS)]
errs = mel.recompile_material(mat)
print('DECAL fails=' + str(fails) + ' props=' + str(ok) + ' errors=' + str(len(errs)) + ' ' + ' | '.join([str(e) for e in errs]))
print('DECAL saved=' + str(eal.save_loaded_asset(mat, False)))
'''

# One MI per call (all six plus the master's recompile overran the 5 s deadline in one call).
DECAL_MI = COMMON + r'''
mat = eal.load_asset(GDIR + '/M_SD_SiteGround')
for name, s in SURF.items():
    mp = GDIR + '/MI_SD_Ground_' + name
    if eal.does_asset_exist(mp):
        mi = eal.load_asset(mp)
    else:
        mi = at.create_asset('MI_SD_Ground_' + name, GDIR, unreal.MaterialInstanceConstant, unreal.MaterialInstanceConstantFactoryNew())
    mel.set_material_instance_parent(mi, mat)
    mel.set_material_instance_texture_parameter_value(mi, 'GroundTex', eal.load_asset(s[0]))
    mel.set_material_instance_scalar_parameter_value(mi, 'TileM', s[1])
    mel.set_material_instance_vector_parameter_value(mi, 'Tint', unreal.LinearColor(s[2][0], s[2][1], s[2][2], 1.0))
    mel.set_material_instance_vector_parameter_value(mi, 'Shape', unreal.LinearColor(s[3][0], s[3][1], s[3][2], s[3][3]))
    mel.set_material_instance_scalar_parameter_value(mi, 'Roughness', s[4])
    mel.update_material_instance(mi)
    print('MI ' + mp + ' saved=' + str(eal.save_loaded_asset(mi, False)))
'''

BLENDFN = COMMON + r'''
ensure_dir(MDIR)
path = MDIR + '/MF_SD_PropGroundBlend'
f = eal.load_asset(path) if eal.does_asset_exist(path) else at.create_asset('MF_SD_PropGroundBlend', MDIR, unreal.MaterialFunction, unreal.MaterialFunctionFactoryNew())
mel.delete_all_material_expressions_in_function(f)
def add(cls, x, y):
    return mel.create_material_expression_in_function(f, cls, x, y)
FI = unreal.FunctionInputType
def fin(name, t, y, prio):
    i = add(unreal.MaterialExpressionFunctionInput, -1400, y)
    i.set_editor_property('input_name', name)
    i.set_editor_property('input_type', t)
    i.set_editor_property('sort_priority', prio)
    return i
def cpd(name, idx, v, y):
    n = add(unreal.MaterialExpressionScalarParameter, -1100, y)
    n.set_editor_property('parameter_name', name)
    n.set_editor_property('default_value', v)
    n.set_editor_property('use_custom_primitive_data', True)
    n.set_editor_property('primitive_data_index', idx)
    n.set_editor_property('group', 'SD Ground Blend')
    return n
def scal(name, v, y):
    n = add(unreal.MaterialExpressionScalarParameter, -1100, y)
    n.set_editor_property('parameter_name', name)
    n.set_editor_property('default_value', v)
    n.set_editor_property('group', 'SD Ground Blend')
    return n
cin = fin('Colour', FI.FUNCTION_INPUT_VECTOR3, -300, 0)
rin = fin('Roughness', FI.FUNCTION_INPUT_SCALAR, -200, 1)
rs = add(unreal.MaterialExpressionRuntimeVirtualTextureSample, -1100, -500)
rvt = eal.load_asset(RVTP)
rs.set_editor_property('virtual_texture', rvt)
rs.set_editor_property('material_type', rvt.get_editor_property('material_type'))
rs.set_editor_property('single_physical_space', rvt.get_editor_property('single_physical_space'))
wp = add(unreal.MaterialExpressionWorldPosition, -1100, -300)
op = add(unreal.MaterialExpressionObjectPositionWS, -1100, -220)
ob = add(unreal.MaterialExpressionObjectBounds, -1100, -140)
vn = add(unreal.MaterialExpressionVertexNormalWS, -1100, -60)
c = add(unreal.MaterialExpressionCustom, -600, 0)
c.set_editor_property('description', 'PropGroundBlend', QUIET)
c.set_editor_property('output_type', unreal.CustomMaterialOutputType.CMOT_FLOAT4, QUIET)
c.set_editor_property('code', CODE, QUIET)
pins = ['Col', 'Rough', 'Ground', 'GRough', 'WP', 'OP', 'OB', 'N', 'C0', 'C1', 'C2', 'C3', 'Dust', 'T5', 'T6', 'T7', 'FadeH', 'BaseK', 'Match']
arr = []
for p in pins:
    ci = unreal.CustomInput()
    ci.set_editor_property('input_name', p)
    arr.append(ci)
c.set_editor_property('inputs', arr, QUIET)
link(cin, '', c, 'Col')
link(rin, '', c, 'Rough')
link(rs, 'BaseColor', c, 'Ground')
link(rs, 'Roughness', c, 'GRough')
link(wp, '', c, 'WP')
link(op, '', c, 'OP')
link(ob, '', c, 'OB')
link(vn, '', c, 'N')
names = [('C0', 'SD_GroundDZ', 0, 0.0), ('C1', 'SD_GroundSX', 1, 0.0), ('C2', 'SD_GroundSY', 2, 0.0), ('C3', 'SD_GroundValid', 3, 0.0),
         ('Dust', 'SD_Dust', 4, 0.4), ('T5', 'SD_TintR', 5, 1.0), ('T6', 'SD_TintG', 6, 1.0), ('T7', 'SD_TintB', 7, 1.0)]
y = 100
for pin, pname, idx, v in names:
    link(cpd(pname, idx, v, y), '', c, pin)
    y += 70
for pin, pname in [('FadeH', 'SD_FadeHeight'), ('BaseK', 'SD_BaseStrength'), ('Match', 'SD_PaletteMatch')]:
    link(scal(pname, DEF[pname], y), '', c, pin)
    y += 70
rgb = add(unreal.MaterialExpressionComponentMask, -300, -100)
rgb.set_editor_property('r', True)
rgb.set_editor_property('g', True)
rgb.set_editor_property('b', True)
rgb.set_editor_property('a', False)
link(c, '', rgb, '')
al = add(unreal.MaterialExpressionComponentMask, -300, 60)
al.set_editor_property('r', False)
al.set_editor_property('g', False)
al.set_editor_property('b', False)
al.set_editor_property('a', True)
link(c, '', al, '')
oc = add(unreal.MaterialExpressionFunctionOutput, 0, -100)
oc.set_editor_property('output_name', 'Colour')
oc.set_editor_property('sort_priority', 0)
link(rgb, '', oc, '')
orr = add(unreal.MaterialExpressionFunctionOutput, 0, 60)
orr.set_editor_property('output_name', 'Roughness')
orr.set_editor_property('sort_priority', 1)
link(al, '', orr, '')
mel.update_material_function(f)
print('MF fails=' + str(fails) + ' saved=' + str(eal.save_loaded_asset(f, False)))
'''

# One source material per call: duplicate (a Material) or duplicate the MI chain onto a blended master copy.
VARIANT = COMMON + r'''
ensure_dir(MDIR)
fn = eal.load_asset(MDIR + '/MF_SD_PropGroundBlend')
MP = unreal.MaterialProperty
def uname(o):
    p = o.get_path_name().split('.')[0]
    parts = p.split('/')
    return (parts[-2] + '_' + parts[-1]) if parts[-1].startswith('Material') else parts[-1]
def insert(m):
    if m.get_editor_property('use_material_attributes'):
        att = mel.get_material_property_input_node(m, MP.MP_MATERIAL_ATTRIBUTES)
        atto = mel.get_material_property_input_node_output_name(m, MP.MP_MATERIAL_ATTRIBUTES)
        brk = mel.create_material_expression(m, unreal.MaterialExpressionBreakMaterialAttributes, 200, -400)
        link(att, atto, brk, '')
        mk = mel.create_material_expression(m, unreal.MaterialExpressionMakeMaterialAttributes, 700, -400)
        mk.set_editor_property('desc', 'SDGroundBlend')
        for n in ['Metallic', 'Specular', 'Anisotropy', 'EmissiveColor', 'Opacity', 'OpacityMask', 'Normal', 'Tangent',
                  'WorldPositionOffset', 'SubsurfaceColor', 'AmbientOcclusion', 'PixelDepthOffset', 'Displacement']:
            mel.connect_material_expressions(brk, n, mk, n)
        call = mel.create_material_expression(m, unreal.MaterialExpressionMaterialFunctionCall, 450, -200)
        call.set_material_function(fn)
        link(brk, 'BaseColor', call, 'Colour')
        link(brk, 'Roughness', call, 'Roughness')
        link(call, 'Colour', mk, 'BaseColor')
        link(call, 'Roughness', mk, 'Roughness')
        mel.connect_material_property(mk, '', MP.MP_MATERIAL_ATTRIBUTES)
        return
    bc = mel.get_material_property_input_node(m, MP.MP_BASE_COLOR)
    bco = mel.get_material_property_input_node_output_name(m, MP.MP_BASE_COLOR)
    ro = mel.get_material_property_input_node(m, MP.MP_ROUGHNESS)
    roo = mel.get_material_property_input_node_output_name(m, MP.MP_ROUGHNESS) if ro else ''
    call = mel.create_material_expression(m, unreal.MaterialExpressionMaterialFunctionCall, 300, 0)
    call.set_material_function(fn)
    if bc is not None:
        link(bc, bco, call, 'Colour')
    if ro is not None:
        link(ro, roo, call, 'Roughness')
    else:
        cr = mel.create_material_expression(m, unreal.MaterialExpressionConstant, 100, 200)
        cr.set_editor_property('r', 0.8)
        link(cr, '', call, 'Roughness')
    mel.connect_material_property(call, 'Colour', MP.MP_BASE_COLOR)
    mel.connect_material_property(call, 'Roughness', MP.MP_ROUGHNESS)
def master_gb(m):
    dst = MDIR + '/' + uname(m) + '_GB'
    if eal.does_asset_exist(dst):
        return eal.load_asset(dst)
    g = eal.duplicate_asset(m.get_path_name().split('.')[0], dst)
    insert(g)
    g.set_editor_property('used_with_instanced_static_meshes', True)
    mel.recompile_material(g)
    eal.save_loaded_asset(g, False)
    return g
def chain_gb(mi):
    par = mi.get_editor_property('parent')
    newpar = master_gb(par) if isinstance(par, unreal.Material) else chain_gb(par)
    dst = MDIR + '/' + uname(mi) + '_GB'
    d = eal.load_asset(dst) if eal.does_asset_exist(dst) else eal.duplicate_asset(mi.get_path_name().split('.')[0], dst)
    mel.set_material_instance_parent(d, newpar)
    mel.update_material_instance(d)
    eal.save_loaded_asset(d, False)
    return d
src = eal.load_asset(SRC)
if src is None:
    print('VARIANT missing ' + SRC)
elif isinstance(src, unreal.MaterialInstance):
    out = chain_gb(src)
    print('MAP ' + SRC + ' ' + out.get_path_name().split('.')[0])
else:
    out = master_gb(src)
    print('MAP ' + SRC + ' ' + out.get_path_name().split('.')[0])
print('VARIANT fails=' + str(fails) + ' DONE')
'''


def fill(body, **kw):
    lines = ['%s = %r' % (k, v) for k, v in kw.items()]
    return ps.validate('\n'.join(lines) + '\n' + body)


def scripts():
    yield 'decal', fill(DECAL, GDIR=GROUND_DIR, TEXDEF=DIRT, CODE=hlsl('SetDressGround.hlsl'))
    yield 'decalmi', fill(DECAL_MI, GDIR=GROUND_DIR, SURF={'path': SURFACES['path']})
    yield 'blendfn', fill(BLENDFN, MDIR=MAT_DIR, RVTP=RVT, CODE=hlsl('PropGroundBlend.hlsl'), DEF=PROP_DEFAULTS)
    yield 'variant', fill(VARIANT, MDIR=MAT_DIR, SRC='/Game/X/M_Test')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('mode', choices=['check', 'decal', 'decalmi', 'blendfn', 'variants'])
    ap.add_argument('site', nargs='?')
    ap.add_argument('--only', type=int, default=0, help='variants: at most N materials this run')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--port', type=int, default=int(os.environ.get('HAYBA_PORT', 52342)))
    args = ap.parse_args()
    if args.mode == 'check':
        for name, sc in scripts():
            compile(sc, name, 'exec')
            print('ok', name, len(sc))
        return
    R = ps.Runner(args)
    if args.mode == 'decalmi':
        names = [args.site] if args.site else list(SURFACES)
        for n in names:
            R.send('mat_decalmi', fill(DECAL_MI, GDIR=GROUND_DIR, SURF={n: SURFACES[n]}))
        return
    if args.mode in ('decal', 'blendfn'):
        name, sc = [x for x in scripts() if x[0] == args.mode][0]
        R.send('mat_' + name, sc)
        return
    sid = args.site or ''
    st = ps.read_state(ps.site_of(ps.load_doc(True), sid)['id'])
    # the foliage MIs (the dry tufts' MI_Saskarta_DryTuft_*) already blend to the RVT ground (LANE4): no _GB copy
    mats = [m for m in st.get('materials', []) if not m.startswith(('/Engine', MAT_DIR, GROUND_DIR, FOLIAGE_DIR))]
    mp = json.load(open(ps.MATERIAL_MAP_JSON, encoding='utf8')) if os.path.exists(ps.MATERIAL_MAP_JSON) else {}
    todo = [m for m in mats if m not in mp]
    if args.only:
        todo = todo[:args.only]
    print('%d materials, %d mapped, %d to do now' % (len(mats), len(mp), len(todo)))
    for m in todo:
        out = R.send('mat_variant', fill(VARIANT, MDIR=MAT_DIR, SRC=m))
        for line in (out or '').splitlines():
            if line.startswith('MAP '):
                _, a, b = line.split(' ')
                mp[a] = b
        if not args.dry_run:
            with open(ps.MATERIAL_MAP_JSON, 'w', encoding='utf8') as fh:
                json.dump(mp, fh, indent=1, sort_keys=True)


if __name__ == '__main__':
    main()
