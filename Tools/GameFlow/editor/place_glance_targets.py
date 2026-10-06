# python_run (Hayba), LANE5: the glance targets (CINEMATICS.md "Glances") and the road tag.
# TargetPoints, not spatially loaded (the runner finds them by tag among loaded actors), folder Story/Glance.
# Positions: Tools/GameFlow/glance_targets.json (computed from road-profile.json; the V2/V5/V9 dressing
# is not placed yet, so the targets mark where it goes: the stones' gap on the bearing to the mast crown,
# the platform side of the road at 2,600 m, the boot point, the Segalen stone 2 m left-forward at 4,877 m).
# Also the StartRouteTrace hook target: a BP_Saskarta_RouteTrace instance tagged Saskarta.Road.
# STEP 0 = spawn/update and tag, STEP 1 = save the touched actor packages.
import unreal
STEP = 0
TARGETS = {"Saskarta.Glance.PromiseStones": [584321, 431130, -33983], "Saskarta.Glance.Platform": [438856, 337750, -40970], "Saskarta.Glance.ValleyEast": [616580, 463550, -35328], "Saskarta.Glance.SegalenWall": [302963, 472105, 11749], "Saskarta.Glance.PoiO09Graveyard": [516046, 367015, -38064], "Saskarta.Glance.PoiO08Pumps": [573076, 254956, -17418], "Saskarta.Glance.PoiO03Bridge": [393080, 317150, -39723], "Saskarta.Glance.PoiO06Dam": [431736, 297828, -38932], "Saskarta.Glance.PoiO09Cradles": [516046, 367015, -38051], "Saskarta.Glance.PoiO10Still": [428504, 391460, -35580], "Saskarta.Glance.PoiO14Dovecote": [576519, 453068, -36075]}
eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
actors = eas.get_all_level_actors()
by_tag = {}
for a in actors:
    for t in a.tags:
        by_tag[str(t)] = a
if STEP == 0:
    for tag, (x, y, z) in TARGETS.items():
        a = by_tag.get(tag)
        if a is None:
            a = eas.spawn_actor_from_class(unreal.TargetPoint, unreal.Vector(x, y, z))
            a.set_actor_label('Glance_' + tag.split('.')[-1])
            a.tags = [unreal.Name(tag)]
        a.set_actor_location(unreal.Vector(x, y, z), False, False)
        a.set_folder_path('Story/Glance')
        a.set_editor_property('is_spatially_loaded', False)
        print(tag, str(a.get_actor_label()), str(a.get_actor_location()))
    # CIN_06's CallHook StartRouteTrace targets the actor tagged Saskarta.Road: a BP_Saskarta_RouteTrace
    # (no spline, so the runner's road lookup skips it), not the road itself (its package holds other lanes' work).
    rt = by_tag.get('Saskarta.Road')
    if rt is None:
        cls = unreal.load_object(None, '/Game/SaskartaGaea/GameFlow/BP_Saskarta_RouteTrace.BP_Saskarta_RouteTrace_C')
        rt = eas.spawn_actor_from_class(cls, unreal.Vector(494822, 321464, -29500))
        rt.set_actor_label('RouteTrace')
        rt.tags = [unreal.Name('Saskarta.Road')]
    rt.set_folder_path('Story/Glance')
    rt.set_editor_property('is_spatially_loaded', False)
    print('route trace', str(rt.get_actor_label()), str([str(t) for t in rt.tags]))
else:
    pk = [str(by_tag[t].get_package().get_name()) for t in list(TARGETS) + ['Saskarta.Road']]
    print('saving', str(pk))
    print(unreal.EditorLoadingAndSavingUtils.save_packages([unreal.load_package(p) for p in pk], True))
