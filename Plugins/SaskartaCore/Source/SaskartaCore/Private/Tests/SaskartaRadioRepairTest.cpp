#include "Misc/AutomationTest.h"

#if WITH_DEV_AUTOMATION_TESTS
#include "SaskartaRadioRepairLogic.h"

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaRadioRepairSequenceTest, "Saskarta.RadioRepair.Sequence",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)
bool FSaskartaRadioRepairSequenceTest::RunTest(const FString&)
{
    using F = FSaskartaRadioRepairLogic;
    F State;
    TestFalse(TEXT("weak aerial cannot lock"), State.Confirm());
    for (int32 I = 0; I < 58; ++I) State.Step(0.05f, 1.f, 1.f, true);
    TestEqual(TEXT("fine control waits for aerial lock"), State.Frequency, -0.45f);
    TestTrue(TEXT("strong aerial locks"), State.Confirm());
    for (int32 I = 0; I < 122; ++I) State.Step(0.05f, 0.f, 1.f, true);
    TestTrue(TEXT("fine tuning peaks real signal state"), State.Signal() > 0.99f);
    TestEqual(TEXT("dial motion is not steady"), State.StableS, 0.f);
    for (int32 I = 0; I < 15; ++I) State.Step(0.1f, 0.f, 0.f, true);
    F Restored;
    Restored.Restore(1, State.AerialDeg, State.Frequency, State.StableS, false);
    for (int32 I = 0; I < 30; ++I) Restored.Step(0.1f, 0.f, 0.f, false);
    TestEqual(TEXT("pause freezes stability"), Restored.StableS, State.StableS);
    for (int32 I = 0; I < 15; ++I) Restored.Step(0.1f, 0.f, 0.f, true);
    TestTrue(TEXT("three steady seconds complete once"), Restored.IsComplete());
    TestFalse(TEXT("completed encounter cannot reopen its stages"), Restored.Confirm());
    TestTrue(TEXT("authored Cistern window is inclusive"), F::InZone(3030.f) && F::InZone(3080.f));
    TestFalse(TEXT("no encounter outside the authored dip"), F::InZone(3100.f));
    return true;
}
#endif
