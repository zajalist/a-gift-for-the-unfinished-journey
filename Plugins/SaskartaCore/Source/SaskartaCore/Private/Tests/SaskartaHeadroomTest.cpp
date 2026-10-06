// Automation tests for the task HEADROOM pure logic: the focus-loss debounce (immediate exit,
// held entry), the RAM-pressure hysteresis (median-smoothed, held both ways), and the two
// decisions that hand off to SaskartaLoadingBudget (t.MaxFPS ownership, deferred RAM-pressure
// GC). No engine calls; SaskartaHeadroomGovernor.h documents the engine-side wiring these feed.
//
//   Automation RunTests Saskarta.Headroom

#include "Misc/AutomationTest.h"

#if WITH_DEV_AUTOMATION_TESTS

#include "SaskartaHeadroomGovernor.h"

namespace SaskartaHeadroomTest
{
    using FStep = FSaskartaHeadroomCore::FStep;

    static FSaskartaHeadroomCore MakeCore()
    {
        FSaskartaHeadroomCore Core;
        Core.FocusLossHoldS = 1.5;
        Core.RamPressureHoldS = 5.0;
        Core.RamLowFraction = 0.10f;
        Core.RamRecoverFraction = 0.18f;
        Core.RamWindowSamples = 6;
        return Core;
    }
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaHeadroomFocusTest, "Saskarta.Headroom.Focus",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)
bool FSaskartaHeadroomFocusTest::RunTest(const FString&)
{
    using namespace SaskartaHeadroomTest;
    FSaskartaHeadroomCore Core = MakeCore();

    // Focused samples: never enters background.
    for (double T = 0.0; T <= 5.0; T += 1.0)
    {
        const FStep S = Core.Update(T, /*bFocused=*/true, -1.f);
        TestFalse("no enter while focused", S.bEnterBackground);
    }
    TestFalse("still foreground", Core.IsBackground());

    // Losing focus does not flip immediately, or before the hold elapses.
    FStep S0 = Core.Update(10.0, false, -1.f);
    TestFalse("not yet at t=10 (just lost focus)", S0.bEnterBackground);
    TestFalse("still foreground before hold", Core.IsBackground());

    FStep S1 = Core.Update(11.0, false, -1.f); // 1.0 s unfocused < 1.5 s hold
    TestFalse("still under the 1.5 s hold", S1.bEnterBackground);
    TestFalse("still foreground under the hold", Core.IsBackground());

    FStep S2 = Core.Update(11.6, false, -1.f); // 1.6 s unfocused >= 1.5 s hold
    TestTrue("enters background once the hold elapses", S2.bEnterBackground);
    TestTrue("now background", Core.IsBackground());

    // A single re-focused sample exits immediately, no hold.
    FStep S3 = Core.Update(11.7, true, -1.f);
    TestTrue("exits background on the very next focused sample", S3.bExitBackground);
    TestFalse("back to foreground", Core.IsBackground());

    // Losing focus again re-arms the same hold from scratch (no carried-over partial time).
    FStep S4 = Core.Update(11.8, false, -1.f);
    TestFalse("hold restarts after returning to foreground", S4.bEnterBackground);
    FStep S5 = Core.Update(13.2, false, -1.f); // only 1.4 s since S4
    TestFalse("1.4 s < 1.5 s hold, still foreground", S5.bEnterBackground);
    FStep S6 = Core.Update(13.4, false, -1.f); // 1.6 s since S4
    TestTrue("hold elapses again", S6.bEnterBackground);

    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaHeadroomCpuPriorityTest, "Saskarta.Headroom.CpuPriority",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)
bool FSaskartaHeadroomCpuPriorityTest::RunTest(const FString&)
{
    using EAction = FSaskartaHeadroomCore::EProcessPriorityAction;
    FSaskartaHeadroomCore Core = SaskartaHeadroomTest::MakeCore();
    TestTrue("foreground does not lower CPU priority", Core.DecideProcessPriorityAction(false, true) == EAction::None);

    // Packaged startup can begin unfocused. Healthy RAM does not justify
    // emptying its working set: background CPU policy remains independent.
    Core.Update(0.0, false, 0.51f);
    TestTrue("focus debounce still applies", Core.DecideProcessPriorityAction(false, true) == EAction::None);
    Core.Update(1.6, false, 0.51f);
    TestFalse("observed51 percent free is not RAM pressure", Core.IsRamPressured());
    TestTrue("unfocused startup applies CPU policy once", Core.DecideProcessPriorityAction(false, true) == EAction::Apply);
    TestTrue("owned CPU priority is not repeatedly applied", Core.DecideProcessPriorityAction(true, true) == EAction::None);
    TestTrue("priority CVar off restores while still unfocused", Core.DecideProcessPriorityAction(true, false) == EAction::Revert);
    TestTrue("disabled and unowned does nothing", Core.DecideProcessPriorityAction(false, false) == EAction::None);

    Core.Update(40.0, false, 0.51f);
    TestTrue("long background stay needs no repeated process operation", Core.DecideProcessPriorityAction(true, true) == EAction::None);
    Core.Update(40.1, true, 0.51f);
    TestTrue("focus return restores CPU priority", Core.DecideProcessPriorityAction(true, true) == EAction::Revert);
    TestTrue("failed restore remains eligible for retry", Core.DecideProcessPriorityAction(true, true) == EAction::Revert);
    TestTrue("successful restore clears ownership", Core.DecideProcessPriorityAction(false, true) == EAction::None);
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaHeadroomRamTest, "Saskarta.Headroom.RamPressure",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)
bool FSaskartaHeadroomRamTest::RunTest(const FString&)
{
    using namespace SaskartaHeadroomTest;

    // A single low-RAM blip does not trip pressure: the median of the 6-sample window stays high.
    {
        FSaskartaHeadroomCore Core = MakeCore();
        double T = 0.0;
        for (int32 I = 0; I < 5; ++I, T += 1.0)
        {
            Core.Update(T, true, 0.50f); // plenty free
        }
        const FStep Blip = Core.Update(T, true, 0.01f); // one bad sample among 6
        TestFalse("one low sample does not trip pressure", Blip.bRamPressureOn);
        TestFalse("not pressured", Core.IsRamPressured());
    }

    // Sustained low RAM (median below RamLowFraction) for RamPressureHoldS trips it; recovery
    // needs RamRecoverFraction sustained for the same hold (hysteresis - a value between the two
    // thresholds does neither).
    {
        FSaskartaHeadroomCore Core = MakeCore();
        double T = 0.0;
        // Fill the median window with sustained low RAM (median well under 0.10). The median is
        // not evaluated at all until the window has RamWindowSamples entries, so the hold starts
        // exactly at the sample that fills it (T=5.0), not before.
        for (int32 I = 0; I < 6; ++I, T += 1.0)
        {
            const FStep S = Core.Update(T, true, 0.05f);
            TestFalse("pressure not on before the 5 s hold elapses", S.bRamPressureOn);
        }
        // Window full and below threshold from T=5.0; hold ends at T=10.0.
        FStep Held = Core.Update(9.9, true, 0.05f);
        TestFalse("just under the 5 s hold", Held.bRamPressureOn);
        FStep On = Core.Update(10.1, true, 0.05f);
        TestTrue("pressure trips once sustained past the hold", On.bRamPressureOn);
        TestTrue("now pressured", Core.IsRamPressured());

        // A value between RamLowFraction (0.10) and RamRecoverFraction (0.18) clears neither flag,
        // however the window mixes old (0.05) and new (0.14) samples while it flushes: 0.14 alone
        // is already below 0.18, so every possible blend of the two stays below 0.18 too.
        T = 10.1;
        for (int32 I = 0; I < 8; ++I)
        {
            T += 1.0;
            const FStep Mid = Core.Update(T, true, 0.14f);
            TestFalse("mid-band value never turns pressure back off", Mid.bRamPressureOff);
        }
        TestTrue("still pressured in the hysteresis band", Core.IsRamPressured());
        // The window is now a known, homogeneous [0.14 x 6] (8 consecutive feeds flushed the
        // 6-sample FIFO): T is 18.1 here.

        // Recovery: feed 0.30 (> RamRecoverFraction). With a homogeneous [0.14 x 6] start and a
        // 6-sample median window, the 6-of-window median (old low, new high) works out to:
        //   1st/2nd 0.30 sample: median still 0.14 (4-5 old 0.14s still outvote it)
        //   3rd 0.30 sample:     window is {0.14,0.14,0.14,0.30,0.30,0.30} -> median 0.22 (crosses)
        //   4th+ 0.30 sample:    window has 4+ 0.30s -> median 0.30
        // So RamHighSinceS is set on the 3rd sample, not the 6th; the hold is timed from there.
        Core.Update(19.1, true, 0.30f); // 1st: median 0.14, no cross
        Core.Update(20.1, true, 0.30f); // 2nd: median 0.14, no cross
        const FStep Cross = Core.Update(21.1, true, 0.30f); // 3rd: median 0.22, crosses -> RamHighSinceS = 21.1
        TestFalse("crossing sample itself is not yet a 5 s hold", Cross.bRamPressureOff);
        FStep StillOn = Core.Update(26.0, true, 0.30f); // 21.1 + 4.9 s: just under the hold
        TestFalse("just under the recovery hold", StillOn.bRamPressureOff);
        FStep Off = Core.Update(26.2, true, 0.30f); // 21.1 + 5.1 s: past the hold
        TestTrue("pressure clears once recovery is sustained", Off.bRamPressureOff);
        TestFalse("no longer pressured", Core.IsRamPressured());
    }

    // Unknown RAM samples (negative) do not perturb the running window or trip anything.
    {
        FSaskartaHeadroomCore Core = MakeCore();
        double T = 0.0;
        for (int32 I = 0; I < 20; ++I, T += 1.0)
        {
            const FStep S = Core.Update(T, true, -1.f);
            TestFalse("unknown RAM never trips pressure", S.bRamPressureOn);
        }
        TestFalse("unknown RAM leaves pressure off", Core.IsRamPressured());
    }

    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaHeadroomIndependenceTest, "Saskarta.Headroom.Independence",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)
bool FSaskartaHeadroomIndependenceTest::RunTest(const FString&)
{
    using namespace SaskartaHeadroomTest;
    // Focus and RAM pressure are independent axes: toggling one never flips the other, and both
    // can be true (or false) at once.
    FSaskartaHeadroomCore Core = MakeCore();
    double T = 0.0;
    for (int32 I = 0; I < 6; ++I, T += 1.0)
    {
        Core.Update(T, true, 0.05f); // focused, low RAM building up
    }
    T += 0.1;
    Core.Update(T, true, 0.05f);
    for (int32 I = 0; I < 5; ++I)
    {
        T += 1.0;
        Core.Update(T, true, 0.05f);
    }
    TestTrue("RAM pressure tripped while focused", Core.IsRamPressured());
    TestFalse("focus loss did not happen on its own", Core.IsBackground());

    // Now lose focus: RAM pressure is untouched, background also becomes true.
    T += 1.0;
    Core.Update(T, false, 0.05f);
    T += 1.6;
    const FStep S = Core.Update(T, false, 0.05f);
    TestTrue("enters background independently", S.bEnterBackground);
    TestTrue("both true at once", Core.IsBackground() && Core.IsRamPressured());

    // Regaining focus clears only Background, not RAM pressure.
    T += 0.1;
    const FStep S2 = Core.Update(T, true, 0.05f);
    TestTrue("exits background", S2.bExitBackground);
    TestFalse("RAM pressure unaffected by focus", S2.bRamPressureOff);
    TestTrue("RAM pressure still on", Core.IsRamPressured());

    return true;
}

// Regression tests for the two confirmed handoff bugs with USaskartaLoadingBudget: the FPS clamp
// must never write t.MaxFPS while the loading budget owns it (either direction), and the
// RAM-pressure GC must never fire while the loading budget owns the frame - it defers instead.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaHeadroomLoadingInteractionTest, "Saskarta.Headroom.LoadingInteraction",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)
bool FSaskartaHeadroomLoadingInteractionTest::RunTest(const FString&)
{
    using namespace SaskartaHeadroomTest;
    using EFpsAction = FSaskartaHeadroomCore::EFpsAction;
    using EGCAction = FSaskartaHeadroomCore::EGCAction;

    // ---- FPS clamp: while the loading budget owns t.MaxFPS, never touch it, either direction ----
    {
        FSaskartaHeadroomCore Core = MakeCore();
        // The confirmed bug: alt-tab clamps to 15, a load then starts mid-background. The old
        // code reverted all the way back to the pre-background baseline instead of leaving the
        // loading budget's own cap alone.
        TestTrue("background, holding a clamp, loading now owns fps: never revert",
            Core.DecideFpsAction(/*bHoldingClamp=*/true, /*bLoadingOwnsFps=*/true, /*bFpsEnabled=*/true) == EFpsAction::None);
        TestTrue("background, loading owns fps, no fps configured either: still None",
            Core.DecideFpsAction(true, true, /*bFpsEnabled=*/false) == EFpsAction::None);

        // Same trap via the other edge: focus already returned (exit-background) while the load
        // is still up - must still leave the loading budget's cap alone, not revert to baseline.
        Core.Update(0.0, /*bFocused=*/true, -1.f);
        TestTrue("foreground again, still holding, loading owns fps: never revert",
            Core.DecideFpsAction(true, true, true) == EFpsAction::None);
    }

    // ---- FPS clamp: ordinary cases with the loading budget never involved ----
    {
        FSaskartaHeadroomCore Core = MakeCore();
        Core.Update(0.0, false, -1.f);
        Core.Update(1.6, false, -1.f); // past the 1.5 s hold: now background
        TestTrue("background, not holding, loading off, fps enabled: Apply",
            Core.DecideFpsAction(/*bHoldingClamp=*/false, /*bLoadingOwnsFps=*/false, /*bFpsEnabled=*/true) == EFpsAction::Apply);
        TestTrue("background, fps disabled (<=0), not holding: None (nothing to apply or revert)",
            Core.DecideFpsAction(false, false, /*bFpsEnabled=*/false) == EFpsAction::None);

        Core.Update(1.7, true, -1.f); // exits background immediately
        TestTrue("foreground, holding, loading off: Revert",
            Core.DecideFpsAction(/*bHoldingClamp=*/true, false, true) == EFpsAction::Revert);
        TestTrue("foreground, not holding, loading off: None",
            Core.DecideFpsAction(false, false, true) == EFpsAction::None);
    }

    // ---- RAM-pressure GC: deferred while the loading budget owns the frame ----
    {
        FSaskartaHeadroomCore Core = MakeCore();
        double T = 0.0;
        for (int32 I = 0; I < 6; ++I, T += 1.0)
        {
            Core.Update(T, true, 0.05f); // fill the median window, sustained low RAM
        }
        T += 5.1; // past the 5 s hold
        const FSaskartaHeadroomCore::FStep OnStep = Core.Update(T, true, 0.05f);
        TestTrue("pressure trips this sample", OnStep.bRamPressureOn);

        // The confirmed bug: this used to force a GC unconditionally, mid-load, defeating
        // SaskartaLoadingBudget's documented "no GC during loading" guarantee.
        TestTrue("pressure trips while loading owns the frame: deferred, no GC now",
            Core.DecideRamPressureGCAction(OnStep, /*bLoadingOwnsFps=*/true) == EGCAction::None);

        const FSaskartaHeadroomCore::FStep NoEdge; // no fields set: not an edge sample
        TestTrue("still loading, no new edge: stays deferred",
            Core.DecideRamPressureGCAction(NoEdge, true) == EGCAction::None);

        TestTrue("loading ends, pressure still on: the deferred GC fires now",
            Core.DecideRamPressureGCAction(NoEdge, false) == EGCAction::ForceNow);
        TestTrue("one-shot: does not fire again the following sample",
            Core.DecideRamPressureGCAction(NoEdge, false) == EGCAction::None);
    }

    // ---- RAM-pressure GC: ordinary case, loading never involved - fires immediately as before ----
    {
        FSaskartaHeadroomCore Core = MakeCore();
        double T = 0.0;
        for (int32 I = 0; I < 6; ++I, T += 1.0)
        {
            Core.Update(T, true, 0.05f);
        }
        T += 5.1;
        const FSaskartaHeadroomCore::FStep OnStep = Core.Update(T, true, 0.05f);
        TestTrue("pressure trips, loading off: fires immediately",
            Core.DecideRamPressureGCAction(OnStep, false) == EGCAction::ForceNow);
    }

    // ---- RAM-pressure GC: pressure clears before loading ever releases the frame - cancelled,
    // not fired later when loading eventually ends ----
    {
        FSaskartaHeadroomCore Core = MakeCore();
        double T = 0.0;
        for (int32 I = 0; I < 6; ++I, T += 1.0)
        {
            Core.Update(T, true, 0.05f);
        }
        T += 5.1;
        const FSaskartaHeadroomCore::FStep OnStep = Core.Update(T, true, 0.05f);
        TestEqual("deferred while loading owns the frame", static_cast<uint8>(Core.DecideRamPressureGCAction(OnStep, true)), static_cast<uint8>(EGCAction::None));

        FSaskartaHeadroomCore::FStep OffStep;
        bool bCleared = false;
        for (int32 I = 0; I < 12 && !bCleared; ++I)
        {
            T += 1.0;
            OffStep = Core.Update(T, true, 0.30f); // sustained recovery
            bCleared = OffStep.bRamPressureOff;
        }
        TestTrue("pressure clears while still loading", bCleared);
        TestTrue("clearing cancels the deferred GC",
            Core.DecideRamPressureGCAction(OffStep, true) == EGCAction::None);

        const FSaskartaHeadroomCore::FStep NoEdge;
        TestTrue("loading ends after pressure already cleared: nothing pending",
            Core.DecideRamPressureGCAction(NoEdge, false) == EGCAction::None);
    }

    return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS
