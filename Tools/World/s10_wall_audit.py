"""Read-only S10 wall replacement audit, run inside the Unreal editor.

python Tools/GameFlow/editor/ending_editor.py run-file Tools/World/s10_wall_audit.py
"""

import unreal


SITE_TAG = 'SD_S10_CrestFort'
OLD = {
    '002': '/Game/AshesOfBazaar/Meshes/SM_300x400_Mid',
    '027': '/Game/AshesOfBazaar/Meshes/SM_300x400_Mid',
    '032': '/Game/AshesOfBazaar/Meshes/SM_Fort_Wall_Mid',
    '037': '/Game/AshesOfBazaar/Meshes/SM_300x400_Mid',
    '054': '/Game/AshesOfBazaar/Meshes/SM_Fort_Wall_Mid',
    '072': '/Game/AshesOfBazaar/Meshes/SM_Fort_Wall_Mid',
    '109': '/Game/AshesOfBazaar/Meshes/SM_Fort_Wall_Mid',
    '304': '/Game/AshesOfBazaar/Meshes/SM_Fort_Wall_Mid',
    '309': '/Game/AshesOfBazaar/Meshes/SM_Fort_Wall_Mid',
    '314': '/Game/AshesOfBazaar/Meshes/SM_Fort_Wall_Mid',
    '353': '/Game/AshesOfBazaar/Meshes/SM_Fort_Wall_Mid',
}
NEW = {
    '002': '/Game/SaskartaGaea/Environment/Batch01/SM_B01_wall01',
    '027': '/Game/AshesOfBazaar/Meshes/SM_300x100_Panel',
    '032': '/Game/SaskartaGaea/Environment/Batch01/SM_B01_wall01',
    '037': '/Game/AshesOfBazaar/Meshes/SM_300x100_Panel',
    '054': '/Game/SaskartaGaea/Environment/Batch01/SM_B01_wall01',
    '072': '/Game/AshesOfBazaar/Meshes/SM_300x100_Panel',
    '109': '/Game/SaskartaGaea/Environment/Batch01/SM_B01_wall01',
    '304': '/Game/AshesOfBazaar/Meshes/SM_300x100_Panel',
    '309': '/Game/SaskartaGaea/Environment/Batch01/SM_B01_wall01',
    '314': '/Game/AshesOfBazaar/Meshes/SM_300x100_Panel',
    '353': '/Game/SaskartaGaea/Environment/Batch01/SM_B01_wall01',
}

world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
actors = unreal.GameplayStatics.get_all_actors_with_tag(world, SITE_TAG)
labels = [a.get_actor_label() for a in actors]
by_label = {}
for actor in actors:
    label = actor.get_actor_label()
    by_label.setdefault(label, []).append(actor)

hosts = sum('SD_ism' in [str(t) for t in a.tags] for a in actors)
ground = sum('SD_ground' in [str(t) for t in a.tags] for a in actors)
duplicates = sorted(label for label, found in by_label.items() if len(found) != 1)
print('S10_AUDIT total=%d unique=%d hosts=%d ground=%d duplicates=%s' %
      (len(actors), len(by_label), hosts, ground, duplicates))

states = []
for suffix in sorted(OLD):
    label = 'SD_S10_CrestFort_v2_' + suffix
    found = by_label.get(label, [])
    mesh_path = 'MISSING'
    if len(found) == 1 and isinstance(found[0], unreal.StaticMeshActor):
        mesh = found[0].static_mesh_component.static_mesh
        if mesh is not None:
            mesh_path = mesh.get_path_name().split('.')[0]
    state = 'OLD' if mesh_path == OLD[suffix] else 'NEW' if mesh_path == NEW[suffix] else 'WRONG'
    states.append(state)
    print('S10_WALL %s count=%d state=%s mesh=%s' % (suffix, len(found), state, mesh_path))

assert len(actors) == 119
assert len(by_label) == 119
assert hosts == 30
assert ground == 45
assert all(len(by_label.get('SD_S10_CrestFort_v2_' + suffix, [])) == 1 for suffix in OLD)
assert len(set(states)) == 1 and states[0] in ('OLD', 'NEW')
print('S10_AUDIT PASS state=' + states[0])
