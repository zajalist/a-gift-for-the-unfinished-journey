// Automation tests for the ambience director's pure logic and the manifest importer (task AMBIENCE2).
//
// Written offline with the implementation (fail-first waived, ruling R33); the next closed-editor
// build compiles them and an editor session runs them:
//   Automation RunTests Saskarta.Ambience
// Saskarta.Ambience.ManifestFile reads the real Saved/GameAudio/Ambience2/manifest.json (skipped
// with a warning when it is absent).

#include "Misc/AutomationTest.h"

#if WITH_DEV_AUTOMATION_TESTS

#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "SaskartaAmbienceAsset.h"
#include "SaskartaAmbienceImport.h"
#include "SaskartaAmbienceLogic.h"
#include "SaskartaAmbienceSettings.h"
#include "UObject/Package.h"

#define SASKARTA_AMBIENCE_TEST_FLAGS (EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)

namespace SaskartaAmbienceTest
{
    static FSaskartaAmbienceZone Zone(const TCHAR* Name, float From, float To, float Xfade)
    {
        FSaskartaAmbienceZone Z;
        Z.Name = Name;
        Z.FromM = From;
        Z.ToM = To;
        Z.XfadeM = Xfade;
        return Z;
    }

    /** The manifest's zone table. */
    static TArray<FSaskartaAmbienceZone> RoadZones()
    {
        return {
            Zone(TEXT("Valley"), 0.f, 2020.f, 150.f),
            Zone(TEXT("Basin"), 2020.f, 2810.f, 150.f),
            Zone(TEXT("Foot"), 2810.f, 3490.f, 150.f),
            Zone(TEXT("Climb"), 3490.f, 4200.f, 150.f),
            Zone(TEXT("Cloud"), 4200.f, 4480.f, 120.f),
            Zone(TEXT("Above"), 4480.f, 5010.f, 120.f),
        };
    }

    static FSaskartaVoiceInfo Voice(float Priority, float Volume, double StartS)
    {
        FSaskartaVoiceInfo V;
        V.Priority = Priority;
        V.Volume = Volume;
        V.StartS = StartS;
        return V;
    }
}

// ============================================================================ zones

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaAmbienceZoneWeightsTest, "Saskarta.Ambience.ZoneWeights", SASKARTA_AMBIENCE_TEST_FLAGS)
bool FSaskartaAmbienceZoneWeightsTest::RunTest(const FString&)
{
    using namespace SaskartaAmbienceTest;
    const TArray<FSaskartaAmbienceZone> Zones = RoadZones();
    TArray<float> W;

    // Road ends at full level (no ramp before the first zone or after the last).
    FSaskartaAmbienceLogic::ZoneWeights(Zones, 0.f, W);
    TestEqual(TEXT("Valley at 0 m"), W[0], 1.f, 1e-4f);
    FSaskartaAmbienceLogic::ZoneWeights(Zones, 5009.f, W);
    TestEqual(TEXT("Above at the hut"), W[5], 1.f, 1e-4f);

    // Mid-zone: only that zone.
    FSaskartaAmbienceLogic::ZoneWeights(Zones, 1000.f, W);
    TestEqual(TEXT("Valley mid"), W[0], 1.f, 1e-4f);
    TestEqual(TEXT("Basin silent mid-Valley"), W[1], 0.f, 1e-4f);

    // A boundary is the 50/50 point of an equal sin^2/cos^2 crossfade.
    FSaskartaAmbienceLogic::ZoneWeights(Zones, 2020.f, W);
    TestEqual(TEXT("Valley at the Basin boundary"), W[0], 0.5f, 1e-4f);
    TestEqual(TEXT("Basin at its start"), W[1], 0.5f, 1e-4f);

    // The ramp is xfade wide, centred on the boundary: +-75 m for 150 m.
    FSaskartaAmbienceLogic::ZoneWeights(Zones, 2020.f - 75.f, W);
    TestEqual(TEXT("Valley full 75 m before"), W[0], 1.f, 1e-4f);
    TestEqual(TEXT("Basin silent 75 m before"), W[1], 0.f, 1e-4f);
    FSaskartaAmbienceLogic::ZoneWeights(Zones, 2020.f + 75.f, W);
    TestEqual(TEXT("Valley silent 75 m after"), W[0], 0.f, 1e-4f);
    TestEqual(TEXT("Basin full 75 m after"), W[1], 1.f, 1e-4f);

    // Equal-power in the sense of the brief: neighbours sum to 1 all the way through, and the
    // curve is sin^2 (a quarter of the way in: sin^2(pi/8) = 0.1464).
    FSaskartaAmbienceLogic::ZoneWeights(Zones, 2020.f - 37.5f, W);
    TestEqual(TEXT("Basin a quarter in"), W[1], 0.14645f, 1e-3f);
    for (float M = 0.f; M <= 5009.f; M += 7.f)
    {
        FSaskartaAmbienceLogic::ZoneWeights(Zones, M, W);
        float Sum = 0.f;
        for (const float X : W) Sum += X;
        if (!TestEqual(*FString::Printf(TEXT("weights sum to 1 at %.0f m"), M), Sum, 1.f, 1e-3f))
        {
            break;
        }
    }

    // The Cloud boundaries use the Cloud's 120 m on both sides (Climb's ramp out too).
    FSaskartaAmbienceLogic::ZoneWeights(Zones, 4200.f - 60.f, W);
    TestEqual(TEXT("Climb full 60 m before the cloud"), W[3], 1.f, 1e-4f);
    TestEqual(TEXT("Cloud silent 60 m before"), W[4], 0.f, 1e-4f);

    FSaskartaAmbienceLogic::ZoneWeights(Zones, 3050.f, W);
    TestEqual(TEXT("dominant at 3,050 m is Foot"), FSaskartaAmbienceLogic::DominantZone(W), 2);

    // The zone-weighted wind multiplier (1 in the Valley, 0.4 in the Cloud, halfway at the boundary).
    TArray<FSaskartaAmbienceZone> Z2 = Zones;
    Z2[3].WindMultiplier = 0.8f;
    Z2[4].WindMultiplier = 0.4f;
    FSaskartaAmbienceLogic::ZoneWeights(Z2, 4200.f, W);
    TestEqual(TEXT("wind multiplier at the cloud boundary"),
        FSaskartaAmbienceLogic::WeightedZoneValue(Z2, W, &FSaskartaAmbienceZone::WindMultiplier, 1.f), 0.6f, 1e-3f);
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaAmbienceStormTest, "Saskarta.Ambience.StormBeds", SASKARTA_AMBIENCE_TEST_FLAGS)
bool FSaskartaAmbienceStormTest::RunTest(const FString&)
{
    // Wind beds: breeze only up to 0.15, strong only at 0.5, gale only from 0.9.
    FVector G = FSaskartaAmbienceLogic::StormWindGains(0.1f);
    TestEqual(TEXT("breeze at 0.1"), static_cast<float>(G.X), 1.f, 1e-4f);
    TestEqual(TEXT("strong at 0.1"), static_cast<float>(G.Y), 0.f, 1e-4f);
    G = FSaskartaAmbienceLogic::StormWindGains(0.5f);
    TestEqual(TEXT("breeze at 0.5"), static_cast<float>(G.X), 0.f, 1e-4f);
    TestEqual(TEXT("strong at 0.5"), static_cast<float>(G.Y), 1.f, 1e-4f);
    TestEqual(TEXT("gale at 0.5"), static_cast<float>(G.Z), 0.f, 1e-4f);
    G = FSaskartaAmbienceLogic::StormWindGains(0.95f);
    TestEqual(TEXT("gale at 0.95"), static_cast<float>(G.Z), 1.f, 1e-4f);
    TestEqual(TEXT("strong at 0.95"), static_cast<float>(G.Y), 0.f, 1e-4f);
    // Crossfades sum to 1 (sin^2 + cos^2).
    for (float I = 0.f; I <= 1.f; I += 0.05f)
    {
        const FVector X = FSaskartaAmbienceLogic::StormWindGains(I);
        TestEqual(*FString::Printf(TEXT("wind gains sum at %.2f"), I), static_cast<float>(X.X + X.Y + X.Z), 1.f, 1e-3f);
    }

    // Bed modifiers.
    FSaskartaAmbienceBed Insects;
    Insects.VolumeDb = -10.f;
    Insects.StormMode = ESaskartaBedStormMode::InverseToRef;
    Insects.StormRef = 0.7f;
    Insects.OffAfterRoadM = 1700.f;
    TestEqual(TEXT("insects at I 0.35"), FSaskartaAmbienceLogic::BedGain(Insects, 500.f, 0.35f), FSaskartaAmbienceLogic::DbToLin(-10.f) * 0.5f, 1e-4f);
    TestEqual(TEXT("insects off at I 0.7"), FSaskartaAmbienceLogic::BedGain(Insects, 500.f, 0.7f), 0.f, 1e-5f);
    TestEqual(TEXT("insects off after 1,700 m"), FSaskartaAmbienceLogic::BedGain(Insects, 1701.f, 0.f), 0.f, 1e-5f);

    FSaskartaAmbienceBed Grass;
    Grass.VolumeDb = -2.f;
    Grass.ExtraFromM = 1550.f;
    Grass.ExtraToM = 2020.f;
    Grass.ExtraDb = -4.f;
    TestEqual(TEXT("grass -2 dB in the valley"), FSaskartaAmbienceLogic::BedGain(Grass, 1000.f, 0.8f), FSaskartaAmbienceLogic::DbToLin(-2.f), 1e-4f);
    TestEqual(TEXT("grass -6 dB on the ridge"), FSaskartaAmbienceLogic::BedGain(Grass, 1800.f, 0.8f), FSaskartaAmbienceLogic::DbToLin(-6.f), 1e-4f);

    TestEqual(TEXT("sand hiss x I^2"), FSaskartaAmbienceLogic::StormFactor(ESaskartaBedStormMode::Squared, 0.f, 0.5f), 0.25f, 1e-5f);
    TestEqual(TEXT("sand on metal at 0.5"), FSaskartaAmbienceLogic::StormFactor(ESaskartaBedStormMode::AboveHalf, 0.f, 0.5f), 0.f, 1e-5f);
    TestEqual(TEXT("sand on metal at 0.75"), FSaskartaAmbienceLogic::StormFactor(ESaskartaBedStormMode::AboveHalf, 0.f, 0.75f), 0.5f, 1e-5f);

    // Gusts: none under 0.15; lerp(90, 20, I) +- 30 %.
    TestTrue(TEXT("no gusts at 0.1"), FSaskartaAmbienceLogic::GustIntervalS(0.1f, 0.5f) < 0.f);
    TestEqual(TEXT("gust mid-jitter at I 1"), FSaskartaAmbienceLogic::GustIntervalS(1.f, 0.5f), 20.f, 1e-3f);
    TestEqual(TEXT("gust shortest at I 0.5"), FSaskartaAmbienceLogic::GustIntervalS(0.5f, 0.f), 55.f * 0.7f, 1e-3f);
    TestEqual(TEXT("gust longest at I 0.5"), FSaskartaAmbienceLogic::GustIntervalS(0.5f, 1.f), 55.f * 1.3f, 1e-3f);
    return true;
}

// ============================================================================ Geiger

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaAmbienceDoseTest, "Saskarta.Ambience.Dose", SASKARTA_AMBIENCE_TEST_FLAGS)
bool FSaskartaAmbienceDoseTest::RunTest(const FString&)
{
    const TArray<FVector2D> Table = { {0, 0.5}, {1550, 0.5}, {2150, 0.6}, {2600, 10}, {2810, 3}, {4480, 0.3}, {4700, 0.3}, {4990, 8} };
    TestEqual(TEXT("valley"), FSaskartaAmbienceLogic::DoseAtRoadM(Table, 800.f), 0.5f, 1e-4f);
    TestEqual(TEXT("the platform peak"), FSaskartaAmbienceLogic::DoseAtRoadM(Table, 2600.f), 10.f, 1e-4f);
    TestEqual(TEXT("halfway down from the platform"), FSaskartaAmbienceLogic::DoseAtRoadM(Table, 2705.f), 6.5f, 1e-3f);
    TestEqual(TEXT("clamped before the table"), FSaskartaAmbienceLogic::DoseAtRoadM(Table, -50.f), 0.5f, 1e-4f);
    TestEqual(TEXT("clamped after the table"), FSaskartaAmbienceLogic::DoseAtRoadM(Table, 6000.f), 8.f, 1e-4f);
    TestEqual(TEXT("empty table"), FSaskartaAmbienceLogic::DoseAtRoadM(TArray<FVector2D>(), 100.f), 0.f, 1e-6f);

    // Spikes: a gust x2.5 held, then decaying with tau 3 s; capped at 60.
    FSaskartaDoseSpike Gust;
    Gust.Cause = TEXT("Gust");
    Gust.Multiplier = 2.5f;
    Gust.HoldUntilS = 10.0;
    Gust.CapCps = 60.f;
    TestEqual(TEXT("held"), FSaskartaAmbienceLogic::SpikeMultiplier(Gust, 5.0), 2.5f, 1e-4f);
    TestEqual(TEXT("one tau after"), FSaskartaAmbienceLogic::SpikeMultiplier(Gust, 13.0), 1.f + 1.5f * FMath::Exp(-1.f), 1e-4f);
    TestEqual(TEXT("road 10 x gust"), FSaskartaAmbienceLogic::ComposeDose(10.f, { Gust }, 5.0), 25.f, 1e-3f);
    TestEqual(TEXT("gust capped at 60"), FSaskartaAmbienceLogic::ComposeDose(40.f, { Gust }, 5.0), 60.f, 1e-3f);
    FSaskartaDoseSpike Dust;
    Dust.Multiplier = 1.8f;
    Dust.HoldUntilS = 10.0;
    TestEqual(TEXT("the strongest spike wins (no stacking)"), FSaskartaAmbienceLogic::ComposeDose(2.f, { Gust, Dust }, 5.0), 5.f, 1e-3f);
    TestEqual(TEXT("no spikes"), FSaskartaAmbienceLogic::ComposeDose(3.f, {}, 5.0), 3.f, 1e-4f);

    // The alarm chirp: rising through 6 only, with a 20 s cooldown.
    TestTrue(TEXT("chirps rising through 6"), FSaskartaAmbienceLogic::ShouldChirp(5.f, 6.5f, 6.f, 100.0, 50.0, 20.f));
    TestFalse(TEXT("no chirp while already above"), FSaskartaAmbienceLogic::ShouldChirp(7.f, 8.f, 6.f, 100.0, 50.0, 20.f));
    TestFalse(TEXT("no chirp falling"), FSaskartaAmbienceLogic::ShouldChirp(8.f, 5.f, 6.f, 100.0, 50.0, 20.f));
    TestFalse(TEXT("no chirp inside the cooldown"), FSaskartaAmbienceLogic::ShouldChirp(5.f, 7.f, 6.f, 100.0, 90.0, 20.f));
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaAmbiencePoissonTest, "Saskarta.Ambience.PoissonRate", SASKARTA_AMBIENCE_TEST_FLAGS)
bool FSaskartaAmbiencePoissonTest::RunTest(const FString&)
{
    // Rate from dose: 1..80 per second.
    TestEqual(TEXT("no dose, no clicks"), FSaskartaAmbienceLogic::PoissonRate(0.f), 0.f, 1e-6f);
    TestEqual(TEXT("floor 1/s"), FSaskartaAmbienceLogic::PoissonRate(0.3f), 1.f, 1e-5f);
    TestEqual(TEXT("floor configurable (0.3 keeps the Above calm)"), FSaskartaAmbienceLogic::PoissonRate(0.3f, 0.3f), 0.3f, 1e-5f);
    TestEqual(TEXT("in range"), FSaskartaAmbienceLogic::PoissonRate(10.f), 10.f, 1e-5f);
    TestEqual(TEXT("ceiling 80/s"), FSaskartaAmbienceLogic::PoissonRate(200.f), 80.f, 1e-5f);

    // Inter-arrival: -ln(U) / rate; U = 1/e gives exactly 1 / rate.
    TestEqual(TEXT("-ln(U)/rate"), FSaskartaAmbienceLogic::PoissonIntervalS(4.f, FMath::Exp(-1.f)), 0.25f, 1e-4f);
    TestTrue(TEXT("rate 0 never fires"), FSaskartaAmbienceLogic::PoissonIntervalS(0.f, 0.5f) > 1000.f);
    TestTrue(TEXT("U 0 is clamped (finite)"), FMath::IsFinite(FSaskartaAmbienceLogic::PoissonIntervalS(5.f, 0.f)));

    // The empirical mean rate of the inter-arrivals matches the dose (seeded, 20,000 draws).
    FRandomStream R(1234);
    for (const float Rate : { 1.f, 10.f, 80.f })
    {
        double Sum = 0.0;
        const int32 N = 20000;
        for (int32 i = 0; i < N; ++i)
        {
            Sum += FSaskartaAmbienceLogic::PoissonIntervalS(Rate, 1.f - R.FRand());
        }
        const double Measured = N / Sum;
        TestTrue(*FString::Printf(TEXT("mean rate %.0f/s within 3 %% (got %.2f)"), Rate, Measured), FMath::Abs(Measured - Rate) < 0.03 * Rate);
    }

    // Clicks carry the rate to 30 cps; the 80 cps loop takes over by 50.
    FSaskartaGeigerMix M = FSaskartaAmbienceLogic::GeigerMix(10.f);
    TestEqual(TEXT("clicks at 10"), M.ClickRate, 10.f, 1e-4f);
    TestEqual(TEXT("no loop at 10"), M.LoopGain, 0.f, 1e-5f);
    M = FSaskartaAmbienceLogic::GeigerMix(40.f);
    TestEqual(TEXT("half the clicks at 40"), M.ClickRate, 20.f, 1e-3f);
    TestEqual(TEXT("half the loop at 40 (x 40/80)"), M.LoopGain, 0.25f, 1e-3f);
    M = FSaskartaAmbienceLogic::GeigerMix(80.f);
    TestEqual(TEXT("no clicks at 80"), M.ClickRate, 0.f, 1e-5f);
    TestEqual(TEXT("full loop at 80"), M.LoopGain, 1.f, 1e-5f);

    // The rate-loop fallback: log crossfade between neighbours, equal power.
    TArray<float> G;
    FSaskartaAmbienceLogic::GeigerLoopWeights({ 1.f, 5.f, 20.f, 80.f }, 5.f, G);
    TestEqual(TEXT("exactly 5 cps -> the 5 loop"), G[1], 1.f, 1e-4f);
    FSaskartaAmbienceLogic::GeigerLoopWeights({ 1.f, 5.f, 20.f, 80.f }, 10.f, G);
    TestEqual(TEXT("10 cps -> equal power between 5 and 20"), G[1] * G[1] + G[2] * G[2], 1.f, 1e-4f);
    TestEqual(TEXT("10 cps: no 1 loop"), G[0], 0.f, 1e-5f);
    FSaskartaAmbienceLogic::GeigerLoopWeights({ 1.f, 5.f, 20.f, 80.f }, 0.5f, G);
    TestEqual(TEXT("under the slowest loop it fades"), G[0], 0.5f, 1e-4f);
    return true;
}

// ============================================================================ pools and voices

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaAmbienceBagTest, "Saskarta.Ambience.NoRepeatBag", SASKARTA_AMBIENCE_TEST_FLAGS)
bool FSaskartaAmbienceBagTest::RunTest(const FString&)
{
    FRandomStream R(42);
    for (const int32 Num : { 2, 3, 4, 6, 10, 16 })
    {
        FSaskartaAmbienceBag Bag;
        int32 Prev = INDEX_NONE;
        bool bRepeat = false;
        bool bCycleOk = true;
        for (int32 Cycle = 0; Cycle < 50; ++Cycle)
        {
            TSet<int32> Seen;
            for (int32 i = 0; i < Num; ++i)
            {
                const int32 X = Bag.Next(Num, R);
                bRepeat |= X == Prev;
                Prev = X;
                Seen.Add(X);
            }
            // Each cycle of Num draws plays every variant once.
            bCycleOk &= Seen.Num() == Num;
        }
        TestFalse(*FString::Printf(TEXT("never twice in a row (%d variants)"), Num), bRepeat);
        TestTrue(*FString::Printf(TEXT("every variant once per cycle (%d variants)"), Num), bCycleOk);
    }
    FSaskartaAmbienceBag One;
    TestEqual(TEXT("a single variant repeats (nothing else to play)"), One.Next(1, R), 0);
    FSaskartaAmbienceBag Empty;
    TestEqual(TEXT("an empty pool"), Empty.Next(0, R), INDEX_NONE);
    // A pool whose size changes starts a fresh cycle and still never repeats.
    FSaskartaAmbienceBag Grow;
    const int32 A = Grow.Next(3, R);
    const int32 B = Grow.Next(5, R);
    TestNotEqual(TEXT("no repeat across a size change"), A, B);
    TestTrue(TEXT("index in range after growing"), B >= 0 && B < 5);
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaAmbienceBudgetTest, "Saskarta.Ambience.VoiceBudget", SASKARTA_AMBIENCE_TEST_FLAGS)
bool FSaskartaAmbienceBudgetTest::RunTest(const FString&)
{
    using namespace SaskartaAmbienceTest;
    bool bReject = false;

    // Room left: nothing culled.
    TArray<FSaskartaVoiceInfo> Active = { Voice(100, 1, 0), Voice(20, 0.5f, 1) };
    TestEqual(TEXT("room: no cull"), FSaskartaAmbienceLogic::PickVoiceToCull(Active, Voice(30, 1, 5), 3, bReject), INDEX_NONE);
    TestFalse(TEXT("room: admitted"), bReject);

    // Full: the lowest priority goes.
    Active = { Voice(100, 1, 0), Voice(20, 0.5f, 1), Voice(70, 1, 2) };
    TestEqual(TEXT("full: lowest priority culled"), FSaskartaAmbienceLogic::PickVoiceToCull(Active, Voice(30, 1, 5), 3, bReject), 1);
    TestFalse(TEXT("full: candidate admitted"), bReject);

    // Full, and the candidate is the lowest: it is refused, nothing culled.
    TestEqual(TEXT("candidate lowest: no cull"), FSaskartaAmbienceLogic::PickVoiceToCull(Active, Voice(10, 1, 5), 3, bReject), INDEX_NONE);
    TestTrue(TEXT("candidate lowest: rejected"), bReject);

    // Equal priority: the quieter goes, then the older.
    Active = { Voice(30, 0.8f, 0), Voice(30, 0.2f, 1), Voice(30, 0.8f, 2) };
    TestEqual(TEXT("tie: quieter culled"), FSaskartaAmbienceLogic::PickVoiceToCull(Active, Voice(30, 0.9f, 5), 3, bReject), 1);
    Active = { Voice(30, 0.5f, 3), Voice(30, 0.5f, 1), Voice(30, 0.5f, 2) };
    TestEqual(TEXT("tie: older culled"), FSaskartaAmbienceLogic::PickVoiceToCull(Active, Voice(30, 0.9f, 5), 3, bReject), 1);
    // A candidate equal to the lowest in priority and volume does not churn the voices.
    TestEqual(TEXT("full tie: candidate refused"), FSaskartaAmbienceLogic::PickVoiceToCull(Active, Voice(30, 0.5f, 5), 3, bReject), INDEX_NONE);
    TestTrue(TEXT("full tie: rejected"), bReject);

    // The brief's 22-voice budget: 22 playing, a thunder (90) arrives, a debris one-shot (20) goes.
    Active.Reset();
    for (int32 i = 0; i < 22; ++i)
    {
        Active.Add(Voice(i == 13 ? 20.f : 50.f + i, 1.f, i));
    }
    TestEqual(TEXT("22 voices: debris culled for thunder"), FSaskartaAmbienceLogic::PickVoiceToCull(Active, Voice(90, 1, 30), 22, bReject), 13);
    TestFalse(TEXT("thunder admitted"), bReject);
    // Over-full (after a budget change): still one cull per admission, the lowest.
    TestEqual(TEXT("over budget: lowest culled"), FSaskartaAmbienceLogic::PickVoiceToCull(Active, Voice(90, 1, 30), 19, bReject), 13);
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaAmbiencePlacementTest, "Saskarta.Ambience.Placement", SASKARTA_AMBIENCE_TEST_FLAGS)
bool FSaskartaAmbiencePlacementTest::RunTest(const FString&)
{
    FRandomStream R(7);
    const FVector Origin(1000.f, 2000.f, 300.f);
    for (int32 i = 0; i < 200; ++i)
    {
        const FVector P = FSaskartaAmbienceLogic::PointAround(Origin, FVector(1, 0, 0), 15.f, 60.f, 70.f, -2.f, R.FRand(), R.FRand());
        const FVector D = P - Origin;
        const float Dist2D = FVector(D.X, D.Y, 0.f).Size();
        const float Yaw = FMath::RadiansToDegrees(FMath::Atan2(D.Y, D.X));
        if (!TestTrue(TEXT("15-60 m out"), Dist2D >= 1500.f - 1.f && Dist2D <= 6000.f + 1.f)
            || !TestTrue(TEXT("within +-70 deg of travel"), FMath::Abs(Yaw) <= 70.01f)
            || !TestEqual(TEXT("height offset"), static_cast<float>(D.Z), -200.f, 1e-2f))
        {
            break;
        }
    }
    TestEqual(TEXT("pool interval min"), FSaskartaAmbienceLogic::PoolIntervalS(30.f, 90.f, 0.f), 30.f, 1e-4f);
    TestEqual(TEXT("pool interval max"), FSaskartaAmbienceLogic::PoolIntervalS(30.f, 90.f, 1.f), 90.f, 1e-4f);
    TestTrue(TEXT("event-driven pool"), FSaskartaAmbienceLogic::PoolIntervalS(0.f, 0.f, 0.5f) < 0.f);
    return true;
}

// ============================================================================ importer and settings

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaAmbienceImportTest, "Saskarta.Ambience.Import", SASKARTA_AMBIENCE_TEST_FLAGS)
bool FSaskartaAmbienceImportTest::RunTest(const FString&)
{
    const FString Json = TEXT(R"JSON({
      "zones": [
        {"zone": "Cloud", "from_m": 4200, "to_m": 4480, "xfade_m": 120, "beds": ["AMB_Cloud_MuffledWind_Loop"], "pools": ["Cloud_Drops"]},
        {"zone": "Valley", "from_m": 0, "to_m": 2020, "xfade_m": 150, "beds": ["AMB_Valley_Insects_Loop"], "pools": ["Valley_Birds"]}
      ],
      "pools": {
        "Valley_Birds": {"zone": "Valley", "files": ["SFX_Valley_Crow_01", "SFX_Valley_Crow_02"], "interval_s": [45, 140], "volume_db": -8.0},
        "Cloud_Drops": {"zone": "Cloud", "files": ["SFX_Cloud_Droplet_01"], "interval_s": [4, 14], "volume_db": -12.0},
        "Platform_Metal": {"zone": "Platform", "files": ["SFX_Platform_SignClank_01"], "interval_s": [12, 40], "volume_db": -8.0},
        "Storm_Gust": {"zone": "Storm", "files": ["SFX_Storm_Gust_01"], "interval_s": [20, 90], "volume_db": -4.0},
        "Geiger_Click": {"zone": "Geiger", "files": ["SFX_Geiger_Click_01", "SFX_Geiger_Click_02"], "interval_s": null, "volume_db": -6.0}
      },
      "placement": [
        {"label": "A2_WW_Trickle", "asset": "AMB_WaitingWater_Trickle_Loop", "road_m": 1220, "x": 1, "y": 2, "z": 3, "inner_radius_m": 4, "falloff_m": 40, "volume_db": -8, "note": "WATER OPTION (off by default)"},
        {"label": "A2_WW_GateCreak", "asset": "SFX_WaitingWater_GateCreak_*", "road_m": 1222, "x": 4, "y": 5, "z": 6, "inner_radius_m": 5, "falloff_m": 60, "volume_db": -10, "note": "DRY-SAFE"}
      ],
      "dose_cps": [[2600, 10], [0, 0.5]],
      "files": [
        {"asset": "AMB_Valley_Insects_Loop", "ue_folder": "/Game/SaskartaGaea/Audio/Ambience2", "zone": "Valley", "type": "bed", "volume_db": -10.0},
        {"asset": "AMB_Storm_SandHiss_Loop", "ue_folder": "/Game/SaskartaGaea/Audio/Ambience2", "zone": "Storm", "type": "bed", "volume_db": -6.0},
        {"asset": "SFX_Geiger_Rate_80_Loop", "ue_folder": "/Game/SaskartaGaea/Audio/Ambience2", "zone": "Geiger", "type": "spot", "rate_cps": 80},
        {"asset": "SFX_Geiger_Rate_5_Loop", "ue_folder": "/Game/SaskartaGaea/Audio/Ambience2", "zone": "Geiger", "type": "spot", "rate_cps": 5},
        {"asset": "SFX_Geiger_AlarmChirp_01", "ue_folder": "/Game/SaskartaGaea/Audio/Ambience2", "zone": "Geiger", "type": "oneshot"}
      ]
    })JSON");

    USaskartaAmbienceAsset* A = NewObject<USaskartaAmbienceAsset>(GetTransientPackage());
    FString Report;
    TestTrue(TEXT("parses"), USaskartaAmbienceImport::ParseManifestJson(Json, A, Report));
    AddInfo(Report);

    TestEqual(TEXT("zones"), A->Zones.Num(), 2);
    TestTrue(TEXT("zones sorted by road"), A->Zones[0].Name == FName(TEXT("Valley")));
    TestEqual(TEXT("cloud wind multiplier"), A->Zones[1].WindMultiplier, 0.4f, 1e-5f);
    TestEqual(TEXT("cloud dose washout"), A->Zones[1].DoseMultiplier, 0.8f, 1e-5f);
    TestEqual(TEXT("cloud xfade"), A->Zones[1].XfadeM, 120.f, 1e-5f);
    const FSaskartaAmbienceBed& Insects = A->Zones[0].Beds[0];
    TestEqual(TEXT("insects dB from the file list"), Insects.VolumeDb, -10.f, 1e-5f);
    TestTrue(TEXT("insects storm rule"), Insects.StormMode == ESaskartaBedStormMode::InverseToRef);
    TestEqual(TEXT("insects off after 1,700"), Insects.OffAfterRoadM, 1700.f, 1e-5f);
    TestEqual(TEXT("sound path"), Insects.Sound.ToSoftObjectPath().ToString(),
        FString(TEXT("/Game/SaskartaGaea/Audio/Ambience2/AMB_Valley_Insects_Loop.AMB_Valley_Insects_Loop")));

    TestEqual(TEXT("pools (the Geiger's are not pools)"), A->Pools.Num(), 4);
    TestEqual(TEXT("geiger clicks"), A->GeigerClicks.Num(), 2);
    const FSaskartaAmbiencePool* Birds = A->FindPool(TEXT("Valley_Birds"));
    if (TestNotNull(TEXT("Valley_Birds"), Birds))
    {
        TestEqual(TEXT("birds interval"), Birds->IntervalMaxS, 140.f, 1e-5f);
        TestTrue(TEXT("birds placement"), Birds->Placement == ESaskartaPoolPlacement::AroundListener);
        TestEqual(TEXT("birds only under I 0.9"), Birds->MaxStorm, 0.9f, 1e-5f);
        TestEqual(TEXT("birds variants"), Birds->Sounds.Num(), 2);
    }
    const FSaskartaAmbiencePool* Metal = A->FindPool(TEXT("Platform_Metal"));
    if (TestNotNull(TEXT("Platform_Metal"), Metal))
    {
        TestTrue(TEXT("metal at the platform emitters"), Metal->Placement == ESaskartaPoolPlacement::AtEmitter);
        TestTrue(TEXT("metal answers gusts"), Metal->bAlsoOnGust);
        TestTrue(TEXT("metal is local"), Metal->bLocal);
    }
    const FSaskartaAmbiencePool* Gust = A->FindPool(TEXT("Storm_Gust"));
    if (TestNotNull(TEXT("Storm_Gust"), Gust))
    {
        TestEqual(TEXT("gusts are timer-driven, not a pool interval"), Gust->IntervalMaxS, 0.f, 1e-6f);
    }

    TestEqual(TEXT("spots"), A->Spots.Num(), 2);
    TestTrue(TEXT("trickle is a water option"), A->Spots[0].bWaterOption);
    TestFalse(TEXT("gate creak is dry-safe"), A->Spots[1].bWaterOption);
    TestTrue(TEXT("gate creak is a pool anchor only"), A->Spots[1].Sound.IsNull());
    TestEqual(TEXT("spot location (cm)"), A->Spots[1].Location, FVector(4, 5, 6));

    TestEqual(TEXT("dose points"), A->DoseByRoadM.Num(), 2);
    TestEqual(TEXT("dose sorted"), A->DoseByRoadM[0].X, 0.0, 1e-6);
    TestEqual(TEXT("rate loops"), A->GeigerRateLoops.Num(), 2);
    TestEqual(TEXT("rate loops sorted"), A->GeigerRateLoops[0].RateCps, 5.f, 1e-5f);
    TestEqual(TEXT("chirps"), A->GeigerChirps.Num(), 1);
    TestEqual(TEXT("storm beds"), A->StormBeds.Num(), 1);
    TestTrue(TEXT("sand hiss x I^2"), A->StormBeds[0].StormMode == ESaskartaBedStormMode::Squared);
    TestFalse(TEXT("mix defaults set"), A->AmbienceSubmix.IsNull());

    TestFalse(TEXT("garbage is refused"), USaskartaAmbienceImport::ParseManifestJson(TEXT("not json"), A, Report));
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaAmbienceManifestFileTest, "Saskarta.Ambience.ManifestFile", SASKARTA_AMBIENCE_TEST_FLAGS)
bool FSaskartaAmbienceManifestFileTest::RunTest(const FString&)
{
    const FString Path = FPaths::Combine(FPaths::ProjectSavedDir(), TEXT("GameAudio/Ambience2/manifest.json"));
    if (!FPaths::FileExists(Path))
    {
        AddWarning(FString::Printf(TEXT("%s not found; skipped."), *Path));
        return true;
    }
    USaskartaAmbienceAsset* A = NewObject<USaskartaAmbienceAsset>(GetTransientPackage());
    FString Report;
    TestTrue(TEXT("imports"), USaskartaAmbienceImport::ImportAmbienceFromManifest(A, Path, Report));
    AddInfo(Report);
    TestEqual(TEXT("six zones"), A->Zones.Num(), 6);
    TestEqual(TEXT("24 pools (+ the Geiger's two)"), A->Pools.Num(), 24);
    TestEqual(TEXT("18 spots"), A->Spots.Num(), 18);
    TestEqual(TEXT("16 clicks"), A->GeigerClicks.Num(), 16);
    TestEqual(TEXT("4 rate loops"), A->GeigerRateLoops.Num(), 4);
    TestEqual(TEXT("3 chirps"), A->GeigerChirps.Num(), 3);
    TestEqual(TEXT("2 grit beds"), A->StormBeds.Num(), 2);
    TestTrue(TEXT("a dose table"), A->DoseByRoadM.Num() >= 10);
    TestFalse(TEXT("no file missing from the list"), Report.Contains(TEXT("not in the file list")));
    // Every zone's pools exist.
    for (const FSaskartaAmbienceZone& Z : A->Zones)
    {
        for (const FName P : Z.Pools)
        {
            TestNotNull(*FString::Printf(TEXT("%s pool %s"), *Z.Name.ToString(), *P.ToString()), A->FindPool(P));
        }
    }
    // Every emitter a pool names is a spot.
    for (const FSaskartaAmbiencePool& P : A->Pools)
    {
        for (const FName L : P.Emitters)
        {
            TestNotNull(*FString::Printf(TEXT("%s emitter %s"), *P.Name.ToString(), *L.ToString()), A->FindSpot(L));
        }
    }
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaAmbienceSettingsTest, "Saskarta.Ambience.SettingsCVars", SASKARTA_AMBIENCE_TEST_FLAGS)
bool FSaskartaAmbienceSettingsTest::RunTest(const FString&)
{
    const TMap<FString, FString> C = USaskartaAmbienceSettings::ComputeCVars(false, 1.7f);
    TestEqual(TEXT("geiger off"), C.FindRef(TEXT("saskarta.geiger")), FString(TEXT("0")));
    TestEqual(TEXT("geiger volume clamped"), C.FindRef(TEXT("saskarta.volume.geiger")), FString(TEXT("1.000")));
    return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS
