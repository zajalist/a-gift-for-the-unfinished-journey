#include "SaskartaMotorAssist.h"

#include "SaskartaEarlyStorm.h"
#include "SaskartaEventRunner.h"
#include "SaskartaMotorResonance.h"
#include "SaskartaPower.h"
#include "Engine/World.h"
#include "GameFramework/Character.h"
#include "GameFramework/CharacterMovementComponent.h"
#include "GameFramework/PlayerController.h"

namespace SaskartaMotor
{
    bool DriveFlow(FName Flow)
    {
        return Flow == FName(TEXT("Playing")) || Flow == FName(TEXT("Carrier"));
    }
}

bool USaskartaMotorAssistSubsystem::ShouldCreateSubsystem(UObject* Outer) const
{
    const UWorld* World = Cast<UWorld>(Outer);
    return World && World->IsGameWorld();
}

bool USaskartaMotorAssistSubsystem::UpdateCarrier(ACharacter* Carrier, float DeltaSeconds, float Throttle,
                                                  bool bReversing, bool bBraking)
{
    if (!IsValid(Carrier) || !Carrier->GetWorld()) return false;
    // Empty fuel cuts propulsion immediately; Power owns the short coast and
    // parked recharge. True suppresses DriveStep's old anti-stuck launch.
    if (const USaskartaPowerSubsystem* Power = Carrier->GetWorld()->GetSubsystem<USaskartaPowerSubsystem>();
        Power && (Power->IsLimp() || Power->GetCharge() <= 0.f))
    {
        if (USaskartaMotorAssistSubsystem* Motor = Carrier->GetWorld()->GetSubsystem<USaskartaMotorAssistSubsystem>())
            Motor->Logic.Reset();
        Carrier->ConsumeMovementInputVector();
        USaskartaPowerSubsystem::ApplyDriveLimits(Carrier, 0.f, false);
        return true;
    }
    // The pursuit applies its own speed/acceleration after DriveStep's base limits.
    // Keep its automatic road drive independent of ordinary hill assistance.
    if (USaskartaEarlyStormSubsystem* Storm = Carrier->GetWorld()->GetSubsystem<USaskartaEarlyStormSubsystem>())
    {
        if (Storm->UpdateCarrierForPursuit(Carrier))
        {
            if (USaskartaMotorAssistSubsystem* Motor = Carrier->GetWorld()->GetSubsystem<USaskartaMotorAssistSubsystem>())
                Motor->Logic.Reset();
            return true;
        }
    }
    USaskartaMotorAssistSubsystem* Motor = Carrier->GetWorld()->GetSubsystem<USaskartaMotorAssistSubsystem>();
    const bool bAssist = Motor && Motor->StepCarrier(Carrier, DeltaSeconds, Throttle, bReversing, bBraking);
    USaskartaPowerSubsystem::ApplyDriveLimits(Carrier, Throttle, bReversing);
    return bAssist;
}

bool USaskartaMotorAssistSubsystem::ShouldPlayDriveAudio(ACharacter* Carrier)
{
    const UWorld* World = IsValid(Carrier) ? Carrier->GetWorld() : nullptr;
    const APlayerController* PC = World ? Cast<APlayerController>(Carrier->GetController()) : nullptr;
    const USaskartaEventRunner* Runner = World ? World->GetSubsystem<USaskartaEventRunner>() : nullptr;
    const USaskartaPowerSubsystem* Power = World ? World->GetSubsystem<USaskartaPowerSubsystem>() : nullptr;
    if (Power && (Power->IsLimp() || Power->GetCharge() <= 0.f)) return false;
    if (!World || World->IsPaused() || !PC || PC->GetPawn() != Carrier || !Runner ||
        !SaskartaMotor::DriveFlow(Runner->GetFlowState()) || Runner->IsCinematicActive() ||
        Runner->IsHoldingInput() || Runner->IsPromptActive()) return false;

    const USaskartaEarlyStormSubsystem* Storm = World->GetSubsystem<USaskartaEarlyStormSubsystem>();
    const USaskartaMotorResonanceSubsystem* Motor = World->GetSubsystem<USaskartaMotorResonanceSubsystem>();
    if (Storm && Storm->OwnsPursuitCarrier(Carrier))
        return Motor && Motor->CanAcceptInput();
    return !PC->IsMoveInputIgnored() && !(Motor && Motor->IsActive());
}

bool USaskartaMotorAssistSubsystem::StepCarrier(ACharacter* Carrier, float DeltaSeconds, float Throttle,
                                                bool bReversing, bool bBraking)
{
    UWorld* World = GetWorld();
    if (!World) return false;
    if (ActiveCarrier.Get() != Carrier)
    {
        Logic.Reset();
        ActiveCarrier = Carrier;
    }
    const APlayerController* PC = Cast<APlayerController>(Carrier->GetController());
    const USaskartaEventRunner* Runner = World->GetSubsystem<USaskartaEventRunner>();
    const USaskartaMotorResonanceSubsystem* Resonance = World->GetSubsystem<USaskartaMotorResonanceSubsystem>();
    UCharacterMovementComponent* Move = Carrier->GetCharacterMovement();
    const bool bGrounded = Move && Move->IsMovingOnGround() && Move->CurrentFloor.IsWalkableFloor();
    const bool bControlsAvailable = !World->IsPaused() && PC && PC->GetPawn() == Carrier &&
        !PC->IsMoveInputIgnored() && Runner && SaskartaMotor::DriveFlow(Runner->GetFlowState()) &&
        !Runner->IsCinematicActive() && !Runner->IsHoldingInput() && !Runner->IsPromptActive() &&
        !(Resonance && Resonance->IsActive());
    float Grade = 0.f;
    if (bGrounded)
    {
        const FVector Forward = Carrier->GetActorForwardVector().GetSafeNormal2D();
        const FVector Normal = Move->CurrentFloor.HitResult.ImpactNormal;
        Grade = -FVector::DotProduct(FVector(Normal.X, Normal.Y, 0.f), Forward) / FMath::Max(Normal.Z, 0.2f);
    }
    const bool bUphillDrive = Logic.Step(DeltaSeconds, bControlsAvailable, bGrounded, Throttle,
                                        bReversing, bBraking, Grade);
    if (bUphillDrive)
    {
        // CharacterMovement owns acceleration, floor projection and collision.
        // No velocity kick, capsule teleport or vertical impulse is applied here.
        const FSaskartaMotorAssistLogic::FLimits Limits = Logic.Apply(Move->MaxAcceleration, Move->MaxWalkSpeed);
        Move->MaxAcceleration = Limits.MaxAcceleration;
        Move->MaxWalkSpeed = Limits.MaxWalkSpeed;
    }
    return bUphillDrive;
}
