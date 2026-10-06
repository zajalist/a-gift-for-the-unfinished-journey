"""Stage a read-only PIE probe; root runs it during CIN19, then during walking.

This host tool never connects to Unreal. No spawning, seeking, animation changes,
material edits or saves are included in the generated script.
"""
import ast
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "Saved/Verification/hatch_visual_audit_20261001"

PROBE = '''import unreal, json, datetime
world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()
if world is None:
    raise RuntimeError('PIE world required for current pose readback')
def path(obj):
    return obj.get_path_name() if obj is not None else None
def vec(p):
    return [round(p.x, 4), round(p.y, 4), round(p.z, 4)]
def material_info(material):
    chain = []
    current = material
    for _ in range(4):
        if current is None:
            break
        row = {'path': path(current), 'class': current.get_class().get_name()}
        if isinstance(current, unreal.MaterialInstance):
            row['base_overrides'] = current.get_editor_property('base_property_overrides').export_text()
            chain.append(row)
            current = current.get_editor_property('parent')
        elif isinstance(current, unreal.Material):
            row['blend_mode'] = str(current.get_editor_property('blend_mode'))
            row['two_sided'] = current.get_editor_property('two_sided')
            row['disable_depth_test'] = current.get_editor_property('disable_depth_test')
            row['opacity_mask_clip_value'] = current.get_editor_property('opacity_mask_clip_value')
            chain.append(row)
            break
        else:
            chain.append(row)
            break
    return chain
actors = list(unreal.GameplayStatics.get_all_actors_of_class(world, unreal.Character))
actors += list(unreal.GameplayStatics.get_all_actors_of_class(world, unreal.SkeletalMeshActor))
rows = []
for actor in actors:
    for comp in actor.get_components_by_class(unreal.SkeletalMeshComponent):
        mesh = comp.get_skeletal_mesh_asset()
        if mesh is None or mesh.get_name() not in ('SK_Traveller', 'SK_CarrierFull', 'SK_Carrier'):
            continue
        bone_names = ('root', 'Hips', 'Spine', 'Spine1', 'Spine2', 'Neck', 'Head', 'LeftFoot', 'RightFoot') if mesh.get_name() == 'SK_Traveller' else ('root', 'capsule_root', 'capsule_lining', 'capsule_hatch', 'capsule_wheel_l', 'capsule_wheel_r')
        bones = {}
        for bone in bone_names:
            if comp.get_bone_index(bone) < 0:
                continue
            wp = comp.get_socket_location(bone)
            bones[bone] = {'world': vec(wp),
                          'actor_local': vec(actor.get_actor_transform().inverse_transform_location(wp)),
                          'socket_world': comp.get_socket_transform(bone, unreal.RelativeTransformSpace.RTS_WORLD).export_text(),
                          'hidden': comp.is_bone_hidden_by_name(bone)}
        rows.append({'actor': path(actor), 'class': actor.get_class().get_name(),
                     'actor_transform': actor.get_actor_transform().export_text(),
                     'actor_hidden': actor.get_editor_property('hidden'),
                     'component': path(comp), 'mesh': path(mesh),
                     'component_world': comp.get_world_transform().export_text(),
                     'component_relative': comp.get_relative_transform().export_text(),
                     'attached_to': path(comp.get_attach_parent()),
                     'parent_world': comp.get_attach_parent().get_world_transform().export_text() if comp.get_attach_parent() else None,
                     'attach_socket': str(comp.get_attach_socket_name()),
                     'animation_mode': str(comp.get_editor_property('animation_mode')),
                     'anim_instance': path(comp.get_anim_instance()),
                     'materials': [material_info(comp.get_material(i)) for i in range(comp.get_num_materials())],
                     'sections_shown_lod0': [comp.is_material_section_shown(i, 0) for i in range(comp.get_num_materials())],
                     'bones': bones})
        if len(rows) >= 12:
            break
    if len(rows) >= 12:
        break
cameras = []
for actor in unreal.GameplayStatics.get_all_actors_of_class(world, unreal.CineCameraActor):
    if 'CIN19' in actor.get_actor_label() or 'CIN19' in actor.get_name():
        cameras.append({'actor': path(actor), 'label': actor.get_actor_label(),
                        'transform': actor.get_actor_transform().export_text()})
print('HATCH_VISUAL_POSE ' + json.dumps({'utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
      'world': path(world), 'skeletal': rows, 'cameras': cameras[:8]}, separators=(',', ':')))
'''


IDLE_PROBE = """import unreal, json
world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()
assert world is None, 'Stop PIE before idle asset reads'
def xf(t):
    p, q, s = t.translation, t.rotation, t.scale3d
    return [round(v,4) for v in (p.x,p.y,p.z,q.x,q.y,q.z,q.w,s.x,s.y,s.z)]
def pose_rows(pose):
    return {str(b): [xf(unreal.AnimPoseExtensions.get_bone_pose(pose, b, unreal.AnimPoseSpaces.LOCAL)), xf(unreal.AnimPoseExtensions.get_bone_pose(pose, b, unreal.AnimPoseSpaces.WORLD))] for b in unreal.AnimPoseExtensions.get_bone_names(pose)}
folder = '/Game/SaskartaGaea/Characters/'
trav = unreal.load_asset(folder + 'Traveller/SK_Traveller')
assert trav is not None
mesh_editor = unreal.get_editor_subsystem(unreal.SkeletalMeshEditorSubsystem)
mat_rows = []
for slot in trav.get_editor_property('materials'):
    mat = slot.get_editor_property('material_interface')
    chain = []
    for level in range(4):
        if mat is None:
            break
        row = {'path':mat.get_path_name(), 'class':mat.get_class().get_name()}
        if isinstance(mat, unreal.MaterialInstance):
            row['overrides'] = mat.get_editor_property('base_property_overrides').export_text()
            chain.append(row)
            mat = mat.get_editor_property('parent')
        elif isinstance(mat, unreal.Material):
            row['blend_mode'] = str(mat.get_editor_property('blend_mode'))
            row['two_sided'] = mat.get_editor_property('two_sided')
            chain.append(row)
            break
        else:
            chain.append(row)
            break
    mat_rows.append(chain)
lods = []
for lod in range(min(4, mesh_editor.get_lod_count(trav))):
    lods.append({'lod':lod, 'vertices':mesh_editor.get_num_verts(trav,lod), 'sections':[mesh_editor.get_lod_material_slot(trav,lod,section) for section in range(mesh_editor.get_num_sections(trav,lod))]})
print('TRAVELLER_ASSET ' + json.dumps({'path':trav.get_path_name(),'materials':mat_rows,'lods':lods},separators=(',',':')))
for name, at in [('A_Traveller_SupportedIdle',0.0),('A_Traveller_SlowWalk',0.0),('A_Traveller_Transmit',0.0),('A_Samyor_FinalStill',0.0)]:
    clip = unreal.load_asset(folder + 'Traveller/Anims/' + name)
    assert clip is not None, name
    pose = unreal.AnimPoseExtensions.get_anim_pose_at_time(clip,at,unreal.AnimPoseEvaluationOptions())
    print('TRAVELLER_POSE ' + json.dumps({'clip':name,'at':at,'length':clip.get_play_length(),'bones':pose_rows(pose)},separators=(',',':')))
clip = unreal.load_asset(folder + 'Carrier/Full/A_CarrierFull_OpenHatch')
assert clip is not None
for at in (0.0,1.2,2.5,4.0):
    pose = unreal.AnimPoseExtensions.get_anim_pose_at_time(clip,min(at,clip.get_play_length()),unreal.AnimPoseEvaluationOptions())
    names = [n for n in unreal.AnimPoseExtensions.get_bone_names(pose) if 'capsule' in str(n).lower() or str(n).lower() == 'root']
    bones = {str(n): [xf(unreal.AnimPoseExtensions.get_bone_pose(pose,n,unreal.AnimPoseSpaces.LOCAL)),xf(unreal.AnimPoseExtensions.get_bone_pose(pose,n,unreal.AnimPoseSpaces.WORLD))] for n in names}
    print('HATCH_ASSET_POSE ' + json.dumps({'at':at,'bones':bones},separators=(',',':')))
print('CONTACT_API', unreal.GeometryScript_AssetUtils.copy_mesh_from_skeletal_mesh.__doc__, unreal.GeometryScript_MeshQueries.get_vertex_position.__doc__, unreal.GeometryScript_BoneWeights.get_vertex_bone_weights.__doc__)
"""


def main():
    ast.parse(PROBE)
    ast.parse(IDLE_PROBE)
    for token in ("try", "getattr", "import time", "open(", ".replace(", "set_editor_property", "load_asset", "save_asset", "spawn_actor"):
        if token in PROBE:
            raise ValueError(token)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "read_idle_assets.py").write_text(IDLE_PROBE.split("for name, at in")[0], encoding="utf-8")
    pre = IDLE_PROBE.split("trav =")[0]
    poses = IDLE_PROBE.split("for name, at in")[1].split("clip = unreal.load_asset(folder + 'Carrier/")[0]
    body = poses[poses.index("    clip ="):]
    for i, name in enumerate(("A_Traveller_SupportedIdle", "A_Traveller_SlowWalk", "A_Traveller_Transmit", "A_Samyor_FinalStill")):
        code = pre + "for name, at in " + repr([(name, 0.0)]) + ":\n" + body
        ast.parse(code)
        (OUT / f"read_idle_pose_{i}.py").write_text(code, encoding="utf-8")
    hatch = pre + "clip = unreal.load_asset(folder + 'Carrier/" + IDLE_PROBE.split("clip = unreal.load_asset(folder + 'Carrier/")[1]
    (OUT / "read_idle_hatch.py").write_text(hatch, encoding="utf-8")
    file = OUT / "read_live_pose.py"
    file.write_text(PROBE, encoding="utf-8")
    manifest = {"utc": datetime.now(timezone.utc).isoformat(), "editor_executed": False,
                "script": str(file), "sha256": hashlib.sha256(file.read_bytes()).hexdigest(),
                "capture_at_sequence_s": [0.5, 6.0, 10.0, 16.0, 26.0, 35.5],
                "capture_again_while_walking": True}
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(file)


if __name__ == "__main__":
    main()
