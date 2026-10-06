// Automation tests for the capture guard's pure logic (task CAPTURE-CPP; SaskartaCaptureGuardLogic.h):
// the role of each capture in the level (the Keeper point cloud, the editor leftovers, anything
// else), what each role gets in each phase, the loading phase tracker, and the audit predicate.
// Run after the closed-editor build with
//   Automation RunTests Saskarta.CaptureGuard

#include "Misc/AutomationTest.h"

#if WITH_DEV_AUTOMATION_TESTS

#include "SaskartaCaptureGuardLogic.h"

#define SASKARTA_CAPTURE_TEST_FLAGS (EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)

namespace SaskartaCaptureGuardTest
{
    using ERole = ESaskartaCaptureRole;
    using EPhase = ESaskartaCapturePhase;
    using ECmd = ESaskartaCaptureCommand;

    static const TArray<FString> NoExtra;

    static TArray<FString> SceneCapture2DChain()
    {
        return { TEXT("SceneCapture2D"), TEXT("SceneCapture"), TEXT("Actor"), TEXT("Object") };
    }

    /** The three capture actors saved in Saskarta_WP's external actors (names from their packages). */
    static FSaskartaCaptureIdentity KeeperInPie()
    {
        FSaskartaCaptureIdentity Id;
        Id.ActorName = TEXT("SceneCapture2D_UAID_D8BBC14136F4DF0503_2029613486");
        Id.ActorLabel = TEXT("KeeperPointCloud_Capture");
        Id.ClassNames = SceneCapture2DChain();
        Id.TextureTargetName = TEXT("RT_Saskarta_LoadingTraveller");
        return Id;
    }

    static FSaskartaCaptureIdentity LookTempInPie(const TCHAR* Label)
    {
        FSaskartaCaptureIdentity Id;
        Id.ActorName = TEXT("SceneCapture2D_UAID_D8BBC14136F4F80503_1472400765");
        Id.ActorLabel = Label;
        Id.ClassNames = SceneCapture2DChain();
        return Id;
    }

    static FSaskartaCaptureIdentity HaybaHelper()
    {
        FSaskartaCaptureIdentity Id;
        Id.ActorName = TEXT("HaybaMCPCaptureActor_UAID_D8BBC14136F4B50503_1523376969");
        Id.ClassNames = { TEXT("HaybaMCPCaptureActor"), TEXT("Actor"), TEXT("Object") };
        return Id;
    }

    static FSaskartaCaptureIdentity Other(const TCHAR* Label, const TCHAR* Target)
    {
        FSaskartaCaptureIdentity Id;
        Id.ActorName = TEXT("SceneCapture2D_UAID_0000000000000000_1");
        Id.ActorLabel = Label;
        Id.ClassNames = SceneCapture2DChain();
        Id.TextureTargetName = Target;
        return Id;
    }
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaCaptureGuardClassifyTest, "Saskarta.CaptureGuard.Classify", SASKARTA_CAPTURE_TEST_FLAGS)
bool FSaskartaCaptureGuardClassifyTest::RunTest(const FString& Parameters)
{
    using namespace SaskartaCaptureGuardTest;
    using L = FSaskartaCaptureGuardLogic;

    // The Keeper point cloud: by its editor label (PIE) and, in a cooked game without labels, by its render target.
    TestTrue("Keeper by label", L::Classify(KeeperInPie(), NoExtra) == ERole::LoadingOnly);
    {
        FSaskartaCaptureIdentity Cooked = KeeperInPie();
        Cooked.ActorLabel.Reset();
        TestTrue("Keeper cooked, by render target", L::Classify(Cooked, NoExtra) == ERole::LoadingOnly);
        Cooked.TextureTargetName = TEXT("rt_saskarta_loadingtraveller");
        TestTrue("render target name ignores case", L::Classify(Cooked, NoExtra) == ERole::LoadingOnly);
        Cooked.TextureTargetName = TEXT("RT_Saskarta_LoadingTraveller_Old");
        TestTrue("render target must match whole", L::Classify(Cooked, NoExtra) == ERole::Unmanaged);
    }
    {
        FSaskartaCaptureIdentity Tagged = Other(TEXT("SomeLoadingCapture"), TEXT("RT_Other"));
        Tagged.Tags.Add(L::LoadingTag);
        TestTrue("Saskarta.LoadingCapture tag", L::Classify(Tagged, NoExtra) == ERole::LoadingOnly);
        FSaskartaCaptureIdentity NameTag = Other(TEXT(""), TEXT(""));
        NameTag.ActorLabel.Reset();
        NameTag.Tags.Add(TEXT("KeeperPointCloud_Capture"));
        TestTrue("KeeperPointCloud_Capture as a tag (cooked)", L::Classify(NameTag, NoExtra) == ERole::LoadingOnly);
    }

    // The editor leftovers.
    TestTrue("Look_TempCapture", L::Classify(LookTempInPie(TEXT("Look_TempCapture")), NoExtra) == ERole::Stray);
    TestTrue("Look_TempCapture_0", L::Classify(LookTempInPie(TEXT("Look_TempCapture_0")), NoExtra) == ERole::Stray);
    TestTrue("Look_TempCapture_1", L::Classify(LookTempInPie(TEXT("Look_TempCapture_1")), NoExtra) == ERole::Stray);
    TestTrue("prefix ignores case", L::Classify(LookTempInPie(TEXT("look_tempcapture_2")), NoExtra) == ERole::Stray);
    TestTrue("prefix, not substring", L::Classify(LookTempInPie(TEXT("My_Look_TempCapture")), NoExtra) == ERole::Unmanaged);
    TestTrue("Hayba helper by class and name", L::Classify(HaybaHelper(), NoExtra) == ERole::Stray);
    {
        FSaskartaCaptureIdentity ByTag = Other(TEXT("Anything"), TEXT(""));
        ByTag.Tags.Add(TEXT("HaybaMCPCaptureActor"));
        TestTrue("Hayba helper by tag", L::Classify(ByTag, NoExtra) == ERole::Stray);
        FSaskartaCaptureIdentity Derived = Other(TEXT("Anything"), TEXT(""));
        Derived.ClassNames.Insert(TEXT("HaybaMCPCaptureActorChild"), 0);
        TestTrue("a class whose name starts with a stray prefix", L::Classify(Derived, NoExtra) == ERole::Stray);
        FSaskartaCaptureIdentity StrayTagged = Other(TEXT("Anything"), TEXT("RT_Any"));
        StrayTagged.Tags.Add(L::StrayTag);
        TestTrue("Saskarta.StrayCapture tag", L::Classify(StrayTagged, NoExtra) == ERole::Stray);
    }

    // Loading beats stray: a loading capture is never switched off while the loading screen is up.
    {
        FSaskartaCaptureIdentity Both = KeeperInPie();
        Both.Tags.Add(L::StrayTag);
        TestTrue("loading-only wins over stray", L::Classify(Both, NoExtra) == ERole::LoadingOnly);
    }

    // Everything else is left alone.
    TestTrue("an unrelated capture", L::Classify(Other(TEXT("SensorMonitor_Capture"), TEXT("RT_SensorMonitor")), NoExtra) == ERole::Unmanaged);
    TestTrue("no owner, nothing", L::Classify(FSaskartaCaptureIdentity(), NoExtra) == ERole::Unmanaged);
    TestTrue("the SceneCapture2D class alone is nothing", L::Classify(Other(TEXT(""), TEXT("")), NoExtra) == ERole::Unmanaged);

    // The CVar list of extra stray prefixes.
    const TArray<FString> Extra = L::ParseList(TEXT(" L1_LookCapture, ,V2_RoadCapture,"));
    TestEqual("extra list parsed", Extra.Num(), 2);
    TestTrue("extra prefix makes a stray", L::Classify(Other(TEXT("L1_LookCapture"), TEXT("RT_L1")), Extra) == ERole::Stray);
    TestTrue("without the extra list it is unmanaged", L::Classify(Other(TEXT("L1_LookCapture"), TEXT("RT_L1")), NoExtra) == ERole::Unmanaged);
    TestTrue("extra list never demotes the Keeper", L::Classify(KeeperInPie(), L::ParseList(TEXT("KeeperPointCloud"))) == ERole::LoadingOnly);
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaCaptureGuardDecideTest, "Saskarta.CaptureGuard.Decide", SASKARTA_CAPTURE_TEST_FLAGS)
bool FSaskartaCaptureGuardDecideTest::RunTest(const FString& Parameters)
{
    using namespace SaskartaCaptureGuardTest;
    using L = FSaskartaCaptureGuardLogic;

    const EPhase Phases[] = { EPhase::Startup, EPhase::Loading, EPhase::Linger, EPhase::Play };
    for (const EPhase P : Phases)
    {
        TestTrue(FString::Printf(TEXT("unmanaged left alone in %s"), L::PhaseName(P)), L::Decide(ERole::Unmanaged, P) == ECmd::Leave);
        TestTrue(FString::Printf(TEXT("stray off in %s"), L::PhaseName(P)), L::Decide(ERole::Stray, P) == ECmd::Off);
    }
    TestTrue("loading-only as authored at startup", L::Decide(ERole::LoadingOnly, EPhase::Startup) == ECmd::Leave);
    TestTrue("loading-only on while loading", L::Decide(ERole::LoadingOnly, EPhase::Loading) == ECmd::On);
    TestTrue("loading-only kept during the linger", L::Decide(ERole::LoadingOnly, EPhase::Linger) == ECmd::Leave);
    TestTrue("loading-only off in play", L::Decide(ERole::LoadingOnly, EPhase::Play) == ECmd::Off);
    for (const EPhase P : Phases)
    {
        TestTrue(FString::Printf(TEXT("unused loading capture stays off in %s"), L::PhaseName(P)),
            L::Decide(ERole::LoadingOnly, P, false) == ECmd::Off);
        TestTrue(TEXT("consumer gate leaves gameplay cameras alone"),
            L::Decide(ERole::Unmanaged, P, false) == ECmd::Leave);
    }
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaCaptureGuardPhaseTest, "Saskarta.CaptureGuard.Phases", SASKARTA_CAPTURE_TEST_FLAGS)
bool FSaskartaCaptureGuardPhaseTest::RunTest(const FString& Parameters)
{
    using namespace SaskartaCaptureGuardTest;

    // Before Start (no BeginPlay yet) nothing moves.
    {
        FSaskartaLoadingPhaseTracker T;
        TestFalse("not started: no change", T.Update(5.0, true));
        TestTrue("not started: Startup", T.GetPhase() == EPhase::Startup);
        TestFalse("not started flag", T.HasStarted());
    }

    // The start sequence: BeginIntro sets Loading 0.05 s in, BeginTitle clears it ~50 s later,
    // the loading widget's fade keeps the signal a little longer, then play; a later loading comes back.
    {
        FSaskartaLoadingPhaseTracker T;
        T.StartGraceS = 8.0;
        T.LingerS = 1.5;
        T.Start(100.0);
        TestFalse("startup, no signal yet", T.Update(100.02, false));
        TestTrue("still Startup", T.GetPhase() == EPhase::Startup);
        TestTrue("loading signal -> Loading", T.Update(100.05, true));
        TestTrue("Loading", T.GetPhase() == EPhase::Loading);
        TestEqual("one loading window", T.GetLoadingCount(), 1);
        TestFalse("long loading stays Loading", T.Update(140.0, true));
        TestTrue("signal drops -> Linger", T.Update(151.0, false));
        TestTrue("Linger", T.GetPhase() == EPhase::Linger);
        TestFalse("inside the linger", T.Update(152.0, false));
        TestTrue("signal back inside the linger -> Loading", T.Update(152.2, true));
        TestTrue("Loading again", T.GetPhase() == EPhase::Loading);
        TestEqual("a flicker is not a new loading window", T.GetLoadingCount(), 1);
        TestTrue("drops again -> Linger", T.Update(153.0, false));
        TestFalse("1.4 s: still Linger", T.Update(154.4, false));
        TestTrue("1.5 s: Play", T.Update(154.5, false));
        TestTrue("Play", T.GetPhase() == EPhase::Play);
        TestFalse("play stays play", T.Update(900.0, false));
        TestTrue("next loading -> Loading", T.Update(901.0, true));
        TestEqual("second loading window", T.GetLoadingCount(), 2);
        TestTrue("-> Linger", T.Update(930.0, false));
        TestTrue("-> Play", T.Update(932.0, false));
        TestTrue("Play at the end", T.GetPhase() == EPhase::Play);
    }

    // A start that never shows the loading screen (a debug start): Play after the grace.
    {
        FSaskartaLoadingPhaseTracker T;
        T.StartGraceS = 8.0;
        T.Start(0.0);
        TestFalse("7.9 s: Startup", T.Update(7.9, false));
        TestTrue("8 s: Play", T.Update(8.0, false));
        TestTrue("Play", T.GetPhase() == EPhase::Play);
        TestEqual("no loading window", T.GetLoadingCount(), 0);
    }

    // No linger: Loading -> Play in one poll.
    {
        FSaskartaLoadingPhaseTracker T;
        T.LingerS = 0.0;
        T.Start(0.0);
        T.Update(0.1, true);
        TestTrue("linger 0: straight to Play", T.Update(5.0, false));
        TestTrue("Play", T.GetPhase() == EPhase::Play);
    }

    // Start again (a new BeginPlay) resets the count.
    {
        FSaskartaLoadingPhaseTracker T;
        T.Start(0.0);
        T.Update(0.1, true);
        T.Start(50.0);
        TestTrue("restart: Startup", T.GetPhase() == EPhase::Startup);
        TestEqual("restart: count 0", T.GetLoadingCount(), 0);
    }
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaCaptureGuardTimelineTest, "Saskarta.CaptureGuard.Timeline", SASKARTA_CAPTURE_TEST_FLAGS)
bool FSaskartaCaptureGuardTimelineTest::RunTest(const FString& Parameters)
{
    using namespace SaskartaCaptureGuardTest;
    using L = FSaskartaCaptureGuardLogic;

    // What the Keeper capture, a leftover and another capture get over the start sequence and a
    // second loading, poll by poll (the subsystem applies a command when the phase changes).
    const ERole Keeper = L::Classify(KeeperInPie(), NoExtra);
    const ERole Leftover = L::Classify(LookTempInPie(TEXT("Look_TempCapture_0")), NoExtra);
    const ERole Mirror = L::Classify(Other(TEXT("Mirror_Capture"), TEXT("RT_Mirror")), NoExtra);

    struct FStep { double T; bool bLoading; ECmd Keeper; };
    const FStep Steps[] = {
        { 0.0, false, ECmd::Leave },  // BeginPlay: as authored
        { 0.5, true, ECmd::On },      // BeginIntro
        { 50.0, false, ECmd::Leave }, // BeginTitle + fade: linger
        { 52.0, false, ECmd::Off },   // play: the 0.5-1.5 ms are back
        { 600.0, true, ECmd::On },    // the next loading screen
        { 620.0, false, ECmd::Leave },
        { 622.0, false, ECmd::Off },
    };
    FSaskartaLoadingPhaseTracker Tracker;
    Tracker.StartGraceS = 8.0;
    Tracker.LingerS = 1.5;
    Tracker.Start(0.0);
    for (const FStep& S : Steps)
    {
        Tracker.Update(S.T, S.bLoading);
        const FString At = FString::Printf(TEXT("t=%.1f (%s)"), S.T, L::PhaseName(Tracker.GetPhase()));
        TestTrue(At + TEXT(": Keeper"), L::Decide(Keeper, Tracker.GetPhase()) == S.Keeper);
        TestTrue(At + TEXT(": leftover off"), L::Decide(Leftover, Tracker.GetPhase()) == ECmd::Off);
        TestTrue(At + TEXT(": other capture left alone"), L::Decide(Mirror, Tracker.GetPhase()) == ECmd::Leave);
    }
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaCaptureGuardAuditTest, "Saskarta.CaptureGuard.Audit", SASKARTA_CAPTURE_TEST_FLAGS)
bool FSaskartaCaptureGuardAuditTest::RunTest(const FString& Parameters)
{
    using namespace SaskartaCaptureGuardTest;
    using L = FSaskartaCaptureGuardLogic;

    TestTrue("unmanaged, every frame, active: warn", L::ShouldAudit(ERole::Unmanaged, true, true, false));
    TestFalse("warned once only", L::ShouldAudit(ERole::Unmanaged, true, true, true));
    TestFalse("not every frame: quiet", L::ShouldAudit(ERole::Unmanaged, false, true, false));
    TestFalse("inactive: quiet", L::ShouldAudit(ERole::Unmanaged, true, false, false));
    TestFalse("the guard's own loading capture: quiet", L::ShouldAudit(ERole::LoadingOnly, true, true, false));
    TestFalse("a stray (switched off anyway): quiet", L::ShouldAudit(ERole::Stray, true, true, false));

    TestEqual("empty list", L::ParseList(TEXT("")).Num(), 0);
    TestEqual("blanks dropped", L::ParseList(TEXT(" , ,")).Num(), 0);
    const TArray<FString> One = L::ParseList(TEXT("  Foo_Capture  "));
    TestEqual("one entry", One.Num(), 1);
    TestEqual("trimmed", One.Num() == 1 ? One[0] : FString(), FString(TEXT("Foo_Capture")));
    return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS
