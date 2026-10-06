from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import prepare_dawn_capture_ab as ab
import prepare_dawn_landscape_fallback as fallback
import prepare_dawn_body_visibility_fix as body_fix


def test_comparisons_do_not_read_private_hidden_components_or_change_world_visibility():
    for module in (ab,fallback):
        source=Path(module.__file__).read_text()
        assert "get_editor_property('hidden_components')" not in source
        assert 'set_actor_hidden_in_game' not in source
        assert 'set_visibility(' not in source
        assert 'execute_console_command' not in source
        assert 'save_asset' not in source
    assert 'c.clear_hidden_components();c.hide_component(found[0])' in Path(ab.__file__).read_text()
    assert 'DawnCaptureHidden:' in Path(ab.__file__).read_text()


def test_fallback_is_a_reversible_capture_view_setting(tmp_path):
    out=tmp_path/'fallback';fallback.prepare(out)
    switch=(out/'00_fallback.py').read_text()
    restore=(out/'90_restore.py').read_text()
    assert "show_flag_name='NaniteMeshes',enabled=False" in switch
    assert switch.index("cap.set_editor_property('tags',tags+[receipt])") < switch.index("c.set_editor_property('show_flag_settings',settings)")
    assert 'previous=json.loads(receipts[0])' in restore
    for script in out.glob('*.py'):compile(script.read_text(),str(script),'exec')


def test_body_visibility_recovery_is_owned_and_restorable(tmp_path):
    out=tmp_path/'body_fix';body_fix.prepare(out)
    begin=(out/'00_enable_body.py').read_text()
    restore=(out/'90_restore.py').read_text()
    assert begin.index("cap.set_editor_property('tags',tags+[receipt])") < begin.index("body.set_editor_property('is_editor_only_actor',False)")
    assert "body.set_editor_property('is_editor_only_actor',previous['editor_only'])" in restore
    assert 'mesh.set_visibility(False,False);mesh.set_visibility(True,False)' in begin
    assert 'mesh.set_visibility(False,False);mesh.set_visibility(True,False)' in restore
    assert 'previous[\'flags\']' in restore and 'c.clear_hidden_components()' in restore
    for script in out.glob('*.py'):
        code=script.read_text();compile(code,str(script),'exec')
        assert not any(word in code for word in ('execute_console_command','save_asset','save_packages',"get_editor_property('hidden_components')"))
