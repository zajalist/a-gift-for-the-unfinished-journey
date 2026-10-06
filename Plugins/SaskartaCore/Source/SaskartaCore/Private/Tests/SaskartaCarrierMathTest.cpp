// Automation tests for SaskartaCarrierMath (task CARRIERANIM): the hitch model and the
// spring-dampers. Pure math, no world or mesh.
//
//   Automation RunTests Saskarta.Carrier
//
// Written offline with the implementation (the editor was open); the closed-editor build
// session runs them first.

#include "Misc/AutomationTest.h"

#if WITH_DEV_AUTOMATION_TESTS

#include "SaskartaCarrierAnimInstance.h"
#include "SaskartaCarrierMath.h"

#include <limits>

namespace SaskartaCarrierMathTest
{
    using namespace SaskartaCarrierMath;

    static constexpr float Dt = 1.f / 60.f;

    /** Runs the hitch model for Seconds at 60 Hz. */
    static float RunHitch(float Psi, float Speed, float YawRateRad, float Seconds, float Length = 250.f, float MaxDeg = 70.f, float Reverse = 0.35f)
    {
        const int32 Steps = FMath::RoundToInt(Seconds / Dt);
        for (int32 I = 0; I < Steps; ++I)
        {
            Psi = StepHitchAngle(Psi, Speed, YawRateRad, Length, 0.f, Dt, FMath::DegreesToRadians(MaxDeg), Reverse);
        }
        return Psi;
    }
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaHitchStraightensTest, "Saskarta.Carrier.Hitch.ForwardStraightens",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)
bool FSaskartaHitchStraightensTest::RunTest(const FString&)
{
    using namespace SaskartaCarrierMathTest;
    // Driving straight ahead pulls a 30 deg hitch angle back in line.
    const float Psi = RunHitch(FMath::DegreesToRadians(30.f), 300.f, 0.f, 12.f);
    TestTrue(FString::Printf(TEXT("|psi| < 1 deg after 12 s at 3 m/s (got %.3f deg)"), FMath::RadiansToDegrees(Psi)), FMath::Abs(FMath::RadiansToDegrees(Psi)) < 1.f);
    // Standing still, nothing moves.
    const float Still = RunHitch(FMath::DegreesToRadians(20.f), 0.f, 0.f, 5.f);
    TestEqual(TEXT("no motion at rest"), FMath::RadiansToDegrees(Still), 20.f, 1e-3f);
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaHitchSteadyTurnTest, "Saskarta.Carrier.Hitch.SteadyTurn",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)
bool FSaskartaHitchSteadyTurnTest::RunTest(const FString&)
{
    using namespace SaskartaCarrierMathTest;
    // A right turn at 20 deg/s and 4 m/s settles at asin(-w L / v): the capsule's nose
    // points left of the carrier's heading, so it tracks inside the turn.
    const float W = FMath::DegreesToRadians(20.f);
    const float Expected = SteadyHitchAngle(400.f, W, 250.f);
    TestTrue(TEXT("steady angle is negative for a right turn"), Expected < 0.f);
    const float Psi = RunHitch(0.f, 400.f, W, 20.f);
    TestEqual(TEXT("settles at the steady angle (deg)"), FMath::RadiansToDegrees(Psi), FMath::RadiansToDegrees(Expected), 0.25f);
    // The rate there is ~0.
    TestEqual(TEXT("rate ~0 at the steady angle"), HitchAngleRate(Expected, 400.f, W, 250.f, 0.f, 0.35f), 0.f, 1e-4f);
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaHitchReverseTest, "Saskarta.Carrier.Hitch.ReverseJackknife",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)
bool FSaskartaHitchReverseTest::RunTest(const FString&)
{
    using namespace SaskartaCarrierMathTest;
    const float Start = FMath::DegreesToRadians(5.f);
    // Reversing grows a small hitch angle (the jackknife) ...
    const float Slow = RunHitch(Start, -150.f, 0.f, 1.f, 250.f, 70.f, 0.35f);
    TestTrue(TEXT("reverse grows the angle"), Slow > Start);
    // ... more slowly than the unscaled model ...
    const float Full = RunHitch(Start, -150.f, 0.f, 1.f, 250.f, 70.f, 1.f);
    TestTrue(TEXT("scaled growth is slower than the pure model"), Slow < Full);
    // ... and never past the clamp.
    const float Long = RunHitch(Start, -300.f, 0.f, 60.f);
    TestTrue(FString::Printf(TEXT("clamped at 70 deg (got %.3f)"), FMath::RadiansToDegrees(Long)), FMath::RadiansToDegrees(Long) <= 70.f + 1e-3f);
    TestEqual(TEXT("reaches the clamp"), FMath::RadiansToDegrees(Long), 70.f, 0.01f);
    // A huge frame is clamped and substepped, and stays finite.
    const float Big = StepHitchAngle(Start, 500.f, 3.f, 250.f, 0.f, 10.f, FMath::DegreesToRadians(70.f), 0.35f);
    TestTrue(TEXT("finite after a 10 s frame"), FMath::IsFinite(Big) && FMath::Abs(Big) <= FMath::DegreesToRadians(70.f) + 1e-4f);
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaSpringTest, "Saskarta.Carrier.Spring",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)
bool FSaskartaSpringTest::RunTest(const FString&)
{
    using namespace SaskartaCarrierMathTest;
    // Critically damped: reaches the target without overshoot.
    {
        FSpring S;
        const float K = 100.f;
        float MaxX = 0.f;
        for (int32 I = 0; I < 300; ++I)
        {
            StepSpring(S, 1.f, K, CriticalDamping(K), Dt);
            MaxX = FMath::Max(MaxX, S.X);
        }
        TestEqual(TEXT("critical: settles at the target"), S.X, 1.f, 1e-3f);
        TestTrue(FString::Printf(TEXT("critical: no overshoot (max %.5f)"), MaxX), MaxX <= 1.f + 1e-3f);
    }
    // Under-damped: overshoots, then settles (the bob / sway character).
    {
        FSpring S;
        float MaxX = 0.f;
        for (int32 I = 0; I < 900; ++I)
        {
            StepSpring(S, 1.f, 120.f, 4.f, Dt);
            MaxX = FMath::Max(MaxX, S.X);
        }
        TestTrue(FString::Printf(TEXT("under-damped overshoots (max %.3f)"), MaxX), MaxX > 1.2f);
        TestEqual(TEXT("under-damped settles"), S.X, 1.f, 1e-2f);
    }
    // A constant external acceleration shifts the rest point by a / k.
    {
        FSpring S;
        for (int32 I = 0; I < 600; ++I)
        {
            StepSpring(S, 0.f, 50.f, CriticalDamping(50.f), Dt, 100.f);
        }
        TestEqual(TEXT("external accel offset = a / k"), S.X, 2.f, 1e-2f);
    }
    // Stiff spring, long frame: substeps keep it stable.
    {
        FSpring S;
        StepSpring(S, 1.f, 2000.f, CriticalDamping(2000.f), 0.2f);
        TestTrue(TEXT("stiff + 0.2 s frame stays bounded"), FMath::IsFinite(S.X) && FMath::Abs(S.X) < 2.f);
    }
    // Non-finite state resets.
    {
        FSpring S;
        S.X = std::numeric_limits<float>::quiet_NaN();
        StepSpring(S, 0.5f, 100.f, 20.f, Dt);
        TestTrue(TEXT("NaN resets near the target"), FMath::IsFinite(S.X) && FMath::Abs(S.X - 0.5f) < 0.01f);
    }
    // Zero or negative dt changes nothing.
    {
        FSpring S;
        S.X = 0.3f;
        S.V = 1.f;
        StepSpring(S, 0.f, 100.f, 20.f, 0.f);
        TestEqual(TEXT("dt 0: X unchanged"), S.X, 0.3f);
        TestEqual(TEXT("dt 0: V unchanged"), S.V, 1.f);
    }
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaCarrierHelpersTest, "Saskarta.Carrier.Helpers",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)
bool FSaskartaCarrierHelpersTest::RunTest(const FString&)
{
    using namespace SaskartaCarrierMath;
    const float MaxSteer = FMath::DegreesToRadians(30.f);
    // Bicycle model: atan(L w / v).
    TestEqual(TEXT("steer from yaw rate"), SteerFromYawRate(0.5f, 300.f, 120.f, MaxSteer, 60.f), FMath::Atan(120.f * 0.5f / 300.f), 1e-5f);
    TestEqual(TEXT("steer clamps"), SteerFromYawRate(5.f, 100.f, 120.f, MaxSteer, 60.f), MaxSteer, 1e-5f);
    TestTrue(TEXT("reverse flips the steer"), SteerFromYawRate(0.5f, -300.f, 120.f, MaxSteer, 60.f) < 0.f);
    TestTrue(TEXT("turning on the spot does not snap to full lock"), SteerFromYawRate(0.2f, 0.f, 120.f, MaxSteer, 60.f) < MaxSteer);

    TestEqual(TEXT("lateral accel"), LateralAccel(500.f, 1.f), 500.f);
    TestEqual(TEXT("clamped gain"), ClampedGain(1000.f, 0.005f, 3.f), 3.f);
    TestEqual(TEXT("clamped gain (negative)"), ClampedGain(-200.f, 0.005f, 3.f), -1.f);

    // Trailer tilt: the rear rising 25 cm over 250 cm pitches the nose down.
    const FVector2D Rise = TrailerPitchRoll(25.f, 60.f, 25.f, -60.f, 250.f);
    TestEqual(TEXT("rear up -> pitch = -asin(0.1)"), static_cast<float>(Rise.X), -FMath::Asin(0.1f), 1e-5f);
    TestEqual(TEXT("level -> no roll"), static_cast<float>(Rise.Y), 0.f, 1e-6f);
    // The right wheel (lateral +60) 12 cm higher lifts the right side: roll < 0; the wheel order does not matter.
    const FVector2D RightUp = TrailerPitchRoll(12.f, 60.f, 0.f, -60.f, 250.f);
    const FVector2D RightUpSwapped = TrailerPitchRoll(0.f, -60.f, 12.f, 60.f, 250.f);
    TestEqual(TEXT("right side up -> roll = -atan(12/120)"), static_cast<float>(RightUp.Y), -FMath::Atan(0.1f), 1e-5f);
    TestEqual(TEXT("wheel order does not matter"), static_cast<float>(RightUpSwapped.Y), static_cast<float>(RightUp.Y), 1e-6f);

    TestEqual(TEXT("wrap 3 pi / 2"), WrapRadians(1.5f * UE_PI), -UE_HALF_PI, 1e-4f);
    TestEqual(TEXT("wrap -pi/2"), WrapRadians(-UE_HALF_PI), -UE_HALF_PI, 1e-5f);
    return true;
}

namespace SaskartaCarrierMathTest
{
    /** SK_CarrierFull: coupler to capsule axle, and the coupler behind the turning centre. */
    static constexpr float FullLength = 278.5f;
    static constexpr float FullOffset = 78.f;

    static float DefaultHitchLimit(float ClearanceDeg = 3.f, float UserMaxDeg = 70.f)
    {
        const FSaskartaCarrierAnimTuning T;
        return SafeHitchAngle(T.CarrierFootprint.GetData(), T.CarrierFootprint.Num(), T.TrailerFootprint.GetData(), T.TrailerFootprint.Num(),
            FMath::DegreesToRadians(ClearanceDeg), FMath::DegreesToRadians(UserMaxDeg));
    }

    static FHitchLimits DefaultLimits()
    {
        FHitchLimits L;
        L.MaxPsiRad = DefaultHitchLimit();
        L.SoftZoneRad = FMath::DegreesToRadians(8.f);
        L.MaxRateRadS = FMath::DegreesToRadians(140.f);
        return L;
    }
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaHitchFootprintTest, "Saskarta.Carrier.Hitch.FootprintLimit",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)
bool FSaskartaHitchFootprintTest::RunTest(const FString&)
{
    using namespace SaskartaCarrierMathTest;
    const FSaskartaCarrierAnimTuning T;
    // The capsule's nose is 19 cm behind the coupler and 105 cm wide: the top views touch near 28 deg, not 70.
    const float Contact = FMath::RadiansToDegrees(FootprintContactAngle(T.CarrierFootprint.GetData(), T.CarrierFootprint.Num(),
        T.TrailerFootprint.GetData(), T.TrailerFootprint.Num(), UE_HALF_PI));
    TestTrue(FString::Printf(TEXT("contact near 28 deg (got %.2f)"), Contact), Contact > 26.f && Contact < 30.f);
    const float Limit = FMath::RadiansToDegrees(DefaultHitchLimit());
    TestEqual(TEXT("limit = contact - clearance"), Limit, Contact - 3.f, 0.01f);
    // The user cap still wins when it is tighter; unusable footprints fall back to it.
    TestEqual(TEXT("user cap"), FMath::RadiansToDegrees(DefaultHitchLimit(3.f, 15.f)), 15.f, 1e-3f);
    const FVector2D Two[2] = { FVector2D(0, 1), FVector2D(1, 1) };
    TestEqual(TEXT("degenerate footprint -> user cap"), FMath::RadiansToDegrees(SafeHitchAngle(Two, 2, Two, 2, 0.f, FMath::DegreesToRadians(40.f))), 40.f, 1e-3f);
    const FVector2D Box[4] = { FVector2D(-10, -10), FVector2D(10, -10), FVector2D(10, 10), FVector2D(-10, 10) };
    TestEqual(TEXT("overlapping when straight -> -1"), FootprintContactAngle(Box, 4, Box, 4, 1.f), -1.f);
    // Closed form: a 2-wide trailer whose front edge is 1.5 behind the coupler, behind a carrier
    // whose rear edge runs through the coupler. Its front corner (1, -1.5) reaches y = 0 after atan2(1.5, 1).
    const FVector2D Car[4] = { FVector2D(-5, 0), FVector2D(5, 0), FVector2D(5, 5), FVector2D(-5, 5) };
    const FVector2D Tr[4] = { FVector2D(-1, -1.5), FVector2D(1, -1.5), FVector2D(1, -10), FVector2D(-1, -10) };
    const float Expected = FMath::RadiansToDegrees(FMath::Atan2(1.5f, 1.f));
    TestEqual(TEXT("square trailer contact"), FMath::RadiansToDegrees(FootprintContactAngle(Car, 4, Tr, 4, UE_PI)), Expected, 0.01f);
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaHitchSoftStopTest, "Saskarta.Carrier.Hitch.SoftStop",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)
bool FSaskartaHitchSoftStopTest::RunTest(const FString&)
{
    using namespace SaskartaCarrierMathTest;
    const FHitchLimits L = DefaultLimits();
    const float MaxDeg = FMath::RadiansToDegrees(L.MaxPsiRad);
    // Turning on the spot at 90 deg/s (the pawn's turn rate): the coupler swings sideways and
    // the capsule eases onto the limit without passing it, never faster than the rate cap.
    float Psi = 0.f;
    float MaxStepDeg = 0.f;
    float Peak = 0.f;
    for (int32 I = 0; I < 5 * 60; ++I)
    {
        const float Next = StepHitchAngleLimited(Psi, 0.f, FMath::DegreesToRadians(90.f), FullLength, FullOffset, Dt, L, 0.35f);
        MaxStepDeg = FMath::Max(MaxStepDeg, FMath::Abs(FMath::RadiansToDegrees(Next - Psi)));
        Psi = Next;
        Peak = FMath::Max(Peak, FMath::Abs(FMath::RadiansToDegrees(Psi)));
    }
    TestTrue(FString::Printf(TEXT("never past the limit (peak %.3f, limit %.3f)"), Peak, MaxDeg), Peak <= MaxDeg + 1e-3f);
    TestTrue(FString::Printf(TEXT("settles close to the limit (%.3f)"), Peak), Peak > MaxDeg - 1.5f);
    TestTrue(FString::Printf(TEXT("rate capped (max step %.3f deg)"), MaxStepDeg), MaxStepDeg <= 140.f * Dt + 1e-3f);
    // The opening rate fades to 0 at the limit; the closing rate is untouched.
    const float Open = LimitHitchRate(L.MaxPsiRad - FMath::DegreesToRadians(1.f), 1.f, L);
    TestTrue(FString::Printf(TEXT("1 deg from the limit the opening rate is cushioned (%.3f)"), Open), Open > 0.f && Open < 0.1f);
    TestEqual(TEXT("closing rate untouched"), LimitHitchRate(L.MaxPsiRad - 0.01f, -1.f, L), -1.f, 1e-6f);
    TestEqual(TEXT("free below the zone"), LimitHitchRate(0.1f, 1.f, L), 1.f, 1e-6f);
    // Driving on straightens it again, smoothly.
    for (int32 I = 0; I < 12 * 60; ++I)
    {
        Psi = StepHitchAngleLimited(Psi, 300.f, 0.f, FullLength, FullOffset, Dt, L, 0.35f);
    }
    TestTrue(FString::Printf(TEXT("straight again after 12 s at 3 m/s (%.3f deg)"), FMath::RadiansToDegrees(Psi)), FMath::Abs(FMath::RadiansToDegrees(Psi)) < 1.f);
    // Reverse still jackknifes slowly, into the cushioned limit.
    Psi = FMath::DegreesToRadians(5.f);
    TestTrue(TEXT("reverse grows the angle"), StepHitchAngleLimited(Psi, -150.f, 0.f, FullLength, FullOffset, Dt, L, 0.35f) > Psi);
    for (int32 I = 0; I < 60 * 60; ++I)
    {
        Psi = StepHitchAngleLimited(Psi, -300.f, 0.f, FullLength, FullOffset, Dt, L, 0.35f);
    }
    TestTrue(FString::Printf(TEXT("reverse stops at the limit (%.3f)"), FMath::RadiansToDegrees(Psi)), Psi <= L.MaxPsiRad + 1e-5f && Psi > L.MaxPsiRad - FMath::DegreesToRadians(1.5f));
    // A teleport-sized yaw rate cannot fling it: one frame moves it at most the rate cap.
    const float Flung = StepHitchAngleLimited(0.f, 0.f, FMath::DegreesToRadians(1800.f), FullLength, FullOffset, Dt, L, 0.35f);
    TestTrue(TEXT("one frame of a 1800 deg/s spike moves <= the rate cap"), FMath::Abs(FMath::RadiansToDegrees(Flung)) <= 140.f * Dt + 1e-3f);
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaHitchSoftClampTest, "Saskarta.Carrier.Hitch.SoftClampAndTeleport",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)
bool FSaskartaHitchSoftClampTest::RunTest(const FString&)
{
    using namespace SaskartaCarrierMathTest;
    // The hitch + sway output: identity below the knee, continuous, never at or past the limit.
    TestEqual(TEXT("identity below the knee"), SoftClampAngle(10.f, 25.f, 3.f), 10.f);
    TestEqual(TEXT("continuous at the knee"), SoftClampAngle(22.0001f, 25.f, 3.f), 22.f, 1e-3f);
    TestTrue(TEXT("below the limit at +4 deg of sway"), SoftClampAngle(29.f, 25.f, 3.f) < 25.f);
    TestTrue(TEXT("monotonic"), SoftClampAngle(24.f, 25.f, 3.f) < SoftClampAngle(26.f, 25.f, 3.f));
    TestEqual(TEXT("odd"), SoftClampAngle(-29.f, 25.f, 3.f), -SoftClampAngle(29.f, 25.f, 3.f));
    const float MaxSpeed = 2500.f;
    const float MaxYaw = FMath::DegreesToRadians(400.f);
    // Driving is never a teleport: 5 m/s and the 90 deg/s turn, at 60 fps and in a 0.25 s hitch.
    TestFalse(TEXT("60 fps drive"), IsTeleportStep(500.f / 60.f, FMath::DegreesToRadians(1.5f), 1.f / 60.f, 250.f, MaxSpeed, MaxYaw));
    TestFalse(TEXT("0.25 s frame drive"), IsTeleportStep(125.f, FMath::DegreesToRadians(22.5f), 0.25f, 250.f, MaxSpeed, MaxYaw));
    TestFalse(TEXT("standing still"), IsTeleportStep(0.f, 0.f, 1.f / 60.f, 250.f, MaxSpeed, MaxYaw));
    // Checkpoints, respawns and sequence cuts are.
    TestTrue(TEXT("50 m jump"), IsTeleportStep(5000.f, 0.f, 1.f / 60.f, 250.f, MaxSpeed, MaxYaw));
    TestTrue(TEXT("turned round in one frame"), IsTeleportStep(0.f, UE_PI, 1.f / 60.f, 250.f, MaxSpeed, MaxYaw));
    TestTrue(TEXT("1 m in one 60 fps frame (60 m/s)"), IsTeleportStep(100.f, 0.f, 1.f / 60.f, 250.f, MaxSpeed, MaxYaw));
    TestTrue(TEXT("NaN"), IsTeleportStep(std::numeric_limits<float>::quiet_NaN(), 0.f, 1.f / 60.f, 250.f, MaxSpeed, MaxYaw));
    return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS
