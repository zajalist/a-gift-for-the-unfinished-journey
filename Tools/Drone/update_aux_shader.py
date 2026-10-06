"""Write a guarded editor packet that refreshes only the auxiliary shader code."""
from pathlib import Path

root = Path(__file__).resolve().parents[2]
shader = (root / 'Shaders/AuxSensors.hlsl').read_text(encoding='utf-8')
packet = '''import unreal
es = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
assert es.get_game_world() is None
path = '/Game/SaskartaGaea/Look/AuxSensors/M_PP_AuxSensors'
mat = unreal.load_asset(path)
assert mat is not None and mat.get_class().get_name() == 'Material'
mel = unreal.MaterialEditingLibrary
nodes = [n for n in mel.get_material_expressions(mat) if n.get_class() == unreal.MaterialExpressionCustom.static_class()]
assert len(nodes) == 1
cu = nodes[0]
assert 'frontLine' in cu.get_editor_property('code')
cu.modify()
cu.set_editor_property('code', __HLSL__, unreal.PropertyAccessChangeNotifyMode.NEVER)
errors = mel.recompile_material(mat)
print('AUX_SHADER_COMPILE', len(errors))
assert len(errors) == 0
mat.modify()
print('AUX_SHADER_SAVE', unreal.EditorLoadingAndSavingUtils.save_packages([mat.get_package()], True))
'''
packet = packet.replace('__HLSL__', repr(shader))
out = root / 'Saved/Verification/point_cloud_audit_20261002/update_aux_shader_editor.py'
out.write_text(packet, encoding='utf-8')
print(out)
