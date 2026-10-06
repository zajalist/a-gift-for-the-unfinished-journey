// Automation tests for the Low Voice live show (docs/story/RADIO_SHOW.md; task-RADIOSHOW-brief.md part B).
//
// Pure logic with an injected clock: FSaskartaShowScheduler, FSaskartaPrefetchPlanner and the show dry run
// (SaskartaShowScheduler.h) on the real docs/story/station.json (the tests are skipped with a warning when it
// is absent). Run after the closed-editor build with
//   Automation RunTests Saskarta.Station.Show

#include "Misc/AutomationTest.h"

#if WITH_DEV_AUTOMATION_TESTS

#include "Kismet/GameplayStatics.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "SaskartaSaveGame.h"
#include "SaskartaShowScheduler.h"
#include "SaskartaStationAsset.h"

#define SASKARTA_SHOW_TEST_FLAGS (EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)

namespace SaskartaShowTest
{
    static bool LoadReal(FAutomationTestBase& Test, FSaskartaStationConfig& Out)
    {
        FString Json;
        if (!FFileHelper::LoadFileToString(Json, *FPaths::Combine(FPaths::ProjectDir(), TEXT("docs/story/station.json"))))
        {
            Test.AddWarning(TEXT("docs/story/station.json not found; skipped"));
            return false;
        }
        FString Err;
        if (!USaskartaStationImport::ParseStationJson(Json, TMap<FName, FString>(), Out, Err))
        {
            Test.AddError(FString::Printf(TEXT("station.json does not parse: %s"), *Err));
            return false;
        }
        if (!Out.Show.bShowMode)
        {
            Test.AddError(TEXT("station.json is not in show mode"));
            return false;
        }
        return true;
    }

    /** Every reaction event at probability P (the tests decide the roll). */
    static void SetProbabilities(FSaskartaStationConfig& C, float P)
    {
        for (TPair<FName, FSaskartaShowEvent>& KV : C.Show.Events)
        {
            KV.Value.Probability = P;
            KV.Value.ProbabilityClose = P;
            KV.Value.AfterBeatProbability = P;
        }
    }

    static void SetProbability(FSaskartaStationConfig& C, const TCHAR* Event, float P)
    {
        if (FSaskartaShowEvent* E = C.Show.Events.Find(FName(Event)))
        {
            E->Probability = P;
            E->ProbabilityClose = P;
            E->AfterBeatProbability = P;
        }
    }

    static TArray<FName> Shelf() { return { FName(TEXT("hayaa")), FName(TEXT("malak")), FName(TEXT("weli")) }; }

    static FSaskartaShowInput In(double T, float RoadM, float Speed = 2.f, bool bGate = true, float MaxFit = 1.0e6f)
    {
        FSaskartaShowInput I;
        I.NowS = T;
        I.RoadM = RoadM;
        I.SpeedMps = Speed;
        I.bGateOpen = bGate;
        I.MaxFitS = MaxFit;
        return I;
    }

    static const FSaskartaStationSegment* Seg(const FSaskartaStationConfig& C, FName Id)
    {
        return C.Segments.FindByPredicate([Id](const FSaskartaStationSegment& S) { return S.Id == Id; });
    }

    /** Talk lines that must never repeat within the window: FILL, LINGER, REACT, SONGIN, SONGOUT. */
    /** Mirrors SaskartaShow::RepeatMinAgeS in SaskartaShowScheduler.cpp. */
    static constexpr double RepeatMinAgeS = 150.0;

    static bool IsTalk(const FSaskartaStationConfig& C, FName Id)
    {
        const FSaskartaStationSegment* S = Seg(C, Id);
        if (!S) return false;
        const FString Cat = S->Category.ToString();
        return Cat == TEXT("FILL") || Cat == TEXT("LINGER") || Cat == TEXT("REACT") || Cat == TEXT("SONGIN") || Cat == TEXT("SONGOUT");
    }

    /** (id, start) of every voice heard in a dry run: the line, or a song block's links. */
    static void Voices(const FSaskartaStationConfig& C, const FSaskartaShowSimResult& R, TArray<TPair<FName, double>>& Out)
    {
        for (const FSaskartaShowSimItem& It : R.Items)
        {
            const bool bSong = It.Kind == ESaskartaShowKind::SongSlot || It.Kind == ESaskartaShowKind::SongReplay || It.Kind == ESaskartaShowKind::SongResume;
            if (!bSong) Out.Add(TPair<FName, double>(It.Id, It.StartS));
            if (!It.IntroId.IsNone()) Out.Add(TPair<FName, double>(It.IntroId, It.StartS));
            // A story cut during the song never reaches its outro. Record the actual outro time,
            // rather than the song's start, for the no-repeat window.
            if (!It.OutroId.IsNone() && !It.bCut)
            {
                const FSaskartaStationSegment* Outro = Seg(C, It.OutroId);
                Out.Add(TPair<FName, double>(It.OutroId, It.EndS - (Outro ? Outro->TargetS : 0.f)));
            }
        }
    }

    /** No talk line twice within the window (a cut, re-queued line is allowed back); a REACT line never twice; time checks never twice. */
    static int32 CountRepeats(FAutomationTestBase& Test, const FSaskartaStationConfig& C, const FSaskartaShowSimResult& R)
    {
        TMap<FName, double> Last;
        TSet<FName> Cut;
        for (const FSaskartaShowSimItem& It : R.Items)
        {
            if (It.bCut && !It.Id.IsNone()) Cut.Add(It.Id);
        }
        TArray<TPair<FName, double>> V;
        Voices(C, R, V);
        int32 Bad = 0;
        for (const TPair<FName, double>& P : V)
        {
            if (!IsTalk(C, P.Key)) continue;
            if (const double* Prev = Last.Find(P.Key))
            {
                const FSaskartaStationSegment* S = Seg(C, P.Key);
                const bool bReact = S && S->Category == FName(TEXT("REACT"));
                const bool bTimeCheck = S && S->bTimeCheck;
                // The repeat pool (2026-10-05) re-airs an already-heard FILL / LINGER line after RepeatMinAgeS.
                const bool bPool = S && (S->Category == FName(TEXT("FILL")) || S->Category == FName(TEXT("LINGER")));
                const bool bTooSoon = P.Value - *Prev < (bPool ? RepeatMinAgeS : C.Show.NoRepeatWindowS);
                if ((bReact || bTimeCheck || bTooSoon) && !Cut.Contains(P.Key))
                {
                    ++Bad;
                    Test.AddError(FString::Printf(TEXT("%s repeated after %.0f s"), *P.Key.ToString(), P.Value - *Prev));
                }
            }
            Last.Add(P.Key, P.Value);
        }
        return Bad;
    }

    static FSaskartaShowSimParams Drive(float Speed, int32 Seed = 1)
    {
        FSaskartaShowSimParams P;
        P.SpeedMps = Speed;
        P.Seed = Seed;
        P.Beats = SaskartaShowDefaultBeats(12.f);
        P.Songs = Shelf();
        P.SongLenS = 150.f;
        return P;
    }

    static bool Played(const FSaskartaShowSimResult& R, FName Id)
    {
        return R.Items.ContainsByPredicate([Id](const FSaskartaShowSimItem& It) { return It.Id == Id && !It.bCut; })
            || R.Items.ContainsByPredicate([Id](const FSaskartaShowSimItem& It) { return It.Id == Id && (It.Kind == ESaskartaShowKind::SongSlot); });
    }

    static void LogTail(FAutomationTestBase& Test, const FSaskartaShowSimResult& R, int32 N)
    {
        for (int32 i = FMath::Max(0, R.Log.Num() - N); i < R.Log.Num(); ++i) Test.AddInfo(R.Log[i]);
    }

    static float VoiceLenOf(const FSaskartaStationConfig& C, int32 Seg) { return C.Segments.IsValidIndex(Seg) ? C.Segments[Seg].TargetS : -1.f; }
}

// ---------------------------------------------------------------------------- import

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaShowImportTest, "Saskarta.Station.Show.Import", SASKARTA_SHOW_TEST_FLAGS)
bool FSaskartaShowImportTest::RunTest(const FString&)
{
    using namespace SaskartaShowTest;
    FSaskartaStationConfig C;
    if (!LoadReal(*this, C)) return true;
    const FSaskartaShowConfig& S = C.Show;
    TestEqual("5 acts", S.Acts.Num(), 5);
    if (S.Acts.Num() == 5)
    {
        TestEqual("Act I backbone", S.Acts[0].Backbone.Num(), 8);
        TestEqual("Act II backbone (A2_05 cut for music)", S.Acts[1].Backbone.Num(), 10);
        TestEqual("Act III backbone", S.Acts[2].Backbone.Num(), 4);
        TestEqual("Act IV backbone", S.Acts[3].Backbone.Num(), 3);
        TestEqual("Act V backbone", S.Acts[4].Backbone.Num(), 4);
        TestEqual("Act III slot after A3_05", S.Acts[2].SongSlotAfter, FName(TEXT("SHOW_A3_05")));
        TestTrue("Act III slot is MUST", S.Acts[2].bSongSlotMust);
        TestEqual("Act III fixed intro", S.Acts[2].SongIntroFixed, FName(TEXT("SONGIN_A3_01")));
        TestEqual("Act IV song closes the act (after A4_03)", S.Acts[3].SongSlotAfter, FName(TEXT("SHOW_A4_03")));
        TestEqual("Act I closing slot (after A1_12)", S.Acts[0].SongSlotAfter, FName(TEXT("SHOW_A1_12")));
        TestTrue("Act I second slot follows the opening line", S.Acts[0].SongSlots.Num() == 1 && S.Acts[0].SongSlots[0].After == FName(TEXT("SHOW_A1_01")) && S.Acts[0].SongSlots[0].bMust);
        TestEqual("Act II has one slot", S.Acts[1].SongSlots.Num(), 0);
        TestEqual("Act II road", S.Acts[1].FromRoadM, 1000.f);
    }
    TestEqual("the opening song", S.OpeningSong, FName(TEXT("malak")));
    TestEqual("late drop", S.LateDropM, 250.f);
    TestEqual("no-repeat window", S.NoRepeatWindowS, 1200.f);
    TestEqual("silence max", S.SilenceMaxS, 3.f);
    TestEqual("global cooldown", S.GlobalCooldownS, 75.f);
    TestTrue("max per act", S.MaxPerAct.Num() == 5 && S.MaxPerAct[1] == 5);
    TestEqual("10 events", S.Events.Num(), 10);
    const FSaskartaShowEvent* L = S.Events.Find(TEXT("LIGHTNING"));
    TestTrue("LIGHTNING from Act II (the author's decision)", L && L->MinAct == 2 && L->Lines.Num() >= 1 && L->ProbabilityClose > L->Probability);
    const FSaskartaShowEvent* A = S.Events.Find(TEXT("AFTER_TAPE"));
    TestTrue("AFTER_TAPE delay", A && A->DelayS.Y > 0.f);
    TestEqual("4 POIs (three more cut for music, 9/29)", S.Pois.Num(), 4);
    TestEqual("sign-off items", S.SignoffItems.Num(), 3);
    TestEqual("collapse", S.CollapseRoadM, 4790.f);
    TestTrue("the last song is empty until provided", S.LastSong.IsEmpty());
    TestTrue("the title song is eyetae", S.TitleSong.ToString().EndsWith(TEXT("eyetae_title.eyetae_title")));
    const FSaskartaStationSegment* A33 = Seg(C, TEXT("SHOW_A3_03"));
    TestTrue("A3_03 chains after A3_02", A33 && A33->ChainAfter == FName(TEXT("SHOW_A3_02")) && A33->Must == 1);
    const FSaskartaStationSegment* A55 = Seg(C, TEXT("SHOW_A5_05"));
    TestTrue("A5_05 is the final line", A55 && A55->bFinal && A55->Must == 1);
    const FSaskartaStationSegment* A17 = Seg(C, TEXT("SHOW_A1_07"));
    TestTrue("A1_07 carries", A17 && A17->bCarry && A17->AtRoadM == 800.f);
    const FSaskartaStationSegment* R7 = Seg(C, TEXT("REACT_AFTER_TAPE_07"));
    TestTrue("REACT_AFTER_TAPE_07 after B15, Act V", R7 && R7->AfterBeat == FName(TEXT("B15")) && R7->Acts == FIntPoint(5, 5) && R7->Event == FName(TEXT("AFTER_TAPE")));
    TestTrue("B15 matches the runner's beat id", FSaskartaShowScheduler::BeatMatches(TEXT("B15"), TEXT("B15_HIGH_VOICE_IN_RANGE")));
    TestFalse("B1 does not match B15", FSaskartaShowScheduler::BeatMatches(TEXT("B1"), TEXT("B15_HIGH_VOICE_IN_RANGE")));
    // The shuffle fallback is untouched: the same file still drives the old loop.
    TestEqual("shuffle categories", C.CategoryWeights.Num(), 6);
    return true;
}

// ---------------------------------------------------------------------------- act progression by road m

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaShowOrderTest, "Saskarta.Station.Show.ActProgression", SASKARTA_SHOW_TEST_FLAGS)
bool FSaskartaShowOrderTest::RunTest(const FString&)
{
    using namespace SaskartaShowTest;
    FSaskartaStationConfig C;
    if (!LoadReal(*this, C)) return true;
    {
        FSaskartaShowScheduler S;
        S.Init(C, 1);
        TestEqual("act at 0", S.ActOfRoadM(0.f), 1);
        TestEqual("act at 999", S.ActOfRoadM(999.f), 1);
        TestEqual("act at 1000", S.ActOfRoadM(1000.f), 2);
        TestEqual("act at 2900", S.ActOfRoadM(2900.f), 3);
        TestEqual("act at 3300", S.ActOfRoadM(3300.f), 4);
        TestEqual("act at 4700", S.ActOfRoadM(4700.f), 5);
        TestEqual("act past the end", S.ActOfRoadM(9000.f), 5);
        // Forward only: the act never goes back when the road does (a reboot, a high-water mark held).
        S.Update(In(0.0, 3500.f));
        S.Update(In(1.0, 500.f));
        TestEqual("forward only", S.GetAct(), 4);
    }
    const FSaskartaShowSimResult R = SaskartaShowDryRun(C, Drive(2.f, 3));
    LogTail(*this, R, 12);
    TestTrue("the sign-off ends the show", R.bSignoffDone);
    TMap<int32, int32> LastIndex;
    int32 Backbone = 0;
    for (const FSaskartaShowSimItem& It : R.Items)
    {
        if (It.Kind != ESaskartaShowKind::Backbone) continue;
        ++Backbone;
        const FSaskartaStationSegment* S = Seg(C, It.Id);
        if (!TestNotNull(*It.Id.ToString(), S)) continue;
        // Nothing from a later act early.
        if (S->Act > It.RoadAct)
        {
            AddError(FString::Printf(TEXT("%s (Act %d) started at road %.0f m, in Act %d"), *It.Id.ToString(), S->Act, It.StartRoadM, It.RoadAct));
        }
        // Strictly in order within the act (a carried letter plays after its act's turn, by design).
        if (S->bCarry) continue;
        const int32 Index = C.Show.Acts[S->Act - 1].Backbone.IndexOfByKey(It.Id);
        const int32* Prev = LastIndex.Find(S->Act);
        if (Prev && Index < *Prev)
        {
            AddError(FString::Printf(TEXT("%s played after a later item of Act %d"), *It.Id.ToString(), S->Act));
        }
        LastIndex.Add(S->Act, Index);
    }
    TestTrue(*FString::Printf(TEXT("backbone items heard (%d)"), Backbone), Backbone >= 25);
    return true;
}

// ---------------------------------------------------------------------------- a fast drive: MUSTs only

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaShowFastTest, "Saskarta.Station.Show.FastDrive", SASKARTA_SHOW_TEST_FLAGS)
bool FSaskartaShowFastTest::RunTest(const FString&)
{
    using namespace SaskartaShowTest;
    FSaskartaStationConfig C;
    if (!LoadReal(*this, C)) return true;
    const FSaskartaShowSimResult Fast = SaskartaShowDryRun(C, Drive(5.f, 2));
    LogTail(*this, Fast, 20);
    TestTrue("the sign-off plays", Fast.bSignoffDone);
    TestTrue(*FString::Printf(TEXT("the last line ends before the collapse (at %.0f m)"), Fast.FinalEndRoadM),
        Fast.FinalEndRoadM > 0.f && Fast.FinalEndRoadM < C.Show.CollapseRoadM);
    // Every must = 2 item: the premise, the names, the last song, the hand-over, the last line.
    for (const TCHAR* Id : { TEXT("SHOW_A1_03"), TEXT("SHOW_A3_02"), TEXT("SHOW_A3_03"), TEXT("SONGSLOT_A3"), TEXT("SHOW_A5_04"), TEXT("SHOW_A5_05") })
    {
        TestTrue(*FString::Printf(TEXT("%s heard at 5 m/s"), Id), Played(Fast, FName(Id)));
    }
    TestTrue("the Act III song block has the fixed links", Fast.Items.ContainsByPredicate([](const FSaskartaShowSimItem& It)
    {
        return It.Id == FName(TEXT("SONGSLOT_A3")) && It.IntroId == FName(TEXT("SONGIN_A3_01")) && It.OutroId == FName(TEXT("SONGOUT_A3_01"));
    }));
    // The five openings.
    for (const TCHAR* Id : { TEXT("SHOW_A1_01"), TEXT("SHOW_A2_01"), TEXT("SHOW_A3_01"), TEXT("SHOW_A4_01") })
    {
        TestTrue(*FString::Printf(TEXT("%s heard at 5 m/s"), Id), Played(Fast, FName(Id)));
    }
    const int32 RequiredLineIndex = Fast.Items.IndexOfByPredicate([](const FSaskartaShowSimItem& It)
    {
        return It.Id == FName(TEXT("SHOW_A3_03"));
    });
    const int32 OpeningIndex = Fast.Items.IndexOfByPredicate([](const FSaskartaShowSimItem& It)
    {
        return It.Id == FName(TEXT("SHOW_A4_01"));
    });
    const int32 SongIndex = Fast.Items.IndexOfByPredicate([](const FSaskartaShowSimItem& It)
    {
        return It.Id == FName(TEXT("SONGSLOT_A3"));
    });
    TestTrue("Act IV opening follows the required Act III line and precedes its carried song",
        RequiredLineIndex != INDEX_NONE && OpeningIndex > RequiredLineIndex && SongIndex > OpeningIndex);
    // A slow drive hears more of the optional backbone than a fast one.
    const FSaskartaShowSimResult Slow = SaskartaShowDryRun(C, Drive(1.f, 2));
    auto Optionals = [&C](const FSaskartaShowSimResult& R)
    {
        int32 N = 0;
        for (const FSaskartaShowSimItem& It : R.Items)
        {
            const FSaskartaStationSegment* S = It.Kind == ESaskartaShowKind::Backbone && !It.bCut ? Seg(C, It.Id) : nullptr;
            N += (S && S->Must == 0) ? 1 : 0;
        }
        return N;
    };
    const int32 OptFast = Optionals(Fast), OptSlow = Optionals(Slow);
    TestTrue(*FString::Printf(TEXT("optional items: %d at 5 m/s < %d at 1 m/s"), OptFast, OptSlow), OptFast < OptSlow);
    TestTrue("the slow drive signs off too", Slow.bSignoffDone);
    TestTrue("no silence while talk was available (fast)", Fast.SilenceViolations == 0);
    return true;
}

// ---------------------------------------------------------------------------- slow drive and lingering: no repeats

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaShowSlowTest, "Saskarta.Station.Show.SlowNoRepeats", SASKARTA_SHOW_TEST_FLAGS)
bool FSaskartaShowSlowTest::RunTest(const FString&)
{
    using namespace SaskartaShowTest;
    FSaskartaStationConfig C;
    if (!LoadReal(*this, C)) return true;
    const FSaskartaShowSimResult R = SaskartaShowDryRun(C, Drive(1.f, 5));
    LogTail(*this, R, 6);
    TestEqual("no talk line within 20 min", CountRepeats(*this, C, R), 0);
    TestEqual(*FString::Printf(TEXT("never silent past %.1f s while talk was available"), C.Show.SilenceMaxS), R.SilenceViolations, 0);
    TestTrue("the sign-off plays", R.bSignoffDone);
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaShowLingerTest, "Saskarta.Station.Show.Linger", SASKARTA_SHOW_TEST_FLAGS)
bool FSaskartaShowLingerTest::RunTest(const FString&)
{
    using namespace SaskartaShowTest;
    FSaskartaStationConfig C;
    if (!LoadReal(*this, C)) return true;
    // A 15 min stop in each act, away from the story beats.
    FSaskartaShowSimParams P = Drive(3.f, 4);
    const float StopAt[] = { 500.f, 1600.f, 2950.f, 3800.f, 4420.f };
    const int32 StopAct[] = { 1, 2, 3, 4, 5 };
    for (const float M : StopAt) P.Stops.Add(FVector2f(M, 900.f));
    const FSaskartaShowSimResult R = SaskartaShowDryRun(C, P);
    LogTail(*this, R, 6);
    TestEqual("five stops", R.StopWindows.Num(), 5);
    TestEqual("no talk line within 20 min", CountRepeats(*this, C, R), 0);
    TestEqual("never silent past 3 s while talk was available", R.SilenceViolations, 0);
    for (int32 s = 0; s < R.StopWindows.Num() && s < 5; ++s)
    {
        const FVector2D W = R.StopWindows[s];
        const int32 Act = StopAct[s];
        int32 Songs = 0, Murmurs = 0;
        for (const FSaskartaShowSimItem& It : R.Items)
        {
            if (It.StartS < W.X || It.StartS >= W.Y) continue;
            // Only the stopped act's pools (never an earlier act's jokes).
            TArray<FName> Ids;
            if (It.Kind == ESaskartaShowKind::SongSlot || It.Kind == ESaskartaShowKind::SongReplay || It.Kind == ESaskartaShowKind::SongResume)
            {
                ++Songs;
                if (!It.IntroId.IsNone()) Ids.Add(It.IntroId);
                if (!It.OutroId.IsNone()) Ids.Add(It.OutroId);
            }
            else
            {
                Ids.Add(It.Id);
            }
            Murmurs += It.Kind == ESaskartaShowKind::Room ? 1 : 0;
            for (const FName& Id : Ids)
            {
                const FSaskartaStationSegment* S = Seg(C, Id);
                if (!S) continue;
                // A backbone item of the act just left may still be closing (its turn); pools are this act's only.
                const bool bRepeatPool = (S->Category == FName(TEXT("FILL")) || S->Category == FName(TEXT("LINGER")))
                    && (Act >= 5 ? S->Act == Act : S->Act <= Act);
                const bool bOk = S->Category == FName(TEXT("ROOM")) || bRepeatPool
                    || (S->Category == FName(TEXT("SHOW")) && S->Act <= Act)
                    || (S->Category == FName(TEXT("REACT")) ? (S->Acts.X <= Act && Act <= S->Acts.Y) : S->Act == Act);
                if (!bOk)
                {
                    AddError(FString::Printf(TEXT("stop %d (Act %d): %s is from another act"), s + 1, Act, *Id.ToString()));
                }
            }
        }
        AddInfo(FString::Printf(TEXT("stop %d (Act %d): %d songs, %d room murmurs"), s + 1, Act, Songs, Murmurs));
        if (s < 4)
        {
            TestTrue(*FString::Printf(TEXT("stop %d: the pools spent, a song"), s + 1), Songs >= 1);
        }
        if (s >= 3)
        {
            TestTrue(*FString::Printf(TEXT("stop %d: then room murmurs or more music"), s + 1), Murmurs >= 1 || Songs >= 2);
        }
    }
    return true;
}

// ---------------------------------------------------------------------------- reactions

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaShowReactionsTest, "Saskarta.Station.Show.Reactions", SASKARTA_SHOW_TEST_FLAGS)
bool FSaskartaShowReactionsTest::RunTest(const FString&)
{
    using namespace SaskartaShowTest;
    FSaskartaStationConfig C;
    if (!LoadReal(*this, C)) return true;
    SetProbabilities(C, 1.f);
    SetProbability(C, TEXT("STOPPED"), 0.f);
    SetProbability(C, TEXT("PASSING_POI"), 0.f);
    FSaskartaShowScheduler S;
    S.Init(C, 11);
    S.SetAvailableSongs(Shelf());
    const auto VoiceLen = [&C](int32 Seg, FName) { return VoiceLenOf(C, Seg); };
    const auto SongLen = [](FName) { return 150.f; };
    S.Update(In(0.0, 500.f));
    TestEqual("Act I", S.GetAct(), 1);

    // The author's decision: no lightning reactions in Act I.
    TestFalse("LIGHTNING is gated to Act II+", S.OnEvent(TEXT("LIGHTNING"), 10.0, true));
    TestTrue("STORM_UP queues", S.OnEvent(TEXT("STORM_UP"), 10.0));
    FSaskartaShowPick P = S.PickNext(In(10.0, 500.f), VoiceLen, SongLen);
    TestTrue("a reaction plays first (before the backbone)", P.bValid && P.Kind == ESaskartaShowKind::React);
    TestEqual("the only Act I storm line", P.Id, FName(TEXT("REACT_STORM_UP_01")));
    S.Commit(P, 10.0);

    TestFalse("the global cooldown (75 s)", S.OnEvent(TEXT("OFFROAD"), 20.0));
    TestFalse("the per-event cooldown (240 s)", S.OnEvent(TEXT("STORM_UP"), 100.0));
    TestTrue("another event after 75 s", S.OnEvent(TEXT("OFFROAD"), 100.0));
    P = S.PickNext(In(100.0, 500.f), VoiceLen, SongLen);
    TestTrue("OFFROAD line", P.bValid && P.Kind == ESaskartaShowKind::React && P.Id == FName(TEXT("REACT_OFFROAD_01")));
    S.Commit(P, 100.0);

    // Never during a story line; dropped when it cannot start within 8 s of its event.
    TestTrue("SILENCE queues", S.OnEvent(TEXT("SILENCE"), 200.0));
    for (double T = 200.5; T < 208.0; T += 1.0)
    {
        TestFalse("nothing starts during a story line", S.PickNext(In(T, 500.f, 2.f, false), VoiceLen, SongLen).bValid);
    }
    P = S.PickNext(In(209.5, 500.f), VoiceLen, SongLen);
    TestTrue("expired after 8 s", P.bValid && P.Kind != ESaskartaShowKind::React);
    TestEqual("nothing pending", S.NumPendingEvents(), 0);

    TestTrue("RADIO_BACK_ON (the SILENCE lines were cut for music)", S.OnEvent(TEXT("RADIO_BACK_ON"), 300.0));
    P = S.PickNext(In(300.0, 500.f), VoiceLen, SongLen);
    TestTrue("the third Act I reaction", P.bValid && P.Kind == ESaskartaShowKind::React);
    S.Commit(P, 300.0);
    TestEqual("3 in Act I", S.ReactsInAct(1), 3);
    TestFalse("MaxPerAct (3 in Act I)", S.OnEvent(TEXT("RESUMED"), 400.0));

    // Act IV has one remaining lightning line. It plays once, without recycling an Act II/III line.
    S.Update(In(1000.0, 3650.f));
    TestEqual("Act IV", S.GetAct(), 4);
    TSet<FName> Seen;
    for (int32 i = 0; i < 5; ++i)
    {
        const double T = 1000.0 + 200.0 * i;
        const bool bQueued = S.OnEvent(TEXT("LIGHTNING"), T, true);
        P = S.PickNext(In(T, 3650.f), VoiceLen, SongLen);
        TestTrue(*FString::Printf(TEXT("strike %d queued"), i + 1), bQueued);
        if (i == 0)
        {
            if (TestTrue("the Act IV lightning line plays", P.bValid && P.Kind == ESaskartaShowKind::React && P.Event == FName(TEXT("LIGHTNING"))))
            {
                const FSaskartaStationSegment* L = Seg(C, P.Id);
                TestEqual("the remaining Act IV line", P.Id, FName(TEXT("REACT_LIGHTNING_03")));
                TestTrue("line belongs to Act IV", L && L->Acts.X <= 4 && 4 <= L->Acts.Y);
                TestFalse(*FString::Printf(TEXT("%s not twice"), *P.Id.ToString()), Seen.Contains(P.Id));
                Seen.Add(P.Id);
                S.Commit(P, T);
            }
        }
        else
        {
            TestFalse("the Act IV lightning line is spent", P.bValid && P.Kind == ESaskartaShowKind::React && P.Event == FName(TEXT("LIGHTNING")));
        }
    }
    TestFalse("never the deniable Act I line in Act IV", Seen.Contains(FName(TEXT("REACT_LIGHTNING_01"))));
    TestTrue("MaxPerAct holds", S.ReactsInAct(4) <= 5);
    return true;
}

// ---------------------------------------------------------------------------- interrupt and resume

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaShowInterruptTest, "Saskarta.Station.Show.InterruptResume", SASKARTA_SHOW_TEST_FLAGS)
bool FSaskartaShowInterruptTest::RunTest(const FString&)
{
    using namespace SaskartaShowTest;
    FSaskartaStationConfig C;
    if (!LoadReal(*this, C)) return true;
    SetProbabilities(C, 0.f);
    SetProbability(C, TEXT("AFTER_TAPE"), 1.f);
    FSaskartaShowScheduler S;
    S.Init(C, 5);
    S.SetAvailableSongs(Shelf());
    const auto VoiceLen = [&C](int32 Seg, FName) { return VoiceLenOf(C, Seg); };
    const auto SongLen = [](FName) { return 150.f; };

    FSaskartaShowPick P = S.PickNext(In(1.0, 0.f), VoiceLen, SongLen);
    TestEqual("the opening music plays first", P.Id, FName(TEXT("SONGSLOT_OPEN")));
    S.Commit(P, 1.0);
    P = S.PickNext(In(2.0, 0.f), VoiceLen, SongLen);
    TestEqual("the show opens with A1_01", P.Id, FName(TEXT("SHOW_A1_01")));
    S.Commit(P, 2.0);
    // A story line cuts it under half heard: back to the front of the backbone.
    S.ReturnInterrupted(P, 0.3f, 5.0);
    TestFalse("not played", S.HasPlayed(TEXT("SHOW_A1_01")));
    P = S.PickNext(In(20.0, 0.f), VoiceLen, SongLen);
    TestEqual("it plays again after the story line", P.Id, FName(TEXT("SHOW_A1_01")));
    S.Commit(P, 20.0);
    // Heard past half: it counts as played.
    S.ReturnInterrupted(P, 0.7f, 30.0);
    TestTrue("played", S.HasPlayed(TEXT("SHOW_A1_01")));
    P = S.PickNext(In(40.0, 0.f), VoiceLen, SongLen);
    TestTrue("the show goes on with something else", P.bValid && P.Id != FName(TEXT("SHOW_A1_01")));

    // After B11 the tied line comes first (REACT_AFTER_TAPE_06).
    S.Update(In(100.0, 3405.f));
    S.OnStoryLineEnded(TEXT("B11_LAST_WAYSTATION"), 100.0);
    P = S.PickNext(In(101.0, 3405.f), VoiceLen, SongLen);
    TestEqual("the tied AFTER_TAPE line", P.Id, FName(TEXT("REACT_AFTER_TAPE_06")));
    S.Commit(P, 101.0);
    // The cut show has no plain AFTER_TAPE line in Act IV; a later tape must not recycle an earlier act's reaction.
    S.OnStoryLineEnded(TEXT("B08_NUMBERED_STOP"), 300.0);
    P = S.PickNext(In(302.5, 3405.f), VoiceLen, SongLen);
    TestFalse("no stale Act IV AFTER_TAPE reaction", P.bValid && P.Kind == ESaskartaShowKind::React);
    // A plain tape reaction remains available in Act II.
    FSaskartaShowScheduler Earlier;
    Earlier.Init(C, 6);
    Earlier.Update(In(300.0, 1500.f));
    Earlier.OnStoryLineEnded(TEXT("B05_WAITING_WATER"), 300.0);
    const FSaskartaShowPick EarlierPick = Earlier.PickNext(In(302.5, 1500.f), VoiceLen, SongLen);
    TestTrue("plain Act II AFTER_TAPE still plays", EarlierPick.bValid && EarlierPick.Kind == ESaskartaShowKind::React
        && EarlierPick.Event == FName(TEXT("AFTER_TAPE")));
    // A cinematic ends: the show resumes with a fill.
    S.RequestOpenWithFill();
    P = S.PickNext(In(400.0, 3405.f), VoiceLen, SongLen);
    TestTrue("back from a cinematic with a fill (a room murmur where the act has none)", P.bValid && (P.Kind == ESaskartaShowKind::Fill || P.Kind == ESaskartaShowKind::Linger || P.Kind == ESaskartaShowKind::Room));
    return true;
}

// ---------------------------------------------------------------------------- act change

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaShowActChangeTest, "Saskarta.Station.Show.ActChange", SASKARTA_SHOW_TEST_FLAGS)
bool FSaskartaShowActChangeTest::RunTest(const FString&)
{
    using namespace SaskartaShowTest;
    FSaskartaStationConfig C;
    if (!LoadReal(*this, C)) return true;
    SetProbabilities(C, 0.f);
    const auto VoiceLen = [&C](int32 Seg, FName) { return VoiceLenOf(C, Seg); };
    const auto SongLen = [](FName) { return 150.f; };
    auto Next = [&](FSaskartaShowScheduler& S, double T, float Road) -> FName
    {
        const FSaskartaShowPick P = S.PickNext(In(T, Road), VoiceLen, SongLen);
        if (P.bValid) S.Commit(P, T);
        return P.Id;
    };
    for (int32 Case = 0; Case < 2; ++Case)
    {
        // Case 0: Act I left 100 m past its end (not late). Case 1: 300 m past it (late).
        FSaskartaShowScheduler S;
        S.Init(C, 3 + Case);
        S.SetAvailableSongs(Shelf());
        TestEqual("the opening song", Next(S, 1.0, 0.f), FName(TEXT("SONGSLOT_OPEN")));
        TestEqual("A1_01", Next(S, 2.0, 0.f), FName(TEXT("SHOW_A1_01")));
        // The second song bridges the opening line and the required premise.
        TestEqual("second early song", Next(S, 30.0, 260.f), FName(TEXT("SONGSLOT_A1_2")));
        TestEqual("catch-up to A1_03", Next(S, 31.0, 260.f), FName(TEXT("SHOW_A1_03")));
        const float Road = Case == 0 ? 1100.f : 1300.f;
        S.Update(In(60.0, Road));
        TestEqual("Act II", S.GetAct(), 2);
        for (const TCHAR* Opt : { TEXT("SHOW_A1_06"), TEXT("SHOW_A1_08"), TEXT("SONGSLOT_A1") })
        {
            TestTrue(*FString::Printf(TEXT("case %d: %s dropped"), Case, Opt), S.WasDropped(FName(Opt)));
        }
        TArray<FName> Order;
        if (Case == 0)
        {
            // Not late: the two surviving MUST lines, letter and turn close Act I in order.
            for (int32 i = 0; i < 5; ++i) Order.Add(Next(S, 70.0 + 30.0 * i, Road));
            TestEqual("water rota", Order[0], FName(TEXT("SHOW_A1_04")));
            TestEqual("departure table", Order[1], FName(TEXT("SHOW_A1_05")));
            TestEqual("letter", Order[2], FName(TEXT("SHOW_A1_07")));
            TestEqual("turn", Order[3], FName(TEXT("SHOW_A1_12")));
            TestEqual("Act II opens", Order[4], FName(TEXT("SHOW_A2_01")));
        }
        else
        {
            // Late: the turn plays, the letter is carried to the front of Act II.
            TestTrue("late A1_04 dropped", S.WasDropped(TEXT("SHOW_A1_04")));
            TestTrue("late A1_05 dropped", S.WasDropped(TEXT("SHOW_A1_05")));
            for (int32 i = 0; i < 3; ++i) Order.Add(Next(S, 70.0 + 30.0 * i, Road));
            TestEqual("turn", Order[0], FName(TEXT("SHOW_A1_12")));
            TestEqual("carried letter", Order[1], FName(TEXT("SHOW_A1_07")));
            TestEqual("Act II opens", Order[2], FName(TEXT("SHOW_A2_01")));
            TestFalse("the letter is never dropped", S.WasDropped(TEXT("SHOW_A1_07")));
        }
    }
    return true;
}

// ---------------------------------------------------------------------------- save and Continue

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaShowSaveTest, "Saskarta.Station.Show.SaveRoundTrip", SASKARTA_SHOW_TEST_FLAGS)
bool FSaskartaShowSaveTest::RunTest(const FString&)
{
    using namespace SaskartaShowTest;
    FSaskartaStationConfig C;
    if (!LoadReal(*this, C)) return true;
    // Drive to the middle of Act III and save.
    FSaskartaShowScheduler S1;
    S1.Init(C, 9);
    FSaskartaShowSimParams P1 = Drive(3.f, 9);
    P1.EndRoadM = 3000.f;
    const FSaskartaShowSimResult R1 = SaskartaShowDryRun(C, P1, &S1);
    TestEqual("saved in Act III", S1.GetAct(), 3);
    const FSaskartaShowSaveState Saved = S1.SaveState(R1.EndS);
    TestTrue("valid", Saved.bValid);

    // Through the real save object (the Saskarta_Run slot's serialisation).
    USaskartaSaveGame* Save = Cast<USaskartaSaveGame>(UGameplayStatics::CreateSaveGameObject(USaskartaSaveGame::StaticClass()));
    if (!TestNotNull("save object", Save)) return false;
    Save->ShowState = Saved;
    TArray<uint8> Bytes;
    TestTrue("serialises", UGameplayStatics::SaveGameToMemory(Save, Bytes));
    const USaskartaSaveGame* Back = Cast<USaskartaSaveGame>(UGameplayStatics::LoadGameFromMemory(Bytes));
    if (!TestNotNull("deserialises", Back)) return false;
    const FSaskartaShowSaveState& L = Back->ShowState;
    TestEqual("act", L.Act, Saved.Act);
    TestEqual("played", L.PlayedBackbone.Num(), Saved.PlayedBackbone.Num());
    TestEqual("used ids", L.UsedIds.Num(), Saved.UsedIds.Num());
    TestEqual("used ages", L.UsedAgeS.Num(), Saved.UsedAgeS.Num());

    // Continue: a new session, a new clock (0).
    FSaskartaShowScheduler S2;
    S2.Init(C, 21);
    S2.SetAvailableSongs(Shelf());
    S2.LoadState(L, 0.0);
    TestEqual("same act", S2.GetAct(), S1.GetAct());
    TestEqual("same next backbone item", S2.PeekNextBackbone(), S1.PeekNextBackbone());
    for (const FSaskartaStationSegment& Seg : C.Segments)
    {
        if (S1.HasPlayed(Seg.Id) != S2.HasPlayed(Seg.Id) || S1.WasDropped(Seg.Id) != S2.WasDropped(Seg.Id))
        {
            AddError(FString::Printf(TEXT("%s: played / dropped differs after the restore"), *Seg.Id.ToString()));
        }
        const double U1 = S1.LastUsedS(Seg.Id);
        if (U1 > -1.0e8 && !FMath::IsNearlyEqual(S2.LastUsedS(Seg.Id), U1 - R1.EndS, 0.05))
        {
            AddError(FString::Printf(TEXT("%s: last use %.2f s ago before, %.2f after"), *Seg.Id.ToString(), R1.EndS - U1, -S2.LastUsedS(Seg.Id)));
        }
    }
    const auto VoiceLen = [&C](int32 Seg, FName) { return VoiceLenOf(C, Seg); };
    const auto SongLen = [](FName) { return 150.f; };
    {
        FSaskartaShowScheduler S3;
        S3.Init(C, 21);
        S3.SetAvailableSongs(Shelf());
        S3.LoadState(L, 0.0);
        const FSaskartaShowPick First = S3.PickNext(In(0.5, 3000.f, 3.f), VoiceLen, SongLen);
        TestTrue("a Continue opens with a fill (a room murmur where the act has none)", First.bValid && (First.Kind == ESaskartaShowKind::Fill || First.Kind == ESaskartaShowKind::Linger || First.Kind == ESaskartaShowKind::Room));
    }
    // The show goes on from the restore without replaying anything.
    FSaskartaShowSimParams P2 = Drive(3.f, 22);
    P2.StartRoadM = 3000.f;
    P2.EndRoadM = 3500.f;
    const FSaskartaShowSimResult R2 = SaskartaShowDryRun(C, P2, &S2, 0.0);
    TSet<FName> PlayedBefore(L.PlayedBackbone);
    TMap<FName, float> AgeBefore;
    for (int32 i = 0; i < L.UsedIds.Num() && i < L.UsedAgeS.Num(); ++i) AgeBefore.Add(L.UsedIds[i], L.UsedAgeS[i]);
    for (const FSaskartaShowSimItem& It : R2.Items)
    {
        if (It.Kind == ESaskartaShowKind::Backbone && PlayedBefore.Contains(It.Id))
        {
            AddError(FString::Printf(TEXT("%s replayed after the Continue"), *It.Id.ToString()));
        }
    }
    TArray<TPair<FName, double>> V;
    Voices(C, R2, V);
    for (const TPair<FName, double>& Vx : V)
    {
        const float* Age = AgeBefore.Find(Vx.Key);
        if (!Age || !IsTalk(C, Vx.Key)) continue;
        const FSaskartaStationSegment* S = Seg(C, Vx.Key);
        const bool bReact = S && S->Category == FName(TEXT("REACT"));
        const bool bPool = S && (S->Category == FName(TEXT("FILL")) || S->Category == FName(TEXT("LINGER")));
        if (bReact || Vx.Value + *Age < (bPool ? RepeatMinAgeS : C.Show.NoRepeatWindowS))
        {
            AddError(FString::Printf(TEXT("%s repeated %.0f s after its use before the save"), *Vx.Key.ToString(), Vx.Value + *Age));
        }
    }
    TestTrue("the show went on", R2.Items.Num() > 3);

    // The song position: a song playing at the save resumes after the opening fill.
    FSaskartaShowSaveState WithSong = L;
    WithSong.SongId = TEXT("malak");
    WithSong.SongPositionS = 30.f;
    WithSong.SongOutroId = TEXT("SONGOUT_A3_01");
    FSaskartaShowScheduler S4;
    S4.Init(C, 23);
    S4.SetAvailableSongs(Shelf());
    S4.LoadState(WithSong, 0.0);
    FSaskartaShowPick Q = S4.PickNext(In(0.5, 3000.f, 3.f), VoiceLen, SongLen);
    S4.Commit(Q, 0.5);
    // Required show lines take priority over an interrupted song; it resumes in the next gap.
    for (int32 i = 0; i < 12; ++i)
    {
        const double T = 20.0 + 20.0 * i;
        Q = S4.PickNext(In(T, 3000.f, 3.f), VoiceLen, SongLen);
        if (Q.Kind == ESaskartaShowKind::SongResume) break;
        if (Q.bValid) S4.Commit(Q, T);
    }
    TestTrue("the song resumes", Q.bValid && Q.Kind == ESaskartaShowKind::SongResume && Q.SongId == FName(TEXT("malak")));
    TestTrue("from its position", Q.Slot.Parts.Num() >= 1 && FMath::IsNearlyEqual(Q.Slot.Parts[0].StartAtS, 30.f));
    TestTrue("with its outro", Q.OutroId == FName(TEXT("SONGOUT_A3_01")));
    // Saved again before it resumes, the song position is kept.
    FSaskartaShowScheduler S5;
    S5.Init(C, 24);
    S5.LoadState(WithSong, 0.0);
    const FSaskartaShowSaveState Again = S5.SaveState(5.0);
    TestTrue("the song position survives a second save", Again.SongId == FName(TEXT("malak")) && FMath::IsNearlyEqual(Again.SongPositionS, 30.f));
    return true;
}

// ---------------------------------------------------------------------------- prefetch

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaShowPrefetchTest, "Saskarta.Station.Show.Prefetch", SASKARTA_SHOW_TEST_FLAGS)
bool FSaskartaShowPrefetchTest::RunTest(const FString&)
{
    using namespace SaskartaShowTest;
    // 1. The planner (injected clock): a bounded resident set, played items released after the grace, pinned ones kept.
    {
        FSaskartaPrefetchPlanner Pl;
        Pl.MaxResident = 6;
        Pl.ReleaseGraceS = 4.0;
        TArray<FString> Load, Release;
        Pl.Plan({ TEXT("a"), TEXT("b"), TEXT("c") }, {}, 0.0, Load, Release);
        TestEqual("loads the window", Load.Num(), 3);
        Pl.Plan({ TEXT("b"), TEXT("c"), TEXT("d") }, { TEXT("a") }, 1.0, Load, Release);
        TestTrue("loads the new item only", Load.Num() == 1 && Load[0] == TEXT("d") && Release.Num() == 0);
        Pl.Plan({ TEXT("c"), TEXT("d"), TEXT("e") }, {}, 2.0, Load, Release);
        TestTrue("within the grace nothing goes", Load.Num() == 1 && Release.Num() == 0);
        Pl.Plan({ TEXT("e"), TEXT("f") }, {}, 7.0, Load, Release);
        TestEqual("played items released after the grace", Release.Num(), 4);
        TestEqual("resident", Pl.NumResident(), 2);
        Pl.Plan({ TEXT("g"), TEXT("h"), TEXT("i"), TEXT("j"), TEXT("k"), TEXT("l"), TEXT("m"), TEXT("n") }, {}, 8.0, Load, Release);
        TestEqual("capped at 6", Pl.NumResident(), 6);
        TestEqual("the best 6 load", Load.Num(), 6);
        TestTrue("the stale ones make room", Release.Contains(TEXT("e")) && Release.Contains(TEXT("f")));
        Pl.Plan({}, { TEXT("g") }, 100.0, Load, Release);
        TestTrue("a pinned (playing) item is never released", Pl.IsResident(TEXT("g")) && !Release.Contains(TEXT("g")));
        TestEqual("the rest released", Pl.NumResident(), 1);
    }
    FSaskartaStationConfig C;
    if (!LoadReal(*this, C)) return true;
    SetProbabilities(C, 0.f);
    const auto VoiceLen = [&C](int32 Seg, FName) { return VoiceLenOf(C, Seg); };
    const auto SongLen = [](FName) { return 150.f; };
    // 2. The window: the next items, the MUSTs, the next opening, a fill, a linger line; the song block when near.
    {
        FSaskartaShowScheduler S;
        S.Init(C, 4);
        S.SetAvailableSongs(Shelf());
        S.Update(In(0.0, 0.f));
        FSaskartaShowUpcoming Up = S.GetUpcoming(3);
        auto Has = [&Up](const TCHAR* Id) { return Up.Voices.ContainsByPredicate([Id](const FSaskartaShowVoiceRef& V) { return V.Id == FName(Id); }); };
        TestTrue("the first backbone lines are prefetched", Up.Voices.Num() >= 3
            && Up.Voices[0].Id == FName(TEXT("SHOW_A1_01"))
            && Up.Voices[1].Id == FName(TEXT("SHOW_A1_03"))
            && Up.Voices[2].Id == FName(TEXT("SHOW_A1_04")));
        TestTrue("every MUST of the act", Has(TEXT("SHOW_A1_07")) && Has(TEXT("SHOW_A1_12")));
        TestTrue("the next act's opening", Has(TEXT("SHOW_A2_01")));
        TestTrue("a likely fill", Up.Voices.ContainsByPredicate([](const FSaskartaShowVoiceRef& V) { return V.Id.ToString().StartsWith(TEXT("FILL_A1_")); }));
        TestTrue("a likely linger line", Up.Voices.ContainsByPredicate([](const FSaskartaShowVoiceRef& V) { return V.Id.ToString().StartsWith(TEXT("LINGER_A1_")); }));
        TestTrue("opening and next song are prefetched", Up.Songs.Contains(FName(TEXT("malak"))) && Up.Songs.Num() <= 2);
        TestTrue("bounded", Up.Voices.Num() <= 12);
        // The Act I song now follows the turn at 900 m. Walk the required lines to that turn.
        bool bReachedTurn = false;
        for (int32 i = 0; i < 12 && !bReachedTurn; ++i)
        {
            const double T = 1.0 + 30.0 * i;
            const FSaskartaShowPick P = S.PickNext(In(T, 950.f), VoiceLen, SongLen);
            if (!TestTrue("a line is available before the Act I turn", P.bValid)) break;
            S.Commit(P, T);
            bReachedTurn = P.Id == FName(TEXT("SHOW_A1_12"));
        }
        TestTrue("Act I turn reached", bReachedTurn);
        S.Update(In(400.0, 950.f));
        Up = S.GetUpcoming(3);
        TestTrue("the current song is in the window", Up.Songs.Contains(FName(TEXT("hayaa"))));
        TestFalse("the mid-slot intro is not repeated for the closing song", Up.Voices.ContainsByPredicate([](const FSaskartaShowVoiceRef& V) { return V.Id == FName(TEXT("SONGIN_A1_02")) && V.SongId == FName(TEXT("hayaa")); }));
        TArray<FName> Reacts;
        S.GetActReactionLines(S.GetAct(), Reacts);
        TestFalse("no Act I lightning to pre-warm", Reacts.Contains(FName(TEXT("REACT_LIGHTNING_01"))));
        TestTrue("the act's reactions to pre-warm", Reacts.Contains(FName(TEXT("REACT_STORM_UP_01"))));
    }
    // 3. Over a whole drive (reactions on), what starts was in the window at least 1 s before.
    {
        FSaskartaStationConfig CR;
        LoadReal(*this, CR);
        TMap<FName, TArray<FVector2D>> Intervals;
        TSet<FName> Current;
        int32 MaxWindow = 0;
        FSaskartaShowSimParams P = Drive(3.f, 8);
        P.OnTick = [&Intervals, &Current, &MaxWindow](FSaskartaShowScheduler& S, double T, float)
        {
            const FSaskartaShowUpcoming Up = S.GetUpcoming(4);
            TSet<FName> W;
            for (const FSaskartaShowVoiceRef& V : Up.Voices) W.Add(V.Id);
            for (const FName& Song : Up.Songs) W.Add(Song);
            TArray<FName> Reacts;
            S.GetActReactionLines(S.GetAct(), Reacts);
            W.Append(Reacts);
            W.Append(S.GetRoomIds());
            MaxWindow = FMath::Max(MaxWindow, W.Num());
            for (const FName& Id : W)
            {
                if (!Current.Contains(Id)) Intervals.FindOrAdd(Id).Add(FVector2D(T, 1.0e18));
            }
            for (const FName& Id : Current)
            {
                if (!W.Contains(Id))
                {
                    TArray<FVector2D>& Iv = Intervals.FindOrAdd(Id);
                    if (Iv.Num() > 0) Iv.Last().Y = T;
                }
            }
            Current = W;
        };
        const FSaskartaShowSimResult R = SaskartaShowDryRun(CR, P);
        auto Predicted = [&Intervals](FName Id, double Start)
        {
            const TArray<FVector2D>* Iv = Intervals.Find(Id);
            return Iv && Iv->ContainsByPredicate([Start](const FVector2D& I) { return I.X <= Start - 1.0 && I.Y >= Start - 0.01; });
        };
        int32 All = 0, Hit = 0, Bb = 0, BbHit = 0;
        for (const FSaskartaShowSimItem& It : R.Items)
        {
            TArray<FName> Ids;
            if (It.Kind == ESaskartaShowKind::SongSlot || It.Kind == ESaskartaShowKind::SongReplay)
            {
                Ids.Add(It.SongId);
                if (!It.IntroId.IsNone()) Ids.Add(It.IntroId);
            }
            else
            {
                Ids.Add(It.Id);
            }
            for (const FName& Id : Ids)
            {
                if (It.StartS < 2.0) continue; // the very first item (the station just came on)
                ++All;
                const bool bHit = Predicted(Id, It.StartS);
                Hit += bHit ? 1 : 0;
                if (It.Kind == ESaskartaShowKind::Backbone)
                {
                    ++Bb;
                    BbHit += bHit ? 1 : 0;
                }
                if (!bHit) AddInfo(FString::Printf(TEXT("not prefetched 1 s ahead: %s at %.0f s"), *Id.ToString(), It.StartS));
            }
        }
        TestTrue(*FString::Printf(TEXT("backbone prefetched ahead: %d / %d"), BbHit, Bb), Bb > 0 && BbHit >= Bb * 95 / 100);
        TestTrue(*FString::Printf(TEXT("everything prefetched ahead: %d / %d"), Hit, All), All > 0 && Hit >= All * 90 / 100);
        TestTrue(*FString::Printf(TEXT("the wanted set stays bounded (max %d)"), MaxWindow), MaxWindow <= 64);
    }
    return true;
}

// ---------------------------------------------------------------------------- music at the start: the opening song and Act I's two slots

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaShowOpeningSongTest, "Saskarta.Station.Show.OpeningSong", SASKARTA_SHOW_TEST_FLAGS)
bool FSaskartaShowOpeningSongTest::RunTest(const FString&)
{
    using namespace SaskartaShowTest;
    FSaskartaStationConfig C;
    if (!LoadReal(*this, C)) return true;
    SetProbabilities(C, 0.f);
    const auto VoiceLen = [&C](int32 Seg, FName) { return VoiceLenOf(C, Seg); };
    const auto SongLen = [](FName) { return 150.f; };
    for (int32 Seed = 1; Seed <= 4; ++Seed)
    {
        FSaskartaShowScheduler S;
        S.Init(C, Seed);
        S.SetAvailableSongs(Shelf());
        // The boot cinematic ends before the station comes on: still the song first, not a fill.
        S.RequestOpenWithFill();
        TArray<FSaskartaShowPick> Picks;
        double T = 1.0;
        for (int32 i = 0; i < 200 && T < 4000.0; ++i, T += 15.0)
        {
            const FSaskartaShowPick P = S.PickNext(In(T, FMath::Min(static_cast<float>(T) * 0.9f, 990.f)), VoiceLen, SongLen);
            if (!P.bValid) continue;
            S.Commit(P, T);
            Picks.Add(P);
            if (P.Id == FName(TEXT("SONGSLOT_A1"))) break;
        }
        if (!TestTrue("picks", Picks.Num() >= 3)) continue;
        TestEqual(*FString::Printf(TEXT("seed %d: the station comes on with the opening song"), Seed), Picks[0].Id, FName(TEXT("SONGSLOT_OPEN")));
        TestEqual("the opening song is malak", Picks[0].SongId, FName(TEXT("malak")));
        TestTrue("the opening song has no links", Picks[0].IntroId.IsNone() && Picks[0].OutroId.IsNone());
        TestEqual("the host comes back from it: A1_01", Picks[1].Id, FName(TEXT("SHOW_A1_01")));
        auto IndexOf = [&Picks](const TCHAR* Id) { return Picks.IndexOfByPredicate([Id](const FSaskartaShowPick& P) { return P.Id == FName(Id); }); };
        const int32 A101 = IndexOf(TEXT("SHOW_A1_01"));
        const int32 Mid = IndexOf(TEXT("SONGSLOT_A1_2"));
        const int32 A112 = IndexOf(TEXT("SHOW_A1_12"));
        const int32 End = IndexOf(TEXT("SONGSLOT_A1"));
        TestTrue(*FString::Printf(TEXT("seed %d: the second song follows A1_01 at once"), Seed), A101 != INDEX_NONE && Mid == A101 + 1);
        TestTrue("Act I closes on its song after A1_12", A112 != INDEX_NONE && End > A112 && End > Mid);
        if (Picks.IsValidIndex(Mid) && Picks.IsValidIndex(End))
        {
            TestEqual("the bag spreads the shelf: the mid-act song is weli", Picks[Mid].SongId, FName(TEXT("weli")));
            TestEqual("Act I still closes on hayaa", Picks[End].SongId, FName(TEXT("hayaa")));
        }
        // Never the same song twice in a row.
        FName LastSong;
        for (const FSaskartaShowPick& P : Picks)
        {
            if (P.SongId.IsNone()) continue;
            TestNotEqual(*FString::Printf(TEXT("seed %d: %s not back to back"), Seed, *P.SongId.ToString()), P.SongId, LastSong);
            LastSong = P.SongId;
        }
    }
    // CP0 was saved before any show item aired: Continue must retain the unheard music.
    {
        FSaskartaShowScheduler S;
        S.Init(C, 5);
        S.SetAvailableSongs(Shelf());
        const FSaskartaShowSaveState Save = S.SaveState(0.0);
        TestEqual("pre-show checkpoint act", Save.Act, 0);
        S.LoadState(Save, 100.0);
        const FSaskartaShowPick P = S.PickNext(In(101.0, 0.f), VoiceLen, SongLen);
        TestTrue("CP0 opening is playable", P.bValid);
        TestEqual("CP0 retains the unheard opening song", P.Id, FName(TEXT("SONGSLOT_OPEN")));
        TestFalse("CP0 does not discard the opening", S.WasDropped(TEXT("SONGSLOT_OPEN")));
        S.Commit(P, 101.0);
        const FSaskartaShowSaveState Started = S.SaveState(102.0);
        S.LoadState(Started, 0.0);
        TestTrue("a later Continue does not replay the opening", S.WasDropped(TEXT("SONGSLOT_OPEN")));
    }
    // A legacy save cannot prove the opening was unheard, so joins in progress.
    {
        FSaskartaShowScheduler S;
        S.Init(C, 5);
        S.LoadState(FSaskartaShowSaveState(), 0.0);
        TestTrue("legacy Continue skips the opening", S.WasDropped(TEXT("SONGSLOT_OPEN")));
    }
    // A Continue in an established show opens with a fill (or the backbone).
    {
        FSaskartaShowScheduler S;
        S.Init(C, 5);
        S.SetAvailableSongs(Shelf());
        FSaskartaShowSaveState Save;
        Save.bValid = true;
        Save.Act = 1;
        S.LoadState(Save, 100.0);
        for (int32 i = 0; i < 4; ++i)
        {
            const FSaskartaShowPick P = S.PickNext(In(100.0 + 20.0 * i, 30.f), VoiceLen, SongLen);
            if (P.bValid) S.Commit(P, 100.0 + 20.0 * i);
            TestNotEqual("no opening song on a Continue", P.Id, FName(TEXT("SONGSLOT_OPEN")));
        }
        TestTrue("the opening song is dropped on a Continue", S.WasDropped(TEXT("SONGSLOT_OPEN")));
    }
    // Starting past Act I (a debug jump): the opening song never plays late.
    {
        FSaskartaShowScheduler S;
        S.Init(C, 6);
        S.SetAvailableSongs(Shelf());
        const FSaskartaShowPick P = S.PickNext(In(1.0, 1500.f), VoiceLen, SongLen);
        TestNotEqual("no opening song in Act II", P.Id, FName(TEXT("SONGSLOT_OPEN")));
        TestTrue("dropped with Act I", S.WasDropped(TEXT("SONGSLOT_OPEN")));
    }
    // The whole drive: the opening song leads, and no shelf song plays twice back to back.
    const FSaskartaShowSimResult R = SaskartaShowDryRun(C, Drive(2.f, 4));
    const FSaskartaShowSimItem* First = R.Items.FindByPredicate([](const FSaskartaShowSimItem& It) { return It.Kind == ESaskartaShowKind::SongSlot; });
    TestTrue("the dry run opens on the opening song", First && First->Id == FName(TEXT("SONGSLOT_OPEN")));
    TestTrue("the mid-act slot plays in the dry run", Played(R, TEXT("SONGSLOT_A1_2")));
    FName Prev;
    for (const FSaskartaShowSimItem& It : R.Items)
    {
        if (It.Kind != ESaskartaShowKind::SongSlot && It.Kind != ESaskartaShowKind::SongReplay) continue;
        if (It.SongId == Prev) AddError(FString::Printf(TEXT("%s twice back to back at %.0f s"), *It.SongId.ToString(), It.StartS));
        Prev = It.SongId;
    }
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaShowContinuousMusicTest, "Saskarta.Station.Show.ContinuousMusic", SASKARTA_SHOW_TEST_FLAGS)
bool FSaskartaShowContinuousMusicTest::RunTest(const FString&)
{
    using namespace SaskartaShowTest;
    FSaskartaStationConfig C;
    if (!LoadReal(*this, C)) return true;
    SetProbabilities(C, 0.f);
    for (const float Speed : { 2.f, 5.f, 7.f })
    {
        FSaskartaShowSimParams P = Drive(Speed, 4);
        // The station turns on after B02's 8.5 s clip, near its 150 m trigger.
        P.StartRoadM = 150.f;
        P.SongLengthsS.Add(TEXT("hayaa"), 85.15f);
        P.SongLengthsS.Add(TEXT("malak"), 133.63f);
        P.SongLengthsS.Add(TEXT("weli"), 143.10f);
        for (FSaskartaShowSimBeat& B : P.Beats)
        {
            if (B.Id == FName(TEXT("B03_PROMISE"))) B.LineS = 19.43f;
            if (B.Id == FName(TEXT("B05_WAITING_WATER"))) B.LineS = 7.52f;
        }
        const FSaskartaShowSimResult R = SaskartaShowDryRun(C, P);
        const FSaskartaShowSimItem* Opening = R.Items.FindByPredicate([](const FSaskartaShowSimItem& It)
        {
            return It.Id == FName(TEXT("SONGSLOT_OPEN"));
        });
        TestTrue(*FString::Printf(TEXT("%.0f m/s: opening song starts after B02 by 250 m"), Speed), Opening && Opening->StartRoadM <= 250.f);
        int32 SongsBeforeHalf = 0;
        for (const FSaskartaShowSimItem& It : R.Items)
        {
            if (It.SongId.IsNone() || It.StartRoadM >= 2400.f) continue;
            if (It.Kind != ESaskartaShowKind::SongSlot && It.Kind != ESaskartaShowKind::SongReplay && It.Kind != ESaskartaShowKind::SongResume) continue;
            ++SongsBeforeHalf;
            AddInfo(FString::Printf(TEXT("%.0f m/s: %s SONG_%s starts at %.0f m (%.0f s)%s"), Speed,
                *It.Id.ToString(), *It.SongId.ToString(), It.StartRoadM, It.StartS, It.bCut ? TEXT(" cut") : TEXT("")));
        }
        TestTrue(*FString::Printf(TEXT("%.0f m/s: music returns in the first half"), Speed), SongsBeforeHalf >= 2);
        float LargestOpenGapS = 0.f;
        for (int32 i = 1; i < R.Items.Num(); ++i)
        {
            const FSaskartaShowSimItem& Prev = R.Items[i - 1];
            const FSaskartaShowSimItem& Next = R.Items[i];
            if (Next.StartRoadM >= 2400.f) break;
            float GapS = FMath::Max(0.f, static_cast<float>(Next.StartS - Prev.EndS));
            for (const FSaskartaShowSimBeat& B : P.Beats)
            {
                const float BeatStartS = (B.RoadM - P.StartRoadM) / Speed;
                const float BeatEndS = BeatStartS + B.LineS + P.HoldoffS;
                GapS -= FMath::Max(0.f, FMath::Min(static_cast<float>(Next.StartS), BeatEndS)
                    - FMath::Max(static_cast<float>(Prev.EndS), BeatStartS));
            }
            LargestOpenGapS = FMath::Max(LargestOpenGapS, GapS);
        }
        AddInfo(FString::Printf(TEXT("%.0f m/s: largest non-story gap in first half %.1f s"), Speed, LargestOpenGapS));
        TestTrue(*FString::Printf(TEXT("%.0f m/s: no deterministic minute of silence"), Speed), LargestOpenGapS < 60.f);
        if (Speed == 5.f)
        {
            for (const FSaskartaShowSimItem& It : R.Items)
            {
                if (It.StartRoadM > 2400.f) break;
                AddInfo(FString::Printf(TEXT("5 m/s timeline: %s %.0f-%.0f m (%.1f-%.1f s)%s"), *It.Id.ToString(),
                    It.StartRoadM, It.EndRoadM, It.StartS, It.EndS, It.bCut ? TEXT(" cut") : TEXT("")));
            }
            const FSaskartaShowSimItem* Mid = R.Items.FindByPredicate([](const FSaskartaShowSimItem& It)
            {
                return It.Id == FName(TEXT("SONGSLOT_A1_2"));
            });
            AddInfo(FString::Printf(TEXT("5 m/s: mid Act I slot %s"), Mid ? *FString::Printf(TEXT("starts at %.0f m"), Mid->StartRoadM) : TEXT("not played")));
            TestTrue(TEXT("5 m/s: a distinct mid Act I song starts before the 1000 m boundary"),
                Mid && Mid->SongId != FName(TEXT("malak")) && Mid->StartRoadM < 1000.f);
        }
        if (Speed == 7.f)
        {
            for (const FSaskartaShowSimItem& It : R.Items)
            {
                if (It.StartRoadM > 1500.f) break;
                AddInfo(FString::Printf(TEXT("7 m/s timeline: %s %.0f-%.0f m%s"), *It.Id.ToString(),
                    It.StartRoadM, It.EndRoadM, It.bCut ? TEXT(" cut") : TEXT("")));
            }
            const FSaskartaShowSimItem* Mid = R.Items.FindByPredicate([](const FSaskartaShowSimItem& It)
            {
                return It.Id == FName(TEXT("SONGSLOT_A1_2"));
            });
            TestTrue(TEXT("7 m/s: the second song starts before 1200 m"), Mid && Mid->StartRoadM < 1200.f);
        }
    }
    return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS
