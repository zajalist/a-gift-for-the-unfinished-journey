// Automation tests for the pure power core (docs/design/ROUTE_BOARD_V3.md POWER). Tools/Power/power_core_smoke.cpp
// runs the same numbers offline with cl. Run after the build: Automation RunTests Saskarta.Power
#include "Misc/AutomationTest.h"

#if WITH_DEV_AUTOMATION_TESTS
#include "SaskartaPowerLogic.h"

#define POWER_TEST_FLAGS (EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaPowerRatesTest, "Saskarta.Power.Rates", POWER_TEST_FLAGS)
bool FSaskartaPowerRatesTest::RunTest(const FString&)
{
    FSaskartaPowerCore Power;
    TestEqual(TEXT("the depot hands over a low cell"), Power.Charge, 35.f);
    FSaskartaPowerInput In;
    In.bPlaying = true;
    In.DeltaS = 0.1f;
    In.SpeedMps = 5.f;
    Power.Step(In);
    TestTrue(TEXT("everything on: -0.132 %/s"), FMath::IsNearlyEqual(Power.LastRatePerS, -0.132f, 1e-4f));
    In.bRadioRequested = false;
    Power.Step(In);
    TestTrue(TEXT("radio off: the -0.08 %/s floor"), FMath::IsNearlyEqual(Power.LastRatePerS, -0.08f, 1e-4f));
    In.bLampsRequested = false;
    Power.Step(In);
    TestTrue(TEXT("all off: -0.08 %/s"), FMath::IsNearlyEqual(Power.LastRatePerS, -0.08f, 1e-4f));
    In.bListening = true;
    Power.Step(In);
    TestTrue(TEXT("LISTEN runs the radio load"), FMath::IsNearlyEqual(Power.LastRatePerS, -0.092f, 1e-4f));

    // At a crawl the generator can exceed drive load, especially with the lamps/radio off.
    // Moving must never become an effectively infinite battery exploit on a shallow climb.
    FSaskartaPowerCore SlowClimb;
    FSaskartaPowerInput SlowIn;
    SlowIn.bPlaying = true;
    SlowIn.DeltaS = 0.1f;
    SlowIn.SpeedMps = 0.31f;
    SlowIn.Grade = 0.1f;
    SlowIn.bRadioRequested = false;
    SlowIn.bLampsRequested = false;
    SlowClimb.Step(SlowIn);
    TestTrue(TEXT("slow uphill movement has a minimum cell cost"),
        FMath::IsNearlyEqual(SlowClimb.LastRatePerS, -0.08f, 1e-4f));
    for (int32 I = 0; I < 1000; ++I) SlowClimb.Step(SlowIn);
    TestTrue(TEXT("slow uphill movement cannot hold charge indefinitely"), SlowClimb.Charge < 33.f);
    TestFalse(TEXT("slow movement still does not count as a stopped recharge"), SlowClimb.CanRest());

    Power.Charge = 100.f;
    TestTrue(TEXT("range all on 3.8 km"), FMath::IsNearlyEqual(Power.RangeKm(true, true), 3.788f, 0.01f));
    TestTrue(TEXT("range radio off 6.25 km"), FMath::IsNearlyEqual(Power.RangeKm(false, true), 6.25f, 0.01f));
    TestTrue(TEXT("range lamps off 5.4 km"), FMath::IsNearlyEqual(Power.RangeKm(true, false), 5.435f, 0.01f));
    TestTrue(TEXT("range all off 6 km"), FMath::IsNearlyEqual(Power.RangeKm(false, false), 6.25f, 0.01f));
    TestTrue(TEXT("rest +1.25 lit and listening"), FMath::IsNearlyEqual(Power.RestRatePerS(true, true), 1.25f, 1e-4f));
    TestTrue(TEXT("rest +1.5 dark and quiet"), FMath::IsNearlyEqual(Power.RestRatePerS(false, false), 1.5f, 1e-4f));
    Power.Charge = 20.f;
    TestTrue(TEXT("20 % to full in about a minute"), FMath::IsNearlyEqual(Power.SecondsToFull(true, true), 64.f, 0.01f));

    Power.Charge = 100.f;
    In.bListening = false;
    In.bRadioRequested = true;
    In.bLampsRequested = true;
    In.SpeedMps = 8.f;
    In.bTurboHeld = true;
    Power.Step(In);
    TestTrue(TEXT("turbo: about 85 s from full"), Power.bTurbo && Power.LastRatePerS < -1.1f && Power.LastRatePerS > -1.3f);
    TestEqual(TEXT("turbo flat cap"), Power.SpeedCapMps(5.f, 0.f), 8.f);
    TestEqual(TEXT("turbo steep cap adds 2 m/s"), Power.SpeedCapMps(2.5f, 0.42f), 4.5f);

    // If the road is steep enough to hold the carrier below the old 0.3 m/s
    // gate, Shift must still spin up the motor and consume cell charge.
    Power.Load({35.f, 0.f, false});
    In.SpeedMps = 0.f;
    const float ChargeBeforeStart = Power.Charge;
    Power.Step(In);
    TestTrue(TEXT("boost starts from standstill on a climb"), Power.bTurbo);
    TestTrue(TEXT("standstill boost costs main cell charge"), Power.Charge < ChargeBeforeStart);
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaPowerLimpTest, "Saskarta.Power.LimpAndRest", POWER_TEST_FLAGS)
bool FSaskartaPowerLimpTest::RunTest(const FString&)
{
    FSaskartaPowerCore Power;
    Power.Load({0.f, 0.f, true});
    FSaskartaPowerInput In;
    In.bPlaying = true;
    In.DeltaS = 0.1f;
    In.SpeedMps = 2.5f;
    In.bTurboHeld = true;
    Power.Step(In);
    TestTrue(TEXT("crawling in limp cannot charge"), Power.LastRatePerS <= 0.f && Power.Charge == 0.f);
    TestTrue(TEXT("limp persists below 30 percent"), Power.bLimp);
    TestFalse(TEXT("turbo denied in limp"), Power.bTurbo);
    TestEqual(TEXT("empty means stopped"), Power.SpeedCapMps(5.f, 0.f), 0.f);
    Power.Tuning.LimpSpeedMps = 99.f;
    TestEqual(TEXT("legacy limp tuning cannot permit a crawl"), Power.SpeedCapMps(5.f, 0.f), 0.f);

    for (int32 I = 0; I < 50; ++I) Power.Step(In);
    TestEqual(TEXT("continued crawling stays empty"), Power.Charge, 0.f);
    In.SpeedMps = 0.f;
    In.bTurboHeld = false;
    for (int32 I = 0; I < 300; ++I) Power.Step(In);
    TestTrue(TEXT("two stopped seconds offer rest"), Power.CanRest());
    TestTrue(TEXT("30 percent lifts limp"), Power.Charge >= 30.f && !Power.bLimp);
    TestFalse(TEXT("a brief rest is not a completed first recharge"), Power.bFirstRechargeComplete);
    for (int32 I = 0; I < 250; ++I) Power.Step(In);
    TestTrue(TEXT("stationary charge to 60 percent completes first recharge"), Power.bFirstRechargeComplete);
    TestTrue(TEXT("saved rest state round-trips"), Power.Save().StoppedForS >= 2.f);
    const FSaskartaPowerSaveState Saved = Power.Save();
    FSaskartaPowerCore Restored;
    Restored.Load(Saved);
    TestTrue(TEXT("first recharge persists through checkpoint"), Restored.bFirstRechargeComplete);

    Power.Load({29.f, 0.f, true});
    TestTrue(TEXT("loading sub-30 limp stays limp"), Power.bLimp);
    Power.Load({30.f, 0.f, true});
    TestFalse(TEXT("loading 30 percent exits limp"), Power.bLimp);
    Power.Load({20.f, 3.f, true});
    In.bTurboHeld = true;
    Power.Step(In);
    TestTrue(TEXT("holding boost while stopped still recharges"), Power.Charge > 20.f && Power.bLimp && !Power.bTurbo);
    TestEqual(TEXT("recovery remains parked below 30 percent"), Power.SpeedCapMps(5.f, 0.f), 0.f);
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaPowerFreezeTest, "Saskarta.Power.FreezeAndSpend", POWER_TEST_FLAGS)
bool FSaskartaPowerFreezeTest::RunTest(const FString&)
{
    FSaskartaPowerCore Power;
    Power.Charge = 80.f;
    FSaskartaPowerInput In;
    In.DeltaS = 0.1f;
    In.SpeedMps = 5.f;
    In.bPlaying = true;
    In.bCinematic = true;
    Power.Step(In);
    TestEqual(TEXT("cinematic freezes charge"), Power.Charge, 80.f);
    In.bCinematic = false;
    In.bPlaying = false;
    Power.Step(In);
    TestEqual(TEXT("non-playing flow freezes charge"), Power.Charge, 80.f);
    TestFalse(TEXT("overspend refused"), Power.TrySpend(81.f));
    TestEqual(TEXT("overspend leaves charge alone"), Power.Charge, 80.f);
    TestTrue(TEXT("spend reaches empty"), Power.TrySpend(80.f));
    TestTrue(TEXT("spending to zero enters limp"), Power.bLimp);
    TestFalse(TEXT("cannot spend negative"), Power.TrySpend(-1.f));
    return true;
}
#endif
