"""Tests for Tools/Look/apply_look.py's editor scripts (FOG3).

Every key's apply script and the --save script must pass python_run's banned-word check, carry the
level-only fog values the director does not blend (second-layer falloff, max opacity), and --save must
name exactly the lighting actors an apply touches.

Run: python -m pytest Tools/Look/tests -q -p no:cacheprovider --basetemp <scratch dir>
"""
import pathlib
import sys

LOOK = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LOOK))

import apply_look as al  # noqa: E402


def test_every_key_applies_through_python_run():
    for k in al.load_keys():
        script = al.check_banned(al.apply_script(k))
        assert repr(k["fog"]["second_falloff"]) in script and repr(k["fog"]["max_opacity"]) in script, k["name"]


def test_road_blend_keeps_the_level_only_fields():
    k = al.blend_keys(al.load_keys(), 2300.0)
    assert k["fog"]["second_falloff"] == al.SECOND_FOG_FALLOFF and k["fog"]["max_opacity"] == al.FOG_MAX_OPACITY


def test_save_script_saves_only_what_an_apply_touches():
    script = al.check_banned(al.save_script())
    for label in ("DirectionalLight", "SkyAtmosphere", "VolumetricCloud", "ExponentialHeightFog", "SkyLight",
                  al.PPV_STORM, al.PPV_CLEAR):
        assert repr(label) in script
    assert al.MPC_PATH in script and al.CLOUD_MI_PATH in script
    assert "save_packages(pk, True)" in script  # dirty packages only


def test_volumetric_ab_range_is_short():
    assert al.VOLUMETRIC_FOG_ENABLED is False
    assert al.VOLUMETRIC_FOG_START_CM < al.VOLUMETRIC_FOG_DISTANCE_CM <= 6000.0


class _FakeStruct:
    def __init__(self, props):
        self.props = props

    def get_editor_property(self, name):
        return self.props[name]

    def get_package(self):
        return self


class _FakeUnreal:
    """Just enough of the unreal module for the --save script: the DA's keys, the level actors, the save."""

    def __init__(self, da_keys):
        self.da = _FakeStruct({"keys": [_FakeStruct(k) for k in da_keys]})
        self.saved = None
        outer = self

        class _Pkg:
            pass

        class _Actor:
            def __init__(self, label):
                self.label = label

            def get_actor_label(self):
                return self.label

            def get_package(self):
                return _Pkg()

        class _Subsystem:
            def get_all_level_actors(self):
                return [_Actor(label) for label in al.SAVE_LABELS]

        class _Saving:
            @staticmethod
            def save_packages(pk, dirty_only):
                outer.saved = len(pk)
                return True

        self.EditorActorSubsystem = object
        self.EditorLoadingAndSavingUtils = _Saving
        self._subsystem = _Subsystem()

    def get_editor_subsystem(self, _cls):
        return self._subsystem

    def load_asset(self, path):
        return self.da if path == al.LOOK_KEYS_DA_PATH else _FakeStruct({})


def _da_keys(keys):
    return [{"name": k["name"], **{field: k["fog"][n] for field, n in al.SAVE_DA_FIELDS.items()}} for k in keys]


def _run_save(monkeypatch, capsys, da_keys):
    fake = _FakeUnreal(da_keys)
    monkeypatch.setitem(sys.modules, "unreal", fake)
    exec(al.check_banned(al.save_script(al.load_keys())), {})
    return fake, capsys.readouterr().out


def test_save_refuses_while_the_da_holds_other_fog(monkeypatch, capsys):
    """FOG3 fix round 1 (verifier): a level saved while DA_Saskarta_LookKeys still holds Fog 2 puts every key on
    the 0.2 floor by 300 m. The --save script checks the DA first and saves nothing if it differs."""
    import copy
    stale = copy.deepcopy(al.load_keys())
    stale[3]["fog"]["second_density"] *= 2.0
    fake, out = _run_save(monkeypatch, capsys, _da_keys(stale))
    assert fake.saved is None and "NOT SAVED" in out and "BasinPeak.fog_second_density" in out


def test_save_goes_ahead_once_the_da_matches(monkeypatch, capsys):
    fake, out = _run_save(monkeypatch, capsys, _da_keys(al.load_keys()))
    assert fake.saved == len(al.SAVE_LABELS) + 2 and "NOT SAVED" not in out, out
