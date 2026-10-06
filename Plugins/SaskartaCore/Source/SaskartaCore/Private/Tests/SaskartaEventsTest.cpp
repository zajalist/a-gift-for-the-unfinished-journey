// Automation tests for the story event runner's pure logic (EVENTS.md; task-EVENTS-brief.md 1A.2).
//
// No world: FSaskartaEventLogic and the USaskartaStoryImport parsers only. Written offline
// with the implementation; run after the closed-editor build with
//   Automation RunTests Saskarta.Events
// Saskarta.Events.RealData.* read docs/story/ from the project dir and are skipped
// (with a warning) when those files are absent.

#include "Misc/AutomationTest.h"

#if WITH_DEV_AUTOMATION_TESTS

#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "SaskartaEventLogic.h"
#include "SaskartaStoryImport.h"

#define SASKARTA_EVENTS_TEST_FLAGS (EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)

namespace SaskartaEventsTest
{
    static FSaskartaBeatDef RoadBeat(const TCHAR* Id, float UeM, ESaskartaEventPriority P = ESaskartaEventPriority::Story)
    {
        FSaskartaBeatDef B;
        B.Id = FName(Id);
        B.Trigger.Type = ESaskartaTriggerType::RoadPass;
        B.Trigger.UeDistanceM = UeM;
        B.Priority = P;
        return B;
    }

    static FSaskartaQueuedBeat Queued(const TCHAR* Id, ESaskartaEventPriority P, double T, int32 Seq, float Late = 0.f)
    {
        FSaskartaQueuedBeat Q;
        Q.BeatId = FName(Id);
        Q.Priority = P;
        Q.EnqueueTimeS = T;
        Q.Seq = Seq;
        Q.MaxLatenessS = Late;
        return Q;
    }

    /** Three samples in the shape of road-profile.json (UE m falls as road m rises). */
    static TArray<FVector2f> Pairs()
    {
        return { FVector2f(0.f, 5133.9f), FVector2f(50.f, 5083.8f), FVector2f(5009.2f, 0.f) };
    }
}

// ---------------------------------------------------------------------------- road

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaEventsRoadConversionTest, "Saskarta.Events.RoadConversion", SASKARTA_EVENTS_TEST_FLAGS)
bool FSaskartaEventsRoadConversionTest::RunTest(const FString&)
{
    const TArray<FVector2f> P = SaskartaEventsTest::Pairs();
    TestEqual("dock", FSaskartaEventLogic::RoadMFromUeM(P, 5133.9f), 0.f, 0.01f);
    TestEqual("sample 2", FSaskartaEventLogic::RoadMFromUeM(P, 5083.8f), 50.f, 0.01f);
    TestEqual("midpoint", FSaskartaEventLogic::RoadMFromUeM(P, (5133.9f + 5083.8f) * 0.5f), 25.f, 0.01f);
    TestEqual("clamp before the dock", FSaskartaEventLogic::RoadMFromUeM(P, 6000.f), 0.f, 0.01f);
    TestEqual("clamp past the end", FSaskartaEventLogic::RoadMFromUeM(P, -10.f), 5009.2f, 0.01f);
    TestEqual("inverse", FSaskartaEventLogic::UeMFromRoadM(P, 25.f), (5133.9f + 5083.8f) * 0.5f, 0.01f);
    for (float R = 0.f; R <= 5000.f; R += 250.f)
    {
        const float U = FSaskartaEventLogic::UeMFromRoadM(P, R);
        TestEqual(*FString::Printf(TEXT("round trip %.0f"), R), FSaskartaEventLogic::RoadMFromUeM(P, U), R, 0.05f);
    }
    TestEqual("no pairs", FSaskartaEventLogic::RoadMFromUeM({}, 100.f), -1.f);
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaEventsRoadConversionRealTest, "Saskarta.Events.RealData.RoadProfile", SASKARTA_EVENTS_TEST_FLAGS)
bool FSaskartaEventsRoadConversionRealTest::RunTest(const FString&)
{
    FString Road, Story;
    const FString Dir = FPaths::Combine(FPaths::ProjectDir(), TEXT("docs/story"));
    if (!FFileHelper::LoadFileToString(Road, *FPaths::Combine(Dir, TEXT("road-profile.json")))
        || !FFileHelper::LoadFileToString(Story, *FPaths::Combine(Dir, TEXT("story-events.json"))))
    {
        AddWarning(TEXT("docs/story not found; skipped"));
        return true;
    }
    TArray<FVector2f> Pairs;
    TestTrue("road-profile parses", USaskartaStoryImport::ParseRoadProfile(Road, Pairs));
    TestEqual("102 samples", Pairs.Num(), 102);
    TArray<FSaskartaBeatDef> Beats;
    TArray<FSaskartaCinematicDef> Cines;
    TArray<FSaskartaGlanceDef> Glances;
    FString Err;
    TestTrue("story parses", USaskartaStoryImport::ParseStoryJson(Story, Beats, Cines, Glances, Err));
    for (const FSaskartaCinematicDef& C : Cines)
    {
        if (C.Id == FName(TEXT("CIN_06_ROAD_AHEAD")) || C.Id == FName(TEXT("CIN_04_DUST_FRONT"))
            || C.Id == FName(TEXT("CIN_11_WAYSTATION")))
            TestTrue(*FString::Printf(TEXT("%s preserves station playback"), *C.Id.ToString()), C.bKeepStationPlaying);
        if (C.Id == FName(TEXT("CIN_18_COLLAPSE")) || C.Id == FName(TEXT("CIN_24_TRANSMISSION")))
            TestFalse(*FString::Printf(TEXT("%s retains narrative suspension"), *C.Id.ToString()), C.bKeepStationPlaying);
    }
    // Every beat's documented road m matches its UE m through the profile to within 1 m.
    for (const FSaskartaBeatDef& B : Beats)
    {
        if (B.Trigger.UeDistanceM >= 0.f && B.Trigger.RoadM >= 0.f)
        {
            TestEqual(*B.Id.ToString(), FSaskartaEventLogic::RoadMFromUeM(Pairs, B.Trigger.UeDistanceM), B.Trigger.RoadM, 1.f);
        }
    }
    return true;
}

// POI zone beats (POI_CINEMATICS.md): "volume:<TriggerId>" imports as a Volume trigger.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaEventsVolumeTriggerTest, "Saskarta.Events.Import.VolumeTrigger", SASKARTA_EVENTS_TEST_FLAGS)
bool FSaskartaEventsVolumeTriggerTest::RunTest(const FString&)
{
    const FSaskartaEventTrigger T = USaskartaStoryImport::ParseTriggerString(TEXT("volume:POI_O01"), -1.f, -1.f);
    TestTrue("volume type", T.Type == ESaskartaTriggerType::Volume);
    TestEqual("volume id", T.VolumeId, FName(TEXT("POI_O01")));
    const FSaskartaEventTrigger P = USaskartaStoryImport::ParseTriggerString(TEXT("pass"), 100.f, 5033.9f);
    TestTrue("pass still RoadPass", P.Type == ESaskartaTriggerType::RoadPass);
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaEventsRoadTriggerTest, "Saskarta.Events.RoadTriggers", SASKARTA_EVENTS_TEST_FLAGS)
bool FSaskartaEventsRoadTriggerTest::RunTest(const FString&)
{
    using namespace SaskartaEventsTest;
    TArray<FSaskartaBeatDef> Beats = { RoadBeat(TEXT("B02"), 4983.8f), RoadBeat(TEXT("B03"), 4683.6f), RoadBeat(TEXT("B05"), 3912.3f) };
    FSaskartaBeatDef Human = RoadBeat(TEXT("B20"), 171.1f);
    Human.Trigger.Type = ESaskartaTriggerType::RoadPassHuman;
    Beats.Add(Human);
    TSet<FName> Fired, Tags;

    TArray<FName> Out;
    FSaskartaEventLogic::CollectRoadPasses(Beats, 5133.9f, 5000.f, false, Fired, Tags, Out);
    TestEqual("nothing crossed yet", Out.Num(), 0);

    // Crossing two beats in one poll: both, in road order.
    FSaskartaEventLogic::CollectRoadPasses(Beats, 5000.f, 4600.f, false, Fired, Tags, Out);
    TestEqual("two crossed", Out.Num(), 2);
    if (Out.Num() == 2)
    {
        TestEqual("road order 1", Out[0], FName(TEXT("B02")));
        TestEqual("road order 2", Out[1], FName(TEXT("B03")));
    }
    // The high-water mark never moves back, so reversing and driving on again never re-fires.
    float Mark = 5000.f;
    Mark = FSaskartaEventLogic::UpdateHighWater(Mark, 4600.f);
    Mark = FSaskartaEventLogic::UpdateHighWater(Mark, 4990.f); // reversing past B02
    TestEqual("mark held", Mark, 4600.f);
    Out.Reset();
    FSaskartaEventLogic::CollectRoadPasses(Beats, Mark, FSaskartaEventLogic::UpdateHighWater(Mark, 4650.f), false, Fired, Tags, Out);
    TestEqual("no re-fire after reversing", Out.Num(), 0);

    // Exactly on the beat fires ("drops to or below").
    Out.Reset();
    FSaskartaEventLogic::CollectRoadPasses(Beats, 4000.f, 3912.3f, false, Fired, Tags, Out);
    TestEqual("at the metre", Out.Num(), 1);

    // A fired one-shot is skipped.
    Fired.Add(TEXT("B05"));
    Out.Reset();
    FSaskartaEventLogic::CollectRoadPasses(Beats, 4000.f, 3900.f, false, Fired, Tags, Out);
    TestEqual("fired one-shot skipped", Out.Num(), 0);

    // Human beats only in the human pass.
    Out.Reset();
    FSaskartaEventLogic::CollectRoadPasses(Beats, 200.f, 150.f, false, Fired, Tags, Out);
    TestEqual("carrier pass ignores human beats", Out.Num(), 0);
    FSaskartaEventLogic::CollectRoadPasses(Beats, 200.f, 150.f, true, Fired, Tags, Out);
    TestEqual("human pass", Out.Num(), 1);

    // The next beat ahead (for the station's time-to-next-beat).
    const FSaskartaBeatDef* Next = FSaskartaEventLogic::NextRoadBeat(Beats, 4700.f, false, TSet<FName>(), Tags);
    TestTrue("next beat is B03", Next && Next->Id == FName(TEXT("B03")));
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaEventsTagTest, "Saskarta.Events.TagGating", SASKARTA_EVENTS_TEST_FLAGS)
bool FSaskartaEventsTagTest::RunTest(const FString&)
{
    TSet<FName> Enabled;
    Enabled.Add(TEXT("Drone"));
    TSet<FName> Derived = FSaskartaEventLogic::DeriveTags(Enabled);
    TestTrue("DroneSolo derived", Derived.Contains(TEXT("DroneSolo")));
    Enabled.Add(TEXT("AuxSensors"));
    Derived = FSaskartaEventLogic::DeriveTags(Enabled);
    TestFalse("no DroneSolo with AuxSensors", Derived.Contains(TEXT("DroneSolo")));

    TestTrue("requires met", FSaskartaEventLogic::TagsAllow({ TEXT("Drone"), TEXT("AuxSensors") }, {}, Derived));
    TestFalse("requires unmet", FSaskartaEventLogic::TagsAllow({ TEXT("Exchange") }, {}, Derived));
    TestFalse("excluded", FSaskartaEventLogic::TagsAllow({ TEXT("Drone") }, { TEXT("AuxSensors") }, Derived));
    TestTrue("no tags", FSaskartaEventLogic::TagsAllow({}, {}, TSet<FName>()));

    // Tag-gated road beats are not collected.
    FSaskartaBeatDef B = SaskartaEventsTest::RoadBeat(TEXT("OX1"), 1746.f);
    B.RequiresTags.Add(TEXT("Exchange"));
    TArray<FName> Out;
    FSaskartaEventLogic::CollectRoadPasses({ B }, 1800.f, 1700.f, false, TSet<FName>(), TSet<FName>(), Out);
    TestEqual("gated", Out.Num(), 0);
    TSet<FName> WithExchange;
    WithExchange.Add(TEXT("Exchange"));
    FSaskartaEventLogic::CollectRoadPasses({ B }, 1800.f, 1700.f, false, TSet<FName>(), WithExchange, Out);
    TestEqual("enabled", Out.Num(), 1);
    return true;
}

// ---------------------------------------------------------------------------- queue

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaEventsQueueOrderTest, "Saskarta.Events.QueueOrder", SASKARTA_EVENTS_TEST_FLAGS)
bool FSaskartaEventsQueueOrderTest::RunTest(const FString&)
{
    using namespace SaskartaEventsTest;
    TArray<FSaskartaQueuedBeat> Q;
    Q.Add(Queued(TEXT("HintA"), ESaskartaEventPriority::Hint, 1.0, 0));
    Q.Add(Queued(TEXT("StoryLate"), ESaskartaEventPriority::Story, 5.0, 1));
    Q.Add(Queued(TEXT("StoryEarly"), ESaskartaEventPriority::Story, 2.0, 2));
    Q.Add(Queued(TEXT("Cine"), ESaskartaEventPriority::Cinematic, 9.0, 3));
    Q.Add(Queued(TEXT("Crit"), ESaskartaEventPriority::Critical, 10.0, 4));
    Q.Add(Queued(TEXT("StorySameTime"), ESaskartaEventPriority::Story, 2.0, 5));

    const TArray<FName> Expected = { TEXT("Crit"), TEXT("Cine"), TEXT("StoryEarly"), TEXT("StorySameTime"), TEXT("StoryLate"), TEXT("HintA") };
    for (const FName& Want : Expected)
    {
        const int32 I = FSaskartaEventLogic::PickNextIndex(Q);
        if (!TestTrue("something to pick", I != INDEX_NONE))
        {
            return false;
        }
        TestEqual(*FString::Printf(TEXT("next is %s"), *Want.ToString()), Q[I].BeatId, Want);
        Q.RemoveAt(I);
    }
    TestEqual("empty", FSaskartaEventLogic::PickNextIndex(Q), INDEX_NONE);
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaEventsLatenessTest, "Saskarta.Events.Lateness", SASKARTA_EVENTS_TEST_FLAGS)
bool FSaskartaEventsLatenessTest::RunTest(const FString&)
{
    using namespace SaskartaEventsTest;
    // Effective limits: Hint 4 s, a mid-road story beat 20 s, a cinematic never.
    const FSaskartaBeatDef Road = RoadBeat(TEXT("B09"), 2554.3f);
    TestEqual("road story 20 s", FSaskartaEventLogic::EffectiveMaxLateness(Road), 20.f);
    FSaskartaBeatDef Hint = RoadBeat(TEXT("W01"), -1.f, ESaskartaEventPriority::Hint);
    Hint.Trigger.Type = ESaskartaTriggerType::Flow;
    TestEqual("hint 4 s", FSaskartaEventLogic::EffectiveMaxLateness(Hint), 4.f);
    const FSaskartaBeatDef Cine = RoadBeat(TEXT("B06"), 3146.9f, ESaskartaEventPriority::Cinematic);
    TestEqual("cinematic never", FSaskartaEventLogic::EffectiveMaxLateness(Cine), 0.f);
    FSaskartaBeatDef Explicit = Road;
    Explicit.Trigger.MaxLatenessS = 7.f;
    TestEqual("explicit wins", FSaskartaEventLogic::EffectiveMaxLateness(Explicit), 7.f);

    TArray<FSaskartaQueuedBeat> Q;
    Q.Add(Queued(TEXT("Hint"), ESaskartaEventPriority::Hint, 0.0, 0, 0.f));
    Q.Add(Queued(TEXT("Road"), ESaskartaEventPriority::Story, 0.0, 1, 20.f));
    Q.Add(Queued(TEXT("Cine"), ESaskartaEventPriority::Cinematic, 0.0, 2, 0.f));
    TArray<FSaskartaQueuedBeat> Dropped;
    FSaskartaEventLogic::DropLate(Q, 3.9, &Dropped);
    TestEqual("nothing dropped at 3.9 s", Dropped.Num(), 0);
    FSaskartaEventLogic::DropLate(Q, 4.1, &Dropped);
    TestEqual("hint dropped after 4 s", Dropped.Num(), 1);
    FSaskartaEventLogic::DropLate(Q, 20.5, &Dropped);
    TestEqual("road beat dropped after 20 s", Dropped.Num(), 2);
    FSaskartaEventLogic::DropLate(Q, 1000.0, &Dropped);
    TestEqual("cinematic kept", Q.Num(), 1);
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaEventsPreemptTest, "Saskarta.Events.Preempt", SASKARTA_EVENTS_TEST_FLAGS)
bool FSaskartaEventsPreemptTest::RunTest(const FString&)
{
    using P = ESaskartaEventPriority;
    TestTrue("critical over story", FSaskartaEventLogic::CanPreempt(P::Critical, P::Story, false));
    TestTrue("critical over hint", FSaskartaEventLogic::CanPreempt(P::Critical, P::Hint, false));
    TestFalse("never another critical", FSaskartaEventLogic::CanPreempt(P::Critical, P::Critical, false));
    TestFalse("never a running cinematic", FSaskartaEventLogic::CanPreempt(P::Critical, P::Cinematic, true));
    TestFalse("story never preempts", FSaskartaEventLogic::CanPreempt(P::Story, P::Hint, false));
    TestFalse("cinematic waits", FSaskartaEventLogic::CanPreempt(P::Cinematic, P::Story, false));
    TestEqual("fade 0.3 s", FSaskartaEventLogic::CriticalFadeS, 0.3f);

    FSaskartaEventTrigger T;
    T.bOneShot = false;
    T.CooldownS = 8.f;
    TestTrue("first firing", FSaskartaEventLogic::CooldownAllows(T, -1.0, 0.0));
    TestFalse("inside cooldown", FSaskartaEventLogic::CooldownAllows(T, 10.0, 17.9));
    TestTrue("after cooldown", FSaskartaEventLogic::CooldownAllows(T, 10.0, 18.0));
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaEventsVoiceTest, "Saskarta.Events.VoiceChannel", SASKARTA_EVENTS_TEST_FLAGS)
bool FSaskartaEventsVoiceTest::RunTest(const FString&)
{
    const double Until = FSaskartaEventLogic::VoiceBusyUntilAfterLine(10.0, 5.f, 0.8f);
    TestEqual("line + gap", Until, 15.8, 1.0e-6);
    TestFalse("busy during the line", FSaskartaEventLogic::IsVoiceFree(14.0, Until));
    TestFalse("busy during the gap", FSaskartaEventLogic::IsVoiceFree(15.5, Until));
    TestTrue("free after the gap", FSaskartaEventLogic::IsVoiceFree(15.8, Until));
    TestTrue("lines need voice", FSaskartaEventLogic::NeedsVoice(ESaskartaActionType::PlayRadioLine));
    TestTrue("carrier lines need voice", FSaskartaEventLogic::NeedsVoice(ESaskartaActionType::PlayCarrierLine));
    TestTrue("cinematics wait for voice", FSaskartaEventLogic::NeedsVoice(ESaskartaActionType::PlayCinematic));
    TestFalse("captions do not", FSaskartaEventLogic::NeedsVoice(ESaskartaActionType::ShowCaption));
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaEventsDuckingTest, "Saskarta.Events.DuckingOrder", SASKARTA_EVENTS_TEST_FLAGS)
bool FSaskartaEventsDuckingTest::RunTest(const FString&)
{
    using K = FSaskartaDuckStep::EKind;
    TestTrue("line ducks", FSaskartaEventLogic::StationReaction(true, false) == ESaskartaStationReaction::DuckThenFade);
    TestTrue("cinematic suspends", FSaskartaEventLogic::StationReaction(true, true) == ESaskartaStationReaction::Suspend);
    TestTrue("quiet releases", FSaskartaEventLogic::StationReaction(false, true) == ESaskartaStationReaction::Release);

    const TArray<FSaskartaDuckStep> Line = FSaskartaEventLogic::StationDuckPlan(ESaskartaStationReaction::DuckThenFade);
    if (TestEqual("two steps", Line.Num(), 2))
    {
        TestTrue("duck first", Line[0].Kind == K::Duck);
        TestEqual("-12 dB", Line[0].LevelDb, -12.f);
        TestEqual("over 0.3 s", Line[0].DurationS, 0.3f);
        TestEqual("at once", Line[0].StartS, 0.f);
        TestTrue("then fade", Line[1].Kind == K::FadeOut);
        TestEqual("fade starts when the duck ends", Line[1].StartS, Line[0].StartS + Line[0].DurationS);
        TestEqual("fade 1 s", Line[1].DurationS, 1.f);
    }
    const TArray<FSaskartaDuckStep> Cine = FSaskartaEventLogic::StationDuckPlan(ESaskartaStationReaction::Suspend);
    TestTrue("suspend fades", Cine.Num() == 2 && Cine[0].Kind == K::FadeOut && Cine[1].Kind == K::PauseClock);
    const TArray<FSaskartaDuckStep> Rel = FSaskartaEventLogic::StationDuckPlan(ESaskartaStationReaction::Release);
    TestTrue("resume after 6 s", Rel.Num() == 1 && Rel[0].Kind == K::ResumeGate && FMath::IsNearlyEqual(Rel[0].StartS, 6.f));

    TestFalse("station never replaces story", FSaskartaEventLogic::SubtitleMayReplace(true, true));
    TestTrue("story replaces station", FSaskartaEventLogic::SubtitleMayReplace(false, false));
    TestTrue("story replaces story", FSaskartaEventLogic::SubtitleMayReplace(false, true));
    TestTrue("station when free", FSaskartaEventLogic::SubtitleMayReplace(true, false));
    return true;
}

// ---------------------------------------------------------------------------- cinematics

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaEventsCinematicTest, "Saskarta.Events.CinematicCuesAndSkip", SASKARTA_EVENTS_TEST_FLAGS)
bool FSaskartaEventsCinematicTest::RunTest(const FString&)
{
    FSaskartaCinematicDef C;
    auto Cue = [](float At, ESaskartaActionType T, const TCHAR* Id)
    {
        FSaskartaEventAction A;
        A.AtS = At;
        A.Type = T;
        A.Id = FName(Id);
        return A;
    };
    C.Cues.Add(Cue(0.f, ESaskartaActionType::SetLook, TEXT("Valley")));
    C.Cues.Add(Cue(4.5f, ESaskartaActionType::PlayCarrierLine, TEXT("CV_DIRECTIVE_01")));
    FSaskartaEventAction Rise = Cue(13.4f, ESaskartaActionType::Prompt, TEXT(""));
    Rise.bPausesSequence = true;
    C.Cues.Add(Rise);
    FSaskartaEventAction After = Cue(13.4f, ESaskartaActionType::PlaySfx, TEXT("BREATH_02"));
    After.bAfterPrompt = true;
    C.Cues.Add(After);
    FSaskartaEventAction Keep = Cue(40.f, ESaskartaActionType::PlayCarrierLine, TEXT("CV_HANDOFF_01"));
    Keep.bKeepOnSkip = true;
    C.Cues.Add(Keep);

    int32 Next = 0;
    TArray<int32> Due;
    FSaskartaEventLogic::CollectDueCues(C, 5.f, true, Next, Due);
    TestEqual("two cues by 5 s", Due.Num(), 2);
    Due.Reset();
    FSaskartaEventLogic::CollectDueCues(C, 14.f, false, Next, Due);
    TestEqual("the prompt stops the step", Due.Num(), 1);
    Due.Reset();
    FSaskartaEventLogic::CollectDueCues(C, 14.f, false, Next, Due);
    TestEqual("after_prompt waits for the key", Due.Num(), 0);
    FSaskartaEventLogic::CollectDueCues(C, 14.f, true, Next, Due);
    TestEqual("after the key", Due.Num(), 1);

    // Skip at 20 s: the not-yet-started keep_on_skip line still plays after the blend.
    TArray<FName> KeepLines;
    FSaskartaEventLogic::CollectKeepOnSkip(C, Next, KeepLines);
    TestTrue("CV_HANDOFF_01 kept on skip", KeepLines.Num() == 1 && KeepLines[0] == FName(TEXT("CV_HANDOFF_01")));

    TestFalse("HoldAfterSeen, first time", FSaskartaEventLogic::CanSkip(ESaskartaSkipRule::HoldAfterSeen, false, 5.f, 1.f, false));
    TestTrue("HoldAfterSeen, seen", FSaskartaEventLogic::CanSkip(ESaskartaSkipRule::HoldAfterSeen, true, 5.f, 1.f, false));
    TestFalse("before SkipMinS", FSaskartaEventLogic::CanSkip(ESaskartaSkipRule::HoldAlways, true, 0.5f, 1.f, false));
    TestFalse("Never", FSaskartaEventLogic::CanSkip(ESaskartaSkipRule::Never, true, 5.f, 1.f, false));
    TestTrue("AllowSkipAll", FSaskartaEventLogic::CanSkip(ESaskartaSkipRule::Never, false, 5.f, 1.f, true));

    TestTrue("auto letterbox", FSaskartaEventLogic::AutoLetterbox(C));
    C.Cues.Add(Cue(3.f, ESaskartaActionType::ShowLetterbox, TEXT("")));
    TestFalse("explicit letterbox cue", FSaskartaEventLogic::AutoLetterbox(C));
    return true;
}

// ---------------------------------------------------------------------------- save

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaEventsCheckpointTest, "Saskarta.Events.Checkpoint", SASKARTA_EVENTS_TEST_FLAGS)
bool FSaskartaEventsCheckpointTest::RunTest(const FString&)
{
    using namespace SaskartaEventsTest;
    TArray<FSaskartaBeatDef> Beats = { RoadBeat(TEXT("B02"), 4983.8f), RoadBeat(TEXT("B06"), 3146.9f), RoadBeat(TEXT("B07"), 2969.9f) };
    FSaskartaBeatDef B01;
    B01.Id = TEXT("B01");
    B01.Trigger.Type = ESaskartaTriggerType::Flow;
    B01.Trigger.UeDistanceM = 5133.9f;
    Beats.Add(B01);
    FSaskartaBeatDef W01;
    W01.Id = TEXT("W01");
    W01.bSystem = true;
    W01.Trigger.bOneShot = false;
    Beats.Add(W01);
    FSaskartaEventAction Look;
    Look.Type = ESaskartaActionType::SpawnOrReveal;
    Look.Id = TEXT("DL:DL_Ending");
    Look.bReapplyOnLoad = true;
    Beats[1].Actions.Add(Look);

    TestEqual("CP1 road m", FSaskartaEventLogic::CheckpointRoadM(TEXT("CP1_CREST")), 1990.f);
    TestEqual("CP4 is off the road", FSaskartaEventLogic::CheckpointRoadM(TEXT("CP4_HUMAN")), -1.f);

    TSet<FName> Fired;
    FSaskartaEventLogic::MarkFiredUpTo(Beats, 3140.f, Fired);
    TestTrue("B01 fired", Fired.Contains(TEXT("B01")));
    TestTrue("B02 fired", Fired.Contains(TEXT("B02")));
    TestTrue("B06 fired", Fired.Contains(TEXT("B06")));
    TestFalse("B07 ahead", Fired.Contains(TEXT("B07")));
    TestFalse("system beats never", Fired.Contains(TEXT("W01")));

    TArray<FSaskartaEventAction> Reapply;
    FSaskartaEventLogic::CollectReapplyActions(Beats, Fired, Reapply);
    TestTrue("reapply the data layer", Reapply.Num() == 1 && Reapply[0].Id == FName(TEXT("DL:DL_Ending")));
    return true;
}

// ---------------------------------------------------------------------------- import

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaEventsImportTest, "Saskarta.Events.Import", SASKARTA_EVENTS_TEST_FLAGS)
bool FSaskartaEventsImportTest::RunTest(const FString&)
{
    const FString Json = FString(R"json({
        "beats": [
          {"id": "B01_BOOT_HANDOVER", "distance_m": 0, "ue_distance_from_p0_m": 5133.9, "trigger": "flow:first_boot", "one_shot": true,
           "actions": [{"type": "PlayCinematic", "id": "CIN_01_DIRECTIVE"}]},
          {"id": "B09", "distance_m": 2560, "ue_distance_from_p0_m": 2554.3, "trigger": "pass", "one_shot": true,
           "actions": [{"type": "Glance", "id": "G09_PLATFORM", "parallel": true}, {"type": "PlayRadioLine", "id": "RADIO_B09_01"}]},
          {"id": "B18", "distance_m": 4790, "ue_distance_from_p0_m": 221.9, "trigger": "scripted:FlowState=Collapsing; PlayBreach()",
           "actions": [{"type": "PlayCinematic", "id": "CIN_18", "priority": "Critical"},
                       {"type": "Prompt", "text": "Release the inner latch.", "next_beat": "B19"}]},
          {"id": "B20", "distance_m": 4840, "ue_distance_from_p0_m": 171.1, "trigger": "pass:human", "actions": []}
        ],
        "system_beats": [{"id": "W01_WARN", "trigger": "flow:TetherWarning", "one_shot": false, "cooldown_s": 8, "priority": "Hint",
                          "actions": [{"type": "PlayCarrierLine", "id": "CV_WARN_01"}]}],
        "cinematics": {"CIN_01_DIRECTIVE": {"sequence": "/Game/SaskartaGaea/GameFlow/Cinematics/LS_CIN_01_Directive", "duration_s": 42,
            "blend_out_s": 2.0, "skip": "HoldAfterSeen", "stop_pawn": false, "relative_to_pawn": false, "keep_station_playing": true,
            "cues": [{"at_s": 8.5, "type": "PlayCarrierLine", "id": "CV_SCAN_01"}, {"at_s": 4.5, "type": "PlayCarrierLine", "id": "CV_DIRECTIVE_01"}],
            "final_state": [{"type": "CallHook", "id": "EnterPlaying", "target_tag": "PC"}]}},
        "glances": {"G09_PLATFORM": {"target_tag": "Saskarta.Glance.Platform", "ease_in_s": 1.2, "hold_s": 2.0, "lock_move": false}}
    })json");
    TArray<FSaskartaBeatDef> Beats;
    TArray<FSaskartaCinematicDef> Cines;
    TArray<FSaskartaGlanceDef> Glances;
    FString Err;
    if (!TestTrue("parses", USaskartaStoryImport::ParseStoryJson(Json, Beats, Cines, Glances, Err)))
    {
        return false;
    }
    TestEqual("beats + system", Beats.Num(), 5);
    TestTrue("B01 flow", Beats[0].Trigger.Type == ESaskartaTriggerType::Flow && Beats[0].Trigger.FlowEvent == FName(TEXT("FirstBootVisionOnline")));
    TestTrue("B01 cinematic priority", Beats[0].Priority == ESaskartaEventPriority::Cinematic);
    TestTrue("B09 road pass", Beats[1].Trigger.Type == ESaskartaTriggerType::RoadPass);
    TestTrue("B09 story priority", Beats[1].Priority == ESaskartaEventPriority::Story);
    TestTrue("B09 glance parallel", Beats[1].Actions[0].bParallel);
    TestTrue("B18 flow Collapsing", Beats[2].Trigger.Type == ESaskartaTriggerType::Flow && Beats[2].Trigger.FlowEvent == FName(TEXT("Collapsing")));
    TestTrue("B18 critical from the action", Beats[2].Priority == ESaskartaEventPriority::Critical);
    TestEqual("B18 prompt next", Beats[2].Actions[1].NextBeat, FName(TEXT("B19")));
    TestTrue("B20 human", Beats[3].Trigger.Type == ESaskartaTriggerType::RoadPassHuman && Beats[3].Trigger.RequiredFlowState == FName(TEXT("Human")));
    TestTrue("W01 system, repeatable, hint", Beats[4].bSystem && !Beats[4].Trigger.bOneShot && Beats[4].Priority == ESaskartaEventPriority::Hint);
    TestEqual("W01 cooldown", Beats[4].Trigger.CooldownS, 8.f);
    if (TestEqual("one cinematic", Cines.Num(), 1))
    {
        TestEqual("sequence path", Cines[0].Sequence.ToSoftObjectPath().ToString(),
            FString(TEXT("/Game/SaskartaGaea/GameFlow/Cinematics/LS_CIN_01_Directive.LS_CIN_01_Directive")));
        TestEqual("cues sorted", Cines[0].Cues[0].Id, FName(TEXT("CV_DIRECTIVE_01")));
        TestFalse("stop pawn", Cines[0].bStopPawn);
        TestTrue("continuous station policy imports", Cines[0].bKeepStationPlaying);
        TestFalse("unannotated cinematics retain suspension", FSaskartaCinematicDef().bKeepStationPlaying);
        TestEqual("final state", Cines[0].FinalState.Num(), 1);
    }
    TestTrue("glance", Glances.Num() == 1 && Glances[0].TargetTag == FName(TEXT("Saskarta.Glance.Platform")));

    // The TSV: quoted English, Language SKS, the Saskartan text; columns found by header name.
    const FString Tsv = FString(TEXT("#\tID (slate)\tGroup\tSpeaker\tBeat\tEnglish\tDelivery\tTarget\tLanguage\tSaskartan? (flag)\tSaskartan translation\tRecorded?\n"))
        + TEXT("1\tRADIO_B02_01\tStory\tKEEPER\tB02\t\"\"\"Archive of the upper valley.\"\" (beat) \"\"For whoever carries this road.\"\"\"\tArchive\t7 s\tSKS (English = subtitle)\t\tImrigheyilef-de zdaw.\t\n")
        + TEXT("43\tCV_BOOT_01\tCarrier\tCARRIER\tFirst boot\t\"\"\"Contactor closing.\"\"\"\tsystem\t\tEN\t\t\t\n");
    TArray<FSaskartaLineDef> Lines;
    USaskartaStoryImport::ParseLinesTsv(Tsv, Lines);
    if (TestEqual("two lines", Lines.Num(), 2))
    {
        TestEqual("english cleaned", Lines[0].English, FString(TEXT("Archive of the upper valley. For whoever carries this road.")));
        TestTrue("SKS from Language", Lines[0].bSaskartan);
        TestEqual("saskartan text", Lines[0].Saskartan, FString(TEXT("Imrigheyilef-de zdaw.")));
        TestEqual("target", Lines[0].DurationS, 7.f);
        TestTrue("carrier", Lines[1].bCarrier && !Lines[1].bSaskartan);
        TestEqual("carrier style", Lines[1].Style, FName(TEXT("system")));
        TestEqual("sound path", Lines[1].Sound.ToSoftObjectPath().ToString(), FString(TEXT("/Game/SaskartaGaea/Audio/CarrierVoice/VO_Carrier_CV_BOOT_01.VO_Carrier_CV_BOOT_01")));
    }
    USaskartaStoryImport::ApplyDurationsJson(FString(R"json({"RADIO_B02_01": 8.4, "CV_BOOT_01": {"duration_s": 1.9}})json"), Lines);
    TestEqual("recorded duration", Lines[0].DurationS, 8.4f, 0.001f);
    TestEqual("recorded duration object", Lines[1].DurationS, 1.9f, 0.001f);
    TestEqual("re-time text", USaskartaStoryImport::ParseTargetSeconds(TEXT("re-time from the take")), 0.f);
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaEventsDryRunRealTest, "Saskarta.Events.RealData.DryRun", SASKARTA_EVENTS_TEST_FLAGS)
bool FSaskartaEventsDryRunRealTest::RunTest(const FString&)
{
    const FString Dir = FPaths::Combine(FPaths::ProjectDir(), TEXT("docs/story"));
    FString Story, Tsv, Carrier, Road;
    if (!FFileHelper::LoadFileToString(Story, *FPaths::Combine(Dir, TEXT("story-events.json")))
        || !FFileHelper::LoadFileToString(Tsv, *FPaths::Combine(Dir, TEXT("radio-lines-for-translation.tsv")))
        || !FFileHelper::LoadFileToString(Road, *FPaths::Combine(Dir, TEXT("road-profile.json"))))
    {
        AddWarning(TEXT("docs/story not found; skipped"));
        return true;
    }
    TArray<FSaskartaBeatDef> Beats;
    TArray<FSaskartaCinematicDef> Cines;
    TArray<FSaskartaGlanceDef> Glances;
    TArray<FSaskartaLineDef> Lines;
    TArray<FVector2f> Pairs;
    FString Err;
    USaskartaStoryImport::ParseStoryJson(Story, Beats, Cines, Glances, Err);
    USaskartaStoryImport::ParseLinesTsv(Tsv, Lines);
    if (FFileHelper::LoadFileToString(Carrier, *FPaths::Combine(Dir, TEXT("carrier-voice-lines.json"))))
    {
        USaskartaStoryImport::ApplyCarrierLinesJson(Carrier, Lines);
    }
    USaskartaStoryImport::ParseRoadProfile(Road, Pairs);

    // Every line an action names has a TSV row.
    for (const FSaskartaBeatDef& B : Beats)
    {
        for (const FSaskartaEventAction& A : B.Actions)
        {
            if (A.Type == ESaskartaActionType::PlayRadioLine || A.Type == ESaskartaActionType::PlayCarrierLine)
            {
                TestTrue(*FString::Printf(TEXT("%s: %s has a row"), *B.Id.ToString(), *A.Id.ToString()),
                    Lines.ContainsByPredicate([&A](const FSaskartaLineDef& L) { return L.Id == A.Id; }));
            }
        }
    }
    // The Saskartan flags come from the Language column.
    const FSaskartaLineDef* B02 = Lines.FindByPredicate([](const FSaskartaLineDef& L) { return L.Id == FName(TEXT("RADIO_B02_01")); });
    TestTrue("RADIO_B02_01 is SKS with text", B02 && B02->bSaskartan && !B02->Saskartan.IsEmpty());

    TArray<FString> Log;
    const bool bNoOverlap = FSaskartaEventLogic::DryRun(Beats, Lines, Cines, Pairs, TSet<FName>(), 5.f, 4790.f, 0.8f, Log);
    for (const FString& L : Log)
    {
        AddInfo(L);
    }
    TestTrue("no story line overlaps another", bNoOverlap);
    const FString* B15 = Log.FindByPredicate([](const FString& L) { return L.Contains(TEXT("START  B15")); });
    TestNotNull("B15 starts", B15);
    return true;
}

// ---------------------------------------------------------------------------- CPPBATCH (2026-09-28)

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaEventsVoiceEdgeTest, "Saskarta.Events.VoiceChannelEdge", SASKARTA_EVENTS_TEST_FLAGS)
bool FSaskartaEventsVoiceEdgeTest::RunTest(const FString&)
{
    // A float line length widened to double lands a hair past the exact end; 0.1 ms of slack frees it.
    const double Until = FSaskartaEventLogic::VoiceBusyUntilAfterLine(10.0, 5.f, 0.8f);
    TestTrue("free 0.05 ms early (float edge)", FSaskartaEventLogic::IsVoiceFree(Until - 0.5e-4, Until));
    TestFalse("busy 0.2 ms early", FSaskartaEventLogic::IsVoiceFree(Until - 2.0e-4, Until));
    TestTrue("free at 15.8 (the float sum is 15.8000000119)", FSaskartaEventLogic::IsVoiceFree(15.8, Until));
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaEventsNoSequenceTest, "Saskarta.Events.NoSequenceLines", SASKARTA_EVENTS_TEST_FLAGS)
bool FSaskartaEventsNoSequenceTest::RunTest(const FString&)
{
    FSaskartaCinematicDef C;
    C.Id = TEXT("CIN_06");
    auto Cue = [](ESaskartaActionType Type, const TCHAR* Id)
    {
        FSaskartaEventAction A;
        A.Type = Type;
        A.Id = FName(Id);
        return A;
    };
    C.Cues.Add(Cue(ESaskartaActionType::ShowCaption, TEXT("CAP")));
    C.Cues.Add(Cue(ESaskartaActionType::PlayRadioLine, TEXT("RADIO_B06_01")));
    C.Cues.Add(Cue(ESaskartaActionType::PlayCarrierLine, TEXT("CV_ROUTE_01")));
    FSaskartaEventAction Drone = Cue(ESaskartaActionType::PlayRadioLine, TEXT("RADIO_DRONE"));
    Drone.RequiresTags.Add(TEXT("Drone"));
    C.Cues.Add(Drone);
    FSaskartaEventAction First = Cue(ESaskartaActionType::PlayCarrierLine, TEXT("CV_FIRST"));
    First.bFirstPlaythroughOnly = true;
    C.Cues.Add(First);

    TArray<FName> Lines;
    FSaskartaEventLogic::CollectCueLines(C, TSet<FName>(), false, Lines);
    if (TestEqual("lines only, tag-gated (3)", Lines.Num(), 3))
    {
        TestEqual("cue order 1", Lines[0], FName(TEXT("RADIO_B06_01")));
        TestEqual("cue order 2", Lines[1], FName(TEXT("CV_ROUTE_01")));
        TestEqual("first playthrough", Lines[2], FName(TEXT("CV_FIRST")));
    }
    Lines.Reset();
    TSet<FName> Tags;
    Tags.Add(TEXT("Drone"));
    FSaskartaEventLogic::CollectCueLines(C, Tags, true, Lines);
    TestEqual("drone line in, first-playthrough line out", Lines.Num(), 3);
    TestTrue("has the drone line", Lines.Contains(FName(TEXT("RADIO_DRONE"))));
    TestFalse("no first-playthrough line after a completed run", Lines.Contains(FName(TEXT("CV_FIRST"))));
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaEventsWatchdogTest, "Saskarta.Events.CineWatchdog", SASKARTA_EVENTS_TEST_FLAGS)
bool FSaskartaEventsWatchdogTest::RunTest(const FString&)
{
    TestEqual("pad is 5 s", FSaskartaEventLogic::CineWatchdogPadS, 5.f);
    TestFalse("inside the duration", FSaskartaEventLogic::CineWatchdogExpired(16.0, 18.f));
    TestFalse("inside the pad", FSaskartaEventLogic::CineWatchdogExpired(22.9, 18.f));
    TestFalse("exactly duration + pad", FSaskartaEventLogic::CineWatchdogExpired(23.0, 18.f));
    TestTrue("past duration + pad", FSaskartaEventLogic::CineWatchdogExpired(23.1, 18.f));
    TestTrue("a zero budget still gets the pad", !FSaskartaEventLogic::CineWatchdogExpired(4.9, 0.f) && FSaskartaEventLogic::CineWatchdogExpired(5.1, 0.f));
    TestTrue("negative budget clamps to 0", FSaskartaEventLogic::CineWatchdogExpired(5.1, -3.f));
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaEventsRoadCineOriginTest, "Saskarta.Events.RoadCineOrigin", SASKARTA_EVENTS_TEST_FLAGS)
bool FSaskartaEventsRoadCineOriginTest::RunTest(const FString&)
{
    // The carrier has stopped 1 m off the spline and yawed 35 degrees from the road. Camera position follows the
    // carrier, while the authored road-relative rig keeps the spline's travel orientation for scenery shots.
    const FVector OnSpline(318000.f, 444000.f, 10050.f);
    const FVector Carrier(318080.f, 443940.f, 10050.f + 374.f + 60.f);
    const FVector O = FSaskartaEventLogic::RoadCineOrigin(Carrier, 60.f);
    TestEqual("x follows the stopped carrier", O.X, Carrier.X);
    TestEqual("y follows the stopped carrier", O.Y, Carrier.Y);
    TestEqual("z at the carrier's feet", O.Z, OnSpline.Z + 374.f);

    const FRotator CarrierYaw(0.f, 125.f, 0.f);
    const FRotator RoadYaw = FSaskartaEventLogic::RoadCineRotation(FVector(0.f, 1.f, 0.f));
    TestEqual("camera frame stays aligned to the road", RoadYaw.Yaw, 90.0);
    TestTrue("road camera frame does not inherit the carrier's off-road yaw", !FMath::IsNearlyEqual(RoadYaw.Yaw, CarrierYaw.Yaw));
    const FTransform RoadFrame(RoadYaw, O);
    const FVector Eye = RoadFrame.TransformPosition(FVector(0.f, 0.f, 120.f));
    TestEqual("POV eye shares the actual carrier X", Eye.X, Carrier.X);
    TestEqual("POV eye shares the actual carrier Y", Eye.Y, Carrier.Y);
    TestTrue("road-local +X remains up-road", FVector::Dist(RoadFrame.TransformVector(FVector(100.f, 0.f, 0.f)), FVector(0.f, 100.f, 0.f)) < 0.01f);

    // CIN18/19 stage on the spline centre today, so their fixed staged transform is unchanged.
    const FVector CollapseStage(OnSpline.X, OnSpline.Y, OnSpline.Z + 374.f + 60.f);
    const FVector CollapseOrigin = FSaskartaEventLogic::RoadCineOrigin(CollapseStage, 60.f);
    TestEqual("staged CIN18/19 keeps its authored X", CollapseOrigin.X, CollapseStage.X);
    TestEqual("staged CIN18/19 keeps its authored Y", CollapseOrigin.Y, CollapseStage.Y);
    // At 4,607 the landscape is 3.18 m under the spline: the origin goes down with it.
    TestEqual("below the spline too", FSaskartaEventLogic::RoadCineOrigin(FVector(0.0, 0.0, 10050.0 - 318.0 + 92.0), 92.f).Z, 10050.0 - 318.0);
    TestEqual("a negative half height is 0", FSaskartaEventLogic::RoadCineOrigin(Carrier, -5.f).Z, Carrier.Z);
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaEventsCapsuleFrameTest, "Saskarta.Events.CapsuleContactFrame", SASKARTA_EVENTS_TEST_FLAGS)
bool FSaskartaEventsCapsuleFrameTest::RunTest(const FString&)
{
    const FVector ReferencePosition(-356.4797, 0.0, 30.0239);
    const FQuat ReferenceRotation = FRotator(0.0, -90.0, 0.0).Quaternion();
    const FTransform Expected(FRotator(12.3, 74.0, -3.0), FVector(490000.0, 323000.0, -28100.0));
    const FTransform Socket(Expected.GetRotation() * ReferenceRotation,
        Expected.TransformPosition(ReferencePosition), FVector(100.0));
    const FTransform Frame = FSaskartaEventLogic::CinematicSocketFrame(Socket, ReferencePosition, ReferenceRotation);
    TestTrue("contact frame retains slope and roll", Frame.GetRotation().Equals(Expected.GetRotation(), 0.00001));
    TestTrue("reference socket maps to real capsule", Frame.TransformPosition(ReferencePosition).Equals(Socket.GetLocation(), 0.001));
    TestTrue("body origin follows actual capsule", Frame.GetLocation().Equals(Expected.GetLocation(), 0.001));
    TestTrue("imported scale cannot enlarge the traveller", Frame.GetScale3D().Equals(FVector::OneVector));
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaEventsArmTest, "Saskarta.Events.DebugArm", SASKARTA_EVENTS_TEST_FLAGS)
bool FSaskartaEventsArmTest::RunTest(const FString&)
{
    using namespace SaskartaEventsTest;
    TestEqual("30 m before B03 (450)", FSaskartaEventLogic::ArmRoadM(450.f, 30.f), 420.f);
    TestEqual("never before the dock", FSaskartaEventLogic::ArmRoadM(10.f, 30.f), 0.f);
    TestEqual("negative lead is 0", FSaskartaEventLogic::ArmRoadM(450.f, -5.f), 450.f);

    // A road beat at the dock (the B01 case): the carrier stands on it, the mark sits just above it,
    // so the next poll at or past it fires it.
    const TArray<FSaskartaBeatDef> Beats = { RoadBeat(TEXT("B00_DOCK"), 5133.9f), RoadBeat(TEXT("B03"), 4683.9f) };
    const float Mark = FSaskartaEventLogic::ArmHighWaterUeM(5133.9f, 5133.9f);
    TestTrue("mark above the beat", Mark > 5133.9f);
    TArray<FName> Hits;
    FSaskartaEventLogic::CollectRoadPasses(Beats, Mark, 5133.9f, false, TSet<FName>(), TSet<FName>(), Hits);
    TestTrue("fires on the next poll at the dock", Hits.Num() == 1 && Hits[0] == FName(TEXT("B00_DOCK")));

    // Armed 30 m before B03: the mark is the carrier's, the beat fires when reached, not before.
    const float Mark2 = FSaskartaEventLogic::ArmHighWaterUeM(4683.9f, 4713.9f);
    TestEqual("mark at the carrier", Mark2, 4713.9f);
    Hits.Reset();
    FSaskartaEventLogic::CollectRoadPasses(Beats, Mark2, 4690.f, false, TSet<FName>(), TSet<FName>(), Hits);
    TestEqual("not yet", Hits.Num(), 0);
    FSaskartaEventLogic::CollectRoadPasses(Beats, 4690.f, 4680.f, false, TSet<FName>(), TSet<FName>(), Hits);
    TestTrue("fires when reached", Hits.Num() == 1 && Hits[0] == FName(TEXT("B03")));

    // Jumping beyond the handover marks both one-shot beats fired. Arming the failure
    // again must leave its recovery live, or the player remains on the blind feed.
    const TArray<FSaskartaBeatDef> DroneChain = {
        RoadBeat(TEXT("OA1_OPTICS_FAIL"), 1400.f), RoadBeat(TEXT("OB1_DRONE"), 1300.f)
    };
    TSet<FName> Fired = { FName(TEXT("B13")) };
    TMap<FName, double> Last = {
        { FName(TEXT("OA1_OPTICS_FAIL")), 10.0 }, { FName(TEXT("OB1_DRONE")), 20.0 }
    };
    FSaskartaEventLogic::MarkFiredUpTo(DroneChain, 1200.f, Fired);
    TestTrue("jump marks drone recovery fired", Fired.Contains(TEXT("OB1_DRONE")));
    FSaskartaEventLogic::RearmConnectedDebugBeats(TEXT("OA1_OPTICS_FAIL"), Fired, Last);
    TestFalse("optics failure rearmed", Fired.Contains(TEXT("OA1_OPTICS_FAIL")));
    TestFalse("drone recovery rearmed", Fired.Contains(TEXT("OB1_DRONE")));
    TestFalse("recovery cooldown cleared", Last.Contains(TEXT("OB1_DRONE")));
    TestTrue("unrelated later beat retained", Fired.Contains(TEXT("B13")));
    Hits.Reset();
    FSaskartaEventLogic::CollectRoadPasses(DroneChain, 1450.f, 1350.f, false, Fired, TSet<FName>(), Hits);
    TestTrue("failure fires after rearm", Hits.Num() == 1 && Hits[0] == FName(TEXT("OA1_OPTICS_FAIL")));
    Hits.Reset();
    FSaskartaEventLogic::CollectRoadPasses(DroneChain, 1350.f, 1250.f, false, Fired, TSet<FName>(), Hits);
    TestTrue("recovery fires after rearm", Hits.Num() == 1 && Hits[0] == FName(TEXT("OB1_DRONE")));
    return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS
