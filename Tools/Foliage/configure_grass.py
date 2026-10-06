# Configure the three Landscape Grass Types fed by M_Saskarta_Ground's grass output
# (world sprint, Task V3).
#
#   node Tools/Foliage/run_foliage.mjs py Tools/Foliage/configure_grass.py            # apply + readback
#   node Tools/Foliage/run_foliage.mjs py Tools/Foliage/configure_grass.py "MODE='read'"
#   node Tools/Foliage/run_foliage.mjs py Tools/Foliage/configure_grass.py "MODE='save'"
#
# Hold the editor gate (Tools/GameFlow/editor_gate.py) while it runs.
# 'apply' creates LGT_Saskarta_Reeds when it is missing, creates or updates the LOOK2
# colour instances in MATERIALS, and rewrites every type's grass_varieties from TYPES; it
# does not save. 'save' saves exactly the three LGT assets and the MATERIALS instances. After creating the reeds type, re-run
# `python Tools/Road/prepare_ground_material.py --send` so the ground material's
# Reeds grass-output pin gets it (Task V2 built that pin empty).
#
# Brief numbers (task-V3-brief.md): cull near 3000/5000, dry 6000/10000, reeds
# 5000/8000 cm; dynamic shadow on the reeds only, contact shadow off everywhere;
# 12, 2 and 1.5 instances per m2; random rotation, uniform scale 0.8-1.3, aligned
# to the surface. Each type's per-m2 total is split over its meshes by 'shares'.
#
# Density units. The 5.8 tooltip says GrassDensity is "instances per 10 square
# meters", but measured in this editor it behaves as instances per 10 m x 10 m
# (100 m2). V3 counted instances in top-down captures of the 200 m and 4,350 m
# stretches and compared them with the counts the mask weights predict: reeds 53
# against 50 (per 100 m2) or 501 (per 10 m2); near grass 854 against 1,242 or
# 12,417. So UNITS_PER_M2 is 100 (task-V3-report.md, "Density units").
# grass.DensityScale scales every variety (5.8 has no per-variety opt-out). The
# per-quality twins (GrassDensityQuality, Start/EndCullDistanceQuality) are set to
# the same values, so the numbers hold whichever path the project uses.
# Meshes (Ruling R25: static meshes only, never the skinned Megaplant reeds):
#   near  - the two AzielArts blade meshes the type already used (11 and 104
#           triangles). Its two clumps are dropped: SM_GrassClump_02 is 2.3 m across
#           (a shrub at the brief's uniform 0.8-1.3 scale) and SM_GrassClump_01 is
#           1,664 triangles and renders as near-black blotches at 12 per m2 (V3_2300);
#   dry   - pale MedievalVillage tufts (0.4-0.55 m, 10-24 triangles). The six
#           Pallbearer tufts the type used before (also in the old
#           PCG_Saskarta_GrassGPU graph, at weight 0) do not render as instances:
#           their material's parent is the glTF importer's M_Default, which is not
#           usable with instanced static meshes;
#   reeds - the AshesOfBazaar Nanite static tall grasses, 0.7-0.95 m high and pale.
#           The GrassGPU tall grasses are 0.3 m, too short to read as reeds.
# None of these meshes' materials reference MPC_Saskarta_Player, so the trample and
# wind WPO of the V4 foliage masters does not reach them (see task-V3-report.md).
# Offline checks: python -m pytest Tools/Foliage/tests -q
import unreal

MODE = 'apply'
# ONLY: None for every type, or one type's path (a slow editor can split 'apply' per type)
ONLY = None

UNITS_PER_M2 = 100.0
SCALE_RANGE = (0.8, 1.3)
RANDOM_ROTATION = True
ALIGN_TO_SURFACE = True
# PERF2 (user: keep grass shadows, cheaply, near the camera): screen-space contact shadows on every type (the
# sun's ContactShadowLength is 30 cm in world units). 5.8 has no per-instance VSM shadow distance, so the dense
# near/dry grass stays out of the VSM; the sparse Nanite reeds keep VSM with RIGID invalidation (their wind WPO
# no longer re-renders cached shadow pages every frame).
CAST_CONTACT_SHADOW = True
RIGID_SHADOW_TYPES = ('/Game/SaskartaGaea/Foliage/LGT_Saskarta_Reeds',)
WPO_DISABLE_CM = 6000
# Grass-output weights below this spawn nothing (FGrassVariety.AllowedDensityRange).
# LOOK2: the crown term is core * saturate((neglect - 0.8) / 0.2) * 0.15, so crown tufts
# spawn only where neglect >= 0.84 (weight 0.03), sparsely. The off-core factor is
# saturate(1 - core / 0.3) for every type (Tools/Road/build_ground_material.py): nothing
# grows from core 0.3 inward, and the verge regrows over the next 1-2 m.
# Off the road it trims only the sparsest fringe (below 0.36 near-grass tufts per m2).
MIN_WEIGHT = 0.03

# LOOK2 (user: "more color variation"; the brief: fix the pink grass). Each grass mesh
# draws through a project-owned child instance of its own material, set as the variety's
# override material, so no third-party asset is edited. Colours are linear:
#   near grass (moist ground)  AzielArts M_GrassFoliage already mixes three per-instance
#       colours ('Local Random Color Variation'); its third was magenta (0.53, 0.16, 0.22).
#       Now rust, straw and a dark olive-green, over an olive base, mixed harder.
#   dry tufts (exposed ground) MedievalVillage MM_FoliageMaster has one Tint per instance
#       material, so each of the four meshes gets its own: straw, ochre, olive, rust.
#   reeds (wettest hollows)     AshesOfBazaar MI_TallGrass tinted them pink
#       (00_BaseColorTint 1.0, 0.55, 0.59): the pink tufts in the RoadVis captures. Now a
#       pale olive-straw; its own colour randomisation stays on.
# Which type grows where follows the Ecology moisture and exposure (the ground material's
# grass output), so the palette follows them too: green in hollows, straw on exposed ground.
MI_DIR = '/Game/SaskartaGaea/Foliage/Materials'
MATERIALS = {
    # name: (parent material instance, vector params, scalar params)
    # Parents (LANE4 ground blend): project copies of the pack MIs (<name>_GB, Tools/Foliage/build_ground_blend.py)
    # whose masters sample RVT_Saskarta_Terrain and lerp the grass toward the ground colour (80 % root, 30 % tip).
    # LANE4 (user 2026-09-28: "more uniform and desaturated", "especially the grass", "some of the white
    # and green grass vary too much", "we need more dead grass"): every type in one dry straw-olive range.
    # The near grass is the bulk of the instances, so its base and two of its three per-instance colours
    # are dead straw/brown (about two thirds dead), the third a dull living olive; the mix is halved
    # (0.85 -> 0.45). The pale tufts and reeds are darkened, the green ones desaturated most.
    # Before (LOOK2): Near Blend (0.56,0.66,0.36) var (0.47,0.24,0.10) (0.78,0.74,0.40) (0.24,0.34,0.12) mix 0.85;
    # Straw (1.0,0.92,0.66), Ochre (1.0,0.80,0.52), Olive (0.78,0.86,0.52), Rust (1.0,0.70,0.48), Reeds (0.95,0.93,0.72).
    'MI_Saskarta_Grass_Near02': ('/Game/SaskartaGaea/Foliage/Materials/Masters/MI_Grass_02_GB',
                                 {'Blend_Color': (0.50, 0.44, 0.26), 'Color Var Color 01': (0.42, 0.31, 0.17),
                                  'Color Var Color 02': (0.58, 0.51, 0.31), 'Color Var Color 03': (0.38, 0.39, 0.23)},
                                 {'Local Random Color Variation': 0.45}),
    'MI_Saskarta_Grass_Near03': ('/Game/SaskartaGaea/Foliage/Materials/Masters/MI_Grass_03_GB',
                                 {'Blend_Color': (0.52, 0.45, 0.27), 'Color Var Color 01': (0.42, 0.31, 0.17),
                                  'Color Var Color 02': (0.58, 0.51, 0.31), 'Color Var Color 03': (0.38, 0.39, 0.23)},
                                 {'Local Random Color Variation': 0.45}),
    'MI_Saskarta_DryTuft_Straw': ('/Game/SaskartaGaea/Foliage/Materials/Masters/MI_Grass_V1_GB',
                                  {'Tint': (0.74, 0.66, 0.46)}, {}),
    'MI_Saskarta_DryTuft_Ochre': ('/Game/SaskartaGaea/Foliage/Materials/Masters/MI_Grass_V2_GB',
                                  {'Tint': (0.76, 0.63, 0.42)}, {}),
    'MI_Saskarta_DryTuft_Olive': ('/Game/SaskartaGaea/Foliage/Materials/Masters/MI_Grass_V2_GB',
                                  {'Tint': (0.68, 0.64, 0.44)}, {}),
    'MI_Saskarta_DryTuft_Rust': ('/Game/SaskartaGaea/Foliage/Materials/Masters/MI_Grass_V5_GB',
                                 {'Tint': (0.76, 0.60, 0.41)}, {}),
    'MI_Saskarta_Reeds': ('/Game/SaskartaGaea/Foliage/Materials/Masters/MI_TallGrass_GB',
                          # LANE4: the pack's per-instance colour randomisation (hue) made the reeds read lilac;
                          # off, and the white subsurface tint warmed to straw
                          {'00_BaseColorTint': (0.68, 0.62, 0.44), '00_ColorRandomizationControls': (0.0, 0.0, 0.0),
                           '00_SubsurfaceColorTint': (0.62, 0.52, 0.32)}, {}),
}

TYPES = [
    {'path': '/Game/SaskartaGaea/Foliage/LGT_Saskarta_NearGrass', 'per_m2': 12.0,
     'start_cull_cm': 4500, 'end_cull_cm': 7000, 'cast_dynamic_shadow': False,
     'meshes': ['/Game/AzielArts_Material/LandscapeGrassFoliage/Assets/Meshes/SM_Grass_blades_tall',
                '/Game/AzielArts_Material/LandscapeGrassFoliage/Assets/Meshes/SM_Grass_blades_med02'],
     'materials': ['MI_Saskarta_Grass_Near02', 'MI_Saskarta_Grass_Near03'],
     'shares': [1, 1]},
    {'path': '/Game/SaskartaGaea/Foliage/LGT_Saskarta_DryGrass', 'per_m2': 2.0,
     'start_cull_cm': 14000, 'end_cull_cm': 20000, 'cast_dynamic_shadow': False,
     'meshes': ['/Game/MedievalVillage/Demo/StaticMesh/Grass/SM_Grass_V1_02',
                '/Game/MedievalVillage/Demo/StaticMesh/Grass/SM_Grass_V2_01',
                '/Game/MedievalVillage/Demo/StaticMesh/Grass/SM_Grass_V2_03',
                '/Game/MedievalVillage/Demo/StaticMesh/Grass/SM_Grass_V5_05'],
     'materials': ['MI_Saskarta_DryTuft_Straw', 'MI_Saskarta_DryTuft_Ochre', 'MI_Saskarta_DryTuft_Olive',
                   'MI_Saskarta_DryTuft_Rust'],
     'shares': [1, 1, 1, 1]},
    {'path': '/Game/SaskartaGaea/Foliage/LGT_Saskarta_Reeds', 'per_m2': 1.5,
     'start_cull_cm': 10000, 'end_cull_cm': 15000, 'cast_dynamic_shadow': True,
     'meshes': ['/Game/AshesOfBazaar/Meshes/SM_SV_TallGrass01_LOD0',
                '/Game/AshesOfBazaar/Meshes/SM_SV_TallGrass02_LOD0',
                '/Game/AshesOfBazaar/Meshes/SM_SV_TallGrass03_LOD0',
                '/Game/AshesOfBazaar/Meshes/SM_SV_TallGrass04_LOD0'],
     'materials': ['MI_Saskarta_Reeds', 'MI_Saskarta_Reeds', 'MI_Saskarta_Reeds', 'MI_Saskarta_Reeds'],
     'shares': [1, 1, 1, 1]},
]

eal = unreal.EditorAssetLibrary
mel = unreal.MaterialEditingLibrary


def ensure_mi(name):
    parent_path, vecs, scals = MATERIALS[name]
    path = MI_DIR + '/' + name
    if eal.does_asset_exist(path):
        mi = eal.load_asset(path)
    else:
        tools = unreal.AssetToolsHelpers.get_asset_tools()
        mi = tools.create_asset(name, MI_DIR, unreal.MaterialInstanceConstant, unreal.MaterialInstanceConstantFactoryNew())
    mel.set_material_instance_parent(mi, eal.load_asset(parent_path))
    for k, v in vecs.items():
        mel.set_material_instance_vector_parameter_value(mi, k, unreal.LinearColor(v[0], v[1], v[2], 1.0))
    for k, v in scals.items():
        mel.set_material_instance_scalar_parameter_value(mi, k, v)
    mel.update_material_instance(mi)
    return mi


def ensure(path):
    if eal.does_asset_exist(path):
        return eal.load_asset(path), False
    folder = path.rsplit('/', 1)[0]
    name = path.rsplit('/', 1)[1]
    tools = unreal.AssetToolsHelpers.get_asset_tools()
    return tools.create_asset(name, folder, unreal.LandscapeGrassType, unreal.LandscapeGrassTypeFactory()), True


def variety(spec, mesh, share, mi):
    v = unreal.GrassVariety()
    v.set_editor_property('grass_mesh', mesh)
    v.set_editor_property('override_materials', [mi])
    d = unreal.PerPlatformFloat()
    d.set_editor_property('default', spec['per_m2'] * UNITS_PER_M2 * share / sum(spec['shares']))
    v.set_editor_property('grass_density', d)
    dq = unreal.PerQualityLevelFloat()
    dq.set_editor_property('default', d.get_editor_property('default'))
    v.set_editor_property('grass_density_quality', dq)
    s = unreal.PerPlatformInt()
    s.set_editor_property('default', spec['start_cull_cm'])
    v.set_editor_property('start_cull_distance', s)
    sq = unreal.PerQualityLevelInt()
    sq.set_editor_property('default', spec['start_cull_cm'])
    v.set_editor_property('start_cull_distance_quality', sq)
    e = unreal.PerPlatformInt()
    e.set_editor_property('default', spec['end_cull_cm'])
    v.set_editor_property('end_cull_distance', e)
    eq = unreal.PerQualityLevelInt()
    eq.set_editor_property('default', spec['end_cull_cm'])
    v.set_editor_property('end_cull_distance_quality', eq)
    v.set_editor_property('scaling', unreal.GrassScaling.UNIFORM)
    v.set_editor_property('scale_x', unreal.FloatInterval(SCALE_RANGE[0], SCALE_RANGE[1]))
    v.set_editor_property('allowed_density_range', unreal.FloatInterval(MIN_WEIGHT, 1.0))
    v.set_editor_property('random_rotation', RANDOM_ROTATION)
    v.set_editor_property('align_to_surface', ALIGN_TO_SURFACE)
    v.set_editor_property('cast_dynamic_shadow', spec['cast_dynamic_shadow'])
    v.set_editor_property('cast_contact_shadow', CAST_CONTACT_SHADOW)
    v.set_editor_property('instance_world_position_offset_disable_distance', WPO_DISABLE_CM)
    if spec['path'] in RIGID_SHADOW_TYPES:
        v.set_editor_property('shadow_cache_invalidation_behavior', unreal.ShadowCacheInvalidationBehavior.RIGID)
    return v


def readback(lgt):
    out = []
    for v in lgt.get_editor_property('grass_varieties'):
        m = v.get_editor_property('grass_mesh')
        sx = v.get_editor_property('scale_x')
        ad = v.get_editor_property('allowed_density_range')
        out.append((m.get_name() if m else None,
                    round(v.get_editor_property('grass_density').get_editor_property('default'), 3),
                    v.get_editor_property('start_cull_distance').get_editor_property('default'),
                    v.get_editor_property('end_cull_distance').get_editor_property('default'),
                    'dyn' + str(v.get_editor_property('cast_dynamic_shadow')),
                    'contact' + str(v.get_editor_property('cast_contact_shadow')),
                    str(v.get_editor_property('scaling')).split('.')[-1].split(':')[0],
                    (round(sx.min, 2), round(sx.max, 2)),
                    'rot' + str(v.get_editor_property('random_rotation')),
                    'align' + str(v.get_editor_property('align_to_surface')),
                    'q' + str((round(v.get_editor_property('grass_density_quality').get_editor_property('default'), 3),
                               v.get_editor_property('start_cull_distance_quality').get_editor_property('default'),
                               v.get_editor_property('end_cull_distance_quality').get_editor_property('default'))),
                    'range' + str((round(ad.min, 3), round(ad.max, 3))),
                    'wpo' + str(v.get_editor_property('instance_world_position_offset_disable_distance')),
                    'mat' + str([m.get_name() for m in v.get_editor_property('override_materials') if m])))
    return out


if MODE == 'save':
    for name in MATERIALS:
        print('SAVE ' + name + ' ok=' + str(eal.save_asset(MI_DIR + '/' + name, False)))
for spec in TYPES:
    if ONLY is not None and spec['path'] != ONLY:
        continue
    if MODE == 'save':
        print('SAVE ' + spec['path'] + ' ok=' + str(eal.save_asset(spec['path'], False)))
        continue
    if MODE == 'apply':
        lgt, created = ensure(spec['path'])
        meshes = [eal.load_asset(m) for m in spec['meshes']]
        bad = [spec['meshes'][i] for i in range(len(meshes)) if not isinstance(meshes[i], unreal.StaticMesh)]
        if len(bad) > 0 or len(meshes) == 0:
            print('GRASS ' + spec['path'] + ' REFUSED: not static meshes ' + str(bad))
            continue
        mis = [ensure_mi(n) for n in spec['materials']]
        lgt.set_editor_property('grass_varieties', [variety(spec, meshes[i], spec['shares'][i], mis[i])
                                                    for i in range(len(meshes))])
        print('GRASS ' + spec['path'] + ' created=' + str(created) + ' varieties=' + str(len(meshes)))
    lgt = eal.load_asset(spec['path'])
    if lgt is None:
        print('GRASS ' + spec['path'] + ' MISSING')
        continue
    for row in readback(lgt):
        print('  ' + str(row))
