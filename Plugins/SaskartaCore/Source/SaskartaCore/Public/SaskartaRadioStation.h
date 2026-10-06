// USaskartaRadioStation: the Low Voice scheduler at runtime (docs/story/STATION.md).
//
// A world subsystem (game and PIE). Every 0.25 s (a timer, no Tick) it works out the mode
// from PC_Saskarta.FlowState, the settings toggle and whether B02 has finished, advances
// station time, applies reception by road m, and runs the loop: tune sweep, a 20-40 s
// first delay, then segments and song blocks from FSaskartaStationScheduler separated by
// gaps. The story gate (the runner's IsVoiceBusy / SecondsSinceVoice / GetSecondsToNextBeat)
// is checked before every slot. It binds the runner's OnStoryBusyChanged: a story line
// ducks it -12 dB over 0.3 s then fades it over 1 s (not resumed); a cinematic suspends it
// (fade, clock paused) until 6 s after the cinematic.
//
// RADIOSHOW: with station.json scheduler.mode "show" (Config.Show.bShowMode) the loop asks the live show
// (FSaskartaShowScheduler, SaskartaShowScheduler.h; docs/story/RADIO_SHOW.md) instead of the shuffle bags:
// acts by road m, the ordered backbone with MUST / optional items, fills, linger pools, song slots with
// talk-over, the REACT_* layer fed by the game (lightning, dropouts, storm, story lines, silence, stops,
// the tether, POIs, the radio switch, the pause menu), the sign-off, the signal death, then the author's
// last song and the title song for the end card. The shuffle loop stays as the fallback.
//
// Assets load asynchronously only (FStreamableManager): DA_Station, the filter chain, the static sounds and a
// bounded prefetch window of the show's next items and the act's reactions. A take that is not loaded when it
// is due waits at most 1.5 s, then plays as a subtitle only; nothing is ever loaded synchronously here.
//
// Takes are picked up by name: <HostFolder>/Recorded/VO_Station_<id> (the user's
// recording) before <HostFolder>/VO_Station_<id> (the TTS placeholder), and a named link
// pickup VO_Station_<id>__<song_id> before the plain take. Songs are every SONG_<id> in
// SongFolder plus station.json's list. In editor builds it also reads
// Saved/RadioRecordings/selected/_tts_manifest.json and warns about user recordings on
// disk that are not imported under Recorded/ yet.

#pragma once

#include "CoreMinimal.h"
#include "Subsystems/WorldSubsystem.h"
#include "TimerManager.h"
#include "SaskartaStationLogic.h"
#include "SaskartaRadioFx.h"
#include "SaskartaShowScheduler.h"
#include "SaskartaSaveGame.h"
#include "SaskartaRadioStation.generated.h"

class UAudioComponent;
struct FStreamableHandle;
class USaskartaSaveGame;
class USaskartaEventRunner;
class USaskartaStationAsset;
class USoundBase;
class USoundWave;
class USoundEffectSubmixPreset;
class USoundSubmix;

DECLARE_DYNAMIC_MULTICAST_DELEGATE_OneParam(FSaskartaRadioForcedOn, FName, BeatId);
DECLARE_DYNAMIC_MULTICAST_DELEGATE_OneParam(FSaskartaRadioForcedOff, bool, bRadioOnAfter);
DECLARE_DYNAMIC_MULTICAST_DELEGATE_ThreeParams(FSaskartaRadioGlitchSignal, ESaskartaRadioGlitch, Type, float, DurationS, float, Intensity);
DECLARE_DYNAMIC_MULTICAST_DELEGATE_OneParam(FSaskartaShowEndSignal, FName, Phase);
/** Where the loop is (not reflected). */
enum class ESaskartaStationPhase : uint8 { Silent, TuningIn, Waiting, Playing };

UCLASS()
class SASKARTACORE_API USaskartaRadioStation : public UWorldSubsystem
{
    GENERATED_BODY()

public:
    UFUNCTION(BlueprintPure, Category = "Saskarta|Station", meta = (WorldContext = "WorldContextObject"))
    static USaskartaRadioStation* GetRadioStation(const UObject* WorldContextObject);

    /** Lower everything the station plays (talk, songs, hiss) under another voice, e.g. a pillar reading
     *  (the author: "spoken above the radio while the radio sound gets lowered a bit"). True fades to -8 dB over
     *  0.3 s; false fades back. */
    UFUNCTION(BlueprintCallable, Category = "Saskarta|Station")
    void SetUnderVoice(bool bUnder);

    /** The idle driver: true when the idle tape starts (the station yields), false when it has faded. */
    UFUNCTION(BlueprintCallable, Category = "Saskarta|Station")
    void NotifyIdle(bool bIdle);

    /** Forces the next slot now, skipping the gap (Saskarta.Station.Next). */
    UFUNCTION(BlueprintCallable, Category = "Saskarta|Station")
    void ForceNextSlot();

    /** Makes the song block due now (Saskarta.Station.Song). */
    UFUNCTION(BlueprintCallable, Category = "Saskarta|Station")
    void ForceSongBlock();

    /** Sets (and applies) the archive filter chain on the station submix. */
    UFUNCTION(BlueprintCallable, Category = "Saskarta|Station")
    void SetArchiveFilter(USoundSubmix* Submix, const TArray<USoundEffectSubmixPreset*>& Chain);

    UFUNCTION(BlueprintPure, Category = "Saskarta|Station")
    float GetReceptionQuality() const { return Quality; }

    /** Optional receiver repair: transient programme-only masking, never a radio setting or transport change. */
    void SetRepairReception(bool bActive, float Signal01);

    /** Measured current voice amplitude; zero for silence, songs, pauses and stale callbacks. */
    float GetProgrammeEnvelope() const;

    UFUNCTION(BlueprintPure, Category = "Saskarta|Station")
    double GetStationTimeS() const { return Scheduler.Clock.StationTimeS; }

    UFUNCTION(BlueprintPure, Category = "Saskarta|Station")
    bool IsAudible() const { return Phase == ESaskartaStationPhase::Playing; }

    // --- LANE5: the radio panel (WBP_Saskarta_Radio, README_Radio.md)
    /** The road zone the carrier is in (Asset Config.Zones), or None. */
    UFUNCTION(BlueprintPure, Category = "Saskarta|Station")
    FName GetCurrentZone() const { return Scheduler.CurrentZone; }

    /** The zone's panel label ("The dry cistern"), or empty. */
    UFUNCTION(BlueprintPure, Category = "Saskarta|Station")
    FText GetCurrentZoneLabel() const;

    /** What is on now: "Weather", "Letters", "(note) Hayaa", "Id"; empty between items. */
    UFUNCTION(BlueprintPure, Category = "Saskarta|Station")
    FText GetCurrentItemTitle() const;

    /** Uses this data instead of DA_Station. */
    UFUNCTION(BlueprintCallable, Category = "Saskarta|Station")
    void SetStationAsset(USaskartaStationAsset* InAsset);

    // --- CPPBATCH: the player's radio, story lines and imperfections (SaskartaRadioFx.h)
    /** The player's on/off choice (the saved "Radio station" setting, USaskartaStorySettings::bRadioStation). */
    UFUNCTION(BlueprintPure, Category = "Saskarta|Station")
    bool IsRadioOn() const;

    /** Sets and saves the player's on/off choice (R / D-pad up). A forced archive line still plays; the choice holds after it. */
    UFUNCTION(BlueprintCallable, Category = "Saskarta|Station")
    void SetRadioOn(bool bOn);

    /**
     * Replays one narrative show item or archive line once, with the programme ducked
     * and its subtitle shown. Returns its length (s); a line with no take shows its subtitle for its target
     * length. 0 when the item is unknown. A new recall stops the one playing.
     */
    UFUNCTION(BlueprintCallable, Category = "Saskarta|Station")
    float PlayRecall(FName ItemId, bool bTuneFirst = false);

    UFUNCTION(BlueprintCallable, Category = "Saskarta|Station")
    void StopRecall();

    UFUNCTION(BlueprintPure, Category = "Saskarta|Station")
    bool IsRecallPlaying() const { return RecallEndS >= 0.0; }

    /** Unused since ROUTE_BOARD_V3.md (limp never cuts the radio); kept for Blueprints. Mutes the player's radio without touching the saved
     * choice. Archive story lines still force through; the choice returns when the cut is released. */
    UFUNCTION(BlueprintCallable, Category = "Saskarta|Station")
    void SetRadioPowerCut(bool bCut) { bRadioPowerCut = bCut; }

    UFUNCTION(BlueprintPure, Category = "Saskarta|Station")
    bool IsRadioPowerCut() const { return bRadioPowerCut; }

    /** True while an archive line forces the radio audible (the panel shows INCOMING ARCHIVE). */
    UFUNCTION(BlueprintPure, Category = "Saskarta|Station")
    bool IsRadioForcedOn() const { return StoryState.bForced; }

    /** The player's choice or a forced archive line: what the panel should show as ON. */
    UFUNCTION(BlueprintPure, Category = "Saskarta|Station")
    bool IsRadioEffectivelyOn() const { return (IsRadioOn() && !bRadioPowerCut) || IsRadioForcedOn(); }

    /** The beat whose archive line forces the radio on, or None. */
    UFUNCTION(BlueprintPure, Category = "Saskarta|Station")
    FName GetForcedBeat() const { return StoryState.ForcedBeat; }

    /** Storm intensity the imperfections use: StormIntensityInput when >= 0, else the lighting director's. */
    UFUNCTION(BlueprintPure, Category = "Saskarta|Station")
    float GetStormIntensityForRadio() const;

    /** An archive line forces the radio audible (the player's radio may be off). */
    UPROPERTY(BlueprintAssignable, Category = "Saskarta|Station")
    FSaskartaRadioForcedOn OnRadioForcedOn;

    /** The force ended, ForceReleaseHoldS after the line; bRadioOnAfter is the player's own choice, now back in charge. */
    UPROPERTY(BlueprintAssignable, Category = "Saskarta|Station")
    FSaskartaRadioForcedOff OnRadioForcedOff;

    /** Every imperfection as it happens (RADIOFX one-shots, submix parameters). Dropouts, jitter, drift and bursts are also applied here. */
    UPROPERTY(BlueprintAssignable, Category = "Saskarta|Station")
    FSaskartaRadioGlitchSignal OnRadioGlitch;

    /** Imperfection tuning. */
    UPROPERTY(BlueprintReadWrite, Category = "Saskarta|Station")
    FSaskartaRadioGlitchParams GlitchParams;

    /** 0-1 storm input for the imperfections; negative = the lighting director's effective storm intensity. */
    UPROPERTY(BlueprintReadWrite, Category = "Saskarta|Station")
    float StormIntensityInput = -1.f;

    // --- RADIOSHOW: the live show (SaskartaShowScheduler.h, README_Radio.md)
    /** True when station.json runs the show (scheduler.mode "show"), false for the shuffle fallback. */
    UFUNCTION(BlueprintPure, Category = "Saskarta|Station|Show")
    bool IsShowMode() const { return bShowMode; }

    /** The show's act (1-5), 0 before it starts. */
    UFUNCTION(BlueprintPure, Category = "Saskarta|Station|Show")
    int32 GetShowAct() const { return Show.GetAct(); }

    /** The tether warning (where the tether Blueprint plays CV_WARN_01): the OFFROAD reaction. */
    UFUNCTION(BlueprintCallable, Category = "Saskarta|Station|Show")
    void NotifyOffroad();

    /** The pause menu: true on open, false on close. Pauses every station sound; a close after >= 15 s may bring a RESUMED reaction. */
    UFUNCTION(BlueprintCallable, Category = "Saskarta|Station|Show")
    void NotifyPaused(bool bPaused);

    /** Optional: a ruin's zone reached (an event volume). POIs also fire by road m on their own. */
    UFUNCTION(BlueprintCallable, Category = "Saskarta|Station|Show")
    void NotifyPassingPoi(FName Zone);

    /** Fires a reaction event by name (LIGHTNING, DROPOUT, STORM_UP, AFTER_TAPE, SILENCE, STOPPED, OFFROAD, PASSING_POI, RADIO_BACK_ON, RESUMED); debug and Blueprint. */
    UFUNCTION(BlueprintCallable, Category = "Saskarta|Station|Show")
    bool FireShowEvent(FName Event, bool bClose = false);

    /** The show state for the run checkpoint (the runner writes it through USaskartaSaveGame::OnWritingRun). */
    UFUNCTION(BlueprintPure, Category = "Saskarta|Station|Show")
    FSaskartaShowSaveState GetShowSaveState() const;

    /** Restores the show on Continue (the runner's RestoreFromSave broadcasts USaskartaSaveGame::OnRestoredRun). */
    UFUNCTION(BlueprintCallable, Category = "Saskarta|Station|Show")
    void ApplyShowSaveState(const FSaskartaShowSaveState& State);

    /** Starts the title song transition now (the end card may call it; the show calls it itself after the last song). */
    UFUNCTION(BlueprintCallable, Category = "Saskarta|Station|Show")
    void StartTitleSongTransition();

    /** Retains one title-track cursor through collapse, the human walk, transmission and credits. */
    void SetEndingMusicFlow(FName State);

    /** Fades the last song and the title song out (the end of the credits, quit to title). */
    UFUNCTION(BlueprintCallable, Category = "Saskarta|Station|Show")
    void StopEndMusic(float FadeS = 2.f);

    UFUNCTION(BlueprintPure, Category = "Saskarta|Station|Show")
    bool IsSignalDead() const { return bSignalDeath; }

    /** The end of the show: SignalDeath (after the last line), LastSong, TitleSong. */
    UPROPERTY(BlueprintAssignable, Category = "Saskarta|Station|Show")
    FSaskartaShowEndSignal OnShowEnd;


    USaskartaStationAsset* GetStationAsset() const { return Asset; }
    const FSaskartaShowScheduler& GetShowScheduler() const { return Show; }

    FString DescribeState() const;

    // ------------------------------------------------------------------ UWorldSubsystem
    virtual void Initialize(FSubsystemCollectionBase& Collection) override;
    virtual void Deinitialize() override;
    virtual void OnWorldBeginPlay(UWorld& InWorld) override;

protected:
    virtual bool DoesSupportWorldType(const EWorldType::Type WorldType) const override;

private:
    void Update();
    void BindRunner();
    UFUNCTION()
    void HandleStoryBusy(bool bBusy, float ExpectedS, bool bCinematic);
    UFUNCTION()
    void HandleBeatFinished(FName BeatId);

    /** LANE5: storm lightning -> a static burst and a forced dropout. */
    UFUNCTION()
    void HandleLightning(float DistanceM, bool bClose);

    /** CPPBATCH: a story line starts (archive: force on + tune-over cut; carrier: -6 dB duck). */
    UFUNCTION()
    void HandleStoryLine(FName LineId, FName BeatId, bool bCarrier, int32 BeatPriority, float DurationS);

    /** Cuts the current item for an archive line with the tune-over; a song is kept to resume. */
    void CutForStoryLine(bool bKeepSong);
    /** After a story line: the interrupted song from its position, or the next item (a new segment). */
    void ResumeProgramme(bool bResumeSong);
    void ApplyStoryStep(const FSaskartaRadioStoryStep& Step);
    void UpdateGlitches(double NowS);
    bool IsBoostInterferenceEligible() const;
    void UpdateBoostInterference(double NowS);
    void EndBoostInterferencePulse();
    void ApplyGlitch(const FSaskartaRadioGlitchEvent& Glitch, bool bArchiveLine);
    float CurrentQuality() const;

    void TuneIn();
    void TryStartSlot();
    void StartPart(int32 PartIndex, float StartAtS = 0.f);
    void FinishSlot();
    void InterruptSlot(bool bDuckFirst, bool bResumeSongAfterStory = false);
    void FadeOutAll(float FadeS, bool bIncludeBed);
    void ApplyReception();
    void HandleProgrammeEnvelope(const UAudioComponent* Component, const USoundWave* Wave, float Envelope);
    void MaybeDropout();
    void ScanAvailability();
    void CheckRecordingsOnDisk() const;

    float VoiceLength(int32 SegmentIndex, FName SongId);
    float SongLength(FName SongId);
    bool AssetExists(const FString& ObjectPath) const;

    // --- RADIOSHOW: asynchronous loading (no synchronous load anywhere at runtime)
    /** DA_Station: in memory, else an async request (else, in the editor, a transient import of station.json). */
    void BeginStationAssetLoad();
    /** After the data arrives: the scheduler, the filter chain and the static sounds (all async). */
    void OnStationAssetReady();
    void ApplyArchiveFilterWhenLoaded();
    /** The take asset path for a line (the user's recording first), or empty when none exists. */
    FString ResolveTakePath(int32 SegmentIndex, FName SongId) const;
    FString ResolveSongPath(FName SongId) const;
    /** The last song's object path (show.last_song), or empty. */
    FString ResolveLastSongPath() const;
    /** The sound if it is loaded (or already in memory); otherwise requests it and returns nullptr. Never blocks. */
    USoundBase* GetResidentSound(const FString& ObjectPath, bool bRequestIfMissing = true);
    USoundBase* GetResidentSoundAt(const FSoftObjectPath& Path) { return Path.IsNull() ? nullptr : GetResidentSound(Path.ToString()); }
    void RequestLoad(const FString& ObjectPath, bool bHighPriority);
    void ReleaseLoad(const FString& ObjectPath);
    /** Every second: the show's window and the act's reactions are kept loaded; the rest is released. */
    void UpdatePrefetch(bool bForce = false);
    void PickPaths(const FSaskartaStationPick& Pick, TArray<FString>& Out) const;

    // --- RADIOSHOW: the show
    FSaskartaShowInput MakeShowInput(bool bGateOpen, float MaxFitS) const;
    void TryStartShowItem();
    void UpdateShowEvents(double NowS);
    double ShowNow() const { return Scheduler.Clock.StationTimeS; }
    /** Heard fraction of the current part (0-1). */
    float HeardFraction() const;
    /** A show pick was cut: return it to the scheduler (a song block past its intro counts as played). */
    void ReturnShowPick();
    void BeginSignalDeath();
    void StartLastSong();
    void RefreshEndingMusicVolume();
    void HandleWritingRun(UWorld* World, USaskartaSaveGame* Save);
    void HandleRestoredRun(UWorld* World, USaskartaSaveGame* Save);
    void StopComp(UAudioComponent* Comp, float FadeS);
    FString CaptionFor(const FSaskartaStationPart& Part) const;
    double Now() const;

    UPROPERTY()
    TObjectPtr<USaskartaStationAsset> Asset;

    UPROPERTY()
    TObjectPtr<UAudioComponent> PartComp;

    UPROPERTY()
    TObjectPtr<UAudioComponent> BedComp;

    /** RADIOSHOW: the previous part finishing under the next (an intro under its song, a song's tail under its outro). */
    UPROPERTY()
    TObjectPtr<UAudioComponent> TailComp;

    /** RADIOSHOW: the author's last song, and the title song (eyetae) for the end card. */
    UPROPERTY()
    TObjectPtr<UAudioComponent> CodaComp;

    UPROPERTY()
    TObjectPtr<UAudioComponent> TitleComp;

    /** A transient looping wrapper; the imported title recording is never modified. */
    UPROPERTY()
    TObjectPtr<USoundBase> EndingTitleLoop;

    /** Explicit narrative replay (PlayRecall). */
    UPROPERTY()
    TObjectPtr<UAudioComponent> RecallComp;
    double RecallEndS = -1.0;
    FTimerHandle RecallTimer;

    // SetUnderVoice: the ramp and each component's own multiplier before the duck.
    void StepUnderVoice();
    float UnderTarget = 1.f;
    float UnderNow = 1.f;
    TMap<TWeakObjectPtr<UAudioComponent>, float> UnderBase;
    FTimerHandle UnderTimer;

    TWeakObjectPtr<USaskartaEventRunner> Runner;

    FSaskartaStationScheduler Scheduler;
    FSaskartaStationPick CurrentPick;
    int32 CurrentPart = INDEX_NONE;
    double PartStartS = 0.0;
    double PartEndS = 0.0;
    double NextActionAtS = 0.0;
    double LastUpdateS = -1.0;
    double NextDropoutAtS = -1.0;
    double DropoutEndS = -1.0;
    // Separate schedule: boost never draws from the programme's random stream.
    double NextBoostInterferenceS = -1.0;
    double BoostPulseUntilS = -1.0;
    int32 BoostPulseIndex = 0;
    FTimerHandle BoostPulseTimer;

    ESaskartaStationPhase Phase = ESaskartaStationPhase::Silent;
    ESaskartaStationMode Mode = ESaskartaStationMode::Off;
    bool bStarted = false;
    bool bStoppedForGood = false;
    bool bSuspended = false;
    bool bRadioPowerCut = false;
    double SuspendRemainingS = 0.0;
    bool bIdle = false;
    bool bDucked = false;
    float Quality = 1.f;
    bool bRepairReception = false;
    float RepairSignal = 1.f;
    float ProgrammeEnvelope = 0.f;
    double ProgrammeEnvelopeAtS = -1.0;
    float LastVolumeSetting = -1.f;
    bool bLoggedNoTakes = false;

    TArray<FName> AvailableSongs;
    mutable TMap<FString, bool> ExistsCache;
    double LastScanS = -1000.0;

    FTimerHandle UpdateTimer;
    FTimerHandle DuckFadeTimer;

    // --- CPPBATCH
    FSaskartaRadioStoryState StoryState;
    /** The story line of this busy period was classified by HandleStoryLine (the busy handler then does not duck-and-fade). */
    bool bStoryLineInfo = false;
    /** The station waits for the story (an archive cut) before it may start anything. */
    bool bHeldForStory = false;
    FSaskartaStationPick InterruptedPick;
    int32 InterruptedPart = INDEX_NONE;
    float InterruptedSongPosS = 0.f;
    double NextGlitchAtS = -1.0;
    bool bGlitchScheduleArchive = false;
    FTimerHandle PitchRestoreTimer;

    // --- RADIOSHOW
    FSaskartaShowScheduler Show;
    bool bShowMode = false;
    FSaskartaShowPick CurrentShowPick;
    FSaskartaShowPick InterruptedShowPick;
    /** A part whose sound is still loading: it starts when loaded, or as a subtitle at the deadline. */
    bool bPartWaitingLoad = false;
    double PartLoadDeadlineS = 0.0;
    float PendingStartAtS = 0.f;
    /** Lines already reported as subtitle-only (no take, or not loaded in time). */
    TSet<FName> SubtitleOnlyLogged;
    /** The story line of the busy period (for AFTER_TAPE). */
    FName LastStoryBeat;
    ESaskartaRadioLineKind LastStoryKind = ESaskartaRadioLineKind::None;
    /** STORM_UP: storm samples over the last 20 s (time, value). */
    TArray<FVector2D> StormSamples;
    double LastStormSampleS = -1.0;
    /** SILENCE: when the station last went quiet, and whether the reaction fired for this silence. */
    double QuietSinceS = -1.0;
    bool bSilenceFired = false;
    /** RADIO_BACK_ON */
    double RadioOffAtS = -1.0;
    /** The pause menu. */
    bool bMenuPaused = false;
    double PauseStartRealS = 0.0;
    double PauseStartWorldS = 0.0;
    /** The show's end: after the last line nothing else plays. */
    bool bSignalDeath = false;
    /** Explicit stop ownership, cleared only for a new ending or checkpoint restore. */
    bool bEndMusicStopped = false;
    FName EndingMusicFlow;
    TSharedPtr<FStreamableHandle> EndingTitleLoad;
    FTimerHandle SongRiseTimer;
    FTimerHandle CodaTimer;
    FTimerHandle TitleTimer;
    /** A Continue that arrived before DA_Station. */
    bool bHasPendingShowState = false;
    FSaskartaShowSaveState PendingShowState;
    FDelegateHandle WritingRunHandle;
    FDelegateHandle RestoredRunHandle;

    // --- RADIOSHOW: loading
    TMap<FString, TSharedPtr<FStreamableHandle>> Loads;
    FSaskartaPrefetchPlanner Prefetch;
    TSet<FString> PinnedPaths;
    double LastPrefetchS = -1000.0;
    TSharedPtr<FStreamableHandle> StationAssetHandle;
    TSharedPtr<FStreamableHandle> FilterHandle;
    bool bWaitingForStationAsset = false;
};
