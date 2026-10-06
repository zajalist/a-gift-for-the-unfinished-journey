// Saskarta project GameUserSettings subclass.
//
// Run 1 (offline, no editor/build): skeleton only. ComputeCVars() intentionally
// returns an EMPTY map so Saskarta.Settings.CVarMapping fails first, per the
// TDD step in task-P2-brief.md. The real mapping lands in Run 2, after the
// user rebuilds and restarts the editor (see task-P2-report.md).

#pragma once

#include "CoreMinimal.h"
#include "GameFramework/GameUserSettings.h"
#include "SaskartaHardwareProfile.h"
#include "SaskartaGameUserSettings.generated.h"

/**
 * Project-wide user settings for Saskarta: foliage density/distance, cloud
 * mode, accessibility, audio, upscaler, subtitles and camera shake.
 *
 * ComputeCVars() is the single source of truth for the settings -> CVar
 * mapping (see task-P2-brief.md's CVar mapping table) and is pure/testable
 * on its own, independent of ApplySaskartaSettings() actually setting them.
 */
UCLASS(config = GameUserSettings, BlueprintType)
class SASKARTACORE_API USaskartaGameUserSettings : public UGameUserSettings
{
    GENERATED_BODY()

public:
    /** Returns the current GameUserSettings, cast to USaskartaGameUserSettings. */
    UFUNCTION(BlueprintPure, Category = "Saskarta|Settings")
    static USaskartaGameUserSettings* GetSaskartaSettings();

    /** 0.25 - 1.0. Scales grass.DensityScale and pcg.Saskarta.DensityScale. */
    UPROPERTY(Config, BlueprintReadWrite, Category = "Saskarta|Foliage")
    float FoliageDensity = 1.0f;

    /** 0.5 - 1.5. Scales grass.CullDistanceScale and foliage.LODDistanceScale. */
    UPROPERTY(Config, BlueprintReadWrite, Category = "Saskarta|Foliage")
    float FoliageDistance = 1.0f;

    /** 0 = 2D layer, 1 = volumetric. Drives r.VolumetricCloud. */
    UPROPERTY(Config, BlueprintReadWrite, Category = "Saskarta|Sky")
    int32 CloudMode = 1;

    /** Drives r.Saskarta.ReduceFlashing, read by materials via an MPC. */
    UPROPERTY(Config, BlueprintReadWrite, Category = "Saskarta|Accessibility")
    bool bReduceFlashing = false;

    /** Applied by the player camera manager, not a CVar. Clamped 70-110 for the test. */
    UPROPERTY(Config, BlueprintReadWrite, Category = "Saskarta|Camera")
    float FieldOfView = 90.f;

    UPROPERTY(Config, BlueprintReadWrite, Category = "Saskarta|Audio")
    float MasterVolume = 1.f;

    UPROPERTY(Config, BlueprintReadWrite, Category = "Saskarta|Audio")
    float AmbienceVolume = 1.f;

    UPROPERTY(Config, BlueprintReadWrite, Category = "Saskarta|Audio")
    float VoiceVolume = 1.f;

    UPROPERTY(Config, BlueprintReadWrite, Category = "Saskarta|Audio")
    float EffectsVolume = 1.f;

    /** 0 = TSR, 1 = DLSS, 2 = Native. */
    UPROPERTY(Config, BlueprintReadWrite, Category = "Saskarta|Upscaling")
    int32 UpscalerMethod = 0;

    /** 0 = Quality, 1 = Balanced, 2 = Performance. */
    UPROPERTY(Config, BlueprintReadWrite, Category = "Saskarta|Upscaling")
    int32 UpscalerMode = 0;

    UPROPERTY(Config, BlueprintReadWrite, Category = "Saskarta|Upscaling")
    float Sharpness = 0.2f;

    UPROPERTY(Config, BlueprintReadWrite, Category = "Saskarta|Upscaling")
    bool bFrameGeneration = false;

    UPROPERTY(Config, BlueprintReadWrite, Category = "Saskarta|Accessibility")
    bool bSubtitles = true;

    UPROPERTY(Config, BlueprintReadWrite, Category = "Saskarta|Accessibility")
    int32 SubtitleSize = 1;

    UPROPERTY(Config, BlueprintReadWrite, Category = "Saskarta|Camera")
    float CameraShake = 1.0f;

    /** The carrier camera's sensor look (M_PP_SensorCRT): 0 Off, 1 Low, 2 Medium (default), 3 High. */
    UPROPERTY(Config, BlueprintReadWrite, Category = "Saskarta|Camera")
    int32 SensorFilter = 2;

    /** Writes the CVars computed by ComputeCVars(). */
    UFUNCTION(BlueprintCallable, Category = "Saskarta|Settings")
    void ApplySaskartaSettings();

    /**
     * Pure, testable single source of truth for the settings -> CVar mapping.
     * Run 1: intentionally returns an empty map (fail-first; see file header).
     */
    UFUNCTION(BlueprintPure, Category = "Saskarta|Settings")
    static TMap<FString, FString> ComputeCVars(const USaskartaGameUserSettings* S);

    /** True when the DLSS plugin module is loaded. */
    UFUNCTION(BlueprintPure, Category = "Saskarta|Settings")
    static bool IsDlssAvailable();

    // ---- Task PERF-AUTO: hardware auto-detect and adaptive quality -------------------
    // See SaskartaHardwareProfile.h, SaskartaPerfGovernor.h and Tools/Perf/SCALABILITY.md.

    /** The adaptive-quality governor (USaskartaPerfGovernor). Default on. */
    UPROPERTY(Config, BlueprintReadWrite, Category = "Saskarta|Performance")
    bool bAdaptiveQuality = true;

    /** The governor's target: 0 = 30 fps, 1 = 60 fps, 2 = Display (the frame cap, else the refresh rate). */
    UPROPERTY(Config, BlueprintReadWrite, Category = "Saskarta|Performance")
    int32 AdaptiveTargetMode = 1;

    /** True once RunAutoDetect() has picked these settings. */
    UPROPERTY(Config, BlueprintReadOnly, Category = "Saskarta|Performance")
    bool bAutoDetected = false;

    /** The adapter the settings were detected on; a different adapter re-runs the detection. */
    UPROPERTY(Config, BlueprintReadOnly, Category = "Saskarta|Performance")
    FString AutoDetectGPU;

    /** Its driver at detection time (informational; a driver update does not re-detect). */
    UPROPERTY(Config, BlueprintReadOnly, Category = "Saskarta|Performance")
    FString AutoDetectDriver;

    UPROPERTY(Config, BlueprintReadOnly, Category = "Saskarta|Performance")
    int32 AutoDetectLevel = -1;

    UPROPERTY(Config, BlueprintReadOnly, Category = "Saskarta|Performance")
    int32 AutoDetectVRAMMB = -1;

    UPROPERTY(Config, BlueprintReadOnly, Category = "Saskarta|Performance")
    float AutoDetectCPUScore = -1.f;

    UPROPERTY(Config, BlueprintReadOnly, Category = "Saskarta|Performance")
    float AutoDetectGPUScore = -1.f;

    /**
     * Reads the hardware, runs the synth benchmark (about 1-2 s), picks the preset, per-group
     * levels, upscaler, frame cap and VSync, applies and saves them. The Settings menu's
     * "Run benchmark" button calls this.
     */
    UFUNCTION(BlueprintCallable, Category = "Saskarta|Performance")
    FSaskartaDetectedProfile RunAutoDetect();

    /** RunAutoDetect() at first launch (no saved settings) or when the GPU changed. True if it ran. */
    UFUNCTION(BlueprintCallable, Category = "Saskarta|Performance")
    bool RunAutoDetectIfNeeded();

    /**
     * The last detection (this session), or one rebuilt from the saved detection and this
     * machine's specs. Summary is the Settings line "Detected: <GPU>, <VRAM>, recommended: High".
     */
    UFUNCTION(BlueprintPure, Category = "Saskarta|Performance")
    FSaskartaDetectedProfile GetDetectedProfile() const;

    /** GetDetectedProfile().Summary, for Blueprint graphs that cannot break the struct (bpgraph). */
    UFUNCTION(BlueprintPure, Category = "Saskarta|Performance")
    FText GetDetectedSummary() const { return GetDetectedProfile().Summary; }

    /** The governor's target frame rate for these settings (AdaptiveTargetMode, frame cap, VSync). */
    UFUNCTION(BlueprintPure, Category = "Saskarta|Performance")
    float GetAdaptiveTargetFps(int32 RefreshHz) const;

    /**
     * Non-empty while any quality group is on Cinematic: the Settings menu shows it under the
     * Preset row. Automatic Cinematic requires benchmark and memory headroom.
     */
    UFUNCTION(BlueprintPure, Category = "Saskarta|Performance")
    FText GetQualityWarning() const;

    /** Writes a recommendation into these settings (does not apply or save). */
    void ApplyDetectedProfile(const FSaskartaDetectedProfile& Profile);

    /** Pure: first launch, or the adapter changed. Never with an empty current adapter name. */
    static bool ShouldAutoDetect(bool bInHadSavedSettings, bool bAlreadyAutoDetected, const FString& SavedGPU, const FString& CurrentGPU);

    /** Pure: the governor target. Mode 0 = 30, 1 = 60, 2 = Display; never above the cap or a VSync'd refresh. */
    static float ComputeAdaptiveTargetFps(int32 Mode, float FrameRateLimit, int32 RefreshHz, bool bVSync);

    /**
     * Pure: the per-tier CVars that DefaultScalability.ini cannot set, because the project's
     * RendererSettings / [SystemSettings] hold them above the scalability priority (VSM LOD
     * bias, Nanite MaxPixelsPerEdge, the texture pool per VRAM class, Lumen HWRT).
     * bIncludeRenderStateRecreate adds the ones whose change recreates every render proxy
     * (r.Lumen.HardwareRayTracing): only on a user settings change, never from the governor.
     * RAMGB (task HEADROOM): <= 0 (default, unknown) leaves the pool's RAM-based reserve alone,
     * matching every call from before task HEADROOM; > 0 also keeps
     * USaskartaHardwareProfileLibrary::RAMHeadroomMB(RAMGB) of system RAM free (see
     * StreamingPoolForVRAM).
     */
    static TMap<FString, FString> ComputeTierCVars(int32 ShadowLevel, int32 GILevel, int32 ViewDistanceLevel, int32 VRAMMB, bool bIncludeRenderStateRecreate, int32 RAMGB = -1);

    /** Sets them at ECVF_SetBySystemSettingsIni (the priority of the ini lines they replace); unchanged values are skipped. */
    static void ApplyTierCVars(const TMap<FString, FString>& CVars);

    /** False in the editor (PIE shares the editor's CVars) unless saskarta.perf.AllowInEditor=1. */
    static bool IsPerfAutomationAllowed();

    /** Broadcast when requested engine/graphics settings change, so the governor can drop its steps. */
    static FSimpleMulticastDelegate& OnUserSettingsApplying();

    //~ Begin UGameUserSettings interface
    virtual void ApplySettings(bool bCheckForCommandLineOverrides) override;
    virtual void ApplyNonResolutionSettings() override;
    /** Also sets the foliage density / distance and the clouds from the level's PresetFoliage row (0-4). */
    virtual void SetOverallScalabilityLevel(int32 Value) override;

    /** The game's hard frame cap: every tier and every saved setting is clamped to it (0 = uncapped becomes this). */
    static constexpr int32 MaxFrameRate = 60;
    virtual void LoadSettings(bool bForceReload = false) override;
    //~ End UGameUserSettings interface

private:
    /** Requested values, not live CVars: governors and PIE may temporarily override the latter. */
    FString NonResolutionApplySignature() const;
    void ApplyRequestedResolutionSettings(bool bCheckForCommandLineOverrides);
    FString LastNonResolutionApplySignature;
    Scalability::FQualityLevels LastAppliedScalabilityQuality;
    bool bHasAppliedNonResolutionSettings = false;

    UPROPERTY(Transient)
    FSaskartaDetectedProfile LastDetected;

    /** Whether GameUserSettings.ini already had this class's section when LoadSettings first ran. */
    bool bHadSavedSettings = true;
    bool bSavedSectionChecked = false;
};
