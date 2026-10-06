#pragma once

#include "CoreMinimal.h"
#include "Subsystems/WorldSubsystem.h"
#include "SaskartaPauseGuard.generated.h"

class APlayerController;
class UUserWidget;
class USaskartaEventRunner;
class FSaskartaPauseKeyProcessor;

/** Catches Escape and gamepad Menu before prompts/widgets, and opens the existing pause widget in every playable flow. */
UCLASS()
class SASKARTACORE_API USaskartaPauseGuardSubsystem : public UTickableWorldSubsystem
{
    GENERATED_BODY()

public:
    virtual bool ShouldCreateSubsystem(UObject* Outer) const override;
    virtual void OnWorldBeginPlay(UWorld& InWorld) override;
    virtual void Deinitialize() override;
    virtual void Tick(float DeltaTime) override;
    virtual TStatId GetStatId() const override;
    virtual bool IsTickableWhenPaused() const override { return true; }

    bool HandlePauseKey(bool bRepeat);

private:
    APlayerController* GetPC() const;
    FName GetFlow(APlayerController* PC) const;
    bool SetName(APlayerController* PC, FName Property, FName Value) const;
    UUserWidget* GetMenu(APlayerController* PC) const;
    bool Call(AActor* Object, FName Function) const;
    bool OpenPause(APlayerController* PC, FName From);
    void WatchMenu();

    TSharedPtr<FSaskartaPauseKeyProcessor> Processor;
    TWeakObjectPtr<USaskartaEventRunner> Runner;
    FName OpenedFrom;
    bool bOpenedByGuard = false;
    bool bHeldCinematic = false;
    bool bFlowMovedOn = false;
    bool bHadMoveLock = false;
    bool bHadLookLock = false;
};
