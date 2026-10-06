import unreal

world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
for x, y in [(335124., 422615.), (337178.24, 425347.98)]:
    hit = unreal.SystemLibrary.line_trace_single(
        world, unreal.Vector(x, y, 52000.), unreal.Vector(x, y, 47000.),
        unreal.TraceTypeQuery.TRACE_TYPE_QUERY1, True, [], unreal.DrawDebugTrace.NONE, True)
    print('STAFF_GROUND', x, y, str(hit))
