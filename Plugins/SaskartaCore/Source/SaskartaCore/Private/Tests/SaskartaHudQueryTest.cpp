// Automation tests for the HUD query lane (storyline-first-light.md 4.2-4.3, SaskartaHudQueryLogic.h):
// query then result timing, the status lines (ROUTE_BOARD_V3.md: they replace the ?-column), HudLine sharing with POI lines, wreck priority, staleness,
// the cinematic hold and cue preemption, the import of ShowHudQuery / hud_beats, and the real data's totals.
// Written offline while the standalone playtest held the binaries. Run after the build:
//   Automation RunTests Saskarta.HudQuery

#include "Misc/AutomationTest.h"

#if WITH_DEV_AUTOMATION_TESTS

#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "SaskartaHudQueryLogic.h"
#include "SaskartaStoryImport.h"

#define SASKARTA_HUD_TEST_FLAGS (EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)

namespace SaskartaHudQueryTest
{
    static FSaskartaHudItem Q(const TCHAR* Query, const TCHAR* Result, const TCHAR* Column, bool bPriority = false)
    {
        FSaskartaHudItem I;
        I.Id = FName(Query);
        I.Query = Query;
        I.Result = Result;
        I.bPriority = bPriority;
        return I;
    }

    static FString Lines(const TArray<FSaskartaHudOutput>& Out)
    {
        FString S;
        for (const FSaskartaHudOutput& O : Out)
        {
            if (O.Kind == ESaskartaHudOut::ShowLine)
            {
                S += O.Text + TEXT("|");
            }
            else if (O.Kind == ESaskartaHudOut::HideLine)
            {
                S += TEXT("-|");
            }
        }
        return S;
    }
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaHudQueryTimingTest, "Saskarta.HudQuery.Timing", SASKARTA_HUD_TEST_FLAGS)
bool FSaskartaHudQueryTimingTest::RunTest(const FString&)
{
    using namespace SaskartaHudQueryTest;
    FSaskartaHudLane L;
    TArray<FSaskartaHudOutput> Out;
    L.Push(Q(TEXT("APRICOT?"), TEXT("ROOF · NO FRUIT"), TEXT("APRICOT?")), 0.0, false, Out);
    TestEqual(TEXT("query shows at once with a tick"), Out.Num() > 0 ? static_cast<int32>(Out[0].Kind) : -1, static_cast<int32>(ESaskartaHudOut::Tick));
    TestEqual(TEXT("query line"), Lines(Out), FString(TEXT("APRICOT?|")));
    Out.Reset();
    L.Advance(1.9, false, Out);
    TestEqual(TEXT("query holds 2 s"), Out.Num(), 0);
    L.Advance(2.0, false, Out);
    TestEqual(TEXT("result at 2 s"), Lines(Out), FString(TEXT("ROOF · NO FRUIT|")));
    Out.Reset();
    L.Advance(5.0, false, Out);
    TestEqual(TEXT("hidden at 5 s"), Lines(Out), FString(TEXT("-|")));
    TestTrue(TEXT("no ?-column any more"), L.Column.IsEmpty());
    TestTrue(TEXT("idle"), L.IsIdle());

    Out.Reset();
    L.Push(Q(TEXT("STONE?"), TEXT("STONE ✓ INSCRIBED"), TEXT("")), 10.0, false, Out);
    L.Advance(12.0, false, Out);
    L.Advance(15.0, false, Out);
    Out.Reset();
    FSaskartaHudItem Bend = Q(TEXT("BEND 1"), TEXT(""), TEXT(""));
    Bend.QueryS = 2.5f;
    L.Push(Bend, 20.0, false, Out);
    L.Advance(22.5, false, Out);
    TestEqual(TEXT("a count shows alone then hides"), Lines(Out), FString(TEXT("BEND 1|-|")));
    // The status lines: set by the BOARD, shown at once, faded by B18's HudStatus, re-shown with the new text.
    Out.Reset();
    L.SetStatus(TEXT("MOTOR READY\nCHARGE 35%"), Out);
    TestTrue(TEXT("status shows"), Out.Num() == 1 && Out[0].Kind == ESaskartaHudOut::ShowColumn);
    Out.Reset();
    L.SetStatus(TEXT("MOTOR READY\nCHARGE 35%"), Out);
    TestEqual(TEXT("same status: nothing"), Out.Num(), 0);
    L.SetColumnVisible(false, Out);
    Out.Reset();
    L.SetStatus(TEXT("MOTOR READY\nCHARGE 50%"), Out);
    TestEqual(TEXT("faded: kept, not shown"), Out.Num(), 0);
    L.SetColumnVisible(true, Out);
    TestTrue(TEXT("re-shown with the new text"), Out.Num() == 1 && Out[0].Text == TEXT("MOTOR READY\nCHARGE 50%"));
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaHudQuerySharingTest, "Saskarta.HudQuery.Sharing", SASKARTA_HUD_TEST_FLAGS)
bool FSaskartaHudQuerySharingTest::RunTest(const FString&)
{
    using namespace SaskartaHudQueryTest;
    FSaskartaHudLane L;
    TArray<FSaskartaHudOutput> Out;
    L.NoteExternalLine(0.0, 3.f, Out);
    L.Push(Q(TEXT("GATE?"), TEXT("POST ×2 · NO WALL"), TEXT("GATE?")), 0.5, false, Out);
    TestEqual(TEXT("waits while a POI line holds HudLine"), Lines(Out), FString());
    L.Push(Q(TEXT("CARRIER 01 — NO RESPONSE"), TEXT(""), TEXT(""), true), 1.0, false, Out);
    L.Advance(3.2, false, Out);
    TestEqual(TEXT("the wreck line goes first"), Lines(Out), FString(TEXT("CARRIER 01 — NO RESPONSE|")));
    Out.Reset();
    L.Advance(5.2, false, Out);
    TestEqual(TEXT("then the query"), Lines(Out), FString(TEXT("-|GATE?|")));

    // A POI line arriving mid-query sends the query back to the front; it restarts after.
    Out.Reset();
    L.NoteExternalLine(6.0, 2.f, Out);
    TestFalse(TEXT("query yielded"), L.bActive);
    L.Advance(8.2, false, Out);
    TestEqual(TEXT("query restarts"), Lines(Out), FString(TEXT("GATE?|")));

    // Stale: a road query that waited more than MaxWaitS is dropped; a wreck line is not.
    FSaskartaHudLane S;
    Out.Reset();
    S.NoteExternalLine(0.0, 30.f, Out);
    S.Push(Q(TEXT("HERON?"), TEXT("ACOUSTIC ONLY"), TEXT("HERON?")), 0.0, false, Out);
    S.Push(Q(TEXT("CARRIER 02 — NO RESPONSE"), TEXT(""), TEXT(""), true), 0.0, false, Out);
    S.Advance(31.0, false, Out);
    TestEqual(TEXT("only the wreck line survives"), Lines(Out), FString(TEXT("CARRIER 02 — NO RESPONSE|")));
    TestEqual(TEXT("stale query dropped"), S.Pending.Num(), 0);
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaHudQueryCinematicTest, "Saskarta.HudQuery.Cinematic", SASKARTA_HUD_TEST_FLAGS)
bool FSaskartaHudQueryCinematicTest::RunTest(const FString&)
{
    using namespace SaskartaHudQueryTest;
    FSaskartaHudLane L;
    TArray<FSaskartaHudOutput> Out;
    L.Push(Q(TEXT("FIRE?"), TEXT("PIT · COLD"), TEXT("FIRE?")), 0.0, true, Out);
    L.Advance(40.0, true, Out);
    TestEqual(TEXT("held under a cinematic, unaged"), Lines(Out), FString());
    L.Advance(40.1, false, Out);
    TestEqual(TEXT("starts at the hand-back"), Lines(Out), FString(TEXT("FIRE?|")));

    // A cue (bImmediate) preempts a road query that is still asking; the query returns first in line.
    Out.Reset();
    FSaskartaHudItem Cue = Q(TEXT("WATER?"), TEXT(""), TEXT("WATER?"));
    Cue.bImmediate = true;
    Cue.QueryS = 1.f;
    L.Push(Cue, 40.5, true, Out);
    TestEqual(TEXT("cue shows at once"), Lines(Out), FString(TEXT("WATER?|")));
    TestEqual(TEXT("FIRE? requeued"), L.Pending.Num(), 1);
    // The cinematic's own POI line (the borrowed result) ends the cue.
    Out.Reset();
    L.NoteExternalLine(40.9, 3.f, Out);
    TestEqual(TEXT("line not hidden under the POI line"), Lines(Out), FString());

    // Status fade (B18).
    Out.Reset();
    L.SetColumnVisible(false, Out);
    TestEqual(TEXT("fade"), Out.Num() == 1 && Out[0].Kind == ESaskartaHudOut::HideColumn, true);
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaHudQueryImportTest, "Saskarta.HudQuery.Import", SASKARTA_HUD_TEST_FLAGS)
bool FSaskartaHudQueryImportTest::RunTest(const FString&)
{
    const FString Json = TEXT(R"({"beats":[],"hud_beats":[{"id":"Q02_APRICOT","distance_m":600,"ue_distance_from_p0_m":4530,"trigger":"pass",
        "actions":[{"type":"ShowHudQuery","id":"Q02","text":"APRICOT?","result":"ROOF · NO FRUIT","column":"APRICOT?"}]},
        {"id":"W03_WRECK","distance_m":3550,"ue_distance_from_p0_m":1550,"trigger":"pass",
        "actions":[{"type":"ShowHudQuery","id":"W03","text":"CARRIER 03 — NO RESPONSE","target_tag":"HudPriority","duration_s":3}]}]})");
    TArray<FSaskartaBeatDef> Beats;
    TArray<FSaskartaCinematicDef> Cines;
    TArray<FSaskartaGlanceDef> Glances;
    FString Error;
    TestTrue(TEXT("parses"), USaskartaStoryImport::ParseStoryJson(Json, Beats, Cines, Glances, Error));
    if (!TestEqual(TEXT("two hud beats"), Beats.Num(), 2))
    {
        return false;
    }
    TestTrue(TEXT("hud only"), FSaskartaHudLane::IsHudOnlyBeat(Beats[0]));
    FSaskartaHudItem I;
    TestTrue(TEXT("item"), FSaskartaHudLane::ItemFromAction(Beats[0].Actions[0], I));
    TestEqual(TEXT("result"), I.Result, FString(TEXT("ROOF · NO FRUIT")));
    TestEqual(TEXT("defaults 2 s"), I.QueryS, 2.f);
    FSaskartaHudItem W;
    FSaskartaHudLane::ItemFromAction(Beats[1].Actions[0], W);
    TestTrue(TEXT("wreck priority"), W.bPriority);
    TestEqual(TEXT("wreck 3 s"), W.QueryS, 3.f);
    FSaskartaEventAction Fade;
    Fade.Type = ESaskartaActionType::ShowHudQuery;
    Fade.TargetTag = FSaskartaHudLane::StatusTarget;
    Fade.Text = FText::FromString(TEXT("x"));
    FSaskartaHudItem None;
    TestFalse(TEXT("HudStatus is a command, not a line"), FSaskartaHudLane::ItemFromAction(Fade, None));
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaHudQueryRealDataTest, "Saskarta.HudQuery.RealData", SASKARTA_HUD_TEST_FLAGS)
bool FSaskartaHudQueryRealDataTest::RunTest(const FString&)
{
    FString Json;
    const FString Path = FPaths::ProjectDir() / TEXT("docs/story/story-events.json");
    if (!FFileHelper::LoadFileToString(Json, *Path))
    {
        AddWarning(TEXT("docs/story/story-events.json absent: skipped"));
        return true;
    }
    TArray<FSaskartaBeatDef> Beats;
    TArray<FSaskartaCinematicDef> Cines;
    TArray<FSaskartaGlanceDef> Glances;
    FString Error;
    TestTrue(TEXT("parses"), USaskartaStoryImport::ParseStoryJson(Json, Beats, Cines, Glances, Error));
    int32 Entries = 0;
    int32 Marks = 0;
    auto Count = [&Entries, &Marks](const TArray<FSaskartaEventAction>& Actions)
    {
        for (const FSaskartaEventAction& A : Actions)
        {
            if (A.Type != ESaskartaActionType::ShowHudQuery)
            {
                continue;
            }
            Entries += A.ColumnText.IsEmpty() ? 0 : 1;
            Marks += (A.Text.ToString().Contains(TEXT("?")) || A.ResultText.ToString().Contains(TEXT("?"))) ? 1 : 0;
        }
    };
    for (const FSaskartaBeatDef& B : Beats)
    {
        Count(B.Actions);
    }
    const int32 RoadMarks = Marks;
    for (const FSaskartaCinematicDef& C : Cines)
    {
        Count(C.Cues);
    }
    TestEqual(TEXT("no ?-column entries (ROUTE_BOARD_V3.md CUT)"), Entries, 0);
    TestEqual(TEXT("no ? in the road's HUD beats"), RoadMarks, 0);
    if (Marks > RoadMarks)
    {
        // CIN01's MOUNTAIN? cue (the machine's own query in the opening) is the author's call, not a board item.
        AddInfo(FString::Printf(TEXT("%d cinematic HUD cue(s) still carry a ?"), Marks - RoadMarks));
    }
    return true;
}

#endif
