"""Serial editor integration for one bounded far-mountain PCG cluster at a time.

Root/editor owner only, after build_far_mountain_pcg.py build. No HLOD build here.
  python Tools/Foliage/apply_far_mountain_pcg.py place FM01 --owner CODEX
  python Tools/Foliage/apply_far_mountain_pcg.py check FM01 --owner CODEX
  python Tools/Foliage/apply_far_mountain_pcg.py prepare FM01 --owner CODEX
  python Tools/Foliage/apply_far_mountain_pcg.py check FM01 --owner CODEX
  python Tools/Foliage/apply_far_mountain_pcg.py save FM01 --owner CODEX
"""

import argparse
import sys

import build_far_mountain_pcg as far

BODY = r'''
import unreal
eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
label = 'PCG_FarMountain_' + CID
volume = None
for a in eas.get_all_level_actors():
    if a.get_actor_label() == label:
        volume = a
if STEP == 'place':
    graph = unreal.load_asset(GRAPH)
    if graph is None:
        print('RESULT missing_graph ' + GRAPH)
    else:
        if volume is None:
            volume = eas.spawn_actor_from_class(unreal.PCGVolume, unreal.Vector(CENTRE[0], CENTRE[1], CENTRE[2]))
        volume.set_actor_label(label)
        volume.set_actor_location(unreal.Vector(CENTRE[0], CENTRE[1], CENTRE[2]), False, False)
        volume.set_actor_scale3d(unreal.Vector(110.0, 110.0, 150.0))
        # MainPartition loads too near for a 0.5-2.2 km far layer. These six
        # bounded actors are always resident; their instances still draw-cull.
        volume.set_editor_property('is_spatially_loaded', False)
        volume.set_editor_property('enable_auto_lod_generation', False)
        volume.set_editor_property('tags', [unreal.Name('FarMountainTrees'), unreal.Name(CID)])
        volume.set_folder_path('PCG/Far Mountain Pines')
        comp = volume.get_component_by_class(unreal.PCGComponent)
        comp.set_editor_property('is_component_partitioned', False)
        comp.set_editor_property('generation_trigger', unreal.PCGComponentGenerationTrigger.GENERATE_ON_DEMAND)
        comp.set_graph(graph)
        comp.generate_local(True)
        print('RESULT generated ' + label)
else:
    if volume is None:
        print('RESULT missing_volume ' + label)
    else:
        pcg = volume.get_component_by_class(unreal.PCGComponent)
        busy = pcg is None or pcg.is_generating()
        counts = {}
        total = 0
        ready = True
        positions_ok = True
        generated_components = 0
        unmatched = list(POINTS)
        for comp in volume.get_components_by_class(unreal.InstancedStaticMeshComponent):
            mesh = comp.get_editor_property('static_mesh')
            if mesh is None or mesh.get_path_name().split('.')[0] not in MESHES:
                continue
            count = comp.get_instance_count()
            generated_components += 1
            counts[mesh.get_name()] = counts.get(mesh.get_name(), 0) + count
            total += count
            if STEP == 'prepare' and not busy:
                comp.set_collision_profile_name('NoCollision')
                comp.set_editor_property('cast_shadow', False)
                comp.set_editor_property('cast_far_shadow', False)
                comp.set_editor_property('visible_in_ray_tracing', False)
                comp.set_editor_property('affect_distance_field_lighting', False)
                comp.set_editor_property('world_position_offset_disable_distance', 1)
            else:
                ready = ready and str(comp.get_collision_profile_name()) == 'NoCollision'
                ready = ready and not comp.get_editor_property('cast_shadow')
                ready = ready and not comp.get_editor_property('cast_far_shadow')
                ready = ready and not comp.get_editor_property('visible_in_ray_tracing')
                ready = ready and not comp.get_editor_property('affect_distance_field_lighting')
                ready = ready and comp.get_editor_property('world_position_offset_disable_distance') == 1
                ready = ready and comp.get_editor_property('instance_start_cull_distance') == START_CULL
                ready = ready and comp.get_editor_property('instance_end_cull_distance') == END_CULL
            for i in range(count):
                t = comp.get_instance_transform(i, True).translation
                match = -1
                for j, p in enumerate(unmatched):
                    if (t - unreal.Vector(p[0], p[1], p[2])).size() < 2.0:
                        match = j
                        break
                if match < 0:
                    positions_ok = False
                else:
                    unmatched.pop(match)
        positions_ok = positions_ok and len(unmatched) == 0
        ready = ready and not volume.get_editor_property('is_spatially_loaded')
        ready = ready and not volume.get_editor_property('enable_auto_lod_generation')
        print('RESULT count ' + label + ' ' + str(total) + ' expected=' + str(EXPECTED) + ' ' + str(counts))
        print('RESULT state ' + label + ' ready=' + str(ready) + ' positions=' + str(positions_ok) + ' components=' + str(generated_components) + ' busy=' + str(busy))
        if STEP == 'save' and total == EXPECTED and ready and positions_ok and generated_components == 2 and not busy:
            graph = unreal.load_asset(GRAPH)
            ok = graph is not None and unreal.EditorLoadingAndSavingUtils.save_packages(
                [graph.get_package(), volume.get_package()], True)
            print('RESULT save ' + label + ' ' + str(ok))
        elif STEP == 'save':
            print('RESULT save ' + label + ' False')
'''


def script(step, cluster):
    first = cluster["points"][0]
    data = dict(STEP=step, CID=cluster["id"], GRAPH=far.PATH_PREFIX + cluster["id"],
                CENTRE=[*cluster["centre_cm"], first["z_cm"]],
                EXPECTED=len(cluster["points"]), MESHES=far.plan()["mesh_paths"],
                MIN_DRAW=far.MIN_DRAW_CM, START_CULL=far.START_CULL_CM, END_CULL=far.END_CULL_CM)
    data["POINTS"] = [(p["x_cm"], p["y_cm"], p["z_cm"]) for p in cluster["points"]]
    return "\n".join(f"{key} = {value!r}" for key, value in data.items()) + "\n" + BODY


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=("code", "place", "prepare", "check", "save"))
    ap.add_argument("cluster")
    ap.add_argument("--owner", default="")
    args = ap.parse_args()
    cluster = next((c for c in far.plan()["clusters"] if c["id"] == args.cluster), None)
    if cluster is None:
        raise SystemExit(f"unknown cluster {args.cluster}")
    step = "check" if args.step == "code" else args.step
    source = script(step, cluster)
    compile(source, "<far-mountain-pcg>", "exec")
    if args.step == "code":
        print(source)
        return
    far.gate(args.owner)
    ok, out = far.pcg.run(source)
    print(out)
    if not ok:
        raise SystemExit(f"far mountain {args.step} failed for {args.cluster}")
    if args.step == "place" and "RESULT generated " not in out:
        raise SystemExit(f"far mountain graph missing for {args.cluster}")
    if args.step in ("prepare", "check", "save"):
        expected = f" expected={len(cluster['points'])} "
        if f" {len(cluster['points'])}{expected}" not in out:
            raise SystemExit(f"far mountain {args.cluster} instance count did not meet hard budget")
    if args.step == "save" and f"RESULT save PCG_FarMountain_{args.cluster} True" not in out:
        raise SystemExit(f"far mountain save returned false for {args.cluster}")
    if args.step in ("check", "save") and ("ready=True positions=True components=2 busy=False" not in out):
        raise SystemExit(f"far mountain {args.cluster} is not prepared at its planned world positions")
    if args.step == "prepare" and "busy=True" in out:
        raise SystemExit(f"far mountain {args.cluster} is still generating; prepare was deferred")


if __name__ == "__main__":
    main()
