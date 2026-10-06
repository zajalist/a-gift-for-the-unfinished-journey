# python_run (Hayba), read-only: the numbers build_cinematics.py needs for CIN_01 (-> probe_cin01.json by hand).
import unreal
eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
ps = None
for a in eas.get_all_level_actors():
    if a.get_class().get_name() == 'PlayerStart':
        ps = a
print('playerstart', str(ps.get_actor_location()), str(ps.get_actor_rotation()))
cls = unreal.load_object(None, '/Game/SaskartaGaea/Characters/Carrier/BP_Saskarta_Carrier.BP_Saskarta_Carrier_C')
cdo = unreal.get_default_object(cls)
cap = cdo.get_editor_property('capsule_component')
print('capsule half', cap.get_scaled_capsule_half_height(), 'radius', cap.get_scaled_capsule_radius())
world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
loc = ps.get_actor_location()
def ground(x, y):
    hit = unreal.SystemLibrary.line_trace_single(world, unreal.Vector(x, y, loc.z + 20000), unreal.Vector(x, y, loc.z - 20000), unreal.TraceTypeQuery.TRACE_TYPE_QUERY1, False, [], unreal.DrawDebugTrace.NONE, True)
    # line_trace_single returns the HitResult, or None when nothing is hit (e.g. the WP cell is not loaded)
    return None if hit is None else hit.get_editor_property('impact_point').z
import math
print('ground at start', ground(loc.x, loc.y))
bx = loc.x + math.cos(math.radians(10)) * 6000
by = loc.y + math.sin(math.radians(10)) * 6000
print('ground 60 m back (yaw 10)', ground(bx, by), bx, by)
# v2 (LANE5): the carrier camera's offset, and the ground under the CIN_01 v2 hill and crane points
S = (287480.0, 444050.0, 20000.0)
ys = math.degrees(math.atan2(S[1] - loc.y, S[0] - loc.x))
print('summit yaw', round(ys, 2))
for label, yaw, dist in (('hill', ys - 30.0, 45000.0), ('crane0', ys, -1100.0), ('crane1', ys, -400.0)):
    x = loc.x + math.cos(math.radians(yaw)) * dist
    y = loc.y + math.sin(math.radians(yaw)) * dist
    print(label, round(x), round(y), ground(x, y))
