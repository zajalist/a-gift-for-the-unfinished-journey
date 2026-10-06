# Side-by-side rig for a far stand-in (world sprint, Task V4, ruling R24).
#
#   node Tools/Foliage/run_foliage.mjs py Tools/Foliage/proof_standin.py "ACTION='spawn'" \
#        "SRC='/Game/Megaplant_Library/...'" "DST='/Game/SaskartaGaea/Foliage/Static/SM_...'"
#   node Tools/Foliage/run_foliage.mjs py Tools/Foliage/proof_standin.py "ACTION='cleanup'"
#
# spawn puts the native Megaplant (skeletal, Nanite assembly) at LOC - (GAP, 0, 0)
# and the static stand-in at LOC + (GAP, 0, 0), both labelled V4_STANDIN_*,
# high above the map so a base-colour capture sees only the two trees. Capture
# with Tools/Foliage/snap.sh from -Y (the native tree is then on screen right).
# cleanup destroys every V4_STANDIN_* actor. Nothing is saved.
import unreal

ACTION = ''
SRC = ''
DST = ''
LOC = [389000.0, 408000.0, 60000.0]
GAP = 900.0

sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
old = [a for a in sub.get_all_level_actors() if a.get_actor_label().startswith('V4_STANDIN')]
for a in old:
    sub.destroy_actor(a)
if ACTION == 'spawn':
    sk = sub.spawn_actor_from_class(unreal.SkeletalMeshActor, unreal.Vector(LOC[0] - GAP, LOC[1], LOC[2]))
    sk.set_actor_label('V4_STANDIN_NATIVE')
    sk.skeletal_mesh_component.set_skeletal_mesh_asset(unreal.load_asset(SRC))
    st = sub.spawn_actor_from_class(unreal.StaticMeshActor, unreal.Vector(LOC[0] + GAP, LOC[1], LOC[2]))
    st.set_actor_label('V4_STANDIN_STATIC')
    st.static_mesh_component.set_static_mesh(unreal.load_asset(DST))
    print('STANDIN spawned native=' + SRC.split('/')[-1] + ' static=' + DST.split('/')[-1] +
          ' bounds native=' + str(sk.get_actor_bounds(False)[1]) + ' static=' + str(st.get_actor_bounds(False)[1]))
elif ACTION == 'cleanup':
    print('STANDIN cleaned ' + str(len(old)))
else:
    raise RuntimeError('ACTION must be spawn or cleanup')
