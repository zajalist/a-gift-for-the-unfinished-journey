# Grass and shrubs pick up the local ground colour (LANE4, user 2026-09-28: "the foliage colors don't blend
# well into the landscape material").
#
#   python <send.py> Tools/Foliage/build_ground_blend.py "MODE='function'"          # MF_Saskarta_GroundBlend (saves)
#   python <send.py> Tools/Foliage/build_ground_blend.py "MODE='inspect'" "SRC='<master path>'"
#   python <send.py> Tools/Foliage/build_ground_blend.py "MODE='copy'" "SRC='<master>'" "DST='<name>'" "ROOT=0.8" "TIP=0.3"
#   python <send.py> Tools/Foliage/build_ground_blend.py "MODE='reparent'" "MIS=[...]" "DST='<name>'"
#
# MF_Saskarta_GroundBlend(Colour, Roughness, Root, Tip):
#   t      = saturate((AbsoluteWorldPosition.z - ObjectPositionWS.z) / ObjectBounds.z)   0 at the root, 1 at the tip
#            (ObjectPositionWS is the instance's pivot for instanced grass)
#   k      = lerp(Root, Tip, t)
#   ground = RVT_Saskarta_Terrain BaseColor / Roughness at this pixel's world position (the landscape's own colour)
#   Colour'    = lerp(Colour, ground, k) * lerp(0.8, 1, t)        (a slightly darker root, like AO)
#   Roughness' = lerp(Roughness, groundRoughness, k)
# The third-party masters are never edited: 'copy' duplicates a master into DEST, inserts the function
# between whatever fed BaseColor / Roughness and the output, and 'reparent' points the project's own
# MI_Saskarta_* grass instances at the copy (every parameter keeps its name, so the overrides carry over).
import unreal

MODE = 'inspect'
SRC = ''
DST = ''
ROOT = 0.8
TIP = 0.3
MIS = []
DEST = '/Game/SaskartaGaea/Foliage/Materials/Masters'
MF = DEST + '/MF_Saskarta_GroundBlend'
RVT = '/Game/SaskartaGaea/RVT/RVT_Saskarta_Terrain'

mel = unreal.MaterialEditingLibrary
eal = unreal.EditorAssetLibrary
at = unreal.AssetToolsHelpers.get_asset_tools()
MP = unreal.MaterialProperty

if MODE == 'inspect':
    m = unreal.load_asset(SRC)
    print('attrs', m.get_editor_property('use_material_attributes'), 'blend', str(m.get_editor_property('blend_mode')), 'sm', str(m.get_editor_property('shading_model')))
    for prop in [MP.MP_BASE_COLOR, MP.MP_ROUGHNESS, MP.MP_MATERIAL_ATTRIBUTES]:
        n = mel.get_material_property_input_node(m, prop)
        print(str(prop), n.get_class().get_name() if n else None, mel.get_material_property_input_node_output_name(m, prop) if n else '')
    print('nexpr', mel.get_num_material_expressions(m), 'ism', m.get_editor_property('used_with_instanced_static_meshes'))

if MODE == 'function':
    f = unreal.load_asset(MF)
    if f is None:
        f = at.create_asset('MF_Saskarta_GroundBlend', DEST, unreal.MaterialFunction, unreal.MaterialFunctionFactoryNew())
    mel.delete_all_material_expressions_in_function(f)
    def add(cls, x, y):
        return mel.create_material_expression_in_function(f, cls, x, y)
    def fin(name, t, x, y, prio):
        i = add(unreal.MaterialExpressionFunctionInput, x, y)
        i.set_editor_property('input_name', name)
        i.set_editor_property('input_type', t)
        i.set_editor_property('sort_priority', prio)
        return i
    FI = unreal.FunctionInputType
    cin = fin('Colour', FI.FUNCTION_INPUT_VECTOR3, -1200, -200, 0)
    rin = fin('Roughness', FI.FUNCTION_INPUT_SCALAR, -1200, 0, 1)
    root = fin('Root', FI.FUNCTION_INPUT_SCALAR, -1200, 200, 2)
    tip = fin('Tip', FI.FUNCTION_INPUT_SCALAR, -1200, 300, 3)
    wp = add(unreal.MaterialExpressionWorldPosition, -1200, 450)
    op = add(unreal.MaterialExpressionObjectPositionWS, -1200, 550)
    ob = add(unreal.MaterialExpressionObjectBounds, -1200, 650)
    wz = add(unreal.MaterialExpressionComponentMask, -1000, 450)
    wz.set_editor_property('r', False); wz.set_editor_property('g', False); wz.set_editor_property('b', True); wz.set_editor_property('a', False)
    mel.connect_material_expressions(wp, '', wz, '')
    oz = add(unreal.MaterialExpressionComponentMask, -1000, 550)
    oz.set_editor_property('r', False); oz.set_editor_property('g', False); oz.set_editor_property('b', True); oz.set_editor_property('a', False)
    mel.connect_material_expressions(op, '', oz, '')
    bz = add(unreal.MaterialExpressionComponentMask, -1000, 650)
    bz.set_editor_property('r', False); bz.set_editor_property('g', False); bz.set_editor_property('b', True); bz.set_editor_property('a', False)
    mel.connect_material_expressions(ob, '', bz, '')
    dz = add(unreal.MaterialExpressionSubtract, -850, 500)
    mel.connect_material_expressions(wz, '', dz, 'A')
    mel.connect_material_expressions(oz, '', dz, 'B')
    bmax = add(unreal.MaterialExpressionMax, -850, 650)
    bmax.set_editor_property('const_b', 1.0)
    mel.connect_material_expressions(bz, '', bmax, 'A')
    div = add(unreal.MaterialExpressionDivide, -700, 550)
    mel.connect_material_expressions(dz, '', div, 'A')
    mel.connect_material_expressions(bmax, '', div, 'B')
    t = add(unreal.MaterialExpressionSaturate, -550, 550)
    mel.connect_material_expressions(div, '', t, '')
    k = add(unreal.MaterialExpressionLinearInterpolate, -400, 300)
    mel.connect_material_expressions(root, '', k, 'A')
    mel.connect_material_expressions(tip, '', k, 'B')
    mel.connect_material_expressions(t, '', k, 'Alpha')
    rvt = unreal.load_asset(RVT)
    rs = add(unreal.MaterialExpressionRuntimeVirtualTextureSample, -700, 0)
    rs.set_editor_property('virtual_texture', rvt)
    rs.set_editor_property('material_type', rvt.get_editor_property('material_type'))
    rs.set_editor_property('single_physical_space', rvt.get_editor_property('single_physical_space'))
    lc = add(unreal.MaterialExpressionLinearInterpolate, -200, -200)
    mel.connect_material_expressions(cin, '', lc, 'A')
    mel.connect_material_expressions(rs, 'BaseColor', lc, 'B')
    mel.connect_material_expressions(k, '', lc, 'Alpha')
    ao = add(unreal.MaterialExpressionLinearInterpolate, -200, 450)
    ao.set_editor_property('const_a', 0.8)
    ao.set_editor_property('const_b', 1.0)
    mel.connect_material_expressions(t, '', ao, 'Alpha')
    dark = add(unreal.MaterialExpressionMultiply, 0, -200)
    mel.connect_material_expressions(lc, '', dark, 'A')
    mel.connect_material_expressions(ao, '', dark, 'B')
    lr = add(unreal.MaterialExpressionLinearInterpolate, -200, 0)
    mel.connect_material_expressions(rin, '', lr, 'A')
    mel.connect_material_expressions(rs, 'Roughness', lr, 'B')
    mel.connect_material_expressions(k, '', lr, 'Alpha')
    oc = add(unreal.MaterialExpressionFunctionOutput, 200, -200)
    oc.set_editor_property('output_name', 'Colour')
    mel.connect_material_expressions(dark, '', oc, '')
    orr = add(unreal.MaterialExpressionFunctionOutput, 200, 0)
    orr.set_editor_property('output_name', 'Roughness')
    oc.set_editor_property('sort_priority', 0)
    orr.set_editor_property('sort_priority', 1)
    mel.connect_material_expressions(lr, '', orr, '')
    mel.update_material_function(f)
    print('MF saved=' + str(eal.save_loaded_asset(f, False)))

if MODE == 'copy':
    path = DEST + '/' + DST
    m = unreal.load_asset(path)
    if m is None:
        m = eal.duplicate_asset(SRC, path)
    fn = unreal.load_asset(MF)
    if m.get_editor_property('use_material_attributes'):
        att = mel.get_material_property_input_node(m, MP.MP_MATERIAL_ATTRIBUTES)
        atto = mel.get_material_property_input_node_output_name(m, MP.MP_MATERIAL_ATTRIBUTES)
        if att is not None and att.get_class().get_name() == 'MaterialExpressionMakeMaterialAttributes' and att.get_editor_property('desc') == 'GroundBlend':
            print('already blended: ' + path)
        else:
            brk = mel.create_material_expression(m, unreal.MaterialExpressionBreakMaterialAttributes, 200, -400)
            mel.connect_material_expressions(att, atto, brk, '')
            mk = mel.create_material_expression(m, unreal.MaterialExpressionMakeMaterialAttributes, 700, -400)
            mk.set_editor_property('desc', 'GroundBlend')
            names = ['BaseColor', 'Metallic', 'Specular', 'Roughness', 'Anisotropy', 'EmissiveColor', 'Opacity', 'OpacityMask',
                     'Normal', 'Tangent', 'WorldPositionOffset', 'SubsurfaceColor', 'ClearCoat', 'ClearCoatRoughness',
                     'AmbientOcclusion', 'Refraction', 'PixelDepthOffset', 'ShadingModel', 'Displacement',
                     'CustomizedUV0', 'CustomizedUV1', 'CustomizedUV2', 'CustomizedUV3']
            links = []
            for n in names:
                if n in ['BaseColor', 'Roughness']:
                    continue
                links.append(n + '=' + str(mel.connect_material_expressions(brk, n, mk, n)))
            call = mel.create_material_expression(m, unreal.MaterialExpressionMaterialFunctionCall, 450, -200)
            call.set_material_function(fn)
            rp = mel.create_material_expression(m, unreal.MaterialExpressionScalarParameter, 250, 0)
            rp.set_editor_property('parameter_name', 'GroundBlendRoot')
            rp.set_editor_property('default_value', ROOT)
            tp = mel.create_material_expression(m, unreal.MaterialExpressionScalarParameter, 250, 100)
            tp.set_editor_property('parameter_name', 'GroundBlendTip')
            tp.set_editor_property('default_value', TIP)
            ok = [mel.connect_material_expressions(brk, 'BaseColor', call, 'Colour'), mel.connect_material_expressions(brk, 'Roughness', call, 'Roughness'),
                  mel.connect_material_expressions(rp, '', call, 'Root'), mel.connect_material_expressions(tp, '', call, 'Tip'),
                  mel.connect_material_expressions(call, 'Colour', mk, 'BaseColor'), mel.connect_material_expressions(call, 'Roughness', mk, 'Roughness'),
                  mel.connect_material_property(mk, '', MP.MP_MATERIAL_ATTRIBUTES)]
            print('attr links ' + str(ok) + ' ' + ' '.join(links))
        m.set_editor_property('used_with_instanced_static_meshes', True)
        mel.recompile_material(m)
        print('COPY ' + path + ' saved=' + str(eal.save_loaded_asset(m, False)))
    bc = mel.get_material_property_input_node(m, MP.MP_BASE_COLOR) if not m.get_editor_property('use_material_attributes') else None
    bco = mel.get_material_property_input_node_output_name(m, MP.MP_BASE_COLOR)
    ro = mel.get_material_property_input_node(m, MP.MP_ROUGHNESS)
    roo = mel.get_material_property_input_node_output_name(m, MP.MP_ROUGHNESS) if ro else ''
    if m.get_editor_property('use_material_attributes'):
        pass
    elif bc is not None and bc.get_class().get_name() == 'MaterialExpressionMaterialFunctionCall' and bc.get_editor_property('material_function') == fn:
        print('already blended: ' + path)
    else:
        call = mel.create_material_expression(m, unreal.MaterialExpressionMaterialFunctionCall, 300, 0)
        call.set_material_function(fn)
        rp = mel.create_material_expression(m, unreal.MaterialExpressionScalarParameter, 100, 300)
        rp.set_editor_property('parameter_name', 'GroundBlendRoot')
        rp.set_editor_property('default_value', ROOT)
        tp = mel.create_material_expression(m, unreal.MaterialExpressionScalarParameter, 100, 400)
        tp.set_editor_property('parameter_name', 'GroundBlendTip')
        tp.set_editor_property('default_value', TIP)
        ok = [mel.connect_material_expressions(bc, bco, call, 'Colour')]
        if ro is not None:
            ok.append(mel.connect_material_expressions(ro, roo, call, 'Roughness'))
        else:
            cr = mel.create_material_expression(m, unreal.MaterialExpressionConstant, 100, 200)
            cr.set_editor_property('r', 0.8)
            ok.append(mel.connect_material_expressions(cr, '', call, 'Roughness'))
        ok.append(mel.connect_material_expressions(rp, '', call, 'Root'))
        ok.append(mel.connect_material_expressions(tp, '', call, 'Tip'))
        ok.append(mel.connect_material_property(call, 'Colour', MP.MP_BASE_COLOR))
        ok.append(mel.connect_material_property(call, 'Roughness', MP.MP_ROUGHNESS))
        print('links ' + str(ok))
    if not m.get_editor_property('use_material_attributes'):
        m.set_editor_property('used_with_instanced_static_meshes', True)
        mel.recompile_material(m)
        print('COPY ' + path + ' saved=' + str(eal.save_loaded_asset(m, False)))

if MODE == 'reparent':
    # MI_Saskarta_X -> third-party MIs (carrying the textures) -> third-party master.
    # Every third-party MI in the chain is duplicated to DEST/<name>_GB (its overrides come along) and the
    # copies are chained the same way, ending at the blended master copy DST. Nothing of the pack is
    # edited and no override is dropped.
    m = unreal.load_asset(DEST + '/' + DST)
    def gb(par):
        if isinstance(par, unreal.Material):
            return m
        if par.get_name().endswith('_GB'):
            return par
        gp = DEST + '/' + par.get_name() + '_GB'
        dup = unreal.load_asset(gp)
        if dup is None:
            dup = eal.duplicate_asset(par.get_path_name().split('.')[0], gp)
        mel.set_material_instance_parent(dup, gb(par.get_editor_property('parent')))
        mel.update_material_instance(dup)
        eal.save_loaded_asset(dup, False)
        return dup
    for p in MIS:
        mi = unreal.load_asset(p)
        mel.set_material_instance_parent(mi, gb(mi.get_editor_property('parent')))
        mel.update_material_instance(mi)
        chain = []
        q = mi.get_editor_property('parent')
        while q is not None:
            chain.append(q.get_name())
            q = q.get_editor_property('parent') if isinstance(q, unreal.MaterialInstance) else None
        print('MI ' + mi.get_name() + ' -> ' + ' > '.join(chain))
