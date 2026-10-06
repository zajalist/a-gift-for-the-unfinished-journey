# python_run (Hayba), LANE5: fill WBP_Saskarta_KeyPrompt's Preload array (class default) with every Light keycap,
# so the icons load with the widget class and Refresh's by-path lookup never loads synchronously during play.
import unreal
eal = unreal.EditorAssetLibrary
P = '/Game/SaskartaGaea/GameFlow/UI/WBP_Saskarta_KeyPrompt'
tex = [eal.load_asset(str(a).split('.')[0]) for a in eal.list_assets('/Game/SaskartaGaea/UI/Prompts/Light', False, False)]
d = unreal.get_default_object(unreal.load_object(None, P + '.WBP_Saskarta_KeyPrompt_C'))
d.set_editor_property('preload', [t for t in tex if t is not None])
bp = unreal.load_asset(P)
unreal.BlueprintEditorLibrary.compile_blueprint(bp)
d = unreal.get_default_object(unreal.load_object(None, P + '.WBP_Saskarta_KeyPrompt_C'))
print('preload', str(len(d.get_editor_property('preload'))), str(bp.get_editor_property('status')))
print('saved', str(eal.save_asset(P, False)))
