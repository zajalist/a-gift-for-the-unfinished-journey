# python_run chunk (Hayba): the Keeper's staff grip fix (task ENDING addendum, 2026-09-28).
# SK_Traveller's staff is skinned 100% to its own bone, staff011 (parent root), not to RightHand.
# All four clips key the right hand rigidly to the staff, with the fist ~7 cm off the shaft
# (the shaft is 2.2 cm in radius and runs along staff011's local -Y, 3.5 cm off the bone origin).
# The offset is constant in every frame of every clip, so the fix is one constant local offset,
# (0.0274, 0, 0.0669) in staff011's local units (x100 cm), added to every staff011 position key.
# Run once per clip, replacing __CLIP__ with SlowWalk, SupportedIdle, Transmit and Rest; it skips a
# clip that is already offset. Then save the four packages. Before/after: Saved/Screenshots/Char/StaffGrip/.
import unreal
AL = unreal.AnimationLibrary
an = unreal.load_asset('/Game/SaskartaGaea/Characters/Traveller/Anims/A_Traveller___CLIP__')
D = unreal.Vector(0.0274, 0.0, 0.0669)
n = AL.get_num_keys(an)
first = AL.get_bone_pose_for_frame(an, 'staff011', 0, False).translation
if abs(first.x - (-0.395)) > 0.001:
    print('SKIP: already offset', str(first.x))
else:
    P = []; R = []; S = []
    for fr in range(n):
        t = AL.get_bone_pose_for_frame(an, 'staff011', fr, False)
        P.append(t.translation + D); R.append(t.rotation); S.append(t.scale3d)
    ctl = an.get_editor_property('controller')
    ok = ctl.set_bone_track_keys('staff011', P, R, S, True)
    print('__CLIP__ keys', n, 'ok', ok, 'f0 now', str(AL.get_bone_pose_for_frame(an, 'staff011', 0, False).translation.x))
