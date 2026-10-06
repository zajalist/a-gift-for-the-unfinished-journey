"""Duplicate the saved CIN19 V7 review sequence and substitute the reviewed V7 body clips.

Run in the editor only after PIE is stopped and an exclusive editor lease is held.
This creates a new review asset. The production sequence is only inspected.
"""
import json
import unreal

assert unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world() is None, 'Stop PIE'

FOLDER = '/Game/SaskartaGaea/GameFlow/Cinematics/'
BASE = FOLDER + 'LS_CIN_19_Hatch_SideSupportedReviewV7'
REVIEW = FOLDER + 'LS_CIN_19_Hatch_SideSupportedReviewV9'
PRODUCTION = FOLDER + 'LS_CIN_19_Hatch'
ANIMS = '/Game/SaskartaGaea/Characters/Traveller/Anims/'
RANGES = [(0., 7.), (7., 13.5), (13.5, 21.5), (21.5, 27.5), (27.5, 36.)]
SWAPS = {
    (0., 7.): 'A_Samyor_ReachLatch_SideSupportedV7_ReviewOnly_InlineV7',
    (7., 13.5): 'A_Samyor_PushLid_SideSupportedV7_ReviewOnly_InlineV7',
    (13.5, 21.5): 'A_Samyor_PullUp_SideSupportedV7_ReviewOnly_InlineV7',
    (27.5, 36.): 'A_Samyor_StaffStand_SideSupportedV7_ClearCarry_ReviewOnly_InlineV7',
}


def body_sections(sequence):
    bindings = [binding for binding in sequence.get_bindings()
                if str(binding.get_display_name()) == 'Samyor_Hatch']
    assert len(bindings) == 1, 'Expected exactly one Samyor_Hatch binding'
    tracks = [track for track in bindings[0].get_tracks()
              if isinstance(track, unreal.MovieSceneSkeletalAnimationTrack)]
    assert len(tracks) == 1, 'Expected one body animation track'
    sections = tracks[0].get_sections()
    assert len(sections) == 5, 'Expected five supported exit body sections'
    return sections


def fingerprint(sequence):
    return sorted((round(section.get_start_frame_seconds(), 3),
                   round(section.get_end_frame_seconds(), 3),
                   section.get_editor_property('params').animation.get_path_name())
                  for section in body_sections(sequence))


base = unreal.load_asset(BASE)
production = unreal.load_asset(PRODUCTION)
assert base and production, 'Saved V7 or production CIN19 missing'
base_before = fingerprint(base)
production_before = fingerprint(production)
assert [(start, end) for start, end, _ in base_before] == RANGES, 'V7 timing changed'
assert base_before[3][2].endswith('.A_Samyor_LegOver_SideContactV4_ReviewOnly_InlineV5'), 'LegOver changed'
assert not unreal.EditorAssetLibrary.does_asset_exist(REVIEW), 'V9 already exists; inspect it before retry'

loaded = {}
for frame_range, name in SWAPS.items():
    clip = unreal.load_asset(ANIMS + name)
    assert clip, name
    tracks = [str(track).casefold() for track in unreal.AnimationLibrary.get_animation_track_names(clip)]
    assert len(tracks) == 68 and len(set(tracks)) == 68, name
    assert abs(clip.get_play_length() - (frame_range[1] - frame_range[0])) < .001, name
    loaded[frame_range] = clip

review = unreal.EditorAssetLibrary.duplicate_asset(BASE, REVIEW)
assert review, 'V9 duplicate failed'
changed = []
for section in body_sections(review):
    frame_range = (round(section.get_start_frame_seconds(), 3),
                   round(section.get_end_frame_seconds(), 3))
    if frame_range in loaded:
        params = section.get_editor_property('params')
        params.set_editor_property('animation', loaded[frame_range])
        section.set_editor_property('params', params)
        changed.append(frame_range)

assert set(changed) == set(loaded), 'Did not substitute all four sections'
review_after = fingerprint(review)
assert review_after[3] == base_before[3], 'LegOver changed'
assert fingerprint(base) == base_before, 'V7 base changed'
assert fingerprint(production) == production_before, 'Production CIN19 changed'
print('CIN19_V9_REVIEW_PREPARED ' + json.dumps({
    'asset': REVIEW,
    'sections': review_after,
    'base_unchanged': True,
    'production_unchanged': True,
    'saved': False,
}, separators=(',', ':')))
