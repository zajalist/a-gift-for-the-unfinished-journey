#include "SaskartaRouteLog.h"

#include "Dom/JsonObject.h"
#include "Engine/World.h"
#include "GameFramework/PlayerController.h"
#include "InputCoreTypes.h"
#include "Kismet/GameplayStatics.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "SaskartaEventRunner.h"
#include "SaskartaMotorResonance.h"
#include "SaskartaPower.h"
#include "SaskartaRouteMap.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "TimerManager.h"

const TCHAR* USaskartaRouteBoardAsset::AssetPath = TEXT("/Game/SaskartaGaea/Story/DA_Saskarta_RouteBoard.DA_Saskarta_RouteBoard");

#if WITH_EDITOR
void USaskartaRouteBoardAsset::ReimportFromDocs()
{
    FString Text;
    TSharedPtr<FJsonObject> Root;
    if (FFileHelper::LoadFileToString(Text, *(FPaths::ProjectDir() / TEXT("docs/story/route-board.json"))) &&
        FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Text), Root) && Root.IsValid())
    {
        Modify();
        Json = MoveTemp(Text);
    }
}
#endif

bool USaskartaRouteLog::ShouldCreateSubsystem(UObject* Outer) const
{
    const UWorld* World = Cast<UWorld>(Outer);
    return World && World->IsGameWorld();
}

void USaskartaRouteLog::Initialize(FSubsystemCollectionBase& Collection)
{
    Super::Initialize(Collection);
    Collection.InitializeDependency<USaskartaMotorResonanceSubsystem>();
}

void USaskartaRouteLog::OnWorldBeginPlay(UWorld& InWorld)
{
    Super::OnWorldBeginPlay(InWorld);
    InWorld.GetTimerManager().SetTimer(KeyTimer, this, &USaskartaRouteLog::PollKeys, 0.02f, true);
}

void USaskartaRouteLog::Deinitialize()
{
    if (UWorld* World = GetWorld()) World->GetTimerManager().ClearTimer(KeyTimer);
    Super::Deinitialize();
}

bool USaskartaRouteLog::IsOpen() const
{
    const UWorld* World = GetWorld();
    const USaskartaMotorResonanceSubsystem* Motor = World ? World->GetSubsystem<USaskartaMotorResonanceSubsystem>() : nullptr;
    return Motor && Motor->IsTuning();
}

bool USaskartaRouteLog::CanOpen() const
{
    const UWorld* World = GetWorld();
    if (!World || UGameplayStatics::IsGamePaused(World)) return false;
    const USaskartaEventRunner* Runner = World->GetSubsystem<USaskartaEventRunner>();
    const USaskartaPowerSubsystem* Power = World->GetSubsystem<USaskartaPowerSubsystem>();
    const USaskartaMotorResonanceSubsystem* Motor = World->GetSubsystem<USaskartaMotorResonanceSubsystem>();
    if (!Runner || !Power || !Motor || (Motor->IsActive() && !Motor->IsTuning())) return false;
    const FName Flow = Runner->GetFlowState();
    return (Flow == FName(TEXT("Playing")) || Flow == FName(TEXT("Carrier"))) &&
        !Runner->IsCinematicActive() && !Runner->IsHoldingInput() && !Runner->IsPromptActive() &&
        (IsOpen() || Power->CanRest());
}

void USaskartaRouteLog::SetOpen(bool bInOpen)
{
    UWorld* World = GetWorld();
    USaskartaMotorResonanceSubsystem* Motor = World ? World->GetSubsystem<USaskartaMotorResonanceSubsystem>() : nullptr;
    if (!Motor) return;
    if (!bInOpen) { Motor->EndTuning(); return; }
    if (IsOpen() || !CanOpen()) return;
    if (USaskartaRouteMap* Map = World->GetSubsystem<USaskartaRouteMap>()) Map->SetOpen(false);
    Motor->BeginTuning();
    if (Motor->IsTuning()) ++OpenCount;
}

void USaskartaRouteLog::PollKeys()
{
    UWorld* World = GetWorld();
    const APlayerController* PC = World ? World->GetFirstPlayerController() : nullptr;
    if (!PC) return;
    bool bToggle = false;
    for (const FKey Key : {EKeys::Tab, EKeys::Gamepad_Special_Left})
    {
        const bool bDown = PC->IsInputKeyDown(Key);
        bool& bWasDown = KeyWasDown.FindOrAdd(Key);
        bToggle |= bDown && !bWasDown;
        bWasDown = bDown;
    }
    if (UGameplayStatics::IsGamePaused(World)) return;
    if (!bToggle)
    {
        if (PendingOpenS > 0.f)
        {
            PendingOpenS -= 0.02f;
            if (!IsOpen() && CanOpen()) { PendingOpenS = 0.f; SetOpen(true); }
        }
        return;
    }
    if (IsOpen()) { PendingOpenS = 0.f; SetOpen(false); return; }
    if (CanOpen()) { SetOpen(true); return; }
    PendingOpenS = 4.f;
    const USaskartaEventRunner* Runner = World->GetSubsystem<USaskartaEventRunner>();
    const USaskartaMotorResonanceSubsystem* Motor = World->GetSubsystem<USaskartaMotorResonanceSubsystem>();
    if (!Runner || (Motor && Motor->IsActive()) || Runner->IsCinematicActive() || Runner->IsHoldingInput() || Runner->IsPromptActive()) return;
    const FName Flow = Runner->GetFlowState();
    if (Flow == FName(TEXT("Playing")) || Flow == FName(TEXT("Carrier")))
        if (USaskartaPowerSubsystem* Power = World->GetSubsystem<USaskartaPowerSubsystem>())
            Power->ShowNotice(TEXT("STOPPING · TUNING OPENS WHEN STILL"));
}

FString USaskartaRouteLog::DumpState() const
{
    return FString::Printf(TEXT("Motor tuning=%d ready=%d opens=%d"), IsOpen(), CanOpen(), OpenCount);
}
