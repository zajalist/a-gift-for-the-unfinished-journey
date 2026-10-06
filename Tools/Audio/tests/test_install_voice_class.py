"""Execute emitted chunks with a tiny Unreal adapter; no editor or assets are modified."""
import sys
import json
from types import SimpleNamespace

import pytest

import install_voice_class as install


class Asset:
    def __init__(self, path, **properties):
        self.path = path
        self.properties = properties

    def get_path_name(self):
        return self.path + '.' + self.path.rsplit('/', 1)[-1]

    def get_editor_property(self, name):
        return self.properties.get(name)

    def set_editor_property(self, name, value):
        self.properties[name] = value


class SoundClass(Asset):
    pass


class SoundBase(Asset):
    pass


@pytest.fixture
def editor(monkeypatch):
    assets = {install.CLASS: SoundClass(install.CLASS)}
    saved = []
    def save(asset, only_if_dirty):
        saved.append(asset.path)
        return True
    eal = SimpleNamespace(load_asset=assets.get, save_loaded_asset=save)
    monkeypatch.setitem(sys.modules, 'unreal', SimpleNamespace(
        EditorAssetLibrary=eal, SoundClass=SoundClass, SoundBase=SoundBase))
    return assets, saved, eal


def test_assignment_and_save_are_separate_and_verify_routing(editor):
    assets, saved, _ = editor
    path = '/Game/SaskartaGaea/Audio/Lines/SAMYOR_B24_01'
    wave = assets[path] = SoundBase(path)
    with pytest.raises(RuntimeError, match='routing missing'):
        exec(install.save_code([path]), {})
    assert saved == []
    exec(install.assignment_code([path]), {})
    assert wave.properties['sound_class_object'] is assets[install.CLASS]
    assert saved == []
    exec(install.save_code([path]), {})
    assert saved == [path]


def test_invalid_later_asset_does_not_partially_assign_batch(editor):
    assets, saved, _ = editor
    path = '/Game/SaskartaGaea/Audio/Lines/SAMYOR_B24_01'
    wave = assets[path] = SoundBase(path)
    with pytest.raises(RuntimeError, match='Expected voice SoundBase'):
        exec(install.assignment_code([path, '/Game/Missing']), {})
    assert wave.get_editor_property('sound_class_object') is None
    assert saved == []


def test_save_failure_stops_before_later_assets(editor):
    assets, saved, eal = editor
    paths = ['/Game/First', '/Game/Second']
    for path in paths:
        assets[path] = SoundBase(path, sound_class_object=assets[install.CLASS])
    def fail(asset, only_if_dirty):
        saved.append(asset.path)
        return False
    eal.save_loaded_asset = fail
    with pytest.raises(RuntimeError, match='save failed'):
        exec(install.save_code(paths), {})
    assert saved == paths[:1]


def test_class_edit_does_not_save_and_class_save_requires_root(editor):
    assets, saved, _ = editor
    assets[install.CLASS].properties['parent_class'] = Asset('/Engine/Master')
    with pytest.raises(RuntimeError, match='independent voice class'):
        exec(install.save_code([install.CLASS], sound_class=True), {})
    with pytest.raises(RuntimeError, match='already has a parent'):
        exec(install.class_code(), {})
    assert assets[install.CLASS].properties['parent_class'].path == '/Engine/Master'
    assets[install.CLASS].properties['parent_class'] = None
    exec(install.class_code(), {})
    assert saved == []
    exec(install.save_code([install.CLASS], sound_class=True), {})
    assert saved == [install.CLASS]


def test_emit_is_ordered_bounded_and_refuses_stale_chunks(tmp_path):
    paths = [f'/Game/Voice{i}' for i in range(41)]
    manifest = install.emit(tmp_path, paths)
    assert manifest['steps'] == sorted(manifest['steps'])
    assert len(manifest['steps']) == 8
    for name in manifest['steps']:
        compile((tmp_path / name).read_text(), name, 'exec')
    with pytest.raises(ValueError, match='old Python chunks'):
        install.emit(tmp_path, paths)
    with pytest.raises(ValueError):
        install.assignment_code(paths)


def test_voice_inventory_excludes_music_and_effects(tmp_path):
    base = tmp_path / 'Content/SaskartaGaea/Audio'
    names = ['Lines/BELOW_R01', 'CarrierVoice/VO_Carrier_INSCR_W01',
             'Station/Host/Recorded/VO_Station_SHOW_A1_01', 'Scan/VO_Scan',
             'Lines/SFX_Click', 'Station/Songs/SONG_A', 'Lines/SC_Other']
    for name in names:
        path = base / (name + '.uasset')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    actual = install.voice_assets(tmp_path)
    assert len(actual) == 4
    assert all('SFX_' not in path and '/Songs/' not in path and '/SC_' not in path for path in actual)


def test_verify_rejects_changed_script_even_if_hash_is_rewritten(tmp_path):
    out = tmp_path / 'plan'
    manifest = install.emit(out, [])
    assert install.verify(out, root=tmp_path) == manifest
    chunk = out / manifest['steps'][0]
    chunk.write_text(chunk.read_text() + "print('changed')\n", encoding='utf-8')
    manifest.update(install.fingerprints(out, manifest['steps']))
    (out / 'voice-manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    with pytest.raises(ValueError, match='differs from current generator'):
        install.verify(out, root=tmp_path)


def test_verify_rejects_new_voice_assets_and_stale_fingerprints(tmp_path):
    out = tmp_path / 'plan'
    manifest = install.emit(out, [])
    asset = tmp_path / 'Content/SaskartaGaea/Audio/Lines/BELOW_R01.uasset'
    asset.parent.mkdir(parents=True)
    asset.touch()
    with pytest.raises(ValueError, match='inventory changed'):
        install.verify(out, root=tmp_path)
    asset.unlink()
    manifest['generator_sha256'] = 'stale'
    (out / 'voice-manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    with pytest.raises(ValueError, match='Stale voice manifest fingerprint'):
        install.verify(out, root=tmp_path)
