// Automation tests for the Low Voice station's pure logic (STATION.md; task-RADIOSYS-brief.md part 2).
//
// No world: FSaskartaShuffleBag, FSaskartaStationScheduler, FSaskartaStationLogic and the
// station.json parser. Run after the closed-editor build with
//   Automation RunTests Saskarta.Station
// Saskarta.Station.RealData reads docs/story/station.json and is skipped when it is absent.

#include "Misc/AutomationTest.h"

#if WITH_DEV_AUTOMATION_TESTS

#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "SaskartaStationLogic.h"
#include "SaskartaRadioFx.h"
#include "SaskartaStorySettings.h"

#define SASKARTA_STATION_TEST_FLAGS (EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)

namespace SaskartaStationTest
{
    static FSaskartaStationSegment Seg(const TCHAR* Id, const TCHAR* Cat, float TargetS = 5.f, bool bLeaving = false)
    {
        FSaskartaStationSegment S;
        S.Id = FName(Id);
        S.Category = FName(Cat);
        S.TargetS = TargetS;
        S.bLeavingHint = bLeaving;
        S.Weight = bLeaving ? 0.6f : 1.f;
        return S;
    }

    /** A small station in the shape of station.json: 6 weighted categories, IDs, links. */
    static FSaskartaStationConfig Config()
    {
        FSaskartaStationConfig C;
        C.PlayFlowStates = { TEXT("Playing") };
        C.HoldFlowStates = { TEXT("Booting"), TEXT("Rebooting"), TEXT("Transferring"), TEXT("Collapsing") };
        C.CategoryWeights.Add(TEXT("NOTICE"), 3.f);
        C.CategoryWeights.Add(TEXT("TALK"), 3.f);
        C.CategoryWeights.Add(TEXT("DEDIC"), 2.f);
        C.CategoryWeights.Add(TEXT("WEATHER"), 2.f);
        C.CategoryWeights.Add(TEXT("LETTER"), 2.f);
        C.CategoryWeights.Add(TEXT("KITCHEN"), 1.f);
        const TCHAR* Cats[] = { TEXT("NOTICE"), TEXT("TALK"), TEXT("DEDIC"), TEXT("WEATHER"), TEXT("LETTER"), TEXT("KITCHEN") };
        for (const TCHAR* Cat : Cats)
        {
            for (int32 i = 1; i <= 4; ++i)
            {
                C.Segments.Add(Seg(*FString::Printf(TEXT("STN_%s_%02d"), Cat, i), Cat, 10.f + i, i == 4));
            }
        }
        for (int32 i = 1; i <= 6; ++i) C.Segments.Add(Seg(*FString::Printf(TEXT("STN_ID_%02d"), i), TEXT("ID"), 5.f));
        for (int32 i = 1; i <= 8; ++i) C.Segments.Add(Seg(*FString::Printf(TEXT("STN_INTRO_%02d"), i), TEXT("INTRO"), 5.f));
        for (int32 i = 1; i <= 8; ++i) C.Segments.Add(Seg(*FString::Printf(TEXT("STN_OUTRO_%02d"), i), TEXT("OUTRO"), 5.f));
        for (int32 i = 1; i <= 4; ++i) C.Segments.Add(Seg(*FString::Printf(TEXT("STN_REQUEST_%02d"), i), TEXT("REQUEST"), 7.f));
        return C;
    }
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaStationShuffleBagTest, "Saskarta.Station.ShuffleBag", SASKARTA_STATION_TEST_FLAGS)
bool FSaskartaStationShuffleBagTest::RunTest(const FString&)
{
    const TArray<int32> Items = { 10, 11, 12, 13, 14 };
    const TArray<float> Weights = { 1.f, 1.f, 1.f, 1.f, 0.6f };
    for (int32 Seed = 1; Seed <= 200; ++Seed)
    {
        FRandomStream R(Seed);
        FSaskartaShuffleBag Bag;
        Bag.Reset(Items, Weights);
        TSet<int32> Seen;
        int32 Last = INDEX_NONE;
        for (int32 i = 0; i < Items.Num(); ++i)
        {
            const int32 D = Bag.Draw(R);
            if (Seen.Contains(D))
            {
                AddError(FString::Printf(TEXT("seed %d: %d repeated before the bag emptied"), Seed, D));
                return false;
            }
            Seen.Add(D);
            Last = D;
        }
        TestEqual("bag empty", Bag.NumRemaining(), 0);
        // The refill never starts with the item played last.
        const int32 First = Bag.Draw(R);
        if (First == Last)
        {
            AddError(FString::Printf(TEXT("seed %d: refill started with the last item %d"), Seed, Last));
            return false;
        }
    }
    // Exclusion leaves items in the bag; PutBack returns one.
    FRandomStream R(7);
    FSaskartaShuffleBag Bag;
    Bag.Reset(Items, Weights);
    TSet<int32> Ex = { 10, 11, 12, 13 };
    TestEqual("only 14 drawable", Bag.Draw(R, &Ex), 14);
    TestEqual("excluded stay", Bag.NumRemaining(), 4);
    Bag.PutBack(14);
    TestTrue("put back", Bag.Contains(14));
    Ex.Add(14);
    TestEqual("nothing drawable", Bag.Draw(R, &Ex), INDEX_NONE);

    // Weighting: a heavy item comes out first far more often than a light one.
    int32 HeavyFirst = 0;
    for (int32 Seed = 0; Seed < 2000; ++Seed)
    {
        FRandomStream W(Seed);
        FSaskartaShuffleBag B2;
        B2.Reset({ 1, 2 }, { 9.f, 1.f });
        if (B2.Draw(W) == 1) ++HeavyFirst;
    }
    TestTrue(*FString::Printf(TEXT("weighted first draw (%d / 2000 heavy)"), HeavyFirst), HeavyFirst > 1600 && HeavyFirst < 1990);
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaStationCategoryTest, "Saskarta.Station.CategoryAndIdSlots", SASKARTA_STATION_TEST_FLAGS)
bool FSaskartaStationCategoryTest::RunTest(const FString&)
{
    const FSaskartaStationConfig C = SaskartaStationTest::Config();
    FRandomStream R(3);
    TMap<FName, int32> Counts;
    for (int32 i = 0; i < 3000; ++i)
    {
        const FName Cat = FSaskartaStationLogic::PickCategory(C.CategoryWeights, TEXT("NOTICE"), R);
        TestNotEqual("never the last category", Cat, FName(TEXT("NOTICE")));
        Counts.FindOrAdd(Cat)++;
    }
    TestTrue("TALK (3) beats KITCHEN (1)", Counts.FindRef(TEXT("TALK")) > 2 * Counts.FindRef(TEXT("KITCHEN")));

    TestFalse("slot 3", FSaskartaStationLogic::IsIdSlot(3, 4));
    TestTrue("slot 4", FSaskartaStationLogic::IsIdSlot(4, 4));
    TestTrue("slot 8", FSaskartaStationLogic::IsIdSlot(8, 4));
    TestFalse("slot 0", FSaskartaStationLogic::IsIdSlot(0, 4));

    // Two hours of schedule, several seeds: every 4th slot an ID and only then, no category
    // twice in a row, leaving lines spaced, gaps inside the configured bounds.
    for (int32 Seed = 1; Seed <= 5; ++Seed)
    {
        const FSaskartaStationDryRunStats S = SaskartaStationDryRun(C, 7200.f, Seed, {}, 0.f, nullptr);
        TestTrue("segments played", S.Segments > 40);
        TestEqual("ID slot violations", S.IdSlotViolations, 0);
        TestEqual("same category twice", S.SameCategoryRepeats, 0);
        TestEqual("leaving spacing", S.LeavingSpacingViolations, 0);
        TestTrue("gaps within 45-120 s", S.MinGapS >= C.GapS.X && S.MaxGapS <= C.GapS.Y);
        TestEqual("no songs, no song blocks", S.SongBlocks, 0);
    }
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaStationTimeTest, "Saskarta.Station.TimeScheduling", SASKARTA_STATION_TEST_FLAGS)
bool FSaskartaStationTimeTest::RunTest(const FString&)
{
    FSaskartaStationClock Clock;
    Clock.Advance(10.0, false);
    TestEqual("held: station time stands still", Clock.StationTimeS, 0.0);
    Clock.Advance(10.0, true);
    TestEqual("on: station time runs", Clock.StationTimeS, 10.0);
    FRandomStream R(11);
    Clock.ScheduleNextSongBlock(R, FVector2f(240.f, 360.f));
    TestTrue("next block 240-360 s ahead", Clock.NextSongBlockAtS >= 250.0 && Clock.NextSongBlockAtS <= 370.0);
    TestFalse("not due yet", Clock.SongBlockDue());
    Clock.Advance(400.0, true);
    TestTrue("due", Clock.SongBlockDue());

    // With a song: blocks at least 4 min of station time apart, link + song + outro.
    const FSaskartaStationConfig C = SaskartaStationTest::Config();
    const FSaskartaStationDryRunStats S = SaskartaStationDryRun(C, 3600.f, 5, { TEXT("hayaa") }, 85.f, nullptr);
    TestTrue("song blocks happen", S.SongBlocks >= 5);
    TestTrue(*FString::Printf(TEXT("spacing >= 240 s (min %.0f)"), S.MinSongSpacingS), S.MinSongSpacingS >= 240.f);

    FSaskartaStationScheduler Sched;
    Sched.Init(C, 2);
    Sched.ForceSongBlockDue();
    const FSaskartaStationPick Pick = Sched.PickSlot(1000.f, { TEXT("hayaa") },
        [&C](int32 Seg, FName) { return C.Segments[Seg].TargetS; }, [](FName) { return 85.f; });
    if (TestTrue("song block picked", Pick.bValid && Pick.bSongBlock) && TestEqual("five parts", Pick.Parts.Num(), 5))
    {
        TestTrue("link first", Pick.Parts[0].Kind == FSaskartaStationPart::EKind::Voice);
        TestEqual("0.6 s of static", Pick.Parts[1].DurationS, 0.6f);
        TestTrue("the song", Pick.Parts[2].Kind == FSaskartaStationPart::EKind::Song && Pick.Parts[2].SongId == FName(TEXT("hayaa")));
        TestEqual("1.0 s of static", Pick.Parts[3].DurationS, 1.0f);
        TestEqual("outro", C.Segments[Pick.Parts[4].SegmentIndex].Category, FName(TEXT("OUTRO")));
    }
    // The whole block must fit before the next beat: with 60 s left, no song block.
    FSaskartaStationScheduler Tight;
    Tight.Init(C, 2);
    Tight.ForceSongBlockDue();
    const FSaskartaStationPick Short = Tight.PickSlot(60.f, { TEXT("hayaa") },
        [&C](int32 Seg, FName) { return C.Segments[Seg].TargetS; }, [](FName) { return 85.f; });
    TestTrue("a segment instead", Short.bValid && !Short.bSongBlock && Short.TotalS <= 60.f);
    // Nothing fits: no pick, nothing lost from the bags.
    const FSaskartaStationPick None = Tight.PickSlot(2.f, {}, [&C](int32 Seg, FName) { return C.Segments[Seg].TargetS; }, [](FName) { return -1.f; });
    TestFalse("nothing fits in 2 s", None.bValid);
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaStationGateTest, "Saskarta.Station.StoryGate", SASKARTA_STATION_TEST_FLAGS)
bool FSaskartaStationGateTest::RunTest(const FString&)
{
    FSaskartaStationConfig C = SaskartaStationTest::Config();
    FSaskartaStationGateInput In;
    In.SecondsSinceStory = 100.f;
    In.SecondsToNextBeat = 200.f;
    In.RoadM = 1000.f;
    TestTrue("open", FSaskartaStationLogic::EvaluateGate(In, 20.f, C) == ESaskartaStationGate::Open);

    FSaskartaStationGateInput Busy = In;
    Busy.bStoryBusy = true;
    TestTrue("story line playing", FSaskartaStationLogic::EvaluateGate(Busy, 20.f, C) == ESaskartaStationGate::StoryBusy);
    FSaskartaStationGateInput Hold = In;
    Hold.SecondsSinceStory = 5.f;
    TestTrue("6 s hold-off", FSaskartaStationLogic::EvaluateGate(Hold, 20.f, C) == ESaskartaStationGate::Holdoff);
    FSaskartaStationGateInput Near = In;
    Near.SecondsToNextBeat = 24.f;
    TestTrue("under 25 s to the next beat", FSaskartaStationLogic::EvaluateGate(Near, 5.f, C) == ESaskartaStationGate::BeatTooClose);
    Near.SecondsToNextBeat = 30.f;
    TestTrue("30 s ahead fits a 20 s segment", FSaskartaStationLogic::EvaluateGate(Near, 20.f, C) == ESaskartaStationGate::Open);
    TestTrue("30 s does not fit 28 s", FSaskartaStationLogic::EvaluateGate(Near, 28.f, C) == ESaskartaStationGate::BeatTooClose);
    TestEqual("max fit = time to beat - 3", FSaskartaStationLogic::MaxFitS(Near, C), 27.f);
    FSaskartaStationGateInput Idle = In;
    Idle.bIdle = true;
    TestTrue("idle tape wins", FSaskartaStationLogic::EvaluateGate(Idle, 5.f, C) == ESaskartaStationGate::Idle);
    C.QuietRangesRoadM.Add(FVector2f(3600.f, 4460.f));
    FSaskartaStationGateInput Climb = In;
    Climb.RoadM = 4000.f;
    TestTrue("quiet climb", FSaskartaStationLogic::EvaluateGate(Climb, 5.f, C) == ESaskartaStationGate::QuietRange);

    // Mode by flow state.
    using M = ESaskartaStationMode;
    TestTrue("before B02: off", FSaskartaStationLogic::ModeFor(TEXT("Playing"), false, true, false, C) == M::Off);
    TestTrue("playing: on", FSaskartaStationLogic::ModeFor(TEXT("Playing"), true, true, false, C) == M::On);
    TestTrue("setting off: off", FSaskartaStationLogic::ModeFor(TEXT("Playing"), true, false, false, C) == M::Off);
    TestTrue("rebooting: held", FSaskartaStationLogic::ModeFor(TEXT("Rebooting"), true, true, false, C) == M::Held);
    TestTrue("human: stopped", FSaskartaStationLogic::ModeFor(TEXT("Human"), true, true, false, C) == M::Stopped);
    TestTrue("stopped stays stopped", FSaskartaStationLogic::ModeFor(TEXT("Playing"), true, true, true, C) == M::Stopped);

    TestTrue("heard half counts", FSaskartaStationLogic::CountsAsPlayed(5.f, 10.f, 0.5f));
    TestFalse("heard under half goes back", FSaskartaStationLogic::CountsAsPlayed(4.9f, 10.f, 0.5f));
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaStationTemplateTest, "Saskarta.Station.Templates", SASKARTA_STATION_TEST_FLAGS)
bool FSaskartaStationTemplateTest::RunTest(const FString&)
{
    const FString Plain = TEXT("Now a song. Voices only, the way the valley likes it.");
    const FString Tpl = TEXT("Now a song.[ This is {SINGER}.][ It's called {SONG}.] Voices only, the way the valley likes it.");
    TestEqual("no values = plain", FSaskartaStationLogic::FillTemplate(Tpl, Plain, {}), Plain);
    TMap<FString, FString> TitleOnly;
    TitleOnly.Add(TEXT("SONG"), TEXT("Hayaa"));
    TitleOnly.Add(TEXT("SINGER"), TEXT(""));
    TestEqual("title only", FSaskartaStationLogic::FillTemplate(Tpl, Plain, TitleOnly),
        FString(TEXT("Now a song. It's called Hayaa. Voices only, the way the valley likes it.")));
    TMap<FString, FString> Both = TitleOnly;
    Both.Add(TEXT("SINGER"), TEXT("The Oskan sisters"));
    TestEqual("both", FSaskartaStationLogic::FillTemplate(TEXT("[That was {SINGER}, with {SONG}. ]My tea's gone cold."), TEXT("My tea's gone cold."), Both),
        FString(TEXT("That was The Oskan sisters, with Hayaa. My tea's gone cold.")));
    TestEqual("group needs every value", FSaskartaStationLogic::FillTemplate(TEXT("[That was {SINGER}, with {SONG}. ]My tea."), TEXT("My tea."), TitleOnly),
        FString(TEXT("My tea.")));
    TestEqual("no template", FSaskartaStationLogic::FillTemplate(TEXT(""), Plain, Both), Plain);

    TestEqual("caption, title only", FSaskartaStationLogic::SongCaption(TEXT("Hayaa"), TEXT("")), FString(TEXT("Song · Hayaa")));
    TestEqual("caption, both", FSaskartaStationLogic::SongCaption(TEXT("Hayaa"), TEXT("X")), FString(TEXT("Song · Hayaa · X")));
    TestEqual("caption, neither", FSaskartaStationLogic::SongCaption(TEXT(" "), TEXT("")), FString(TEXT("Song")));
    // Only glyphs the caption fonts carry (Cormorant Garamond has no U+266A; Slate logged a last-resort fallback).
    TestFalse("caption has no music-note glyph", FSaskartaStationLogic::SongCaption(TEXT("Hayaa"), TEXT("X")).Contains(TEXT("♪")));
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaStationReceptionTest, "Saskarta.Station.Reception", SASKARTA_STATION_TEST_FLAGS)
bool FSaskartaStationReceptionTest::RunTest(const FString&)
{
    FSaskartaStationConfig C;
    C.QualityByRoadM = { FVector2f(0.f, 1.f), FVector2f(1550.f, 0.92f), FVector2f(3550.f, 0.62f), FVector2f(4790.f, 0.25f) };
    TestEqual("dock", FSaskartaStationLogic::Quality(C.QualityByRoadM, 0.f), 1.f);
    TestEqual("key", FSaskartaStationLogic::Quality(C.QualityByRoadM, 1550.f), 0.92f, 1.0e-4f);
    TestEqual("between", FSaskartaStationLogic::Quality(C.QualityByRoadM, 775.f), 0.96f, 1.0e-4f);
    TestEqual("past the end", FSaskartaStationLogic::Quality(C.QualityByRoadM, 6000.f), 0.25f, 1.0e-4f);
    TestEqual("low-pass at q 1", FSaskartaStationLogic::MapQ(1.f, C.VoiceLowpassHz), 5500.f);
    TestEqual("low-pass at q 0.25", FSaskartaStationLogic::MapQ(0.25f, C.VoiceLowpassHz), 2400.f);
    TestEqual("gain halfway", FSaskartaStationLogic::MapQ(0.625f, C.VoiceGainDb), -2.f, 1.0e-4f);
    TestEqual("no dropouts at 0.85", FSaskartaStationLogic::DropoutRate(0.85f, C), 0.f);
    TestEqual("full rate at 0.25", FSaskartaStationLogic::DropoutRate(0.25f, C), C.DropoutRateAtLowQ, 1.0e-4f);
    TestEqual("-12 dB", FSaskartaStationLogic::DbToLinear(-12.f), 0.2512f, 1.0e-3f);
    C.VoiceGainDb = FVector2f(0.f, -10.f);
    C.VoiceGainDbAtQ0 = -40.f;
    TestEqual("authored zero-signal endpoint, not another -40 dB added", FSaskartaStationLogic::ReceptionVoiceDb(0.f, C), -40.f);
    TestEqual("continuous below-quarter interpolation", FSaskartaStationLogic::ReceptionVoiceDb(0.125f, C), -25.f);
    TestEqual("normal reception at q=.25 unchanged", FSaskartaStationLogic::ProgrammeGainDb(0.25f, C), -10.f);
    for (float Q : { 0.f, 0.04f, 0.1f, 0.18f, 0.25f, 0.5f, 1.f })
        TestTrue("ordinary mountain programme remains intelligible", FSaskartaStationLogic::ProgrammeGainDb(Q, C) >= -12.f);
    TestEqual("walk score subdued", FSaskartaStationLogic::EndingMusicDb(TEXT("Human")), -10.f);
    TestEqual("report score yields to words", FSaskartaStationLogic::EndingMusicDb(TEXT("Transmit")), -16.f);
    TestEqual("credits rise on same player", FSaskartaStationLogic::EndingMusicDb(TEXT("End")), 0.f);
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaStationTakesTest, "Saskarta.Station.Takes", SASKARTA_STATION_TEST_FLAGS)
bool FSaskartaStationTakesTest::RunTest(const FString&)
{
    const FString Host = TEXT("/Game/SaskartaGaea/Audio/Station/Host");
    const TArray<FString> Plain = FSaskartaStationLogic::TakeCandidates(Host, TEXT("STN_ID_01"), NAME_None);
    if (TestEqual("two candidates", Plain.Num(), 2))
    {
        TestEqual("the user's recording first", Plain[0], Host + TEXT("/Recorded/VO_Station_STN_ID_01.VO_Station_STN_ID_01"));
        TestEqual("then the placeholder", Plain[1], Host + TEXT("/VO_Station_STN_ID_01.VO_Station_STN_ID_01"));
        const FString ResolvedPlain = FSaskartaStationLogic::FirstExistingTakeCandidate(Plain,
            [&Plain](const FString& Path) { return Path == Plain[1]; });
        TestEqual("plain Host recording is a valid runtime-resolved take", ResolvedPlain, Plain[1]);
        TestTrue("missing only when every runtime candidate is absent",
            FSaskartaStationLogic::FirstExistingTakeCandidate(Plain, [](const FString&) { return false; }).IsEmpty());
    }
    const TArray<FString> Named = FSaskartaStationLogic::TakeCandidates(Host, TEXT("STN_INTRO_02"), TEXT("hayaa"));
    if (TestEqual("four candidates", Named.Num(), 4))
    {
        TestEqual("named pickup first", Named[0], Host + TEXT("/Recorded/VO_Station_STN_INTRO_02__hayaa.VO_Station_STN_INTRO_02__hayaa"));
        TestEqual("plain take last", Named[3], Host + TEXT("/VO_Station_STN_INTRO_02.VO_Station_STN_INTRO_02"));
    }
    TestEqual("song path", FSaskartaStationLogic::SongAssetPath(TEXT("/Game/SaskartaGaea/Audio/Station/Songs"), TEXT("hayaa")),
        FString(TEXT("/Game/SaskartaGaea/Audio/Station/Songs/SONG_hayaa.SONG_hayaa")));

    const TSet<FName> Tts = FSaskartaStationLogic::ParseTtsManifest(FString(R"json([{"id": "STN_ID_01", "source": "elevenlabs_tts"}, {"id": "IDLE_EARLY_04"}])json"));
    TestEqual("manifest ids", Tts.Num(), 2);
    using S = FSaskartaStationLogic::ETakeSource;
    TestTrue("listed = TTS", FSaskartaStationLogic::ClassifyTake(TEXT("STN_ID_01"), Tts, true, false) == S::Tts);
    TestTrue("raw take = the user's", FSaskartaStationLogic::ClassifyTake(TEXT("STN_ID_01"), Tts, true, true) == S::User);
    TestTrue("unlisted selected = the user's", FSaskartaStationLogic::ClassifyTake(TEXT("STN_ID_02"), Tts, true, false) == S::User);
    TestTrue("nothing = missing", FSaskartaStationLogic::ClassifyTake(TEXT("STN_ID_03"), Tts, false, false) == S::Missing);

    const TMap<FString, FString> CV = USaskartaStorySettings::ComputeCVars(false, 1.7f, true);
    TestEqual("radio mirror", CV.FindRef(TEXT("saskarta.radio")), FString(TEXT("0")));
    TestEqual("volume mirror clamped", CV.FindRef(TEXT("saskarta.volume.station")), FString(TEXT("1.000")));
    TestEqual("saskartan mirror", CV.FindRef(TEXT("saskarta.subtitles.saskartan")), FString(TEXT("1")));
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaStationRealDataTest, "Saskarta.Station.RealData", SASKARTA_STATION_TEST_FLAGS)
bool FSaskartaStationRealDataTest::RunTest(const FString&)
{
    FString Json;
    if (!FFileHelper::LoadFileToString(Json, *FPaths::Combine(FPaths::ProjectDir(), TEXT("docs/story/station.json"))))
    {
        AddWarning(TEXT("docs/story/station.json not found; skipped"));
        return true;
    }
    TMap<FName, FString> Sidecars;
    Sidecars.Add(TEXT("hayaa"), FString(R"({"title": "Hayaa", "singer": ""})"));
    FSaskartaStationConfig C;
    FString Err;
    if (!TestTrue("parses", USaskartaStationImport::ParseStationJson(Json, Sidecars, C, Err)))
    {
        return false;
    }
    TestTrue("the 61 station segments and the show lines", C.Segments.Num() >= 61); // 385 with the live show (RADIOSHOW)
    TestEqual("6 weighted categories", C.CategoryWeights.Num(), 6);
    TestEqual("ID every 4th", C.IdEveryNthSegment, 4);
    TestTrue("hayaa listed", C.Songs.Num() >= 1 && C.Songs[0].Id == FName(TEXT("hayaa")) && C.Songs[0].Title == TEXT("Hayaa"));
    TestEqual("host folder", C.HostFolder, FString(TEXT("/Game/SaskartaGaea/Audio/Station/Host")));
    TestEqual("the boot handover is the station start event", C.StartEvent, FName(TEXT("B01_BOOT_HANDOVER")));
    TestFalse("road zero does not start the station during boot", FSaskartaStationLogic::MayStartAtRoad(C, TEXT("Playing"), 0.f));
    TestFalse("road progress does not bypass the boot handover", FSaskartaStationLogic::MayStartAtRoad(C, TEXT("Playing"), 149.f));
    TestTrue("reception curve", C.QualityByRoadM.Num() >= 2);
    TestTrue("static bed path", C.StaticBed.ToString().EndsWith(TEXT("SFX_Radio_Static_Bed_Loop.SFX_Radio_Static_Bed_Loop")));
    const FSaskartaStationSegment* NameRoll = C.Segments.FindByPredicate([](const FSaskartaStationSegment& S)
    {
        return S.Id == FName(TEXT("SHOW_A3_03"));
    });
    if (TestNotNull("name roll imported", NameRoll))
    {
        TestEqual("name roll caption pages", NameRoll->CaptionPages.Num(), 5);
        TestTrue("name roll pages match its spoken text", FSaskartaCaptionPaging::PagesSpell(NameRoll->CaptionPages, NameRoll->Text));
        if (NameRoll->CaptionPages.Num() >= 2)
        {
            TestEqual("name roll second page timed", NameRoll->CaptionPages[1].StartS, 5.82f, 0.01f);
        }
    }
    // Every template with no values reads exactly the plain text (STATION.md section 4).
    for (const FSaskartaStationSegment& S : C.Segments)
    {
        if (!S.Template.IsEmpty())
        {
            TestEqual(*S.Id.ToString(), FSaskartaStationLogic::FillTemplate(S.Template, S.Text, {}), S.Text);
        }
    }
    TArray<FString> Log;
    const FSaskartaStationDryRunStats Stats = SaskartaStationDryRun(C, 1200.f, 1, { TEXT("hayaa") }, 85.f, &Log);
    for (const FString& L : Log)
    {
        AddInfo(L);
    }
    TestEqual("ID slots", Stats.IdSlotViolations, 0);
    TestEqual("no repeats", Stats.SameCategoryRepeats, 0);
    return true;
}

// ---------------------------------------------------------------------------- CPPBATCH: zones, fragments, story lines, imperfections

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaStationZonesTest, "Saskarta.Station.ZonesAndFragments", SASKARTA_STATION_TEST_FLAGS)
bool FSaskartaStationZonesTest::RunTest(const FString&)
{
    TArray<FSaskartaStationZone> Zones;
    auto Zone = [](const TCHAR* Name, const TCHAR* Label, float From, float To)
    {
        FSaskartaStationZone Z;
        Z.Name = FName(Name);
        Z.Label = Label;
        Z.FromRoadM = From;
        Z.ToRoadM = To;
        return Z;
    };
    Zones.Add(Zone(TEXT("Valley"), TEXT("The valley"), 0.f, 1550.f));
    Zones.Add(Zone(TEXT("Ridge"), TEXT("The ridge"), 1550.f, 2020.f));
    TestEqual("in the valley", FSaskartaStationLogic::ZoneAt(Zones, 10.f), FName(TEXT("Valley")));
    TestEqual("edge belongs to the next", FSaskartaStationLogic::ZoneAt(Zones, 1550.f), FName(TEXT("Ridge")));
    TestEqual("past the last", FSaskartaStationLogic::ZoneAt(Zones, 5000.f), FName());

    FSaskartaStationSegment ZoneSeg = SaskartaStationTest::Seg(TEXT("STN_ZONE_VALLEY_01"), TEXT("ZONE"));
    ZoneSeg.Zone = TEXT("VALLEY");
    TestEqual("zone bag", FSaskartaStationLogic::BagKeyFor(ZoneSeg), FName(TEXT("ZONE_VALLEY")));
    TestEqual("plain bag", FSaskartaStationLogic::BagKeyFor(SaskartaStationTest::Seg(TEXT("STN_TALK_01"), TEXT("TALK"))), FName(TEXT("TALK")));

    TMap<FName, FString> Labels;
    Labels.Add(TEXT("KITCHEN"), TEXT("The kitchen"));
    TestEqual("label", FSaskartaStationLogic::CategoryLabel(Labels, TEXT("KITCHEN")), FString(TEXT("The kitchen")));
    TestEqual("title case fallback", FSaskartaStationLogic::CategoryLabel(Labels, TEXT("WEATHER")), FString(TEXT("Weather")));

    TestEqual("no fade at q 0.25", FSaskartaStationLogic::BelowQuarterDb(0.25f, -40.f), 0.f);
    TestEqual("no fade above", FSaskartaStationLogic::BelowQuarterDb(0.8f, -40.f), 0.f);
    TestEqual("half way down", FSaskartaStationLogic::BelowQuarterDb(0.125f, -40.f), -20.f, 1e-4f);
    TestEqual("gone at q 0", FSaskartaStationLogic::BelowQuarterDb(0.f, -40.f), -40.f);
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaStationStoryLinesTest, "Saskarta.Station.StoryLines", SASKARTA_STATION_TEST_FLAGS)
bool FSaskartaStationStoryLinesTest::RunTest(const FString&)
{
    using K = ESaskartaRadioLineKind;
    // Classification.
    TestTrue("RADIO_* is archive", FSaskartaRadioFxLogic::ClassifyLine(TEXT("RADIO_B03_01"), false, 3) == K::Archive);
    TestTrue("story priority is archive", FSaskartaRadioFxLogic::ClassifyLine(TEXT("LINE_X"), false, 2) == K::Archive);
    TestTrue("critical is archive", FSaskartaRadioFxLogic::ClassifyLine(TEXT("LINE_X"), false, 0) == K::Archive);
    TestTrue("hint, not RADIO_: other", FSaskartaRadioFxLogic::ClassifyLine(TEXT("LINE_X"), false, 3) == K::None);
    TestTrue("CV_* is carrier", FSaskartaRadioFxLogic::ClassifyLine(TEXT("CV_ROUTE_01"), false, 2) == K::Carrier);
    TestTrue("bCarrier is carrier", FSaskartaRadioFxLogic::ClassifyLine(TEXT("RADIO_X"), true, 2) == K::Carrier);

    // Archive line over a playing segment, radio off or on: forced on, cut, released line + 1.5 s, new segment.
    {
        FSaskartaRadioStoryState S;
        const FSaskartaRadioStoryStep A = S.OnLineStart(K::Archive, TEXT("B03"), true, false, 0.f, 100.0, 6.f);
        TestTrue("forced on", A.bForcedOn && S.bForced && S.ForcedBeat == FName(TEXT("B03")));
        TestTrue("cut, not ducked", A.bInterrupt && !A.bDuck);
        TestFalse("no release during the line", S.Tick(105.0).bForcedOff);
        const FSaskartaRadioStoryStep E = S.OnLineEnd(106.0);
        TestFalse("no resume at the line end itself", E.bResume || E.bForcedOff);
        TestFalse("held 1.5 s after the line", S.Tick(107.4).bForcedOff);
        const FSaskartaRadioStoryStep R = S.Tick(107.5);
        TestTrue("released after line + 1.5 s", R.bForcedOff && !S.bForced);
        TestTrue("a new segment, not a song", R.bResume && !R.bResumeSong);
        TestFalse("released once", S.Tick(120.0).bForcedOff);
    }
    // Archive line over a song: the song resumes from its position.
    {
        FSaskartaRadioStoryState S;
        const FSaskartaRadioStoryStep A = S.OnLineStart(K::Archive, TEXT("B08"), true, true, 42.5f, 10.0, 4.f);
        TestTrue("cut the song", A.bInterrupt && S.bSongInterrupted);
        TestEqual("song position kept", S.SongPositionS, 42.5f);
        S.OnLineEnd(14.0);
        const FSaskartaRadioStoryStep R = S.Tick(15.5);
        TestTrue("song resumes", R.bForcedOff && R.bResume && R.bResumeSong);
    }
    // Archive line while the station is silent (the player's radio off): forced on, nothing to cut.
    {
        FSaskartaRadioStoryState S;
        const FSaskartaRadioStoryStep A = S.OnLineStart(K::Archive, TEXT("B02"), false, false, 0.f, 0.0, 3.f);
        TestTrue("forced on with the radio off", A.bForcedOn && !A.bInterrupt);
        S.OnLineEnd(3.0);
        const FSaskartaRadioStoryStep R = S.Tick(4.5);
        TestTrue("released; the programme may go on (the station decides by the player's choice)", R.bForcedOff && R.bResume && !R.bResumeSong);
    }
    // Two archive lines back to back: one force, extended.
    {
        FSaskartaRadioStoryState S;
        TestTrue("first forces", S.OnLineStart(K::Archive, TEXT("B10"), true, false, 0.f, 0.0, 3.f).bForcedOn);
        S.OnLineEnd(3.0);
        const FSaskartaRadioStoryStep B = S.OnLineStart(K::Archive, TEXT("B10"), false, false, 0.f, 3.8, 4.f);
        TestTrue("second does not re-fire or re-cut", !B.bForcedOn && !B.bInterrupt);
        TestFalse("still held at 5 s", S.Tick(5.0).bForcedOff);
        S.OnLineEnd(7.8);
        TestFalse("held until 9.3", S.Tick(9.2).bForcedOff);
        TestTrue("released at 9.3", S.Tick(9.3).bForcedOff);
    }
    // Carrier line: duck only, never forced, unduck at the end.
    {
        FSaskartaRadioStoryState S;
        const FSaskartaRadioStoryStep A = S.OnLineStart(K::Carrier, TEXT("B06"), true, false, 0.f, 0.0, 2.f);
        TestTrue("duck", A.bDuck && !A.bInterrupt && !A.bForcedOn && !S.bForced);
        const FSaskartaRadioStoryStep E = S.OnLineEnd(2.0);
        TestTrue("unduck, no resume needed", E.bUnduck && !E.bResume);
        TestFalse("nothing to release", S.Tick(10.0).bForcedOff);
        TestFalse("carrier over a silent station: no duck", S.OnLineStart(K::Carrier, NAME_None, false, false, 0.f, 20.0, 2.f).bDuck);
    }
    // An end that never comes: the force is dropped StaleLineS after the announced release.
    {
        FSaskartaRadioStoryState S;
        S.OnLineStart(K::Archive, TEXT("B11"), false, false, 0.f, 0.0, 5.f);
        TestFalse("held while the line is supposedly on", S.Tick(30.0).bForcedOff);
        TestTrue("dropped when stale", S.Tick(6.5 + FSaskartaRadioFxLogic::StaleLineS).bForcedOff);
    }
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaStationGlitchTest, "Saskarta.Station.Glitches", SASKARTA_STATION_TEST_FLAGS)
bool FSaskartaStationGlitchTest::RunTest(const FString&)
{
    const FSaskartaRadioGlitchParams P;
    // Rate scaling: about one per 60-90 s at a strong signal, near-constant at none, monotonic.
    const float Strong = FSaskartaRadioFxLogic::MeanIntervalS(P, 1.f, 0.f, false);
    const float Weak = FSaskartaRadioFxLogic::MeanIntervalS(P, 0.f, 0.f, false);
    TestTrue("strong signal: 60-90 s", Strong >= 60.f && Strong <= 90.f);
    TestTrue("no signal: under 2 s", Weak <= 2.f);
    float Prev = Weak;
    for (float Q = 0.1f; Q <= 1.001f; Q += 0.1f)
    {
        const float M = FSaskartaRadioFxLogic::MeanIntervalS(P, Q, 0.f, false);
        TestTrue(*FString::Printf(TEXT("monotonic at q %.1f"), Q), M >= Prev);
        Prev = M;
    }
    TestTrue("a storm makes it worse", FSaskartaRadioFxLogic::MeanIntervalS(P, 1.f, 1.f, false) < Strong);
    TestEqual("storm eats 40 % of the signal", FSaskartaRadioFxLogic::EffectiveSignal(P, 1.f, 1.f), 0.6f, 1e-5f);

    // The Poisson schedule's mean matches.
    FRandomStream Rand(7);
    double Sum = 0.0;
    const int32 N = 4000;
    for (int32 i = 0; i < N; ++i)
    {
        Sum += FSaskartaRadioFxLogic::NextGlitchAtS(P, 1.f, 0.f, false, 0.0, Rand);
    }
    TestTrue("sampled mean near 75 s", FMath::Abs(Sum / N - Strong) < Strong * 0.1);

    // Immunity: during an archive line only light crackle, never a dropout.
    for (int32 i = 0; i < 500; ++i)
    {
        const FSaskartaRadioGlitchEvent E = FSaskartaRadioFxLogic::DrawGlitch(P, 0.f, 1.f, true, Rand);
        if (E.Type != ESaskartaRadioGlitch::Crackle || E.Intensity > P.ArchiveCrackleIntensity + 1e-4f || E.PitchOffset != 0.f)
        {
            AddError(FString::Printf(TEXT("archive line got glitch %d (intensity %.2f)"), static_cast<int32>(E.Type), E.Intensity));
            break;
        }
    }
    TestTrue("archive lines: crackle rarer", FSaskartaRadioFxLogic::MeanIntervalS(P, 0.5f, 0.f, true) > FSaskartaRadioFxLogic::MeanIntervalS(P, 0.5f, 0.f, false));
    TestTrue("only crackle is allowed on archive", FSaskartaRadioFxLogic::AllowedDuringArchive(ESaskartaRadioGlitch::Crackle)
        && !FSaskartaRadioFxLogic::AllowedDuringArchive(ESaskartaRadioGlitch::Dropout));

    // The mix: weak signal is mostly dropouts / bursts / drift and has squeals; strong has no squeals.
    int32 CountWeak[6] = {};
    int32 CountStrong[6] = {};
    for (int32 i = 0; i < 6000; ++i)
    {
        const FSaskartaRadioGlitchEvent W = FSaskartaRadioFxLogic::DrawGlitch(P, 0.f, 0.f, false, Rand);
        const FSaskartaRadioGlitchEvent S = FSaskartaRadioFxLogic::DrawGlitch(P, 1.f, 0.f, false, Rand);
        ++CountWeak[static_cast<int32>(W.Type)];
        ++CountStrong[static_cast<int32>(S.Type)];
        if (W.Type == ESaskartaRadioGlitch::PitchJitter && FMath::Abs(W.PitchOffset) > P.PitchJitter + 1e-6f)
        {
            AddError(TEXT("pitch jitter over +-0.5 %"));
        }
        if (W.Type == ESaskartaRadioGlitch::Drift && (W.DurationS < P.DriftSecondsRange.X - 1e-4f || W.DurationS > P.DriftSecondsRange.Y + 1e-4f))
        {
            AddError(TEXT("drift outside 1-3 s"));
        }
    }
    const int32 Dropout = static_cast<int32>(ESaskartaRadioGlitch::Dropout);
    const int32 Squeal = static_cast<int32>(ESaskartaRadioGlitch::Squeal);
    TestTrue("weak signal drops out more", CountWeak[Dropout] > 3 * CountStrong[Dropout]);
    TestTrue("squeals are rare but happen when weak", CountWeak[Squeal] > 0 && CountWeak[Squeal] < 6000 / 10);
    TestEqual("no squeal at a strong signal", CountStrong[Squeal], 0);
    return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS
