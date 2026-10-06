"""Offline checks for the story runner's PlaySfx sounds (Tools/Audio/make_story_sfx.py). No editor, no network.

    python -m pytest Tools/Audio/tests/test_story_sfx.py -q
"""
import json
import pathlib
import sys

import numpy as np
import pytest

AUDIO = pathlib.Path(__file__).resolve().parents[1]
REPO = AUDIO.parents[1]
sys.path.insert(0, str(AUDIO))
import import_game_audio as iga  # noqa: E402
import make_story_sfx as mss  # noqa: E402

STORY = json.loads((REPO / "docs" / "story" / "story-events.json").read_text(encoding="utf-8"))


def play_sfx_ids():
    ids = set()

    def walk(o):
        if isinstance(o, dict):
            if o.get("type") == "PlaySfx" and o.get("id"):
                ids.add(o["id"])
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(STORY)
    return ids


# PlaySfx ids that have no sound yet (updated 2026-10-01). Remove an id
# here when its sound lands. The author's session takes: BREATH_*, FOLEY_* (CIN_19), CHORUS_B24 (CIN_24).
# B12/B13/CIN15 now reference existing authored one-shots. OpenChannelHiss / RelayClunk are installed.
# CIN_25 ValleyWindBed (AMB_Valley_Wind exists), CIN_B1 FlankHatchPop / RotorSpinUp (optional Drone).
PENDING = frozenset({
    "BREATH_01", "BREATH_02", "BREATH_04A", "BREATH_04B", "BREATH_04C", "BREATH_05", "BREATH_06", "CHORUS_B24", "FOLEY_01",
    "FOLEY_02", "SFX_FlankHatchPop", "SFX_RotorSpinUp", "SFX_ValleyWindBed",
})


def available():
    imported = {p.stem for p in (REPO / "Content" / "SaskartaGaea" / "Audio").rglob("*.uasset")}
    return imported | {name for _, _, name, _ in iga.story_jobs()}


def test_every_play_sfx_is_imported_or_queued():
    """The runner resolves a PlaySfx id by asset name under /Game/SaskartaGaea/Audio; anything missing
    logs "not imported yet" in play. Each id must be an imported uasset, in the story import list, or
    a known pending one."""
    missing = sorted(play_sfx_ids() - available() - PENDING)
    assert not missing, f"PlaySfx ids with no sound: {missing} (add them to make_story_sfx.py)"


def test_pending_list_is_current():
    landed = sorted(PENDING & available())
    assert not landed, f"these now have a sound; remove them from PENDING: {landed}"


def test_active_fault_and_range_cues_reuse_existing_short_one_shots():
    beats = {b['id']: b for b in STORY['beats']}
    for beat, expected in [('B12_KNEE_FAULT', 'SFX_Carrier_Joint_Strain'),
                           ('B13_SECOND_FAULT', 'SFX_Capsule_Scrape_Failing')]:
        cue = beats[beat]['actions'][0]
        assert cue == {'type': 'PlaySfx', 'id': expected, 'parallel': True}
        assert expected in available()
    cue = STORY['cinematics']['CIN_15_IN_RANGE']['cues'][0]
    assert cue == {'at_s': .4, 'type': 'PlaySfx', 'id': 'SFX_Radio_Static_In'}
    assert cue['id'] in available()
    assert not {'SFX_Carrier_ServoStrain', 'SFX_CapsuleScrape', 'SFX_StaticCrackle'} & play_sfx_ids()


def test_story_manifest_covers_the_spec():
    if not (mss.OUT / "manifest.json").exists():
        pytest.skip("run python Tools/Audio/make_story_sfx.py first")
    assert {name for _, _, name, _ in iga.story_jobs()} == set(mss.SPEC)
    assert all(dest == mss.UE_FOLDER and not loop for _, dest, _, loop in iga.story_jobs())


def test_generated_files_pass_the_check():
    if not all((mss.OUT / f"{a}.wav").exists() for a in mss.SPEC):
        pytest.skip("run python Tools/Audio/make_story_sfx.py first")
    assert mss.check() == []


def test_servo_is_deterministic_and_in_spec():
    a = mss.servo_up(np.random.default_rng(7))
    b = mss.servo_up(np.random.default_rng(7))
    assert np.array_equal(a, b)
    _, peak, (lo, hi), _, _ = mss.SPEC["SFX_Carrier_ServoUp"]
    assert lo <= len(a) / mss.SR <= hi
    assert abs(20 * np.log10(np.max(np.abs(a))) - peak) < 0.01
    assert a[0] == 0.0 and a[-1] == 0.0
