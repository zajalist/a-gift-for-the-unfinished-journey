# Build M_Saskarta_Ground / MI_Saskarta_Ground and assign it to the landscape (world sprint, Task V2).
#
# Sent as the script of Hayba python_run. It is NOT a standalone module: run
#
#     python Tools/Road/prepare_ground_material.py --send            # build the master + instance
#     python Tools/Road/prepare_ground_material.py --send --assign   # put the MI on the Landscape actor
#
# which fills the placeholders below (python_run may not read files):
#   AUTO_HLSL       <- Shaders/GroundAuto.hlsl  (RVT write pass)
#   READ_HLSL       <- Shaders/GroundRead.hlsl  (per-frame read pass + DebugView)
#   NOTILE_HLSL     <- Shaders/GroundNoTile.hlsl (write-pass anti-tiling, one node per layer)
#   NOTILE_N_HLSL   <- Shaders/GroundNoTileNormal.hlsl (turns its normals back, one per layer)
#   MASK_ORIGIN_CM  <- (X0, Y0) of the mask UV mapping, from Tools/Terrain/MASKS.md
#   MASK_EXTENT_CM  <- the mapping extent, from Tools/Terrain/MASKS.md (Ruling R5)
#   MODE            <- 'build' or 'assign'
#
# python_run rules this file obeys: 5 s cooperative deadline; none of the banned
# words (Tools/Road/ROAD.md); the policy scanner also reads string contents.
#
# The graph (Tools/Road/GROUND.md has the picture):
#   Mask UV  = (AbsoluteWorldPosition.xy - MASK_ORIGIN_CM) / MASK_EXTENT_CM   (MASKS.md, no flip)
#   Layer UV = (AbsoluteWorldPosition.xy - MASK_ORIGIN_CM) / <Layer> Tile     (world XY planar)
#   WRITE  (Runtime Virtual Texture Output, RVT_Saskarta_Terrain, page updates only):
#     rock, dirt, grass and snow texture sets (read from the current landscape
#     instance's parameters), each sampled twice through GroundNoTile (index-offset
#     and rotated copies, explicit turned derivatives of the plain UV) and flattened (its own
#     low-frequency blotches swapped for its average), x tints -> GroundAuto (Custom)
#     <- T_Saskarta_Ecology -> BaseColor, Roughness, Normal (world).
#   READ   (main pass, per frame): Runtime Virtual Texture Sample (BaseColor,
#     Roughness, Normal) + Detail Normal sample + PixelDepth -> GroundRead
#     (Custom: near detail and tone within 30 m, DebugView false colour, whose two
#     mask samples run only in its DebugView branch) -> BaseColor, Roughness,
#     Normal (world; tangent_space_normal is off), Emissive (debug only).
#   GRASS  (Landscape Grass Output): the density trees below, as math nodes, on
#     T_Saskarta_Ecology and T_Saskarta_RoadInfluence.
# Ruling R21: no stale Gaea mask texture is read anywhere.
#
# Idempotent: a re-run deletes every expression in the master and rebuilds it.
# 'build' saves only M_Saskarta_Ground and MI_Saskarta_Ground. 'assign' sets the
# Landscape actor's material (streaming proxies inherit it) and saves only the
# Landscape actor's own package. Starts nothing: no PIE, no level load.

AUTO_HLSL = r'''__AUTO__'''
READ_HLSL = r'''__READ__'''
NOTILE_HLSL = r'''__NOTILE__'''
NOTILE_N_HLSL = r'''__NOTILE_N__'''
MASK_ORIGIN_CM = None
MASK_EXTENT_CM = None
MODE = 'build'

# ---- FORMULAS BEGIN
# Grass-output densities (brief Step 3). Each is an expression tree the build turns
# into material math nodes; Tools/Road/tests/test_ground_material.py evaluates the
# same trees against the brief. Leaves: ('in', mask) and ('const', value). Masks:
# moisture, exposure = T_Saskarta_Ecology R, G; core, verge, neglect =
# T_Saskarta_RoadInfluence R, G, B.


def _c(v):
    return ('const', v)


def _in(name):
    return ('in', name)


def _mul(*xs):
    out = xs[0]
    for x in xs[1:]:
        out = ('mul', out, x)
    return out


def _add(a, b):
    return ('add', a, b)


def _om(a):
    return ('om', a)   # 1 - a


# verge thinning, scaled back by neglect: (1 - verge * (1 - neglect) * 0.85)
_VERGE_THIN = _om(_mul(_in('verge'), _om(_in('neglect')), _c(0.85)))
# Off-core factor. The brief's soft (1 - core) left small weights in the core's bilinear
# edge band, so the V3 probe found tufts rooted at core 0.50-0.63 on the maintained 4,350 m
# stretch (Review Focus 3). Task V3 fix round 1 hardened it to saturate(1 - 2 core).
# LOOK2 (user: "less foliage inside the road"): the RVT road's noise-warped edge reaches out
# to core ~0.15 in places, so every foliage type is now zero from core 0.3 inward and back to
# full at core 0: saturate(1 - core / 0.3). On the real masks core falls 0.3 -> 0 over about
# 1-1.5 m just outside the road edge, so the verge regrows over 1-2 m, not across the road.
OFF_CORE_ZERO = 0.3
_OFF_CORE = ('sat', _om(_mul(_in('core'), _c(1.0 / OFF_CORE_ZERO))))
# LOOK2 fix round 1 (review 4, user: "less foliage inside the road"): the core ramp alone let tufts
# root at core 0.15-0.3, right on the road's noise-warped edge (|d| ~3 m on a 4.5 m road), and at
# 1050 m they read as clutter along the ruts. A shoulder on the verge mask (a linear distance
# falloff: 0.96 on the centreline, 0.83 at 3 m, 0.74 at 4.5 m) keeps every foliage type off the
# first ~0.7 m outside the visible edge and brings it back over the next 1.5 m:
#   shoulder = saturate((SHOULDER_ZERO - verge) / (SHOULDER_ZERO - SHOULDER_FULL))
SHOULDER_ZERO = 0.835
SHOULDER_FULL = 0.74
_SHOULDER = ('sat', _add(_mul(_in('verge'), _c(-1.0 / (SHOULDER_ZERO - SHOULDER_FULL))),
                         _c(SHOULDER_ZERO / (SHOULDER_ZERO - SHOULDER_FULL))))

# grassNear = saturate((0.25 + 0.75 m)(1 - 0.8 e)) offcore shoulder (1 - verge (1 - neglect) 0.85)
#             + core * saturate((neglect - 0.8) / 0.2) * CROWN_MAX
# The crown term. V2 substituted core * neglect for the ribbon's crown, giving
# core * neglect^2 * 0.8: 0.41 at the 200 m stretch (neglect 0.72), a full-width carpet of
# about 5 blades per m2 that hid the road (LOOK2 brief, RoadVis captures). LOOK2: only truly
# abandoned stretches (neglect > 0.8) grow crown tufts, and sparsely: the weight rises from 0
# at neglect 0.8 to CROWN_MAX (0.15, under 2 blades per m2) at neglect 1. With the 0.03 spawn
# floor (configure_grass.py MIN_WEIGHT) the first tufts appear at neglect 0.84.
CROWN_NEGLECT = 0.8
CROWN_MAX = 0.15
_CROWN = _mul(_in('core'), ('sat', _add(_mul(_in('neglect'), _c(1.0 / (1.0 - CROWN_NEGLECT))),
                                       _c(-CROWN_NEGLECT / (1.0 - CROWN_NEGLECT)))), _c(CROWN_MAX))
GRASS_NEAR = _add(
    _mul(('sat', _mul(_add(_c(0.25), _mul(_c(0.75), _in('moisture'))), _om(_mul(_in('exposure'), _c(0.8))))),
         _OFF_CORE, _SHOULDER, _VERGE_THIN),
    _CROWN)

# grassDry: the mirror of grassNear, weighted toward exposure and away from moisture:
#   saturate((0.25 + 0.75 e)(1 - 0.8 m)) offcore shoulder (1 - verge (1 - neglect) 0.85)
GRASS_DRY = _mul(
    ('sat', _mul(_add(_c(0.25), _mul(_c(0.75), _in('exposure'))), _om(_mul(_in('moisture'), _c(0.8))))),
    _OFF_CORE, _SHOULDER, _VERGE_THIN)

# reeds = moisture^2 offcore shoulder
REEDS = _mul(_in('moisture'), _in('moisture'), _OFF_CORE, _SHOULDER)

# (grass-output pin name, LandscapeGrassType, density tree). LGT_Saskarta_Reeds is created
# by Task V3; until it exists its pin is built with no grass type, and a re-run fills it.
GRASS_OUTPUTS = [
    ('NearGrass', '/Game/SaskartaGaea/Foliage/LGT_Saskarta_NearGrass', GRASS_NEAR),
    ('DryGrass', '/Game/SaskartaGaea/Foliage/LGT_Saskarta_DryGrass', GRASS_DRY),
    ('Reeds', '/Game/SaskartaGaea/Foliage/LGT_Saskarta_Reeds', REEDS),
]
# ---- FORMULAS END

import unreal

PACKAGE_DIR = '/Game/SaskartaGaea/Materials'
ASSET_NAME = 'M_Saskarta_Ground'
MI_NAME = 'MI_Saskarta_Ground'
ASSET_PATH = PACKAGE_DIR + '/' + ASSET_NAME
MI_PATH = PACKAGE_DIR + '/' + MI_NAME
ECO_TEXTURE = '/Game/SaskartaGaea/Masks/T_Saskarta_Ecology'
ROAD_TEXTURE = '/Game/SaskartaGaea/Masks/T_Saskarta_RoadInfluence'
RVT_PATH = '/Game/SaskartaGaea/RVT/RVT_Saskarta_Terrain'

# The texture sets come from the landscape instance this material replaces (brief:
# "reuse its rock, dirt and grass texture sets; read them from the current instance's
# parameters"). Names are matched with runs of spaces collapsed ('Layer02 -  ORM').
# FALLBACK is what that instance held on 2026-09-27, used only once it is deleted
# (Step 5) and the master has not been built yet; a re-run otherwise keeps the
# master's own texture parameters.
SOURCE_MI = '/Game/SaskartaGaea/Materials/MI_Saskarta_ColdWasteland_PerfCandidate'
LAYERS = [  # (layer, source prefix, tile cm, fallback colour, ORM, normal, fallback tint)
    ('Rock', 'Layer01 Slope - ', 900.0, '/Game/AzielArts_Material/Textures/Rock/Rock_Color',
     '/Game/AzielArts_Material/Textures/Rock/Rock_ORM', '/Game/AzielArts_Material/Textures/Rock/Rock_NormalDX',
     (0.84, 0.80, 0.72)),
    ('Dirt', 'Layer02 - ', 520.0, '/Game/Pallbearer/Terrain/Tex/T_PH_dirt_aerial_02_diff',
     '/Game/Pallbearer/Terrain/Tex/T_PH_dirt_aerial_02_arm', '/Game/Pallbearer/Terrain/Tex/T_PH_dirt_aerial_02_nor_gl',
     (0.83, 0.79, 0.69)),
    ('Grass', 'Layer03 - ', 400.0, '/Game/Pallbearer/Terrain/Tex/T_PH_forest_ground_04_diff',
     '/Game/Pallbearer/Terrain/Tex/T_PH_forest_ground_04_arm',
     '/Game/Pallbearer/Terrain/Tex/T_PH_forest_ground_04_nor_gl', (1.10, 0.62, 0.72)),
    ('Snow', 'Snow - ', 700.0, '/Game/AzielArts_Material/Textures/ClumpSnow/ClumpSnow_Color',
     '/Game/AzielArts_Material/Textures/ClumpSnow/ClumpSnow_ORM',
     '/Game/AzielArts_Material/Textures/ClumpSnow/ClumpSnow_Normal', (1.0, 1.0, 1.0)),
]
# Layer tints set here win over the source instance and the master's own value.
# LOOK2 fix round 1 (review 3): the grass layer inherited a pink tint (1.10, 0.62, 0.72) from the
# ColdWasteland instance; times GrassTint it turned every moist hollow rust-red, so the olive and
# green patches never showed. A near-neutral olive keeps the forest-floor texture's own hue.
LAYER_TINT_OVERRIDE = {'Grass': (0.9, 1.0, 0.8)}
# Tile sizes (fix round 1, review finding 2): rock 14 m -> 9 m and snow 10 m -> 7 m, so the
# alpine ground near the road is crisp rather than smeared; dirt 4.5 m -> 5.2 m, off the
# grass tile's harmonics.
#
# Flatten per layer (0 = the map as is): colour + Flatten * (average - low), where low is the
# map at mip FLATTEN_MIP (16x16 texels, blotches bigger than about 1/8 of a tile). The
# Pallbearer 'aerial' dirt is a photo with large light streaks and dark blotches; tiled, those
# ARE the visible print. Flatten removes them and keeps the fine grain, so the colour does not
# go soft the way the old whole-map contrast cut did. Large-scale tone comes from the Ecology
# macro channel and the breakup noise instead, which never repeat.
FLATTEN = {'Rock': 0.4, 'Dirt': 0.85, 'Grass': 0.5, 'Snow': 0.5}
FLATTEN_MIP = 7
# Turn per layer (GroundNoTile): how far each offset copy may be turned, as a fraction of a full
# turn. The dirt and grass sets have no direction, so they turn freely, which scatters the
# aerial dirt's streaks. The rock set is stratified: turned freely its strata read as fur, so it
# turns by at most 0.06 x 360 = 22 degrees.
TURN = {'Rock': 0.06, 'Dirt': 1.0, 'Grass': 1.0, 'Snow': 1.0}
# The near detail normal (read pass): the uniform forest-ground gravel normal. The aerial dirt
# normal it replaces carries the same blotches as its colour map and, tiled at 1.5 m, drew a
# scale pattern in the lighting within 30 m of the camera.
DETAIL_TEXTURE = '/Game/Pallbearer/Terrain/Tex/T_PH_forest_ground_04_nor_gl'

# (name, default, group). Defaults are checked by the offline tests.
SCALARS = [
    ('SlopeLo', 0.16, 'Auto'), ('SlopeHi', 0.33, 'Auto'), ('GrassLo', 0.42, 'Auto'), ('GrassHi', 0.72, 'Auto'),
    ('SnowLo', 0.78, 'Auto'), ('SnowHi', 0.85, 'Auto'), ('AlpineLo', 0.62, 'Auto'), ('AlpineHi', 0.78, 'Auto'),
    ('AlpineRock', 0.9, 'Auto'), ('MacroTone', 0.12, 'Auto'), ('NormalStrength', 1.0, 'Auto'),
    ('NearStart', 2000.0, 'Near'), ('NearEnd', 3000.0, 'Near'), ('DetailStrength', 0.35, 'Near'),
    ('DetailTile', 230.0, 'Near'), ('MacroNearStrength', 0.07, 'Near'), ('MacroNearScale', 600.0, 'Near'),
    ('NoTile', 1.0, 'Layers'), ('DebugView', 0.0, 'Debug'),
    # LOOK2 (task-LOOK2-brief.md): colour variation in the write pass, the road read in the read pass
    # HueAmount 1.0 -> 1.8 (LOOK2 fix round 1, review 3): at 1.0 the base-colour hue spread was only
    # 5-7 deg, too little to survive the low warm sun; 1.8 extrapolates the ochre/rust/olive hues
    ('HueAmount', 1.8, 'Colour'), ('ScreeAmount', 0.35, 'Colour'), ('MottleTone', 0.12, 'Colour'),
    ('MottleHue', 1.0, 'Colour'), ('VergeDarken', 0.5, 'Road'),
    # RoadLift 1.3 -> 1.5 (LOOK2 fix round 1, review 1): at the 8-degree sun the flat road core takes
    # ~30 % less light per unit albedo than the rough, sun-facing verge, so the lit road/verge ratio
    # at 1050 m was 0.46-0.64 with an albedo ratio of 1.31
    ('RoadLift', 1.5, 'Road'), ('RoadWetRough', 0.8, 'Road'), ('PuddleAmount', 0.8, 'Road'),
    ('PuddleCut', 0.1, 'Road'),
    # LOOK2 fix round 1 (review 7): pull the core toward a light warm-grey stone, so the road is a
    # different surface from the ochre and rust ground, not only a brighter shade of it
    ('RoadDesat', 0.5, 'Road'),
]
COLORS = [('DryTint', (1.08, 1.02, 0.92), 'Auto'), ('GrassTint', (0.85, 0.95, 0.70), 'Auto'),
          ('RoadTone', (1.06, 1.0, 0.9), 'Road')]
AUTO_PINS = ['Eco', 'N', 'WorldXY', 'RockC', 'RockM', 'RockN', 'DirtC', 'DirtM', 'DirtN', 'GrassC', 'GrassM', 'GrassN',
             'SnowC', 'SnowM', 'SnowN', 'DryTint', 'GrassTint', 'SlopeLo', 'SlopeHi', 'GrassLo', 'GrassHi',
             'SnowLo', 'SnowHi', 'AlpineLo', 'AlpineHi', 'AlpineRock', 'MacroTone', 'NormalStrength', 'ZoneSoft',
             'Road', 'HueAmount', 'ScreeAmount', 'MottleTone', 'MottleHue', 'VergeDarken']
# AUTO pins fed straight from a same-named scalar or colour parameter
AUTO_PARAM_PINS = ['DryTint', 'GrassTint', 'SlopeLo', 'SlopeHi', 'GrassLo', 'GrassHi', 'SnowLo', 'SnowHi',
                   'AlpineLo', 'AlpineHi', 'AlpineRock', 'MacroTone', 'NormalStrength',
                   'HueAmount', 'ScreeAmount', 'MottleTone', 'MottleHue', 'VergeDarken']
READ_PINS = ['BaseColor', 'Rough', 'N', 'Detail', 'WorldXY', 'Depth', 'NearStart', 'NearEnd', 'DetailStrength',
             'MacroNearStrength', 'MacroNearScale', 'DebugView', 'MaskUV', 'Eco', 'Road',
             'RoadLift', 'RoadWetRough', 'PuddleAmount', 'PuddleCut', 'RoadDesat', 'RoadTone']

mel = unreal.MaterialEditingLibrary
eal = unreal.EditorAssetLibrary
QUIET = unreal.PropertyAccessChangeNotifyMode.NEVER
ST = unreal.MaterialSamplerType


def _norm_name(s):
    return ' '.join(str(s).split())


def _load(path):
    return eal.load_asset(path) if eal.does_asset_exist(path) else None


def assign():
    ls = None
    for a in unreal.get_editor_subsystem(unreal.EditorActorSubsystem).get_all_level_actors():
        if a.get_class().get_name() == 'Landscape':
            ls = a
    mi = _load(MI_PATH)
    if ls is None or mi is None:
        raise RuntimeError('assign: landscape=' + str(ls) + ' mi=' + str(mi))
    before = ls.get_editor_property('landscape_material')
    ls.set_editor_property('landscape_material', mi)   # notified: the landscape updates its components
    pkg = ls.get_package()
    ok = unreal.EditorLoadingAndSavingUtils.save_packages([pkg], False)
    print('AS before=' + str(before.get_path_name() if before else None))
    print('AS after=' + str(ls.get_editor_property('landscape_material').get_path_name()))
    print('AS saved=' + str(ok) + ' pkg=' + str(pkg.get_name()))


def sampler_for(tex):
    cs = tex.get_editor_property('compression_settings')
    srgb = tex.get_editor_property('srgb')
    vt = tex.get_editor_property('virtual_texture_streaming')
    TCS = unreal.TextureCompressionSettings
    if cs == TCS.TC_NORMALMAP:
        return ST.SAMPLERTYPE_VIRTUAL_NORMAL if vt else ST.SAMPLERTYPE_NORMAL
    if cs == TCS.TC_MASKS:
        return ST.SAMPLERTYPE_VIRTUAL_MASKS if vt else ST.SAMPLERTYPE_MASKS
    if cs in (TCS.TC_GRAYSCALE, TCS.TC_ALPHA):
        if vt:
            return ST.SAMPLERTYPE_VIRTUAL_GRAYSCALE if srgb else ST.SAMPLERTYPE_VIRTUAL_LINEAR_GRAYSCALE
        return ST.SAMPLERTYPE_GRAYSCALE if srgb else ST.SAMPLERTYPE_LINEAR_GRAYSCALE
    if vt:
        return ST.SAMPLERTYPE_VIRTUAL_COLOR if srgb else ST.SAMPLERTYPE_VIRTUAL_LINEAR_COLOR
    return ST.SAMPLERTYPE_COLOR if srgb else ST.SAMPLERTYPE_LINEAR_COLOR


def is_opengl_normal(tex):
    # Pallbearer ships *_nor_gl maps; flip them unless the import already did
    return '_gl' in tex.get_name().lower() and not tex.get_editor_property('flip_green_channel')


def build():
    if len(AUTO_HLSL) < 800 or 'GroundNormal' not in AUTO_HLSL:
        raise RuntimeError('AUTO_HLSL holds ' + str(len(AUTO_HLSL)) + ' chars: run prepare_ground_material.py')
    if len(READ_HLSL) < 800 or 'DebugEmissive' not in READ_HLSL:
        raise RuntimeError('READ_HLSL holds ' + str(len(READ_HLSL)) + ' chars: run prepare_ground_material.py')
    if len(NOTILE_HLSL) < 400 or 'offB' not in NOTILE_HLSL:
        raise RuntimeError('NOTILE_HLSL holds ' + str(len(NOTILE_HLSL)) + ' chars: run prepare_ground_material.py')
    if len(NOTILE_N_HLSL) < 200 or 'lerp(a, b, W)' not in NOTILE_N_HLSL:
        raise RuntimeError('NOTILE_N_HLSL holds ' + str(len(NOTILE_N_HLSL)) + ' chars: run prepare_ground_material.py')
    if MASK_ORIGIN_CM is None or MASK_EXTENT_CM is None or MASK_EXTENT_CM <= 0:
        raise RuntimeError('mask mapping missing: run prepare_ground_material.py')
    eco_tex = _load(ECO_TEXTURE)
    road_tex = _load(ROAD_TEXTURE)
    rvt = _load(RVT_PATH)
    if eco_tex is None or road_tex is None or rvt is None:
        raise RuntimeError('missing a mask or the RVT: ' + str([eco_tex, road_tex, rvt]))

    tools = unreal.AssetToolsHelpers.get_asset_tools()
    created = eal.does_asset_exist(ASSET_PATH) is False
    mat = tools.create_asset(ASSET_NAME, PACKAGE_DIR, unreal.Material, unreal.MaterialFactoryNew()) \
        if created else eal.load_asset(ASSET_PATH)
    if not isinstance(mat, unreal.Material):
        raise RuntimeError('expected a Material at ' + ASSET_PATH + ', found ' + str(mat))

    # ---- texture sources: the old instance, else this master's own params, else FALLBACK
    src = _load(SOURCE_MI)
    src_tex = {}
    src_vec = {}
    if src is not None:
        for nm in mel.get_texture_parameter_names(src):
            src_tex[_norm_name(nm)] = mel.get_material_instance_texture_parameter_value(src, nm)
        for nm in mel.get_vector_parameter_names(src):
            src_vec[_norm_name(nm)] = mel.get_material_instance_vector_parameter_value(src, nm)
    own_tex = {}
    own_vec = {}
    if not created:
        for nm in mel.get_texture_parameter_names(mat):
            own_tex[_norm_name(nm)] = mel.get_material_default_texture_parameter_value(mat, nm)
        for nm in mel.get_vector_parameter_names(mat):
            own_vec[_norm_name(nm)] = mel.get_material_default_vector_parameter_value(mat, nm)

    origin_of = {}

    def pick_tex(own_name, src_name, fallback):
        if src_name in src_tex and src_tex[src_name] is not None:
            origin_of[own_name] = 'instance'
            return src_tex[src_name]
        if own_name in own_tex and own_tex[own_name] is not None:
            origin_of[own_name] = 'master'
            return own_tex[own_name]
        origin_of[own_name] = 'fallback'
        return eal.load_asset(fallback)

    def pick_vec(own_name, src_name, fallback):
        layer = own_name[:-len(' Tint')] if own_name.endswith(' Tint') else None
        if layer in LAYER_TINT_OVERRIDE:
            v = LAYER_TINT_OVERRIDE[layer]
            return unreal.LinearColor(v[0], v[1], v[2], 1.0)
        if src_name in src_vec:
            return src_vec[src_name]
        if own_name in own_vec:
            return own_vec[own_name]
        return unreal.LinearColor(fallback[0], fallback[1], fallback[2], 1.0)

    mat.set_editor_property('tangent_space_normal', False, QUIET)
    removed = 0
    for old in mel.get_material_expressions(mat):
        mel.delete_material_expression(mat, old)
        removed += 1

    links = []

    def add(cls, x, y):
        return mel.create_material_expression(mat, cls, x, y)

    def link(src_node, src_out, dst, pin):
        links.append((src_node, src_out, dst, pin))

    def binop(cls, a, b, x, y):
        node = add(cls, x, y)
        link(a[0], a[1], node, 'A')
        link(b[0], b[1], node, 'B')
        return node

    def cmask(src_pair, rgba, x, y):
        node = add(unreal.MaterialExpressionComponentMask, x, y)
        for ch, on in zip('rgba', rgba):
            node.set_editor_property(ch, on, QUIET)
        link(src_pair[0], src_pair[1], node, '')
        return node

    def scalar(name, default, group, x, y, order):
        node = add(unreal.MaterialExpressionScalarParameter, x, y)
        node.set_editor_property('parameter_name', name, QUIET)
        node.set_editor_property('default_value', default, QUIET)
        node.set_editor_property('group', group, QUIET)
        node.set_editor_property('sort_priority', order, QUIET)
        return node

    def vector(name, rgb, group, x, y, order):
        node = add(unreal.MaterialExpressionVectorParameter, x, y)
        node.set_editor_property('parameter_name', name, QUIET)
        node.set_editor_property('default_value', rgb, QUIET)
        node.set_editor_property('group', group, QUIET)
        node.set_editor_property('sort_priority', order, QUIET)
        return node

    def tex_param(name, tex, uv, group, x, y, order):
        node = add(unreal.MaterialExpressionTextureSampleParameter2D, x, y)
        node.set_editor_property('parameter_name', name, QUIET)
        node.set_editor_property('texture', tex, QUIET)
        node.set_editor_property('sampler_type', sampler_for(tex), QUIET)
        node.set_editor_property('sampler_source', unreal.SamplerSourceMode.SSM_WRAP_WORLD_GROUP_SETTINGS, QUIET)
        node.set_editor_property('group', group, QUIET)
        node.set_editor_property('sort_priority', order, QUIET)
        link(uv, '', node, 'UVs')
        return node

    def custom(desc, code, out_type, pins, extra, x, y):
        node = add(unreal.MaterialExpressionCustom, x, y)
        node.set_editor_property('description', desc, QUIET)
        node.set_editor_property('output_type', out_type, QUIET)
        node.set_editor_property('code', code, QUIET)
        ins = []
        for pin_name in pins:
            pin = unreal.CustomInput()
            pin.set_editor_property('input_name', pin_name)
            ins.append(pin)
        node.set_editor_property('inputs', ins, QUIET)
        outs = []
        for out_name in extra:
            out_type3 = unreal.CustomMaterialOutputType.CMOT_FLOAT3
            if out_name.endswith(':1'):
                out_name = out_name[:-2]
                out_type3 = unreal.CustomMaterialOutputType.CMOT_FLOAT1
            elif out_name.endswith(':4'):
                out_name = out_name[:-2]
                out_type3 = unreal.CustomMaterialOutputType.CMOT_FLOAT4
            out = unreal.CustomOutput()
            out.set_editor_property('output_name', out_name)
            out.set_editor_property('output_type', out_type3)
            outs.append(out)
        node.set_editor_property('additional_outputs', outs)   # notified: rebuilds the output pins
        return node

    # ---- shared coordinates -------------------------------------------------------
    wpos = add(unreal.MaterialExpressionWorldPosition, -4200, 0)
    origin = add(unreal.MaterialExpressionConstant3Vector, -4200, 150)
    origin.set_editor_property('constant', unreal.LinearColor(MASK_ORIGIN_CM[0], MASK_ORIGIN_CM[1], 0.0, 0.0), QUIET)
    rel = binop(unreal.MaterialExpressionSubtract, (wpos, ''), (origin, ''), -4000, 50)
    rel_xy = cmask((rel, ''), (True, True, False, False), -3850, 50)
    extent = add(unreal.MaterialExpressionConstant, -3850, 200)
    extent.set_editor_property('r', MASK_EXTENT_CM, QUIET)
    mask_uv = binop(unreal.MaterialExpressionDivide, (rel_xy, ''), (extent, ''), -3650, 100)

    eco = add(unreal.MaterialExpressionTextureSample, -3400, -300)
    eco.set_editor_property('texture', eco_tex, QUIET)
    eco.set_editor_property('sampler_type', ST.SAMPLERTYPE_LINEAR_COLOR, QUIET)
    link(mask_uv, '', eco, 'UVs')
    road = add(unreal.MaterialExpressionTextureSample, -3400, 2200)
    road.set_editor_property('texture', road_tex, QUIET)
    road.set_editor_property('sampler_type', ST.SAMPLERTYPE_LINEAR_COLOR, QUIET)
    link(mask_uv, '', road, 'UVs')

    params = {}
    order = 0
    for name, default, group in SCALARS:
        params[name] = scalar(name, default, group, -3000, 1200 + 70 * order, order)
        order += 1
    for name, rgb, group in COLORS:
        params[name] = vector(name, unreal.LinearColor(rgb[0], rgb[1], rgb[2], 1.0), group, -3000, 1200 + 70 * order, order)
        order += 1

    # ---- WRITE pass: layers -> GroundAuto -> RVT Output -----------------------------
    auto = custom('GroundAuto', AUTO_HLSL, unreal.CustomMaterialOutputType.CMOT_FLOAT4,
                  AUTO_PINS, ['GroundNormal'], -1200, -900)
    link(eco, 'RGBA', auto, 'Eco')
    vnormal = add(unreal.MaterialExpressionVertexNormalWS, -1600, -1300)
    link(vnormal, '', auto, 'N')
    link(rel_xy, '', auto, 'WorldXY')
    flip = add(unreal.MaterialExpressionConstant3Vector, -2400, -1400)
    flip.set_editor_property('constant', unreal.LinearColor(1.0, -1.0, 1.0, 0.0), QUIET)
    layer_report = []
    row = 0
    for layer, prefix, tile_cm, fb_c, fb_m, fb_n, fb_tint in LAYERS:
        y = -2400 + 900 * row
        tile = scalar(layer + ' Tile', tile_cm, 'Layers', -4400, y, 100 + row)
        uv = binop(unreal.MaterialExpressionDivide, (rel_xy, ''), (tile, ''), -4200, y)
        tc = pick_tex(layer + ' Color', _norm_name(prefix + 'Color'), fb_c)
        tm = pick_tex(layer + ' ORM', _norm_name(prefix + 'ORM'), fb_m)
        tn = pick_tex(layer + ' Normal', _norm_name(prefix + 'Normal'), fb_n)
        tint = vector(layer + ' Tint', pick_vec(layer + ' Tint', _norm_name(prefix + 'ColorTint'), fb_tint),
                      'Layers', -2600, y, 113 + 4 * row)
        # anti-tiling: GroundNoTile gives two offset, turned copies of the tile UV, their blend
        # weight W, each copy's turned derivatives (DA, DB) and its turn (RA, for the normals)
        ddx = add(unreal.MaterialExpressionDDX, -4200, y + 160)
        link(uv, '', ddx, '')
        ddy = add(unreal.MaterialExpressionDDY, -4200, y + 220)
        link(uv, '', ddy, '')
        nt = custom('GroundNoTile ' + layer, NOTILE_HLSL, unreal.CustomMaterialOutputType.CMOT_FLOAT4,
                    ['UV', 'DX', 'DY', 'Amount', 'Seed', 'Turn'], ['W:1', 'DA:4', 'DB:4', 'RA:4'], -4000, y)
        link(uv, '', nt, 'UV')
        link(ddx, '', nt, 'DX')
        link(ddy, '', nt, 'DY')
        link(params['NoTile'], '', nt, 'Amount')
        seed = add(unreal.MaterialExpressionConstant, -4200, y + 100)
        seed.set_editor_property('r', float(row), QUIET)
        link(seed, '', nt, 'Seed')
        link(scalar(layer + ' Turn', TURN[layer], 'Layers', -4200, y + 280, 125 + row), '', nt, 'Turn')
        uva = cmask((nt, ''), (True, True, False, False), -3800, y)
        uvb = cmask((nt, ''), (False, False, True, True), -3800, y + 60)
        grads = []
        for k, out_name in enumerate(('DA', 'DB')):
            grads.append((cmask((nt, out_name), (True, True, False, False), -3800, y + 120 + 120 * k),
                          cmask((nt, out_name), (False, False, True, True), -3800, y + 180 + 120 * k)))

        def pair(name, tex, order, dy):
            out = []
            for k, uvx in enumerate((uva, uvb)):
                s = tex_param(name, tex, uvx, 'Layers', -3500, y + dy + 70 * k, order)
                s.set_editor_property('mip_value_mode', unreal.TextureMipValueMode.TMVM_DERIVATIVE, QUIET)
                link(grads[k][0], '', s, 'DDX(UVs)')
                link(grads[k][1], '', s, 'DDY(UVs)')
                out.append(s)
            return out

        def mix2(a, b, x, yy):
            mix = add(unreal.MaterialExpressionLinearInterpolate, x, yy)
            link(a[0], a[1], mix, 'A')
            link(b[0], b[1], mix, 'B')
            link(nt, 'W', mix, 'Alpha')
            return mix

        cs = pair(layer + ' Color', tc, 110 + 4 * row, 0)
        c_mix = mix2((cs[0], 'RGB'), (cs[1], 'RGB'), -3200, y)
        ms = pair(layer + ' ORM', tm, 111 + 4 * row, 300)
        m_mix = mix2((ms[0], 'RGB'), (ms[1], 'RGB'), -3200, y + 300)
        ns = pair(layer + ' Normal', tn, 112 + 4 * row, 450)
        gl = is_opengl_normal(tn)
        nsrc = []
        for k, s in enumerate(ns):
            if gl:   # to the DirectX convention in texture space, before the copy is turned back
                nsrc.append((binop(unreal.MaterialExpressionMultiply, (s, 'RGB'), (flip, ''), -3350, y + 450 + 70 * k), ''))
            else:
                nsrc.append((s, 'RGB'))
        n_mix = custom('GroundNoTileNormal ' + layer, NOTILE_N_HLSL, unreal.CustomMaterialOutputType.CMOT_FLOAT3,
                       ['NA', 'NB', 'W', 'RA'], [], -3200, y + 450)
        link(nsrc[0][0], nsrc[0][1], n_mix, 'NA')
        link(nsrc[1][0], nsrc[1][1], n_mix, 'NB')
        link(nt, 'W', n_mix, 'W')
        link(nt, 'RA', n_mix, 'RA')
        # flatten: colour + Flatten * (average - low); average = the smallest mip, low = mip
        # FLATTEN_MIP of the same two copies
        lows = []
        for k, uvx in enumerate((uva, uvb)):
            lo = tex_param(layer + ' Color', tc, uvx, 'Layers', -3500, y + 150 + 70 * k, 110 + 4 * row)
            lo.set_editor_property('mip_value_mode', unreal.TextureMipValueMode.TMVM_MIP_LEVEL, QUIET)
            lo.set_editor_property('const_mip_value', FLATTEN_MIP, QUIET)
            lows.append(lo)
        low = add(unreal.MaterialExpressionLinearInterpolate, -3200, y + 150)
        link(lows[0], 'RGB', low, 'A')
        link(lows[1], 'RGB', low, 'B')
        link(nt, 'W', low, 'Alpha')
        avg = tex_param(layer + ' Color', tc, uv, 'Layers', -3500, y + 700, 110 + 4 * row)
        avg.set_editor_property('mip_value_mode', unreal.TextureMipValueMode.TMVM_MIP_LEVEL, QUIET)
        avg.set_editor_property('const_mip_value', 12, QUIET)
        flat_k = scalar(layer + ' Flatten', FLATTEN[layer], 'Layers', -3200, y + 700, 120 + row)
        dev = binop(unreal.MaterialExpressionSubtract, (avg, 'RGB'), (low, ''), -3000, y + 150)
        dev_k = binop(unreal.MaterialExpressionMultiply, (dev, ''), (flat_k, ''), -2850, y + 150)
        flat = binop(unreal.MaterialExpressionAdd, (c_mix, ''), (dev_k, ''), -2700, y)
        col = binop(unreal.MaterialExpressionMultiply, (flat, ''), (tint, 'RGB'), -2300, y)
        link(col, '', auto, layer + 'C')
        link(m_mix, '', auto, layer + 'M')
        link(n_mix, '', auto, layer + 'N')
        layer_report.append(layer + ':' + tc.get_name() + '/' + tm.get_name() + '/' + tn.get_name() +
                            ('(gl-flipped)' if gl else '') + ' from ' + origin_of[layer + ' Color'])
        row += 1
    for name in AUTO_PARAM_PINS:
        link(params[name], 'RGB' if name in ('DryTint', 'GrassTint') else '', auto, name)
    link(road, 'RGBA', auto, 'Road')   # LOOK2 roadside term (the grass output reads the same sample)
    # ZoneSoft: the Ecology zone at mip 2 (about 8 m), so snow and alpine rock do not trace the
    # 2 m stair steps of the zone channel's hard 35-degree snow cut
    eco_soft = add(unreal.MaterialExpressionTextureSample, -3400, -150)
    eco_soft.set_editor_property('texture', eco_tex, QUIET)
    eco_soft.set_editor_property('sampler_type', ST.SAMPLERTYPE_LINEAR_COLOR, QUIET)
    eco_soft.set_editor_property('mip_value_mode', unreal.TextureMipValueMode.TMVM_MIP_LEVEL, QUIET)
    eco_soft.set_editor_property('const_mip_value', 2, QUIET)
    link(mask_uv, '', eco_soft, 'UVs')
    link(eco_soft, 'B', auto, 'ZoneSoft')

    rvt_out = add(unreal.MaterialExpressionRuntimeVirtualTextureOutput, -600, -900)
    link(cmask((auto, ''), (True, True, True, False), -850, -950), '', rvt_out, 'BaseColor')
    link(cmask((auto, ''), (False, False, False, True), -850, -850), '', rvt_out, 'Roughness')
    link(auto, 'GroundNormal', rvt_out, 'Normal')

    # ---- READ pass: RVT sample + near detail + DebugView -> main outputs -------------
    rvs = add(unreal.MaterialExpressionRuntimeVirtualTextureSample, -1600, 300)
    rvs.set_editor_property('virtual_texture', rvt)
    rvs.set_editor_property('material_type', rvt.get_editor_property('material_type'))
    rvs.set_editor_property('single_physical_space', rvt.get_editor_property('single_physical_space'))
    detail_tex = eal.load_asset(DETAIL_TEXTURE)
    origin_of['Detail Normal'] = 'DETAIL_TEXTURE'
    duv = binop(unreal.MaterialExpressionDivide, (rel_xy, ''), (params['DetailTile'], ''), -1900, 700)
    dn = tex_param('Detail Normal', detail_tex, duv, 'Near', -1650, 700, 200)
    detail_out = (dn, 'RGB')
    if is_opengl_normal(detail_tex):
        detail_out = (binop(unreal.MaterialExpressionMultiply, (dn, 'RGB'), (flip, ''), -1400, 700), '')
    depth = add(unreal.MaterialExpressionPixelDepth, -1400, 850)
    eco_obj = add(unreal.MaterialExpressionTextureObject, -1400, 950)
    eco_obj.set_editor_property('texture', eco_tex, QUIET)
    eco_obj.set_editor_property('sampler_type', ST.SAMPLERTYPE_LINEAR_COLOR, QUIET)
    road_obj = add(unreal.MaterialExpressionTextureObject, -1400, 1050)
    road_obj.set_editor_property('texture', road_tex, QUIET)
    road_obj.set_editor_property('sampler_type', ST.SAMPLERTYPE_LINEAR_COLOR, QUIET)

    read = custom('GroundRead', READ_HLSL, unreal.CustomMaterialOutputType.CMOT_FLOAT4,
                  READ_PINS, ['GroundN', 'DebugEmissive'], -900, 400)
    link(rvs, 'BaseColor', read, 'BaseColor')
    link(rvs, 'Roughness', read, 'Rough')
    link(rvs, 'Normal', read, 'N')
    link(detail_out[0], detail_out[1], read, 'Detail')
    link(rel_xy, '', read, 'WorldXY')
    link(depth, '', read, 'Depth')
    for name in ('NearStart', 'NearEnd', 'DetailStrength', 'MacroNearStrength', 'MacroNearScale', 'DebugView',
                 'RoadLift', 'RoadWetRough', 'PuddleAmount', 'PuddleCut', 'RoadDesat'):
        link(params[name], '', read, name)
    link(params['RoadTone'], 'RGB', read, 'RoadTone')
    link(mask_uv, '', read, 'MaskUV')
    link(eco_obj, '', read, 'Eco')
    link(road_obj, '', read, 'Road')
    read_rgb = cmask((read, ''), (True, True, True, False), -500, 350)
    read_a = cmask((read, ''), (False, False, False, True), -500, 450)

    # ---- GRASS output: density trees -> Landscape Grass Output -----------------------
    leaves = {'moisture': (eco, 'R'), 'exposure': (eco, 'G'),
              'core': (road, 'R'), 'verge': (road, 'G'), 'neglect': (road, 'B')}
    consts = {}
    counter = [0]
    classes = {'add': unreal.MaterialExpressionAdd, 'mul': unreal.MaterialExpressionMultiply}

    def emit(tree, depth_x):
        op = tree[0]
        if op == 'in':
            return leaves[tree[1]]
        if op == 'const':
            if tree[1] not in consts:
                c = add(unreal.MaterialExpressionConstant, -3000, 2800 + 60 * len(consts))
                c.set_editor_property('r', tree[1], QUIET)
                consts[tree[1]] = (c, '')
            return consts[tree[1]]
        counter[0] += 1
        y = 2200 + 55 * counter[0]
        x = -600 - 180 * depth_x
        if op in ('om', 'sat'):
            node = add(unreal.MaterialExpressionOneMinus if op == 'om' else unreal.MaterialExpressionSaturate, x, y)
            a = emit(tree[1], depth_x + 1)
            link(a[0], a[1], node, '')
            return (node, '')
        a = emit(tree[1], depth_x + 1)
        b = emit(tree[2], depth_x + 1)
        return (binop(classes[op], a, b, x, y), '')

    grass = add(unreal.MaterialExpressionLandscapeGrassOutput, -200, 2400)
    gins = []
    missing_lgt = []
    for pin_name, lgt_path, tree in GRASS_OUTPUTS:
        gi = unreal.GrassInput()
        gi.set_editor_property('name', pin_name)
        lgt = _load(lgt_path)
        if lgt is None:
            missing_lgt.append(lgt_path)
        else:
            gi.set_editor_property('grass_type', lgt)
        gins.append(gi)
    grass.set_editor_property('grass_types', gins)   # notified: rebuilds the input pins
    for pin_name, lgt_path, tree in GRASS_OUTPUTS:
        out = emit(tree, 0)
        link(out[0], out[1], grass, pin_name)

    # ---- wires, main outputs --------------------------------------------------------
    failed = []
    for s, so, d, dp in links:
        if not mel.connect_material_expressions(s, so, d, dp):
            failed.append(d.get_class().get_name()[18:] + '.' + dp + '<-' + s.get_class().get_name()[18:] + '.' + so)
    MP = unreal.MaterialProperty
    props_ok = [mel.connect_material_property(read_rgb, '', MP.MP_BASE_COLOR),
                mel.connect_material_property(read_a, '', MP.MP_ROUGHNESS),
                mel.connect_material_property(read, 'GroundN', MP.MP_NORMAL),
                mel.connect_material_property(read, 'DebugEmissive', MP.MP_EMISSIVE_COLOR)]

    mel.recompile_material(mat)
    saved = eal.save_loaded_asset(mat, False)
    mi_created = eal.does_asset_exist(MI_PATH) is False
    mi = tools.create_asset(MI_NAME, PACKAGE_DIR, unreal.MaterialInstanceConstant,
                            unreal.MaterialInstanceConstantFactoryNew()) if mi_created else eal.load_asset(MI_PATH)
    mel.set_material_instance_parent(mi, mat)
    mi_saved = eal.save_loaded_asset(mi, False)

    print('GB asset=' + ASSET_PATH + ' created=' + str(created) + ' removed=' + str(removed) +
          ' nodes=' + str(mel.get_num_material_expressions(mat)) + ' tangent_space_normal=' +
          str(mat.get_editor_property('tangent_space_normal')))
    print('GB mapping origin=' + str(MASK_ORIGIN_CM) + ' extent=' + str(MASK_EXTENT_CM))
    print('GB layers ' + ' | '.join(layer_report))
    print('GB detail=' + detail_tex.get_name() + ' from ' + origin_of['Detail Normal'])
    print('GB rvt=' + str(rvs.get_editor_property('virtual_texture').get_name()) + ' type=' +
          str(rvs.get_editor_property('material_type')))
    print('GB grass=' + str([str(g.get_editor_property('name')) for g in grass.get_editor_property('grass_types')]) +
          ' missing_lgt=' + str(missing_lgt))
    print('GB failed_links=' + str(failed) + ' props_ok=' + str(props_ok))
    print('GB saved=' + str(saved) + ' mi_created=' + str(mi_created) + ' mi_parent=' +
          str(mi.get_editor_property('parent').get_path_name()) + ' mi_saved=' + str(mi_saved))


if MODE == 'assign':
    assign()
else:
    build()
