// USaskartaCollapseStageSubsystem (task COLLAPSE-STAGE): stages the carrier for the collapse.
//
// On the runner's OnBeatStarted(B18_COLLAPSE) (or OnCinematicStarted(CIN_18_COLLAPSE) for a debug
// play), before CIN_18's sequence starts and takes its origin from the pawn, the carrier is moved to
// FSaskartaCollapseStageLogic's pose on the road spline (the runner's own, found by class/tag):
// the capsule on the landscape under its centre, the wheel and capsule-wheel columns traced and
// logged (the pawn's own UpdateGround fits the body to its wheels; the capsule re-reads its ground),
// yawed along the road, speed zero, the capsule's hitch straightened, the drone / fall sequence
// stopped (which also untips a fallen mesh). A move longer than CoverBeyondM happens in black and
// fades back in under the POV lurch. Hooks through the runner's delegates only; the runner is unchanged.

#pragma once

#include "CoreMinimal.h"
#include "Subsystems/WorldSubsystem.h"
#include "SaskartaCollapseStage.generated.h"

class USaskartaEventRunner;
class USaskartaCarrierAnimInstance;
class UParticleSystem;
class UParticleSystemComponent;
class ACharacter;
class APlayerController;
class APawn;

UCLASS()
class SASKARTACORE_API USaskartaCollapseStageSubsystem : public UWorldSubsystem
{
    GENERATED_BODY()

public:
    USaskartaCollapseStageSubsystem();
    virtual bool ShouldCreateSubsystem(UObject* Outer) const override;
    virtual void OnWorldBeginPlay(UWorld& InWorld) override;
    virtual void Deinitialize() override;

    /** Stages the carrier now (the delegates call it; also for a debug call). True when it staged. */
    UFUNCTION(BlueprintCallable, Category = "Saskarta|Collapse")
    bool StageNow();

    /** Repairs a missing Blueprint handoff and grounds the Keeper before the first-person return. */
    bool EnsureHumanHandoff(APlayerController* PC, APawn* Carrier);

private:
    UFUNCTION()
    void HandleBeatStarted(FName Id);
    UFUNCTION()
    void HandleCinematicStarted(FName Id);
    void MaybeStage(FName Id);
    void RestoreTrailer();
    void FadeBackIn();

    TWeakObjectPtr<USaskartaEventRunner> Runner;
    TWeakObjectPtr<USaskartaCarrierAnimInstance> TrailerAnim;
    /** Hard reference so the existing Cascade smoke is included in a cooked game. */
    UPROPERTY()
    TObjectPtr<UParticleSystem> CollapseSmoke;
    /** Cooked fallback for maps where the non-spatial Keeper actor was omitted. */
    UPROPERTY()
    TSubclassOf<ACharacter> TravellerClass;
    UPROPERTY(Transient)
    TArray<TObjectPtr<UParticleSystemComponent>> SmokeEmitters;
    bool bSavedTrailer = true;
    double LastStageS = -1000.0;
    float PendingFadeS = 0.6f;
    FTimerHandle TrailerTimer;
    FTimerHandle FadeTimer;
};
