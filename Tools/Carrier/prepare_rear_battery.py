"""Emit narrowly scoped editor scripts; this host tool never connects to Unreal.

Root must verify Biofuel01Assembly SCS AttachToName=capsule_root before placement.
The known socket has scale100. Only root executes these scripts under its lease.
"""
from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MATERIAL = "/Game/SaskartaGaea/Characters/Carrier/Biofuel/Materials/M_Biofuel_ChargeIndicator"
MOUNT_LOCATION = (0.0, 2.1148, 1.32)
MOUNT_SCALE = 0.01
ROOF_SLOPE = 0.0
# V12 front shoulder fit:190cm closer,1.0worldscale, level battery on short steel
# supports. Source geometry/LOS packet is front_mount_v12; rendered acceptance pending.
RACK_PARTS = (('BiofuelRearRackPost1', 'Cylinder', (-135.0, -8.0, 91.95726173901453), (0.05, 0.05, 0.15585476521970945), (0.0, 0.0, 0.0)), ('BiofuelRearRackFoot1', 'Cube', (-135.0, -8.0, 82.29122375055455), (0.06, 0.06, 0.024), {'forward': [1.0, 0.0, -1.4765631915619462], 'right': [0.0, 1.0, -0.31588472421369335]}), ('BiofuelRearRackPost2', 'Cylinder', (-135.0, 8.0, 91.86296430275252), (0.05, 0.05, 0.15774071394494982), (0.0, 0.0, 0.0)), ('BiofuelRearRackFoot2', 'Cube', (-135.0, 8.0, 82.0848788034122), (0.06, 0.06, 0.024), {'forward': [1.0, 0.0, -1.4947531037682396], 'right': [0.0, 1.0, 0.3154870395815929]}), ('BiofuelRearRackPlatform', 'Cube', (-145.0, 0.0, 100.75), (0.32, 0.48, 0.025), (0.0, 0.0, 0.0)))

RACK_HELPER = '''
def ensure_rear_battery_rack(bp):
    sub = unreal.get_engine_subsystem(unreal.SubobjectDataSubsystem)
    lib = unreal.SubobjectDataBlueprintFunctionLibrary
    def named_components(asset):
        result = {}
        for handle in sub.k2_gather_subobject_data_for_blueprint(asset):
            data = lib.get_data(handle)
            name = str(lib.get_variable_name(data))
            obj = lib.get_object(data)
            if obj is None:
                continue
            prior = result.get(name)
            if prior is not None and prior[1].get_path_name() != obj.get_path_name():
                raise RuntimeError('Duplicate battery rack component ' + name)
            result[name] = (handle, obj)
        return result
    named = named_components(bp)
    root_pair = named.get('CapsuleComponent')
    if root_pair is None or not isinstance(root_pair[1], unreal.CapsuleComponent):
        raise RuntimeError('Expected the carrier actual CapsuleComponent; no rack parent guessed')
    assembly = unreal.load_asset('/Game/SaskartaGaea/Characters/Carrier/Biofuel/Assemblies/BP_Biofuel01_Assembly')
    if assembly is None:
        raise RuntimeError('Missing intact battery assembly')
    support_part = named_components(assembly).get('Biofuel01_Mount')
    support_material = support_part[1].get_material(0) if support_part else None
    if support_material is None:
        raise RuntimeError('Missing existing biofuel steel support material')
    placements = __RACK_PARTS__
    for name, shape, loc, scale, rot in placements:
        pair = named.get(name)
        if pair is None:
            added = sub.add_new_subobject(unreal.AddNewSubobjectParams(
                parent_handle=root_pair[0], new_class=unreal.StaticMeshComponent, blueprint_context=bp))
            handle = added[0] if isinstance(added, tuple) else added
            if not sub.rename_subobject(handle, unreal.Text(name)):
                raise RuntimeError('Could not name battery rack component ' + name)
            named = named_components(bp)
            pair = named.get(name)
        if pair is None or not isinstance(pair[1], unreal.StaticMeshComponent):
            raise RuntimeError('Unexpected battery rack component class ' + name)
        mesh = unreal.load_asset('/Engine/BasicShapes/' + shape)
        if mesh is None:
            raise RuntimeError('Missing rack primitive ' + shape)
        obj = pair[1]
        obj.set_static_mesh(mesh)
        obj.set_material(0, support_material)
        obj.set_editor_property('cast_shadow', True)
        obj.set_editor_property('visible', True)
        obj.set_editor_property('hidden_in_game', False)
        obj.set_collision_profile_name('NoCollision')
    # Existing parts may actually attach to Biofuel01Assembly after SCS reconstruction.
    # Resolve that actual parent, rather than assuming the requested creation parent persisted.
    unreal.BlueprintEditorLibrary.compile_blueprint(bp)
    actors = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    preview = actors.spawn_actor_from_class(bp.generated_class(), unreal.Vector(0., 0., 0.),
        unreal.Rotator(0., 0., 0.), transient=True)
    if preview is None:
        raise RuntimeError('Could not create owned battery rack transform preview')
    # An SCS property change reconstructs its preview and invalidates cached components.
    # Calculate all five value transforms before touching any SCS template.
    components = preview.get_components_by_class(unreal.SceneComponent)
    relative_poses = []
    for name, shape, loc, scale, rot in placements:
        matches = [c for c in components if c.get_name() == name or c.get_name().startswith(name + '_')]
        if len(matches) != 1:
            actors.destroy_actor(preview)
            raise RuntimeError('Expected one actual rack component ' + name)
        parent = matches[0].get_attach_parent()
        if parent is None:
            actors.destroy_actor(preview)
            raise RuntimeError('Rack component has no actual parent ' + name)
        desired = unreal.Transform()
        desired.translation = unreal.Vector(*loc)
        if isinstance(rot, dict):
            desired.rotation = unreal.MathLibrary.make_rot_from_xy(
                unreal.Vector(*rot['forward']), unreal.Vector(*rot['right'])).quaternion()
        else:
            desired.rotation = unreal.Rotator(*rot).quaternion()
        desired.scale3d = unreal.Vector(*scale)
        relative_poses.append((name, unreal.MathLibrary.make_relative_transform(desired, parent.get_world_transform())))
    if not actors.destroy_actor(preview):
        raise RuntimeError('Could not remove owned battery rack transform preview')
    named = named_components(bp)
    for name, relative in relative_poses:
        obj = named[name][1]
        obj.set_editor_property('relative_location', relative.translation)
        obj.set_editor_property('relative_rotation', relative.rotation.rotator())
        obj.set_editor_property('relative_scale3d', relative.scale3d)
    print('BATTERY_RACK_CONFIGURED components=5 material=' + support_material.get_path_name())
'''


def rack_editor_script() -> str:
    """Emit the shared rack helper; never connect to an editor on the host."""
    return RACK_HELPER.replace('__RACK_PARTS__', repr(RACK_PARTS))

COMMON = '''import unreal
eal = unreal.EditorAssetLibrary
sub = unreal.get_engine_subsystem(unreal.SubobjectDataSubsystem)
lib = unreal.SubobjectDataBlueprintFunctionLibrary
if unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world() is not None:
    raise RuntimeError('Stop PIE before changing battery assets')
def component(bp, name):
    found = {}
    for handle in sub.k2_gather_subobject_data_for_blueprint(bp):
        data = lib.get_data(handle)
        if str(lib.get_variable_name(data)) == name:
            obj = lib.get_object(data)
            found[obj.get_path_name()] = obj
    if len(found) != 1:
        raise RuntimeError('Expected one ' + name + ', got ' + str(len(found)))
    return list(found.values())[0]
'''

PLACEMENT = COMMON + '__RACK_HELPER__' + '''
bp = eal.load_asset('/Game/SaskartaGaea/Characters/Carrier/BP_Saskarta_Carrier')
if bp is None:
    raise RuntimeError('Missing carrier Blueprint')
mount = component(bp, 'Biofuel01Assembly')
child = mount.get_editor_property('child_actor_class')
if child is None or child.get_name() != 'BP_Biofuel01_Assembly_C':
    raise RuntimeError('Unexpected battery child actor class')
scale = mount.get_editor_property('relative_scale3d')
if not any(all(abs(value - allowed) <= .00015 for value in (scale.x, scale.y, scale.z)) for allowed in (.0075, __SCALE__)):
    raise RuntimeError('Socket-scale precondition changed; remeasure before applying')
old = mount.get_editor_property('relative_location')
known = [(0., 1.312, 1.35), (0., .2148, 1.1069), (0., .214797, 1.5953039), __LOCATION__]
if not any(max(abs(value - expected) for value, expected in zip((old.x, old.y, old.z), pose)) < .002 for pose in known):
    raise RuntimeError('Mount changed since measurement; preserve it and remeasure')
# The user now wants the real module closer to the front. The fitted front shoulder
# rack supports a level1.0-scale module at actor(-145,0,102); its56lamp-bound corners
# clear the pod for measured/nominal driver positions in the offline geometry packet.
mount.set_editor_property('relative_scale3d', unreal.Vector(__SCALE__, __SCALE__, __SCALE__))
mount.set_editor_property('relative_location', unreal.Vector(*__LOCATION__))
mount.set_editor_property('relative_rotation', unreal.MathLibrary.make_rot_from_xy(
    unreal.Vector(1., 0., 0.), unreal.Vector(0., 1., __SLOPE__)))
ensure_rear_battery_rack(bp)
unreal.BlueprintEditorLibrary.compile_blueprint(bp)
if not eal.save_loaded_asset(bp, False):
    raise RuntimeError('Carrier mount save failed')
print('BATTERY_REAR_TIP saved=True location=' + str(mount.get_editor_property('relative_location')) +
      ' rotation=' + str(mount.get_editor_property('relative_rotation')))
'''

INDICATOR = COMMON + '''
path = '__MATERIAL__'
mat = eal.load_asset(path)
mel = unreal.MaterialEditingLibrary
rebuild = mat is None
# Resume the first interrupted creation only: the observed incomplete graph
# contains exactly ChargeFill and a Clamp, with no saved output connections.
if isinstance(mat, unreal.Material) and mel.get_num_material_expressions(mat) == 2:
    existing = [str(name) for name in mel.get_scalar_parameter_names(mat)]
    if existing == ['ChargeFill']:
        mel.delete_all_material_expressions(mat)
        rebuild = True
if rebuild:
    folder, name = path.rsplit('/', 1)
    if not eal.does_directory_exist(folder):
        eal.make_directory(folder)
    if mat is None:
        mat = unreal.AssetToolsHelpers.get_asset_tools().create_asset(name, folder, unreal.Material, unreal.MaterialFactoryNew())
    if mat is None:
        raise RuntimeError('Could not create scoped indicator material')
    mat.set_editor_property('material_domain', unreal.MaterialDomain.MD_SURFACE)
    mat.set_editor_property('blend_mode', unreal.BlendMode.BLEND_OPAQUE)
    mat.set_editor_property('shading_model', unreal.MaterialShadingModel.MSM_DEFAULT_LIT)
    def node(cls, x, y):
        return mel.create_material_expression(mat, cls, x, y)
    def link(src, pin, dest, target):
        if not mel.connect_material_expressions(src, pin, dest, target):
            raise RuntimeError('Indicator material connection failed ' + target)
    def scalar(name, value, x, y):
        n = node(unreal.MaterialExpressionScalarParameter, x, y)
        n.set_editor_property('parameter_name', name)
        n.set_editor_property('default_value', value)
        return n
    fill = scalar('ChargeFill', 0., -650, 0)
    clamp = node(unreal.MaterialExpressionClamp, -420, 0)
    clamp.set_editor_property('min_default', 0.)
    clamp.set_editor_property('max_default', 1.)
    link(fill, '', clamp, '')
    color = node(unreal.MaterialExpressionVectorParameter, -650, 180)
    color.set_editor_property('parameter_name', 'ChargeColor')
    color.set_editor_property('default_value', unreal.LinearColor(.4, .9, .48, 1.))
    off = node(unreal.MaterialExpressionConstant3Vector, -650, -140)
    off.set_editor_property('constant', unreal.LinearColor(.012, .018, .013, 1.))
    base = node(unreal.MaterialExpressionLinearInterpolate, -140, -90)
    link(off, '', base, 'A')
    link(color, 'RGB', base, 'B')
    link(clamp, '', base, 'Alpha')
    lit = node(unreal.MaterialExpressionMultiply, -140, 160)
    link(color, 'RGB', lit, 'A')
    link(clamp, '', lit, 'B')
    glow = node(unreal.MaterialExpressionMultiply, 30, 160)
    link(lit, '', glow, 'A')
    link(scalar('ChargeGlow', 1.6, -300, 340), '', glow, 'B')
    rough = scalar('IndicatorRoughness', .45, 30, 360)
    for source, prop in [(base, unreal.MaterialProperty.MP_BASE_COLOR),
                         (glow, unreal.MaterialProperty.MP_EMISSIVE_COLOR),
                         (rough, unreal.MaterialProperty.MP_ROUGHNESS)]:
        if not mel.connect_material_property(source, '', prop):
            raise RuntimeError('Indicator material output connection failed')
    errors = mel.recompile_material(mat)
    if errors:
        raise RuntimeError('Indicator material compile errors: ' + str(errors))
    if not eal.save_loaded_asset(mat, False):
        raise RuntimeError('Indicator material save failed')
elif not isinstance(mat, unreal.Material):
    raise RuntimeError('Expected our material at scoped path')
names = [str(name) for name in mel.get_scalar_parameter_names(mat)]
if 'ChargeFill' not in names or 'ChargeGlow' not in names:
    raise RuntimeError('Existing material does not satisfy indicator contract; not overwritten')
bp = eal.load_asset('/Game/SaskartaGaea/Characters/Carrier/Biofuel/Assemblies/BP_Biofuel01_Assembly')
if bp is None:
    raise RuntimeError('Missing intact battery assembly')
for index in range(1, 8):
    part = component(bp, 'Biofuel01_Charge' + str(index).zfill(2))
    part.set_material(0, mat)
unreal.BlueprintEditorLibrary.compile_blueprint(bp)
if not eal.save_loaded_asset(bp, False):
    raise RuntimeError('Indicator assembly save failed')
print('BATTERY_INDICATOR saved=True material=' + path + ' parameter=ChargeFill segments=7')
'''


def scripts() -> dict[str, str]:
    return {
        'placement': PLACEMENT.replace('__LOCATION__', repr(MOUNT_LOCATION)).replace('__SLOPE__', repr(ROOF_SLOPE)).replace('__SCALE__', repr(MOUNT_SCALE)).replace('__RACK_HELPER__', rack_editor_script()),
        'indicator': INDICATOR.replace('__MATERIAL__', MATERIAL),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--write', action='store_true', help='Write scripts under Saved; never execute them')
    args = parser.parse_args()
    output = ROOT / 'Saved/BiofuelRearTip'
    for name, script in scripts().items():
        compile(script, name, 'exec')
        if args.write:
            output.mkdir(parents=True, exist_ok=True)
            file = output / (name + '.py')
            file.write_text(script, encoding='utf-8')
            print(file)
        else:
            print(name + ': parsed, ' + str(len(script)) + ' bytes; use --write to stage')


if __name__ == '__main__':
    main()
