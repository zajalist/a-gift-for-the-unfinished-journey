// USaskartaLightingDirector: blends the look keys along the road (Task L7).
//
// Spec: docs/superpowers/specs/2026-09-26-saskarta-world-sprint-design.md, section 6
// ("The lighting director", "Lightning").
//
// - SetRoadProgress(RoadM) is called from the tether's existing 0.2 s closest-key check.
// - Every 0.5 s the director moves a smoothed road metre toward the last RoadM with a
//   25 s time constant, blends the two neighbouring keys of DA_Saskarta_LookKeys at it,
//   and drives the actors tagged Saskarta_Sun, Saskarta_Sky, Saskarta_Clouds,
//   Saskarta_Fog, Saskarta_GradeStorm and Saskarta_GradeClear, plus MPC_Saskarta_Sky.
// - While StormIntensity > 0.3 it fires lightning every 8-35 s (scaled by intensity; also
//   without road progress, from the MPC default or an override):
//   a LightningFlash pulse (0.08 s up, 0.4 s down) and a sun-intensity pop, then thunder
//   after distance / 343 s for a random 1-8 km strike (SFX_Thunder_Close_* under 2.5 km,
//   SFX_Thunder_Rolling_* otherwise). r.Saskarta.ReduceFlashing 1 scales the flash down.
//
// The maths (key blend, smoothing, thunder delay, flash envelope, strike interval) are
// pure static functions so Saskarta.Director.* automation tests can check them without
// a world.

#pragma once

#include "CoreMinimal.h"
#include "Subsystems/WorldSubsystem.h"
#include "Engine/EngineTypes.h"
#include "Math/RandomStream.h"
#include "TimerManager.h"
#include "SaskartaLookKeys.h"
#include "SaskartaLightingDirector.generated.h"

class AActor;
class APostProcessVolume;
class UDirectionalLightComponent;
class UExponentialHeightFogComponent;
class UMaterialParameterCollection;
class USkyAtmosphereComponent;
class USoundBase;
class UVolumetricCloudComponent;

DECLARE_DYNAMIC_MULTICAST_DELEGATE_TwoParams(FSaskartaLightningStrike, float, DistanceM, bool, bClose);

UCLASS(BlueprintType)
class SASKARTACORE_API USaskartaLightingDirector : public UWorldSubsystem
{
    GENERATED_BODY()

public:
    // ------------------------------------------------------------------ constants
    static constexpr float BlendIntervalS = 0.5f;
    static constexpr float SmoothingTauS = 25.f;
    static constexpr float SpeedOfSoundMps = 343.f;
    static constexpr float CloseThunderM = 2500.f;
    static constexpr float StrikeMinM = 1000.f;
    static constexpr float StrikeMaxM = 8000.f;
    static constexpr float LightningMinIntensity = 0.3f;
    static constexpr float LightningIntervalMinS = 8.f;   // LANE4 "more intense": was 20
    static constexpr float LightningIntervalMaxS = 35.f;  // LANE4: was 90
    /** The intensity at which the interval is exactly 8-35 s (the Valley key's 0.45). */
    static constexpr float LightningReferenceIntensity = 0.45f;
    static constexpr float FlashRiseS = 0.08f;
    static constexpr float FlashFallS = 0.4f;
    /** Fog inscattering is absolute luminance; the key colour is a hue (apply_look.py FOG_LUMINANCE_SCALE). */
    static constexpr float FogLuminanceScale = 0.08f;

    static const FName TagSun;
    static const FName TagSky;
    static const FName TagClouds;
    static const FName TagFog;
    static const FName TagGradeStorm;
    static const FName TagGradeClear;

    // ------------------------------------------------------------------ pure maths (tested)
    /**
     * The look at RoadM. Keys must be sorted by RoadM. Exact (a copy of the key) at a key's
     * RoadM, linear between neighbours, clamped to the first/last key outside the range.
     * Yaw is blended along the shortest arc. Name is the lower key's name.
     */
    static FSaskartaLookKey BlendKeys(const TArray<FSaskartaLookKey>& SortedKeys, float RoadM);

    /** Exponential smoothing: one step of Dt seconds toward Target with time constant Tau. */
    static float SmoothTowards(float Current, float Target, float DtS, float TauS);

    /** Thunder follows the flash after Distance / 343 m/s. */
    static float ThunderDelaySeconds(float DistanceM);

    /** Close thunder family under 2.5 km, rolling otherwise. */
    static bool IsCloseStrike(float DistanceM);

    /** Lightning flash envelope 0..1 at T seconds after the strike: 0.08 s up, 0.4 s down. */
    static float FlashEnvelope(float TimeS);

    /**
     * Seconds to the next strike: 8-35 s (Rand01 picks within) at the reference intensity,
     * shorter when stormier (x 0.45 / Intensity, clamped to x0.5 .. x1.5).
     */
    static float NextLightningIntervalS(float Rand01, float Intensity);

    // ------------------------------------------------------------------ runtime API
    UFUNCTION(BlueprintPure, Category = "Saskarta|Look", meta = (WorldContext = "WorldContextObject"))
    static USaskartaLightingDirector* GetLightingDirector(const UObject* WorldContextObject);

    /** The player's walk metre along the road; the tether calls this every 0.2 s. */
    UFUNCTION(BlueprintCallable, Category = "Saskarta|Look")
    void SetRoadProgress(float RoadM);

    /** Uses these keys instead of DA_Saskarta_LookKeys (tests, or a level override). Sorted on set. */
    UFUNCTION(BlueprintCallable, Category = "Saskarta|Look")
    void SetLookKeys(const TArray<FSaskartaLookKey>& InKeys);

    UFUNCTION(BlueprintPure, Category = "Saskarta|Look")
    float GetStormIntensity() const { return StormIntensity; }

    UFUNCTION(BlueprintPure, Category = "Saskarta|Look")
    float GetSmoothedRoadM() const { return SmoothedRoadM; }

    /** The storm level lightning uses: an override, else the road look's, else the level's (MPC default). The radio's imperfections read it. */
    UFUNCTION(BlueprintPure, Category = "Saskarta|Look")
    float GetEffectiveStormIntensity() const { return EffectiveStormIntensity(); }

    UFUNCTION(BlueprintPure, Category = "Saskarta|Look")
    FSaskartaLookKey GetCurrentLook() const { return CurrentLook; }

    /** 0-1, the blended key's storm intensity: wind beds, gusts, thunder and Geiger rates read this. */
    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Look")
    float StormIntensity = 0.f;

    /** Fired at each lightning strike (flash time), before the thunder. */
    UPROPERTY(BlueprintAssignable, Category = "Saskarta|Look")
    FSaskartaLightningStrike OnLightningStrike;

    /**
     * Plays SFX_Thunder_Close_* / SFX_Thunder_Rolling_* after each strike. The ambience director
     * (USaskartaAmbienceDirector) clears it once its Ambience 2 thunder has streamed in, so the
     * thunder is never doubled (AMBIENCE2 brief option B).
     */
    UPROPERTY(BlueprintReadWrite, Category = "Saskarta|Look")
    bool bPlayThunder = true;

    // ------------------------------------------------------------------ overrides (EVENTS.md section 8, README_Debug.md)
    // The story's SetLook / SetFog actions (forwarded by the event runner) and the debug menu use
    // these instead of writing the actors or the MPC themselves, so nothing fights the director.
    // They work with or without road progress: without it, the level's own look (captured once from
    // the tagged actors) is the base the override blends from and back to.

    /** Blends to the named look key over BlendS and holds it. False if no key has that name. */
    UFUNCTION(BlueprintCallable, Category = "Saskarta|Look")
    bool PushLookOverride(FName LookKey, float BlendS);

    /** Holds the road's look at RoadM (the debug menu's look buttons), blended in over BlendS. */
    UFUNCTION(BlueprintCallable, Category = "Saskarta|Look")
    void PushLookOverrideAtRoadM(float RoadM, float BlendS);

    /** Blends back to the road's look over BlendS. */
    UFUNCTION(BlueprintCallable, Category = "Saskarta|Look")
    void PopLookOverride(float BlendS);

    /** Multiplies the fog density (both layers) by Multiplier, blended over BlendS; 1 restores it. */
    UFUNCTION(BlueprintCallable, Category = "Saskarta|Look")
    void PushFogOverride(float Multiplier, float BlendS);

    /** Temporary surrounding dust, composed by the fog's existing sole writer. VisibilityM is the distance to 10% transmission. */
    void SetPursuitDustFog(UObject* Owner, float Weight, float VisibilityM, float CameraHeightCm);
    void ReleasePursuitDustFog(UObject* Owner);

    /**
     * First light (storyline-first-light.md section 6): from the look showing now (PreDawn at the mast) to the dawn,
     * by time: the sun's disc clears HorizonPitch at ClearAtS and the ramp ends at DurationS. Applied 4 times a
     * second and the SkyLight recaptured every 10 s (FSaskartaFirstLight), so a skipped sequence still gets it.
     * PopLookOverride ends it. The event runner's PlayDawn action calls this.
     */
    UFUNCTION(BlueprintCallable, Category = "Saskarta|Look")
    bool PlayDawn(float DurationS = 120.f, float ClearAtS = 62.f, float HorizonPitch = -0.5f, float SunYaw = 176.5f);

    UFUNCTION(BlueprintPure, Category = "Saskarta|Look")
    bool IsDawnPlaying() const { return bDawn; }

    /** Pins the storm intensity (MPC StormIntensity, lightning rate) at Intensity 0-1; a negative value releases it. */
    UFUNCTION(BlueprintCallable, Category = "Saskarta|Look")
    void SetStormOverride(float Intensity);

    UFUNCTION(BlueprintPure, Category = "Saskarta|Look")
    bool IsLookOverridden() const { return bLookOverride; }

    UFUNCTION(BlueprintPure, Category = "Saskarta|Look")
    float GetFogMultiplier() const { return FogMult; }

    UFUNCTION(BlueprintPure, Category = "Saskarta|Look")
    float GetStormOverride() const { return StormOverride; }

    /**
     * The look actually applied: Road blended toward Override by OverrideAlpha (0 = road, 1 = override;
     * the name is the override's from alpha 0.5), both fog densities x FogMultiplier, and the storm
     * intensity replaced by StormOverride when it is >= 0 (clamped to 0-1).
     */
    static FSaskartaLookKey ComposeLook(const FSaskartaLookKey& Road, const FSaskartaLookKey& Override, float OverrideAlpha,
        float FogMultiplier, float StormOverrideIntensity);

    /** The key named Name, or null. */
    static const FSaskartaLookKey* FindKeyByName(const TArray<FSaskartaLookKey>& InKeys, FName Name);

    /** A blend's value ElapsedS into a BlendS ramp from From to To (smoothstep; BlendS <= 0 jumps). */
    static float BlendValue(float From, float To, float ElapsedS, float BlendS);

    // ------------------------------------------------------------------ UWorldSubsystem
    virtual void Initialize(FSubsystemCollectionBase& Collection) override;
    virtual void Deinitialize() override;
    virtual void OnWorldBeginPlay(UWorld& InWorld) override;

protected:
    virtual bool DoesSupportWorldType(const EWorldType::Type WorldType) const override;

private:
    void LoadAssets();
    void ResolveActors();
    void OnBlendTick();
    void ApplyLook(const FSaskartaLookKey& Look);
    void ApplyFog(const FSaskartaLookKey& Look);
    void RestorePursuitFogFields();
    void ApplySunIntensity();
    /** Storm level for lightning: the blended key's when road progress drives the look, else the MPC default (LANE4). */
    float EffectiveStormIntensity() const;
    /** The sun's saved intensity, used for the flash pop when road progress does not drive the look (-1 = unknown). */
    float UndrivenSunLux = -1.f;
    void ScheduleNextLightning();
    void OnLightning();
    void OnFlashTick();
    void PlayThunder(float DistanceM);

    // --- overrides
    /** True when an override (look, fog or storm) is active or still blending out. */
    bool AnyOverride() const;
    /** Road look (or the captured level look without road progress) with the overrides composed, applied to the actors. */
    void ApplyComposite();
    /** 30 Hz while an override blends; stops itself when every blend is done. */
    void OnOverrideTick();
    void StartOverrideTick();
    /** Reads the level's current look from the tagged actors and the MPC defaults (once, without road progress). */
    void CaptureLevelLook();
    /** Starts holding Key: from the road look (or, when an override already shows, from what it shows now). */
    void BeginLookOverride(const FSaskartaLookKey& Key, float BlendS);
    /** The override look as it shows now: OverrideFromKey blended to OverrideKey by OverrideMix. */
    FSaskartaLookKey EffectiveOverrideKey() const;

    /** Blend of the override look between the previous override (From) and the new one (OverrideKey). */
    FSaskartaLookKey OverrideFromKey;
    float OverrideMix = 1.f;
    double OverrideMixStartS = 0.0;
    float OverrideMixBlendS = 0.f;

    FSaskartaLookKey OverrideKey;
    bool bLookOverride = false;
    /** Weight of the override against the road look (0 = road, 1 = override). */
    float OverrideAlpha = 0.f;
    float OverrideAlphaFrom = 0.f;
    float OverrideAlphaTo = 0.f;
    double OverrideBlendStartS = 0.0;
    float OverrideBlendS = 0.f;

    float FogMult = 1.f;
    float FogMultFrom = 1.f;
    float FogMultTo = 1.f;
    double FogBlendStartS = 0.0;
    float FogBlendS = 0.f;

    float StormOverride = -1.f;

    TWeakObjectPtr<UObject> PursuitFogOwner;
    TWeakObjectPtr<UExponentialHeightFogComponent> PursuitOwnedFog;
    float PursuitFogWeight = 0.f;
    float PursuitVisibilityM = 40.f;
    float PursuitCameraHeightCm = 0.f;
    float PursuitPreviousMaxOpacity = 0.f;
    float PursuitAppliedMaxOpacity = 0.f;
    float PursuitPreviousEndDistance = 0.f;
    float PursuitPreviousCutoffDistance = 0.f;
    float PursuitPreviousSkyCaptureStrength = 0.f;
    float PursuitAppliedSkyCaptureStrength = 0.f;
    FLinearColor PursuitPreviousDirectional;
    FLinearColor PursuitAppliedDirectional;
    FLinearColor PursuitPreviousSkyAmbient;
    FLinearColor PursuitAppliedSkyAmbient;
    FLinearColor PursuitPreviousCubemapTint;
    FLinearColor PursuitAppliedCubemapTint;
    FColor PursuitPreviousVolumeAlbedo;
    FColor PursuitAppliedVolumeAlbedo;
    FLinearColor PursuitPreviousVolumeEmissive;
    FLinearColor PursuitAppliedVolumeEmissive;
    float PursuitPreviousVolumeExtinction = 1.f;
    float PursuitAppliedVolumeExtinction = 1.f;
    float PursuitAppliedEndDistance = 0.f;
    float PursuitAppliedCutoffDistance = 0.f;
    float PursuitPreviousVolumeStart = 0.f;
    float PursuitAppliedVolumeStart = 0.f;
    float PursuitPreviousVolumeNearFade = 0.f;
    float PursuitAppliedVolumeNearFade = 0.f;
    UPROPERTY(Transient) TObjectPtr<class UTextureCube> PursuitPreviousCubemap;

    /** The level's own look (CaptureLevelLook), the base without road progress. */
    FSaskartaLookKey LevelLook;
    bool bLevelLookCaptured = false;
    /** An override was applied without road progress, so the level look must be put back once they are all released. */
    bool bUndrivenDirty = false;

    FTimerHandle OverrideTimer;

    // --- first light (PlayDawn)
    bool bDawn = false;
    double DawnStartS = 0.0;
    float DawnDurationS = 0.f;
    float DawnClearAtS = 0.f;
    float DawnClearMix = 0.5f;
    float DawnPrevElapsedS = -1.f;
    double DawnLastApplyS = -1.0;
    TWeakObjectPtr<class USkyLightComponent> DawnSkyLight;
    void DawnTick(double NowS);

    TArray<FSaskartaLookKey> Keys;
    FSaskartaLookKey CurrentLook;

    float TargetRoadM = 0.f;
    float SmoothedRoadM = 0.f;
    bool bHasRoadProgress = false;
    bool bWarnedNoKeys = false;

    UPROPERTY()
    TObjectPtr<UMaterialParameterCollection> SkyMPC;

    UPROPERTY()
    TArray<TObjectPtr<USoundBase>> ThunderClose;

    UPROPERTY()
    TArray<TObjectPtr<USoundBase>> ThunderRolling;

    TWeakObjectPtr<AActor> SunActor;
    TWeakObjectPtr<UDirectionalLightComponent> SunLight;
    TWeakObjectPtr<USkyAtmosphereComponent> SkyAtmosphere;
    TWeakObjectPtr<UVolumetricCloudComponent> Clouds;
    TWeakObjectPtr<UExponentialHeightFogComponent> Fog;
    TWeakObjectPtr<APostProcessVolume> GradeStorm;
    TWeakObjectPtr<APostProcessVolume> GradeClear;
    double LastResolveTimeS = -1000.0;
    bool bWarnedMissingTags = false;

    FTimerHandle BlendTimer;
    FTimerHandle LightningTimer;
    FTimerHandle FlashTimer;
    double FlashStartTimeS = 0.0;
    float FlashLevel = 0.f;
    FRandomStream Random;
};
