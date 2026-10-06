// LANE5 (queued): see SaskartaSensorFilter.h and README.md in cpp_queue/lane5_sensorfilter.
#include "SaskartaSensorFilter.h"

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
    InWorld.GetTimerManager().SetTimer(Timer, this, &USaskartaSensorFilterSubsystem::Poll, SaskartaSensor::PollS, true);
}

void USaskartaSensorFilterSubsystem::Deinitialize()
{
    if (UWorld* W = GetWorld())
    {
        W->GetTimerManager().ClearTimer(Timer);
    }
    Super::Deinitialize();
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
    for (TActorIterator<APostProcessVolume> It(GetWorld()); It; ++It)
    {
        if (It->Tags.Contains(SaskartaSensor::Tag) || It->GetName().Contains(SaskartaSensor::VolumeName)
#if WITH_EDITOR
            || It->GetActorLabel() == SaskartaSensor::VolumeName
#endif
        )
        {
            Volume = *It;
            break;
        }
    }
    if (!Volume.IsValid())
    {
        return false;
    }
    for (FWeightedBlendable& B : Volume->Settings.WeightedBlendables.Array)
    {
        UMaterialInterface* M = Cast<UMaterialInterface>(B.Object);
        if (M && M->GetName().Contains(SaskartaSensor::MaterialName))
        {
            Mid = UMaterialInstanceDynamic::Create(M, Volume.Get());
            B.Object = Mid;
            return true;
        }
    }
    return false;
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
    const float Amount = AmountFor(Level, Runner ? Runner->GetFlowState() : NAME_None);
    if (!FMath::IsNearlyEqual(Amount, LastAmount))
    {
        Mid->SetScalarParameterValue(SaskartaSensor::Param, Amount);
        LastAmount = Amount;
    }
}
