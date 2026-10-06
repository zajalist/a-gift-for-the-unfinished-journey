// USaskartaAutopilot: an unattended "AI playthrough" driver (docs/AUTOPILOT.md).
//
// Off unless the command line has -autopilot or the console runs `Saskarta.Autopilot 1`.
// It plays through the same doors a player uses: it presses Begin on the title (PC_Saskarta.StartGame),
// holds W and steers with A/D toward a point ahead on the road spline, taps E on story prompts, parks
// to recharge (and tunes the motor while parked), cranks the motor in rhythm during the dust pursuit,
// answers the elder's footing checks (Space / A / D) and chooses Transmit at the end. Simulated keys go
// through APlayerController::InputKey, so PlayerInput / Enhanced Input see them like real presses; the
// motor rhythm game, which reads Slate key events, gets USaskartaMotorResonanceSubsystem::HandleKey.
//
// Every decision is written as one line "LogSaskartaAutopilot: AP|<seconds>|<event>|<text>" to the log
// (non-Shipping) and always to Saved/Logs/Autopilot-<date>.log (or -autopilotlog=<path>), because
// Shipping builds compile UE_LOG out. -autopilotshots also takes eight HighResShot stills.
#pragma once

#include "CoreMinimal.h"
#include "InputCoreTypes.h"
#include "Subsystems/WorldSubsystem.h"
#include "SaskartaAutopilot.generated.h"

class APawn;
class APlayerController;
class USaskartaEventRunner;

UCLASS()
class SASKARTACORE_API USaskartaAutopilot : public UTickableWorldSubsystem
{
    GENERATED_BODY()

public:
    virtual bool ShouldCreateSubsystem(UObject* Outer) const override;
    virtual void Initialize(FSubsystemCollectionBase& Collection) override;
    virtual void OnWorldBeginPlay(UWorld& InWorld) override;
    virtual void Deinitialize() override;
    virtual void Tick(float DeltaTime) override;
    virtual TStatId GetStatId() const override;
    virtual bool IsTickableWhenPaused() const override { return false; }

    UFUNCTION(BlueprintCallable, Category = "Saskarta|Autopilot")
    void SetAutopilotEnabled(bool bEnable);

    UFUNCTION(BlueprintPure, Category = "Saskarta|Autopilot")
    bool IsAutopilotEnabled() const { return bEnabled; }

    void SetShotsEnabled(bool bEnable) { bShots = bEnable; }

private:
    enum class EDriveMode : uint8 { Driving, Charging };

    // --- delegates from the event runner
    UFUNCTION() void HandleBeatStarted(FName Id);
    UFUNCTION() void HandleCinematicStarted(FName Id);
    UFUNCTION() void HandleCinematicFinished(FName Id);
    UFUNCTION() void HandlePromptShow(const FText& Text);
    void BindRunner();

    // --- per-tick lanes
    void TickTitle(APlayerController* PC, FName Flow);
    void TickPrompt(APlayerController* PC, USaskartaEventRunner* Runner);
    void TickMotor(float DeltaTime);
    void TickFooting(APlayerController* PC);
    void TickCarrier(APlayerController* PC, USaskartaEventRunner* Runner, APawn* Pawn, float DeltaTime);
    void TickHuman(APlayerController* PC, USaskartaEventRunner* Runner, APawn* Pawn, float DeltaTime);
    void TickShots(USaskartaEventRunner* Runner, bool bDriving);
    void FollowCamera(APlayerController* PC, USaskartaEventRunner* Runner, float TargetYaw, float DeltaTime);
    bool RoadTarget(USaskartaEventRunner* Runner, const FVector& From, float LookCm, FVector& OutTarget, float& OutNearCm, float& OutOffCm) const;
    AActor* FindSummitVolume();

    // --- simulated keys
    void SetKey(APlayerController* PC, const FKey& Key, bool bDown);
    void TapKey(APlayerController* PC, const FKey& Key, float HoldS);
    void ReleaseAllKeys();
    void PumpReleases(APlayerController* PC);
    void MotorPress(const FKey& Key);

    // --- logging
    void Say(const TCHAR* Event, const FString& Text);
    void TakeShot(const FString& Name);
    double Now() const;

    bool bEnabled = false;
    bool bShots = false;
    bool bFinished = false;
    bool bBound = false;
    double StartS = 0.0;
    FString LogPath;

    TWeakObjectPtr<APlayerController> KeyController;
    TMap<FKey, bool> Held;
    TMap<FKey, double> LastSent;
    TArray<TPair<FKey, double>> PendingReleases;
    TArray<TPair<FKey, double>> MotorReleases;

    FName LastFlow;
    double FlowSinceS = 0.0;
    double LastStartGameS = -1000.0;
    bool bSaidTitle = false;
    bool bSaidPlaying = false;
    bool bSaidHuman = false;

    double PromptSinceS = -1.0;
    double LastPromptTapS = -1000.0;
    FString LastPromptText;

    EDriveMode Mode = EDriveMode::Driving;
    bool bTunedThisRest = false;
    bool bWasTuning = false;
    bool bWasChasing = false;
    bool bWasFailed = false;
    int32 MotorHits = 0;
    bool bSteerRight = false;
    bool bSteerLeft = false;
    double StuckS = 0.0;
    double TotalStuckS = 0.0;
    int32 UnstickStage = 0;
    double UnstickUntilS = -1.0;
    double AssistUntilS = -1.0;
    bool bReversing = false;
    int32 LastMilestone = 0;
    bool bRadioDone = false;
    double LastSteleS = -1000.0;

    bool bWasFooting = false;
    int32 FootingHealthAtStart = 3;
    double LastMashS = 0.0;
    bool bMashDown = false;

    TWeakObjectPtr<AActor> SummitVolume;
    bool bSearchedSummit = false;

    FName ShotCine;
    FString ShotCineName;
    float ShotCineAtS = -1.f;
    TSet<FString> ShotsTaken;
};
