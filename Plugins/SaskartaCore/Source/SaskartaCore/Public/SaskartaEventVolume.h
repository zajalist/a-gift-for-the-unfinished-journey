// ASaskartaEventVolume: a proximity trigger for the story runner (EVENTS.md section 2).
// Place in the level's Gameplay folder and set it NOT spatially loaded.

#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "SaskartaEventVolume.generated.h"

class UBoxComponent;
class UPrimitiveComponent;

UCLASS(BlueprintType)
class SASKARTACORE_API ASaskartaEventVolume : public AActor
{
    GENERATED_BODY()

public:
    ASaskartaEventVolume();

    UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "Saskarta|Events")
    TObjectPtr<UBoxComponent> Box;

    /** Matches FSaskartaEventTrigger::VolumeId of a Volume beat. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Events")
    FName TriggerId;

    /** Only the player's possessed pawn triggers it. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Events")
    bool bPawnOnly = true;

protected:
    virtual void BeginPlay() override;

private:
    UFUNCTION()
    void HandleBeginOverlap(UPrimitiveComponent* OverlappedComponent, AActor* OtherActor, UPrimitiveComponent* OtherComp,
        int32 OtherBodyIndex, bool bFromSweep, const FHitResult& SweepResult);
};
