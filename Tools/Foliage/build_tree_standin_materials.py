# Tree stand-in materials that do not depend on the ProceduralVegetationEditor plugin (LANE4, 2026-09-28).
#
#   python <scratchpad>/send.py Tools/Foliage/build_tree_standin_materials.py "MODE='read'"     # read the Megaplant MIs
#   python <scratchpad>/send.py Tools/Foliage/build_tree_standin_materials.py "MODE='master'"   # MODE='leaf' then MODE='bark': the masters (each saves)
#   python <scratchpad>/send.py Tools/Foliage/build_tree_standin_materials.py "MODE='mis'"      # MIs + mesh slots (no save)
#
# Why (user bug, 2026-09-28: close broadleaf leaves render as opaque dark square cards): the
# SM_Saskarta_TreeFar_* stand-ins use the Megaplant MIs (MI_Ginkgo_Foliage_01, MI_*_Bark_01, ...), whose
# parent MA_Foliage_Trees lives in the ProceduralVegetationEditor engine plugin. That plugin is not
# mounted (log: "expected to be found in plugin Procedural Vegetation Editor, however that plugin is not
# mounted"), so every Megaplant MI loads with no parent and renders with the default opaque material.
# The project's copy M_Saskarta_PlantFoliage depends on the same plugin's functions and textures, so it
# is no fix either. HLOD tiles were baked while the plugin was mounted, so distant trees still look right.
#
# These masters use only the MIs' own textures:
#   M_Saskarta_TreeLeaf  masked, two-sided foliage, dithered LOD transition. BaseColor = CA.rgb x Tint,
#       desaturated by Desat; OpacityMask = CA.a (clip 0.33); Normal = NT.rg with Z rebuilt; subsurface =
#       base colour x Translucency. SaskartaWind WPO is not included (the static stand-ins are still).
#   M_Saskarta_TreeBark  opaque (masked when the colour alpha cuts: barkplates, broken branches).
#       BaseColor = C.rgb x Tint, Normal = NAH.rg with Z rebuilt, AO = NAH.b.
# The MIs copy the Megaplant MI texture values into /Game/SaskartaGaea/Foliage/Static/Materials and
# the stand-in meshes' slots are pointed at them. The Megaplant assets are not edited.
import unreal

MODE = 'read'
# 'mis' is split to stay under python_run's 5 s: ONLY = one source MI name (None = all); MESHES = species to re-slot
ONLY = None
MESHES = []
DEST = '/Game/SaskartaGaea/Foliage/Static/Materials'
SPECIES = ['DeadPine_A', 'DeadPine_B', 'DeadPine_C', 'DeadPine_D', 'DeadPine_E', 'Ginkgo_A', 'Ginkgo_B', 'Ginkgo_C', 'Ginkgo_D']
LEAF = DEST + '/M_Saskarta_TreeLeaf'
BARK = DEST + '/M_Saskarta_TreeBark'
# grading (user: foliage "a bit more uniform and desaturated"; trees only a light touch, ~15 %)
LEAF_TINT = (0.92, 0.9, 0.78)
LEAF_DESAT = 0.15
BARK_TINT = (1.0, 1.0, 1.0)

mel = unreal.MaterialEditingLibrary
eal = unreal.EditorAssetLibrary
at = unreal.AssetToolsHelpers.get_asset_tools()
QUIET = unreal.PropertyAccessChangeNotifyMode.NEVER


def sources():
    out = {}
    for sp in SPECIES:
        sm = unreal.load_asset('/Game/SaskartaGaea/Foliage/Static/SM_Saskarta_TreeFar_' + sp)
        for i, s in enumerate(sm.get_editor_property('static_materials')):
            mi = s.get_editor_property('material_interface')
            if mi is not None:
                out[mi.get_path_name()] = mi
    return out


if MODE == 'read':
    for p, mi in sorted(sources().items()):
        line = mi.get_name() + ' ' + mi.get_class().get_name()
        if isinstance(mi, unreal.MaterialInstanceConstant):
            par = mi.get_editor_property('parent')
            line += ' parent=' + str(par.get_name() if par else None)
            line += ' tex=' + str([(str(t.get_editor_property('parameter_info').get_editor_property('name')), t.get_editor_property('parameter_value').get_name() if t.get_editor_property('parameter_value') else None) for t in mi.get_editor_property('texture_parameter_values')])
            line += ' sc=' + str([(str(t.get_editor_property('parameter_info').get_editor_property('name')), round(t.get_editor_property('parameter_value'), 3)) for t in mi.get_editor_property('scalar_parameter_values')])
        print(line)
    for sp in SPECIES:
        sm = unreal.load_asset('/Game/SaskartaGaea/Foliage/Static/SM_Saskarta_TreeFar_' + sp)
        print('MESH ' + sp + ' ' + str([s.get_editor_property('material_interface').get_name() for s in sm.get_editor_property('static_materials')]) + ' nanite=' + str(sm.get_editor_property('nanite_settings').get_editor_property('enabled')))


def new_material(path):
    m = unreal.load_asset(path)
    if m is None:
        folder, name = path.rsplit('/', 1)
        m = at.create_asset(name, folder, unreal.Material, unreal.MaterialFactoryNew())
    mel.delete_all_material_expressions(m)
    return m


def add(m, cls, x, y):
    return mel.create_material_expression(m, cls, x, y)


def texparam(m, name, x, y, normal=False):
    t = add(m, unreal.MaterialExpressionTextureSampleParameter2D, x, y)
    t.set_editor_property('parameter_name', name)
    # the Megaplant textures are virtual textures (colour: sRGB default, NT/NAH: linear masks); a
    # non-virtual sampler rejects them and the leaves drew as unmasked black cards
    t.set_editor_property('sampler_type', unreal.MaterialSamplerType.SAMPLERTYPE_VIRTUAL_MASKS if normal else unreal.MaterialSamplerType.SAMPLERTYPE_VIRTUAL_COLOR)
    return t


def vparam(m, name, v, x, y):
    p = add(m, unreal.MaterialExpressionVectorParameter, x, y)
    p.set_editor_property('parameter_name', name)
    p.set_editor_property('default_value', unreal.LinearColor(v[0], v[1], v[2], 1.0))
    return p


def sparam(m, name, v, x, y):
    p = add(m, unreal.MaterialExpressionScalarParameter, x, y)
    p.set_editor_property('parameter_name', name)
    p.set_editor_property('default_value', v)
    return p


def rebuilt_normal(m, tex, x, y):
    # tangent normal from RG (linear sampler): rg*2-1, z = sqrt(1 - x^2 - y^2)
    mask = add(m, unreal.MaterialExpressionComponentMask, x, y)
    mask.set_editor_property('r', True); mask.set_editor_property('g', True)
    mask.set_editor_property('b', False); mask.set_editor_property('a', False)
    mel.connect_material_expressions(tex, 'RGB', mask, '')
    two = add(m, unreal.MaterialExpressionConstantBiasScale, x + 150, y)
    two.set_editor_property('bias', -0.5); two.set_editor_property('scale', 2.0)
    mel.connect_material_expressions(mask, '', two, '')
    dz = add(m, unreal.MaterialExpressionDeriveNormalZ, x + 300, y)
    mel.connect_material_expressions(two, '', dz, 'InXY')
    return dz


def graded_colour(m, tex, tint, desat, x, y):
    mul = add(m, unreal.MaterialExpressionMultiply, x + 200, y)
    mel.connect_material_expressions(tex, 'RGB', mul, 'A')
    mel.connect_material_expressions(vparam(m, 'Tint', tint, x, y + 120), '', mul, 'B')
    ds = add(m, unreal.MaterialExpressionDesaturation, x + 350, y)
    mel.connect_material_expressions(mul, '', ds, '')
    mel.connect_material_expressions(sparam(m, 'Desat', desat, x + 200, y + 200), '', ds, 'Fraction')
    return ds


if MODE == 'leaf':
    m = new_material(LEAF)
    m.set_editor_property('blend_mode', unreal.BlendMode.BLEND_MASKED)
    m.set_editor_property('shading_model', unreal.MaterialShadingModel.MSM_TWO_SIDED_FOLIAGE)
    m.set_editor_property('two_sided', True)
    m.set_editor_property('dithered_lod_transition', True)
    m.set_editor_property('opacity_mask_clip_value', 0.33)
    ca = texparam(m, 'ColorAlpha', -900, -200)
    ca.set_editor_property('texture', unreal.load_asset('/Game/Megaplant_Library/Tree_Ginkgo/Textures/T_Ginkgo_Foliage_01_CA'))
    nt = texparam(m, 'NormalTrans', -900, 200, True)
    nt.set_editor_property('texture', unreal.load_asset('/Game/Megaplant_Library/Tree_Ginkgo/Textures/T_Ginkgo_Foliage_01_NT'))
    col = graded_colour(m, ca, LEAF_TINT, LEAF_DESAT, -600, -300)
    mel.connect_material_property(col, '', unreal.MaterialProperty.MP_BASE_COLOR)
    mel.connect_material_property(ca, 'A', unreal.MaterialProperty.MP_OPACITY_MASK)
    mel.connect_material_property(rebuilt_normal(m, nt, -600, 200), '', unreal.MaterialProperty.MP_NORMAL)
    rough = sparam(m, 'Roughness', 0.7, -300, 100)
    mel.connect_material_property(rough, '', unreal.MaterialProperty.MP_ROUGHNESS)
    ss = add(m, unreal.MaterialExpressionMultiply, -200, 400)
    mel.connect_material_expressions(col, '', ss, 'A')
    mel.connect_material_expressions(sparam(m, 'Translucency', 0.5, -400, 480), '', ss, 'B')
    mel.connect_material_property(ss, '', unreal.MaterialProperty.MP_SUBSURFACE_COLOR)
    mel.recompile_material(m)
    print('LEAF saved=' + str(eal.save_loaded_asset(m, False)))


if MODE == 'bark':
    b = new_material(BARK)
    b.set_editor_property('blend_mode', unreal.BlendMode.BLEND_MASKED)
    b.set_editor_property('dithered_lod_transition', True)
    b.set_editor_property('opacity_mask_clip_value', 0.33)
    c = texparam(b, 'Color', -900, -200)
    c.set_editor_property('texture', unreal.load_asset('/Game/Megaplant_Library/Tree_Ginkgo/Textures/T_Ginkgo_Trunkmat_C'))
    nah = texparam(b, 'NormalAOHeight', -900, 200, True)
    nah.set_editor_property('texture', unreal.load_asset('/Game/Megaplant_Library/Tree_Ginkgo/Textures/T_Ginkgo_Trunkmat_NAH'))
    bcol = graded_colour(b, c, BARK_TINT, 0.1, -600, -300)
    mel.connect_material_property(bcol, '', unreal.MaterialProperty.MP_BASE_COLOR)
    mel.connect_material_property(c, 'A', unreal.MaterialProperty.MP_OPACITY_MASK)
    mel.connect_material_property(rebuilt_normal(b, nah, -600, 200), '', unreal.MaterialProperty.MP_NORMAL)
    mel.connect_material_property(nah, 'B', unreal.MaterialProperty.MP_AMBIENT_OCCLUSION)
    mel.connect_material_property(sparam(b, 'Roughness', 0.85, -300, 100), '', unreal.MaterialProperty.MP_ROUGHNESS)
    mel.recompile_material(b)
    print('BARK saved=' + str(eal.save_loaded_asset(b, False)))


if MODE == 'mis':
    leaf = unreal.load_asset(LEAF)
    bark = unreal.load_asset(BARK)
    made = {}
    for p, src in sorted(sources().items()):
        if src.get_name().startswith('MI_TreeStandin_') or (ONLY is not None and src.get_name() != ONLY):
            continue
        texs = {}
        for t in src.get_editor_property('texture_parameter_values'):
            v = t.get_editor_property('parameter_value')
            if v is not None:
                texs[v.get_name()] = v
        colour = [v for n, v in texs.items() if n.endswith('_CA') or n.endswith('_C')]
        normal = [v for n, v in texs.items() if n.endswith('_NT') or n.endswith('_NAH')]
        is_leaf = len([n for n in texs if n.endswith('_CA')]) > 0
        name = 'MI_TreeStandin_' + src.get_name()[3:]
        path = DEST + '/' + name
        mi = unreal.load_asset(path)
        if mi is None:
            mi = at.create_asset(name, DEST, unreal.MaterialInstanceConstant, unreal.MaterialInstanceConstantFactoryNew())
        mel.set_material_instance_parent(mi, leaf if is_leaf else bark)
        if colour:
            mel.set_material_instance_texture_parameter_value(mi, 'ColorAlpha' if is_leaf else 'Color', colour[0])
        if normal:
            mel.set_material_instance_texture_parameter_value(mi, 'NormalTrans' if is_leaf else 'NormalAOHeight', normal[0])
        mel.update_material_instance(mi)
        made[src.get_path_name()] = mi
        print('MI ' + name + ' leaf=' + str(is_leaf) + ' tex=' + str(sorted(texs)))


if MODE == 'meshes':
    made = {}
    for p, src in sorted(sources().items()):
        mi = unreal.load_asset(DEST + '/MI_TreeStandin_' + src.get_name()[3:])
        if mi is not None and not src.get_name().startswith('MI_TreeStandin_'):
            made[src.get_path_name()] = mi
    for sp in MESHES:
        sm = unreal.load_asset('/Game/SaskartaGaea/Foliage/Static/SM_Saskarta_TreeFar_' + sp)
        slots = sm.get_editor_property('static_materials')
        for i in range(len(slots)):
            src = slots[i].get_editor_property('material_interface')
            if src is not None and src.get_path_name() in made:
                sm.set_material(i, made[src.get_path_name()])
        print('MESH ' + sp + ' -> ' + str([s.get_editor_property('material_interface').get_name() for s in sm.get_editor_property('static_materials')]))
