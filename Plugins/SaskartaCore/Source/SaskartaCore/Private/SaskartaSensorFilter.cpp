// LANE5 (queued): see SaskartaSensorFilter.h and README.md in cpp_queue/lane5_sensorfilter.
#include "SaskartaSensorFilter.h"
#include "Materials/MaterialInstance.h"
#include "SaskartaDroneSequence.h"

#include "Engine/PostProcessVolume.h"
#include "Engine/World.h"
#include "EngineUtils.h"
#include "HAL/IConsoleManager.h"
#include "Materials/MaterialInstanceDynamic.h"
#include "SaskartaEventRunner.h"
#include "TimerManager.h"

namespace SaskartaSensor
{
    static const FName Tag(TEXT("Saskarta.SensorPPV"));
    static const TCHAR* VolumeName = TEXT("PPV_Saskarta_Sensor");
    static const TCHAR* MaterialName = TEXT("MI_PP_SensorCRT");
    static const TCHAR* GlassMaterialName = TEXT("MI_PP_SensorGlass");
    static const FName Param(TEXT("Amount"));
    static constexpr float PollS = 0.25f;
    static constexpr float Levels[4] = {0.f, 0.35f, 0.6f, 0.85f};
}

bool USaskartaSensorFilterSubsystem::ShouldCreateSubsystem(UObject* Outer) const
{
    const UWorld* W = Cast<UWorld>(Outer);
    return W && W->IsGameWorld();
}

void USaskartaSensorFilterSubsystem::OnWorldBeginPlay(UWorld& InWorld)
{
    Super::OnWorldBeginPlay(InWorld);
    if (USaskartaEventRunner* Runner = USaskartaEventRunner::GetEventRunner(this))
    {
        BoundRunner = Runner;
        Runner->OnCinematicStarted.AddUniqueDynamic(this, &USaskartaSensorFilterSubsystem::HandleCinematicChanged);
        Runner->OnCinematicFinished.AddUniqueDynamic(this, &USaskartaSensorFilterSubsystem::HandleCinematicChanged);
        Runner->OnModeChanged.AddUniqueDynamic(this, &USaskartaSensorFilterSubsystem::HandleModeChanged);
    }
    Poll();
    InWorld.GetTimerManager().SetTimer(Timer, this, &USaskartaSensorFilterSubsystem::Poll, SaskartaSensor::PollS, true);
}

void USaskartaSensorFilterSubsystem::Deinitialize()
{
    if (USaskartaEventRunner* Runner = BoundRunner.Get())
    {
        Runner->OnCinematicStarted.RemoveDynamic(this, &USaskartaSensorFilterSubsystem::HandleCinematicChanged);
        Runner->OnCinematicFinished.RemoveDynamic(this, &USaskartaSensorFilterSubsystem::HandleCinematicChanged);
        Runner->OnModeChanged.RemoveDynamic(this, &USaskartaSensorFilterSubsystem::HandleModeChanged);
    }
    BoundRunner.Reset();
    if (UWorld* W = GetWorld())
    {
        W->GetTimerManager().ClearTimer(Timer);
    }
    Volume.Reset();
    Mid = nullptr;
    GlassMid = nullptr;
    CrtIndex = INDEX_NONE;
    GlassIndex = INDEX_NONE;
    Super::Deinitialize();
}

void USaskartaSensorFilterSubsystem::HandleCinematicChanged(FName Id)
{
    // Camera changes take effect this frame; the setting/streaming poll is too
    // slow for the first human-eye frame or a relay handover.
    Poll();
}

void USaskartaSensorFilterSubsystem::HandleModeChanged(FName Mode, bool bOn)
{
    Poll();
}

float USaskartaSensorFilterSubsystem::AmountFor(int32 Level, FName FlowState)
{
    static const FName On[] = {FName(TEXT("Playing")), FName(TEXT("Carrier")), FName(TEXT("Collapsing")), FName(TEXT("Booting")), FName(TEXT("Rebooting"))};
    bool bCarrierCamera = false;
    for (const FName& N : On)
    {
        bCarrierCamera |= (N == FlowState);
    }
    return bCarrierCamera ? SaskartaSensor::Levels[FMath::Clamp(Level, 0, 3)] : 0.f;
}

bool USaskartaSensorFilterSubsystem::Bind()
{
    if (Volume.IsValid() && Mid)
    {
        return true;
    }
    // A packaged World Partition game has no actor labels and renames actors, so the volume is also found by what
    // it carries: the sensor (CRT) or glass material among its blendables (the glass vanished in the first package).
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
    auto CarriesSensor = [&ChainHas](const APostProcessVolume* V)
    {
        for (const FWeightedBlendable& B : V->Settings.WeightedBlendables.Array)
        {
            const UMaterialInterface* M = Cast<UMaterialInterface>(B.Object);
            if (ChainHas(M, SaskartaSensor::MaterialName) || ChainHas(M, SaskartaSensor::GlassMaterialName))
            {
                return true;
            }
        }
        return false;
    };
    for (TActorIterator<APostProcessVolume> It(GetWorld()); It; ++It)
    {
        if (It->Tags.Contains(SaskartaSensor::Tag) || It->GetName().Contains(SaskartaSensor::VolumeName)
#if WITH_EDITOR
            || It->GetActorLabel() == SaskartaSensor::VolumeName
#endif
            || CarriesSensor(*It))
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
    GlassMid = nullptr;
    CrtIndex = INDEX_NONE;
    GlassIndex = INDEX_NONE;
    int32 Index = 0;
    for (FWeightedBlendable& B : Volume->Settings.WeightedBlendables.Array)
    {
        UMaterialInterface* M = Cast<UMaterialInterface>(B.Object);
        if (M && M->GetName().Contains(SaskartaSensor::GlassMaterialName))
        {
            GlassMid = UMaterialInstanceDynamic::Create(M, Volume.Get());
            B.Object = GlassMid;
            B.Weight = 0.f; // start absent; Poll enables it only for an active carrier camera
            GlassIndex = Index;
        }
        else if (M && M->GetName().Contains(SaskartaSensor::MaterialName))
        {
            Mid = UMaterialInstanceDynamic::Create(M, Volume.Get());
            B.Object = Mid;
            B.Weight = 0.f; // Poll enables it for an active carrier camera.
            CrtIndex = Index;
        }
        ++Index;
    }
    LastAmount = -1.f; // Rebinding must reapply both weights, even when the setting is unchanged.
    LastGlassAmount = -1.f;
    return Mid != nullptr;
}

void USaskartaSensorFilterSubsystem::Poll()
{
    if (!Bind())
    {
        return;
    }
    int32 Level = 2;
    if (IConsoleVariable* V = IConsoleManager::Get().FindConsoleVariable(TEXT("saskarta.sensorfilter")))
    {
        Level = V->GetInt();
    }
    const USaskartaEventRunner* Runner = USaskartaEventRunner::GetEventRunner(this);
    const USaskartaDroneSequenceSubsystem* Drone = GetWorld()->GetSubsystem<USaskartaDroneSequenceSubsystem>();
    // Human vision starts inside the capsule, before the final-state possession.
    const bool bHumanReveal = Runner && Runner->GetActiveCinematicId() == FName(TEXT("CIN_19_HATCH"));
    const float Amount = bHumanReveal ? 0.f : AmountFor(Level, Runner ? Runner->GetFlowState() : NAME_None);
    // The relay shot is already clean at B1's 8 s switch, before the 12 s
    // persistent-mode cue. Never flash the destroyed lens back during that gap.
    const bool bCleanFeed = (Runner && (Runner->IsPresentationModeActive(TEXT("AuxSensors")) ||
                                       Runner->IsPresentationModeActive(TEXT("DroneCam"))))
        || (Drone && IsValid(Drone->GetDroneViewTarget()));
    const float GlassAmount = bCleanFeed ? 0.f : Amount;
    if (!FMath::IsNearlyEqual(Amount, LastAmount) || !FMath::IsNearlyEqual(GlassAmount, LastGlassAmount))
    {
        Mid->SetScalarParameterValue(SaskartaSensor::Param, Amount);
        const float Weight = Amount > 0.001f ? 1.f : 0.f;
        if (Volume.IsValid() && Volume->Settings.WeightedBlendables.Array.IsValidIndex(CrtIndex))
        {
            Volume->Settings.WeightedBlendables.Array[CrtIndex].Weight = Weight;
        }
        if (GlassMid)
        {
            GlassMid->SetScalarParameterValue(SaskartaSensor::Param, GlassAmount);
            if (Volume.IsValid() && Volume->Settings.WeightedBlendables.Array.IsValidIndex(GlassIndex))
            {
                Volume->Settings.WeightedBlendables.Array[GlassIndex].Weight = GlassAmount > 0.001f ? 1.f : 0.f;
            }
        }
        LastAmount = Amount;
        LastGlassAmount = GlassAmount;
    }
}
