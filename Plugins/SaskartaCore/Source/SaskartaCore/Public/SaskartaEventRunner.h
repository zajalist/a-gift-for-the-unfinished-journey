// USaskartaEventRunner: the story event runner (docs/story/EVENTS.md).
//
// A world subsystem (game and PIE worlds). It loads DA_Saskarta_Story, polls the carrier's
// road distance every 0.25 s, takes flow reports and volume overlaps, and runs one beat at
// a time from a priority queue: radio and carrier lines on an exclusive Voice channel,
// cinematics through ULevelSequencePlayer (camera blend out of and back into the pawn
// camera by the camera-cut track's ease, input lock, letterbox, hold-to-skip), captions,
// subtitles (with the Saskartan line), glances, prompts, look/fog requests, flow state,
// hooks and checkpoints. Every clock is an FTimerHandle; there is no Tick.
//
// The UI binds to the BlueprintAssignable events below (subtitle, caption, prompt,
// letterbox, skip ring, end card). The station binds OnStoryBusyChanged (duck versus
// suspend). The decisions are in FSaskartaEventLogic, which the tests drive directly.
//
// Missing assets never stop the story: a line without a sound still shows its subtitle and
// holds Voice for its duration; a cinematic without a sequence never locks input or stops
// the carrier: its line cues play as radio on the Voice channel and its FinalState runs at
// once (so CIN_01 still hands control back). A cinematic that does play is watched: a phase
// that outlives its budget by CineWatchdogPadS ends and releases input, and every lock is
// released on skip, abort, StopAll and world teardown (PIE end).

#pragma once

#include "CoreMinimal.h"
#include "Subsystems/WorldSubsystem.h"
#include "TimerManager.h"
#include "SaskartaEventTypes.h"
#include "SaskartaEventLogic.h"
#include "SaskartaHudQueryLogic.h"
#include "SaskartaEventRunner.generated.h"

class AActor;
class ACharacter;
class ALevelSequenceActor;
class APawn;
class APlayerController;
class UAudioComponent;
class ULevelSequencePlayer;
class USaskartaStoryAsset;
class USaskartaSaveGame;
class USoundBase;
class USplineComponent;
class UWorldPartitionStreamingSourceComponent;
class FSceneViewExtensionBase;
struct FMinimalViewInfo;

DECLARE_DYNAMIC_MULTICAST_DELEGATE_ThreeParams(FSaskartaStoryBusy, bool, bBusy, float, ExpectedS, bool, bCinematic);
DECLARE_DYNAMIC_MULTICAST_DELEGATE_OneParam(FSaskartaSubtitleShow, const FSaskartaSubtitle&, Subtitle);
DECLARE_DYNAMIC_MULTICAST_DELEGATE_OneParam(FSaskartaSubtitleHide, bool, bStation);
DECLARE_DYNAMIC_MULTICAST_DELEGATE_ThreeParams(FSaskartaCaptionShow, const FText&, Text, FName, Target, float, DurationS);
DECLARE_DYNAMIC_MULTICAST_DELEGATE_OneParam(FSaskartaCaptionHide, FName, Target);
DECLARE_DYNAMIC_MULTICAST_DELEGATE_TwoParams(FSaskartaLetterbox, bool, bOn, float, BlendS);
DECLARE_DYNAMIC_MULTICAST_DELEGATE_OneParam(FSaskartaPromptShow, const FText&, Text);
DECLARE_DYNAMIC_MULTICAST_DELEGATE(FSaskartaPromptHide);
DECLARE_DYNAMIC_MULTICAST_DELEGATE_OneParam(FSaskartaSkipProgress, float, Fraction);
DECLARE_DYNAMIC_MULTICAST_DELEGATE_TwoParams(FSaskartaLookRequest, FName, LookKey, float, BlendS);
DECLARE_DYNAMIC_MULTICAST_DELEGATE_TwoParams(FSaskartaFogRequest, float, Multiplier, float, BlendS);
DECLARE_DYNAMIC_MULTICAST_DELEGATE_TwoParams(FSaskartaModeChanged, FName, Mode, bool, bOn);
DECLARE_DYNAMIC_MULTICAST_DELEGATE_OneParam(FSaskartaNamedEvent, FName, Id);
DECLARE_DYNAMIC_MULTICAST_DELEGATE_FiveParams(FSaskartaStoryLine, FName, LineId, FName, BeatId, bool, bCarrier, int32, BeatPriority, float, DurationS);

/** What the running beat is waiting on (not reflected). */
enum class ESaskartaRunWait : uint8 { None, Time, Voice, Cinematic, Prompt };

/** Where a cinematic is (not reflected). */
enum class ESaskartaCinePhase : uint8 { None, WaitingStop, Playing, BlendingOut };

UCLASS()
class SASKARTACORE_API USaskartaEventRunner : public UWorldSubsystem
{
    GENERATED_BODY()

public:
    UFUNCTION(BlueprintPure, Category = "Saskarta|Events", meta = (WorldContext = "WorldContextObject"))
    static USaskartaEventRunner* GetEventRunner(const UObject* WorldContextObject);

    // Native camera safety: final post-blend viewpoint and physical drone handoffs.
    void ConstrainCinematicView(APlayerController* Player, FMinimalViewInfo& View);
    FVector ConstrainCarrierCameraPath(const FVector& From, const FVector& To);
    void SetCollisionSafeViewTarget(APlayerController* Player, AActor* Target, float BlendS);

    // ------------------------------------------------------------------ API (EVENTS.md section 3)
    /** PC_Saskarta calls this at each flow change: FirstBootVisionOnline, RebootVisionOnline, TetherWarning, Collapsing, HumanPossessed. */
    UFUNCTION(BlueprintCallable, Category = "Saskarta|Events")
    void ReportFlow(FName FlowEvent);

    /** Queues a beat by id (scripted chains, tests, the console). bForce ignores one-shot and tag gating. */
    UFUNCTION(BlueprintCallable, Category = "Saskarta|Events")
    bool FireBeat(FName BeatId, bool bForce = false);

    UFUNCTION(BlueprintCallable, Category = "Saskarta|Events")
    void NotifyVolume(FName TriggerId, APawn* Pawn);

    UFUNCTION(BlueprintPure, Category = "Saskarta|Events")
    bool IsCinematicActive() const { return CinePhase != ESaskartaCinePhase::None; }

    /** Translation for a sensor POV only; exterior shots retain the authored road frame. */
    bool GetCinematicSensorOffset(float AuthoredEyeHeightCm, FVector& OutOffset) const;

    /** Sequence time, frozen by pause; -1 before playback and after it finishes. */
    UFUNCTION(BlueprintPure, Category = "Saskarta|Events")
    float GetCinematicPlaybackSeconds() const;

    UFUNCTION(BlueprintPure, Category = "Saskarta|Events")
    FName GetActiveCinematicId() const { return ActiveCineId; }

    UFUNCTION(BlueprintPure, Category = "Saskarta|Events")
    bool IsVoiceBusy() const;

    /** Seconds since the last story, carrier or cinematic line ended (large if none yet). */
    UFUNCTION(BlueprintPure, Category = "Saskarta|Events")
    float SecondsSinceVoice() const;

    /** Radio-specific gate: camera-only cinematics do not occupy its audio channel. */
    bool ShouldKeepStationPlaying() const;
    bool IsStationVoiceBusy() const;
    float SecondsSinceStationVoice() const;

    UFUNCTION(BlueprintPure, Category = "Saskarta|Events")
    bool CanSkipCurrentCinematic() const;

    UFUNCTION(BlueprintCallable, Category = "Saskarta|Events")
    void SkipCurrentCinematic();

    /** The pause menu pauses a playing cinematic too. */
    UFUNCTION(BlueprintCallable, Category = "Saskarta|Events")
    void PauseCinematic(bool bPause);

    /** Stops everything: lines, the cinematic (and its spawnables), prompts, glances, the queue. QuitToTitle calls it first. */
    UFUNCTION(BlueprintCallable, Category = "Saskarta|Events")
    void StopAll();

    UFUNCTION(BlueprintCallable, Category = "Saskarta|Events")
    bool SaveCheckpoint(FName CheckpointId);

    /** Complete run snapshot, including registered power/radio/world save hooks. No disk write. */
    USaskartaSaveGame* CreateCheckpointSnapshot(FName CheckpointId, bool bExactCarrierPose = false);

    /** Shared by Continue and encounter retry; restores run state and stages a collision-gated pawn handoff. */
    bool RestoreCheckpointSnapshot(USaskartaSaveGame* Snapshot);

    /** Restores the Saskarta_Run slot: marks beats fired without running them, replays bReapplyOnLoad actions, teleports the pawn. */
    UFUNCTION(BlueprintCallable, Category = "Saskarta|Events")
    bool RestoreFromSave();

    /** Plays a cinematic outside any beat (console Saskarta.Cine.Play). */
    UFUNCTION(BlueprintCallable, Category = "Saskarta|Events")
    void PlayCinematicById(FName CinematicId);

    /** Teleports the pawn to RoadM on the spline and marks the beats behind it fired (Saskarta.Events.GoTo). */
    UFUNCTION(BlueprintCallable, Category = "Saskarta|Events")
    bool GoToRoadM(float RoadM);

    UFUNCTION(BlueprintCallable, Category = "Saskarta|Events")
    void SetEnabledTags(const TArray<FName>& Tags);

    // --- debug mode (defined in SaskartaDebugTools.cpp; README_Debug.md)
    /** Clears BeatId's one-shot flag and cooldown, and rewinds the high-water mark to the pawn so a road beat fires again when reached. */
    UFUNCTION(BlueprintCallable, Category = "Saskarta|Debug")
    bool ResetBeat(FName BeatId);

    /** Clears every one-shot flag and cooldown and rewinds the high-water mark to the pawn. */
    UFUNCTION(BlueprintCallable, Category = "Saskarta|Debug")
    void ResetAllBeats();

    UFUNCTION(BlueprintPure, Category = "Saskarta|Debug")
    FName GetRunningBeatId() const { return bHasRunning ? RunningBeatId : NAME_None; }

    UFUNCTION(BlueprintPure, Category = "Saskarta|Debug")
    bool HasBeatFired(FName BeatId) const { return FiredBeats.Contains(BeatId); }

    /**
     * Arms one beat without touching the Continue save: clears its one-shot flag, then
     * - a road beat: teleports the carrier LeadM (of road) before it and leaves the mark behind it,
     *   so it fires when the carrier reaches it; a beat closer than LeadM to the dock (B01's road 0)
     *   is armed at the dock and fires on the next road poll;
     * - a flow beat (B01 is flow:first_boot): fires on the next ReportFlow of its flow event;
     * - a volume beat: fires on the next overlap.
     */
    UFUNCTION(BlueprintCallable, Category = "Saskarta|Debug")
    bool ArmBeat(FName BeatId, float LeadM = 30.f);

    /**
     * Ends any cinematic at once (its final state still runs) and releases every input lock this
     * runner holds (cinematic, SetInputLock, glance). The cinematic watchdog calls it; so can the
     * debug menu or a stuck player (console Saskarta.Events.ReleaseInput).
     */
    UFUNCTION(BlueprintCallable, Category = "Saskarta|Events")
    void ForceReleaseInput();

    /** True while this runner holds a move or look lock on the player controller. */
    UFUNCTION(BlueprintPure, Category = "Saskarta|Events")
    bool IsHoldingInput() const { return bHumanGroundingActive || bCarrierGroundingActive || MoveLocks > 0 || LookLocks > 0 || bGlanceMoveLocked || bGlanceLookLocked; }

    UFUNCTION(BlueprintPure, Category = "Saskarta|Events")
    float GetRoadM() const { return CurrentRoadM; }

    UFUNCTION(BlueprintPure, Category = "Saskarta|Events")
    float GetHighWaterUeM() const { return HighWaterUeM; }

    /** The road spline road beats run on (None until BP_Saskarta_Road is found). The route map draws it. */
    USplineComponent* GetRoadSpline() const;

    UFUNCTION(BlueprintPure, Category = "Saskarta|Events")
    float GetSpeedMps() const { return SpeedMps; }

    /** (next unfired road beat's road m - road m) / max(speed, 0.5 m/s); large when none is ahead. */
    UFUNCTION(BlueprintPure, Category = "Saskarta|Events")
    float GetSecondsToNextBeat() const;

    /** PC_Saskarta.FlowState, read by reflection (None if absent). */
    UFUNCTION(BlueprintPure, Category = "Saskarta|Events")
    FName GetFlowState() const;

    /** Story interaction owns E while a prompt is displayed. */
    UFUNCTION(BlueprintPure, Category = "Saskarta|Events")
    bool IsPromptActive() const { return bPromptActive; }

    /** Persist a presentation feed in the run save and notify its runtime owner. */
    UFUNCTION(BlueprintCallable, Category = "Saskarta|Events")
    void SetPresentationMode(FName Mode, bool bOn);

    UFUNCTION(BlueprintPure, Category = "Saskarta|Events")
    bool IsPresentationModeActive(FName Mode) const { return ActiveModes.Contains(Mode); }

    /** True while a story subtitle is on screen (the station's caption must not replace it). */
    UFUNCTION(BlueprintPure, Category = "Saskarta|Events")
    bool IsStorySubtitleActive() const { return bStorySubtitleActive; }

    /** The station's caption path: shown only if no story subtitle is up. */
    UFUNCTION(BlueprintCallable, Category = "Saskarta|Events")
    void ShowStationSubtitle(const FSaskartaSubtitle& Subtitle);

    UFUNCTION(BlueprintCallable, Category = "Saskarta|Events")
    void HideStationSubtitle();

    /** Freeze the station caption clock with its audio while the menu is open. */
    void SetStationSubtitlePaused(bool bPaused);

    /**
     * Plays a short carrier line outside any beat on the Voice channel (the stele scanner's reading,
     * docs/look/STELE_SCAN.md 3.5), only if FSaskartaEventLogic::CanStartAuxLine allows it: Voice free,
     * no cinematic, no beat running or queued, MinGapS since the last line, the next road beat at least
     * clip + LeadS away. On success it holds Voice for the clip (a beat that fires meanwhile queues), and
     * broadcasts OnStoryLine (carrier, Hint priority) then OnStoryBusyChanged, like a beat line, so the
     * station ducks instead of cutting. No subtitle: the scanner's HUD block is the text. Returns false
     * (nothing played) when refused. DurationS is used when Sound is null or has no length.
     */
    UFUNCTION(BlueprintCallable, Category = "Saskarta|Events")
    bool TryPlayAuxCarrierLine(FName LineId, USoundBase* Sound, float DurationS, float MinGapS = 1.5f, float LeadS = 4.f);

    /** EarlyStorm polls this after its cinematic. Starts varied short warnings only in a free
     * Voice/input-warning window; inactive cancels only this lane. Never controls camera/input. */
    void UpdateStormPanic(float GapM, bool bActive, bool bInputWarningActive);
    /** Short environmental alarms may start only in a quiet, free driving window. */
    bool CanPlayStormAlarm() const;

    /** The current driving status lines, shown on caption target HudColumn. */
    UFUNCTION(BlueprintPure, Category = "Saskarta|Events")
    FString GetHudStatus() const { return HudLane.Column; }

    /** Replaces the status lines (USaskartaRouteLog). Shown unless B18's HUD_STATUS_FADE faded them. */
    UFUNCTION(BlueprintCallable, Category = "Saskarta|Events")
    void SetHudStatus(const FString& Status);

    /** One line on HudLine for DurationS, queued behind the road's own HUD lines. */
    UFUNCTION(BlueprintCallable, Category = "Saskarta|Events")
    void ShowHudEvent(const FString& Text, float DurationS = 3.f);

    /** Types one line on the capsule CRT while the collapse's boot-log black is up. False (nothing typed) otherwise. */
    UFUNCTION(BlueprintCallable, Category = "Saskarta|Events")
    bool TypeCrtLog(const FString& Line);

    /** Plays a 2D sound effect by asset name under /Game/SaskartaGaea/Audio (a dead click, a tick). */
    UFUNCTION(BlueprintCallable, Category = "Saskarta|Events")
    void PlayNamedSfx(FName SfxId);

    /** A story line's sound (may load it) and its subtitle text and speaker; null when the line has no take. */
    USoundBase* ResolveLineSound(FName LineId, FString& OutText, FName& OutSpeaker);

    UFUNCTION(BlueprintPure, Category = "Saskarta|Events")
    USaskartaStoryAsset* GetStory() const { return Story; }

    /** Uses this data instead of DA_Saskarta_Story (tests, level overrides). */
    UFUNCTION(BlueprintCallable, Category = "Saskarta|Events")
    void SetStory(USaskartaStoryAsset* InStory);

    /** Multi-line state for Saskarta.Events.Dump. */
    FString DumpState() const;

    /** Logs a DryRun of the current data (Saskarta.Events.DryRun). */
    void LogDryRun(float SpeedMps, float EndRoadM) const;

    // ------------------------------------------------------------------ events for the UI and the station
    UPROPERTY(BlueprintAssignable, Category = "Saskarta|Events")
    FSaskartaStoryBusy OnStoryBusyChanged;

    UPROPERTY(BlueprintAssignable, Category = "Saskarta|Events")
    FSaskartaSubtitleShow OnSubtitleShow;

    UPROPERTY(BlueprintAssignable, Category = "Saskarta|Events")
    FSaskartaSubtitleHide OnSubtitleHide;

    UPROPERTY(BlueprintAssignable, Category = "Saskarta|Events")
    FSaskartaCaptionShow OnCaptionShow;

    UPROPERTY(BlueprintAssignable, Category = "Saskarta|Events")
    FSaskartaCaptionHide OnCaptionHide;

    UPROPERTY(BlueprintAssignable, Category = "Saskarta|Events")
    FSaskartaLetterbox OnLetterbox;

    UPROPERTY(BlueprintAssignable, Category = "Saskarta|Events")
    FSaskartaPromptShow OnPromptShow;

    UPROPERTY(BlueprintAssignable, Category = "Saskarta|Events")
    FSaskartaPromptHide OnPromptHide;

    /** 0..1 while the skip key is held; 0 when released or not skippable. */
    UPROPERTY(BlueprintAssignable, Category = "Saskarta|Events")
    FSaskartaSkipProgress OnSkipProgress;

    /** SetLook: also forwarded to the lighting director's PushLookOverride/PopLookOverride when those UFUNCTIONs exist. */
    UPROPERTY(BlueprintAssignable, Category = "Saskarta|Events")
    FSaskartaLookRequest OnLookRequested;

    /** SetFog: also forwarded to the director's PushFogOverride when it exists. */
    UPROPERTY(BlueprintAssignable, Category = "Saskarta|Events")
    FSaskartaFogRequest OnFogRequested;

    UPROPERTY(BlueprintAssignable, Category = "Saskarta|Events")
    FSaskartaModeChanged OnModeChanged;

    /** ShowEndCard (Title, Credits). */
    UPROPERTY(BlueprintAssignable, Category = "Saskarta|Events")
    FSaskartaNamedEvent OnEndCard;

    /** SetGeiger (the sample name). */
    UPROPERTY(BlueprintAssignable, Category = "Saskarta|Events")
    FSaskartaNamedEvent OnGeigerSample;

    UPROPERTY(BlueprintAssignable, Category = "Saskarta|Events")
    FSaskartaNamedEvent OnBeatStarted;

    /**
     * A story or carrier line starts on the Voice channel (not the cinematic lane), just before
     * OnStoryBusyChanged. BeatPriority is the running beat's (0 Critical .. 3 Hint), or 1 for a
     * cinematic's lines played as radio. The station classifies it (FSaskartaRadioFxLogic::ClassifyLine).
     */
    UPROPERTY(BlueprintAssignable, Category = "Saskarta|Events")
    FSaskartaStoryLine OnStoryLine;

    /** B02's end turns the station on (STATION.md section 1). */
    UPROPERTY(BlueprintAssignable, Category = "Saskarta|Events")
    FSaskartaNamedEvent OnBeatFinished;

    UPROPERTY(BlueprintAssignable, Category = "Saskarta|Events")
    FSaskartaNamedEvent OnCinematicStarted;

    UPROPERTY(BlueprintAssignable, Category = "Saskarta|Events")
    FSaskartaNamedEvent OnCinematicFinished;

    // ------------------------------------------------------------------ UWorldSubsystem
    virtual void Initialize(FSubsystemCollectionBase& Collection) override;
    virtual void Deinitialize() override;
    virtual void OnWorldBeginPlay(UWorld& InWorld) override;

protected:
    virtual bool DoesSupportWorldType(const EWorldType::Type WorldType) const override;

private:
    // --- clocks
    void PollRoad();
    void Step();
    void PollPrompt();
    void PollSkip();
    void GlanceTick();

    // --- queue and beats
    void EnqueueBeat(const FSaskartaBeatDef& Beat, bool bForce);
    void StartNextBeat();
    void RunActions();
    void FinishBeat();
    void AbortRunningBeat(bool bRequeueOnReboot);
    bool StartAction(const FSaskartaEventAction& Action, bool bInCinematic, double& OutCompleteAtS, ESaskartaRunWait& OutWait);

    // --- lines and subtitles
    float PlayLine(FName LineId, bool bCarrier, bool bCinematicLane);
    void ShowLineSubtitle(FName LineId, float DurationS);
    void HideStorySubtitle();
    void UpdateSubtitlePages();
    void UpdateVoiceBusy();

    // --- cinematics
    bool BeginCinematic(FName CinematicId);
    /** Watchdog (1 s): a cinematic phase that outlives its budget + FSaskartaEventLogic::CineWatchdogPadS is ended and input released. */
    void CineWatchdog();
    /** PIE end / world teardown: stop everything while the controller still exists, so no lock outlives the run. */
    void HandleWorldTearDown(UWorld* World);
    void StartSequence();
    void ClearParkedCarrierMotion(bool bStopMovement);
    FBox CarrierCameraBounds();
    void CinematicStep();
    float GetCinematicTimeS() const;
    UFUNCTION()
    void HandleSequenceFinished();
    void EndCinematic(bool bSkipped);
    void FinishBlendOut();
    AActor* ResolveCinematicHandback(const FSaskartaCinematicDef& Cinematic) const;
    void RunCue(const FSaskartaEventAction& Cue);
    void RunImmediate(const FSaskartaEventAction& Action);

    // --- glance / prompt
    void BeginGlance(FName GlanceId, const FSaskartaEventAction& Action);
    void EndGlance();
    void BeginPrompt(const FSaskartaEventAction& Action, bool bFromCue);
    void AnswerPrompt();

    // --- a prompt the player can always see and answer (SaskartaEventRunnerPrompt.cpp, SaskartaPromptLogic.h)
    void NotePromptShown(const FText& Text);
    void TickPromptReminder();
    void ReadPromptKeys(bool& bOutKeyboardDown, bool& bOutGamepadDown) const;
    /** BPC_CarrierVision on the PC (the component with ShowLogLine); bOutBlackUp while its BootLogWidget covers the screen. */
    class UActorComponent* FindCrtTerminal(bool& bOutBlackUp) const;
    bool TypeCrtLine(class UActorComponent* Terminal, const FString& Line) const;
    void ShowPromptOverlay(const FString& Line);
    void RemovePromptOverlay();
    UFUNCTION()
    void HandlePromptHidden();
    /** SpawnOrReveal "DL:<asset name or path>": activates the data layer instance of that UDataLayerAsset. */
    bool ActivateDataLayer(const FString& Ref);
    FText PromptText;
    double PromptShownS = 0.0;
    double PromptLastRemindS = -1.0;
    int32 PromptReminds = 0;
    TSharedPtr<class SWidget> PromptOverlay;
    TWeakObjectPtr<class UGameViewportClient> PromptOverlayViewport;
    UPROPERTY()
    TObjectPtr<UObject> PromptFont;

    // --- HUD queries (SaskartaHudQueryLogic.h): HudLine and the ?-column, outside the beat queue
    void RunHudAction(const FSaskartaEventAction& A, bool bFromCue);
    void PumpHud();
    void EmitHud(const TArray<FSaskartaHudOutput>& Out);
    void RebuildHudColumn();
    FSaskartaHudLane HudLane;
    FTimerHandle HudTimer;

    // --- world access
    APlayerController* GetPC() const;
    APawn* GetPawn() const;
    AActor* ResolveTarget(FName Tag) const;
    bool ResolveRoad();
    bool CallHook(AActor* Target, FName Function, const TArray<FName>& NameArgs, const TArray<float>& FloatArgs) const;
    void SetFlowStateByReflection(FName State);
    void LockInput(bool bMove, bool bLook);
    void UnlockInput();
    USoundBase* ResolveSound(FName Id, const TSoftObjectPtr<USoundBase>& Preferred);
    void PrefetchBeatSounds(const FSaskartaBeatDef& Beat);
    void PlaySfx(const FSaskartaEventAction& Action);
    /** StopSfx: the newest sound PlaySfx started under Id (a hard cut when FadeS <= 0). */
    void StopSfx(FName Id, float FadeS);
    void Reveal(FName Id);
    void BroadcastBusy(bool bBusy, float ExpectedS, bool bCinematic);
    void LoadProfile();
    void SaveProfile();
    bool RestoreHumanCheckpoint(const USaskartaSaveGame& Snapshot);
    void BeginHumanGroundingHold(ACharacter* Human, bool bExactPose);
    void PollHumanGrounding();
    void ClearHumanGroundingHold();
    void FailHumanGrounding(const TCHAR* Reason);
    void BeginCarrierGroundingHold(ACharacter* Carrier, bool bExactPose);
    void PollCarrierGrounding();
    void ClearCarrierGroundingHold();
    void FailCarrierGrounding(const TCHAR* Reason);
    bool TeleportToRoadM(float RoadM);
    double Now() const;

    // CP4 restores the pose first, but walking waits for destination collision.
    // These locks/source/fade belong only to this pending handoff, never to a menu.
    bool bHumanGroundingActive = false;
    bool bHumanGroundingExactPose = false;
    bool bHumanGroundingMoveLock = false;
    bool bHumanGroundingLookLock = false;
    bool bHumanGroundingFade = false;
    int32 HumanGroundingReadyPolls = 0;
    double HumanGroundingLastPollS = 0.0;
    double HumanGroundingActiveElapsedS = 0.0;
    FTransform HumanGroundingPose;
    TWeakObjectPtr<ACharacter> HumanGroundingPawn;
    TWeakObjectPtr<APlayerController> HumanGroundingController;
    UPROPERTY(Transient)
    TObjectPtr<UWorldPartitionStreamingSourceComponent> HumanGroundingSource;
    FTimerHandle HumanGroundingTimer;

    // Continue/retry keeps the restored carrier stopped until destination floor exists.
    bool bCarrierGroundingActive = false;
    bool bCarrierGroundingExactPose = false;
    bool bCarrierGroundingMoveLock = false;
    bool bCarrierGroundingLookLock = false;
    bool bCarrierGroundingFade = false;
    bool bCarrierGroundingMovementTick = false;
    int32 CarrierGroundingReadyPolls = 0;
    uint64 CarrierGroundingLastReadyFrame = MAX_uint64;
    double CarrierGroundingLastPollS = 0.0;
    double CarrierGroundingActiveElapsedS = 0.0;
    FTransform CarrierGroundingPose;
    TWeakObjectPtr<ACharacter> CarrierGroundingPawn;
    TWeakObjectPtr<APlayerController> CarrierGroundingController;
    UPROPERTY(Transient)
    TObjectPtr<UWorldPartitionStreamingSourceComponent> CarrierGroundingSource;
    FTimerHandle CarrierGroundingTimer;

    // --- data
    UPROPERTY()
    TObjectPtr<USaskartaStoryAsset> Story;

    TArray<FSaskartaQueuedBeat> Queue;
    int32 QueueSeq = 0;
    TSet<FName> FiredBeats;
    TSet<FName> SeenCinematics;
    TSet<FName> EnabledTags;
    TMap<FName, double> LastFiredS;
    bool bCompletedOnce = false;

    // --- running beat
    bool bHasRunning = false;
    FName RunningBeatId;
    ESaskartaEventPriority RunningPriority = ESaskartaEventPriority::Story;
    int32 RunningActionIndex = 0;
    bool bRunningDelayDone = false;
    double RunningBlockedUntilS = 0.0;
    ESaskartaRunWait RunningWait = ESaskartaRunWait::None;
    FName InterruptedBeatId;

    // --- voice
    UPROPERTY()
    TObjectPtr<UAudioComponent> VoiceComp;
    UPROPERTY()
    TObjectPtr<UAudioComponent> CineVoiceComp;
    double VoiceBusyUntilS = 0.0;
    double LineEndS = -1.0;
    double LastVoiceEndS = -1000.0;
    FName CurrentLineId;
    bool bStoryBusyBroadcast = false;
    bool bStationDuckMixPushed = false;
    bool bStorySubtitleActive = false;
    bool bStationSubtitleActive = false;
    double SubtitleHideAtS = -1.0;
    FSaskartaCaptionPager StorySubtitlePager;
    FSaskartaCaptionPager StationSubtitlePager;
    FSaskartaSubtitle StorySubtitleBase;
    FSaskartaSubtitle StationSubtitleBase;
    TArray<FName> PendingKeepLines;

    // --- cinematic
    ESaskartaCinePhase CinePhase = ESaskartaCinePhase::None;
    FName ActiveCineId;
    bool bCineFromBeat = false;
    UPROPERTY()
    TObjectPtr<ULevelSequencePlayer> CinePlayer;
    UPROPERTY()
    TObjectPtr<ALevelSequenceActor> CineActor;

    FTransform CineRoadFrame;
    FVector CineSensorOrigin = FVector::ZeroVector;
    bool bCineSensorOriginValid = false;
    bool bCineSensorFromDrone = false;
    bool bHaveSafeCineView = false;
    bool bReportedCineClearance = false;
    FVector LastSafeCineView = FVector::ZeroVector;
    TWeakObjectPtr<ACharacter> CameraCollisionCarrier;
    TSharedPtr<FSceneViewExtensionBase, ESPMode::ThreadSafe> CinematicViewGuard;
    int32 NextCue = 0;
    bool bCinePromptPending = false;
    bool bCinePromptAnswered = true;
    double CineStartS = 0.0;
    double CinePausedAtS = -1.0;
    double CinePausedTotalS = 0.0;
    double CinePhaseStartS = 0.0;
    bool bCineSkipped = false;
    bool bCineLetterboxOn = false;
    float SkipHeldS = 0.f;
    FTimerHandle CineWatchdogTimer;
    FDelegateHandle TearDownHandle;

    // --- glance / prompt / input
    TWeakObjectPtr<AActor> GlanceTarget;
    FRotator GlanceStartRot = FRotator::ZeroRotator;
    double GlanceStartS = 0.0;
    float GlanceEaseS = 1.5f;
    float GlanceHoldS = 2.f;
    bool bGlanceActive = false;
    bool bGlanceMoveLocked = false;
    bool bGlanceLookLocked = false;
    bool bPromptActive = false;
    bool bPromptFromCue = false;
    bool bPromptEWasDown = false;
    bool bPromptGamepadWasDown = false;
    FName PromptNextBeat;
    int32 MoveLocks = 0;
    int32 LookLocks = 0;

    // --- road
    TWeakObjectPtr<USplineComponent> RoadSpline;
    double LastRoadResolveS = -1000.0;
    float HighWaterUeM = TNumericLimits<float>::Max();
    float CurrentUeM = -1.f;
    float CurrentRoadM = -1.f;
    float SpeedMps = 0.f;
    bool bWarnedNoRoad = false;

    // --- reapplied state (saved)
    FName LastLook;
    float LastFog = 1.f;
    TArray<FName> Revealed;
    TSet<FName> ActiveModes;

    TMap<FName, FSoftObjectPath> SoundIndex;
    /** PlaySfx's sounds by Id (the newest), so StopSfx can cut the hut speaker, the hiss and the title track. */
    TMap<FName, TWeakObjectPtr<class UAudioComponent>> TrackedSfx;

    /** Perf: line sounds and sequences of the beats ahead are async-loaded (PrefetchAhead) and held here. */
    void PrefetchAhead();
    void PrefetchBeat(const struct FSaskartaBeatDef& Beat);
    FSoftObjectPath SoundPathFor(FName Id, const TSoftObjectPtr<USoundBase>& Preferred);
    TSet<FName> PrefetchedBeats;
    TArray<TSharedPtr<struct FStreamableHandle>> PrefetchHandles;
    bool bSoundIndexBuilt = false;
    TSet<FName> WarnedMissing;

    bool bStormPanicActive = false;
    double NextStormPanicS = 0.0;
    double LastStormPanicEndS = -1000.0;
    int32 StormPanicVariant[3] = { 0, 0, 0 };
    FName LastStormPanicLine;
    TSharedPtr<struct FStreamableHandle> StormPanicLoad;
    void StopStormPanicLine();

    FTimerHandle PollRoadTimer;
    FTimerHandle StepTimer;
    FTimerHandle PromptTimer;
    FTimerHandle SkipTimer;
    FTimerHandle GlanceTimer;
};
