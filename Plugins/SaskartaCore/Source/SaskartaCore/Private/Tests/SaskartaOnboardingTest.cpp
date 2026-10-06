// Automation tests for the onboarding hint scheduler (SaskartaOnboardingLogic.h): one at a time, first time
// only, the block rules, dismissal by the action or the 8 s hold, skip-if-known, ordering, the road window,
// the gamepad text, and docs/story/onboarding.json itself. Written offline (no build ran). Run after the build:
//   Automation RunTests Saskarta.Onboarding

#include "Misc/AutomationTest.h"

#if WITH_DEV_AUTOMATION_TESTS

#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "SaskartaOnboardingLogic.h"

#define SASKARTA_ONBOARDING_TEST_FLAGS (EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)

namespace SaskartaOnboardingTest
{
    static FSaskartaHintDef Hint(const TCHAR* Id, std::initializer_list<const TCHAR*> When, std::initializer_list<const TCHAR*> DoneWhen,
        int32 Priority = 0, float DelayS = 0.f)
    {
        FSaskartaHintDef H;
        H.Id = FName(Id);
        H.Text = FString(Id).ToUpper();
        for (const TCHAR* W : When)
        {
            H.When.Add(FName(W));
        }
        for (const TCHAR* D : DoneWhen)
        {
            H.DoneWhen.Add(FName(D));
        }
        H.Priority = Priority;
        H.DelayS = DelayS;
        return H;
    }

    static FSaskartaHintFacts Facts(double NowS, std::initializer_list<const TCHAR*> Conditions,
        std::initializer_list<const TCHAR*> Actions = {}, bool bBlocked = false, float RoadM = -1.f)
    {
        FSaskartaHintFacts F;
        F.NowS = NowS;
        F.bBlocked = bBlocked;
        F.RoadM = RoadM;
        for (const TCHAR* C : Conditions)
        {
            F.Conditions.Add(FName(C));
        }
        for (const TCHAR* A : Actions)
        {
            F.Actions.Add(FName(A));
        }
        return F;
    }

    static FName Shown(const FSaskartaOnboardingCore& Core, const FSaskartaHintStep& S)
    {
        return S.Event == ESaskartaHintEvent::Show && Core.Hints.IsValidIndex(S.Hint) ? Core.Hints[S.Hint].Id : NAME_None;
    }
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaOnboardingOneAtATimeTest, "Saskarta.Onboarding.OneAtATime", SASKARTA_ONBOARDING_TEST_FLAGS)
bool FSaskartaOnboardingOneAtATimeTest::RunTest(const FString&)
{
    using namespace SaskartaOnboardingTest;
    FSaskartaOnboardingCore C;
    C.GapS = 3.f;
    C.Hints = {Hint(TEXT("low"), {TEXT("a")}, {TEXT("did_low")}, 1), Hint(TEXT("high"), {TEXT("a")}, {TEXT("did_high")}, 5)};

    TestEqual(TEXT("the higher priority shows first"), Shown(C, C.Step(Facts(10.0, {TEXT("a")}))), FName(TEXT("high")));
    TestEqual(TEXT("nothing else while one is up"), C.Step(Facts(11.0, {TEXT("a")})).Event, ESaskartaHintEvent::None);
    const FSaskartaHintStep Hide = C.Step(Facts(12.0, {TEXT("a")}, {TEXT("did_high")}));
    TestEqual(TEXT("the action dismisses it at once"), Hide.Event, ESaskartaHintEvent::Hide);
    TestEqual(TEXT("reason done"), Hide.Reason, FName(TEXT("done")));
    TestEqual(TEXT("quiet gap"), C.Step(Facts(13.0, {TEXT("a")})).Event, ESaskartaHintEvent::None);
    TestEqual(TEXT("then the next"), Shown(C, C.Step(Facts(15.5, {TEXT("a")}))), FName(TEXT("low")));
    const FSaskartaHintStep Timeout = C.Step(Facts(15.5 + 8.0, {TEXT("a")}));
    TestEqual(TEXT("8 s hold"), Timeout.Reason, FName(TEXT("timeout")));
    TestEqual(TEXT("first time only"), C.Step(Facts(40.0, {TEXT("a")})).Event, ESaskartaHintEvent::None);
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaOnboardingBlockedTest, "Saskarta.Onboarding.Blocked", SASKARTA_ONBOARDING_TEST_FLAGS)
bool FSaskartaOnboardingBlockedTest::RunTest(const FString&)
{
    using namespace SaskartaOnboardingTest;
    FSaskartaOnboardingCore C;
    C.GapS = 0.f;
    C.Hints = {Hint(TEXT("radio"), {TEXT("show_on")}, {TEXT("radio_toggled")})};

    TestEqual(TEXT("never while blocked (story line, cinematic, prompt)"),
        C.Step(Facts(1.0, {TEXT("show_on")}, {}, true)).Event, ESaskartaHintEvent::None);
    TestEqual(TEXT("shows once clear"), Shown(C, C.Step(Facts(2.0, {TEXT("show_on")}))), FName(TEXT("radio")));
    const FSaskartaHintStep Hide = C.Step(Facts(2.5, {TEXT("show_on")}, {}, true));
    TestEqual(TEXT("a story line hides it"), Hide.Reason, FName(TEXT("blocked")));
    TestFalse(TEXT("barely seen: not remembered"), C.Seen.Contains(FName(TEXT("radio"))));
    TestEqual(TEXT("it comes back"), Shown(C, C.Step(Facts(4.0, {TEXT("show_on")}))), FName(TEXT("radio")));
    C.Step(Facts(7.0, {TEXT("show_on")}, {}, true));
    TestTrue(TEXT("read for 3 s: remembered"), C.Seen.Contains(FName(TEXT("radio"))));
    TestEqual(TEXT("and gone for good"), C.Step(Facts(20.0, {TEXT("show_on")})).Event, ESaskartaHintEvent::None);
    FSaskartaOnboardingCore Delayed;
    Delayed.GapS = 0.f;
    Delayed.Hints = {Hint(TEXT("later"), {TEXT("playing")}, {TEXT("used")}, 0, 2.f)};
    Delayed.Hints[0].bSkipIfKnown = true;
    Delayed.Step(Facts(1.0, {TEXT("playing")}, {TEXT("used")}, true));
    TestFalse(TEXT("blocked menu input does not teach an action"), Delayed.Known.Contains(FName(TEXT("used"))));
    TestEqual(TEXT("blocked time does not satisfy the delay"), Delayed.Step(Facts(20.0, {TEXT("playing")})).Event, ESaskartaHintEvent::None);
    TestEqual(TEXT("delay starts at allowed gameplay"), Shown(Delayed, Delayed.Step(Facts(22.0, {TEXT("playing")}))), FName(TEXT("later")));
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaOnboardingRulesTest, "Saskarta.Onboarding.Rules", SASKARTA_ONBOARDING_TEST_FLAGS)
bool FSaskartaOnboardingRulesTest::RunTest(const FString&)
{
    using namespace SaskartaOnboardingTest;
    {
        FSaskartaOnboardingCore C;
        C.GapS = 0.f;
        C.Hints = {Hint(TEXT("drive"), {TEXT("playing")}, {TEXT("drive_controls_used")}, 20),
                   Hint(TEXT("later"), {TEXT("playing")}, {TEXT("later_used")})};
        C.Hints[1].After = {FName(TEXT("drive"))};
        // The shell remembers movement/look, but emits completion only once the
        // drive row is active and has reached MinReadS. A delayed voice cannot
        // skip an unseen drive prerequisite and trap every later instruction.
        C.Step(Facts(1.0, {TEXT("playing")}, {}, true));
        C.Step(Facts(8.0, {TEXT("playing")}, {}, true));
        TestEqual(TEXT("first controls still show after delayed speech and prior input"),
            Shown(C, C.Step(Facts(9.0, {TEXT("playing")}))), FName(TEXT("drive")));
        TestEqual(TEXT("prior input still leaves a readable first row"),
            C.Step(Facts(10.0, {TEXT("playing")})).Event, ESaskartaHintEvent::None);
        TestEqual(TEXT("remembered controls dismiss after readable hold"),
            C.Step(Facts(10.5, {TEXT("playing")}, {TEXT("drive_controls_used")})).Reason, FName(TEXT("done")));
        TestEqual(TEXT("later contextual hints remain eligible"),
            Shown(C, C.Step(Facts(11.0, {TEXT("playing")}))), FName(TEXT("later")));
    }
    {
        FSaskartaOnboardingCore C;
        C.GapS = 0.f;
        FSaskartaHintDef Drive = Hint(TEXT("drive"), {TEXT("playing")}, {TEXT("moving")}, 0, 3.f);
        Drive.bSkipIfKnown = true;
        C.Hints = {Drive};
        C.Step(Facts(0.0, {TEXT("playing")}));
        TestEqual(TEXT("the delay holds it"), C.Step(Facts(2.0, {TEXT("playing")})).Event, ESaskartaHintEvent::None);
        C.Step(Facts(2.5, {TEXT("playing"), TEXT("moving")}));
        TestEqual(TEXT("already driving: never taught"), C.Step(Facts(4.0, {TEXT("playing")})).Event, ESaskartaHintEvent::None);
        TestTrue(TEXT("and marked seen (saved)"), C.Seen.Contains(FName(TEXT("drive"))));
    }
    {
        FSaskartaOnboardingCore C;
        C.GapS = 0.f;
        FSaskartaHintDef Later = Hint(TEXT("later"), {TEXT("x")}, {TEXT("y")}, 9);
        Later.After = {FName(TEXT("first"))};
        C.Hints = {Later, Hint(TEXT("first"), {TEXT("x")}, {TEXT("z")})};
        TestEqual(TEXT("after: the prerequisite first"), Shown(C, C.Step(Facts(1.0, {TEXT("x")}))), FName(TEXT("first")));
        C.Step(Facts(2.0, {TEXT("x")}, {TEXT("z")}));
        TestEqual(TEXT("then the dependant"), Shown(C, C.Step(Facts(3.0, {TEXT("x")}))), FName(TEXT("later")));
    }
    {
        FSaskartaOnboardingCore C;
        C.GapS = 0.f;
        FSaskartaHintDef Turbo = Hint(TEXT("turbo"), {TEXT("moving")}, {TEXT("turbo_used")});
        Turbo.FromRoadM = 1300.f;
        Turbo.ToRoadM = 1520.f;
        FSaskartaHintDef Charging = Hint(TEXT("charging"), {TEXT("charging")}, {TEXT("!resting")});
        C.Hints = {Turbo, Charging};
        TestEqual(TEXT("outside the road window"), C.Step(Facts(1.0, {TEXT("moving")}, {}, false, 1200.f)).Event, ESaskartaHintEvent::None);
        TestEqual(TEXT("inside it"), Shown(C, C.Step(Facts(2.0, {TEXT("moving")}, {}, false, 1400.f))), FName(TEXT("turbo")));
        C.Step(Facts(3.0, {TEXT("moving")}, {TEXT("turbo_used")}, false, 1410.f));
        TestEqual(TEXT("charging shows while resting"), Shown(C, C.Step(Facts(4.0, {TEXT("charging"), TEXT("resting")}))), FName(TEXT("charging")));
        TestEqual(TEXT("!resting: driving off dismisses it"), C.Step(Facts(5.0, {})).Reason, FName(TEXT("done")));
    }
    {
        FSaskartaOnboardingCore C;
        C.Hints = {Hint(TEXT("map"), {TEXT("scanned_any")}, {TEXT("map_opened")})};
        C.Seen.Add(FName(TEXT("map"))); // restored from Saskarta_Hints
        TestEqual(TEXT("seen in the save: never again"), C.Step(Facts(10.0, {TEXT("scanned_any")})).Event, ESaskartaHintEvent::None);
    }
    {
        FSaskartaHintDef H = Hint(TEXT("radio"), {}, {});
        H.Text = TEXT("R Â· RADIO");
        H.PadText = TEXT("D-PAD UP Â· RADIO");
        TestEqual(TEXT("keyboard text"), FSaskartaOnboardingCore::TextFor(H, false), FString(TEXT("R Â· RADIO")));
        TestEqual(TEXT("gamepad text"), FSaskartaOnboardingCore::TextFor(H, true), FString(TEXT("D-PAD UP Â· RADIO")));
        H.PadText.Reset();
        TestEqual(TEXT("no pad text: the same line"), FSaskartaOnboardingCore::TextFor(H, true), FString(TEXT("R Â· RADIO")));
    }
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaOnboardingDataTest, "Saskarta.Onboarding.Data", SASKARTA_ONBOARDING_TEST_FLAGS)
bool FSaskartaOnboardingDataTest::RunTest(const FString&)
{
    FString Json;
    const FString Path = FPaths::ProjectDir() / TEXT("docs/story/onboarding.json");
    if (!FFileHelper::LoadFileToString(Json, *Path))
    {
        AddError(FString::Printf(TEXT("cannot read %s"), *Path));
        return false;
    }
    FSaskartaOnboardingCore C;
    FString Error;
    if (!TestTrue(TEXT("onboarding.json parses"), C.ParseJson(Json, Error)))
    {
        AddError(Error);
        return false;
    }
    TestEqual(TEXT("parse error"), Error, FString());
    for (const TCHAR* Id : {TEXT("drive"), TEXT("radio"), TEXT("numbered"), TEXT("motor_tuning"),
             TEXT("boost"), TEXT("lamps"), TEXT("power_low"), TEXT("inscriptions"), TEXT("optics_lost"), TEXT("drone_feed")})
    {
        const int32 I = C.FindHint(FName(Id));
        if (!TestTrue(FString::Printf(TEXT("hint %s"), Id), I != INDEX_NONE))
        {
            continue;
        }
        const FSaskartaHintDef& H = C.Hints[I];
        TestTrue(FString::Printf(TEXT("%s is dismissable"), Id), H.DoneWhen.Num() > 0);
        TestTrue(FString::Printf(TEXT("%s holds at most 8 s"), Id), H.HoldS > 0.f && H.HoldS <= 8.f);
        for (const TCHAR* Ch = *H.Text; *Ch; ++Ch)
        {
            // Font_Terminal (VT323): ASCII and the middle dot only.
            TestTrue(FString::Printf(TEXT("%s glyphs"), Id), *Ch < 128 || *Ch == 0x00B7);
        }
        for (const FName& A : H.After)
        {
            TestTrue(FString::Printf(TEXT("%s after a known hint"), Id), C.FindHint(A) != INDEX_NONE);
        }
    }
    const int32 RadioIndex = C.FindHint(FName(TEXT("radio")));
    if (TestTrue(TEXT("radio hint exists"), C.Hints.IsValidIndex(RadioIndex)))
    {
        TestEqual(TEXT("radio switch guidance"), C.Hints[RadioIndex].Text, FString(TEXT("R . RADIO")));
    }
    const FSaskartaHintDef& Drive = C.Hints[C.FindHint(FName(TEXT("drive")))];
    TestTrue(TEXT("drive clears after movement and look"), Drive.DoneWhen.Contains(FName(TEXT("drive_controls_used"))));
    const FSaskartaHintDef& Boost = C.Hints[C.FindHint(FName(TEXT("boost")))];
    TestTrue(TEXT("boost is taught before use"), Boost.When.Contains(FName(TEXT("boost_available"))));
    TestFalse(TEXT("boost never requires prior boost"), Boost.When.Contains(FName(TEXT("turbo_on"))));
    TestTrue(TEXT("progressive boost follows driving"), Boost.After.Contains(FName(TEXT("drive"))));
    TestTrue(TEXT("readable quiet gap"), C.GapS >= 6.f);
    const int32 TuningIndex = C.FindHint(FName(TEXT("motor_tuning")));
    if (TestTrue(TEXT("motor tuning hint exists"), C.Hints.IsValidIndex(TuningIndex)))
    {
        TestEqual(TEXT("pad tuning key"), C.Hints[TuningIndex].PadText, FString(TEXT("TUNE MOTOR")));
    }
    return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS
