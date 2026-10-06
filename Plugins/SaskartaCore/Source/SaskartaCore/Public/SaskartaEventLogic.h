// Pure logic of the story event runner: no world, no UObjects beyond the data structs.
// Saskarta.Events.* automation tests drive these directly (EVENTS.md sections 2, 3, 5, 7).
//
// FSaskartaEventLogic is a plain C++ struct of static functions (not a USTRUCT), so there
// is no U/F name pairing for UHT to trip on.

#pragma once

#include "CoreMinimal.h"
#include "SaskartaEventTypes.h"

/** A beat waiting for its turn. */
struct SASKARTACORE_API FSaskartaQueuedBeat
{
    FName BeatId;
    ESaskartaEventPriority Priority = ESaskartaEventPriority::Story;
    double EnqueueTimeS = 0.0;
    /** 0 = never dropped (Hint beats still drop after HintMaxWaitS). */
    float MaxLatenessS = 0.f;
    /** Tie-break for equal priority and time: the order they were enqueued. */
    int32 Seq = 0;
};

/** What the station should do when the story's busy state changes (STATION.md section 5, EVENTS.md section 3). */
enum class ESaskartaStationReaction : uint8
{
    /** Duck -12 dB over 0.3 s, then fade out over 1 s; the segment is not resumed. */
    DuckThenFade,
    /** Fade out over 1 s and pause the station clock (a cinematic). */
    Suspend,
    /** Story is quiet: may start again after the hold-off. */
    Release
};

/** One timed step of the station's reaction, in the order it happens. */
struct SASKARTACORE_API FSaskartaDuckStep
{
    enum class EKind : uint8 { Duck, FadeOut, PauseClock, ResumeGate };
    EKind Kind = EKind::Duck;
    /** Seconds after the story event when this step starts. */
    float StartS = 0.f;
    /** Length of the ramp (0 for instant steps). */
    float DurationS = 0.f;
    /** Target level in dB for Duck (relative), -inf is represented by -96. */
    float LevelDb = 0.f;
};

struct SASKARTACORE_API FSaskartaEventLogic
{
    // ------------------------------------------------------------------ constants (EVENTS.md)
    static constexpr float RoadPollS = 0.25f;
    static constexpr float StepS = 0.1f;
    // Poll each game frame at the 60 fps cap. A 50 ms timer can miss a key's one-frame pressed flag.
    static constexpr float PromptPollS = 0.01f;
    static constexpr float SkipPollS = 0.05f;
    static constexpr float GlanceTickS = 0.02f;
    static constexpr float DefaultGapS = 0.8f;
    static constexpr float HintMaxWaitS = 4.f;
    static constexpr float RoadStoryMaxLatenessS = 20.f;
    static constexpr float CriticalFadeS = 0.3f;
    static constexpr float SkipHoldS = 1.f;
    static constexpr float LetterboxBlendS = 0.6f;
    static constexpr float StopSpeedCmS = 20.f;
    static constexpr float StopTimeoutS = 1.5f;
    static constexpr float StationDuckDb = -12.f;
    static constexpr float StationDuckS = 0.3f;
    static constexpr float StationFadeS = 1.f;
    static constexpr float StationHoldoffS = 6.f;

    // ------------------------------------------------------------------ road
    /**
     * Pairs are (road m, UE m), sorted by road m; UE m falls as road m rises. Piecewise
     * linear, clamped to the ends. Empty pairs: identity-free fallback (returns -1).
     */
    static float RoadMFromUeM(const TArray<FVector2f>& RoadMToUeM, float UeM);
    static float UeMFromRoadM(const TArray<FVector2f>& RoadMToUeM, float RoadM);

    /** The high-water mark only moves forward (down in UE m): a reversing player never re-fires a beat. */
    static float UpdateHighWater(float HighWaterUeM, float CurrentUeM) { return FMath::Min(HighWaterUeM, CurrentUeM); }

    /**
     * Road beats crossed when the high-water mark moves from OldUeM to NewUeM (a beat at
     * UeDistanceM fires when the mark first drops to or below it). bHuman selects
     * RoadPassHuman beats instead of RoadPass. Skips fired one-shots and tag-gated beats.
     * Returned in road order (highest UE m first).
     */
    static void CollectRoadPasses(const TArray<FSaskartaBeatDef>& Beats, float OldUeM, float NewUeM, bool bHuman,
        const TSet<FName>& Fired, const TSet<FName>& EnabledTags, TArray<FName>& OutBeatIds);

    /** The next unfired road beat ahead of HighWaterUeM, or null. */
    static const FSaskartaBeatDef* NextRoadBeat(const TArray<FSaskartaBeatDef>& Beats, float HighWaterUeM, bool bHuman,
        const TSet<FName>& Fired, const TSet<FName>& EnabledTags);

    // ------------------------------------------------------------------ tags
    /** EnabledTags plus the derived tags: DroneSolo = Drone without AuxSensors. */
    static TSet<FName> DeriveTags(const TSet<FName>& EnabledTags);
    static bool TagsAllow(const TArray<FName>& Requires, const TArray<FName>& Excludes, const TSet<FName>& DerivedTags);

    // ------------------------------------------------------------------ queue
    static float EffectiveMaxLateness(const FSaskartaBeatDef& Beat);

    /** Index of the beat to run next: lowest priority value, then earliest enqueue, then Seq. INDEX_NONE if empty. */
    static int32 PickNextIndex(const TArray<FSaskartaQueuedBeat>& Queue);

    /** Removes beats past their lateness (Hint: HintMaxWaitS). Dropped beats are appended to OutDropped. */
    static void DropLate(TArray<FSaskartaQueuedBeat>& Queue, double NowS, TArray<FSaskartaQueuedBeat>* OutDropped);

    /** A Critical beat interrupts anything but another Critical, and never a running cinematic. */
    static bool CanPreempt(ESaskartaEventPriority Incoming, ESaskartaEventPriority Running, bool bRunningCinematic);

    /** Repeatable beats: may fire again once CooldownS has passed since the last firing. */
    static bool CooldownAllows(const FSaskartaEventTrigger& Trigger, double LastFiredS, double NowS);

    // ------------------------------------------------------------------ voice channel
    static bool IsVoiceFree(double NowS, double VoiceBusyUntilS) { return NowS + 1.0e-4 >= VoiceBusyUntilS; } // 0.1 ms slack: float line/gap lengths widen to double
    static double VoiceBusyUntilAfterLine(double StartS, float LineS, float GapS) { return StartS + FMath::Max(0.f, LineS) + FMath::Max(0.f, GapS); }

    /**
     * A short carrier line outside any beat (the stele scanner's reading, USaskartaEventRunner::
     * TryPlayAuxCarrierLine) may take the Voice channel only when nothing story-side is on it or about
     * to be: the channel free, no cinematic, no beat running or queued, at least MinGapS since the last
     * line ended, and the next road beat at least ClipS + LeadS away. A refused line is not played.
     */
    static bool CanStartAuxLine(bool bVoiceBusy, bool bCinematic, bool bBeatRunningOrQueued,
        float SecondsSinceVoice, float SecondsToNextBeat, float ClipS, float MinGapS, float LeadS)
    {
        return !bVoiceBusy && !bCinematic && !bBeatRunningOrQueued
            && SecondsSinceVoice >= MinGapS && SecondsToNextBeat >= ClipS + LeadS;
    }

    /** Does this action hold (or wait for) the Voice channel? */
    static bool NeedsVoice(ESaskartaActionType Type);

    // ------------------------------------------------------------------ station ducking
    static ESaskartaStationReaction StationReaction(bool bBusy, bool bCinematic);

    /**
     * The ordered steps the station takes for one story event (StationReaction), for
     * logging and tests: DuckThenFade = Duck(-12 dB, 0.3 s) then FadeOut(1 s) starting when
     * the duck ends; Suspend = FadeOut(1 s) and PauseClock at 0; Release = ResumeGate after 6 s.
     */
    static TArray<FSaskartaDuckStep> StationDuckPlan(ESaskartaStationReaction Reaction);

    /** A station caption never replaces a story subtitle; a story subtitle always replaces a station caption. */
    static bool SubtitleMayReplace(bool bIncomingIsStation, bool bCurrentIsStory);

    // ------------------------------------------------------------------ cinematics
    static bool CanSkip(ESaskartaSkipRule Rule, bool bSeenBefore, float ElapsedS, float SkipMinS, bool bAllowSkipAll);

    /** True when a cinematic auto-letterboxes at the start (it has no explicit ShowLetterbox cue). */
    static bool AutoLetterbox(const FSaskartaCinematicDef& Cine);

    /**
     * The TransformOrigin location of a road cinematic (relative_to_pawn): the carrier's actual stopped X/Y and its
     * feet (location minus collision half height). The spline projection is used only for orientation: the plans are
     * road-relative, but the carrier can stop laterally off the spline. Anchoring position to the projected point can
     * put the POV camera outside the carrier and make close shots clip through it. The spline's own z is a straight
     * chord between points ~100 m apart, so Z still comes from the carrier's feet; a spline-z origin can put the POV
     * eye below ground or metres above the carrier depending on where it stopped.
     */
    static FVector RoadCineOrigin(const FVector& PawnLocation, float PawnHalfHeight)
    {
        return FVector(PawnLocation.X, PawnLocation.Y, PawnLocation.Z - FMath::Max(0.f, PawnHalfHeight));
    }

    /** Road plans keep their authored +X up-road / +Y right frame even when the carrier is yawed off the spline. */
    static FRotator RoadCineRotation(const FVector& TravelTangent)
    {
        return FRotator(0.f, TravelTangent.Rotation().Yaw, 0.f);
    }

    /** Fit an authored centimetre frame to a measured socket, preserving slope but excluding imported mesh scale. */
    static FTransform CinematicSocketFrame(const FTransform& SocketWorld, const FVector& ReferencePosition,
        const FQuat& ReferenceRotation)
    {
        const FQuat Rotation = (SocketWorld.GetRotation() * ReferenceRotation.Inverse()).GetNormalized();
        return FTransform(Rotation, SocketWorld.GetLocation() - Rotation.RotateVector(ReferencePosition));
    }

    /** Cues due at TimeS, from NextCue on; advances NextCue. Cues after an unanswered prompt wait when bAfterPrompt. */
    static void CollectDueCues(const FSaskartaCinematicDef& Cine, float TimeS, bool bPromptAnswered, int32& InOutNextCue,
        TArray<int32>& OutCueIndices);

    /** The skip path: the cue lines to keep playing after the blend (bKeepOnSkip) that had not started yet. */
    static void CollectKeepOnSkip(const FSaskartaCinematicDef& Cine, int32 NextCue, TArray<FName>& OutLineIds);

    /**
     * The no-sequence path (a cinematic whose Level Sequence does not exist yet): its radio and
     * carrier line cues allowed by the tags (and not first-playthrough-only after a completed run), in
     * cue order. They play as radio on the Voice channel; the carrier is never stopped and input is
     * never locked (user, 2026-09-28: "my car got stuck" on CIN_06 / CIN_11).
     */
    static void CollectCueLines(const FSaskartaCinematicDef& Cine, const TSet<FName>& DerivedTags, bool bCompletedOnce, TArray<FName>& OutLineIds);

    /** A cinematic phase that outlives its budget by more than this is ended and input is released (the watchdog). */
    static constexpr float CineWatchdogPadS = 5.f;

    /** Watchdog test: PhaseActiveS (paused time excluded) past PhaseBudgetS + CineWatchdogPadS. */
    static bool CineWatchdogExpired(double PhaseActiveS, float PhaseBudgetS)
    {
        return PhaseActiveS > static_cast<double>(FMath::Max(0.f, PhaseBudgetS)) + CineWatchdogPadS;
    }

    // ------------------------------------------------------------------ debug arm (README_Debug.md)
    /** How far behind a beat the mark is left when the carrier already stands on it (B01 at road 0). */
    static constexpr float ArmEpsilonUeM = 0.05f;

    /** Where the carrier is put to arm a road beat: LeadM before it, never before the dock. */
    static float ArmRoadM(float BeatRoadM, float LeadM) { return FMath::Max(0.f, BeatRoadM - FMath::Max(0.f, LeadM)); }

    /** The high-water mark after arming: at the carrier, but always above the beat so the beat is crossed again. */
    static float ArmHighWaterUeM(float BeatUeM, float PawnUeM) { return FMath::Max(PawnUeM, BeatUeM + ArmEpsilonUeM); }

    /** Re-arming the optics failure must also re-arm its drone recovery after a debug jump past both beats. */
    static void RearmConnectedDebugBeats(FName BeatId, TSet<FName>& InOutFired, TMap<FName, double>& InOutLastFiredS);

    // ------------------------------------------------------------------ save
    /** Checkpoint -> road m (EVENTS.md section 7). <0 = not on the road (CP4_HUMAN, unknown). */
    static float CheckpointRoadM(FName CheckpointId);

    /** Marks every one-shot road beat with UeDistanceM >= CheckpointUeM (and every earlier beat in the chain) fired, without running it. */
    static void MarkFiredUpTo(const TArray<FSaskartaBeatDef>& Beats, float CheckpointUeM, TSet<FName>& InOutFired);

    /** Actions with bReapplyOnLoad from the beats in Fired, in beat order. */
    static void CollectReapplyActions(const TArray<FSaskartaBeatDef>& Beats, const TSet<FName>& Fired,
        TArray<FSaskartaEventAction>& OutActions);

    // ------------------------------------------------------------------ dry run
    /**
     * Simulates a drive at SpeedMps from road m 0 to EndRoadM through the queue and the
     * Voice channel (line lengths from Lines, cinematics by DurationS), with no world.
     * One log line per fire, start, finish and drop. Returns false if two story lines overlap.
     */
    static bool DryRun(const TArray<FSaskartaBeatDef>& Beats, const TArray<FSaskartaLineDef>& Lines,
        const TArray<FSaskartaCinematicDef>& Cinematics, const TArray<FVector2f>& RoadMToUeM, const TSet<FName>& EnabledTags,
        float SpeedMps, float EndRoadM, float GapS, TArray<FString>& OutLog);
};
