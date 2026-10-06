// Automation tests for the story prompts and the ending chain (SaskartaPromptLogic.h): the reminder clock,
// the key edge, the CRT and overlay lines, the data-layer reference by asset, the cues a sequence-less
// cinematic still runs, and the real story data's chain from B18's latch prompt to the end card.
// Written offline (packaged playtest 2026-09-29: the latch prompt sat under the collapse's black). Run:
//   Automation RunTests Saskarta.Prompt

#include "Misc/AutomationTest.h"

#if WITH_DEV_AUTOMATION_TESTS

#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "SaskartaEventTypes.h"
#include "SaskartaPromptLogic.h"
#include "SaskartaStoryImport.h"

#define SASKARTA_PROMPT_TEST_FLAGS (EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaPromptRemindTest, "Saskarta.Prompt.Remind", SASKARTA_PROMPT_TEST_FLAGS)
bool FSaskartaPromptRemindTest::RunTest(const FString&)
{
    using L = FSaskartaPromptLogic;
    TestFalse(TEXT("not at once"), L::ShouldRemind(0.0, -1.0));
    TestFalse(TEXT("not before FirstRemindS"), L::ShouldRemind(L::FirstRemindS - 0.01, -1.0));
    TestTrue(TEXT("first reminder"), L::ShouldRemind(L::FirstRemindS, -1.0));
    TestFalse(TEXT("not again right after"), L::ShouldRemind(L::FirstRemindS + 1.0, 1.0));
    TestTrue(TEXT("again after RemindEveryS"), L::ShouldRemind(L::FirstRemindS + L::RemindEveryS, L::RemindEveryS));
    // Simulate a 60 s dead screen at the 0.01 s poll: reminders at 10, 30, 50 s.
    int32 Count = 0;
    double Last = -1.0;
    for (double T = 0.0; T <= 60.0; T += 0.01)
    {
        if (L::ShouldRemind(T, Last < 0.0 ? -1.0 : T - Last))
        {
            Last = T;
            ++Count;
        }
    }
    TestEqual(TEXT("three reminders in a minute"), Count, 3);
    TestTrue(TEXT("overlay above the boot log (100 + 10) and below the pause menu (300 + 10)"), L::OverlayZOrder > 110 && L::OverlayZOrder < 310);
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaPromptKeysTest, "Saskarta.Prompt.KeysAndLines", SASKARTA_PROMPT_TEST_FLAGS)
bool FSaskartaPromptKeysTest::RunTest(const FString&)
{
    using L = FSaskartaPromptLogic;
    TestTrue(TEXT("press"), L::IsPressEdge(true, false));
    TestFalse(TEXT("held from before the prompt"), L::IsPressEdge(true, true));
    TestFalse(TEXT("up"), L::IsPressEdge(false, false));
    TestFalse(TEXT("release"), L::IsPressEdge(false, true));
    TestEqual(TEXT("CRT line"), L::CrtLine(TEXT("Release the inner latch.")), FString(TEXT("RELEASE THE INNER LATCH  -  PRESS E / A")));
    TestEqual(TEXT("CRT Rise."), L::CrtLine(TEXT(" Rise. ")), FString(TEXT("RISE  -  PRESS E / A")));
    TestEqual(TEXT("CRT empty"), L::CrtLine(TEXT("")), FString(TEXT("PRESS E / A")));
    TestTrue(TEXT("overlay keeps the words"), L::OverlayLine(TEXT("Lay your hand on the mark.")).StartsWith(TEXT("Lay your hand on the mark.")));
    TestTrue(TEXT("overlay names the keys"), L::OverlayLine(TEXT("Rise.")).Contains(TEXT("[E]")));
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaPromptDataLayerTest, "Saskarta.Prompt.DataLayerRef", SASKARTA_PROMPT_TEST_FLAGS)
bool FSaskartaPromptDataLayerTest::RunTest(const FString&)
{
    using L = FSaskartaPromptLogic;
    FString Ref;
    TestTrue(TEXT("DL: parses"), L::ParseDataLayerRef(TEXT("DL:DL_Ending"), Ref) && Ref == TEXT("DL_Ending"));
    TestTrue(TEXT("DL: path parses"), L::ParseDataLayerRef(TEXT("DL:/Game/Story/DL_Ending.DL_Ending"), Ref) && Ref == TEXT("/Game/Story/DL_Ending.DL_Ending"));
    TestFalse(TEXT("a tag reveal is not a layer"), L::ParseDataLayerRef(TEXT("HutLamp"), Ref));
    TestFalse(TEXT("empty layer"), L::ParseDataLayerRef(TEXT("DL:"), Ref));
    const FString Path = TEXT("/Game/Story/DL_Ending.DL_Ending");
    TestTrue(TEXT("by asset name"), L::DataLayerAssetMatches(TEXT("DL_Ending"), TEXT("DL_Ending"), Path));
    TestTrue(TEXT("by name, any case"), L::DataLayerAssetMatches(TEXT("dl_ending"), TEXT("DL_Ending"), Path));
    TestTrue(TEXT("by object path"), L::DataLayerAssetMatches(Path, TEXT("DL_Ending"), Path));
    TestTrue(TEXT("by package path"), L::DataLayerAssetMatches(TEXT("/Game/Story/DL_Ending"), TEXT("DL_Ending"), Path));
    TestFalse(TEXT("not a suffix match"), L::DataLayerAssetMatches(TEXT("Ending"), TEXT("DL_Ending"), Path));
    TestFalse(TEXT("another layer"), L::DataLayerAssetMatches(TEXT("DL_Ending"), TEXT("DL_EndingOld"), TEXT("/Game/Story/DL_EndingOld.DL_EndingOld")));
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaPromptChainTest, "Saskarta.Prompt.EndingChain", SASKARTA_PROMPT_TEST_FLAGS)
bool FSaskartaPromptChainTest::RunTest(const FString&)
{
    FSaskartaEventAction Clear;
    Clear.Type = ESaskartaActionType::CallHook;
    Clear.Id = TEXT("Cine_ClearBlack");
    FSaskartaEventAction Show = Clear;
    Show.Id = TEXT("Cine_ShowBlack");
    FSaskartaEventAction Flow;
    Flow.Type = ESaskartaActionType::SetFlowState;
    Flow.Id = TEXT("Human");
    FSaskartaEventAction Rise;
    Rise.Type = ESaskartaActionType::Prompt;
    TestTrue(TEXT("a sequence-less cinematic still clears the black"), FSaskartaPromptLogic::RunsWithoutSequence(Clear));
    TestTrue(TEXT("and sets the flow state"), FSaskartaPromptLogic::RunsWithoutSequence(Flow));
    TestFalse(TEXT("but never shows a black"), FSaskartaPromptLogic::RunsWithoutSequence(Show));
    TestFalse(TEXT("nor waits on a prompt"), FSaskartaPromptLogic::RunsWithoutSequence(Rise));

    FString Json;
    if (!FFileHelper::LoadFileToString(Json, *FPaths::Combine(FPaths::ProjectDir(), TEXT("docs/story/story-events.json"))))
    {
        AddWarning(TEXT("story-events.json not found; chain checks skipped"));
        return true;
    }
    TArray<FSaskartaBeatDef> Beats;
    TArray<FSaskartaCinematicDef> Cines;
    TArray<FSaskartaGlanceDef> Glances;
    FString Error;
    if (!TestTrue(TEXT("story parses"), USaskartaStoryImport::ParseStoryJson(Json, Beats, Cines, Glances, Error)))
    {
        AddError(Error);
        return false;
    }
    auto FindBeat = [&Beats](const TCHAR* Id) { return Beats.FindByPredicate([Id](const FSaskartaBeatDef& B) { return B.Id == FName(Id); }); };
    auto FindCine = [&Cines](FName Id) { return Cines.FindByPredicate([Id](const FSaskartaCinematicDef& C) { return C.Id == Id; }); };

    // Every prompt's next beat exists (a dangling one is a dead screen after the key press).
    for (const FSaskartaBeatDef& B : Beats)
    {
        for (const FSaskartaEventAction& A : B.Actions)
        {
            if (A.Type == ESaskartaActionType::Prompt && !A.NextBeat.IsNone())
            {
                TestNotNull(*FString::Printf(TEXT("%s prompt -> %s exists"), *B.Id.ToString(), *A.NextBeat.ToString()), FindBeat(*A.NextBeat.ToString()));
            }
        }
    }
    // B18: CIN_18 leaves the black up, then the latch prompt leads to B19.
    const FSaskartaBeatDef* B18 = FindBeat(TEXT("B18_COLLAPSE"));
    if (TestNotNull(TEXT("B18"), B18))
    {
        const FSaskartaEventAction* Latch = B18->Actions.FindByPredicate([](const FSaskartaEventAction& A) { return A.Type == ESaskartaActionType::Prompt; });
        TestTrue(TEXT("B18 latch prompt -> B19_REVEAL"), Latch && Latch->NextBeat == FName(TEXT("B19_REVEAL")));
        TestTrue(TEXT("latch prompt has words"), Latch && !Latch->Text.IsEmpty());
    }
    // B19 plays CIN_19, whose first cue clears the black (also without its sequence) and whose end is the Human flow.
    const FSaskartaBeatDef* B19 = FindBeat(TEXT("B19_REVEAL"));
    if (TestNotNull(TEXT("B19"), B19))
    {
        const FSaskartaEventAction* Play = B19->Actions.FindByPredicate([](const FSaskartaEventAction& A) { return A.Type == ESaskartaActionType::PlayCinematic; });
        const FSaskartaCinematicDef* C19 = Play ? FindCine(Play->Id) : nullptr;
        if (TestNotNull(TEXT("B19 plays a defined cinematic"), C19))
        {
            TestTrue(TEXT("CIN_19 clears the black"), C19->Cues.ContainsByPredicate([](const FSaskartaEventAction& A)
                { return FSaskartaPromptLogic::RunsWithoutSequence(A) && A.Type == ESaskartaActionType::CallHook; }));
            TestTrue(TEXT("CIN_19 ends in the Human flow"), C19->FinalState.ContainsByPredicate([](const FSaskartaEventAction& A)
                { return A.Type == ESaskartaActionType::SetFlowState && A.Id == FName(TEXT("Human")); }));
        }
    }
    // The last cinematic returns to the title.
    const FSaskartaCinematicDef* C25 = FindCine(TEXT("CIN_25_END_CARD"));
    if (TestNotNull(TEXT("CIN_25"), C25))
    {
        TestTrue(TEXT("CIN_25 opens the title"), C25->FinalState.ContainsByPredicate([](const FSaskartaEventAction& A)
            { return A.Type == ESaskartaActionType::OpenLevel; }));
    }
    return true;
}

#endif
