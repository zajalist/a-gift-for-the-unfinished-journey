// USaskartaAmbienceDirector: the Ambience 2 road ambience and the carrier's Geiger counter.
//
// Brief: .superpowers/sdd/2026-09-26-saskarta-world-sprint/task-AMBIENCE2-brief.md (sections 1-6).
// Editor steps: Tools/GameFlow/specs/README_Ambience.md.
//
// A world subsystem (game and PIE). No Tick: one 0.5 s timer reads the event runner's road
// metre, the lighting director's storm intensity and PC_Saskarta.FlowState, and
//   - crossfades the zone beds by road metre (sin^2/cos^2 over 120-150 m, DA_Ambience zones);
//   - crossfades the three storm wind beds by storm intensity (x the zone's wind multiplier),
//     with the grit beds (sand hiss x I^2, sand on metal x max(0, I-0.5) x 2);
//   - runs the per-zone and local one-shot pools (random interval, no-repeat bag, +-3 % pitch,
//     +-2 dB, 2D / around the carrier / at a spot emitter, one stinger per 4 s);
//   - activates the spot emitters by proximity (placed AmbientSounds tagged with the spot label,
//     else its own 3D components at the manifest positions);
//   - streams the current and next zone's sounds in asynchronously and releases the far ones.
// Its own timers: the storm gusts (lerp(90, 20, I) s +- 30 %, none under I 0.15; a gust one-shot,
// a sand spray, a dose spike, the metal/cloth pools), the thunder (OnLightningStrike + distance/343 s,
// never in Act I), and the Geiger's Poisson click timer.
//
// Mix: every voice goes through a -8 dB story duck (0.3 s in, 1.5 s out) while a story or
// carrier line is busy (OnStoryBusyChanged) or the radio forces an archive line on; the Geiger
// takes a further -2 dB. With SMX_Ambience in DA_Ambience the duck moves the submix output, else
// each voice's volume. At most MaxVoices (22) play, less ReservedExternalVoices for the old
// AmbientSounds; the lowest priority is culled.
//
// Geiger: Dose (counts/s) = the DA's dose-by-road table x the zone washout x the strongest live
// spike (gust x2.5 capped at 60, dust wall x1.8, close lightning x3; each decays with a 3 s time
// constant). Clicks fire at a Poisson rate clamped to 1-80/s (2D, panned toward the dashboard),
// crossfading into the 80 cps loop above 30-50 cps. SwitchOn at the carrier boot (FlowState
// Playing) and the human handover (Human), SwitchOff on Collapsing. An alarm chirp when the dose
// rises through 6 cps (20 s cooldown).

#pragma once

#include "CoreMinimal.h"
#include "Subsystems/WorldSubsystem.h"
#include "Math/RandomStream.h"
#include "TimerManager.h"
#include "SaskartaAmbienceLogic.h"
#include "SaskartaAmbienceDirector.generated.h"

class APawn;
class UAudioComponent;
class USaskartaAmbienceAsset;
class USoundBase;
class USoundClass;
class USoundSubmix;
struct FStreamableHandle;

DECLARE_DYNAMIC_MULTICAST_DELEGATE_TwoParams(FSaskartaDoseSpikeSignal, float, Dose, FName, Cause);
DECLARE_DYNAMIC_MULTICAST_DELEGATE_TwoParams(FSaskartaGustSignal, float, Intensity, float, DurationS);

UCLASS()
class SASKARTACORE_API USaskartaAmbienceDirector : public UWorldSubsystem
{
    GENERATED_BODY()

public:
    static constexpr float UpdateIntervalS = 0.5f;
    static constexpr float BedFadeS = 2.f;
    static constexpr float BedStopAfterSilentS = 5.f;

    UFUNCTION(BlueprintPure, Category = "Saskarta|Ambience", meta = (WorldContext = "WorldContextObject"))
    static USaskartaAmbienceDirector* GetAmbienceDirector(const UObject* WorldContextObject);

    // ------------------------------------------------------------------ Geiger (BP / HUD)
    /** The current dose, counts per second (road table x zone x spikes). */
    UFUNCTION(BlueprintPure, Category = "Saskarta|Ambience|Geiger")
    float GetDose() const { return Dose; }

    /** The road table's dose alone (no spikes). */
    UFUNCTION(BlueprintPure, Category = "Saskarta|Ambience|Geiger")
    float GetRoadDose() const { return RoadDose; }

    /** True while the counter is switched on (flow) - it may still be muted by the Geiger setting. */
    UFUNCTION(BlueprintPure, Category = "Saskarta|Ambience|Geiger")
    bool IsGeigerPowered() const { return bGeigerPowered; }

    /** Switches the counter on or off (the flow does it by itself; this is for scripts and the console). */
    UFUNCTION(BlueprintCallable, Category = "Saskarta|Ambience|Geiger")
    void SetGeigerPowered(bool bOn, bool bPlaySwitch = true);

    /** A dose spike starts (Cause: Gust, DustWall, Lightning). */
    UPROPERTY(BlueprintAssignable, Category = "Saskarta|Ambience|Geiger")
    FSaskartaDoseSpikeSignal OnDoseSpike;

    // ------------------------------------------------------------------ ambience state
    UFUNCTION(BlueprintPure, Category = "Saskarta|Ambience")
    FName GetCurrentZone() const;

    UFUNCTION(BlueprintPure, Category = "Saskarta|Ambience")
    float GetRoadM() const { return RoadM; }

    UFUNCTION(BlueprintPure, Category = "Saskarta|Ambience")
    float GetStormIntensity() const { return Storm; }

    UFUNCTION(BlueprintPure, Category = "Saskarta|Ambience")
    int32 GetActiveVoiceCount() const;

    UFUNCTION(BlueprintPure, Category = "Saskarta|Ambience")
    bool IsDucked() const { return bDuckWanted; }

    /** A storm gust starts (the fog pulse can follow it). */
    UPROPERTY(BlueprintAssignable, Category = "Saskarta|Ambience")
    FSaskartaGustSignal OnGust;

    /** Uses this data instead of DA_Ambience (tests, level overrides). */
    UFUNCTION(BlueprintCallable, Category = "Saskarta|Ambience")
    void SetAmbienceAsset(USaskartaAmbienceAsset* InAsset);

    /** Pins the road metre (debug); negative releases it to the event runner. */
    UFUNCTION(BlueprintCallable, Category = "Saskarta|Ambience")
    void SetRoadOverride(float InRoadM) { RoadOverrideM = InRoadM; }

    /** Pins the storm intensity (debug); negative releases it to the lighting director. */
    UFUNCTION(BlueprintCallable, Category = "Saskarta|Ambience")
    void SetStormOverride(float Intensity) { StormOverride = Intensity; }

    /** Fires a gust now (debug, Saskarta.Ambience.Gust). */
    UFUNCTION(BlueprintCallable, Category = "Saskarta|Ambience")
    void TriggerGust();

    /** Multi-line state for Saskarta.Ambience.Dump. */
    FString DumpState() const;

    // ------------------------------------------------------------------ tuning
    /** WATER OPTION (brief section 3): the Waiting Water / Heron Pools water emitters and pools. Off by default (B05, V4). */
    UPROPERTY(BlueprintReadWrite, Category = "Saskarta|Ambience")
    bool bWaitingWaterHasWater = false;

    UPROPERTY(BlueprintReadWrite, Category = "Saskarta|Ambience")
    int32 MaxVoices = 22;

    /** Voices of the old AmbientSounds still audible (rumble, far thunder, GEI_* bed), kept out of the director's share. */
    UPROPERTY(BlueprintReadWrite, Category = "Saskarta|Ambience")
    int32 ReservedExternalVoices = 3;

    UPROPERTY(BlueprintReadWrite, Category = "Saskarta|Ambience")
    float DuckDb = -8.f;

    UPROPERTY(BlueprintReadWrite, Category = "Saskarta|Ambience")
    float DuckAttackS = 0.3f;

    UPROPERTY(BlueprintReadWrite, Category = "Saskarta|Ambience")
    float DuckReleaseS = 1.5f;

    /** One pool stinger at most every StingerSpacingS (covers the 1.5 s pool spacing). */
    UPROPERTY(BlueprintReadWrite, Category = "Saskarta|Ambience")
    float StingerSpacingS = 4.f;

    /** No thunder below this road metre (RADIO_SHOW.md: Act I, the valley to 1,000 m, has no lightning). */
    UPROPERTY(BlueprintReadWrite, Category = "Saskarta|Ambience")
    float ActIEndRoadM = 1000.f;

    /** The director plays the Ambience 2 thunder and silences the lighting director's own (brief option B). */
    UPROPERTY(BlueprintReadWrite, Category = "Saskarta|Ambience")
    bool bPlayThunder = true;

    /** The beat whose start stops Above_Wind (the chorus thins into wind). */
    UPROPERTY(BlueprintReadWrite, Category = "Saskarta|Ambience")
    FName FinalBeatId = TEXT("B24");

    UPROPERTY(BlueprintReadWrite, Category = "Saskarta|Ambience|Geiger")
    float GeigerLevelDb = -6.f;

    UPROPERTY(BlueprintReadWrite, Category = "Saskarta|Ambience|Geiger")
    float GeigerExtraDuckDb = -2.f;

    /** -1 left .. 1 right: the dashboard side. */
    UPROPERTY(BlueprintReadWrite, Category = "Saskarta|Ambience|Geiger")
    float GeigerPan = -0.35f;

    /** The Poisson rate floor. 0.3 cps (the brief's table): near silence above the clouds. The logic's
        default (FSaskartaAmbienceLogic::MinClickRateCps) stays the task's 1/s. */
    UPROPERTY(BlueprintReadWrite, Category = "Saskarta|Ambience|Geiger")
    float MinClickRateCps = 0.3f;

    UPROPERTY(BlueprintReadWrite, Category = "Saskarta|Ambience|Geiger")
    float ChirpThresholdCps = 6.f;

    UPROPERTY(BlueprintReadWrite, Category = "Saskarta|Ambience|Geiger")
    float ChirpCooldownS = 20.f;

    UPROPERTY(BlueprintReadWrite, Category = "Saskarta|Ambience|Geiger")
    float ChirpVolumeDb = -12.f;

    UPROPERTY(BlueprintReadWrite, Category = "Saskarta|Ambience|Geiger")
    float SwitchVolumeDb = -8.f;

    // ------------------------------------------------------------------ UWorldSubsystem
    virtual void Initialize(FSubsystemCollectionBase& Collection) override;
    virtual void Deinitialize() override;
    virtual void OnWorldBeginPlay(UWorld& InWorld) override;

protected:
    virtual bool DoesSupportWorldType(const EWorldType::Type WorldType) const override;

private:
    // --- one voice the director plays (bed, spot, one-shot or Geiger)
    struct FVoice
    {
        TWeakObjectPtr<UAudioComponent> Comp;
        float Priority = 0.f;
        /** The voice's own gain (dB, random variation) on its VolumeMultiplier; the mix gain multiplies it. */
        float BaseVolume = 1.f;
        double StartS = 0.0;
        bool bGeiger = false;
        /** Beds, spots and the Geiger's components stay; one-shots are dropped when they end. */
        bool bPersistent = false;
    };

    struct FBedState
    {
        TWeakObjectPtr<UAudioComponent> Comp;
        TSoftObjectPtr<USoundBase> Sound;
        float Priority = 70.f;
        float Target = 0.f;
        double SilentSinceS = -1.0;
        bool bPlaying = false;
    };

    struct FPoolState
    {
        double NextFireS = -1.0;
        FSaskartaAmbienceBag Bag;
        bool bStopped = false;
    };

    struct FSpotState
    {
        TWeakObjectPtr<UAudioComponent> Comp;
        bool bPlaced = false;
        bool bActive = false;
    };

    /** What one update sees. */
    struct FAmbienceFrame
    {
        double NowS = 0.0;
        FVector Listener = FVector::ZeroVector;
        FVector Carrier = FVector::ZeroVector;
        FVector Travel = FVector::ForwardVector;
        bool bHasListener = false;
    };

    // --- clocks
    void Update();
    void ScheduleGust();
    void OnGustTimer();
    void OnClickTimer();
    void ArmClickTimer();
    void OnDuckTimer();

    // --- delegates
    UFUNCTION()
    void HandleStoryBusy(bool bBusy, float ExpectedS, bool bCinematic);
    UFUNCTION()
    void HandleRadioForcedOn(FName BeatId);
    UFUNCTION()
    void HandleRadioForcedOff(bool bRadioOnAfter);
    UFUNCTION()
    void HandleLightning(float DistanceM, bool bClose);
    UFUNCTION()
    void HandleBeatStarted(FName BeatId);
    void BindSources();
    void UnbindSources();

    // --- data and loading
    void RequestAsset();
    void OnAssetReady();
    void RebuildIndex();
    void UpdateStreaming(int32 Dominant);

    // --- parts of Update
    bool ReadFrame(FAmbienceFrame& Out) const;
    void UpdateFlow(FName Flow);
    void UpdateDose(const FAmbienceFrame& F);
    void UpdateGeigerLoops();
    void UpdateStormBeds();
    void UpdateZoneBeds();
    void UpdateSpots(const FAmbienceFrame& F);
    void UpdatePools(const FAmbienceFrame& F);
    void PruneVoices(double NowS);

    // --- pools
    bool IsPoolActive(int32 PoolIndex, const FAmbienceFrame& F, FVector* OutEmitter, float* OutInnerM, float* OutFalloffM) const;
    bool FirePool(int32 PoolIndex, const FAmbienceFrame& F, float ExtraDb, bool bIgnoreCap);
    bool FirePoolByName(FName Pool, float VolumeDbOverride, bool bUseOverride, float RandomDb);
    USoundBase* PickFromPool(int32 PoolIndex);

    // --- voices
    /** A stopped component: 2D, 3D at Location (natural-sound falloff, air absorption), or the panned Geiger on the camera. */
    UAudioComponent* CreateVoice(USoundBase* Sound, const FVector* Location, float InnerM, float FalloffM, bool bGeiger);
    /** Registers Comp under the budget; false (and nothing kept) when a higher voice holds the last slot. */
    bool AdmitVoice(UAudioComponent* Comp, float Priority, float BaseVolume, bool bGeiger, bool bPersistent);
    UAudioComponent* PlayOneShot(USoundBase* Sound, const FVector* Location, float VolumeDb, float Priority,
        float InnerM, float FalloffM, float PitchJitter, float DbJitter);
    void ApplyVoiceVolume(const FVoice& V) const;
    void ApplyMixToAll();
    float MixGain(bool bGeiger) const;
    /** A looping 2D bed toward Target (2 s), started when audible and loaded, stopped after 5 s at 0. */
    void SetBedTarget(FName Key, const TSoftObjectPtr<USoundBase>& Sound, float Target, float Priority, double NowS, bool bGeiger, float BaseVolume);
    void StopVoiceComp(UAudioComponent* Comp, float FadeS);

    // --- Geiger
    void AddSpike(FName Cause, float Multiplier, float HoldS, float CapCps);
    void EnsureGeigerComps();
    void PlayGeigerOneShot(const TSoftObjectPtr<USoundBase>& Sound, float VolumeDb);
    bool GeigerAudible() const;

    // --- mix
    void SetDuck(bool bDuck);

    double Now() const;
    APawn* GetCarrier() const;

    // ------------------------------------------------------------------ state
    UPROPERTY()
    TObjectPtr<USaskartaAmbienceAsset> Asset;

    /** Keeps every component the director made alive (GC). */
    UPROPERTY()
    TArray<TObjectPtr<UAudioComponent>> OwnedComps;

    TSharedPtr<FStreamableHandle> AssetHandle;
    TSharedPtr<FStreamableHandle> CoreHandle;
    TMap<int32, TSharedPtr<FStreamableHandle>> ZoneHandles;
    TArray<TArray<FSoftObjectPath>> ZonePaths;

    TArray<FVoice> Voices;
    TMap<FName, FBedState> Beds;
    TArray<FPoolState> PoolStates;
    TArray<FSpotState> SpotStates;
    TArray<float> ZoneW;
    int32 DominantZone = INDEX_NONE;

    float RoadM = 0.f;
    float RoadOverrideM = -1.f;
    float Storm = 0.f;
    float StormOverride = -1.f;
    FName LastFlow;
    bool bCollapsed = false;
    bool bHuman = false;
    bool bFinalBeat = false;

    // gusts
    FTimerHandle GustTimer;
    double GustEndS = -1000.0;

    // pools
    double LastStingerS = -1000.0;

    // Geiger
    float Dose = 0.f;
    float RoadDose = 0.f;
    float PrevDose = 0.f;
    TArray<FSaskartaDoseSpike> Spikes;
    bool bGeigerPowered = false;
    bool bGeigerSettingOn = true;
    double LastChirpS = -1000.0;
    float ArmedRate = 0.f;
    FTimerHandle ClickTimer;
    TWeakObjectPtr<UAudioComponent> ClickComps[2];
    int32 NextClickComp = 0;
    FSaskartaAmbienceBag ClickBag;
    FSaskartaAmbienceBag ChirpBag;
    TArray<TWeakObjectPtr<UAudioComponent>> GeigerLoopComps;

    // mix
    bool bStoryBusy = false;
    bool bRadioForced = false;
    bool bDuckWanted = false;
    /** 0 = open, 1 = fully ducked. */
    float DuckAmount = 0.f;
    float DuckFrom = 0.f;
    double DuckStartS = 0.0;
    double DuckBeganAtS = -1.0;
    FTimerHandle DuckTimer;
    bool bSubmixDuck = false;
    float LastSettingsVolume = 1.f;

    TMap<FName, FSaskartaAmbienceBag> ExtraBags;

    FTimerHandle UpdateTimer;
    bool bBound = false;
    bool bWarnedNoAsset = false;
    FRandomStream Random;
};
