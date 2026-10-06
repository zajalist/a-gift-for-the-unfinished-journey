// Automation tests for the storm shells' pure logic (task STORM-SHELLS): the gate hysteresis, the cvar
// tiers, the PPV weight, and the shader math mirrored from Shaders/StormShells.ush (far root, height band,
// gust drift, layer alpha, storm response) against the numbers in docs/look/STORM_SHELLS.md.
//
// Written offline (fail-first waived, as R33). Run after the build:
//   Automation RunTests Saskarta.StormShells

#include "Misc/AutomationTest.h"

#if WITH_DEV_AUTOMATION_TESTS

#include "SaskartaStormShellsLogic.h"

#define SASKARTA_SHELLS_TEST_FLAGS (EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)

namespace SaskartaStormShellsTest
{
    static const FVector4f Band(1.2f, 18.f, 45.f, 160.f);
    static const float Radii[4] = {30.f, 55.f, 90.f, 150.f};
    static const float Slab[4] = {18.f, 30.f, 45.f, 50.f};
    static constexpr float Sigma = 0.003f;

    static FVector3f Ray(float YawDeg, float PitchDeg)
    {
        const float Y = FMath::DegreesToRadians(YawDeg), P = FMath::DegreesToRadians(PitchDeg);
        return FVector3f(FMath::Cos(P) * FMath::Cos(Y), FMath::Cos(P) * FMath::Sin(Y), FMath::Sin(P));
    }
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaStormShellsGateTest, "Saskarta.StormShells.Gate", SASKARTA_SHELLS_TEST_FLAGS)
bool FSaskartaStormShellsGateTest::RunTest(const FString& Parameters)
{
    using namespace SaskartaStormShells;
    TestFalse(TEXT("off stays off at 0"), NextGate(false, 0.f));
    TestFalse(TEXT("off stays off inside the band"), NextGate(false, 0.01f));
    TestTrue(TEXT("off -> on above 0.015"), NextGate(false, 0.02f));
    TestTrue(TEXT("on stays on inside the band"), NextGate(true, 0.01f));
    TestFalse(TEXT("on -> off at 0.005"), NextGate(true, 0.005f));
    TestFalse(TEXT("on -> off at 0"), NextGate(true, 0.f));
    TestTrue(TEXT("the Valley key (0.28) is on"), NextGate(false, 0.28f));
    TestFalse(TEXT("Above the clouds (0.0) is off"), NextGate(true, 0.0f));

    // A slow ramp across the band flips once each way, never flickers.
    bool bOn = false;
    int32 Flips = 0;
    for (int32 i = 0; i <= 400; ++i)
    {
        const float S = 0.02f * FMath::Abs(FMath::Sin(i * 0.0157f)) + 0.0005f * ((i % 2) ? 1.f : -1.f);
        const bool bNext = NextGate(bOn, S);
        Flips += (bNext != bOn) ? 1 : 0;
        bOn = bNext;
    }
    TestTrue(TEXT("a noisy ramp through the band flips only at the thresholds"), Flips <= 4);
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaStormShellsTierTest, "Saskarta.StormShells.Tier", SASKARTA_SHELLS_TEST_FLAGS)
bool FSaskartaStormShellsTierTest::RunTest(const FString& Parameters)
{
    using namespace SaskartaStormShells;
    const FSaskartaStormShellTier High = TierFor(1, 4, 3);
    TestEqual(TEXT("default shells"), High.Shells, 4);
    TestEqual(TEXT("default detail"), High.DetailShells, 3);
    const FSaskartaStormShellTier Low = TierFor(1, 3, 2);
    TestEqual(TEXT("low shells"), Low.Shells, 3);
    TestEqual(TEXT("low detail"), Low.DetailShells, 2);
    TestEqual(TEXT("disabled -> 0 shells"), TierFor(0, 4, 3).Shells, 0);
    TestEqual(TEXT("layers 0 -> 0 shells"), TierFor(1, 0, 3).Shells, 0);
    TestEqual(TEXT("layers clamp to 4"), TierFor(1, 9, 9).Shells, 4);
    TestEqual(TEXT("detail clamps to the shells"), TierFor(1, 2, 4).DetailShells, 2);
    TestEqual(TEXT("negative detail clamps to 0"), TierFor(1, 4, -1).DetailShells, 0);

    TestEqual(TEXT("gate on, shells -> weight 1"), PassWeight(true, High), 1.f);
    TestEqual(TEXT("gate off -> weight 0"), PassWeight(false, High), 0.f);
    TestEqual(TEXT("gate on, no shells -> weight 0"), PassWeight(true, TierFor(0, 4, 3)), 0.f);
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaStormShellsRootTest, "Saskarta.StormShells.FarRoot", SASKARTA_SHELLS_TEST_FLAGS)
bool FSaskartaStormShellsRootTest::RunTest(const FString& Parameters)
{
    using namespace SaskartaStormShells;
    using namespace SaskartaStormShellsTest;
    for (float Yaw : {0.f, 37.f, 180.f, -121.f})
    {
        for (float Pitch : {-60.f, -10.f, 0.f, 12.f, 70.f})
        {
            const FVector3f D = Ray(Yaw, Pitch);
            for (float R : Radii)
            {
                const float T = FarRootCentered(D, R);
                const FVector3f P = D * T;
                TestTrue(TEXT("the hit is ahead"), T > 0.f);
                TestTrue(TEXT("the hit is on the cylinder"), FMath::IsNearlyEqual(FMath::Sqrt(P.X * P.X + P.Y * P.Y), R, R * 1e-4f));
                TestTrue(TEXT("the general root agrees at offset 0"), FMath::IsNearlyEqual(FarRootOffset(FVector2f::ZeroVector, D, R), T, T * 1e-4f));
                const FVector2f O(2.f, -1.5f);  // the eye a couple of metres off the axis
                const float To = FarRootOffset(O, D, R);
                const FVector2f Po(O.X + To * D.X, O.Y + To * D.Y);
                TestTrue(TEXT("the offset root is ahead and on the cylinder"), To > 0.f && FMath::IsNearlyEqual(Po.Size(), R, R * 1e-3f));
            }
        }
    }
    // Zenith and nadir: the |d.xy| clamp keeps t finite (a NaN in scene colour spreads through bloom and TSR).
    TestTrue(TEXT("zenith stays finite"), FMath::IsFinite(FarRootCentered(FVector3f(0.f, 0.f, 1.f), 150.f)));
    TestTrue(TEXT("nadir stays finite"), FMath::IsFinite(FarRootCentered(FVector3f(0.f, 0.f, -1.f), 30.f)));
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaStormShellsBandTest, "Saskarta.StormShells.HeightBand", SASKARTA_SHELLS_TEST_FLAGS)
bool FSaskartaStormShellsBandTest::RunTest(const FString& Parameters)
{
    using namespace SaskartaStormShells;
    using namespace SaskartaStormShellsTest;
    TestTrue(TEXT("full at the ground"), FMath::IsNearlyEqual(HeightProfile(0.f, Band), 1.f, 1e-4f));
    TestTrue(TEXT("half at the halving height"), FMath::IsNearlyEqual(HeightProfile(18.f, Band), 0.5f, 1e-3f));
    TestTrue(TEXT("gone by the top"), HeightProfile(45.f, Band) < 1e-5f);
    TestTrue(TEXT("full in a valley 60 m below"), FMath::IsNearlyEqual(HeightProfile(-60.f, Band), 1.f, 1e-4f));
    TestTrue(TEXT("gone 160 m below"), HeightProfile(-160.f, Band) < 1e-5f);
    for (float H = -200.f; H < 60.f; H += 1.f)
    {
        const float V = HeightProfile(H, Band);
        TestTrue(TEXT("0..1"), V >= 0.f && V <= 1.f);
        if (H >= 0.f)
        {
            TestTrue(TEXT("falls with height above the ground"), HeightProfile(H + 1.f, Band) <= V + 1e-6f);
        }
    }

    // The doc's check: a 40 m tower 90 m away keeps its top readable. The 90 m and 150 m shells are behind
    // it or above the band; only the 30 m and 55 m shells add dust. At storm 1, no gust front.
    const float TopZ = 40.f - Band.X;
    const FVector3f D = FVector3f(90.f, 0.f, TopZ).GetSafeNormal();
    const float RayToTower = FVector3f(90.f, 0.f, TopZ).Size();
    const float Dxy = FMath::Sqrt(D.X * D.X + D.Y * D.Y);
    const float PathK = FMath::Min(1.f / Dxy, 2.f);
    auto DustOverTowerTop = [&](float N)
    {
        float Trans = 1.f;
        for (int32 i = 0; i < 4; ++i)
        {
            const float T = FarRootCentered(D, Radii[i]);
            const float Vis = FMath::Clamp((RayToTower - T) / (0.3f * Radii[i]), 0.f, 1.f);
            const float Prof = HeightProfile(T * D.Z + Band.X, Band);
            Trans *= 1.f - LayerAlpha(Sigma, 1.f, Slab[i], PathK, N, 1.f, Prof, Vis);
        }
        return 1.f - Trans;
    };
    const float Densest = DustOverTowerTop(1.f);
    const float Typical = DustOverTowerTop(0.5f);
    AddInfo(FString::Printf(TEXT("dust over a 40 m tower top at 90 m: densest %.1f %%, typical %.1f %%"), Densest * 100.f, Typical * 100.f));
    TestTrue(TEXT("a tall object's top stays readable in the densest streak (< 8 %)"), Densest < 0.08f);
    TestTrue(TEXT("and in typical dust (< 4.5 %)"), Typical < 0.045f);
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaStormShellsGustTest, "Saskarta.StormShells.GustDrift", SASKARTA_SHELLS_TEST_FLAGS)
bool FSaskartaStormShellsGustTest::RunTest(const FString& Parameters)
{
    using namespace SaskartaStormShells;
    const double V = 12.0, A = 0.35, P = 7.0;
    for (double T = 0.0; T < 120.0; T += 0.37)
    {
        const double H = 1e-3;
        const double Rate = (GustDriftM(T + H, V, A, P) - GustDriftM(T - H, V, A, P)) / (2.0 * H);
        const double Want = V * (1.0 + A * Gust(T, P));
        TestTrue(TEXT("the drift's rate is the gusting wind speed"), FMath::IsNearlyEqual(Rate, Want, 1e-3));
        TestTrue(TEXT("the drift never runs backwards"), Rate > 0.0);
    }
    TestTrue(TEXT("gust stays within +-1"), FMath::Abs(Gust(3.3, P)) <= 1.0);
    // Over an hour the mean speed is the wind speed (the gust integrates to ~0).
    const double Hour = GustDriftM(3600.0, V, A, P) - GustDriftM(0.0, V, A, P);
    TestTrue(TEXT("an hour of drift is about 43 km"), FMath::Abs(Hour - V * 3600.0) < 100.0);
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaStormShellsAlphaTest, "Saskarta.StormShells.Alpha", SASKARTA_SHELLS_TEST_FLAGS)
bool FSaskartaStormShellsAlphaTest::RunTest(const FString& Parameters)
{
    using namespace SaskartaStormShells;
    using namespace SaskartaStormShellsTest;
    // The doc: at a dense streak looking level, per-shell alpha about 0.05 / 0.08 / 0.12 / 0.13.
    const float Want[4] = {0.052f, 0.086f, 0.126f, 0.139f};
    for (int32 i = 0; i < 4; ++i)
    {
        const float A = LayerAlpha(Sigma, 1.f, Slab[i], 1.f, 1.f, 1.f, 1.f, 1.f);
        TestTrue(FString::Printf(TEXT("shell %d alpha %.3f"), i, A), FMath::IsNearlyEqual(A, Want[i], 0.003f));
        TestTrue(TEXT("inside the thin-veil brief (<= 0.2)"), A <= 0.2f);
    }
    TestEqual(TEXT("storm 0 draws nothing"), LayerAlpha(Sigma, 0.f, 50.f, 2.f, 1.f, 1.5f, 1.f, 1.f), 0.f);
    TestEqual(TEXT("occluded draws nothing"), LayerAlpha(Sigma, 1.f, 50.f, 2.f, 1.f, 1.5f, 1.f, 0.f), 0.f);

    TestEqual(TEXT("response at 0"), StormResponse(0.f, 0.6f, 1.f), 0.f);
    TestTrue(TEXT("response at 1"), FMath::IsNearlyEqual(StormResponse(1.f, 0.6f, 1.f), 1.f));
    TestTrue(TEXT("the Valley's 0.28 gives about half the peak"), FMath::IsNearlyEqual(StormResponse(0.28f, 0.6f, 1.f), 0.466f, 0.01f));
    TestTrue(TEXT("exponent 1 is linear"), FMath::IsNearlyEqual(StormResponse(0.28f, 1.f, 1.f), 0.28f));
    TestTrue(TEXT("clamped above 1"), FMath::IsNearlyEqual(StormResponse(3.f, 0.6f, 1.f), 1.f));
    return true;
}

#undef SASKARTA_SHELLS_TEST_FLAGS

#endif // WITH_DEV_AUTOMATION_TESTS
