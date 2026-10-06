"""Save and read back the prepared CIN19 V9 review asset after visual inspection."""
import json
import unreal

assert unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world() is None, 'Stop PIE'
review = '/Game/SaskartaGaea/GameFlow/Cinematics/LS_CIN_19_Hatch_SideSupportedReviewV9'
sequence = unreal.load_asset(review)
assert sequence, 'V9 review asset missing'
bindings = [binding for binding in sequence.get_bindings()
            if str(binding.get_display_name()) == 'Samyor_Hatch']
assert len(bindings) == 1
tracks = [track for track in bindings[0].get_tracks()
          if isinstance(track, unreal.MovieSceneSkeletalAnimationTrack)]
assert len(tracks) == 1
sections = sorted((round(section.get_start_frame_seconds(), 3),
                   round(section.get_end_frame_seconds(), 3),
                   section.get_editor_property('params').animation.get_name())
                  for section in tracks[0].get_sections())
assert [(start, end) for start, end, _ in sections] == [
    (0., 7.), (7., 13.5), (13.5, 21.5), (21.5, 27.5), (27.5, 36.)]
assert sections[0][2] == 'A_Samyor_ReachLatch_SideSupportedV7_ReviewOnly_InlineV7'
assert sections[1][2] == 'A_Samyor_PushLid_SideSupportedV7_ReviewOnly_InlineV7'
assert sections[2][2] == 'A_Samyor_PullUp_SideSupportedV7_ReviewOnly_InlineV7'
assert sections[3][2] == 'A_Samyor_LegOver_SideContactV4_ReviewOnly_InlineV5'
assert sections[4][2] == 'A_Samyor_StaffStand_SideSupportedV7_ClearCarry_ReviewOnly_InlineV7'
assert unreal.EditorAssetLibrary.save_asset(review, only_if_is_dirty=False), 'V9 save failed'
print('CIN19_V9_REVIEW_SAVED ' + json.dumps({'asset': review, 'sections': sections}, separators=(',', ':')))
