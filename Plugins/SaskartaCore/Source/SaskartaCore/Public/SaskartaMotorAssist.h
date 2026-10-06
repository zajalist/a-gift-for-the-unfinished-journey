// Called by the carrier after setting its base CharacterMovement limits.
#pragma once

#include "CoreMinimal.h"
#include "Subsystems/WorldSubsystem.h"
#include "SaskartaMotorAssistLogic.h"
#include "SaskartaMotorAssist.generated.h"

class ACharacter;

/** Ordinary hill torque is automatic; the shared motor CRT owns E/A/D rhythm. */
UCLASS()
class SASKARTACORE_API USaskartaMotorAssistSubsystem : public UWorldSubsystem
{
    GENERATED_BODY()

public:
    virtual bool ShouldCreateSubsystem(UObject* Outer) const override;

    /** Compatibility for scanner/onboarding priority: there is no separate pulse prompt. */
    bool IsMotorPromptActive() const { return false; }

    /** Called at 30 Hz after base movement limits, before the backwards anti-stuck nudge.
     * Returns true for uphill drive, pursuit ownership, or the empty-fuel stop. */
    UFUNCTION(BlueprintCallable, Category = "Saskarta|Carrier")
    static bool UpdateCarrier(ACharacter* Carrier, float DeltaSeconds, float Throttle,
                              bool bReversing, bool bBraking);

    /** Vehicle loops follow ordinary control or this carrier's unsuppressed automatic pursuit. */
    UFUNCTION(BlueprintPure, Category = "Saskarta|Carrier")
    static bool ShouldPlayDriveAudio(ACharacter* Carrier);

private:
    bool StepCarrier(ACharacter* Carrier, float DeltaSeconds, float Throttle,
                     bool bReversing, bool bBraking);
    FSaskartaMotorAssistLogic Logic;
    TWeakObjectPtr<ACharacter> ActiveCarrier;
};
