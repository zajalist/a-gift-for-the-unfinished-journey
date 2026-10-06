#pragma once

#include "CoreMinimal.h"
#include "Subsystems/WorldSubsystem.h"
#include "SaskartaSaveGame.h"
#include "SaskartaEarlyStorm.generated.h"

class USaskartaEventRunner;
class USaskartaSaveGame;
class USaskartaPackageRescueWidget;
class ASaskartaDustWreck;
class ASaskartaDustFront;
class ACharacter;
class APlayerController;
class UAudioComponent;
class USoundBase;
class AActor;
class ULocalFogVolumeComponent;
class UTexture2D;
class UGameViewportClient;
class SSaskartaStormLens;
class SWidget;
struct FStreamableHandle;

/**
 * An automatic road pursuit from 650 m to Waiting Water. The player cranks the
 * motor in rhythm and balances it; dust contact rescues the package into a fresh carrier.
 */
UCLASS()
class SASKARTACORE_API USaskartaEarlyStormSubsystem : public UTickableWorldSubsystem
{
    GENERATED_BODY()

public:
    USaskartaEarlyStormSubsystem();
    virtual bool ShouldCreateSubsystem(UObject* Outer) const override;
    virtual void OnWorldBeginPlay(UWorld& InWorld) override;
    virtual void Deinitialize() override;
    virtual void Tick(float DeltaSeconds) override;
    virtual TStatId GetStatId() const override;
    virtual bool IsTickableWhenPaused() const override { return true; }

    /** Called after the carrier Blueprint sets ordinary drive limits. */
    bool UpdateCarrierForPursuit(ACharacter* Carrier);
    void ReturnToTitle();
    bool HasFailed() const { return bFailed; }

    UFUNCTION(BlueprintPure, Category = "Saskarta|Storm")
    bool IsChasing() const { return bChasing; }

    /** Exact movement owner; callers must also check the shared input/suppression gate. */
    bool OwnsPursuitCarrier(const ACharacter* Carrier) const
    {
        return bChasing && !bFailed && bOwnsMoveLock && Carrier && DriveCarrier.Get() == Carrier;
    }

    UFUNCTION(BlueprintPure, Category = "Saskarta|Storm")
    float GetFrontGapM() const { return FrontGapM; }

    /** Shared entry fade for the actual world fog. */
    float GetFrontPresentationAlpha() const { return FrontVisibilityAlpha; }

private:
    void Poll();
    void BindRunner(USaskartaEventRunner* Runner);
    void BeginChase(bool bRetry = false);
    void EndChase(bool bKeepWorldFront = false);
    void FailPursuit();
    void CompleteRescue();
    bool RestoreRecoveryFuel(bool& bRefueled);
    void RebuildWrecks();
    void HandleWritingRun(UWorld* World, USaskartaSaveGame* Save);
    void ReleaseDrive();
    void HideFailure();
    void HandleRestoredRun(UWorld* World, USaskartaSaveGame* Save);
    void ApplyWeather(float GapM);
    void UpdateFrontVisual(float GapM);
    void UpdateIntroFront();
    void TryPlayProximityRattle();
    void StopProximityRattle();
    void ClearProximityRattle();
    void UpdateStormAlarm(bool bInputWarningActive);
    void StopStormAlarm();
    bool IsStormAlarmBusy() const;
    void UpdateDustPresentation(float GapM);
    void TickDustLens(float DeltaSeconds, bool bVisible);
    void ClearDustPresentation();
    void TickBackgroundDust(float DeltaSeconds);

    UFUNCTION()
    void OnCinematicStarted(FName CinematicId);
    UFUNCTION()
    void OnCinematicFinished(FName CinematicId);

    FTimerHandle PollTimer;
    TWeakObjectPtr<USaskartaEventRunner> BoundRunner;
    bool bRequested = false;
    bool bIntroActive = false;
    float IntroCarrierRoadM = -1.f;
    bool bChasing = false;
    bool bFailed = false;
    bool bOwnsMoveLock = false;
    bool bOwnsPause = false;
    bool bOwnsRadioPause = false;
    bool bRestoredPursuit = false;
    float DriveSpeedCmS = 0.f;
    float PreviousMaxSpeed = 0.f;
    float PreviousAcceleration = 0.f;
    float PreviousBraking = 0.f;
    bool bPreviousOrientToMovement = false;
    TWeakObjectPtr<APlayerController> DriveController;
    TWeakObjectPtr<ACharacter> DriveCarrier;
    UPROPERTY(Transient) TObjectPtr<USaskartaSaveGame> PursuitCheckpoint;
    UPROPERTY(Transient) TObjectPtr<USaskartaPackageRescueWidget> RescueWidget;
    UPROPERTY(Transient) TArray<TObjectPtr<USaskartaSaveGame>> RecoveryCheckpoints;
    UPROPERTY(Transient) TArray<TObjectPtr<ASaskartaDustWreck>> WreckActors;
    UPROPERTY(Transient) TObjectPtr<ASaskartaDustFront> FrontActor;
    UPROPERTY(Transient) TObjectPtr<USoundBase> ProximityRattleSound;
    UPROPERTY(Transient) TObjectPtr<UAudioComponent> ProximityRattleAudio;
    TSharedPtr<FStreamableHandle> ProximityRattleLoad;
    bool bProximityRattleFired = false;
    UPROPERTY(Transient) TArray<TObjectPtr<USoundBase>> StormAlarmSounds;
    UPROPERTY(Transient) TObjectPtr<UAudioComponent> StormAlarmAudio;
    TSharedPtr<FStreamableHandle> StormAlarmLoad;
    double NextStormAlarmS = 0.0;
    int32 StormAlarmPulsesLeft = 0;
    int32 StormAlarmVariant = 0;
    bool bStormAlarmArmed = false;
    bool bStormAlarmOnset = false;
    TArray<FSaskartaDustWreckSave> Wrecks;
    FDelegateHandle WriteHandle;
    double RescueStartedRealS = -1.0;
    double RescueSucceededRealS = -1.0;
    bool bRescueRestored = false;
    float LastRecoveryRoadM = -1.f;
    FDelegateHandle RestoreHandle;
    bool bOwnsWeather = false;
    bool bOwnsShellSuppression = false;
    bool bPreviousShellSuppression = false;
    UPROPERTY() TSoftObjectPtr<UTexture2D> LensGrimeAsset;
    TSharedPtr<FStreamableHandle> DustPresentationLoad;
    UPROPERTY(Transient) TObjectPtr<AActor> CloseDustVolume;
    UPROPERTY(Transient) TObjectPtr<UTexture2D> LensGrimeTexture;
    UPROPERTY(Transient) TArray<TObjectPtr<ULocalFogVolumeComponent>> CloseFogLobes;
    struct FOwnedDustCvar
    {
        FName Name;
        float Previous = 0.f;
        float Applied = 0.f;
        uint32 SetBy = 0;
    };
    TArray<FOwnedDustCvar> OwnedDustCvars;
    TSharedPtr<SSaskartaStormLens> DustLens;
    TSharedPtr<SWidget> DustLensWrapper;
    TWeakObjectPtr<UGameViewportClient> DustViewport;
    float DustNear = 0.f;
    float DustProximity = 0.f;
    float DustTimeS = 0.f;
    double LastDustPresentationS = -1.0;
    bool bBackgroundActive = false;
    bool bDustFading = false;
    float DustFadeS = 0.f;
    float DustEffectAlpha = 0.f;
    float FrontVisibilityAlpha = 0.f;
    float AppliedFrontVisibilityAlpha = -1.f;
    UPROPERTY(Transient) TArray<TObjectPtr<ULocalFogVolumeComponent>> FrontFogLobes;
    TArray<FVector2f> FrontFogExtinction;
    float FrontRoadM = 0.f;
    float FrontSpeedMps = 6.2f;
    float FrontGapM = 0.f;
    float PreviousStormIntensity = -1.f;
    float LastStormIntensity = -1.f;
    double LastPollS = -1.0;
    double LastNoticeS = -100.0;
    double RequestedAtS = -1.0;
};
