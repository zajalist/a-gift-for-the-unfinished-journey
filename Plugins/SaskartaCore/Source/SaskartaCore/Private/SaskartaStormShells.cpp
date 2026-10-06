// Storm shells gate (task STORM-SHELLS). See SaskartaStormShells.h.
#include "SaskartaStormShells.h"

#include "Materials/MaterialInstance.h"
#include "Engine/Engine.h"
#include "Engine/ExponentialHeightFog.h"
#include "Engine/PostProcessVolume.h"
#include "Engine/World.h"
#include "Components/ExponentialHeightFogComponent.h"
#include "EngineUtils.h"
#include "HAL/IConsoleManager.h"
#include "Materials/MaterialInstanceDynamic.h"
#include "Materials/MaterialInterface.h"
#include "Materials/MaterialParameterCollection.h"
#include "Materials/MaterialParameterCollectionInstance.h"
#include "SaskartaLightingDirector.h"

DEFINE_LOG_CATEGORY_STATIC(LogSaskartaStormShells, Log, All);

static TAutoConsoleVariable<int32> CVarStormShells(
    TEXT("saskarta.stormshells"), 1,
    TEXT("Storm shells (moving dust around the camera, one post-process pass): 0 removes the pass, 1 on (gated by MPC_Saskarta_Sky.StormIntensity)."),
    ECVF_Scalability);

static TAutoConsoleVariable<int32> CVarStormShellsLayers(
    TEXT("saskarta.stormshells.layers"), 4,
    TEXT("Storm shells drawn, nearest first: 4 = 30/55/90/150 m, 3 drops the 150 m shell, 0 = off."),
    ECVF_Scalability);

static TAutoConsoleVariable<int32> CVarStormShellsDetail(
    TEXT("saskarta.stormshells.detail"), 2,
    TEXT("Storm shells with the wisp octave, nearest first (0-4)."),
    ECVF_Scalability);

namespace SaskartaStormShellsGate
{
    static const FName Tag(TEXT("Saskarta_StormShells"));
    static const TCHAR* VolumeName = TEXT("PPV_Saskarta_StormShells");
    static const TCHAR* MaterialName = TEXT("StormShells");  // MI_PP_Saskarta_StormShells (or M_...)
    static const TCHAR* SkyMPCPath = TEXT("/Game/SaskartaGaea/Look/MPC_Saskarta_Sky.MPC_Saskarta_Sky");
    static const FName StormParam(TEXT("StormIntensity"));
    static const FName TierParam(TEXT("Tier"));
    static constexpr double BindRetryS = 1.0;
}

USaskartaStormShellsSubsystem* USaskartaStormShellsSubsystem::GetStormShells(const UObject* WorldContextObject)
{
    const UWorld* World = GEngine ? GEngine->GetWorldFromContextObject(WorldContextObject, EGetWorldErrorMode::ReturnNull) : nullptr;
    return World ? World->GetSubsystem<USaskartaStormShellsSubsystem>() : nullptr;
}

void USaskartaStormShellsSubsystem::SetSuppressed(bool bInSuppressed)
{
    if (bSuppressed == bInSuppressed)
    {
        return;
    }
    bSuppressed = bInSuppressed;
    // Apply the hide immediately: the lighting director can raise StormIntensity
    // during the same frame, before the shell subsystem's next tick.
    if (bSuppressed && Volume.IsValid())
    {
        Volume->BlendWeight = 0.f;
        AppliedWeight = 0.f;
        bPassOn = false;
    }
    UE_LOG(LogSaskartaStormShells, Log, TEXT("Storm shells %s in this world."),
        bSuppressed ? TEXT("suppressed") : TEXT("restored"));
}

bool USaskartaStormShellsSubsystem::ShouldCreateSubsystem(UObject* Outer) const
{
    const UWorld* W = Cast<UWorld>(Outer);
    return W && W->IsGameWorld() && Super::ShouldCreateSubsystem(Outer);
}

void USaskartaStormShellsSubsystem::OnWorldBeginPlay(UWorld& InWorld)
{
    Super::OnWorldBeginPlay(InWorld);
    SkyMPC = LoadObject<UMaterialParameterCollection>(nullptr, SaskartaStormShellsGate::SkyMPCPath);
    bBegunPlay = true;
    NextBindTryS = 0.0;
}

void USaskartaStormShellsSubsystem::Deinitialize()
{
    bBegunPlay = false;
    bSuppressed = false;
    Volume.Reset();
    Mid = nullptr;
    bFogApplied = false;
    Super::Deinitialize();
}

bool USaskartaStormShellsSubsystem::IsTickable() const
{
    return bBegunPlay;
}

TStatId USaskartaStormShellsSubsystem::GetStatId() const
{
    RETURN_QUICK_DECLARE_CYCLE_STAT(USaskartaStormShellsSubsystem, STATGROUP_Tickables);
}

bool USaskartaStormShellsSubsystem::Bind()
{
    if (Volume.IsValid() && Mid)
    {
        return true;
    }
    UWorld* World = GetWorld();
    if (!World)
    {
        return false;
    }
    Volume.Reset();
    auto ChainHas = [](const UMaterialInterface* M, const TCHAR* Needle)
    {
        // A dynamic instance made at runtime has a generated name: walk up to the named parents.
        for (int32 Depth = 0; M && Depth < 8; ++Depth)
        {
            if (M->GetName().Contains(Needle))
            {
                return true;
            }
            const UMaterialInstance* MI = Cast<UMaterialInstance>(M);
            M = MI ? MI->Parent.Get() : nullptr;
        }
        return false;
    };
    // Packaged World Partition games have no labels and renamed actors: also match the volume by its storm material.
    auto CarriesShells = [&ChainHas](const APostProcessVolume* V)
    {
        for (const FWeightedBlendable& B : V->Settings.WeightedBlendables.Array)
        {
            if (ChainHas(Cast<UMaterialInterface>(B.Object), SaskartaStormShellsGate::MaterialName))
            {
                return true;
            }
        }
        return false;
    };
    for (TActorIterator<APostProcessVolume> It(World); It; ++It)
    {
        if (It->Tags.Contains(SaskartaStormShellsGate::Tag) || It->GetName().Contains(SaskartaStormShellsGate::VolumeName)
#if WITH_EDITOR
            || It->GetActorLabel() == SaskartaStormShellsGate::VolumeName
#endif
            || CarriesShells(*It))
        {
            Volume = *It;
            break;
        }
    }
    if (!Volume.IsValid())
    {
        return false;
    }
    Mid = nullptr;
    for (FWeightedBlendable& B : Volume->Settings.WeightedBlendables.Array)
    {
        UMaterialInterface* M = Cast<UMaterialInterface>(B.Object);
        if (!M || !M->GetName().Contains(SaskartaStormShellsGate::MaterialName))
        {
            continue;
        }
        if (UMaterialInstanceDynamic* Existing = Cast<UMaterialInstanceDynamic>(M))
        {
            Mid = Existing;
        }
        else
        {
            Mid = UMaterialInstanceDynamic::Create(M, Volume.Get());
            B.Object = Mid;
        }
        AppliedWeight = -1.f;
        AppliedTier = FSaskartaStormShellTier{-1, -1};
        bFogApplied = false;
        // An interrupted editor A/B capture can leave the saved PPV disabled.
        Volume->bEnabled = true;
        UE_LOG(LogSaskartaStormShells, Log, TEXT("Storm shells bound: %s, material %s."), *Volume->GetName(), *M->GetName());
        return true;
    }
    return false;
}

float USaskartaStormShellsSubsystem::ReadStormIntensity() const
{
    const UWorld* World = GetWorld();
    if (World && SkyMPC)
    {
        if (const UMaterialParameterCollectionInstance* Inst = World->GetParameterCollectionInstance(SkyMPC))
        {
            float Value = 0.f;
            if (Inst->GetScalarParameterValue(SaskartaStormShellsGate::StormParam, Value))
            {
                return Value;
            }
        }
    }
    if (const USaskartaLightingDirector* Director = USaskartaLightingDirector::GetLightingDirector(this))
    {
        return Director->GetEffectiveStormIntensity();
    }
    return 0.f;
}

void USaskartaStormShellsSubsystem::Apply(float Weight, const FSaskartaStormShellTier& Tier)
{
    // Write only on change (memory: render-state recreation stalls; this is a plain property, but keep the habit).
    if (Weight != AppliedWeight)
    {
        Volume->BlendWeight = Weight;
        AppliedWeight = Weight;
        UE_LOG(LogSaskartaStormShells, Verbose, TEXT("Storm shells pass %s (storm %.3f)."), Weight > 0.f ? TEXT("on") : TEXT("off"), LastStorm);
    }
    if (Tier != AppliedTier)
    {
        Mid->SetVectorParameterValue(SaskartaStormShellsGate::TierParam,
            FLinearColor(static_cast<float>(Tier.Shells), static_cast<float>(Tier.DetailShells), 0.f, 0.f));
        AppliedTier = Tier;
    }
}

void USaskartaStormShellsSubsystem::UpdateFogParams()
{
    UWorld* World = GetWorld();
    if (!World || !Mid)
    {
        return;
    }
    for (TActorIterator<AExponentialHeightFog> It(World); It; ++It)
    {
        const UExponentialHeightFogComponent* Fog = It->GetComponent();
        if (!Fog || !Fog->IsVisible())
        {
            continue;
        }
        const FExponentialHeightFogData& Second = Fog->SecondFogData;
        const float FogZ = Fog->GetComponentLocation().Z * 0.01f;
        const FLinearColor Haze(Fog->FogInscatteringLuminance.R, Fog->FogInscatteringLuminance.G,
            Fog->FogInscatteringLuminance.B, Fog->DirectionalInscatteringExponent);
        const FLinearColor HazeDir(Fog->DirectionalInscatteringLuminance.R,
            Fog->DirectionalInscatteringLuminance.G, Fog->DirectionalInscatteringLuminance.B, 0.f);
        // The shader and fog_model.py use metres. UE's fog density/falloff values are per 1000 cm.
        const FLinearColor FogA(Fog->FogDensity / 10.f, Fog->FogHeightFalloff / 10.f,
            Second.FogDensity / 10.f, Second.FogHeightFalloff / 10.f);
        const FLinearColor FogB(FogZ, FogZ + Second.FogHeightOffset * 0.01f,
            Fog->StartDistance * 0.01f, Fog->FogMaxOpacity);
        if (!bFogApplied || !AppliedHaze.Equals(Haze, 1e-4f) || !AppliedHazeDir.Equals(HazeDir, 1e-4f)
            || !AppliedFogA.Equals(FogA, 1e-5f) || !AppliedFogB.Equals(FogB, 1e-3f))
        {
            Mid->SetVectorParameterValue(TEXT("Haze"), Haze);
            Mid->SetVectorParameterValue(TEXT("HazeDir"), HazeDir);
            Mid->SetVectorParameterValue(TEXT("FogA"), FogA);
            Mid->SetVectorParameterValue(TEXT("FogB"), FogB);
            AppliedHaze = Haze;
            AppliedHazeDir = HazeDir;
            AppliedFogA = FogA;
            AppliedFogB = FogB;
            bFogApplied = true;
        }
        return;
    }
}

void USaskartaStormShellsSubsystem::Tick(float DeltaTime)
{
    Super::Tick(DeltaTime);
    UWorld* World = GetWorld();
    if (!World)
    {
        return;
    }
    if (!IsBound())
    {
        const double Now = World->GetRealTimeSeconds();
        if (Now < NextBindTryS)
        {
            return;
        }
        NextBindTryS = Now + SaskartaStormShellsGate::BindRetryS;
        if (!Bind())
        {
            if (!bWarnedUnbound && Now > 10.0)
            {
                UE_LOG(LogSaskartaStormShells, Log, TEXT("Storm shells: no %s with a StormShells blendable in this world; the gate is idle."),
                    SaskartaStormShellsGate::VolumeName);
                bWarnedUnbound = true;
            }
            return;
        }
    }
    LastStorm = ReadStormIntensity();
    bGateOn = SaskartaStormShells::NextGate(bGateOn, LastStorm);
    const FSaskartaStormShellTier Tier = SaskartaStormShells::TierFor(
        CVarStormShells.GetValueOnGameThread(), CVarStormShellsLayers.GetValueOnGameThread(), CVarStormShellsDetail.GetValueOnGameThread());
    const float Weight = bSuppressed ? 0.f : SaskartaStormShells::PassWeight(bGateOn, Tier);
    bPassOn = Weight > 0.f;
    Apply(Weight, Tier);
    UpdateFogParams();
}
