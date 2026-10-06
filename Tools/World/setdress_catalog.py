"""The set-dressing asset catalog: short keys -> package paths, category and size.

Shared by build_setdress_sites.py (offline planning) and its tests. Sizes come from
Tools/World/setdress_assets.json (the uasset ApproxSize tags, see scan_setdress_assets.py);
the Batch01 meshes are not imported yet, so their size is the FBX size from
docs/models/stats.md times the planned import scale below.

Style rules (author, 2026-09-28):
- BAZAAR STONE FIRST. AshesOfBazaar and the stone Batch01 pieces are the architecture.
  MedievalVillage wood is only for farms, barns and the waystation, plus small props
  (carts, barrels, crates, jute bags, buckets, wells).
- The world's tech is steampunk / biofuel / medieval / retrofuturist: brass, copper, riveted
  iron, valves and gauges, biofuel tanks and vats, hand-cranked machines, timber, stone, cloth,
  rope. Old machines are allowed when they read that way. Anything contemporary is forbidden:
  asphalt, plastic, chain-link, modern road signs, electric poles with modern insulators and
  wires, cars, modern military kit (the Megascans trench sandbags stay out unless they read
  as old earth sacks).
- Nothing religious; the valley is emptied, not massacred (no bodies, no gore).
"""
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
INVENTORY = os.path.join(ROOT, 'Tools', 'World', 'setdress_assets.json')
MODEL_STATS = os.path.join(ROOT, 'docs', 'models', 'stats.md')

AB = '/Game/AshesOfBazaar/Meshes/'
ABP = '/Game/AshesOfBazaar/Blueprint/'
MV = '/Game/MedievalVillage/Meshes/'
MVB = '/Game/MedievalVillage/Blueprints/'
PHB = '/Game/Pallbearer/PolyHaven/'
FAB = '/Game/Fab/Megascans/3D/'
B01 = '/Game/SaskartaGaea/Environment/Batch01/SM_B01_'
VFX = '/Game/Vefects/Free_Fire/Shared/Particles/'


def ph(asset, part=None):
    return PHB + '%s/%s_2k/StaticMeshes/%s' % (asset, asset, part or asset + '_2k')


# Batch01 (SourceArt/Environment/batch01, 36 FBX, Tripo-style, every file normalised to a
# ~1.9 m longest axis). verdict: use = fits the world; check = the editor lane looks at it in
# the first capture and keeps it only if it reads old / steampunk / retrofuturist (else the
# placement is dropped or takes its fallback); reject = contemporary, never placed.
# scale = the uniform import scale that brings it to the real size given in the note.
BATCH01 = {
    'arch01':     (2.6, 'use', 'ruined rubble-stone arch, 4.9 m wide, 3.3 m tall'),
    'beam01':     (1.6, 'use', 'iron-banded timber beam, 3 m'),
    'bench01':    (1.0, 'check', 'cast-iron and timber bench, 1.9 m; Victorian cast iron fits the steampunk rule, platform only'),
    'brick01':    (0.8, 'use', 'cut sandstone block, 1.5 m (quarry, steps, bench legs)'),
    'bridge01':   (5.0, 'use', 'six-arch stone aqueduct/footbridge run, 9.5 m long, 2.6 m tall'),
    'channel01':  (2.2, 'use', 'stone irrigation channel segment, 1.1 m wide, 4.2 m long'),
    'crane01':    (1.8, 'use', 'hand-cranked timber crane on a stone drum, 3.4 m (fits the steampunk rule)'),
    'dock01':     (1.6, 'check', 'riveted iron cradle frame with rollers, 3 m; retrofuturist carrier-cradle candidate, check it reads old/riveted'),
    'floor01':    (1.6, 'use', 'flagstone slab, 3 x 3 m'),
    'gate01':     (1.2, 'use', 'timber sluice gate with an iron screw hand-wheel, 2.3 m (hand-cranked: fits)'),
    'house01':    (4.5, 'check', 'intact tiled-roof stone cottage, 8.5 m; intact and Mediterranean, distant use only'),
    'house02':    (4.2, 'use', 'roofless ruined two-storey stone house, 7.9 x 7.3 x 7.6 m'),
    'house03':    (4.8, 'use', 'ruined stone tower house, 9 m tall (watchtower)'),
    'marker01':   (0.42, 'use', 'rounded standing stone with a flat face, 0.8 m (way-stone / stele blank)'),
    'monument01': (1.2, 'use', 'broken stele / standing slab, 2.3 m'),
    'pillar01':   (1.5, 'use', 'tapered rubble-stone pillar, 2.9 m'),
    'pipe01':     (1.2, 'check', 'riveted, banded pipe elbow, 2.3 m; fits the works only if the orange paint reads rusted iron, not modern'),
    'pump01':     (1.0, 'check', 'enamel pressure pump with brass gauges and a valve wheel, 1.9 m; keep only if it reads retrofuturist (biofuel), not a 20th-century fuel pump'),
    'rail01':     (1.6, 'check', 'timber-sleeper iron track, 3 m; a hand-cart track at the quarry/works only, never a railway line'),
    'rubble01':   (1.6, 'use', 'sandstone rubble heap, 3 m'),
    'ruin01':     (7.0, 'use', 'ruined walled compound, 13 x 10 x 8 m (keep / caravanserai core)'),
    'scale01':    (1.0, 'check', 'timber water-gauge board with 0-20 marks, 1.9 m; cistern gauge candidate if the numerals read hand-cut'),
    'shelter01':  (3.4, 'use', 'timber deck on four stone piers, 6.4 x 6.2 x 4.1 m (platform / shade)'),
    'sign01':     (1.0, 'reject', 'pictogram sign with a cable-car icon: modern'),
    'sign02':     (0.6, 'use', 'iron-strapped timber notice board, 0.8 x 1.1 m (painted boards: the numbered signs of the story)'),
    'sign03':     (0.6, 'use', 'same notice board, second texture'),
    'station01':  (6.0, 'check', 'tiled-roof arcaded stone hall, 11 x 8 m; may read European, caravan-inn stalls only if it fits'),
    'support01':  (1.3, 'use', 'stone plinth with a timber post and iron pivot, 2.5 m (sluice winch post)'),
    'tank01':     (0.65, 'use', 'wood-hooped clay storage jar with a spout, 1.2 m (not a metal tank)'),
    'village01':  (16.0, 'use', 'ruined mud-brick village block, 30 x 24 x 19 m (distant silhouette)'),
    'wall01':     (2.1, 'use', 'broken rubble wall, 4 m long, 1.8 m tall'),
    'wall02':     (2.0, 'use', 'dry-stone field wall, 3.8 m long, 1 m tall'),
    'wall03':     (2.3, 'use', 'plastered U-shaped ruin corner, 4.4 x 3.3 x 2.6 m'),
    'wall04':     (2.2, 'use', 'plastered wall panel, 4.2 m long, 1.8 m tall'),
    'wheel01':    (2.1, 'use', 'timber water wheel, 4 m'),
    'window01':   (1.6, 'use', 'stone wall with a window, 2.1 x 3 m'),
}

# Fallback when a Batch01 mesh is not imported yet: (catalog key, extra scale).
BATCH01_FALLBACK = {
    'arch01': ('AB_Side_Arch_small', 1.0), 'brick01': ('FAB_TempleStones', 0.8),
    'bridge01': ('AB_Side_aRCH_WALL', 1.0), 'channel01': ('AB_Broken_Walls', 1.0),
    'house02': ('AB_BrokenStructer', 0.7), 'house03': ('AB_Damaged_Minarate', 0.5),
    'marker01': ('FAB_TempleStones', 0.45), 'monument01': ('FAB_TempleStones', 1.1),
    'pillar01': ('AB_Pillar_A_01', 1.3), 'rubble01': ('AB_Pillar_A_05', 1.8),
    'ruin01': ('AB_BrokenStructer', 1.0), 'shelter01': ('BPP_Terrace_01', 1.0),
    'tank01': ('AB_Clay_Pot_A', 1.8), 'wall01': ('AB_Broken_Walls', 2.0),
    'wall02': ('AB_Broken_Walls', 1.5), 'wall03': ('AB_300x400_Mid_Damaged_A', 1.0),
    'wall04': ('AB_300x400_Mid_Damaged_A', 1.0), 'wheel01': ('MV_Woodmill_Wheel', 0.9),
    'window01': ('AB_300x400_Mid_Damaged_A', 1.0), 'floor01': ('AB_Planks_150_A', 1.5),
    'bench01': ('MV_bench_02', 1.0), 'dock01': ('MV_Manger', 1.0),
}

# key -> (path, category). Categories drive the settle mode, sink, draw distance and tags.
#   building: houses, ruins, towers         wall: wall and arch runs
#   stone: steles, blocks, pillars, rocks   prop: crates, pots, carts, bags (physics)
#   rubble: small masonry debris (ISM)      wood: logs, beams, planks (physics)
#   veg: dead trees, stumps, shrubs         cloth: tarps, cloth, flags
#   bpp: packed level actors                fx: Niagara
_C = {}


def _add(key, path, cat):
    _C[key] = (path, cat)


for n in ('SM_Broken_Arch_Wall', 'SM_Broken_Walls', 'SM_Broken_Windwo_wall_low', 'SM_Fort_Wall_Mid',
          'SM_300x400_Mid', 'SM_300x400_Mid_Damaged_A', 'SM_300x400_Corner_90d', 'SM_Side_Arch',
          'SM_Side_Arch_small', 'SM_Side_aRCH_WALL', 'SM_Danaged_Wall_B', 'SM_300x100_Panel_Damages_A',
          'SM_300x100_Panel', 'SM_Interior_Arch_low', 'SM_Arch_D_Zbrush_Export'):
    _add('AB_' + n[3:], AB + n, 'wall')
for n in ('SM_BrokenStructer', 'SM_Damaged_Minarate', 'SM_Minarate_Damaged', 'SM_Arch_E'):
    _add('AB_' + n[3:], AB + n, 'building')
for n in ('SM_Damaged_Pillar_A', 'SM_Damaged_Pillar_A1', 'SM_Pillar_A_01', 'SM_Pillar_A_02', 'SM_Pillar_A_03',
          'SM_Pillar_low', 'SM_Fireplace'):
    _add('AB_' + n[3:], AB + n, 'stone')
for n in ('SM_Pillar_A_04', 'SM_Pillar_A_05', 'SM_Pillar_Part'):
    _add('AB_' + n[3:], AB + n, 'rubble_big')
for n in ('SM_Box_A', 'SM_Box_B', 'SM_Box_C', 'SM_Clay_Pot_A', 'SM_Clay_Pot_B', 'SM_Clay_Pot_C', 'SM_Clay_Pot_D',
          'SM_Table', 'SM_Chair_A_low', 'SM_Lamp_A', 'SM_Lamp_B', 'SM_Lamp_C', 'SM_Cart_A_texturing',
          'SM_Cart_Wheel', 'SM_Cart_Plank', 'SM_WoodenTable_B', 'SM_OutdoorRake_A'):
    _add('AB_' + n[3:], AB + n, 'prop')
for n in ('SM_Planks_150_A', 'SM_Planks_150_B', 'SM_Woden_Beam_A_low'):
    _add('AB_' + n[3:], AB + n, 'wood')
for n in ('SM_Damaged_Tent_A', 'SM_Tent_A', 'SM_Tent_C_Frame', 'SM_Tent_C_Cloth', 'SM_Tent_Cloth_B_frame',
          'sm_Tent_B_Cloth_low', 'SM_Table_Cloth'):
    _add('AB_' + n[3:], AB + n, 'cloth')
for i in ('', '1', '2', '3', '4', '5'):
    _add('AB_Brick_A' + i, AB + 'SM_Damaged_Brick_SM_Damaged_Brick_A' + i, 'rubble')
for i in range(1, 8):
    _add('AB_Cobble_%02d' % i, AB + 'SM_Cobble_Stone_A_SM_Cobble_Stone_A_%02d' % i, 'rubble')
_add('AB_FogCard', AB + 'SM_Fog_Card', 'fx_card')
_add('ABP_Arch_D', ABP + 'BP_Arch_D', 'bp')

for n, cat in (('Misc/SM_well', 'stone'), ('Misc/SM_Manger', 'prop'), ('Misc/SM_Manger_support_01', 'wood'),
               ('Misc/SM_cart_01', 'prop'), ('Misc/SM_cart_01_wheels', 'prop'), ('Misc/SM_cart_02', 'prop'),
               ('Misc/SM_cart_02_wheels', 'prop'), ('Misc/SM_cart_tarp', 'cloth'), ('Misc/SM_cart_top', 'prop'),
               ('Misc/SM_bucket_01', 'prop'), ('Misc/SM_bucket_02', 'prop'), ('Misc/SM_bucket_03', 'prop'),
               ('Misc/SM_carafe_01', 'prop'), ('Misc/SM_carafe_02', 'prop'), ('Misc/SM_wash_tub', 'prop'),
               ('Misc/SM_barrel_01', 'prop'), ('Misc/SM_barrel_02', 'prop'), ('Misc/SM_box_01', 'prop'),
               ('Misc/SM_box_02', 'prop'), ('Misc/SM_box_03', 'prop'), ('Misc/SM_box_04', 'prop'),
               ('Misc/SM_box_05', 'prop'), ('Misc/SM_Hay_Bale_01', 'prop'), ('Misc/SM_Hay_Bale_02', 'prop'),
               ('Misc/SM_table_01', 'prop'), ('Misc/SM_table_02', 'prop'), ('Misc/SM_bench_02', 'prop'),
               ('Misc/SM_bench_03', 'prop'), ('Misc/SM_Cloth_01', 'cloth'), ('Misc/SM_Cloth_02', 'cloth'),
               ('Misc/SM_Rope_01', 'prop'), ('Misc/SM_Logs_Package', 'wood'),
               ('Misc/SM_Log_01', 'wood'), ('Misc/SM_Log_02', 'wood'), ('Misc/SM_Log_05', 'wood'),
               ('Misc/SM_Log_07', 'wood'), ('Misc/SM_Log_08', 'wood'),
               ('House/SM_Beam_03', 'wood'), ('House/SM_Beam_06', 'wood'), ('House/SM_Beam_08', 'wood'),
               ('House/SM_Foundation', 'wall'), ('House/SM_Foundation_Corner', 'wall'), ('House/SM_Chimney', 'stone'),
               ('House/SM_Wall_01', 'wall'), ('House/SM_Wall_03', 'wall'), ('House/SM_Roof_Beams_Middle', 'wood'),
               ('House/SM_Roof_Beams_Top_02', 'wood'), ('House/SM_Door_01', 'wood'),
               ('Fence_01/SM_Fence_01_V1', 'wall'), ('Fence_01/SM_Fence_01_V2', 'wall'), ('Fence_01/SM_Fence_01_V3', 'wall'),
               ('Fence_01/SM_Fence_01_Log1', 'wood_post'), ('Fence_01/SM_Fence_01_Log2', 'wood_post'),
               ('Fence_01/SM_Fence_01_board1', 'wood'), ('Fence_01/SM_Fence_01_board2', 'wood'),
               ('Fence_03/SM_Fence_03_V1', 'wall'), ('Fence_03/SM_Fence_03_V2', 'wall'),
               ('Barn/SM_Barn_Fence_01', 'wall'), ('Barn/SM_Barn_Fence_02', 'wall'),
               ('Tarp_Annexes/SM_Annex_Tarp_01', 'cloth'), ('Tarp_Annexes/SM_Annex_Tarp_02', 'cloth'),
               ('Hay_Annex/SM_Annex_Hay', 'building'), ('Rope_Annex/SM_Annex_Rope', 'building'),
               ('Rope_Annex/SM_Rope_Woven', 'prop'),
               ('Terrace/SM_Terrace_Stairs', 'wood'), ('Terrace/SM_Terrace_Stairs_02', 'wood'),
               ('Woodmill/SM_Woodmill_Wheel', 'wood'), ('Woodmill/SM_Wm_wheel_support', 'wood')):
    _add('MV_' + n.split('/')[1][3:], MV + n, cat)
for i in range(1, 11):
    _add('MV_jute_bag_%02d' % i, MV + 'Misc/SM_jute_bag_%02d' % i, 'prop')
for n in ('Annex_01', 'Annex_02', 'Annex_03', 'Barn', 'Barrels_01', 'Barrels_03', 'Boxes', 'Boxes_02', 'Boxes_03',
          'Cart_01', 'Cart_02', 'Cart_03', 'Cart_04', 'Cart_05', 'Hay_Bale', 'Jute_Bags', 'Jute_Bags_02',
          'Jute_Bags_03', 'Jute_Bags_04', 'Logs_01', 'Logs_03', 'Manger_01', 'Terrace_01', 'Terrace_03',
          'Wash_Tube', 'Wooden_Pen_01', 'Wooden_Pen_02', 'Woodmill', 'Table_Bench_01'):
    _add('BPP_' + n, MVB + 'BPP_PLA_' + n, 'bpp')

_add('FAB_TempleStones', FAB + 'Ancient_Temple_Stones_tixjegefa/Medium/tixjegefa_tier_2/StaticMeshes/tixjegefa_tier_2', 'stone')
_add('FAB_Stump', FAB + 'Broken_Stump_rkswd/Medium/rkswd_tier_2/StaticMeshes/rkswd_tier_2', 'veg')
_add('FAB_DeadTree_qlEtl', FAB + 'Dead_Tree_qlEtl/Raw/qlEtl_tier_0/StaticMeshes/qlEtl_tier_0', 'hero_tree')
_add('FAB_DeadTree_rlthg', FAB + 'Dead_Tree_rlthg/Raw/rlthg_tier_0/StaticMeshes/rlthg_tier_0', 'hero_tree')
_add('FAB_Campfire', FAB + 'Campfire_uenpfeifa/Raw/uenpfeifa_tier_0/StaticMeshes/uenpfeifa_tier_0', 'prop_static')
_add('FAB_Sandbags', FAB + 'Military_Trenches_Barrier_Sandbag_Canvas_03_ydymfdzga/High/SM_ydymfdzga_tier_1/StaticMeshes/SM_ydymfdzga_tier_1', 'wall')
for v in 'ABCDEFGH':
    _add('FAB_Shrub_' + v, '/Game/Fab/Megascans/Plants/Dead_Shrubs_vdknafgha/Raw/vdknafgha_tier_0/StaticMeshes/SM_vdknafgha_Var' + v, 'shrub')
_add('FAB_Twig', '/Game/Fab/Twig_V4_PBR/twig_4_max/StaticMeshes/twig_4_max', 'veg')
for i in range(1, 9):
    _add('LF_Rock_%02d' % i, '/Game/Light_Foliage/Meshes/SM_Rock_%02d' % i, 'stone' if i <= 5 else 'rubble')

for key, (asset, part) in {
        'PH_boulder': ('boulder_01', None), 'PH_rock_face': ('rock_face_02', None),
        'PH_trunk': ('dead_tree_trunk', None), 'PH_trunk_02': ('dead_tree_trunk_02', None),
        'PH_stump_01': ('tree_stump_01', None), 'PH_stump_02': ('tree_stump_02', None),
        'PH_roots_a': ('pine_roots', 'pine_roots_a'), 'PH_roots_b': ('pine_roots', 'pine_roots_b'),
        'PH_branches_a': ('dry_branches_medium_01', 'dry_branches_medium_01_a'),
        'PH_branches_b': ('dry_branches_medium_01', 'dry_branches_medium_01_b'),
        'PH_fire_pit': ('stone_fire_pit', None), 'PH_lantern': ('Lantern_01', 'Lantern_01'),
        'PH_mcrate': ('old_military_crate', 'old_military_crate_a'),
        'PH_wcrate': ('wooden_crate_02', 'wooden_crate_02_crate'),
        'PH_barrel': ('barrel_03', None), 'PH_pot': ('pot_enamel_01', 'pot_enamel_01_base'),
        'PH_moss_rock_07': ('rock_moss_set_02', 'rock_moss_set_02_rock07'),
        'PH_moss_rock_09': ('rock_moss_set_02', 'rock_moss_set_02_rock09'),
        'PH_moss_rock_11': ('rock_moss_set_02', 'rock_moss_set_02_rock11')}.items():
    cat = {'PH_boulder': 'stone', 'PH_rock_face': 'stone', 'PH_fire_pit': 'stone', 'PH_trunk': 'wood',
           'PH_trunk_02': 'wood', 'PH_roots_a': 'veg', 'PH_roots_b': 'veg', 'PH_stump_01': 'veg',
           'PH_stump_02': 'veg', 'PH_moss_rock_07': 'stone', 'PH_moss_rock_09': 'stone',
           'PH_moss_rock_11': 'stone'}.get(key, 'prop')
    if key.startswith('PH_branches'):
        cat = 'wood'
    _add(key, ph(asset, part), cat)

_add('LF_Flowers_01', '/Game/Light_Foliage/Meshes/SM_Flowers_01', 'shrub')
# the pale dry tufts the landscape grass already grows (Tools/Foliage/configure_grass.py 'dry'); set dressing V2
# places them as creep inside roofless rooms with the same project MIs (DRY_TUFT_MATERIAL)
MVG = '/Game/MedievalVillage/Demo/StaticMesh/Grass/'
for n in ('V1_02', 'V2_01', 'V2_03', 'V5_05'):
    _add('MV_Grass_' + n, MVG + 'SM_Grass_' + n, 'shrub')
DRY_TUFT_MATERIAL = {
    'MV_Grass_V1_02': '/Game/SaskartaGaea/Foliage/Materials/MI_Saskarta_DryTuft_Straw',
    'MV_Grass_V2_01': '/Game/SaskartaGaea/Foliage/Materials/MI_Saskarta_DryTuft_Ochre',
    'MV_Grass_V2_03': '/Game/SaskartaGaea/Foliage/Materials/MI_Saskarta_DryTuft_Olive',
    'MV_Grass_V5_05': '/Game/SaskartaGaea/Foliage/Materials/MI_Saskarta_DryTuft_Rust',
}
_add('TRIPO_Flag', '/Game/Pallbearer/Tripo/extras/Untitled/StaticMeshes/Flag', 'cloth')
for n in ('NS_Fire_Floor_01_Smoke', 'NS_Fire_Small_Smoke', 'NS_Fire_Big_Smoke'):
    _add('VFX_' + n[3:], VFX + n, 'fx')

for name, (scale, verdict, note) in BATCH01.items():
    if verdict == 'reject':
        continue
    cat = {'house01': 'building', 'house02': 'building', 'house03': 'building', 'ruin01': 'building',
           'village01': 'building', 'station01': 'building', 'shelter01': 'building', 'bridge01': 'wall',
           'arch01': 'wall', 'wall01': 'wall', 'wall02': 'wall', 'wall03': 'wall', 'wall04': 'wall',
           'window01': 'wall', 'channel01': 'wall', 'floor01': 'wall', 'marker01': 'stone',
           'monument01': 'stone', 'pillar01': 'stone', 'brick01': 'stone', 'rubble01': 'stone',
           'support01': 'stone', 'crane01': 'stone', 'gate01': 'wall', 'wheel01': 'wood',
           'beam01': 'wood', 'tank01': 'prop', 'sign02': 'wood_post', 'sign03': 'wood_post',
           'bench01': 'prop_static', 'dock01': 'prop_static', 'pipe01': 'rubble_big', 'pump01': 'prop_static',
           'rail01': 'wall', 'scale01': 'wood_post'}[name]
    _add('B01_' + name, B01 + name, cat)

_add('MV_Barn_roof_bean', MV + 'Barn/SM_Barn_roof_bean', 'wood')
_add('EA_Pillar10', '/Game/EasyAtmos/EpicContentDemo/DemoRoom/Meshes/Tile_10MPillar', 'stone')
_add('EA_Pipe', '/Game/EasyAtmos/EpicContentDemo/DemoRoom/Meshes/Pipe', 'wood')

# Tripo models being generated in the steampunk-medieval style (author, 2026-09-28), not imported yet.
# Planned path /Game/SaskartaGaea/Environment/Tripo02/SM_T2_<name>. Size = the planned real size (m),
# the fallback is used by place_setdress.py until the asset exists. None = skipped until it exists.
T2 = '/Game/SaskartaGaea/Environment/Tripo02/SM_T2_'
TRIPO2 = {
    # name: (size m (x, y, z), category, fallback (key, scale) or None)
    'relay_tower': ((6, 6, 26), 'building', None),   # no stand-in: the EasyAtmos demo-room pillar read as a modern white monolith (LANE_SD)
    'carrier_cradle': ((3.2, 1.2, 1.3), 'prop_static', ('MV_Manger', 1.0)),
    'mudbrick_house': ((8, 7, 6), 'building', ('B01_house02', 1.0)),
    'mudbrick_house_collapsed': ((8, 7, 3), 'building', ('B01_house02', 0.8)),
    'stone_hut': ((5, 4, 3), 'building', ('B01_house03', 0.8)),
    'courtyard': ((20, 18, 4), 'building', ('B01_ruin01', 1.2)),
    'biofuel_still': ((4, 4, 7), 'building', ('B01_tank01', 4.0)),
    'chem_bench': ((2.2, 0.9, 1.3), 'prop_static', ('AB_WoodenTable_B', 1.2)),
    'pipe_manifold': ((4, 2, 2.2), 'prop_static', None),
    'distillation_column': ((3, 3, 22), 'building', ('AB_Pillar_low', 2.6)),
    'water_wheel': ((5, 2, 5), 'wood', ('B01_wheel01', 1.2)),
    'dovecote': ((4, 4, 8), 'building', ('B01_house03', 0.8)),
    'granary': ((6, 5, 6), 'building', ('B01_house02', 0.8)),
    'animal_pen': ((8, 6, 1.3), 'wall', ('BPP_Wooden_Pen_01', 1.0)),
    'bread_oven': ((2.5, 2.5, 2.2), 'stone', ('AB_Fireplace', 0.5)),
    'jars': ((0.6, 0.6, 0.9), 'prop', ('B01_tank01', 0.7)),
    'way_marker': ((0.5, 0.4, 1.2), 'stone', ('B01_marker01', 1.4)),
    'rope_footbridge': ((16, 1.6, 2.2), 'wood', None),
    'terrace_wall': ((5, 1, 1.5), 'wall', ('B01_wall02', 1.3)),
    'watchtower': ((5, 5, 12), 'building', ('B01_house03', 1.3)),
    # asked for by this plan (not in the Tripo list yet)
    'airship_hull': ((60, 14, 14), 'building', None),
    'brass_dome': ((9, 9, 6), 'building', None),
    'brass_telescope': ((5, 1.5, 4), 'prop_static', None),
    'wind_pump': ((4, 4, 12), 'building', ('B01_pillar01', 2.2)),
    'signal_mirror': ((1.6, 0.6, 2.4), 'prop_static', None),
    'radio_desk': ((2, 0.9, 1.6), 'prop_static', ('AB_WoodenTable_B', 1.0)),
}
for name, (size, cat, fb) in TRIPO2.items():
    _add('T2_' + name, T2 + name, cat)

# The wall pieces' long axis in mesh space (for runs): 'x' or 'y'.
LONG_AXIS_Y = {'AB_Fort_Wall_Mid', 'AB_300x400_Mid', 'AB_300x400_Mid_Damaged_A', 'AB_Broken_Windwo_wall_low',
               'B01_channel01', 'MV_Fence_01_V1', 'MV_Fence_01_V2', 'MV_Fence_01_V3', 'MV_Fence_03_V1',
               'MV_Fence_03_V2', 'MV_Foundation'}
# (Measured from the ApproxSize tags; the editor lane re-checks the orientation in the first capture.)


# Packed level actors and blueprints carry no size tag; these footprints are estimates from
# their parts (the editor lane replaces them with get_actor_bounds after the first spawn).
BP_SIZE_ESTIMATE_CM = {
    'BPP_Barn': [1480, 900, 900], 'BPP_Annex_01': [380, 360, 280], 'BPP_Annex_02': [430, 380, 280],
    'BPP_Annex_03': [400, 370, 280], 'BPP_Barrels_01': [200, 180, 120], 'BPP_Barrels_03': [200, 180, 120],
    'BPP_Boxes': [200, 150, 120], 'BPP_Boxes_02': [200, 150, 120], 'BPP_Boxes_03': [200, 150, 120],
    'BPP_Cart_01': [400, 200, 200], 'BPP_Cart_02': [400, 200, 200], 'BPP_Cart_03': [400, 200, 200],
    'BPP_Cart_04': [400, 200, 200], 'BPP_Cart_05': [400, 200, 200], 'BPP_Hay_Bale': [250, 200, 150],
    'BPP_Jute_Bags': [180, 150, 90], 'BPP_Jute_Bags_02': [180, 150, 90], 'BPP_Jute_Bags_03': [180, 150, 90],
    'BPP_Jute_Bags_04': [180, 150, 90], 'BPP_Logs_01': [360, 150, 100], 'BPP_Logs_03': [360, 150, 100],
    'BPP_Manger_01': [300, 100, 70], 'BPP_Terrace_01': [600, 500, 250], 'BPP_Terrace_03': [600, 500, 250],
    'BPP_Wash_Tube': [150, 150, 70], 'BPP_Wooden_Pen_01': [800, 600, 120], 'BPP_Wooden_Pen_02': [800, 600, 120],
    'BPP_Woodmill': [1120, 1060, 1400], 'BPP_Table_Bench_01': [250, 200, 100], 'ABP_Arch_D': [772, 239, 710],
}
FX_SIZE_CM = [200, 200, 200]


def _batch01_native():
    sizes = {}
    if not os.path.exists(MODEL_STATS):
        return sizes
    for line in open(MODEL_STATS, encoding='utf8'):
        m = re.match(r'\| (\w+) \|.*\| (\d+) x (\d+) x (\d+) \|', line)
        if m:
            sizes[m.group(1)] = [float(m.group(2)), float(m.group(3)), float(m.group(4))]
    return sizes


def load():
    """Return {key: dict(path, cat, size_cm, nanite, tris, exists, batch01, import_scale, verdict, fallback)}."""
    inv = json.load(open(INVENTORY, encoding='utf8'))['assets'] if os.path.exists(INVENTORY) else {}
    native = _batch01_native()
    out = {}
    for key, (path, cat) in _C.items():
        e = dict(path=path, cat=cat, exists=False, batch01=False, size_cm=None, nanite=False, tris=0,
                 kind='SM')
        if key.startswith('BPP_'):
            e['kind'] = 'BPP'
        elif key.startswith('ABP_'):
            e['kind'] = 'BP'
        elif cat == 'fx':
            e['kind'] = 'NS'
        if path in inv:
            a = inv[path]
            e.update(exists=True, size_cm=a.get('size_cm'), nanite=a.get('nanite', False),
                     tris=a.get('tris', 0), file_mb=a.get('file_mb'))
        if key.startswith('B01_'):
            name = key[4:]
            scale, verdict, note = BATCH01[name]
            n = native.get(name)
            measured = e['size_cm'] if path in inv else None     # after the import, the uasset tags win
            # Imported at the FBX's native ~1.9 m (scale 1)? Then the placement carries the scale.
            mult = 1.0
            if measured and n and max(measured) > 0:
                ratio = max(measured) / max(n)
                if abs(ratio - 1.0) < 0.15 and abs(scale - 1.0) > 0.15:
                    mult = scale
            e.update(batch01=True, import_scale=scale, verdict=verdict, note=note,
                     size_cm=([v * mult for v in measured] if measured else ([v * scale for v in n] if n else None)),
                     fallback=BATCH01_FALLBACK.get(name), imported=path in inv, placement_scale_mult=mult)
            e['exists'] = path in inv or os.path.exists(os.path.join(ROOT, 'SourceArt', 'Environment', 'batch01', name + '.fbx'))
        if key.startswith('T2_'):
            size, _, fb = TRIPO2[key[3:]]
            imported = path in inv
            e.update(batch01=True, pending=not imported, verdict='use' if imported else 'pending',
                     import_scale=1.0, size_cm=e['size_cm'] if imported and e['size_cm'] else [v * 100.0 for v in size],
                     fallback=fb, exists=imported, imported=imported,
                     note='Measured imported mesh' if imported else 'Tripo model pending import')
        if e['size_cm'] is None:
            e['size_cm'] = BP_SIZE_ESTIMATE_CM.get(key, FX_SIZE_CM)
            e['size_estimated'] = True
        out[key] = e
    return out
