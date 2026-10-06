// Run 2: ComputeCVars() is the single source of truth for the settings ->
// CVar mapping (task-P2-brief.md's CVar mapping table). See
// SaskartaGameUserSettings.h.

#include "SaskartaGameUserSettings.h"
#include "ComponentRecreateRenderStateContext.h"
#include "CoreGlobals.h"
#include "Engine/Engine.h"
#include "Misc/ConfigCacheIni.h"
#include "HAL/IConsoleManager.h"
#include "Modules/ModuleManager.h"
#include "Scalability.h"

namespace
{
    bool CVarValueMatches(const IConsoleVariable& Variable, const FString& Desired)
    {
        const FString Current = Variable.GetString();
        return Current == Desired
            || (Current.IsNumeric() && Desired.IsNumeric()
                && FMath::IsNearlyEqual(FCString::Atod(*Current), FCString::Atod(*Desired), 1.0e-4));
    }
}

USaskartaGameUserSettings* USaskartaGameUserSettings::GetSaskartaSettings()
{
    return Cast<USaskartaGameUserSettings>(GEngine->GetGameUserSettings());
}

TMap<FString, FString> USaskartaGameUserSettings::ComputeCVars(const USaskartaGameUserSettings* S)
{
    TMap<FString, FString> C;
    auto F = [](float V) { return FString::Printf(TEXT("%.3f"), V); };
    C.Add(TEXT("grass.DensityScale"), F(FMath::Clamp(S->FoliageDensity, 0.25f, 1.f)));
    C.Add(TEXT("pcg.Saskarta.DensityScale"), F(FMath::Clamp(S->FoliageDensity, 0.25f, 1.f)));
    C.Add(TEXT("grass.CullDistanceScale"), F(FMath::Clamp(S->FoliageDistance, 0.5f, 1.5f)));
    C.Add(TEXT("foliage.LODDistanceScale"), F(FMath::Clamp(S->FoliageDistance, 0.5f, 1.5f)));
    C.Add(TEXT("r.VolumetricCloud"), S->CloudMode ? TEXT("1") : TEXT("0"));
    C.Add(TEXT("r.Saskarta.ReduceFlashing"), S->bReduceFlashing ? TEXT("1") : TEXT("0"));
    static const float Pct[3] = {66.7f, 58.f, 50.f};
    if (S->UpscalerMethod == 2) { C.Add(TEXT("r.ScreenPercentage"), F(100.f)); }
    else { C.Add(TEXT("r.ScreenPercentage"), F(Pct[FMath::Clamp(S->UpscalerMode, 0, 2)])); }
    if (S->UpscalerMethod == 0) { C.Add(TEXT("r.AntiAliasingMethod"), TEXT("4")); }
    C.Add(TEXT("r.Tonemapper.Sharpen"), F(FMath::Clamp(S->Sharpness, 0.f, 1.f)));
    C.Add(TEXT("saskarta.fov"), F(FMath::Clamp(S->FieldOfView, 70.f, 110.f)));

    // Task P3: one "saskarta.*" mirror per setting. They are the settings
    // menu's read path (Blueprint reads them with GetConsoleVariable*Value,
    // since it cannot read this object's properties without new UFUNCTIONs,
    // R40) and the value the game-side consumers (audio mix, subtitles,
    // camera shake) read. ApplySaskartaSettings registers any that are
    // missing. Nothing else sets them, so no ini or scalability priority can
    // mask them the way it can mask grass.DensityScale.
    auto I = [](int32 V) { return FString::FromInt(V); };
    C.Add(TEXT("saskarta.foliage.density"), F(FMath::Clamp(S->FoliageDensity, 0.25f, 1.f)));
    C.Add(TEXT("saskarta.foliage.distance"), F(FMath::Clamp(S->FoliageDistance, 0.5f, 1.5f)));
    C.Add(TEXT("saskarta.clouds"), I(S->CloudMode ? 1 : 0));
    C.Add(TEXT("saskarta.upscaler.method"), I(FMath::Clamp(S->UpscalerMethod, 0, 2)));
    C.Add(TEXT("saskarta.upscaler.mode"), I(FMath::Clamp(S->UpscalerMode, 0, 2)));
    C.Add(TEXT("saskarta.upscaler.sharpness"), F(FMath::Clamp(S->Sharpness, 0.f, 1.f)));
    C.Add(TEXT("saskarta.upscaler.framegen"), I(S->bFrameGeneration ? 1 : 0));
    C.Add(TEXT("saskarta.volume.master"), F(FMath::Clamp(S->MasterVolume, 0.f, 1.f)));
    C.Add(TEXT("saskarta.volume.ambience"), F(FMath::Clamp(S->AmbienceVolume, 0.f, 1.f)));
    C.Add(TEXT("saskarta.volume.voice"), F(FMath::Clamp(S->VoiceVolume, 0.f, 1.f)));
    C.Add(TEXT("saskarta.volume.effects"), F(FMath::Clamp(S->EffectsVolume, 0.f, 1.f)));
    C.Add(TEXT("saskarta.subtitles"), I(S->bSubtitles ? 1 : 0));
    C.Add(TEXT("saskarta.subtitles.size"), I(FMath::Clamp(S->SubtitleSize, 0, 2)));
    C.Add(TEXT("saskarta.camerashake"), F(FMath::Clamp(S->CameraShake, 0.f, 1.f)));
    C.Add(TEXT("saskarta.sensorfilter"), I(FMath::Clamp(S->SensorFilter, 0, 3)));
    // Task PERF-AUTO mirrors (the Graphics tab's Adaptive quality / Target frame rate rows).
    C.Add(TEXT("saskarta.adaptive"), I(S->bAdaptiveQuality ? 1 : 0));
    C.Add(TEXT("saskarta.adaptive.target"), I(FMath::Clamp(S->AdaptiveTargetMode, 0, 2)));
    return C;
}

void USaskartaGameUserSettings::ApplySaskartaSettings()
{
    const TMap<FString, FString> RequestedCVars = ComputeCVars(this);
    auto MirrorMatches = [&RequestedCVars](const TCHAR* Name)
    {
        const IConsoleVariable* Variable = IConsoleManager::Get().FindConsoleVariable(Name);
        const FString* Requested = RequestedCVars.Find(Name);
        return Variable && Requested && CVarValueMatches(*Variable, *Requested);
    };
    const bool bAdaptiveBaselineChanged = !MirrorMatches(TEXT("saskarta.foliage.density"))
        || !MirrorMatches(TEXT("saskarta.foliage.distance"))
        || !MirrorMatches(TEXT("saskarta.upscaler.method"))
        || !MirrorMatches(TEXT("saskarta.upscaler.mode"));
    if (Scalability::IsTemporaryQualityLevelActive() && bAdaptiveBaselineChanged)
    {
        // A real foliage/upscaler edit needs a new adaptive baseline. DropAllSteps
        // disables its temporary levels before calling back here to restore CVars.
        OnUserSettingsApplying().Broadcast();
    }
    const bool bPreserveAdaptiveOverrides = Scalability::IsTemporaryQualityLevelActive() && !bAdaptiveBaselineChanged;
    for (const TPair<FString, FString>& KV : RequestedCVars)
    {
        if (bPreserveAdaptiveOverrides && (KV.Key == TEXT("r.ScreenPercentage")
            || KV.Key == TEXT("grass.DensityScale") || KV.Key == TEXT("grass.CullDistanceScale")))
        {
            // PreviewLight is also used by volume sliders and after Apply. Its
            // unchanged user mirrors must not undo the governor's current step.
            continue;
        }
        IConsoleVariable* V = IConsoleManager::Get().FindConsoleVariable(*KV.Key);
        if (!V && KV.Key.StartsWith(TEXT("saskarta.")))
        {
            // Registered on first use rather than at module load, so adding a
            // mirror needs only this .cpp (Live Coding, R40/R41).
            V = IConsoleManager::Get().RegisterConsoleVariable(*KV.Key, 0.f,
                TEXT("Saskarta settings mirror, written by USaskartaGameUserSettings::ApplySaskartaSettings()."),
                ECVF_Default);
        }
        if (!V)
        {
            continue;
        }
        // Task PERF-URGENT: only write what changed. A CVar Set always fires its change callback,
        // even with the same value, and foliage.LODDistanceScale's callback is an engine-wide
        // FGlobalComponentRecreateRenderStateContext: every call (BeginIntro, the Settings menu,
        // the perf governor's DropAllSteps) recreated the render state of every component, which
        // measured an 18-27 s D3D12 stall at PIE start (Tools/Perf/BUDGET.md, PERF-URGENT).
        const bool bSame = CVarValueMatches(*V, KV.Value);
        if (!bSame)
        {
            V->Set(*KV.Value, ECVF_SetByGameSetting);
        }
        else if (static_cast<uint32>(V->GetFlags() & ECVF_SetByMask) < static_cast<uint32>(ECVF_SetByGameSetting))
        {
            // Same value, lower priority: take the game-setting priority (so scalability cannot
            // override the user's choice later) without firing the callbacks or sinks.
            V->Set(*KV.Value, static_cast<EConsoleVariableFlags>(ECVF_SetByGameSetting | ECVF_Set_SetOnly_Unsafe));
        }
    }
}

bool USaskartaGameUserSettings::IsDlssAvailable()
{
    return FModuleManager::Get().IsModuleLoaded("DLSS");
}

namespace
{
    // Task P4 (R40/R41): file-scope helper struct, no header change. Baseline
    // foliage/cloud values per overall scalability level (0 Low .. 4
    // Cinematic), applied by SetOverallScalabilityLevel() below. Provisional pending the
    // P5 flythrough; see Tools/Perf/PRESETS.md. High (2) is the 80 fps @
    // 1440p TSR-Quality target on an RTX 5070.
    struct FSaskartaFoliagePreset
    {
        float FoliageDensity;
        float FoliageDistance;
        int32 CloudMode; // 0 = 2D layer, 1 = volumetric.
    };

    const FSaskartaFoliagePreset PresetFoliage[5] = {
        /* 0 Low       */ { 0.35f, 0.6f,  0 },
        /* 1 Medium    */ { 0.6f,  0.75f, 0 },
        /* 2 High      */ { 0.9f,  1.0f,  1 },
        /* 3 Epic      */ { 1.0f,  1.15f, 1 },
        /* 4 Cinematic */ { 1.0f,  1.5f,  1 },
    };
}

void USaskartaGameUserSettings::SetOverallScalabilityLevel(int32 Value)
{
    Super::SetOverallScalabilityLevel(Value);

    // Task P4 (R40): picking a preset (the Settings menu's Preset row, ApplyDetectedProfile) sets
    // the foliage and cloud rows from the table. This used to run in ApplySettings() whenever the
    // overall level was clean (0-4), and no foliage or cloud change ever makes it Custom, so every
    // Apply replaced the player's Foliage density / distance and Clouds with the table while the
    // sliders kept showing the player's value (2026-09-28).
    if (Value >= 0 && Value < UE_ARRAY_COUNT(PresetFoliage))
    {
        const FSaskartaFoliagePreset& Preset = PresetFoliage[Value];
        FoliageDensity = Preset.FoliageDensity;
        FoliageDistance = Preset.FoliageDistance;
        CloudMode = Preset.CloudMode;
    }
}

void USaskartaGameUserSettings::ApplySettings(bool bCheckForCommandLineOverrides)
{
    ValidateSettings();
    // UE 5.8's base ApplySettings unconditionally recreates every component's render
    // state, even for unchanged settings or an audio-only Apply. Keep its individual
    // apply methods (resolution, VSync, frame cap, scalability, sinks and HDR), but
    // only batch a global recreation when rendering changes actually require it.
    const bool bQualityChanged = bEnableScalabilitySettings && Scalability::GetQualityLevels() != ScalabilityQuality;
    const IConsoleVariable* FoliageLOD = IConsoleManager::Get().FindConsoleVariable(TEXT("foliage.LODDistanceScale"));
    const FString DesiredFoliageLOD = FString::Printf(TEXT("%.3f"), FMath::Clamp(FoliageDistance, 0.5f, 1.5f));
    const bool bFoliageLODChanged = FoliageLOD && !CVarValueMatches(*FoliageLOD, DesiredFoliageLOD);
    auto ApplyRequestedSettings = [this, bCheckForCommandLineOverrides]()
    {
        ApplyRequestedResolutionSettings(bCheckForCommandLineOverrides);
        ApplyNonResolutionSettings();
        ApplySaskartaSettings();
    };
    if (bQualityChanged || bFoliageLODChanged)
    {
        FGlobalComponentRecreateRenderStateContext Context;
        ApplyRequestedSettings();
    }
    else
    {
        ApplyRequestedSettings();
    }
    RequestUIUpdate();
    SaveSettings();

    if (!GetQualityWarning().IsEmpty())
    {
        UE_LOG(LogTemp, Log, TEXT("Saskarta settings: Cinematic quality selected."));
    }
}

void USaskartaGameUserSettings::ApplyRequestedResolutionSettings(bool bCheckForCommandLineOverrides)
{
    ValidateSettings();
    const bool bPendingDisplayChange = GetScreenResolution() != GetLastConfirmedScreenResolution()
        || GetFullscreenMode() != GetLastConfirmedFullscreenMode()
        || GetDisplayIndex() != GetLastConfirmedDisplayIndex()
        || GetDisplayID() != GetLastConfirmedDisplayID();
    if (!bCheckForCommandLineOverrides && !bPendingDisplayChange)
    {
        return;
    }
    // Startup preloads the confirmed display before creating the game window.
    // Keep explicit command-line checks and real display edits on the original
    // engine path. Compare the
    // confirmed user choice: PIE's forced Windowed viewport or borderless desktop
    // size alone is not a new request. RevertResolution still calls the engine's
    // nonvirtual ApplyResolutionSettings directly, so no stale request cache can
    // suppress choosing the rejected mode again later.
    Super::ApplyResolutionSettings(bCheckForCommandLineOverrides);
}

FString USaskartaGameUserSettings::NonResolutionApplySignature() const
{
    return FString::Printf(TEXT("%d|%d|%.9g|%d|%d|%d|%d"),
        IsVSyncEnabled() ? 1 : 0, IsDynamicResolutionEnabled() ? 1 : 0,
        static_cast<double>(GetFrameRateLimit()), GetAudioQualityLevel(),
        bUseHDRDisplayOutput ? 1 : 0, HDRDisplayOutputNits, bEnableScalabilitySettings ? 1 : 0);
}

// ---- Task PERF-AUTO ----------------------------------------------------------------------

DEFINE_LOG_CATEGORY_STATIC(LogSaskartaAutoDetect, Log, All);

static TAutoConsoleVariable<int32> CVarSaskartaPerfAllowInEditor(
    TEXT("saskarta.perf.AllowInEditor"),
    0,
    TEXT("Saskarta: 1 lets the hardware auto-detect, the per-tier CVars and the adaptive-quality governor run in the ")
    TEXT("editor (PIE). Off by default: PIE shares the editor's CVars, so they would outlive the session."),
    ECVF_Default);

bool USaskartaGameUserSettings::IsPerfAutomationAllowed()
{
    return !GIsEditor || CVarSaskartaPerfAllowInEditor.GetValueOnGameThread() != 0;
}

FSimpleMulticastDelegate& USaskartaGameUserSettings::OnUserSettingsApplying()
{
    static FSimpleMulticastDelegate Delegate;
    return Delegate;
}

void USaskartaGameUserSettings::ApplyNonResolutionSettings()
{
    ValidateSettings();
    // The hard cap: an old save with "Unlimited" or 144 comes back at 60.
    const float Limit = GetFrameRateLimit();
    if (Limit <= 0.f || Limit > MaxFrameRate)
    {
        SetFrameRateLimit(static_cast<float>(MaxFrameRate));
    }
    const bool bQualityChanged = bEnableScalabilitySettings && (!bHasAppliedNonResolutionSettings
        || LastAppliedScalabilityQuality != ScalabilityQuality || Scalability::GetQualityLevels() != ScalabilityQuality);
    if (bHasAppliedNonResolutionSettings && !bQualityChanged
        && LastNonResolutionApplySignature == NonResolutionApplySignature())
    {
        // Preserve temporary quality/cap overrides for no-change and audio-only
        // Apply. Comparing live CVars would incorrectly classify those as edits.
        return;
    }
    OnUserSettingsApplying().Broadcast();
    Super::ApplyNonResolutionSettings();
    LastAppliedScalabilityQuality = ScalabilityQuality;
    LastNonResolutionApplySignature = NonResolutionApplySignature();
    bHasAppliedNonResolutionSettings = true;

    // Apply the additional renderer tier values on the same real quality edit,
    // including a menu preview. An audio Apply must not reset adaptive tier CVars
    // or repeat hardware discovery. First application still initializes them.
    if (bQualityChanged && IsPerfAutomationAllowed())
    {
        const FSaskartaHardwareSpecs Specs = USaskartaHardwareProfileLibrary::GatherHardwareSpecs();
        const int32 VRAMMB = AutoDetectVRAMMB > 0 ? AutoDetectVRAMMB : Specs.VRAMMB;
        ApplyTierCVars(ComputeTierCVars(GetShadowQuality(), GetGlobalIlluminationQuality(), GetViewDistanceQuality(), VRAMMB, true, Specs.RAMGB));
    }
}

void USaskartaGameUserSettings::LoadSettings(bool bForceReload)
{
    if (bForceReload)
    {
        // A forced reload is the Settings menu's Revert / Back ("drop what is not applied"). The engine's
        // LoadSettings copies the LIVE scalability levels (Scalability::GetQualityLevels), which the
        // menu's preview has already changed, so a Shadows -> Low preview survived Revert and the next
        // save kept it. Load the saved groups first, from where SaveSettings writes them.
        Scalability::LoadState(GIsEditor ? GEditorSettingsIni : GGameUserSettingsIni);
    }
    if (!bSavedSectionChecked)
    {
        // Only the Saved (user) layer ever has this class's section; Default*.ini do not.
        bSavedSectionChecked = true;
        bHadSavedSettings = GConfig && GConfig->DoesSectionExist(*GetClass()->GetPathName(), GGameUserSettingsIni);
    }
    Super::LoadSettings(bForceReload);
}

bool USaskartaGameUserSettings::ShouldAutoDetect(bool bInHadSavedSettings, bool bAlreadyAutoDetected, const FString& SavedGPU, const FString& CurrentGPU)
{
    if (CurrentGPU.IsEmpty())
    {
        return false; // RHI not up (or a null RHI): nothing to detect
    }
    if (!SavedGPU.IsEmpty())
    {
        return !SavedGPU.Equals(CurrentGPU, ESearchCase::IgnoreCase); // the card changed
    }
    // No adapter stamped yet: a first launch detects; a player from before this feature keeps
    // their settings (RunAutoDetectIfNeeded stamps the adapter instead).
    return !bInHadSavedSettings && !bAlreadyAutoDetected;
}

float USaskartaGameUserSettings::ComputeAdaptiveTargetFps(int32 Mode, float FrameRateLimit, int32 RefreshHz, bool bVSync)
{
    const float Display = FrameRateLimit > 0.f ? FrameRateLimit : (RefreshHz > 0 ? static_cast<float>(RefreshHz) : 60.f);
    float Target = Mode <= 0 ? 30.f : Mode >= 2 ? Display : 60.f;
    if (FrameRateLimit > 0.f)
    {
        Target = FMath::Min(Target, FrameRateLimit);
    }
    if (bVSync && RefreshHz > 0)
    {
        Target = FMath::Min(Target, static_cast<float>(RefreshHz));
    }
    return FMath::Max(Target, 20.f);
}

float USaskartaGameUserSettings::GetAdaptiveTargetFps(int32 RefreshHz) const
{
    return ComputeAdaptiveTargetFps(AdaptiveTargetMode, GetFrameRateLimit(), RefreshHz, IsVSyncEnabled());
}

TMap<FString, FString> USaskartaGameUserSettings::ComputeTierCVars(int32 ShadowLevel, int32 GILevel, int32 ViewDistanceLevel, int32 VRAMMB, bool bIncludeRenderStateRecreate, int32 RAMGB)
{
    // Levels 0 Low .. 4 Cinematic. High/Epic keep the values the project runs today
    // (DefaultEngine.ini: VSM bias 0.0, MaxPixelsPerEdge 1.5, pool 3072, HWRT on).
    static const float VsmBias[5] = { 2.0f, 1.0f, 0.0f, 0.0f, -0.5f };
    static const float NaniteEdge[5] = { 2.5f, 2.0f, 1.5f, 1.5f, 1.0f };
    auto F = [](float V) { return FString::Printf(TEXT("%.2f"), V); };
    TMap<FString, FString> C;
    const int32 S = FMath::Clamp(ShadowLevel, 0, 4);
    const int32 V = FMath::Clamp(ViewDistanceLevel, 0, 4);
    C.Add(TEXT("r.Shadow.Virtual.ResolutionLodBiasDirectional"), F(VsmBias[S]));
    C.Add(TEXT("r.Shadow.Virtual.ResolutionLodBiasDirectionalMoving"), F(VsmBias[S]));
    C.Add(TEXT("r.Nanite.MaxPixelsPerEdge"), F(NaniteEdge[V]));
    const int32 Pool = USaskartaHardwareProfileLibrary::StreamingPoolForVRAM(VRAMMB, RAMGB);
    if (Pool > 0)
    {
        C.Add(TEXT("r.Streaming.PoolSize"), FString::FromInt(Pool));
    }
    if (bIncludeRenderStateRecreate)
    {
        // Low has no Lumen GI at all; Medium is software Lumen (global distance field).
        C.Add(TEXT("r.Lumen.HardwareRayTracing"), GILevel <= 1 ? TEXT("0") : TEXT("1"));
    }
    return C;
}

void USaskartaGameUserSettings::ApplyTierCVars(const TMap<FString, FString>& CVars)
{
    for (const TPair<FString, FString>& KV : CVars)
    {
        IConsoleVariable* V = IConsoleManager::Get().FindConsoleVariable(*KV.Key);
        if (!V)
        {
            continue;
        }
        // Skip unchanged values: some of these recreate every render proxy on any Set.
        if (FMath::IsNearlyEqual(V->GetFloat(), FCString::Atof(*KV.Value), 0.001f))
        {
            continue;
        }
        V->Set(*KV.Value, ECVF_SetBySystemSettingsIni);
    }
}

void USaskartaGameUserSettings::ApplyDetectedProfile(const FSaskartaDetectedProfile& P)
{
    SetOverallScalabilityLevel(P.RecommendedLevel);
    SetViewDistanceQuality(P.ViewDistanceQuality);
    SetAntiAliasingQuality(P.AntiAliasingQuality);
    SetShadowQuality(P.ShadowQuality);
    SetGlobalIlluminationQuality(P.GlobalIlluminationQuality);
    SetReflectionQuality(P.ReflectionQuality);
    SetPostProcessingQuality(P.PostProcessQuality);
    SetTextureQuality(P.TextureQuality);
    SetVisualEffectQuality(P.EffectsQuality);
    SetFoliageQuality(P.FoliageQuality);
    SetShadingQuality(P.ShadingQuality);

    // SetOverallScalabilityLevel above wrote the uncapped level's PresetFoliage row; the capped
    // foliage / effects levels decide instead, so write the foliage/cloud values here.
    const int32 FoliageLevel = FMath::Clamp(FMath::Min(P.RecommendedLevel, P.FoliageQuality), 0, 4);
    const int32 CloudLevel = FMath::Clamp(FMath::Min(P.RecommendedLevel, P.EffectsQuality), 0, 4);
    FoliageDensity = PresetFoliage[FoliageLevel].FoliageDensity;
    FoliageDistance = PresetFoliage[FoliageLevel].FoliageDistance;
    CloudMode = PresetFoliage[CloudLevel].CloudMode;

    UpscalerMethod = P.UpscalerMethod;
    UpscalerMode = P.UpscalerMode;
    SetFrameRateLimit(P.FrameRateLimit);
    SetVSyncEnabled(P.bVSync);
}

FSaskartaDetectedProfile USaskartaGameUserSettings::RunAutoDetect()
{
    FSaskartaHardwareSpecs Specs = USaskartaHardwareProfileLibrary::GatherHardwareSpecs();

    // Fills LastCPU/GPUBenchmarkResult (and ScalabilityQuality, which ApplyDetectedProfile
    // then overwrites: the engine thresholds put every modern card on Epic).
    RunHardwareBenchmark(10, 1.f, 1.f);
    Specs.CPUScore = GetLastCPUBenchmarkResult();
    Specs.GPUScore = GetLastGPUBenchmarkResult();

    const FSaskartaDetectedProfile P = USaskartaHardwareProfileLibrary::Recommend(Specs);
    ApplyDetectedProfile(P);
    bAutoDetected = true;
    AutoDetectGPU = Specs.GPUName;
    AutoDetectDriver = Specs.DriverVersion;
    AutoDetectLevel = P.RecommendedLevel;
    AutoDetectVRAMMB = Specs.VRAMMB;
    AutoDetectCPUScore = Specs.CPUScore;
    AutoDetectGPUScore = Specs.GPUScore;
    LastDetected = P;

    UE_LOG(LogSaskartaAutoDetect, Log,
        TEXT("Auto-detect: GPU '%s' (vendor 0x%04X, %s, driver %s, %d MB), CPU '%s' (%d cores / %d threads, %d MHz), %d GB RAM, ")
        TEXT("display %dx%d @ %d Hz, scores CPU %.1f GPU %.1f -> class %d, %s. Groups VD%d AA%d Sh%d GI%d Rf%d PP%d Tx%d Fx%d Fo%d Sd%d, ")
        TEXT("upscaler %d/%d (%.1f %%), cap %.0f, vsync %d. %s"),
        *Specs.GPUName, Specs.VendorId, Specs.bIntegrated ? TEXT("integrated") : TEXT("discrete"), *Specs.DriverVersion, Specs.VRAMMB,
        *Specs.CPUBrand, Specs.CPUCores, Specs.CPUThreads, Specs.CPUClockMHz, Specs.RAMGB,
        Specs.DisplayResolution.X, Specs.DisplayResolution.Y, Specs.RefreshHz, Specs.CPUScore, Specs.GPUScore,
        static_cast<int32>(P.GPUClass), *USaskartaHardwareProfileLibrary::LevelName(P.RecommendedLevel),
        P.ViewDistanceQuality, P.AntiAliasingQuality, P.ShadowQuality, P.GlobalIlluminationQuality, P.ReflectionQuality,
        P.PostProcessQuality, P.TextureQuality, P.EffectsQuality, P.FoliageQuality, P.ShadingQuality,
        P.UpscalerMethod, P.UpscalerMode, P.ScreenPercentage, P.FrameRateLimit, P.bVSync ? 1 : 0, *P.Reasons);

    ApplySettings(false);
    SaveSettings();
    return P;
}

bool USaskartaGameUserSettings::RunAutoDetectIfNeeded()
{
    if (!IsPerfAutomationAllowed())
    {
        return false;
    }
    const FSaskartaHardwareSpecs Specs = USaskartaHardwareProfileLibrary::GatherHardwareSpecs();
    if (ShouldAutoDetect(bHadSavedSettings, bAutoDetected, AutoDetectGPU, Specs.GPUName))
    {
        UE_LOG(LogSaskartaAutoDetect, Log, TEXT("Auto-detect needed (saved settings %d, saved GPU '%s', this GPU '%s')."),
            bHadSavedSettings ? 1 : 0, *AutoDetectGPU, *Specs.GPUName);
        RunAutoDetect();
        return true;
    }
    if (!Specs.GPUName.IsEmpty() && (AutoDetectGPU.IsEmpty() || AutoDetectDriver != Specs.DriverVersion || AutoDetectVRAMMB != Specs.VRAMMB))
    {
        // Existing settings from before this feature, or a driver update: stamp, keep the settings.
        UE_LOG(LogSaskartaAutoDetect, Log, TEXT("Keeping the saved settings; stamping GPU '%s' driver '%s' (was '%s' / '%s')."),
            *Specs.GPUName, *Specs.DriverVersion, *AutoDetectGPU, *AutoDetectDriver);
        AutoDetectGPU = Specs.GPUName;
        AutoDetectDriver = Specs.DriverVersion;
        AutoDetectVRAMMB = Specs.VRAMMB;
        SaveSettings();
    }
    return false;
}

FText USaskartaGameUserSettings::GetQualityWarning() const
{
    const int32 Levels[] = { GetViewDistanceQuality(), GetAntiAliasingQuality(), GetShadowQuality(), GetGlobalIlluminationQuality(),
        GetReflectionQuality(), GetPostProcessingQuality(), GetTextureQuality(), GetVisualEffectQuality(), GetFoliageQuality(), GetShadingQuality() };
    for (const int32 Level : Levels)
    {
        if (Level >= 4)
        {
            return NSLOCTEXT("SaskartaSettings", "CinematicWarning",
                "Cinematic uses the highest quality. Choose a lower preset if performance drops.");
        }
    }
    return FText::GetEmpty();
}

FSaskartaDetectedProfile USaskartaGameUserSettings::GetDetectedProfile() const
{
    if (LastDetected.bValid)
    {
        return LastDetected;
    }
    // Not detected this session: rebuild from this machine plus the saved benchmark scores.
    FSaskartaHardwareSpecs Specs = USaskartaHardwareProfileLibrary::GatherHardwareSpecs();
    Specs.CPUScore = AutoDetectCPUScore;
    Specs.GPUScore = AutoDetectGPUScore;
    return USaskartaHardwareProfileLibrary::Recommend(Specs);
}
