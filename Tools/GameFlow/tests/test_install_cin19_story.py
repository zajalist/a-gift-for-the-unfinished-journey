"""Offline Story packet checks; the editor boundary is a small fake Unreal module."""
import json
from pathlib import Path
import shutil
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'editor'))
import install_cin19_story as install


def packet(tmp_path):
    for name in install.INPUTS:
        source = install.ROOT / name
        if source.is_file():
            target = tmp_path / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
    directory = tmp_path / 'prepared/cin19_story'
    install.prepare(directory, tmp_path)
    return directory


def test_packet_pins_every_importer_input_and_script(tmp_path):
    directory = packet(tmp_path)
    plan = install.check(directory, tmp_path)
    assert plan['groups'][0]['steps'] == ['00_apply.py', '90_save.py', '99_read.py']
    assert len(plan['input_sha256']) == len(install.INPUTS)
    path = tmp_path / 'docs/story/caption-pages.json'
    path.write_text('{}', encoding='utf-8')
    with pytest.raises(ValueError, match='Importer input changed'):
        install.check(directory, tmp_path)


def test_packet_rejects_modified_script_and_extra_script(tmp_path):
    directory = packet(tmp_path)
    script = directory / '99_read.py'
    old = script.read_bytes()
    script.write_bytes(old + b'\n# changed\n')
    with pytest.raises(ValueError, match='hash changed'):
        install.check(directory, tmp_path)
    script.write_bytes(old)
    (directory / 'unexpected.py').write_text('pass', encoding='utf-8')
    with pytest.raises(ValueError, match='filenames'):
        install.check(directory, tmp_path)


class Properties:
    def __init__(self, **values):
        self.values = values

    def get_editor_property(self, name):
        return self.values[name]


def test_generated_import_save_and_full_readback_fail_closed(monkeypatch):
    cine = json.loads((install.ROOT / install.INPUTS[0]).read_text(encoding='utf-8'))['cinematics']['CIN_19_HATCH']
    code = install.scripts(cine)
    names = {q['type'] for q in cine['cues'] + cine['final_state']}
    import re
    enum = SimpleNamespace(**{re.sub(r'(?<!^)(?=[A-Z])', '_', name).upper(): name for name in names})
    def action(q):
        return Properties(type=q['type'], id=q.get('id', 'None'), at_s=q.get('at_s', -1),
                          duration_s=q.get('duration_s', 0), after_prompt=q.get('after_prompt', False))
    c = Properties(id='CIN_19_HATCH', duration_s=36, cues=[action(q) for q in cine['cues']],
                   final_state=[action(q) for q in cine['final_state']])
    asset = Properties(cinematics=[c])
    unreal = SimpleNamespace(load_asset=lambda _: asset, SaskartaActionType=enum,
                             Paths=SimpleNamespace(project_dir=lambda: 'root'),
                             SaskartaStoryImport=SimpleNamespace(import_story_from_files=lambda *_: 'beats 1, problems 0'),
                             EditorAssetLibrary=SimpleNamespace(save_loaded_asset=lambda *_: True))
    monkeypatch.setitem(sys.modules, 'unreal', unreal)
    for script in code.values():
        exec(script, {})
    unreal.SaskartaStoryImport.import_story_from_files = lambda *_: 'beats 1, problems 1'
    with pytest.raises(AssertionError, match='problems'):
        exec(code['00_apply.py'], {})
    unreal.EditorAssetLibrary.save_loaded_asset = lambda *_: False
    with pytest.raises(AssertionError, match='save'):
        exec(code['90_save.py'], {})
    c.values['cues'][0].values['at_s'] = 99
    with pytest.raises(AssertionError):
        exec(code['99_read.py'], {})
