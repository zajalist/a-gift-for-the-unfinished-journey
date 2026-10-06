// USaskartaStoryImport and USaskartaStoryAsset lookups. See the headers.

#include "SaskartaStoryImport.h"
#include "SaskartaStoryAsset.h"

#include "Dom/JsonObject.h"
#include "Dom/JsonValue.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "Sound/SoundBase.h"
#include "LevelSequence.h"

DEFINE_LOG_CATEGORY_STATIC(LogSaskartaStoryImport, Log, All);

const TCHAR* USaskartaStoryImport::StoryAssetPath = TEXT("/Game/SaskartaGaea/Story/DA_Saskarta_Story.DA_Saskarta_Story");

// ============================================================================ asset lookups

const FSaskartaBeatDef* USaskartaStoryAsset::FindBeat(FName Id) const
{
    return Beats.FindByPredicate([Id](const FSaskartaBeatDef& B) { return B.Id == Id; });
}

const FSaskartaLineDef* USaskartaStoryAsset::FindLine(FName Id) const
{
    return Lines.FindByPredicate([Id](const FSaskartaLineDef& L) { return L.Id == Id; });
}

const FSaskartaCinematicDef* USaskartaStoryAsset::FindCinematic(FName Id) const
{
    return Cinematics.FindByPredicate([Id](const FSaskartaCinematicDef& C) { return C.Id == Id; });
}

const FSaskartaGlanceDef* USaskartaStoryAsset::FindGlance(FName Id) const
{
    return Glances.FindByPredicate([Id](const FSaskartaGlanceDef& G) { return G.Id == Id; });
}

// ============================================================================ helpers

namespace SaskartaStoryImportPrivate
{
    static TSharedPtr<FJsonObject> ParseObject(const FString& Json)
    {
        TSharedPtr<FJsonObject> Obj;
        const TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(Json);
        if (!FJsonSerializer::Deserialize(Reader, Obj))
        {
            return nullptr;
        }
        return Obj;
    }

    static FString GetString(const TSharedPtr<FJsonObject>& O, const TCHAR* Key)
    {
        FString S;
        if (O.IsValid())
        {
            O->TryGetStringField(Key, S);
        }
        return S;
    }

    static float GetNumber(const TSharedPtr<FJsonObject>& O, const TCHAR* Key, float Default)
    {
        double D = 0.0;
        if (O.IsValid() && O->TryGetNumberField(Key, D))
        {
            return static_cast<float>(D);
        }
        return Default;
    }

    static bool GetBool(const TSharedPtr<FJsonObject>& O, const TCHAR* Key, bool Default)
    {
        bool B = Default;
        if (O.IsValid() && O->TryGetBoolField(Key, B))
        {
            return B;
        }
        return Default;
    }

    static TArray<FName> GetNames(const TSharedPtr<FJsonObject>& O, const TCHAR* Key)
    {
        TArray<FName> Out;
        const TArray<TSharedPtr<FJsonValue>>* Arr = nullptr;
        if (O.IsValid() && O->TryGetArrayField(Key, Arr) && Arr)
        {
            for (const TSharedPtr<FJsonValue>& V : *Arr)
            {
                FString S;
                if (V.IsValid() && V->TryGetString(S) && !S.IsEmpty())
                {
                    Out.Add(FName(*S));
                }
            }
        }
        return Out;
    }

    static FSaskartaBeatDef ParseBeat(const TSharedPtr<FJsonObject>& B)
    {
        FSaskartaBeatDef Beat;
        Beat.Id = FName(*GetString(B, TEXT("id")));
        const float UeM = GetNumber(B, TEXT("ue_distance_from_p0_m"), -1.f);
        const float RoadM = GetNumber(B, TEXT("distance_m"), -1.f);
        Beat.Trigger = USaskartaStoryImport::ParseTriggerString(GetString(B, TEXT("trigger")), UeM, RoadM);
        const FString RequiredFlow = GetString(B, TEXT("required_flow_state"));
        if (!RequiredFlow.IsEmpty()) Beat.Trigger.RequiredFlowState = FName(*RequiredFlow);
        Beat.Trigger.bOneShot = GetBool(B, TEXT("one_shot"), true);
        Beat.Trigger.CooldownS = GetNumber(B, TEXT("cooldown_s"), 0.f);
        Beat.Trigger.MaxLatenessS = GetNumber(B, TEXT("max_lateness_s"), Beat.Trigger.MaxLatenessS);
        Beat.RequiresTags = GetNames(B, TEXT("requires_tags"));
        Beat.ExcludesTags = GetNames(B, TEXT("excludes_tags"));

        const TArray<TSharedPtr<FJsonValue>>* Actions = nullptr;
        if (B->TryGetArrayField(TEXT("actions"), Actions) && Actions)
        {
            for (const TSharedPtr<FJsonValue>& V : *Actions)
            {
                const TSharedPtr<FJsonObject>* AO = nullptr;
                if (V.IsValid() && V->TryGetObject(AO) && AO)
                {
                    Beat.Actions.Add(USaskartaStoryImport::ParseAction(*AO));
                }
            }
        }

        ESaskartaEventPriority P;
        if (USaskartaStoryImport::ParsePriority(GetString(B, TEXT("priority")), P))
        {
            Beat.Priority = P;
        }
        else
        {
            // An action-level "priority" (B18, B19, B24) is the beat's.
            bool bFound = false;
            if (Actions)
            {
                for (const TSharedPtr<FJsonValue>& V : *Actions)
                {
                    const TSharedPtr<FJsonObject>* AO = nullptr;
                    if (V.IsValid() && V->TryGetObject(AO) && AO && USaskartaStoryImport::ParsePriority(GetString(*AO, TEXT("priority")), P))
                    {
                        Beat.Priority = P;
                        bFound = true;
                        break;
                    }
                }
            }
            if (!bFound)
            {
                Beat.Priority = USaskartaStoryImport::DerivePriority(Beat);
            }
        }
        return Beat;
    }
}

// ============================================================================ enums

ESaskartaActionType USaskartaStoryImport::ParseActionType(const FString& Name)
{
    static const TMap<FString, ESaskartaActionType> Map = {
        { TEXT("PlayRadioLine"), ESaskartaActionType::PlayRadioLine },
        { TEXT("PlayCarrierLine"), ESaskartaActionType::PlayCarrierLine },
        { TEXT("PlayCinematic"), ESaskartaActionType::PlayCinematic },
        { TEXT("ShowCaption"), ESaskartaActionType::ShowCaption },
        { TEXT("ShowHudQuery"), ESaskartaActionType::ShowHudQuery },
        { TEXT("ShowSubtitle"), ESaskartaActionType::ShowSubtitle },
        { TEXT("SetLook"), ESaskartaActionType::SetLook },
        { TEXT("SetLookKey"), ESaskartaActionType::SetLook },
        { TEXT("SetFog"), ESaskartaActionType::SetFog },
        { TEXT("SpawnOrReveal"), ESaskartaActionType::SpawnOrReveal },
        { TEXT("SetFlowState"), ESaskartaActionType::SetFlowState },
        { TEXT("Wait"), ESaskartaActionType::Wait },
        { TEXT("Prompt"), ESaskartaActionType::Prompt },
        { TEXT("PlaySfx"), ESaskartaActionType::PlaySfx },
        { TEXT("Glance"), ESaskartaActionType::Glance },
        { TEXT("SetInputLock"), ESaskartaActionType::SetInputLock },
        { TEXT("CallHook"), ESaskartaActionType::CallHook },
        { TEXT("Checkpoint"), ESaskartaActionType::Checkpoint },
        { TEXT("SetMode"), ESaskartaActionType::SetMode },
        { TEXT("SetControlRotation"), ESaskartaActionType::SetControlRotation },
        { TEXT("ShowLetterbox"), ESaskartaActionType::ShowLetterbox },
        { TEXT("SetGeiger"), ESaskartaActionType::SetGeiger },
        { TEXT("ShowEndCard"), ESaskartaActionType::ShowEndCard },
        { TEXT("OpenLevel"), ESaskartaActionType::OpenLevel },
        { TEXT("PlayDawn"), ESaskartaActionType::PlayDawn },
        { TEXT("StopSfx"), ESaskartaActionType::StopSfx },
    };
    const ESaskartaActionType* T = Map.Find(Name);
    return T ? *T : ESaskartaActionType::None;
}

bool USaskartaStoryImport::ParsePriority(const FString& Name, ESaskartaEventPriority& Out)
{
    if (Name.Equals(TEXT("Critical"), ESearchCase::IgnoreCase)) { Out = ESaskartaEventPriority::Critical; return true; }
    if (Name.Equals(TEXT("Cinematic"), ESearchCase::IgnoreCase)) { Out = ESaskartaEventPriority::Cinematic; return true; }
    if (Name.Equals(TEXT("Story"), ESearchCase::IgnoreCase)) { Out = ESaskartaEventPriority::Story; return true; }
    if (Name.Equals(TEXT("Hint"), ESearchCase::IgnoreCase)) { Out = ESaskartaEventPriority::Hint; return true; }
    return false;
}

ESaskartaSkipRule USaskartaStoryImport::ParseSkipRule(const FString& Name)
{
    if (Name == TEXT("Never")) return ESaskartaSkipRule::Never;
    if (Name == TEXT("HoldAlways")) return ESaskartaSkipRule::HoldAlways;
    if (Name == TEXT("AnyKeyAfter")) return ESaskartaSkipRule::AnyKeyAfter;
    return ESaskartaSkipRule::HoldAfterSeen;
}

ESaskartaEventPriority USaskartaStoryImport::DerivePriority(const FSaskartaBeatDef& Beat)
{
    for (const FSaskartaEventAction& A : Beat.Actions)
    {
        // The first action that is not a parallel side effect decides.
        if (A.Type == ESaskartaActionType::PlayCinematic)
        {
            return ESaskartaEventPriority::Cinematic;
        }
        if (A.Type == ESaskartaActionType::PlayRadioLine || A.Type == ESaskartaActionType::PlayCarrierLine)
        {
            return ESaskartaEventPriority::Story;
        }
    }
    return ESaskartaEventPriority::Story;
}

// ============================================================================ triggers and actions

FSaskartaEventTrigger USaskartaStoryImport::ParseTriggerString(const FString& Trigger, float UeDistanceM, float RoadM)
{
    FSaskartaEventTrigger T;
    T.UeDistanceM = UeDistanceM;
    T.RoadM = RoadM;
    const FString S = Trigger.TrimStartAndEnd();

    if (S.StartsWith(TEXT("pass:human")))
    {
        T.Type = ESaskartaTriggerType::RoadPassHuman;
        T.RequiredFlowState = TEXT("Human");
    }
    else if (S.StartsWith(TEXT("volume:")))
    {
        // POI zone beats (POI_CINEMATICS.md): "volume:POI_O01" -> an ASaskartaEventVolume with TriggerId POI_O01.
        T.Type = ESaskartaTriggerType::Volume;
        T.VolumeId = FName(*S.Mid(7).TrimStartAndEnd());
    }
    else if (S.StartsWith(TEXT("pass")) || S.StartsWith(TEXT("curve:")))
    {
        // "pass+curve:..." and "curve:geiger_cps" (B07) still fire on their road metre;
        // the curve is the audio that plays there, not a separate trigger.
        T.Type = UeDistanceM >= 0.f ? ESaskartaTriggerType::RoadPass : ESaskartaTriggerType::Scripted;
    }
    else if (S.StartsWith(TEXT("flow:")))
    {
        T.Type = ESaskartaTriggerType::Flow;
        const FString Event = S.Mid(5);
        if (Event == TEXT("first_boot")) T.FlowEvent = TEXT("FirstBootVisionOnline");
        else T.FlowEvent = FName(*Event);
    }
    else if (S.StartsWith(TEXT("scripted:FlowState=")))
    {
        // B18: "scripted:FlowState=Collapsing; ..." -> ReportFlow(Collapsing).
        FString State = S.Mid(19);
        int32 Semi = INDEX_NONE;
        if (State.FindChar(TEXT(';'), Semi))
        {
            State = State.Left(Semi);
        }
        T.Type = ESaskartaTriggerType::Flow;
        T.FlowEvent = FName(*State.TrimStartAndEnd());
    }
    else if (S.StartsWith(TEXT("prompt")))
    {
        T.Type = ESaskartaTriggerType::Prompt;
    }
    else if (S.StartsWith(TEXT("scripted")))
    {
        T.Type = ESaskartaTriggerType::Scripted;
    }
    else if (S.StartsWith(TEXT("manual")))
    {
        T.Type = ESaskartaTriggerType::Manual;
    }
    else
    {
        T.Type = ESaskartaTriggerType::None;
    }
    return T;
}

FSaskartaEventAction USaskartaStoryImport::ParseAction(const TSharedPtr<FJsonObject>& O)
{
    using namespace SaskartaStoryImportPrivate;
    FSaskartaEventAction A;
    if (!O.IsValid())
    {
        return A;
    }
    A.Type = ParseActionType(GetString(O, TEXT("type")));
    A.Id = FName(*GetString(O, TEXT("id")));
    A.AtS = GetNumber(O, TEXT("at_s"), -1.f);
    A.DelayS = GetNumber(O, TEXT("delay_s"), 0.f);
    A.bParallel = GetBool(O, TEXT("parallel"), false);
    A.DurationS = GetNumber(O, TEXT("duration_s"), 0.f);
    A.Text = FText::FromString(GetString(O, TEXT("text")));
    A.TargetTag = FName(*GetString(O, TEXT("target_tag")));
    A.Value = GetNumber(O, TEXT("value"), 0.f);
    A.Pitch = GetNumber(O, TEXT("pitch"), 0.f);
    A.Yaw = GetNumber(O, TEXT("yaw"), 0.f);
    A.bReapplyOnLoad = GetBool(O, TEXT("reapply_on_load"), false);
    A.RequiresTags = GetNames(O, TEXT("requires_tags"));
    A.ExcludesTags = GetNames(O, TEXT("excludes_tags"));
    A.NextBeat = FName(*GetString(O, TEXT("next_beat")));
    A.bKeepOnSkip = GetBool(O, TEXT("keep_on_skip"), false);
    A.bKeepAfterCinematic = GetBool(O, TEXT("keep_after_cinematic"), false);
    A.bPausesSequence = GetBool(O, TEXT("pauses_sequence"), false);
    A.bAfterPrompt = GetBool(O, TEXT("after_prompt"), false);
    A.bFirstPlaythroughOnly = GetBool(O, TEXT("first_playthrough_only"), false);
    A.ResultText = FText::FromString(GetString(O, TEXT("result")));
    A.ColumnText = FText::FromString(GetString(O, TEXT("column")));
    return A;
}

bool USaskartaStoryImport::ParseStoryJson(const FString& Json, TArray<FSaskartaBeatDef>& OutBeats,
    TArray<FSaskartaCinematicDef>& OutCinematics, TArray<FSaskartaGlanceDef>& OutGlances, FString& OutError)
{
    using namespace SaskartaStoryImportPrivate;
    const TSharedPtr<FJsonObject> Root = ParseObject(Json);
    if (!Root.IsValid())
    {
        OutError = TEXT("story-events.json: not valid JSON");
        return false;
    }

    auto ReadBeats = [&](const TCHAR* Key, bool bOptional, bool bSystem)
    {
        const TArray<TSharedPtr<FJsonValue>>* Arr = nullptr;
        if (!Root->TryGetArrayField(Key, Arr) || !Arr)
        {
            return;
        }
        for (const TSharedPtr<FJsonValue>& V : *Arr)
        {
            const TSharedPtr<FJsonObject>* BO = nullptr;
            if (V.IsValid() && V->TryGetObject(BO) && BO)
            {
                FSaskartaBeatDef Beat = ParseBeat(*BO);
                Beat.bOptional = bOptional;
                Beat.bSystem = bSystem;
                if (!Beat.Id.IsNone())
                {
                    OutBeats.Add(MoveTemp(Beat));
                }
            }
        }
    };
    ReadBeats(TEXT("beats"), false, false);
    ReadBeats(TEXT("optional_beats"), true, false);
    ReadBeats(TEXT("system_beats"), false, true);
    ReadBeats(TEXT("hud_beats"), false, false); // HUD queries and wreck lines (storyline-first-light.md 4.2-4.3)

    const TSharedPtr<FJsonObject>* Cines = nullptr;
    if (Root->TryGetObjectField(TEXT("cinematics"), Cines) && Cines)
    {
        for (const TPair<FString, TSharedPtr<FJsonValue>>& KV : (*Cines)->Values)
        {
            const TSharedPtr<FJsonObject>* CO = nullptr;
            if (!KV.Value.IsValid() || !KV.Value->TryGetObject(CO) || !CO)
            {
                continue;
            }
            const TSharedPtr<FJsonObject>& C = *CO;
            FSaskartaCinematicDef Def;
            Def.Id = FName(*KV.Key);
            const FString Seq = GetString(C, TEXT("sequence"));
            if (!Seq.IsEmpty())
            {
                // "/Game/.../LS_CIN_01_Directive" -> "/Game/.../LS_CIN_01_Directive.LS_CIN_01_Directive"
                const FString Full = Seq.Contains(TEXT(".")) ? Seq : Seq + TEXT(".") + FPaths::GetBaseFilename(Seq);
                Def.Sequence = TSoftObjectPtr<ULevelSequence>(FSoftObjectPath(Full));
            }
            Def.DurationS = GetNumber(C, TEXT("duration_s"), 0.f);
            Def.BlendInS = GetNumber(C, TEXT("blend_in_s"), 0.f);
            Def.BlendOutS = GetNumber(C, TEXT("blend_out_s"), 2.f);
            Def.bLetterbox = GetBool(C, TEXT("letterbox"), true);
            Def.SkipRule = ParseSkipRule(GetString(C, TEXT("skip")));
            Def.SkipMinS = GetNumber(C, TEXT("skip_min_s"), 1.f);
            Def.bStopPawn = GetBool(C, TEXT("stop_pawn"), true);
            Def.bKeepStationPlaying = GetBool(C, TEXT("keep_station_playing"), false);
            Def.bRelativeToPawn = GetBool(C, TEXT("relative_to_pawn"), true);
            const FString HandBack = GetString(C, TEXT("hand_back"));
            Def.HandBack = HandBack.IsEmpty() ? FName(TEXT("CarrierPOV")) : FName(*HandBack);

            auto ReadList = [&](const TCHAR* Key, TArray<FSaskartaEventAction>& Out)
            {
                const TArray<TSharedPtr<FJsonValue>>* Arr = nullptr;
                if (C->TryGetArrayField(Key, Arr) && Arr)
                {
                    for (const TSharedPtr<FJsonValue>& V : *Arr)
                    {
                        const TSharedPtr<FJsonObject>* AO = nullptr;
                        if (V.IsValid() && V->TryGetObject(AO) && AO)
                        {
                            Out.Add(ParseAction(*AO));
                        }
                    }
                }
            };
            ReadList(TEXT("cues"), Def.Cues);
            ReadList(TEXT("final_state"), Def.FinalState);
            // Stable sort keeps the authored order of cues at the same time.
            Def.Cues.StableSort([](const FSaskartaEventAction& A, const FSaskartaEventAction& B) { return A.AtS < B.AtS; });
            OutCinematics.Add(MoveTemp(Def));
        }
    }

    const TSharedPtr<FJsonObject>* Glances = nullptr;
    if (Root->TryGetObjectField(TEXT("glances"), Glances) && Glances)
    {
        for (const TPair<FString, TSharedPtr<FJsonValue>>& KV : (*Glances)->Values)
        {
            const TSharedPtr<FJsonObject>* GO = nullptr;
            if (!KV.Value.IsValid() || !KV.Value->TryGetObject(GO) || !GO)
            {
                continue;
            }
            FSaskartaGlanceDef G;
            G.Id = FName(*KV.Key);
            G.TargetTag = FName(*GetString(*GO, TEXT("target_tag")));
            G.EaseInS = GetNumber(*GO, TEXT("ease_in_s"), 1.5f);
            G.HoldS = GetNumber(*GO, TEXT("hold_s"), 2.f);
            G.bLockMove = GetBool(*GO, TEXT("lock_move"), false);
            OutGlances.Add(G);
        }
    }
    return true;
}

// ============================================================================ lines

TArray<FString> USaskartaStoryImport::SplitTsvLine(const FString& Line)
{
    TArray<FString> Out;
    FString Cur;
    bool bInQuotes = false;
    for (int32 i = 0; i < Line.Len(); ++i)
    {
        const TCHAR C = Line[i];
        if (bInQuotes)
        {
            if (C == TEXT('"'))
            {
                if (i + 1 < Line.Len() && Line[i + 1] == TEXT('"'))
                {
                    Cur.AppendChar(TEXT('"'));
                    ++i;
                }
                else
                {
                    bInQuotes = false;
                }
            }
            else
            {
                Cur.AppendChar(C);
            }
        }
        else if (C == TEXT('"') && Cur.IsEmpty())
        {
            bInQuotes = true;
        }
        else if (C == TEXT('\t'))
        {
            Out.Add(Cur);
            Cur.Reset();
        }
        else if (C != TEXT('\r'))
        {
            Cur.AppendChar(C);
        }
    }
    Out.Add(Cur);
    return Out;
}

FString USaskartaStoryImport::CleanSpokenText(const FString& Text)
{
    FString Out;
    Out.Reserve(Text.Len());
    int32 Depth = 0;
    for (const TCHAR C : Text)
    {
        if (C == TEXT('('))
        {
            ++Depth;
            continue;
        }
        if (C == TEXT(')'))
        {
            Depth = FMath::Max(0, Depth - 1);
            continue;
        }
        if (Depth > 0 || C == TEXT('"'))
        {
            continue;
        }
        Out.AppendChar(C);
    }
    // Collapse the double spaces left where a direction was removed.
    while (Out.ReplaceInline(TEXT("  "), TEXT(" ")) > 0)
    {
    }
    return Out.TrimStartAndEnd();
}

float USaskartaStoryImport::ParseTargetSeconds(const FString& Target)
{
    const FString T = Target.TrimStartAndEnd();
    if (T.IsEmpty() || !FChar::IsDigit(T[0]))
    {
        return 0.f;
    }
    int32 End = 0;
    while (End < T.Len() && (FChar::IsDigit(T[End]) || T[End] == TEXT('.')))
    {
        ++End;
    }
    return FCString::Atof(*T.Left(End));
}

void USaskartaStoryImport::ParseLinesTsv(const FString& Tsv, TArray<FSaskartaLineDef>& OutLines)
{
    TArray<FString> Rows;
    Tsv.ParseIntoArrayLines(Rows, /*bCullEmpty*/ true);
    if (Rows.Num() < 2)
    {
        return;
    }
    // Columns by header name, so a column added later does not shift the others.
    const TArray<FString> Header = SplitTsvLine(Rows[0]);
    auto Col = [&Header](const TCHAR* Prefix) -> int32
    {
        for (int32 i = 0; i < Header.Num(); ++i)
        {
            if (Header[i].TrimStartAndEnd().StartsWith(Prefix, ESearchCase::IgnoreCase))
            {
                return i;
            }
        }
        return INDEX_NONE;
    };
    const int32 CId = Col(TEXT("ID"));
    const int32 CGroup = Col(TEXT("Group"));
    const int32 CSpeaker = Col(TEXT("Speaker"));
    const int32 CEnglish = Col(TEXT("English"));
    const int32 CDelivery = Col(TEXT("Delivery"));
    const int32 CTarget = Col(TEXT("Target"));
    const int32 CLanguage = Col(TEXT("Language"));
    const int32 CSaskartan = Col(TEXT("Saskartan translation"));
    if (CId == INDEX_NONE || CEnglish == INDEX_NONE)
    {
        return;
    }
    auto Cell = [](const TArray<FString>& R, int32 C) -> FString
    {
        return (C != INDEX_NONE && R.IsValidIndex(C)) ? R[C].TrimStartAndEnd() : FString();
    };

    for (int32 r = 1; r < Rows.Num(); ++r)
    {
        const TArray<FString> R = SplitTsvLine(Rows[r]);
        const FString Id = Cell(R, CId);
        if (Id.IsEmpty())
        {
            continue;
        }
        FSaskartaLineDef L;
        L.Id = FName(*Id);
        L.Speaker = FName(*Cell(R, CSpeaker));
        L.English = CleanSpokenText(Cell(R, CEnglish));
        L.bSaskartan = Cell(R, CLanguage).StartsWith(TEXT("SKS"), ESearchCase::IgnoreCase);
        L.Saskartan = L.bSaskartan ? CleanSpokenText(Cell(R, CSaskartan)) : FString();
        L.DurationS = ParseTargetSeconds(Cell(R, CTarget));
        L.bCarrier = Cell(R, CGroup) == TEXT("Carrier") || Id.StartsWith(TEXT("CV_"));
        if (L.bCarrier)
        {
            // Carrier rows keep the vocoder style in the Delivery column.
            L.Style = FName(*Cell(R, CDelivery));
        }
        // Carrier lines live under CarrierVoice as VO_Carrier_<Id> (make_carrier_voice.py names);
        // everything else under Lines/<Id>.
        L.Sound = TSoftObjectPtr<USoundBase>(FSoftObjectPath(L.bCarrier
            ? FString::Printf(TEXT("/Game/SaskartaGaea/Audio/CarrierVoice/VO_Carrier_%s.VO_Carrier_%s"), *Id, *Id)
            : FString::Printf(TEXT("/Game/SaskartaGaea/Audio/Lines/%s.%s"), *Id, *Id)));
        OutLines.Add(MoveTemp(L));
    }
}

void USaskartaStoryImport::ApplyCarrierLinesJson(const FString& Json, TArray<FSaskartaLineDef>& InOutLines)
{
    using namespace SaskartaStoryImportPrivate;
    const TSharedPtr<FJsonObject> Root = ParseObject(Json);
    const TArray<TSharedPtr<FJsonValue>>* Arr = nullptr;
    if (!Root.IsValid() || !Root->TryGetArrayField(TEXT("lines"), Arr) || !Arr)
    {
        return;
    }
    for (const TSharedPtr<FJsonValue>& V : *Arr)
    {
        const TSharedPtr<FJsonObject>* LO = nullptr;
        if (!V.IsValid() || !V->TryGetObject(LO) || !LO)
        {
            continue;
        }
        const FName Id(*GetString(*LO, TEXT("id")));
        FSaskartaLineDef* L = InOutLines.FindByPredicate([Id](const FSaskartaLineDef& X) { return X.Id == Id; });
        if (!L)
        {
            FSaskartaLineDef New;
            New.Id = Id;
            New.Speaker = TEXT("CARRIER");
            New.English = CleanSpokenText(GetString(*LO, TEXT("text")));
            New.bCarrier = true;
            New.Sound = TSoftObjectPtr<USoundBase>(FSoftObjectPath(FString::Printf(
                TEXT("/Game/SaskartaGaea/Audio/CarrierVoice/VO_Carrier_%s.VO_Carrier_%s"), *Id.ToString(), *Id.ToString())));
            L = &InOutLines.Add_GetRef(New);
        }
        const FString Style = GetString(*LO, TEXT("style"));
        if (!Style.IsEmpty())
        {
            L->Style = FName(*Style);
        }
        L->bCarrier = true;
    }
}

void USaskartaStoryImport::ApplyDurationsJson(const FString& Json, TArray<FSaskartaLineDef>& InOutLines)
{
    const TSharedPtr<FJsonObject> Root = SaskartaStoryImportPrivate::ParseObject(Json);
    if (!Root.IsValid())
    {
        return;
    }
    for (FSaskartaLineDef& L : InOutLines)
    {
        const TSharedPtr<FJsonValue> V = Root->TryGetField(L.Id.ToString());
        if (!V.IsValid())
        {
            continue;
        }
        double D = 0.0;
        if (V->TryGetNumber(D) && D > 0.0)
        {
            L.DurationS = static_cast<float>(D);
            continue;
        }
        const TSharedPtr<FJsonObject>* O = nullptr;
        if (V->TryGetObject(O) && O && (*O)->TryGetNumberField(TEXT("duration_s"), D) && D > 0.0)
        {
            L.DurationS = static_cast<float>(D);
        }
    }
}

bool USaskartaStoryImport::ApplyCaptionPagesJson(const FString& Json, TArray<FSaskartaLineDef>& InOutLines)
{
    const TSharedPtr<FJsonObject> Root = SaskartaStoryImportPrivate::ParseObject(Json);
    const TSharedPtr<FJsonObject>* LinesObj = nullptr;
    if (!Root.IsValid() || !Root->TryGetObjectField(TEXT("lines"), LinesObj) || !LinesObj || !LinesObj->IsValid())
    {
        return false;
    }
    for (FSaskartaLineDef& Line : InOutLines)
    {
        const TArray<TSharedPtr<FJsonValue>>* Entries = nullptr;
        if (!(*LinesObj)->TryGetArrayField(Line.Id.ToString(), Entries) || !Entries)
        {
            continue;
        }
        TArray<FSaskartaCaptionPage> Pages;
        for (const TSharedPtr<FJsonValue>& Entry : *Entries)
        {
            const TSharedPtr<FJsonObject>* PageObj = nullptr;
            if (!Entry.IsValid() || !Entry->TryGetObject(PageObj) || !PageObj || !PageObj->IsValid())
            {
                continue;
            }
            FSaskartaCaptionPage Page;
            double Start = -1.0;
            (*PageObj)->TryGetNumberField(TEXT("t"), Start);
            Page.StartS = static_cast<float>(Start);
            Page.Text = SaskartaStoryImportPrivate::GetString(*PageObj, TEXT("text"));
            Page.Saskartan = SaskartaStoryImportPrivate::GetString(*PageObj, TEXT("sks"));
            if (Page.StartS >= 0.f && !Page.Text.IsEmpty())
            {
                Pages.Add(MoveTemp(Page));
            }
        }
        Pages.Sort([](const FSaskartaCaptionPage& A, const FSaskartaCaptionPage& B) { return A.StartS < B.StartS; });
        Line.CaptionPages = MoveTemp(Pages);
    }
    return true;
}

bool USaskartaStoryImport::ParseRoadProfile(const FString& Json, TArray<FVector2f>& OutRoadMToUeM)
{
    using namespace SaskartaStoryImportPrivate;
    const TSharedPtr<FJsonObject> Root = ParseObject(Json);
    const TArray<TSharedPtr<FJsonValue>>* Arr = nullptr;
    if (!Root.IsValid() || !Root->TryGetArrayField(TEXT("samples"), Arr) || !Arr)
    {
        return false;
    }
    OutRoadMToUeM.Reset();
    for (const TSharedPtr<FJsonValue>& V : *Arr)
    {
        const TSharedPtr<FJsonObject>* SO = nullptr;
        if (V.IsValid() && V->TryGetObject(SO) && SO)
        {
            const float RoadM = GetNumber(*SO, TEXT("dist_m"), -1.f);
            const float UeM = GetNumber(*SO, TEXT("ue_spline_distance_m"), -1.f);
            if (RoadM >= 0.f && UeM >= 0.f)
            {
                OutRoadMToUeM.Add(FVector2f(RoadM, UeM));
            }
        }
    }
    OutRoadMToUeM.Sort([](const FVector2f& A, const FVector2f& B) { return A.X < B.X; });
    return OutRoadMToUeM.Num() >= 2;
}

// ============================================================================ files

bool USaskartaStoryImport::ImportStoryFromFiles(USaskartaStoryAsset* Asset, const FString& ProjectDir, FString& OutReport)
{
    if (!Asset)
    {
        OutReport = TEXT("no asset");
        return false;
    }
    const FString Story = FPaths::Combine(ProjectDir, TEXT("docs/story"));
    FString Json, Tsv, Carrier, Durations, CaptionPages, Road;
    if (!FFileHelper::LoadFileToString(Json, *FPaths::Combine(Story, TEXT("story-events.json"))))
    {
        OutReport = TEXT("missing docs/story/story-events.json");
        return false;
    }
    TArray<FSaskartaBeatDef> Beats;
    TArray<FSaskartaCinematicDef> Cines;
    TArray<FSaskartaGlanceDef> Glances;
    FString Error;
    if (!ParseStoryJson(Json, Beats, Cines, Glances, Error))
    {
        OutReport = Error;
        return false;
    }

    TArray<FSaskartaLineDef> Lines;
    if (FFileHelper::LoadFileToString(Tsv, *FPaths::Combine(Story, TEXT("radio-lines-for-translation.tsv"))))
    {
        ParseLinesTsv(Tsv, Lines);
    }
    if (FFileHelper::LoadFileToString(Carrier, *FPaths::Combine(Story, TEXT("carrier-voice-lines.json"))))
    {
        ApplyCarrierLinesJson(Carrier, Lines);
    }
    const FString DurPath = FPaths::Combine(ProjectDir, TEXT("Saved/RadioRecordings/durations.json"));
    const bool bDurations = FFileHelper::LoadFileToString(Durations, *DurPath);
    if (bDurations)
    {
        ApplyDurationsJson(Durations, Lines);
    }
    const bool bCaptionPages = FFileHelper::LoadFileToString(CaptionPages, *FPaths::Combine(Story, TEXT("caption-pages.json")))
        && ApplyCaptionPagesJson(CaptionPages, Lines);
    TArray<FVector2f> RoadPairs;
    if (FFileHelper::LoadFileToString(Road, *FPaths::Combine(Story, TEXT("road-profile.json"))))
    {
        ParseRoadProfile(Road, RoadPairs);
    }

    // Validation (EVENTS.md section 6): every line id an action names must exist.
    TArray<FString> Problems;
    auto CheckAction = [&](const FSaskartaEventAction& A, const FString& Where)
    {
        const bool bLine = A.Type == ESaskartaActionType::PlayRadioLine || A.Type == ESaskartaActionType::PlayCarrierLine
            || A.Type == ESaskartaActionType::ShowSubtitle;
        if (bLine && !Lines.ContainsByPredicate([&A](const FSaskartaLineDef& L) { return L.Id == A.Id; }))
        {
            Problems.Add(FString::Printf(TEXT("%s: line %s has no TSV row"), *Where, *A.Id.ToString()));
        }
        if (A.Type == ESaskartaActionType::PlayCinematic && !Cines.ContainsByPredicate([&A](const FSaskartaCinematicDef& C) { return C.Id == A.Id; }))
        {
            Problems.Add(FString::Printf(TEXT("%s: cinematic %s is not defined"), *Where, *A.Id.ToString()));
        }
        if (A.Type == ESaskartaActionType::None)
        {
            Problems.Add(FString::Printf(TEXT("%s: unknown action type"), *Where));
        }
    };
    for (const FSaskartaBeatDef& B : Beats)
    {
        for (const FSaskartaEventAction& A : B.Actions)
        {
            CheckAction(A, B.Id.ToString());
        }
    }
    for (const FSaskartaCinematicDef& C : Cines)
    {
        for (const FSaskartaEventAction& A : C.Cues)
        {
            CheckAction(A, C.Id.ToString());
            if (C.DurationS > 0.f && A.AtS > C.DurationS)
            {
                Problems.Add(FString::Printf(TEXT("%s: cue at %.1f s is past duration %.1f s"), *C.Id.ToString(), A.AtS, C.DurationS));
            }
        }
        for (const FSaskartaEventAction& A : C.FinalState)
        {
            CheckAction(A, C.Id.ToString() + TEXT(".final_state"));
        }
    }

    Asset->Modify();
    Asset->Beats = MoveTemp(Beats);
    Asset->Cinematics = MoveTemp(Cines);
    Asset->Glances = MoveTemp(Glances);
    Asset->Lines = MoveTemp(Lines);
    Asset->RoadMToUeM = MoveTemp(RoadPairs);
    // collapse_stage (task COLLAPSE-STAGE): absent -> the C++ defaults.
    FSaskartaCollapseStageDef Stage;
    const bool bStage = FSaskartaCollapseStageLogic::ParseJson(Json, Stage);
    Asset->CollapseStage = Stage;

    OutReport = FString::Printf(TEXT("beats %d, lines %d, cinematics %d, glances %d, road pairs %d, durations.json %s, caption-pages.json %s, collapse_stage %s (road %.0f m), problems %d"),
        Asset->Beats.Num(), Asset->Lines.Num(), Asset->Cinematics.Num(), Asset->Glances.Num(), Asset->RoadMToUeM.Num(),
        bDurations ? TEXT("read") : TEXT("absent (TSV targets used)"), bCaptionPages ? TEXT("read") : TEXT("absent or invalid"),
        bStage ? TEXT("read") : TEXT("defaults"), Stage.RoadM, Problems.Num());
    for (const FString& P : Problems)
    {
        OutReport += TEXT("\n  ") + P;
        UE_LOG(LogSaskartaStoryImport, Warning, TEXT("%s"), *P);
    }
    UE_LOG(LogSaskartaStoryImport, Log, TEXT("ImportStoryFromFiles: %s"), *OutReport.Left(400));
    return true;
}

USaskartaStoryAsset* USaskartaStoryImport::LoadStoryOrImportTransient(UObject* Outer)
{
    if (USaskartaStoryAsset* Asset = LoadObject<USaskartaStoryAsset>(nullptr, StoryAssetPath, nullptr, LOAD_NoWarn | LOAD_Quiet))
    {
        return Asset;
    }
#if WITH_EDITOR
    USaskartaStoryAsset* Transient = NewObject<USaskartaStoryAsset>(Outer ? Outer : GetTransientPackage());
    FString Report;
    if (ImportStoryFromFiles(Transient, FPaths::ProjectDir(), Report))
    {
        UE_LOG(LogSaskartaStoryImport, Warning,
            TEXT("DA_Saskarta_Story not found; imported a transient copy from docs/story (editor only). %s"), *Report.Left(300));
        return Transient;
    }
#endif
    UE_LOG(LogSaskartaStoryImport, Warning, TEXT("DA_Saskarta_Story not found (%s); the event runner is idle."), StoryAssetPath);
    return nullptr;
}
