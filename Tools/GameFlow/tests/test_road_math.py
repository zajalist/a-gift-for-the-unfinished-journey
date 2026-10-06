# Zone classification probe for BFL_SaskartaRoad.ClassifyTetherZone.
#
# Runs inside the live editor through Hayba python_run: read-only, well under
# the 5 s limit, and free of the constructs python_run refuses. It calls the
# Blueprint function library on its default object (world context first) and
# prints one PASS/FAIL line per case, then "N passed, M failed".
#
# Thresholds match BPC_RoadTether's defaults: warn past 1000 cm, clear under
# 900 cm, breach past 2000 cm.
import unreal

BFL_CLASS_PATH = '/Game/SaskartaGaea/GameFlow/BFL_SaskartaRoad.BFL_SaskartaRoad_C'
WARN_CM = 1000.0
CLEAR_CM = 900.0
BREACH_CM = 2000.0

# (distance cm, current zone, expected new zone)
CASES = [
    (0.0, 'Safe', 'Safe'),
    (950.0, 'Safe', 'Safe'),
    (1200.0, 'Safe', 'Warning'),
    (950.0, 'Warning', 'Warning'),
    (850.0, 'Warning', 'Safe'),
    (1999.0, 'Warning', 'Warning'),
    (2001.0, 'Safe', 'Breach'),
    (2500.0, 'Warning', 'Breach'),
]

passed = 0
failed = 0

world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
bfl_class = unreal.load_class(None, BFL_CLASS_PATH)

if world is None:
    failed = len(CASES)
    print('FAIL no editor world')
elif bfl_class is None:
    failed = len(CASES)
    print('FAIL cannot load ' + BFL_CLASS_PATH)
else:
    library = unreal.get_default_object(bfl_class)
    for distance, current, expected in CASES:
        got = library.call_method(
            'ClassifyTetherZone',
            (world, distance, unreal.Name(current), WARN_CM, CLEAR_CM, BREACH_CM),
        )
        if isinstance(got, tuple):
            got = got[0]
        label = 'ClassifyTetherZone(%s cm, %s) expected %s, got %s' % (
            str(distance), current, expected, str(got))
        if str(got) == expected:
            passed += 1
            print('PASS ' + label)
        else:
            failed += 1
            print('FAIL ' + label)

print('%d passed, %d failed' % (passed, failed))
