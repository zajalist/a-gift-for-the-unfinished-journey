"""Scoped editor bridge script: extend visible Loading to 12 seconds.

Run only after the 4K capture, with PIE stopped. The current saved value must
still be 8 seconds; this script does not modify intro card or timeout timing.
"""
import unreal

editor = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
assert editor.get_game_world() is None, "Stop PIE before editing the loading hold"
path = "/Game/SaskartaGaea/GameFlow/PC_Saskarta"
bp = unreal.load_asset(path)
assert isinstance(bp, unreal.Blueprint)
cdo = unreal.get_default_object(bp.generated_class())
before = float(cdo.get_editor_property("LoadMinShown"))
assert abs(before - 8.0) < 0.001, f"Unexpected existing hold: {before}"

bp.modify()
cdo.modify()
cdo.set_editor_property("LoadMinShown", 12.0)
unreal.BlueprintEditorLibrary.compile_blueprint(bp)
assert bp.get_editor_property("status") == unreal.BlueprintStatus.BS_UP_TO_DATE
after = float(unreal.get_default_object(bp.generated_class()).get_editor_property("LoadMinShown"))
assert abs(after - 12.0) < 0.001, f"Hold did not survive compile: {after}"
assert unreal.EditorAssetLibrary.save_loaded_asset(bp, False) is True
print(f"LOADING_HOLD_SAVED old={before} new={after}")
