"""Build and place the High Voice beacon, and set up the far HLOD layer (Task L2).

    python Tools/Look/build_high_voice.py materials   # M_Saskarta_HighVoiceBeam + M_Saskarta_HighVoiceCrown
    python Tools/Look/build_high_voice.py blueprint   # BP_Saskarta_HighVoice (mast, crown, beam)
    python Tools/Look/build_high_voice.py place       # the level instance at spline point 0
    python Tools/Look/build_high_voice.py hlod        # HLOD_Saskarta_Far and its assignment
    python Tools/Look/build_high_voice.py read        # print the current state

Spec: docs/superpowers/specs/2026-09-26-saskarta-world-sprint-design.md, section 6
("The High Voice"): an 8 m warm emissive crown, and an unlit additive translucent beam with
scrolling noise that keeps a minimum screen size so it reads at 3 km and fades with the cloud
base. No dynamic light. Every step is idempotent (it rebuilds or reuses what is there).

The beacon (spline point 0, 298079.6, 483050) is not spatially loaded, so it renders from
anywhere even while the terrain around it is streamed out.

Minimum screen size is done in the vertex shader (world position offset): beyond the distance
where the real size falls below MinAngularRadius, the crown and the beam's cross-section grow
with distance so their angular size stays constant. The mesh bounds are not scaled for it; the
beam's bounds are 400 m tall anyway, and the crown only grows at distances where its bounds
are a few pixels.

Runs through Hayba python_run (5 s per call, banned words checked). Wrap it in
Tools/GameFlow/editor_gate.py acquire/release. It saves nothing; save by explicit list.
"""
import argparse
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from apply_look import python_run, check_banned  # noqa: E402

FOLDER = "/Game/SaskartaGaea/Story"
BEAM = "M_Saskarta_HighVoiceBeam"
CROWN = "M_Saskarta_HighVoiceCrown"
BP = "BP_Saskarta_HighVoice"
MPC = "/Game/SaskartaGaea/Look/MPC_Saskarta_Sky.MPC_Saskarta_Sky"
NOISE = "/Engine/EngineMaterials/Good64x64TilingNoiseHighFreq.Good64x64TilingNoiseHighFreq"
PILLAR = "/Game/EasyAtmos/EpicContentDemo/DemoRoom/Meshes/Tile_10MPillar.Tile_10MPillar"
HLOD_FOLDER = "/Game/SaskartaGaea/HLOD"
HLOD = "HLOD_Saskarta_Far"
LABEL = "HighVoice"

# Accent #C8703A (concept board), sRGB -> linear.
ACCENT_LINEAR = (0.578, 0.166, 0.042)
CROWN_EMISSIVE = 40.0          # brief: about 40
BEAM_EMISSIVE = 8.0            # brief: about 8
CROWN_DIAMETER_M = 8.0
BEAM_WIDTH_M = 3.0
BEAM_HEIGHT_M = 400.0
MAST_SECTIONS = 4              # 4 x Tile_10MPillar (0.5 x 1 m, 10 m, pivot at its base) = 40 m
# Minimum angular radius. 3 km at 1440p and a 70 deg horizontal FOV is about 1830 px/rad:
# the 1.5 m beam radius (0.0005 rad) would be about 1.8 px wide; 0.0012 rad keeps it about
# 4.4 px, and the crown's 0.002 rad keeps it about 7 px across.
BEAM_MIN_ANGULAR_RADIUS = 0.0012
CROWN_MIN_ANGULAR_RADIUS = 0.002
# MPC_Saskarta_Sky.BaseAltitude is km above the SkyAtmosphere planet top (apply_look.py).
PLANET_TOP_Z_CM = -45000.0
CLOUD_FADE_LENGTH_CM = 20000.0   # the beam fades over 200 m ...
CLOUD_FADE_OFFSET_CM = 5000.0    # ... ending 50 m inside the cloud base
# Spline point 0 (Tools/Story/build_road_profile.py SPLINE_POINTS_CM[0]); Z is traced at place time.
SITE_CM = (298079.6, 483050.0, 10898.0)
HLOD_CELL_CM = 102400            # 1 km HLOD cells over the 8.16 km map


def run(script, label):
    ok, out, err = python_run(check_banned(script))
    print(f"--- {label}: {'ok' if ok else 'FAILED'}")
    if out.strip():
        print(out.rstrip())
    if not ok:
        print(err, file=sys.stderr)
        raise SystemExit(1)
    return out


def sub(text, **kw):
    for k, v in kw.items():
        text = text.replace(f"__{k}__", str(v))
    return text


# ----------------------------------------------------------------------------- materials

MAT_HEAD = """
import unreal
M = unreal.MaterialEditingLibrary
E = unreal.EditorAssetLibrary
full = '__FOLDER__/__NAME__'
# Rebuild in place (the Blueprint references the asset). delete_all_material_expressions
# leaves parameter nodes behind, so delete every expression one by one.
if E.does_asset_exist(full):
    mat = unreal.load_asset(full)
    for x in list(M.get_material_expressions(mat)):
        M.delete_material_expression(mat, x)
else:
    mat = unreal.AssetToolsHelpers.get_asset_tools().create_asset('__NAME__', '__FOLDER__', unreal.Material, unreal.MaterialFactoryNew())
def node(cls, x, y):
    return M.create_material_expression(mat, cls, x, y)
def scal(n, v, x, y):
    e = node(unreal.MaterialExpressionScalarParameter, x, y)
    e.set_editor_property('parameter_name', n)
    e.set_editor_property('default_value', v)
    return e
def vec(n, v, x, y):
    e = node(unreal.MaterialExpressionVectorParameter, x, y)
    e.set_editor_property('parameter_name', n)
    e.set_editor_property('default_value', unreal.LinearColor(v[0], v[1], v[2], 1.0))
    return e
def custom(desc, code, ins, otype, x, y):
    e = node(unreal.MaterialExpressionCustom, x, y)
    e.set_editor_property('description', desc)
    e.set_editor_property('code', code)
    e.set_editor_property('output_type', otype)
    arr = []
    for i in ins:
        c = unreal.CustomInput()
        c.set_editor_property('input_name', i)
        arr.append(c)
    e.set_editor_property('inputs', arr)
    return e
def link(a, b, pin):
    if not M.connect_material_expressions(a, '', b, pin):
        print('LINK FAILED', pin)
F3 = unreal.CustomMaterialOutputType.CMOT_FLOAT3
F2 = unreal.CustomMaterialOutputType.CMOT_FLOAT2
"""

# World position offset that keeps a minimum angular radius (A) for a mesh of radius R:
# beyond distance R/A the geometry grows around the object origin. Beam: horizontal only.
WPO_BEAM = "float d = length(WP - CP); float s = max(1.0, d * A / R); return float3((WP.xy - OP.xy) * (s - 1.0), 0.0);"
WPO_CROWN = "float d = length(WP - CP); float s = max(1.0, d * A / R); return (WP - OP) * (s - 1.0);"
UV1 = "return float2(UV.x * 2.0, WP.z / L - T * S);"
UV2 = "return float2(UV.x * 3.0 + 0.37, WP.z / (L * 0.37) - T * S * 2.3);"
BEAM_EMIT = (
    "float h = saturate((WP.z - OP.z) / H + 0.5);"
    " float ends = saturate(h * 40.0) * saturate((1.0 - h) * 3.0);"
    " float cb = PT + BA * 100000.0;"
    " float bz = OP.z - 0.5 * H;"
    " float cf = max(saturate((cb + FO - WP.z) / FL), saturate((bz - cb) * 0.01));"
    " float core = pow(saturate(abs(dot(normalize(N), normalize(V)))), 2.0);"
    " float n = saturate(0.35 + 1.3 * N1 * N2);"
    " return C * I * n * core * ends * cf;"
)

BEAM_BODY = """
mat.set_editor_property('blend_mode', unreal.BlendMode.BLEND_ADDITIVE)
mat.set_editor_property('shading_model', unreal.MaterialShadingModel.MSM_UNLIT)
mat.set_editor_property('two_sided', True)
wpv = node(unreal.MaterialExpressionWorldPosition, -1400, 600)
wpv.set_editor_property('world_position_shader_offset', unreal.WorldPositionIncludedOffsets.WPT_EXCLUDE_ALL_SHADER_OFFSETS)
wp = node(unreal.MaterialExpressionWorldPosition, -1400, -200)
op = node(unreal.MaterialExpressionObjectPositionWS, -1400, 0)
cp = node(unreal.MaterialExpressionCameraPositionWS, -1400, 800)
hb = scal('BeamHeight', __H__, -1400, 100)
nr = node(unreal.MaterialExpressionVertexNormalWS, -1400, 200)
cv = node(unreal.MaterialExpressionCameraVectorWS, -1400, 300)
tm = node(unreal.MaterialExpressionTime, -1400, -400)
tc = node(unreal.MaterialExpressionTextureCoordinate, -1400, -500)
col = vec('BeamColor', __COL__, -1000, 400)
ins = scal('EmissiveIntensity', __I__, -1000, 500)
spd = scal('ScrollSpeed', 0.05, -1000, -400)
nz = scal('NoiseScaleZ', 6000.0, -1000, -300)
rad = scal('BeamRadius', __R__, -1000, 900)
ang = scal('MinAngularRadius', __A__, -1000, 1000)
pt = scal('PlanetTopZ', __PT__, -1000, 600)
fl = scal('CloudFadeLength', __FL__, -1000, 700)
fo = scal('CloudFadeOffset', __FO__, -1000, 800)
ba = node(unreal.MaterialExpressionCollectionParameter, -1000, 250)
ba.set_editor_property('collection', unreal.load_asset('__MPC__'))
ba.set_editor_property('parameter_name', 'BaseAltitude')
u1 = custom('NoiseUV1', '__UV1__', ['UV', 'WP', 'T', 'S', 'L'], F2, -700, -500)
u2 = custom('NoiseUV2', '__UV2__', ['UV', 'WP', 'T', 'S', 'L'], F2, -700, -300)
for u in (u1, u2):
    link(tc, u, 'UV'); link(wp, u, 'WP'); link(tm, u, 'T'); link(spd, u, 'S'); link(nz, u, 'L')
tex = unreal.load_asset('__NOISE__')
s1 = node(unreal.MaterialExpressionTextureSample, -450, -500)
s2 = node(unreal.MaterialExpressionTextureSample, -450, -250)
for s, u in ((s1, u1), (s2, u2)):
    s.set_editor_property('texture', tex)
    s.set_editor_property('sampler_type', unreal.MaterialSamplerType.SAMPLERTYPE_LINEAR_GRAYSCALE)
    link(u, s, 'UVs')
em = custom('BeamEmissive', '__EMIT__', ['WP', 'OP', 'H', 'N', 'V', 'N1', 'N2', 'BA', 'PT', 'FL', 'FO', 'C', 'I'], F3, -150, 0)
for a, p in ((wp, 'WP'), (op, 'OP'), (hb, 'H'), (nr, 'N'), (cv, 'V'), (ba, 'BA'), (pt, 'PT'), (fl, 'FL'), (fo, 'FO'), (col, 'C'), (ins, 'I')):
    link(a, em, p)
M.connect_material_expressions(s1, 'R', em, 'N1')
M.connect_material_expressions(s2, 'R', em, 'N2')
wo = custom('MinScreenWidth', '__WPO__', ['WP', 'OP', 'CP', 'R', 'A'], F3, -150, 700)
for a, p in ((wpv, 'WP'), (op, 'OP'), (cp, 'CP'), (rad, 'R'), (ang, 'A')):
    link(a, wo, p)
print('emissive', M.connect_material_property(em, '', unreal.MaterialProperty.MP_EMISSIVE_COLOR))
print('wpo', M.connect_material_property(wo, '', unreal.MaterialProperty.MP_WORLD_POSITION_OFFSET))
print('nodes', M.get_num_material_expressions(mat))
"""

CROWN_BODY = """
mat.set_editor_property('blend_mode', unreal.BlendMode.BLEND_OPAQUE)
mat.set_editor_property('shading_model', unreal.MaterialShadingModel.MSM_UNLIT)
wpv = node(unreal.MaterialExpressionWorldPosition, -900, 300)
wpv.set_editor_property('world_position_shader_offset', unreal.WorldPositionIncludedOffsets.WPT_EXCLUDE_ALL_SHADER_OFFSETS)
op = node(unreal.MaterialExpressionObjectPositionWS, -900, 400)
cp = node(unreal.MaterialExpressionCameraPositionWS, -900, 500)
col = vec('CrownColor', __COL__, -700, -100)
ins = scal('EmissiveIntensity', __I__, -700, 50)
rad = scal('CrownRadius', __R__, -700, 600)
ang = scal('MinAngularRadius', __A__, -700, 700)
mul = node(unreal.MaterialExpressionMultiply, -350, 0)
link(col, mul, 'A'); link(ins, mul, 'B')
wo = custom('MinScreenSize', '__WPO__', ['WP', 'OP', 'CP', 'R', 'A'], F3, -350, 400)
for a, p in ((wpv, 'WP'), (op, 'OP'), (cp, 'CP'), (rad, 'R'), (ang, 'A')):
    link(a, wo, p)
print('emissive', M.connect_material_property(mul, '', unreal.MaterialProperty.MP_EMISSIVE_COLOR))
print('wpo', M.connect_material_property(wo, '', unreal.MaterialProperty.MP_WORLD_POSITION_OFFSET))
print('nodes', M.get_num_material_expressions(mat))
"""

COMPILE = """
import unreal
M = unreal.MaterialEditingLibrary
mat = unreal.load_asset('__FOLDER__/__NAME__')
M.recompile_material(mat)
print('recompiled __NAME__')
"""

STATS = """
import unreal
M = unreal.MaterialEditingLibrary
for n in ('__BEAM__', '__CROWN__'):
    mat = unreal.load_asset('__FOLDER__/' + n)
    st = M.get_statistics(mat)
    print(n, 'vs', st.num_vertex_shader_instructions, 'ps', st.num_pixel_shader_instructions, 'samplers', st.num_samplers,
          'blend', str(mat.get_editor_property('blend_mode')), 'model', str(mat.get_editor_property('shading_model')))
"""


def materials():
    common = dict(FOLDER=FOLDER, COL=ACCENT_LINEAR)
    run(sub(MAT_HEAD, NAME=BEAM, **common) + sub(
        BEAM_BODY, I=BEAM_EMISSIVE, R=BEAM_WIDTH_M * 50.0, A=BEAM_MIN_ANGULAR_RADIUS, PT=PLANET_TOP_Z_CM,
        FL=CLOUD_FADE_LENGTH_CM, FO=CLOUD_FADE_OFFSET_CM, MPC=MPC, NOISE=NOISE, UV1=UV1, UV2=UV2,
        EMIT=BEAM_EMIT, WPO=WPO_BEAM, COL=ACCENT_LINEAR, H=BEAM_HEIGHT_M * 100.0), BEAM)
    run(sub(COMPILE, FOLDER=FOLDER, NAME=BEAM), "compile beam")
    run(sub(MAT_HEAD, NAME=CROWN, **common) + sub(
        CROWN_BODY, I=CROWN_EMISSIVE, R=CROWN_DIAMETER_M * 50.0, A=CROWN_MIN_ANGULAR_RADIUS,
        WPO=WPO_CROWN, COL=ACCENT_LINEAR), CROWN)
    run(sub(COMPILE, FOLDER=FOLDER, NAME=CROWN), "compile crown")


# ----------------------------------------------------------------------------- blueprint

BP_CREATE = """
import unreal
E = unreal.EditorAssetLibrary
full = '__FOLDER__/__BP__'
if E.does_asset_exist(full):
    print('exists', full)
else:
    f = unreal.BlueprintFactory()
    f.set_editor_property('parent_class', unreal.Actor)
    bp = unreal.AssetToolsHelpers.get_asset_tools().create_asset('__BP__', '__FOLDER__', unreal.Blueprint, f)
    print('created', bp.get_path_name())
"""

# One call per component keeps each python_run well inside 5 s.
BP_COMPONENT = """
import unreal
S = unreal.get_engine_subsystem(unreal.SubobjectDataSubsystem)
BL = unreal.SubobjectDataBlueprintFunctionLibrary
bp = unreal.load_asset('__FOLDER__/__BP__')
hs = S.k2_gather_subobject_data_for_blueprint(bp)
names = [str(BL.get_variable_name(BL.get_data(h))) for h in hs]
print('have', names)
if '__CNAME__' not in names:
    h, why = S.add_new_subobject(unreal.AddNewSubobjectParams(parent_handle=hs[0], new_class=unreal.StaticMeshComponent, blueprint_context=bp))
    S.rename_subobject(h, unreal.Text('__CNAME__'))
    hs = S.k2_gather_subobject_data_for_blueprint(bp)
for h in hs:
    if str(BL.get_variable_name(BL.get_data(h))) == '__CNAME__':
        c = BL.get_object(BL.get_data(h))
        c.set_editor_property('static_mesh', unreal.load_asset('__MESH__'))
        c.set_editor_property('relative_location', unreal.Vector(0.0, 0.0, __Z__))
        c.set_editor_property('relative_scale3d', unreal.Vector(__SX__, __SY__, __SZ__))
        __EXTRA__
        print('set', c.get_name(), str(c.get_editor_property('static_mesh').get_name()))
"""

NO_SHADOW = ("c.set_editor_property('cast_shadow', False); "
             "c.set_collision_enabled(unreal.CollisionEnabled.NO_COLLISION); "
             "c.set_editor_property('can_character_step_up_on', unreal.CanBeCharacterBase.ECB_NO); "
             "c.set_material(0, unreal.load_asset('__MAT__'))")

BP_FINISH = """
import unreal
bp = unreal.load_asset('__FOLDER__/__BP__')
unreal.BlueprintEditorLibrary.compile_blueprint(bp)
cdo = unreal.get_default_object(bp.generated_class())
cdo.set_editor_property('is_spatially_loaded', False)
print('compiled; CDO spatially loaded =', cdo.get_editor_property('is_spatially_loaded'))
"""


def blueprint():
    run(sub(BP_CREATE, FOLDER=FOLDER, BP=BP), "create BP")
    for i in range(MAST_SECTIONS):
        run(sub(BP_COMPONENT, FOLDER=FOLDER, BP=BP, CNAME=f"Mast{i}", MESH=PILLAR, Z=i * 1000.0,
                SX=1.0, SY=1.0, SZ=1.0, EXTRA="pass"), f"Mast{i}")
    mast_top = MAST_SECTIONS * 1000.0
    crown_z = mast_top + CROWN_DIAMETER_M * 50.0 - 100.0   # sits 1 m down over the mast top
    s = CROWN_DIAMETER_M  # the engine sphere is 1 m across
    run(sub(BP_COMPONENT, FOLDER=FOLDER, BP=BP, CNAME="Crown", MESH="/Engine/BasicShapes/Sphere.Sphere",
            Z=crown_z, SX=s, SY=s, SZ=s, EXTRA=sub(NO_SHADOW, MAT=f"{FOLDER}/{CROWN}")), "Crown")
    w, hgt = BEAM_WIDTH_M, BEAM_HEIGHT_M   # the engine cylinder is 1 m across and 1 m tall, pivot at its centre
    # Preserve the existing component for asset compatibility, but the summit
    # direction has no permanent vertical sky beam.
    hidden_beam = sub(NO_SHADOW, MAT=f"{FOLDER}/{BEAM}") + "; c.set_editor_property('visible', False); c.set_editor_property('hidden_in_game', True)"
    run(sub(BP_COMPONENT, FOLDER=FOLDER, BP=BP, CNAME="Beam", MESH="/Engine/BasicShapes/Cylinder.Cylinder",
            Z=crown_z + hgt * 50.0, SX=w, SY=w, SZ=hgt, EXTRA=hidden_beam), "Beam")
    run(sub(BP_FINISH, FOLDER=FOLDER, BP=BP), "compile BP")


# ----------------------------------------------------------------------------- placement

PLACE = """
import unreal
eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
w = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
x, y, zs = __X__, __Y__, __Z__
h = unreal.SystemLibrary.line_trace_single(w, unreal.Vector(x, y, zs + 50000.0), unreal.Vector(x, y, zs - 50000.0), unreal.TraceTypeQuery.TRACE_TYPE_QUERY1, False, [], unreal.DrawDebugTrace.NONE, True)
t = h.to_tuple()
gz = zs
if t[0]:
    gz = t[4].z
print('ground hit', t[0], 'z', round(gz, 1), 'spline z', zs)
a = None
for e in eas.get_all_level_actors():
    if e.get_actor_label() == '__LABEL__':
        a = e
cls = unreal.load_asset('__FOLDER__/__BP__').generated_class()
if a is None:
    a = eas.spawn_actor_from_class(cls, unreal.Vector(x, y, gz - 50.0), unreal.Rotator(0.0, 0.0, 0.0))
    a.set_actor_label('__LABEL__')
a.set_actor_location(unreal.Vector(x, y, gz - 50.0), False, False)
a.set_editor_property('is_spatially_loaded', False)
print('placed', a.get_actor_label(), str(a.get_actor_location()), 'spatially loaded', a.get_editor_property('is_spatially_loaded'), a.get_package().get_name())
"""


def place():
    x, y, z = SITE_CM
    run(sub(PLACE, X=x, Y=y, Z=z, LABEL=LABEL, FOLDER=FOLDER, BP=BP), "place")


# ----------------------------------------------------------------------------- HLOD

HLOD_CREATE = """
import unreal
E = unreal.EditorAssetLibrary
full = '__HF__/__HN__'
if E.does_asset_exist(full):
    L = unreal.load_asset(full)
else:
    L = unreal.AssetToolsHelpers.get_asset_tools().create_asset('__HN__', '__HF__', unreal.HLODLayer, None)
# A layer made without HLODLayerFactory has no builder settings object; changing the layer type
# runs PostEditChange, which creates it (HLODBuilderInstancingSettings).
L.set_editor_property('layer_type', unreal.HLODLayerType.MESH_MERGE)
L.set_editor_property('layer_type', unreal.HLODLayerType.INSTANCING)
L.set_editor_property('is_spatially_loaded', False)
L.set_editor_property('cell_size', __CELL__)
L.set_editor_property('parent_layer', None)
for p in ('layer_type', 'is_spatially_loaded', 'cell_size', 'parent_layer'):
    print(p, str(L.get_editor_property(p)))
bs = L.get_editor_property('hlod_builder_settings')
print('builder settings', str(bs.get_class().get_name()) if bs else 'MISSING')
"""

# UE 5.8 requires every HLOD layer to be listed in a runtime partition's HLOD setups
# (hard-coded RequireExplicitHLODLayerPartitionAssignation). HLOD_Saskarta_Far is not, and those
# setups cannot be edited from Python, so the builder dropped it and built 0 HLOD actors.
# The level's registered template chain is used instead: _Instanced (spatially loaded) ->
# _Merged (always loaded), which keeps the far mountain drawn from anywhere.
HLOD_ASSIGN = """
import unreal
eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
w = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
L = unreal.load_asset('/Game/level/Saskarta_WP_HLODLayer_Instanced')
wp = w.get_world_settings().get_editor_property('world_partition')
print('default before', str(wp.get_editor_property('default_hlod_layer').get_name()))
wp.set_editor_property('default_hlod_layer', L)
for a in eas.get_all_level_actors():
    if a.get_class().get_name() in ('Landscape', 'LandscapeStreamingProxy') or a.get_actor_label() in __ROCKS__:
        a.set_editor_property('hlod_layer', None)
        print('cleared', a.get_actor_label(), a.get_package().get_name())
print('default after', str(wp.get_editor_property('default_hlod_layer').get_name()))
"""

READ = """
import unreal
eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
w = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
wp = w.get_world_settings().get_editor_property('world_partition')
print('default hlod', str(wp.get_editor_property('default_hlod_layer').get_path_name()))
for a in eas.get_all_level_actors():
    n = a.get_class().get_name()
    if n in ('Landscape', 'LandscapeStreamingProxy', 'PCGVolume') or a.get_actor_label() == '__LABEL__':
        hl = a.get_editor_property('hlod_layer')
        print(a.get_actor_label(), n, 'hlod', str(hl.get_name()) if hl else 'None', 'spatial', a.get_editor_property('is_spatially_loaded'), str(a.get_actor_location()))
"""

ROCK_VOLUMES = ("PCG_Saskarta_RocksDebris",)


def hlod():
    run(sub(HLOD_CREATE, HF=HLOD_FOLDER, HN=HLOD, CELL=HLOD_CELL_CM), "HLOD layer")
    run(sub(HLOD_ASSIGN, HF=HLOD_FOLDER, HN=HLOD, ROCKS=repr(ROCK_VOLUMES)), "HLOD assign")


def read():
    run(sub(READ, LABEL=LABEL), "read")
    run(sub(STATS, FOLDER=FOLDER, BEAM=BEAM, CROWN=CROWN), "material stats")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("step", choices=["materials", "blueprint", "place", "hlod", "read"])
    a = ap.parse_args(argv)
    {"materials": materials, "blueprint": blueprint, "place": place, "hlod": hlod, "read": read}[a.step]()
    return 0


if __name__ == "__main__":
    sys.exit(main())
