#include "Misc/AutomationTest.h"

#if WITH_DEV_AUTOMATION_TESTS
#include "Dom/JsonObject.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "SaskartaPowerHud.h"
#include "SaskartaPowerLogic.h"

#define POWER_SLICE_FLAGS (EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaPowerHudLineTest, "Saskarta.Power.Hud.Line", POWER_SLICE_FLAGS)
bool FSaskartaPowerHudLineTest::RunTest(const FString&)
{
    // ROUTE_BOARD_V3.md THE CRT: one RANGE line driving, ^ FULL IN at rest, LIMP . STOP TO CHARGE when empty.
    auto L = [](const FSaskartaPowerHudInput& In) { return FString(FSaskartaPowerHud::LineFor(In).c_str()); };
    FSaskartaPowerHudInput In;
    In.Charge = 62.f;
    In.RatePerS = -0.33f;
    In.RangeKm = 1.4f;
    TestEqual(TEXT("driving"), L(In), FString(TEXT("PWR ||||||||||||........ 62%  RANGE 1.4 KM")));
    In.Charge = 31.f;
    In.RatePerS = 1.25f;
    In.bResting = true;
    In.SecondsToFull = 55.2f;
    TestEqual(TEXT("resting"), L(In), FString(TEXT("PWR ||||||.............. 31%  ^ FULL IN 55 S")));
    In.bResting = false;
    In.bLimp = true;
    In.Charge = 0.f;
    TestEqual(TEXT("empty stops the system"), L(In), FString(TEXT("PWR ....................  0%  SYSTEM STOPPED . RECHARGE TO 30%")));
    TestTrue(TEXT("full bar uses glyphs the CRT font has"), FSaskartaPowerHud::Bar(100.f, false) == std::wstring(20, L'|'));
    FSaskartaPowerHudInput R;
    R.bResting = true;
    R.bMotorReady = true;
    TestEqual(TEXT("motor tuning at rest"), FString(FSaskartaPowerHud::SteadySub(R).c_str()), FString(TEXT("TAB . TUNE MOTOR")));
    FSaskartaPowerHudInput T;
    T.bTurbo = true;
    TestEqual(TEXT("turbo names its control"), FString(FSaskartaPowerHud::SteadySub(T).c_str()), FString(TEXT("SHIFT BOOST . RADIO DROWNED")));
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaPowerHudRestraintTest, "Saskarta.Power.Hud.Restraint", POWER_SLICE_FLAGS)
bool FSaskartaPowerHudRestraintTest::RunTest(const FString&)
{
    FSaskartaPowerHud Hud;
    FSaskartaPowerHudInput In;
    In.Charge = 80.f;
    In.RatePerS = -0.33f;
    In.RangeKm = 2.4f;
    TestEqual(TEXT("bright at first"), Hud.Step(0.1f, In).Opacity, 1.f);
    TestTrue(TEXT("no second line at start"), Hud.Step(0.1f, In).Loads.empty());
    for (int32 I = 0; I < 60; ++I) Hud.Step(0.1f, In);
    TestEqual(TEXT("dims when steady above 40 %"), Hud.Step(0.1f, In).Opacity, FSaskartaPowerHud::DimOpacity);
    In.bRadioOn = false;
    In.RangeKm = 4.5f;
    const FSaskartaPowerHudOutput Changed = Hud.Step(0.1f, In);
    TestEqual(TEXT("a toggle brightens"), Changed.Opacity, 1.f);
    TestEqual(TEXT("a toggle shows its cost"), FString(Changed.Loads.c_str()), FString(TEXT("RADIO OFF . RANGE 4.5 KM")));
    for (int32 I = 0; I < 35; ++I) Hud.Step(0.1f, In);
    TestTrue(TEXT("the toggle line clears after 3 s"), Hud.Step(0.1f, In).Loads.empty());
    Hud.Notify(L"STOP TO TUNE MOTOR");
    TestEqual(TEXT("a notice"), FString(Hud.Step(0.1f, In).Loads.c_str()), FString(TEXT("STOP TO TUNE MOTOR")));
    In.Charge = 30.f;
    for (int32 I = 0; I < 60; ++I) Hud.Step(0.1f, In);
    TestEqual(TEXT("below 40 % never dims"), Hud.Step(0.1f, In).Opacity, 1.f);
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaPowerLimpRadioTest, "Saskarta.Power.LimpKeepsLoads", POWER_SLICE_FLAGS)
bool FSaskartaPowerLimpRadioTest::RunTest(const FString&)
{
    FSaskartaPowerCore Power;
    Power.Load({0.5f, 0.f, false});
    FSaskartaPowerInput In;
    In.bPlaying = true;
    In.DeltaS = 0.25f;
    In.SpeedMps = 8.f;
    In.bTurboHeld = true;
    for (int32 I = 0; I < 8; ++I) Power.Step(In);
    TestTrue(TEXT("the empty bar is limp"), Power.bLimp);
    TestEqual(TEXT("empty prohibits travel"), Power.SpeedCapMps(5.f, 0.f), 0.f);
    In.SpeedMps = 2.5f;
    Power.Step(In);
    TestTrue(TEXT("crawling in limp does not recharge even with the radio and lamps on"),
        Power.LastRatePerS <= 0.f && Power.Charge == 0.f);
    TestFalse(TEXT("no turbo in limp"), Power.bTurbo);
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaBatteryInspectionTest, "Saskarta.Power.BatteryInspection", POWER_SLICE_FLAGS)
bool FSaskartaBatteryInspectionTest::RunTest(const FString&)
{
    TestEqual(TEXT("empty LEDs"), SaskartaBatterySegmentFill(0.f, 0), 0.f);
    TestEqual(TEXT("full final LED"), SaskartaBatterySegmentFill(100.f, 6), 1.f);
    TestEqual(TEXT("half charge has a fractional fourth LED"), SaskartaBatterySegmentFill(50.f, 3), 0.5f);
    TestEqual(TEXT("half charge leaves the fifth LED dark"), SaskartaBatterySegmentFill(50.f, 4), 0.f);
    FSaskartaBatteryGaze Gaze;
    TestFalse(TEXT("a one-frame glance is hidden"), Gaze.Step(0.1f, true, true, true));
    Gaze.Step(0.1f, true, true, true);
    TestTrue(TEXT("dwell reveals percentage"), Gaze.Step(0.1f, true, true, true));
    TestTrue(TEXT("brief look-away is stable"), Gaze.Step(0.1f, true, false, false));
    TestFalse(TEXT("sustained look-away hides it"), Gaze.Step(0.1f, true, false, false));
    for (int32 I = 0; I < 3; ++I) Gaze.Step(0.1f, true, true, true);
    TestFalse(TEXT("occlusion/flow loss hides immediately"), Gaze.Step(0.1f, false, true, true));
    FSaskartaPowerHud Hud;
    FSaskartaPowerHudInput In;
    In.Charge = 8.f; In.bLow = true; In.bBlink = true;
    for (int32 I = 0; I < 25; ++I)
        TestEqual(TEXT("critical gauge never flashes dark"), Hud.Step(0.1f, In).Opacity, 1.f);
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaPowerTelemetryTest, "Saskarta.Power.Telemetry", POWER_SLICE_FLAGS)
bool FSaskartaPowerTelemetryTest::RunTest(const FString&)
{
    FSaskartaPowerTelemetry History;
    for (int32 I = 0; I < 150; ++I) History.Push(1000.f, -45000.f, I * 0.1);
    TestEqual(TEXT("history is bounded"), History.Count, 120);
    TestEqual(TEXT("cm/s converts to km/h"), History.SpeedKph[History.Index(119)], 36.f);
    TestEqual(TEXT("world cm converts to datum metres"), History.AltitudeM[History.Index(119)], -450.f);
    History.Push(100.f, 100.f, 30.0);
    TestEqual(TEXT("a hitch expires old samples"), History.Count, 1);
    History.Push(100.f, 100.f, 30.0);
    TestEqual(TEXT("duplicate timer instant does not add samples"), History.Count, 1);
    History.Push(100.f, 100.f, 1.0);
    TestEqual(TEXT("restored clock starts a fresh trace"), History.Count, 1);
    return true;
}

#endif
