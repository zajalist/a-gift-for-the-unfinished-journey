// USaskartaLightingDirector (Task L7). See the header for the design.

#include "SaskartaLightingDirector.h"

#include "SaskartaFirstLightLogic.h"

#include "Components/DirectionalLightComponent.h"
#include "Components/SkyLightComponent.h"
#include "Engine/SkyLight.h"
#include "Components/ExponentialHeightFogComponent.h"
#include "Components/SkyAtmosphereComponent.h"
#include "Components/VolumetricCloudComponent.h"
#include "Engine/Engine.h"
#include "Engine/PostProcessVolume.h"
#include "Engine/TextureCube.h"
#include "Engine/World.h"
#include "EngineUtils.h"
#include "HAL/IConsoleManager.h"
#include "HAL/PlatformTime.h"
#include "Kismet/GameplayStatics.h"
#include "Kismet/KismetMaterialLibrary.h"
#include "Materials/MaterialParameterCollection.h"
#include "Sound/SoundBase.h"
#include "UObject/UnrealType.h"

DEFINE_LOG_CATEGORY_STATIC(LogSaskartaLook, Log, All);

const FName USaskartaLightingDirector::TagSun(TEXT("Saskarta_Sun"));
const FName USaskartaLightingDirector::TagSky(TEXT("Saskarta_Sky"));
const FName USaskartaLightingDirector::TagClouds(TEXT("Saskarta_Clouds"));
const FName USaskartaLightingDirector::TagFog(TEXT("Saskarta_Fog"));
const FName USaskartaLightingDirector::TagGradeStorm(TEXT("Saskarta_GradeStorm"));
const FName USaskartaLightingDirector::TagGradeClear(TEXT("Saskarta_GradeClear"));

namespace SaskartaLook
{
    static const TCHAR* LookKeysPath = TEXT("/Game/SaskartaGaea/Look/DA_Saskarta_LookKeys.DA_Saskarta_LookKeys");
    static const TCHAR* SkyMPCPath = TEXT("/Game/SaskartaGaea/Look/MPC_Saskarta_Sky.MPC_Saskarta_Sky");
    static const TCHAR* StormAudioDir = TEXT("/Game/SaskartaGaea/Audio/Storm");
    static constexpr int32 ThunderVariants = 4;
    /** Re-scan for missing tagged actors (World Partition may stream them in late) at most this often. */
    static constexpr double ResolveIntervalS = 5.0;
    static constexpr float FlashTickS = 1.f / 60.f;
    /** Sun intensity multiplier at the flash peak: 1 + this. */
    static constexpr float SunFlashBoost = 1.5f;
    /** Flash amplitude while r.Saskarta.ReduceFlashing is 1. */
    static constexpr float ReducedFlashScale = 0.25f;

    static FLinearColor LerpColor(const FLinearColor& A, const FLinearColor& B, float T)
    {
        return FLinearColor(FMath::Lerp(A.R, B.R, T), FMath::Lerp(A.G, B.G, T),
            FMath::Lerp(A.B, B.B, T), FMath::Lerp(A.A, B.A, T));
    }

    static FSaskartaLookKey LerpKey(const FSaskartaLookKey& A, const FSaskartaLookKey& B, float T)
    {
        FSaskartaLookKey R = A;
        R.RoadM = FMath::Lerp(A.RoadM, B.RoadM, T);
        R.SunPitch = FMath::Lerp(A.SunPitch, B.SunPitch, T);
        R.SunYaw = A.SunYaw + FRotator::NormalizeAxis(B.SunYaw - A.SunYaw) * T;
        R.SunIntensityLux = FMath::Lerp(A.SunIntensityLux, B.SunIntensityLux, T);
        R.SunTemperatureK = FMath::Lerp(A.SunTemperatureK, B.SunTemperatureK, T);
        R.MieScatteringScale = FMath::Lerp(A.MieScatteringScale, B.MieScatteringScale, T);
        R.MieAnisotropy = FMath::Lerp(A.MieAnisotropy, B.MieAnisotropy, T);
        R.RayleighScatteringScale = FMath::Lerp(A.RayleighScatteringScale, B.RayleighScatteringScale, T);
        R.CloudCoverage = FMath::Lerp(A.CloudCoverage, B.CloudCoverage, T);
        R.CloudDensity = FMath::Lerp(A.CloudDensity, B.CloudDensity, T);
        R.CloudBaseKm = FMath::Lerp(A.CloudBaseKm, B.CloudBaseKm, T);
        R.CloudTopKm = FMath::Lerp(A.CloudTopKm, B.CloudTopKm, T);
        R.FogDensity = FMath::Lerp(A.FogDensity, B.FogDensity, T);
        R.FogFalloff = FMath::Lerp(A.FogFalloff, B.FogFalloff, T);
        R.FogColor = LerpColor(A.FogColor, B.FogColor, T);
        R.FogStartM = FMath::Lerp(A.FogStartM, B.FogStartM, T);
        R.FogSecondDensity = FMath::Lerp(A.FogSecondDensity, B.FogSecondDensity, T);
        R.FogSecondHeightM = FMath::Lerp(A.FogSecondHeightM, B.FogSecondHeightM, T);
        R.GradeStormWeight = FMath::Lerp(A.GradeStormWeight, B.GradeStormWeight, T);
        R.GradeClearWeight = FMath::Lerp(A.GradeClearWeight, B.GradeClearWeight, T);
        R.StormIntensity = FMath::Lerp(A.StormIntensity, B.StormIntensity, T);
        return R;
    }

    static bool IsFlashReduced()
    {
        const IConsoleVariable* CVar = IConsoleManager::Get().FindConsoleVariable(TEXT("r.Saskarta.ReduceFlashing"));
        return CVar && CVar->GetInt() != 0;
    }

    /** Override blends tick at 30 Hz (the road blend's 0.5 s would step visibly). */
    static constexpr float OverrideTickS = 1.f / 30.f;

    /** Reads a float/double UPROPERTY by name (the level-look capture; no reliance on member access). */
    static bool ReadFloat(const UObject* Object, const TCHAR* Name, float& Out)
    {
        if (!Object)
        {
            return false;
        }
        const FProperty* P = Object->GetClass()->FindPropertyByName(FName(Name));
        if (const FFloatProperty* F = CastField<FFloatProperty>(P))
        {
            Out = F->GetPropertyValue_InContainer(Object);
            return true;
        }
        if (const FDoubleProperty* D = CastField<FDoubleProperty>(P))
        {
            Out = static_cast<float>(D->GetPropertyValue_InContainer(Object));
            return true;
        }
        return false;
    }

    static bool ReadColor(const UObject* Object, const TCHAR* Name, FLinearColor& Out)
    {
        const FStructProperty* P = Object ? CastField<FStructProperty>(Object->GetClass()->FindPropertyByName(FName(Name))) : nullptr;
        if (P && P->Struct == TBaseStructure<FLinearColor>::Get())
        {
            Out = *P->ContainerPtrToValuePtr<FLinearColor>(Object);
            return true;
        }
        return false;
    }

    static float MPCDefault(const UMaterialParameterCollection* MPC, const TCHAR* Name, float Fallback)
    {
        const FCollectionScalarParameter* P = MPC ? MPC->GetScalarParameterByName(FName(Name)) : nullptr;
        return P ? P->DefaultValue : Fallback;
    }
}

// ============================================================================ pure maths

FSaskartaLookKey USaskartaLightingDirector::BlendKeys(const TArray<FSaskartaLookKey>& SortedKeys, float RoadM)
{
    if (SortedKeys.Num() == 0)
    {
        return FSaskartaLookKey();
    }
    if (RoadM <= SortedKeys[0].RoadM)
    {
        return SortedKeys[0];
    }
    const int32 Last = SortedKeys.Num() - 1;
    if (RoadM >= SortedKeys[Last].RoadM)
    {
        return SortedKeys[Last];
    }
    // The segment whose lower key is the last key at or before RoadM. At a key's own
    // RoadM this picks that key with alpha 0, so the result is the key exactly.
    int32 Lo = 0;
    for (int32 i = 0; i < Last; ++i)
    {
        if (SortedKeys[i].RoadM <= RoadM)
        {
            Lo = i;
        }
    }
    const FSaskartaLookKey& A = SortedKeys[Lo];
    const FSaskartaLookKey& B = SortedKeys[Lo + 1];
    if (RoadM == A.RoadM)
    {
        return A;
    }
    const float Span = B.RoadM - A.RoadM;
    const float T = Span > 0.f ? FMath::Clamp((RoadM - A.RoadM) / Span, 0.f, 1.f) : 0.f;
    return SaskartaLook::LerpKey(A, B, T);
}

float USaskartaLightingDirector::SmoothTowards(float Current, float Target, float DtS, float TauS)
{
    if (TauS <= 0.f)
    {
        return Target;
    }
    const float Alpha = 1.f - FMath::Exp(-DtS / TauS);
    return Current + (Target - Current) * Alpha;
}

float USaskartaLightingDirector::ThunderDelaySeconds(float DistanceM)
{
    return DistanceM / SpeedOfSoundMps;
}

bool USaskartaLightingDirector::IsCloseStrike(float DistanceM)
{
    return DistanceM < CloseThunderM;
}

float USaskartaLightingDirector::FlashEnvelope(float TimeS)
{
    if (TimeS <= 0.f)
    {
        return 0.f;
    }
    if (TimeS < FlashRiseS)
    {
        return TimeS / FlashRiseS;
    }
    const float Down = TimeS - FlashRiseS;
    if (Down < FlashFallS)
    {
        return 1.f - Down / FlashFallS;
    }
    return 0.f;
}

float USaskartaLightingDirector::NextLightningIntervalS(float Rand01, float Intensity)
{
    const float Base = FMath::Lerp(LightningIntervalMinS, LightningIntervalMaxS, FMath::Clamp(Rand01, 0.f, 1.f));
    const float Scale = FMath::Clamp(LightningReferenceIntensity / FMath::Max(Intensity, 0.01f), 0.5f, 1.5f);
    return Base * Scale;
}

FSaskartaLookKey USaskartaLightingDirector::ComposeLook(const FSaskartaLookKey& Road, const FSaskartaLookKey& Override, float OverrideAlpha,
    float FogMultiplier, float StormOverrideIntensity)
{
    const float A = FMath::Clamp(OverrideAlpha, 0.f, 1.f);
    FSaskartaLookKey R = A > 0.f ? SaskartaLook::LerpKey(Road, Override, A) : Road;
    R.Name = A >= 0.5f ? Override.Name : Road.Name;
    R.RoadM = Road.RoadM;
    const float M = FMath::Max(0.f, FogMultiplier);
    R.FogDensity *= M;
    R.FogSecondDensity *= M;
    if (StormOverrideIntensity >= 0.f)
    {
        R.StormIntensity = FMath::Clamp(StormOverrideIntensity, 0.f, 1.f);
    }
    return R;
}

const FSaskartaLookKey* USaskartaLightingDirector::FindKeyByName(const TArray<FSaskartaLookKey>& InKeys, FName Name)
{
    return InKeys.FindByPredicate([Name](const FSaskartaLookKey& K) { return K.Name == Name; });
}

float USaskartaLightingDirector::BlendValue(float From, float To, float ElapsedS, float BlendS)
{
    if (BlendS <= 0.f || ElapsedS >= BlendS)
    {
        return To;
    }
    const float T = FMath::Clamp(ElapsedS / BlendS, 0.f, 1.f);
    return FMath::Lerp(From, To, T * T * (3.f - 2.f * T));
}

// ============================================================================ subsystem

bool USaskartaLightingDirector::DoesSupportWorldType(const EWorldType::Type WorldType) const
{
    // Runtime only: the editor world keeps the look saved by apply_look.py.
    return WorldType == EWorldType::Game || WorldType == EWorldType::PIE;
}

USaskartaLightingDirector* USaskartaLightingDirector::GetLightingDirector(const UObject* WorldContextObject)
{
    const UWorld* World = GEngine
        ? GEngine->GetWorldFromContextObject(WorldContextObject, EGetWorldErrorMode::ReturnNull)
        : nullptr;
    return World ? World->GetSubsystem<USaskartaLightingDirector>() : nullptr;
}

void USaskartaLightingDirector::Initialize(FSubsystemCollectionBase& Collection)
{
    Super::Initialize(Collection);
    Random.Initialize(static_cast<int32>(FPlatformTime::Cycles()));
}

void USaskartaLightingDirector::Deinitialize()
{
    ReleasePursuitDustFog(PursuitFogOwner.Get());
    if (UWorld* World = GetWorld())
    {
        World->GetTimerManager().ClearTimer(BlendTimer);
        World->GetTimerManager().ClearTimer(LightningTimer);
        World->GetTimerManager().ClearTimer(FlashTimer);
        World->GetTimerManager().ClearTimer(OverrideTimer);
    }
    Super::Deinitialize();
}

void USaskartaLightingDirector::OnWorldBeginPlay(UWorld& InWorld)
{
    Super::OnWorldBeginPlay(InWorld);
    LoadAssets();
    ResolveActors();
    InWorld.GetTimerManager().SetTimer(BlendTimer, this, &USaskartaLightingDirector::OnBlendTick, BlendIntervalS, true);
    ScheduleNextLightning();
}

void USaskartaLightingDirector::LoadAssets()
{
    if (Keys.Num() == 0)
    {
        if (const USaskartaLookKeys* Asset = LoadObject<USaskartaLookKeys>(nullptr, SaskartaLook::LookKeysPath))
        {
            SetLookKeys(Asset->Keys);
        }
        else
        {
            UE_LOG(LogSaskartaLook, Warning, TEXT("Lighting director: %s not found; run Tools/Look/build_look_keys_asset.py."),
                SaskartaLook::LookKeysPath);
        }
    }
    SkyMPC = LoadObject<UMaterialParameterCollection>(nullptr, SaskartaLook::SkyMPCPath);
    if (!SkyMPC)
    {
        UE_LOG(LogSaskartaLook, Warning, TEXT("Lighting director: %s not found."), SaskartaLook::SkyMPCPath);
    }
    ThunderClose.Reset();
    ThunderRolling.Reset();
    for (int32 i = 1; i <= SaskartaLook::ThunderVariants; ++i)
    {
        const FString Close = FString::Printf(TEXT("%s/SFX_Thunder_Close_%02d.SFX_Thunder_Close_%02d"), SaskartaLook::StormAudioDir, i, i);
        const FString Rolling = FString::Printf(TEXT("%s/SFX_Thunder_Rolling_%02d.SFX_Thunder_Rolling_%02d"), SaskartaLook::StormAudioDir, i, i);
        if (USoundBase* S = LoadObject<USoundBase>(nullptr, *Close))
        {
            ThunderClose.Add(S);
        }
        if (USoundBase* S = LoadObject<USoundBase>(nullptr, *Rolling))
        {
            ThunderRolling.Add(S);
        }
    }
    if (ThunderClose.Num() == 0 || ThunderRolling.Num() == 0)
    {
        UE_LOG(LogSaskartaLook, Warning, TEXT("Lighting director: thunder sounds missing under %s (close %d, rolling %d)."),
            SaskartaLook::StormAudioDir, ThunderClose.Num(), ThunderRolling.Num());
    }
}

void USaskartaLightingDirector::SetLookKeys(const TArray<FSaskartaLookKey>& InKeys)
{
    Keys = InKeys;
    Keys.Sort([](const FSaskartaLookKey& A, const FSaskartaLookKey& B) { return A.RoadM < B.RoadM; });
    bWarnedNoKeys = false;
}

void USaskartaLightingDirector::ResolveActors()
{
    UWorld* World = GetWorld();
    if (!World)
    {
        return;
    }
    LastResolveTimeS = World->GetRealTimeSeconds();
    for (TActorIterator<AActor> It(World); It; ++It)
    {
        AActor* Actor = *It;
        if (!Actor || Actor->Tags.Num() == 0)
        {
            continue;
        }
        if (Actor->ActorHasTag(TagSun))
        {
            SunActor = Actor;
            SunLight = Actor->FindComponentByClass<UDirectionalLightComponent>();
            if (SunLight.IsValid() && !bHasRoadProgress && !bUndrivenDirty && FlashLevel <= 0.f)
            {
                UndrivenSunLux = SunLight->Intensity;
            }
        }
        if (Actor->ActorHasTag(TagSky))
        {
            SkyAtmosphere = Actor->FindComponentByClass<USkyAtmosphereComponent>();
        }
        if (Actor->ActorHasTag(TagClouds))
        {
            Clouds = Actor->FindComponentByClass<UVolumetricCloudComponent>();
        }
        if (Actor->ActorHasTag(TagFog))
        {
            Fog = Actor->FindComponentByClass<UExponentialHeightFogComponent>();
        }
        if (Actor->ActorHasTag(TagGradeStorm))
        {
            GradeStorm = Cast<APostProcessVolume>(Actor);
        }
        if (Actor->ActorHasTag(TagGradeClear))
        {
            GradeClear = Cast<APostProcessVolume>(Actor);
        }
    }
    const bool bAll = SunLight.IsValid() && SkyAtmosphere.IsValid() && Clouds.IsValid() && Fog.IsValid()
        && GradeStorm.IsValid() && GradeClear.IsValid();
    if (!bAll && !bWarnedMissingTags)
    {
        bWarnedMissingTags = true;
        UE_LOG(LogSaskartaLook, Warning,
            TEXT("Lighting director: missing tagged actors: sun %d sky %d clouds %d fog %d storm grade %d clear grade %d (1 = found)."),
            SunLight.IsValid(), SkyAtmosphere.IsValid(), Clouds.IsValid(), Fog.IsValid(), GradeStorm.IsValid(), GradeClear.IsValid());
    }
}

void USaskartaLightingDirector::SetRoadProgress(float RoadM)
{
    TargetRoadM = RoadM;
    if (!bHasRoadProgress)
    {
        // The first report snaps, so the level does not blend in from road metre 0.
        bHasRoadProgress = true;
        SmoothedRoadM = RoadM;
        OnBlendTick();
    }
}

void USaskartaLightingDirector::OnBlendTick()
{
    UWorld* World = GetWorld();
    if (!World)
    {
        return;
    }
    if (!bHasRoadProgress)
    {
        // Nothing drives the road look: the level keeps its saved look, unless an override holds.
        // The sun may stream in late (World Partition): keep looking for it, for lightning's flash pop.
        if (!SunLight.IsValid() && World->GetRealTimeSeconds() - LastResolveTimeS >= SaskartaLook::ResolveIntervalS)
        {
            ResolveActors();
        }
        if (AnyOverride() || bUndrivenDirty)
        {
            ApplyComposite();
        }
        return;
    }
    if (Keys.Num() == 0)
    {
        if (!bWarnedNoKeys)
        {
            bWarnedNoKeys = true;
            UE_LOG(LogSaskartaLook, Warning, TEXT("Lighting director: no look keys; nothing to blend."));
        }
        return;
    }
    const bool bMissing = !SunLight.IsValid() || !SkyAtmosphere.IsValid() || !Clouds.IsValid() || !Fog.IsValid()
        || !GradeStorm.IsValid() || !GradeClear.IsValid();
    if (bMissing && World->GetRealTimeSeconds() - LastResolveTimeS >= SaskartaLook::ResolveIntervalS)
    {
        ResolveActors();
    }

    SmoothedRoadM = SmoothTowards(SmoothedRoadM, TargetRoadM, BlendIntervalS, SmoothingTauS);
    ApplyComposite();
}

// ============================================================================ overrides

bool USaskartaLightingDirector::AnyOverride() const
{
    return bLookOverride || OverrideAlpha > 0.f || !FMath::IsNearlyEqual(FogMult, 1.f) || !FMath::IsNearlyEqual(FogMultTo, 1.f)
        || StormOverride >= 0.f || PursuitFogOwner.IsValid();
}

void USaskartaLightingDirector::SetPursuitDustFog(UObject* Owner, float Weight, float VisibilityM, float CameraHeightCm)
{
    if (!IsValid(Owner) || !FMath::IsFinite(Weight) || !FMath::IsFinite(VisibilityM)
        || !FMath::IsFinite(CameraHeightCm) || (PursuitFogOwner.IsValid() && PursuitFogOwner.Get() != Owner)) return;
    if (!Fog.IsValid()) ResolveActors();
    UExponentialHeightFogComponent* F = Fog.Get();
    if (!F) return;
    if (PursuitOwnedFog.Get() != F)
    {
        RestorePursuitFogFields();
        PursuitOwnedFog = F;
        PursuitPreviousMaxOpacity = F->FogMaxOpacity;
        PursuitPreviousEndDistance = F->EndDistance;
        PursuitPreviousCutoffDistance = F->FogCutoffDistance;
        PursuitPreviousDirectional = F->DirectionalInscatteringLuminance;
        PursuitPreviousSkyAmbient = F->SkyAtmosphereAmbientContributionColorScale;
        PursuitPreviousSkyCaptureStrength = F->SkyLightCaptureAffectsHeightFogStrength;
        PursuitPreviousCubemap = F->InscatteringColorCubemap;
        PursuitPreviousCubemapTint = F->InscatteringTextureTint;
        PursuitPreviousVolumeAlbedo = F->VolumetricFogAlbedo;
        PursuitPreviousVolumeEmissive = F->VolumetricFogEmissive;
        PursuitPreviousVolumeExtinction = F->VolumetricFogExtinctionScale;
        PursuitPreviousVolumeStart = F->VolumetricFogStartDistance;
        PursuitPreviousVolumeNearFade = F->VolumetricFogNearFadeInDistance;
    }
    PursuitFogOwner = Owner;
    PursuitFogWeight = FMath::Clamp(Weight, 0.f, 1.f);
    PursuitVisibilityM = FMath::Clamp(VisibilityM, 20.f, 40.f);
    PursuitCameraHeightCm = CameraHeightCm;
    if (!bHasRoadProgress && !bLevelLookCaptured) CaptureLevelLook();
    // Fog only: do not dirty the sun/sky/clouds or recapture lighting at 10 Hz.
    ApplyFog(CurrentLook.Name.IsNone() && !bHasRoadProgress ? LevelLook : CurrentLook);
}

void USaskartaLightingDirector::RestorePursuitFogFields()
{
    if (UExponentialHeightFogComponent* F = PursuitOwnedFog.Get())
    {
        if (FMath::IsNearlyEqual(F->FogMaxOpacity, PursuitAppliedMaxOpacity)) F->SetFogMaxOpacity(PursuitPreviousMaxOpacity);
        if (FMath::IsNearlyEqual(F->EndDistance, PursuitAppliedEndDistance)) F->SetEndDistance(PursuitPreviousEndDistance);
        if (FMath::IsNearlyEqual(F->FogCutoffDistance, PursuitAppliedCutoffDistance)) F->SetFogCutoffDistance(PursuitPreviousCutoffDistance);
        if (F->DirectionalInscatteringLuminance.Equals(PursuitAppliedDirectional)) F->SetDirectionalInscatteringColor(PursuitPreviousDirectional);
        if (F->SkyAtmosphereAmbientContributionColorScale.Equals(PursuitAppliedSkyAmbient)) F->SetSkyAtmosphereAmbientContributionColorScale(PursuitPreviousSkyAmbient);
        if (FMath::IsNearlyEqual(F->SkyLightCaptureAffectsHeightFogStrength, PursuitAppliedSkyCaptureStrength))
            F->SkyLightCaptureAffectsHeightFogStrength = PursuitPreviousSkyCaptureStrength;
        if (!F->InscatteringColorCubemap) F->SetInscatteringColorCubemap(PursuitPreviousCubemap);
        if (F->InscatteringTextureTint.Equals(PursuitAppliedCubemapTint)) F->SetInscatteringTextureTint(PursuitPreviousCubemapTint);
        if (F->VolumetricFogAlbedo == PursuitAppliedVolumeAlbedo) F->SetVolumetricFogAlbedo(PursuitPreviousVolumeAlbedo);
        if (F->VolumetricFogEmissive.Equals(PursuitAppliedVolumeEmissive)) F->SetVolumetricFogEmissive(PursuitPreviousVolumeEmissive);
        if (FMath::IsNearlyEqual(F->VolumetricFogExtinctionScale, PursuitAppliedVolumeExtinction))
            F->SetVolumetricFogExtinctionScale(PursuitPreviousVolumeExtinction);
        if (FMath::IsNearlyEqual(F->VolumetricFogStartDistance, PursuitAppliedVolumeStart))
            F->SetVolumetricFogStartDistance(PursuitPreviousVolumeStart);
        if (FMath::IsNearlyEqual(F->VolumetricFogNearFadeInDistance, PursuitAppliedVolumeNearFade))
            F->SetVolumetricFogNearFadeInDistance(PursuitPreviousVolumeNearFade);
        F->MarkRenderStateDirty();
    }
    PursuitOwnedFog.Reset();
    PursuitPreviousCubemap = nullptr;
}

void USaskartaLightingDirector::ReleasePursuitDustFog(UObject* Owner)
{
    if (PursuitFogOwner.Get() != Owner) return;
    RestorePursuitFogFields();
    PursuitFogOwner.Reset();
    PursuitFogWeight = 0.f;
    // Density, colour, falloff and start distance belong to this director. Restore
    // its current road/story look, including any changes made during the chase.
    if (Fog.IsValid()) ApplyFog(CurrentLook.Name.IsNone() && !bHasRoadProgress ? LevelLook : CurrentLook);
}

void USaskartaLightingDirector::ApplyFog(const FSaskartaLookKey& Look)
{
    UExponentialHeightFogComponent* F = Fog.Get();
    if (!F) return;
    float Density = Look.FogDensity;
    float Falloff = Look.FogFalloff;
    float SecondDensity = Look.FogSecondDensity;
    float StartCm = Look.FogStartM * 100.f;
    FLinearColor Luminance = Look.FogColor * FogLuminanceScale;
    if (bHasRoadProgress && !PursuitFogOwner.IsValid())
    {
        // Keep the mountain haze at its authored brightness, with a modest
        // ochre cast that connects it to the rock and late sunlight. The owned
        // pursuit fog retains its accepted colour and extinction unchanged.
        const float Mountain = FMath::SmoothStep(2850.f, 3600.f, SmoothedRoadM)
            * (1.f - FMath::SmoothStep(4450.f, 4550.f, SmoothedRoadM));
        if (Mountain > UE_SMALL_NUMBER)
        {
            const float Brightness = Luminance.GetLuminance();
            const FLinearColor Ochre(.55f, .32f, .16f, 1.f);
            const FLinearColor Warm = Ochre * (Brightness / Ochre.GetLuminance());
            Luminance = FMath::Lerp(Luminance, Warm, .38f * Mountain);
        }
    }
    if (PursuitFogOwner.IsValid() && PursuitOwnedFog.Get() == F)
    {
        const float W = PursuitFogWeight;
        // UE5.8 SceneCore divides UI density/falloff by 1000 (world cm).
        // HeightFogCommon's horizontal integral is ln(2), then exp2(-integral).
        // T(d metres)=exp(-Density * ln(2)^2 * d / 10). These native densities
        // are 1.20..2.40, inside the engine's supported 0..10 range.
        constexpr float Ln2 = .69314718056f;
        constexpr float Ln10 = 2.30258509299f;
        const float TargetDensity = 10.f * Ln10 / (Ln2 * Ln2 * PursuitVisibilityM);
        const float HeightCm = F->GetComponentLocation().Z;
        const float PrimaryAtCamera = Look.FogDensity * FMath::Exp2(FMath::Clamp(
            -Look.FogFalloff * .001f * (PursuitCameraHeightCm - HeightCm), -30.f, 30.f));
        const float ShapeT = FMath::Clamp(W / .2f, 0.f, 1.f);
        const float Shape = ShapeT * ShapeT * (3.f - 2.f * ShapeT);
        // Preserve the actual baseline at zero weight and flatten its height
        // profile smoothly in the leading gust. Compensate UI density for the
        // remaining falloff so camera-height extinction grows through the fade,
        // rather than popping in when the high mountain finally enters fog.
        const float CameraDensity = FMath::Lerp(FMath::Clamp(PrimaryAtCamera, 0.f, 10.f), TargetDensity, W);
        Falloff = Look.FogFalloff * (1.f - Shape);
        const float HeightDeltaScaled = (PursuitCameraHeightCm - HeightCm) * .001f;
        if (HeightDeltaScaled > 0.f && CameraDensity > UE_SMALL_NUMBER)
            Falloff = FMath::Min(Falloff, FMath::Max(0.f, FMath::Log2(10.f / CameraDensity) / HeightDeltaScaled));
        Density = CameraDensity * FMath::Exp2(FMath::Clamp(Falloff * HeightDeltaScaled, -30.f, 30.f));
        SecondDensity = Look.FogSecondDensity * (1.f - W);
        StartCm *= 1.f - Shape;
        if (W <= 0.f)
        {
            Density = Look.FogDensity;
            Falloff = Look.FogFalloff;
        }
        Luminance = FMath::Lerp(Luminance, FLinearColor(.028f, .025f, .020f), W);
        PursuitAppliedMaxOpacity = FMath::Lerp(PursuitPreviousMaxOpacity, .998f, W);
        PursuitAppliedDirectional = PursuitPreviousDirectional * (1.f - .92f * W);
        PursuitAppliedSkyAmbient = PursuitPreviousSkyAmbient * (1.f - W);
        PursuitAppliedSkyCaptureStrength = PursuitPreviousSkyCaptureStrength * (1.f - W);
        F->SetFogMaxOpacity(PursuitAppliedMaxOpacity);
        F->SetDirectionalInscatteringColor(PursuitAppliedDirectional);
        F->SetSkyAtmosphereAmbientContributionColorScale(PursuitAppliedSkyAmbient);
        auto Unlimit = [Shape](float Previous)
        {
            return Previous <= 0.f || Shape >= 1.f ? 0.f
                : FMath::Lerp(Previous, FMath::Max(Previous, 10000000.f), Shape);
        };
        PursuitAppliedEndDistance = Unlimit(PursuitPreviousEndDistance);
        PursuitAppliedCutoffDistance = Unlimit(PursuitPreviousCutoffDistance);
        F->SetEndDistance(PursuitAppliedEndDistance);
        F->SetFogCutoffDistance(PursuitAppliedCutoffDistance);
        PursuitAppliedCubemapTint = PursuitPreviousCubemapTint;
        if (PursuitPreviousCubemap)
        {
            // Native fog has no cubemap/constant-colour crossfade. Meet at zero
            // luminance before changing source, in both entry and exit directions,
            // so even a cubemap-authored baseline cannot pop to a new fog colour.
            if (W < .2f)
            {
                PursuitAppliedCubemapTint *= 1.f - Shape;
                F->SetInscatteringColorCubemap(PursuitPreviousCubemap);
            }
            else
            {
                PursuitAppliedCubemapTint = FLinearColor::Black;
                F->SetInscatteringColorCubemap(nullptr);
                const float ColourT = FMath::Clamp((W - .2f) / .8f, 0.f, 1.f);
                Luminance = FLinearColor(.028f, .025f, .020f) * (ColourT * ColourT * (3.f - 2.f * ColourT));
            }
        }
        else F->SetInscatteringColorCubemap(nullptr);
        F->SetInscatteringTextureTint(PursuitAppliedCubemapTint);
        F->SkyLightCaptureAffectsHeightFogStrength = PursuitAppliedSkyCaptureStrength;
        // VFog is integrated with natural exp(-extinction*cm), unlike the
        // analytic exp2(-density*ln(2)*cm). Match them inside the existing grid.
        // Absorbing neutral dust also prevents direct sun/backlighting turning
        // the volume into a luminous white cloud above the analytic brown haze.
        const FLinearColor Albedo = FMath::Lerp(FLinearColor(PursuitPreviousVolumeAlbedo),
            FLinearColor(.22f, .20f, .17f), W);
        PursuitAppliedVolumeAlbedo = W <= 0.f ? PursuitPreviousVolumeAlbedo : Albedo.ToFColor(true);
        PursuitAppliedVolumeEmissive = PursuitPreviousVolumeEmissive * (1.f - W);
        PursuitAppliedVolumeExtinction = FMath::Lerp(PursuitPreviousVolumeExtinction, Ln2 * Ln2, W);
        F->SetVolumetricFogAlbedo(PursuitAppliedVolumeAlbedo);
        F->SetVolumetricFogEmissive(PursuitAppliedVolumeEmissive);
        F->SetVolumetricFogExtinctionScale(PursuitAppliedVolumeExtinction);
        PursuitAppliedVolumeStart = PursuitPreviousVolumeStart * (1.f - Shape);
        PursuitAppliedVolumeNearFade = PursuitPreviousVolumeNearFade * (1.f - Shape);
        F->SetVolumetricFogStartDistance(PursuitAppliedVolumeStart);
        F->SetVolumetricFogNearFadeInDistance(PursuitAppliedVolumeNearFade);
    }
    F->SetFogDensity(FMath::Clamp(Density, 0.f, 10.f));
    F->SetFogHeightFalloff(FMath::Clamp(Falloff, 0.f, 2.f));
    F->SetFogInscatteringColor(Luminance);
    F->SetStartDistance(StartCm);
    F->SetSecondFogDensity(SecondDensity);
    F->SetSecondFogHeightOffset(Look.FogSecondHeightM * 100.f);
}

FSaskartaLookKey USaskartaLightingDirector::EffectiveOverrideKey() const
{
    return OverrideMix >= 1.f ? OverrideKey : SaskartaLook::LerpKey(OverrideFromKey, OverrideKey, FMath::Clamp(OverrideMix, 0.f, 1.f));
}

void USaskartaLightingDirector::ApplyComposite()
{
    FSaskartaLookKey Road;
    if (bHasRoadProgress && Keys.Num() > 0)
    {
        Road = BlendKeys(Keys, SmoothedRoadM);
    }
    else
    {
        if (!bLevelLookCaptured)
        {
            CaptureLevelLook();
        }
        Road = LevelLook;
    }
    const bool bOverrides = AnyOverride();
    CurrentLook = ComposeLook(Road, EffectiveOverrideKey(), OverrideAlpha, FogMult, StormOverride);
    StormIntensity = CurrentLook.StormIntensity;
    if (!bHasRoadProgress)
    {
        // Applying the level's own look once more (all overrides released) restores it; after that the level is left alone.
        bUndrivenDirty = true;
        ApplyLook(CurrentLook);
        bUndrivenDirty = bOverrides;
        if (!bOverrides)
        {
            UE_LOG(LogSaskartaLook, Log, TEXT("Lighting director: overrides released; the level look is restored."));
        }
        return;
    }
    ApplyLook(CurrentLook);
}

void USaskartaLightingDirector::CaptureLevelLook()
{
    // Defaults for anything that cannot be read: the first key (or the struct defaults).
    LevelLook = Keys.Num() > 0 ? Keys[0] : FSaskartaLookKey();
    LevelLook.Name = TEXT("Level");
    if (const AActor* Sun = SunActor.Get())
    {
        const FRotator R = Sun->GetActorRotation();
        LevelLook.SunPitch = R.Pitch;
        LevelLook.SunYaw = R.Yaw;
    }
    if (const UDirectionalLightComponent* Light = SunLight.Get())
    {
        LevelLook.SunIntensityLux = UndrivenSunLux >= 0.f ? UndrivenSunLux : Light->Intensity;
        SaskartaLook::ReadFloat(Light, TEXT("Temperature"), LevelLook.SunTemperatureK);
    }
    if (const USkyAtmosphereComponent* Sky = SkyAtmosphere.Get())
    {
        SaskartaLook::ReadFloat(Sky, TEXT("MieScatteringScale"), LevelLook.MieScatteringScale);
        SaskartaLook::ReadFloat(Sky, TEXT("MieAnisotropy"), LevelLook.MieAnisotropy);
        SaskartaLook::ReadFloat(Sky, TEXT("RayleighScatteringScale"), LevelLook.RayleighScatteringScale);
    }
    if (const UVolumetricCloudComponent* Cloud = Clouds.Get())
    {
        float Bottom = LevelLook.CloudBaseKm;
        float Height = LevelLook.CloudTopKm - LevelLook.CloudBaseKm;
        SaskartaLook::ReadFloat(Cloud, TEXT("LayerBottomAltitude"), Bottom);
        SaskartaLook::ReadFloat(Cloud, TEXT("LayerHeight"), Height);
        LevelLook.CloudBaseKm = Bottom;
        LevelLook.CloudTopKm = Bottom + Height;
    }
    if (const UExponentialHeightFogComponent* F = Fog.Get())
    {
        SaskartaLook::ReadFloat(F, TEXT("FogDensity"), LevelLook.FogDensity);
        SaskartaLook::ReadFloat(F, TEXT("FogHeightFalloff"), LevelLook.FogFalloff);
        float StartCm = LevelLook.FogStartM * 100.f;
        if (SaskartaLook::ReadFloat(F, TEXT("StartDistance"), StartCm))
        {
            LevelLook.FogStartM = StartCm / 100.f;
        }
        FLinearColor Inscatter;
        if (SaskartaLook::ReadColor(F, TEXT("FogInscatteringLuminance"), Inscatter) || SaskartaLook::ReadColor(F, TEXT("FogInscatteringColor"), Inscatter))
        {
            LevelLook.FogColor = Inscatter * (1.f / FogLuminanceScale);
            LevelLook.FogColor.A = 1.f;
        }
        if (const FStructProperty* Prop = FindFProperty<FStructProperty>(UExponentialHeightFogComponent::StaticClass(), TEXT("SecondFogData")))
        {
            if (Prop->Struct && Prop->Struct->GetFName() == FName(TEXT("ExponentialHeightFogData")))
            {
                const FExponentialHeightFogData* Second = Prop->ContainerPtrToValuePtr<FExponentialHeightFogData>(F);
                LevelLook.FogSecondDensity = Second->FogDensity;
                LevelLook.FogSecondHeightM = Second->FogHeightOffset / 100.f;
            }
        }
    }
    if (const APostProcessVolume* Storm = GradeStorm.Get())
    {
        LevelLook.GradeStormWeight = Storm->BlendWeight;
    }
    if (const APostProcessVolume* Clear = GradeClear.Get())
    {
        LevelLook.GradeClearWeight = Clear->BlendWeight;
    }
    LevelLook.CloudCoverage = SaskartaLook::MPCDefault(SkyMPC, TEXT("Coverage"), LevelLook.CloudCoverage);
    LevelLook.CloudDensity = SaskartaLook::MPCDefault(SkyMPC, TEXT("Density"), LevelLook.CloudDensity);
    LevelLook.StormIntensity = SaskartaLook::MPCDefault(SkyMPC, TEXT("StormIntensity"), LevelLook.StormIntensity);
    // Captured for good once the sun is known; before that, what was read is used but read again next time.
    bLevelLookCaptured = SunLight.IsValid();
    UE_LOG(LogSaskartaLook, Log, TEXT("Lighting director: level look captured (sun %d, sun %.2f lux, fog %.4f, storm %.2f)."),
        SunLight.IsValid() ? 1 : 0, LevelLook.SunIntensityLux, LevelLook.FogDensity, LevelLook.StormIntensity);
}

void USaskartaLightingDirector::BeginLookOverride(const FSaskartaLookKey& Key, float BlendS)
{
    UWorld* World = GetWorld();
    const double T = World ? World->GetTimeSeconds() : 0.0;
    if (OverrideAlpha > 0.f)
    {
        // An override already shows: blend from what it shows now to the new key, at full weight.
        OverrideFromKey = EffectiveOverrideKey();
        OverrideMix = 0.f;
        OverrideMixStartS = T;
        OverrideMixBlendS = FMath::Max(0.f, BlendS);
    }
    else
    {
        OverrideFromKey = Key;
        OverrideMix = 1.f;
        OverrideMixBlendS = 0.f;
    }
    OverrideKey = Key;
    bLookOverride = true;
    OverrideAlphaFrom = OverrideAlpha;
    OverrideAlphaTo = 1.f;
    OverrideBlendStartS = T;
    OverrideBlendS = FMath::Max(0.f, BlendS);
    UE_LOG(LogSaskartaLook, Log, TEXT("Lighting director: look override %s over %.1f s."), *Key.Name.ToString(), BlendS);
    StartOverrideTick();
}

bool USaskartaLightingDirector::PushLookOverride(FName LookKey, float BlendS)
{
    const FSaskartaLookKey* Key = FindKeyByName(Keys, LookKey);
    if (!Key)
    {
        UE_LOG(LogSaskartaLook, Warning, TEXT("Lighting director: PushLookOverride %s: no look key by that name (%d keys)."), *LookKey.ToString(), Keys.Num());
        return false;
    }
    BeginLookOverride(*Key, BlendS);
    return true;
}

void USaskartaLightingDirector::PushLookOverrideAtRoadM(float RoadM, float BlendS)
{
    if (Keys.Num() == 0)
    {
        UE_LOG(LogSaskartaLook, Warning, TEXT("Lighting director: PushLookOverrideAtRoadM: no look keys."));
        return;
    }
    FSaskartaLookKey Key = BlendKeys(Keys, RoadM);
    Key.Name = FName(*FString::Printf(TEXT("Road%.0f"), RoadM));
    BeginLookOverride(Key, BlendS);
}

bool USaskartaLightingDirector::PlayDawn(float DurationS, float ClearAtS, float HorizonPitch, float SunYaw)
{
    UWorld* World = GetWorld();
    if (!World)
    {
        return false;
    }
    if (!bLookOverride && !bHasRoadProgress && !bLevelLookCaptured)
    {
        CaptureLevelLook();
    }
    FSaskartaDawnParams P;
    P.SunYaw = SunYaw;
    P.HorizonPitch = HorizonPitch;
    // Start from what shows now (PreDawn at the mast, or an override), yawed to the dawn's bearing.
    const FSaskartaLookKey Now = CurrentLook.Name.IsNone() && !bHasRoadProgress ? LevelLook : CurrentLook;
    OverrideFromKey = FSaskartaFirstLight::MakeStartKey(Now, P);
    OverrideKey = FSaskartaFirstLight::MakeDawnKey(Now, P);
    OverrideMix = 0.f;
    const double T = World->GetTimeSeconds();
    OverrideMixStartS = T;
    OverrideMixBlendS = FMath::Max(0.f, DurationS);
    bLookOverride = true;
    OverrideAlphaFrom = OverrideAlpha;
    OverrideAlphaTo = 1.f;
    OverrideBlendStartS = T;
    OverrideBlendS = OverrideAlpha >= 1.f ? 0.f : 1.f;
    bDawn = true;
    DawnStartS = T;
    DawnDurationS = FMath::Max(0.f, DurationS);
    DawnClearAtS = ClearAtS;
    DawnClearMix = FSaskartaFirstLight::ClearMix(OverrideFromKey.SunPitch, OverrideKey.SunPitch, HorizonPitch);
    DawnPrevElapsedS = -1.f;
    DawnLastApplyS = -1.0;
    UE_LOG(LogSaskartaLook, Log, TEXT("Lighting director: first light over %.0f s, disc clears at %.0f s (pitch %.1f -> %.1f, horizon %.1f, yaw %.1f)."),
        DurationS, ClearAtS, OverrideFromKey.SunPitch, OverrideKey.SunPitch, HorizonPitch, SunYaw);
    StartOverrideTick();
    return true;
}

void USaskartaLightingDirector::DawnTick(double NowS)
{
    DawnLastApplyS = NowS;
    const float Elapsed = static_cast<float>(NowS - DawnStartS);
    if (FSaskartaFirstLight::RecaptureDue(DawnPrevElapsedS, Elapsed))
    {
        USkyLightComponent* Sky = DawnSkyLight.Get();
        if (!Sky && GetWorld())
        {
            for (TActorIterator<ASkyLight> It(GetWorld()); It; ++It)
            {
                Sky = It->GetLightComponent();
                break;
            }
            DawnSkyLight = Sky;
        }
        // A real-time capture follows the sky by itself; a static one is recaptured in steps only.
        if (Sky && !Sky->IsRealTimeCaptureEnabled())
        {
            Sky->RecaptureSky();
        }
    }
    DawnPrevElapsedS = Elapsed;
}

void USaskartaLightingDirector::PopLookOverride(float BlendS)
{
    if (!bLookOverride && OverrideAlpha <= 0.f)
    {
        return;
    }
    UWorld* World = GetWorld();
    bDawn = false;
    bLookOverride = false;
    OverrideAlphaFrom = OverrideAlpha;
    OverrideAlphaTo = 0.f;
    OverrideBlendStartS = World ? World->GetTimeSeconds() : 0.0;
    OverrideBlendS = FMath::Max(0.f, BlendS);
    UE_LOG(LogSaskartaLook, Log, TEXT("Lighting director: look override released over %.1f s."), BlendS);
    StartOverrideTick();
}

void USaskartaLightingDirector::PushFogOverride(float Multiplier, float BlendS)
{
    UWorld* World = GetWorld();
    FogMultFrom = FogMult;
    FogMultTo = FMath::Max(0.f, Multiplier);
    FogBlendStartS = World ? World->GetTimeSeconds() : 0.0;
    FogBlendS = FMath::Max(0.f, BlendS);
    UE_LOG(LogSaskartaLook, Log, TEXT("Lighting director: fog x%.2f over %.1f s."), FogMultTo, BlendS);
    StartOverrideTick();
}

void USaskartaLightingDirector::SetStormOverride(float Intensity)
{
    StormOverride = Intensity < 0.f ? -1.f : FMath::Clamp(Intensity, 0.f, 1.f);
    UE_LOG(LogSaskartaLook, Log, TEXT("Lighting director: storm override %.2f%s."), StormOverride, StormOverride < 0.f ? TEXT(" (released)") : TEXT(""));
    ApplyComposite();
}

void USaskartaLightingDirector::StartOverrideTick()
{
    if (UWorld* World = GetWorld())
    {
        if (!World->GetTimerManager().IsTimerActive(OverrideTimer))
        {
            World->GetTimerManager().SetTimer(OverrideTimer, this, &USaskartaLightingDirector::OnOverrideTick, SaskartaLook::OverrideTickS, true);
        }
        OnOverrideTick();
    }
}

void USaskartaLightingDirector::OnOverrideTick()
{
    UWorld* World = GetWorld();
    if (!World)
    {
        return;
    }
    const double T = World->GetTimeSeconds();
    const float AlphaElapsed = static_cast<float>(T - OverrideBlendStartS);
    const float MixElapsed = static_cast<float>(T - OverrideMixStartS);
    const float FogElapsed = static_cast<float>(T - FogBlendStartS);
    OverrideAlpha = BlendValue(OverrideAlphaFrom, OverrideAlphaTo, AlphaElapsed, OverrideBlendS);
    FogMult = BlendValue(FogMultFrom, FogMultTo, FogElapsed, FogBlendS);
    if (bDawn)
    {
        const bool bOthersDone = AlphaElapsed >= OverrideBlendS && FogElapsed >= FogBlendS;
        const float DawnElapsed = static_cast<float>(T - DawnStartS);
        // Only the slow dawn moves: apply at ApplyIntervalS, not 30 Hz (each apply dirties the sky and clouds).
        if (bOthersDone && DawnElapsed < DawnDurationS && DawnLastApplyS >= 0.0 && T - DawnLastApplyS < FSaskartaFirstLight::ApplyIntervalS)
        {
            return;
        }
        OverrideMix = FSaskartaFirstLight::DawnMix(DawnElapsed, DawnDurationS, DawnClearAtS, DawnClearMix);
        DawnTick(T);
        if (bOthersDone && DawnElapsed >= DawnDurationS)
        {
            ApplyComposite();
            World->GetTimerManager().ClearTimer(OverrideTimer);
            UE_LOG(LogSaskartaLook, Log, TEXT("Lighting director: first light done (%.1f s)."), DawnElapsed);
            return;
        }
        ApplyComposite();
        return;
    }
    OverrideMix = BlendValue(0.f, 1.f, MixElapsed, OverrideMixBlendS);
    const bool bDone = AlphaElapsed >= OverrideBlendS && MixElapsed >= OverrideMixBlendS && FogElapsed >= FogBlendS;
    ApplyComposite();
    if (bDone)
    {
        World->GetTimerManager().ClearTimer(OverrideTimer);
    }
}

void USaskartaLightingDirector::ApplyLook(const FSaskartaLookKey& Look)
{
    if (AActor* Sun = SunActor.Get())
    {
        Sun->SetActorRotation(FRotator(Look.SunPitch, Look.SunYaw, 0.f));
    }
    if (UDirectionalLightComponent* Light = SunLight.Get())
    {
        Light->SetTemperature(Look.SunTemperatureK);
    }
    ApplySunIntensity();

    if (USkyAtmosphereComponent* Sky = SkyAtmosphere.Get())
    {
        Sky->SetMieScatteringScale(Look.MieScatteringScale);
        Sky->SetMieAnisotropy(Look.MieAnisotropy);
        Sky->SetRayleighScatteringScale(Look.RayleighScatteringScale);
    }

    if (UVolumetricCloudComponent* Cloud = Clouds.Get())
    {
        Cloud->SetLayerBottomAltitude(Look.CloudBaseKm);
        Cloud->SetLayerHeight(FMath::Max(Look.CloudTopKm - Look.CloudBaseKm, 0.01f));
    }

    ApplyFog(Look);

    if (APostProcessVolume* Storm = GradeStorm.Get())
    {
        Storm->BlendWeight = FMath::Clamp(Look.GradeStormWeight, 0.f, 1.f);
    }
    if (APostProcessVolume* Clear = GradeClear.Get())
    {
        Clear->BlendWeight = FMath::Clamp(Look.GradeClearWeight, 0.f, 1.f);
    }

    if (SkyMPC)
    {
        UWorld* World = GetWorld();
        UKismetMaterialLibrary::SetScalarParameterValue(World, SkyMPC, TEXT("Coverage"), Look.CloudCoverage);
        UKismetMaterialLibrary::SetScalarParameterValue(World, SkyMPC, TEXT("Density"), Look.CloudDensity);
        UKismetMaterialLibrary::SetScalarParameterValue(World, SkyMPC, TEXT("BaseAltitude"), Look.CloudBaseKm);
        UKismetMaterialLibrary::SetScalarParameterValue(World, SkyMPC, TEXT("StormIntensity"), Look.StormIntensity);
    }
}

float USaskartaLightingDirector::EffectiveStormIntensity() const
{
    if (StormOverride >= 0.f)
    {
        return StormOverride;
    }
    if (bHasRoadProgress || bUndrivenDirty)
    {
        return StormIntensity;
    }
    if (SkyMPC)
    {
        if (const FCollectionScalarParameter* P = SkyMPC->GetScalarParameterByName(TEXT("StormIntensity")))
        {
            return P->DefaultValue;
        }
    }
    return 0.f;
}

void USaskartaLightingDirector::ApplySunIntensity()
{
    if (UDirectionalLightComponent* Light = SunLight.Get())
    {
        // Driven (road progress, or an override on the level look): the composed look's sun; else the level's own.
        const float BaseLux = (bHasRoadProgress || bUndrivenDirty) ? CurrentLook.SunIntensityLux : UndrivenSunLux;
        if (BaseLux < 0.f)
        {
            return;
        }
        Light->SetIntensity(BaseLux * (1.f + SaskartaLook::SunFlashBoost * FlashLevel));
    }
}

// ============================================================================ lightning

void USaskartaLightingDirector::ScheduleNextLightning()
{
    UWorld* World = GetWorld();
    if (!World)
    {
        return;
    }
    // Checked again at fire time: below the threshold the strike is skipped and rescheduled,
    // so lightning resumes on its own when the player walks back into a storm key.
    const float Interval = NextLightningIntervalS(Random.GetFraction(), FMath::Max(EffectiveStormIntensity(), LightningMinIntensity));
    World->GetTimerManager().SetTimer(LightningTimer, this, &USaskartaLightingDirector::OnLightning, Interval, false);
}

void USaskartaLightingDirector::OnLightning()
{
    UWorld* World = GetWorld();
    if (!World)
    {
        return;
    }
    // LANE4: lightning also runs when nothing drives road progress (the saved level look is then the
    // look, and its storm level is the MPC default), so the storm flashes and thunders in gameplay.
    if (EffectiveStormIntensity() > LightningMinIntensity && (bHasRoadProgress || UndrivenSunLux >= 0.f))
    {
        const float DistanceM = Random.FRandRange(StrikeMinM, StrikeMaxM);

        FlashStartTimeS = World->GetTimeSeconds();
        World->GetTimerManager().SetTimer(FlashTimer, this, &USaskartaLightingDirector::OnFlashTick, SaskartaLook::FlashTickS, true);
        OnFlashTick();

        TWeakObjectPtr<USaskartaLightingDirector> WeakThis(this);
        FTimerHandle ThunderHandle;
        World->GetTimerManager().SetTimer(ThunderHandle,
            FTimerDelegate::CreateLambda([WeakThis, DistanceM]()
            {
                if (USaskartaLightingDirector* Self = WeakThis.Get())
                {
                    Self->PlayThunder(DistanceM);
                }
            }),
            ThunderDelaySeconds(DistanceM), false);

        OnLightningStrike.Broadcast(DistanceM, IsCloseStrike(DistanceM));
    }
    ScheduleNextLightning();
}

void USaskartaLightingDirector::OnFlashTick()
{
    UWorld* World = GetWorld();
    if (!World)
    {
        return;
    }
    const float T = static_cast<float>(World->GetTimeSeconds() - FlashStartTimeS);
    const float Scale = SaskartaLook::IsFlashReduced() ? SaskartaLook::ReducedFlashScale : 1.f;
    FlashLevel = FlashEnvelope(T) * Scale;
    const bool bDone = T >= FlashRiseS + FlashFallS;
    if (bDone)
    {
        FlashLevel = 0.f;
        World->GetTimerManager().ClearTimer(FlashTimer);
    }
    if (SkyMPC)
    {
        UKismetMaterialLibrary::SetScalarParameterValue(World, SkyMPC, TEXT("LightningFlash"), FlashLevel);
    }
    ApplySunIntensity();
}

void USaskartaLightingDirector::PlayThunder(float DistanceM)
{
    UWorld* World = GetWorld();
    if (!World || !bPlayThunder)
    {
        return;
    }
    const bool bClose = IsCloseStrike(DistanceM);
    const TArray<TObjectPtr<USoundBase>>& Family = bClose ? ThunderClose : ThunderRolling;
    if (Family.Num() == 0)
    {
        return;
    }
    USoundBase* Sound = Family[Random.RandRange(0, Family.Num() - 1)];
    // Close strikes are louder and sharper; rolling thunder fades with distance.
    const float Far = FMath::Clamp((DistanceM - CloseThunderM) / (StrikeMaxM - CloseThunderM), 0.f, 1.f);
    const float Volume = bClose ? 1.f : FMath::Lerp(0.85f, 0.4f, Far);
    const float Pitch = bClose ? Random.FRandRange(0.97f, 1.05f) : Random.FRandRange(0.9f, 1.0f);
    UGameplayStatics::PlaySound2D(World, Sound, Volume, Pitch);
}
