// USaskartaEventLibrary, ASaskartaEventVolume and the save slot names.

#include "SaskartaEventLibrary.h"
#include "SaskartaEventRunner.h"
#include "SaskartaEventVolume.h"
#include "SaskartaSaveGame.h"

#include "Components/BoxComponent.h"
#include "GameFramework/Pawn.h"
#include "GameFramework/PlayerController.h"

const TCHAR* USaskartaSaveGame::RunSlot = TEXT("Saskarta_Run");
const TCHAR* USaskartaSaveGame::ProfileSlot = TEXT("Saskarta_Profile");

// ============================================================================ library

void USaskartaEventLibrary::ReportFlow(const UObject* WorldContext, FName FlowEvent)
{
    if (USaskartaEventRunner* R = USaskartaEventRunner::GetEventRunner(WorldContext)) R->ReportFlow(FlowEvent);
}

bool USaskartaEventLibrary::FireBeat(const UObject* WorldContext, FName BeatId)
{
    USaskartaEventRunner* R = USaskartaEventRunner::GetEventRunner(WorldContext);
    return R && R->FireBeat(BeatId, false);
}

bool USaskartaEventLibrary::IsCinematicActive(const UObject* WorldContext)
{
    const USaskartaEventRunner* R = USaskartaEventRunner::GetEventRunner(WorldContext);
    return R && R->IsCinematicActive();
}

bool USaskartaEventLibrary::IsVoiceBusy(const UObject* WorldContext)
{
    const USaskartaEventRunner* R = USaskartaEventRunner::GetEventRunner(WorldContext);
    return R && R->IsVoiceBusy();
}

float USaskartaEventLibrary::SecondsSinceVoice(const UObject* WorldContext)
{
    const USaskartaEventRunner* R = USaskartaEventRunner::GetEventRunner(WorldContext);
    return R ? R->SecondsSinceVoice() : 1000.f;
}

bool USaskartaEventLibrary::CanSkipCinematic(const UObject* WorldContext)
{
    const USaskartaEventRunner* R = USaskartaEventRunner::GetEventRunner(WorldContext);
    return R && R->CanSkipCurrentCinematic();
}

void USaskartaEventLibrary::SkipCurrentCinematic(const UObject* WorldContext)
{
    if (USaskartaEventRunner* R = USaskartaEventRunner::GetEventRunner(WorldContext)) R->SkipCurrentCinematic();
}

void USaskartaEventLibrary::PauseCinematic(const UObject* WorldContext, bool bPause)
{
    if (USaskartaEventRunner* R = USaskartaEventRunner::GetEventRunner(WorldContext)) R->PauseCinematic(bPause);
}

void USaskartaEventLibrary::StopAll(const UObject* WorldContext)
{
    if (USaskartaEventRunner* R = USaskartaEventRunner::GetEventRunner(WorldContext)) R->StopAll();
}

bool USaskartaEventLibrary::SaveCheckpoint(const UObject* WorldContext, FName CheckpointId)
{
    USaskartaEventRunner* R = USaskartaEventRunner::GetEventRunner(WorldContext);
    return R && R->SaveCheckpoint(CheckpointId);
}

bool USaskartaEventLibrary::RestoreFromSave(const UObject* WorldContext)
{
    USaskartaEventRunner* R = USaskartaEventRunner::GetEventRunner(WorldContext);
    return R && R->RestoreFromSave();
}

// ============================================================================ volume

ASaskartaEventVolume::ASaskartaEventVolume()
{
    PrimaryActorTick.bCanEverTick = false;
    Box = CreateDefaultSubobject<UBoxComponent>(TEXT("Box"));
    Box->InitBoxExtent(FVector(300.f, 300.f, 300.f));
    Box->SetCollisionProfileName(TEXT("OverlapAllDynamic"));
    Box->SetGenerateOverlapEvents(true);
    RootComponent = Box;
}

void ASaskartaEventVolume::BeginPlay()
{
    Super::BeginPlay();
    Box->OnComponentBeginOverlap.AddDynamic(this, &ASaskartaEventVolume::HandleBeginOverlap);
}

void ASaskartaEventVolume::HandleBeginOverlap(UPrimitiveComponent* OverlappedComponent, AActor* OtherActor, UPrimitiveComponent* OtherComp,
    int32 OtherBodyIndex, bool bFromSweep, const FHitResult& SweepResult)
{
    APawn* Pawn = Cast<APawn>(OtherActor);
    if (bPawnOnly && (!Pawn || !Pawn->IsPlayerControlled()))
    {
        return;
    }
    if (USaskartaEventRunner* R = USaskartaEventRunner::GetEventRunner(this))
    {
        R->NotifyVolume(TriggerId, Pawn);
    }
}
