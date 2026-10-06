import json
import unreal

name = '/Game/SaskartaGaea/Characters/Traveller/Anims/A_Traveller_StaffHoldCentre'
clip = unreal.load_asset(name)
assert clip
tracks = [str(track) for track in unreal.AnimationLibrary.get_animation_track_names(clip)]
pose = unreal.AnimationLibrary.get_bone_pose_for_time(clip, 'staff011', .5, False)
print('STAFF_CLIP ' + json.dumps({
    'clip': name,
    'length': clip.get_play_length(),
    'staff_track': 'staff011' in tracks,
    'track_count': len(tracks),
    'pose': str(pose),
}, separators=(',', ':')))
