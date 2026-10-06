// FSaskartaEventLogic: pure runner logic. See the header.

#include "SaskartaEventLogic.h"

// ============================================================================ road

float FSaskartaEventLogic::RoadMFromUeM(const TArray<FVector2f>& P, float UeM)
{
    if (P.Num() == 0)
    {
        return -1.f;
    }
    if (P.Num() == 1)
    {
        return P[0].X;
    }
    // UE m falls along the array. Clamp outside the sampled range.
    if (UeM >= P[0].Y)
    {
        return P[0].X;
    }
    if (UeM <= P.Last().Y)
    {
        return P.Last().X;
    }
    for (int32 i = 0; i + 1 < P.Num(); ++i)
    {
        const FVector2f& A = P[i];
        const FVector2f& B = P[i + 1];
        const float Hi = FMath::Max(A.Y, B.Y);
        const float Lo = FMath::Min(A.Y, B.Y);
        if (UeM <= Hi && UeM >= Lo)
        {
            const float Span = B.Y - A.Y;
            const float T = FMath::IsNearlyZero(Span) ? 0.f : (UeM - A.Y) / Span;
            return FMath::Lerp(A.X, B.X, T);
        }
    }
    return P.Last().X;
}

float FSaskartaEventLogic::UeMFromRoadM(const TArray<FVector2f>& P, float RoadM)
{
    if (P.Num() == 0)
    {
        return -1.f;
    }
    if (RoadM <= P[0].X)
    {
        return P[0].Y;
    }
    if (RoadM >= P.Last().X)
    {
        return P.Last().Y;
    }
    for (int32 i = 0; i + 1 < P.Num(); ++i)
    {
        const FVector2f& A = P[i];
        const FVector2f& B = P[i + 1];
        if (RoadM >= A.X && RoadM <= B.X)
        {
            const float Span = B.X - A.X;
            const float T = FMath::IsNearlyZero(Span) ? 0.f : (RoadM - A.X) / Span;
            return FMath::Lerp(A.Y, B.Y, T);
        }
    }
    return P.Last().Y;
}

void FSaskartaEventLogic::CollectRoadPasses(const TArray<FSaskartaBeatDef>& Beats, float OldUeM, float NewUeM, bool bHuman,
    const TSet<FName>& Fired, const TSet<FName>& EnabledTags, TArray<FName>& OutBeatIds)
{
    if (!(NewUeM < OldUeM))
    {
        return;
    }
    const TSet<FName> Tags = DeriveTags(EnabledTags);
    const ESaskartaTriggerType Want = bHuman ? ESaskartaTriggerType::RoadPassHuman : ESaskartaTriggerType::RoadPass;
    TArray<const FSaskartaBeatDef*> Hits;
    for (const FSaskartaBeatDef& B : Beats)
    {
        if (B.Trigger.Type != Want || B.Trigger.UeDistanceM < 0.f)
        {
            continue;
        }
        if (B.Trigger.bOneShot && Fired.Contains(B.Id))
        {
            continue;
        }
        if (!TagsAllow(B.RequiresTags, B.ExcludesTags, Tags))
        {
            continue;
        }
        // Crossed: the mark was above the beat and is now at or below it.
        if (OldUeM > B.Trigger.UeDistanceM && NewUeM <= B.Trigger.UeDistanceM)
        {
            Hits.Add(&B);
        }
    }
    Hits.StableSort([](const FSaskartaBeatDef& A, const FSaskartaBeatDef& B) { return A.Trigger.UeDistanceM > B.Trigger.UeDistanceM; });
    for (const FSaskartaBeatDef* B : Hits)
    {
        OutBeatIds.Add(B->Id);
    }
}

const FSaskartaBeatDef* FSaskartaEventLogic::NextRoadBeat(const TArray<FSaskartaBeatDef>& Beats, float HighWaterUeM, bool bHuman,
    const TSet<FName>& Fired, const TSet<FName>& EnabledTags)
{
    const TSet<FName> Tags = DeriveTags(EnabledTags);
    const ESaskartaTriggerType Want = bHuman ? ESaskartaTriggerType::RoadPassHuman : ESaskartaTriggerType::RoadPass;
    const FSaskartaBeatDef* Best = nullptr;
    for (const FSaskartaBeatDef& B : Beats)
    {
        if (B.Trigger.Type != Want || B.Trigger.UeDistanceM < 0.f || B.Trigger.UeDistanceM >= HighWaterUeM)
        {
            continue;
        }
        if (Fired.Contains(B.Id) || !TagsAllow(B.RequiresTags, B.ExcludesTags, Tags))
        {
            continue;
        }
        if (!Best || B.Trigger.UeDistanceM > Best->Trigger.UeDistanceM)
        {
            Best = &B;
        }
    }
    return Best;
}

// ============================================================================ tags

TSet<FName> FSaskartaEventLogic::DeriveTags(const TSet<FName>& EnabledTags)
{
    TSet<FName> Out = EnabledTags;
    static const FName Drone(TEXT("Drone"));
    static const FName Aux(TEXT("AuxSensors"));
    static const FName DroneSolo(TEXT("DroneSolo"));
    if (Out.Contains(Drone) && !Out.Contains(Aux))
    {
        Out.Add(DroneSolo);
    }
    return Out;
}

bool FSaskartaEventLogic::TagsAllow(const TArray<FName>& Requires, const TArray<FName>& Excludes, const TSet<FName>& DerivedTags)
{
    for (const FName& R : Requires)
    {
        if (!DerivedTags.Contains(R))
        {
            return false;
        }
    }
    for (const FName& E : Excludes)
    {
        if (DerivedTags.Contains(E))
        {
            return false;
        }
    }
    return true;
}

// ============================================================================ queue

float FSaskartaEventLogic::EffectiveMaxLateness(const FSaskartaBeatDef& Beat)
{
    if (Beat.Trigger.MaxLatenessS > 0.f)
    {
        return Beat.Trigger.MaxLatenessS;
    }
    if (Beat.Priority == ESaskartaEventPriority::Hint)
    {
        return HintMaxWaitS;
    }
    // Mid-road story beats: their vignettes are in view for about 20 s.
    const bool bRoad = Beat.Trigger.Type == ESaskartaTriggerType::RoadPass || Beat.Trigger.Type == ESaskartaTriggerType::RoadPassHuman;
    if (Beat.Priority == ESaskartaEventPriority::Story && bRoad)
    {
        return RoadStoryMaxLatenessS;
    }
    return 0.f;
}

int32 FSaskartaEventLogic::PickNextIndex(const TArray<FSaskartaQueuedBeat>& Queue)
{
    int32 Best = INDEX_NONE;
    for (int32 i = 0; i < Queue.Num(); ++i)
    {
        if (Best == INDEX_NONE)
        {
            Best = i;
            continue;
        }
        const FSaskartaQueuedBeat& A = Queue[i];
        const FSaskartaQueuedBeat& B = Queue[Best];
        const uint8 PA = static_cast<uint8>(A.Priority);
        const uint8 PB = static_cast<uint8>(B.Priority);
        if (PA != PB)
        {
            if (PA < PB) Best = i;
            continue;
        }
        if (A.EnqueueTimeS != B.EnqueueTimeS)
        {
            if (A.EnqueueTimeS < B.EnqueueTimeS) Best = i;
            continue;
        }
        if (A.Seq < B.Seq)
        {
            Best = i;
        }
    }
    return Best;
}

void FSaskartaEventLogic::DropLate(TArray<FSaskartaQueuedBeat>& Queue, double NowS, TArray<FSaskartaQueuedBeat>* OutDropped)
{
    for (int32 i = Queue.Num() - 1; i >= 0; --i)
    {
        const FSaskartaQueuedBeat& Q = Queue[i];
        float Limit = Q.MaxLatenessS;
        if (Q.Priority == ESaskartaEventPriority::Hint)
        {
            Limit = Limit > 0.f ? FMath::Min(Limit, HintMaxWaitS) : HintMaxWaitS;
        }
        if (Limit > 0.f && NowS - Q.EnqueueTimeS > Limit)
        {
            if (OutDropped)
            {
                OutDropped->Add(Q);
            }
            Queue.RemoveAt(i);
        }
    }
}

bool FSaskartaEventLogic::CanPreempt(ESaskartaEventPriority Incoming, ESaskartaEventPriority Running, bool bRunningCinematic)
{
    return Incoming == ESaskartaEventPriority::Critical && Running != ESaskartaEventPriority::Critical && !bRunningCinematic;
}

bool FSaskartaEventLogic::CooldownAllows(const FSaskartaEventTrigger& Trigger, double LastFiredS, double NowS)
{
    if (LastFiredS < 0.0)
    {
        return true;
    }
    return NowS - LastFiredS >= Trigger.CooldownS;
}

bool FSaskartaEventLogic::NeedsVoice(ESaskartaActionType Type)
{
    return Type == ESaskartaActionType::PlayRadioLine || Type == ESaskartaActionType::PlayCarrierLine
        || Type == ESaskartaActionType::PlayCinematic;
}

// ============================================================================ station ducking

ESaskartaStationReaction FSaskartaEventLogic::StationReaction(bool bBusy, bool bCinematic)
{
    if (!bBusy)
    {
        return ESaskartaStationReaction::Release;
    }
    return bCinematic ? ESaskartaStationReaction::Suspend : ESaskartaStationReaction::DuckThenFade;
}

TArray<FSaskartaDuckStep> FSaskartaEventLogic::StationDuckPlan(ESaskartaStationReaction Reaction)
{
    TArray<FSaskartaDuckStep> Steps;
    FSaskartaDuckStep S;
    switch (Reaction)
    {
    case ESaskartaStationReaction::DuckThenFade:
        S.Kind = FSaskartaDuckStep::EKind::Duck; S.StartS = 0.f; S.DurationS = StationDuckS; S.LevelDb = StationDuckDb;
        Steps.Add(S);
        S.Kind = FSaskartaDuckStep::EKind::FadeOut; S.StartS = StationDuckS; S.DurationS = StationFadeS; S.LevelDb = -96.f;
        Steps.Add(S);
        break;
    case ESaskartaStationReaction::Suspend:
        S.Kind = FSaskartaDuckStep::EKind::FadeOut; S.StartS = 0.f; S.DurationS = StationFadeS; S.LevelDb = -96.f;
        Steps.Add(S);
        S.Kind = FSaskartaDuckStep::EKind::PauseClock; S.StartS = 0.f; S.DurationS = 0.f; S.LevelDb = 0.f;
        Steps.Add(S);
        break;
    case ESaskartaStationReaction::Release:
        S.Kind = FSaskartaDuckStep::EKind::ResumeGate; S.StartS = StationHoldoffS; S.DurationS = 0.f; S.LevelDb = 0.f;
        Steps.Add(S);
        break;
    }
    return Steps;
}

bool FSaskartaEventLogic::SubtitleMayReplace(bool bIncomingIsStation, bool bCurrentIsStory)
{
    return !(bIncomingIsStation && bCurrentIsStory);
}

// ============================================================================ cinematics

bool FSaskartaEventLogic::CanSkip(ESaskartaSkipRule Rule, bool bSeenBefore, float ElapsedS, float SkipMinS, bool bAllowSkipAll)
{
    if (ElapsedS < SkipMinS)
    {
        return false;
    }
    if (bAllowSkipAll)
    {
        return true;
    }
    switch (Rule)
    {
    case ESaskartaSkipRule::Never: return false;
    case ESaskartaSkipRule::HoldAfterSeen: return bSeenBefore;
    case ESaskartaSkipRule::HoldAlways: return true;
    case ESaskartaSkipRule::AnyKeyAfter: return true;
    }
    return false;
}

bool FSaskartaEventLogic::AutoLetterbox(const FSaskartaCinematicDef& Cine)
{
    if (!Cine.bLetterbox)
    {
        return false;
    }
    return !Cine.Cues.ContainsByPredicate([](const FSaskartaEventAction& A) { return A.Type == ESaskartaActionType::ShowLetterbox; });
}

void FSaskartaEventLogic::CollectDueCues(const FSaskartaCinematicDef& Cine, float TimeS, bool bPromptAnswered, int32& InOutNextCue,
    TArray<int32>& OutCueIndices)
{
    while (Cine.Cues.IsValidIndex(InOutNextCue))
    {
        const FSaskartaEventAction& Cue = Cine.Cues[InOutNextCue];
        if (Cue.AtS > TimeS)
        {
            break;
        }
        if (Cue.bAfterPrompt && !bPromptAnswered)
        {
            break;
        }
        OutCueIndices.Add(InOutNextCue);
        ++InOutNextCue;
        // A cue that pauses the sequence is the last one this step: the rest wait for the key.
        if (Cue.Type == ESaskartaActionType::Prompt && Cue.bPausesSequence)
        {
            break;
        }
    }
}

void FSaskartaEventLogic::CollectCueLines(const FSaskartaCinematicDef& Cine, const TSet<FName>& DerivedTags, bool bCompletedOnce, TArray<FName>& OutLineIds)
{
    for (const FSaskartaEventAction& Cue : Cine.Cues)
    {
        if ((Cue.Type == ESaskartaActionType::PlayRadioLine || Cue.Type == ESaskartaActionType::PlayCarrierLine) && !Cue.Id.IsNone()
            && TagsAllow(Cue.RequiresTags, Cue.ExcludesTags, DerivedTags) && !(Cue.bFirstPlaythroughOnly && bCompletedOnce))
        {
            OutLineIds.Add(Cue.Id);
        }
    }
}

void FSaskartaEventLogic::CollectKeepOnSkip(const FSaskartaCinematicDef& Cine, int32 NextCue, TArray<FName>& OutLineIds)
{
    for (int32 i = FMath::Max(0, NextCue); i < Cine.Cues.Num(); ++i)
    {
        const FSaskartaEventAction& Cue = Cine.Cues[i];
        if (Cue.bKeepOnSkip && (Cue.Type == ESaskartaActionType::PlayCarrierLine || Cue.Type == ESaskartaActionType::PlayRadioLine))
        {
            OutLineIds.Add(Cue.Id);
        }
    }
}

// ============================================================================ save

float FSaskartaEventLogic::CheckpointRoadM(FName CheckpointId)
{
    static const TMap<FName, float> Map = {
        { FName(TEXT("CP0_DOCK")), 0.f },
        { FName(TEXT("CP1_CREST")), 1990.f },
        { FName(TEXT("CP2_WAYSTATION")), 3420.f },
        { FName(TEXT("CP3_SHOULDER")), 4465.f },
    };
    const float* M = Map.Find(CheckpointId);
    return M ? *M : -1.f;
}

void FSaskartaEventLogic::RearmConnectedDebugBeats(FName BeatId, TSet<FName>& InOutFired,
    TMap<FName, double>& InOutLastFiredS)
{
    InOutFired.Remove(BeatId);
    InOutLastFiredS.Remove(BeatId);
    if (BeatId == FName(TEXT("OA1_OPTICS_FAIL")))
    {
        const FName Recovery(TEXT("OB1_DRONE"));
        InOutFired.Remove(Recovery);
        InOutLastFiredS.Remove(Recovery);
    }
}

void FSaskartaEventLogic::MarkFiredUpTo(const TArray<FSaskartaBeatDef>& Beats, float CheckpointUeM, TSet<FName>& InOutFired)
{
    for (const FSaskartaBeatDef& B : Beats)
    {
        if (B.bSystem || !B.Trigger.bOneShot)
        {
            continue;
        }
        const bool bRoad = B.Trigger.Type == ESaskartaTriggerType::RoadPass || B.Trigger.Type == ESaskartaTriggerType::RoadPassHuman;
        // Road beats behind the checkpoint, and flow beats (B01) that sit at or behind it on the road.
        if (B.Trigger.UeDistanceM >= 0.f && B.Trigger.UeDistanceM >= CheckpointUeM && (bRoad || B.Trigger.Type == ESaskartaTriggerType::Flow))
        {
            InOutFired.Add(B.Id);
        }
    }
}

void FSaskartaEventLogic::CollectReapplyActions(const TArray<FSaskartaBeatDef>& Beats, const TSet<FName>& Fired,
    TArray<FSaskartaEventAction>& OutActions)
{
    for (const FSaskartaBeatDef& B : Beats)
    {
        if (!Fired.Contains(B.Id))
        {
            continue;
        }
        for (const FSaskartaEventAction& A : B.Actions)
        {
            if (A.bReapplyOnLoad)
            {
                OutActions.Add(A);
            }
        }
    }
}

// ============================================================================ dry run

bool FSaskartaEventLogic::DryRun(const TArray<FSaskartaBeatDef>& Beats, const TArray<FSaskartaLineDef>& Lines,
    const TArray<FSaskartaCinematicDef>& Cinematics, const TArray<FVector2f>& RoadMToUeM, const TSet<FName>& EnabledTags,
    float SpeedMps, float EndRoadM, float GapS, TArray<FString>& OutLog)
{
    const TSet<FName> Tags = DeriveTags(EnabledTags);
    auto LineLen = [&Lines](FName Id) -> float
    {
        const FSaskartaLineDef* L = Lines.FindByPredicate([Id](const FSaskartaLineDef& X) { return X.Id == Id; });
        return (L && L->DurationS > 0.f) ? L->DurationS : 3.f;
    };
    auto FindBeat = [&Beats](FName Id) { return Beats.FindByPredicate([Id](const FSaskartaBeatDef& B) { return B.Id == Id; }); };

    const float Dt = 0.1f;
    double T = 0.0;
    float RoadM = 0.f;
    float HighWater = TNumericLimits<float>::Max();
    TSet<FName> Fired;
    TArray<FSaskartaQueuedBeat> Queue;
    int32 Seq = 0;
    double VoiceBusyUntil = 0.0;
    double LastLineEnd = -1.0;
    bool bOk = true;

    // Running beat.
    const FSaskartaBeatDef* Running = nullptr;
    int32 ActionIndex = 0;
    double BlockedUntil = 0.0;
    double PawnStoppedUntil = 0.0;

    auto Enqueue = [&](const FSaskartaBeatDef& B)
    {
        FSaskartaQueuedBeat Q;
        Q.BeatId = B.Id;
        Q.Priority = B.Priority;
        Q.EnqueueTimeS = T;
        Q.MaxLatenessS = EffectiveMaxLateness(B);
        Q.Seq = Seq++;
        Queue.Add(Q);
        if (B.Trigger.bOneShot)
        {
            Fired.Add(B.Id);
        }
        OutLog.Add(FString::Printf(TEXT("%7.1fs  road %6.0f  FIRE   %s"), T, RoadM, *B.Id.ToString()));
    };

    for (const FSaskartaBeatDef& B : Beats)
    {
        if (B.Trigger.Type == ESaskartaTriggerType::Flow && B.Trigger.FlowEvent == FName(TEXT("FirstBootVisionOnline")))
        {
            Enqueue(B);
        }
    }

    const double MaxT = (EndRoadM / FMath::Max(SpeedMps, 0.1f)) + 600.0;
    while (T < MaxT)
    {
        // Drive (the pawn stops for cinematics that stop it).
        if (T >= PawnStoppedUntil && RoadM < EndRoadM)
        {
            RoadM = FMath::Min(EndRoadM, RoadM + SpeedMps * Dt);
        }
        const float UeM = UeMFromRoadM(RoadMToUeM, RoadM);
        TArray<FName> Hits;
        CollectRoadPasses(Beats, HighWater, UeM, false, Fired, EnabledTags, Hits);
        HighWater = UpdateHighWater(HighWater, UeM);
        for (const FName& Id : Hits)
        {
            if (const FSaskartaBeatDef* B = FindBeat(Id))
            {
                Enqueue(*B);
            }
        }

        TArray<FSaskartaQueuedBeat> Dropped;
        DropLate(Queue, T, &Dropped);
        for (const FSaskartaQueuedBeat& D : Dropped)
        {
            OutLog.Add(FString::Printf(TEXT("%7.1fs  road %6.0f  DROP   %s (late %.1f s)"), T, RoadM, *D.BeatId.ToString(), T - D.EnqueueTimeS));
        }

        if (!Running)
        {
            const int32 Next = PickNextIndex(Queue);
            if (Next != INDEX_NONE)
            {
                const FSaskartaQueuedBeat Q = Queue[Next];
                Queue.RemoveAt(Next);
                Running = FindBeat(Q.BeatId);
                ActionIndex = 0;
                BlockedUntil = T;
                if (Running)
                {
                    OutLog.Add(FString::Printf(TEXT("%7.1fs  road %6.0f  START  %s (waited %.1f s)"), T, RoadM, *Q.BeatId.ToString(), T - Q.EnqueueTimeS));
                }
            }
        }

        while (Running && T >= BlockedUntil)
        {
            if (!Running->Actions.IsValidIndex(ActionIndex))
            {
                OutLog.Add(FString::Printf(TEXT("%7.1fs  road %6.0f  END    %s"), T, RoadM, *Running->Id.ToString()));
                Running = nullptr;
                break;
            }
            const FSaskartaEventAction& A = Running->Actions[ActionIndex];
            if (!TagsAllow(A.RequiresTags, A.ExcludesTags, Tags))
            {
                ++ActionIndex;
                continue;
            }
            if (NeedsVoice(A.Type) && !IsVoiceFree(T, VoiceBusyUntil))
            {
                break;
            }
            double Done = T;
            if (A.Type == ESaskartaActionType::PlayRadioLine || A.Type == ESaskartaActionType::PlayCarrierLine)
            {
                const float Len = LineLen(A.Id);
                if (LastLineEnd > T + KINDA_SMALL_NUMBER)
                {
                    bOk = false;
                    OutLog.Add(FString::Printf(TEXT("%7.1fs  OVERLAP %s starts before the previous line ends (%.1f s)"), T, *A.Id.ToString(), LastLineEnd));
                }
                LastLineEnd = T + Len;
                VoiceBusyUntil = VoiceBusyUntilAfterLine(T, Len, GapS);
                Done = VoiceBusyUntil;
                OutLog.Add(FString::Printf(TEXT("%7.1fs  road %6.0f  LINE   %s (%.1f s)"), T, RoadM, *A.Id.ToString(), Len));
            }
            else if (A.Type == ESaskartaActionType::PlayCinematic)
            {
                const FSaskartaCinematicDef* C = Cinematics.FindByPredicate([&A](const FSaskartaCinematicDef& X) { return X.Id == A.Id; });
                const float Len = C ? C->DurationS + C->BlendOutS : 0.f;
                VoiceBusyUntil = T + Len;
                LastLineEnd = FMath::Max(LastLineEnd, T + Len);
                Done = T + Len;
                if (C && C->bStopPawn)
                {
                    PawnStoppedUntil = Done;
                }
                OutLog.Add(FString::Printf(TEXT("%7.1fs  road %6.0f  CINE   %s (%.1f s)"), T, RoadM, *A.Id.ToString(), Len));
            }
            else if (A.Type == ESaskartaActionType::Wait || A.Type == ESaskartaActionType::ShowCaption)
            {
                Done = T + A.DurationS;
            }
            else if (A.Type == ESaskartaActionType::Prompt)
            {
                Done = T + 1.0; // the player presses after a second
                if (!A.NextBeat.IsNone())
                {
                    if (const FSaskartaBeatDef* NB = FindBeat(A.NextBeat))
                    {
                        Enqueue(*NB);
                    }
                }
            }
            ++ActionIndex;
            if (!A.bParallel)
            {
                BlockedUntil = Done;
            }
        }

        if (RoadM >= EndRoadM && !Running && Queue.Num() == 0 && T >= VoiceBusyUntil)
        {
            break;
        }
        T += Dt;
    }
    OutLog.Add(FString::Printf(TEXT("DryRun: %.0f m at %.1f m/s, %.1f s, %d beats fired, overlap %s"),
        EndRoadM, SpeedMps, T, Fired.Num(), bOk ? TEXT("none") : TEXT("FOUND")));
    return bOk;
}
