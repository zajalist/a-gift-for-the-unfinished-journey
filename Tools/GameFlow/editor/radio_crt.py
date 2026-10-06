# Run with ending_editor.py run-file while PIE is stopped, before the radio tree build.
# The radio shares the boot terminal's phosphor shader through its own restrained MI.
import unreal

folder = '/Game/SaskartaGaea/GameFlow/Materials'
path = folder + '/MI_UI_RadioCRT'
eal = unreal.EditorAssetLibrary
mel = unreal.MaterialEditingLibrary
parent = unreal.load_asset(folder + '/M_UI_CRTTerminal')
if not isinstance(parent, unreal.Material):
    raise RuntimeError('M_UI_CRTTerminal must exist before building the radio effect')
mi = unreal.load_asset(path) if eal.does_asset_exist(path) else unreal.AssetToolsHelpers.get_asset_tools().create_asset(
    'MI_UI_RadioCRT', folder, unreal.MaterialInstanceConstant, unreal.MaterialInstanceConstantFactoryNew())
mel.set_material_instance_parent(mi, parent)
mel.update_material_instance(mi)
# The shader uses a 1080-line reference. RadioScreen is 92 px high at 1080p,
# so 12 reference pixels give approximately one output pixel of phosphor halo.
values = {'Brightness': 1.05, 'GlowStrength': 0.16, 'GlowRadius': 12.0,
          'ScanlineCount': 46.0, 'ScanlineDepth': 0.12, 'Curvature': 0.0,
          'Vignette': 0.0, 'FlickerDepth': 0.0, 'RollSpeed': 0.0, 'RollGain': 0.0,
          'JitterChance': 0.0, 'JitterPx': 0.0, 'RasterGlow': 0.0}
for name, value in values.items():
    # UE 5.8's setter leaves its bool result false even after a successful write.
    # Compare the actual value instead of treating that return as a save receipt.
    changed = mel.set_material_instance_scalar_parameter_value(mi, name, value)
    if abs(mel.get_material_instance_scalar_parameter_value(mi, name) - value) > 0.0001:
        print('RADIO_CRT failed parameter=' + name + ' changed=' + str(changed))
        raise RuntimeError('missing radio CRT parameter ' + name)
mel.set_material_instance_vector_parameter_value(mi, 'PhosphorColor', unreal.LinearColor(0.9, 0.58, 0.28, 1.0))
mel.update_material_instance(mi)
print('RADIO_CRT parent=' + mi.get_editor_property('parent').get_path_name())
print('RADIO_CRT scalars=' + str({name: mel.get_material_instance_scalar_parameter_value(mi, name) for name in values}))
print('RADIO_CRT saved=' + str(eal.save_loaded_asset(mi, False)))
