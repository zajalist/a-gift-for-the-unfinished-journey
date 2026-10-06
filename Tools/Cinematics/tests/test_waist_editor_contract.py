"""Regression contracts from the actual UE5.8 staged import/readback."""
from pathlib import Path
import sys
import ast
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import prepare_waist_reimport as stage
import prepare_waist_production as production


def test_import_uses_observed_python_wrappers_and_retains_narrow_weights_mode():
    assert 'owner=unreal.DynamicMesh()' in stage.COMMON
    assert 'get_transient_package' not in stage.COMMON
    assert 'ok,imported=' not in stage.COMMON
    assert 'imported=manager.import_asset' in stage.COMMON
    assert 'last_skeletal_mesh_import_content_type' not in stage.COMMON
    assert 'params.reimport_source_index=2' in stage.COMMON
    assert "s.get_editor_property('material_slot_name')" in stage.COMMON
    assert "set_editor_property('update_skeleton_reference_pose',False)" in stage.COMMON


def test_verification_and_save_have_no_filesystem_writes_or_import_calls():
    for code in (stage.VERIFY,production.VERIFY,production.SAVE):
        tree=ast.parse(code)
        methods={x.func.attr for x in ast.walk(tree) if isinstance(x,ast.Call) and isinstance(x.func,ast.Attribute)}
        assert not methods&{'write_text','write_bytes','import_asset','duplicate_asset'}
    assert 'same_surface(original,review,True)' in production.SAVE
    assert 'save_asset(ORIGINAL' in production.SAVE
    assert 'expected_original_weights.json' in production.IMPORT
