"""Prepare only this lane's proposal and receipts; never modify native source."""
from pathlib import Path
import difflib
import hashlib
import json

ROOT = Path(__file__).resolve().parents[3]
LANE = Path(__file__).resolve().parent
SOURCE = ROOT / 'Plugins/SaskartaCore/Source/SaskartaCore/Private/SaskartaMotorDiagram.cpp'
RECEIPTS = ROOT / 'Saved/Verification/ui_refinement_v13/loading_crank_refinement_v17'
original_bytes = SOURCE.read_bytes()
original = original_bytes.decode('utf-8').replace('\r\n', '\n')
start = original.index('        // Loading and charging share the exact crank rings, spokes, pin and top mark.')
end = original.index('\n        Text(24, 12,', start)
replacement = '''        // One connected mechanism in both presentations. The arm and grip rotate
        // with the wheel; the attached top index stays fixed for the accepted beat.
        const auto DrawCrank = [&](FVector2D Wheel, float WheelAngle, float HubBright)
        {
            Arc(Wheel, 67, 0, 2*PI, 0.3f, 2.f);
            Arc(Wheel, 61, 0, 2*PI, 0.56f, 2.f);
            for (int32 I = 0; I < 6; ++I)
            {
                const float Angle = WheelAngle + I * PI / 3.f;
                const FVector2D Direction(FMath::Cos(Angle), FMath::Sin(Angle));
                Line({Wheel+Direction*24.f,Wheel+Direction*61.f}, 0.45f, 2.f);
            }
            Arc(Wheel, 24, 0, 2*PI, HubBright, 2.f);

            const FVector2D Direction(FMath::Cos(WheelAngle), FMath::Sin(WheelAngle));
            const FVector2D Tangent(-Direction.Y, Direction.X);
            const FVector2D Pin = Wheel + Direction * 51.f;
            Line({Wheel+Direction*24.f,Pin}, 0.9f, 3.f);
            // A closed grip and its spindle make the handle read as a crank,
            // while leaving the center clear for the existing input glyph.
            Line({Pin-Tangent*8.f-Direction*4.f,Pin+Tangent*8.f-Direction*4.f}, 1.f, 2.f);
            Line({Pin-Tangent*8.f+Direction*4.f,Pin+Tangent*8.f+Direction*4.f}, 1.f, 2.f);
            Arc(Pin+Tangent*8.f, 4, WheelAngle, WheelAngle+PI, 1.f, 2.f);
            Arc(Pin-Tangent*8.f, 4, WheelAngle+PI, WheelAngle+2*PI, 1.f, 2.f);
            Arc(Pin, 2, 0, 2*PI, 1.f, 1.5f);
            Line({Wheel+FVector2D(0,-74),Wheel+FVector2D(0,-67)}, 1.f, 3.f);
        };
        if (bLoading)
        {
            // Readiness supplies exactly two turns and finishes at the top mark.
            // A stalled or regressing readiness stalls or reverses the mechanism.
            const FVector2D Wheel(92.f, 83.f);
            DrawCrank(Wheel, LoadingFraction * 2.f * 2.f * PI - PI * 0.5f, 0.6f);
            Arc(Wheel, 5, 0, 2*PI, 0.6f, 1.5f);
            if (LoadingFraction > 0.f)
                Arc(Wheel, 70, -PI*0.5f, -PI*0.5f + LoadingFraction*2.f*PI, 0.9f, 3.f);
            Box(184, 81.5f, 512, 3, 0.16f);
            Box(184, 81.5f, 512*LoadingFraction, 3, 0.9f);
            return Layer;
        }
'''
proposed = original[:start] + replacement + original[end:]
old_call = '        DrawCrank(Wheel, WheelAngle);'
assert proposed.count(old_call) == 1
proposed = proposed.replace(old_call, '        DrawCrank(Wheel, WheelAngle, Core.BeatWindowOpen() ? 1.f : 0.38f);')
old_hub = '        Arc(Wheel, 24, 0, 2*PI, Core.BeatWindowOpen() ? 1.f : 0.38f, 2.f);\n'
assert proposed.count(old_hub) == 1
proposed = proposed.replace(old_hub, '')
target = LANE / 'Proposed/SaskartaMotorDiagram.cpp'
target.write_bytes(proposed.replace('\n', '\r\n').encode('utf-8'))
relative = SOURCE.relative_to(ROOT).as_posix()
patch = ''.join(difflib.unified_diff(original.splitlines(True), proposed.splitlines(True),
                                  fromfile='a/' + relative, tofile='b/' + relative))
patch_path = LANE / 'loading_crank_refinement.patch'
patch_path.write_text(patch, encoding='utf-8', newline='\n')
receipt = {
    'status': 'proposal_only_no_native_integration',
    'source': relative,
    'source_sha256': hashlib.sha256(original_bytes).hexdigest(),
    'proposal_sha256': hashlib.sha256(target.read_bytes()).hexdigest(),
    'patch_sha256': hashlib.sha256(patch_path.read_bytes()).hexdigest(),
    'scope': 'one visual revision; shared crank geometry and readiness-driven presentation',
    'loading_turns': 2,
    'loading_bar': {'x': 184, 'y': 81.5, 'width': 512, 'height': 3},
    'charging_phase_and_accepted_window': 'unchanged',
    'checks_run': 'none; no native build, editor operation, or gameplay test',
    'preview': 'CPU geometry sketch only; excludes authored font, input glyph textures, phosphor, DPI and game background',
}
RECEIPTS.mkdir(parents=True, exist_ok=True)
(RECEIPTS / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
print(str(target))
print(str(patch_path))
