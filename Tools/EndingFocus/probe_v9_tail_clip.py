import unreal

name = '/Game/SaskartaGaea/Characters/Traveller/Anims/A_Samyor_StaffStand_SideSupportedV7_ClearCarry_ReviewOnly_InlineV7'
clip = unreal.load_asset(name)
assert clip
print('TAIL_CLIP_FLAGS', clip.get_play_length(),
      clip.get_editor_property('enable_root_motion'),
      clip.get_editor_property('force_root_lock'))
for seconds in (2.5, 6.9, 8.4):
    print('TAIL_CLIP_POSE', seconds,
          str(unreal.AnimationLibrary.get_bone_pose_for_time(clip,'root',seconds,False)),
          str(unreal.AnimationLibrary.get_bone_pose_for_time(clip,'Hips',seconds,False)))
