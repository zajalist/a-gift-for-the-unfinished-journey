// The carrier's biofuel charge at runtime (docs/design/ROUTE_BOARD_V3.md, POWER): drain for driving, radio,
// lamps and turbo; generator refill at rest; a complete stop at 0% until 30% recovery. The legacy saved
// bLimp name remains for compatibility. A physical seven-segment indicator follows actual charge; its numeric
// readout requires looking at the visible rear battery. Independent H/L3 instruments update at 10 Hz.
#pragma once

#include "CoreMinimal.h"
#include "InputCoreTypes.h"
#include "Blueprint/UserWidget.h"
#include "Subsystems/WorldSubsystem.h"
#include "SaskartaPowerLogic.h"
#include "SaskartaPowerHud.h"
#include "SaskartaPower.generated.h"

class ACharacter;
class APlayerController;
class UCameraComponent;
class UBorder;
class UCanvasPanelSlot;
class UMaterialInstanceDynamic;
class UPrimitiveComponent;
class UProgressBar;
class USaskartaTelemetryGraph;
class UTextBlock;
class UVerticalBox;
class UWidgetComponent;
class USaskartaSaveGame;
class USaskartaEventRunner;
class UAudioComponent;
class USoundBase;
class USaskartaChargeAudio;
struct FStreamableHandle;

/** Load each authored gameplay widget class once, before play; retain it across GC. */
SASKARTACORE_API UClass* SaskartaRuntimeWidgetClass(UClass* NativeClass, const TCHAR* AuthoredClassPath);

UCLASS()
class SASKARTACORE_API USaskartaPowerWidget : public UUserWidget
{
    GENERATED_BODY()

public:
    void ShowPower(bool bShow, bool bInspecting, bool bTelemetry, const FSaskartaPowerHudInput& In,
        const FSaskartaPowerHudOutput& Out, const FSaskartaPowerTelemetry& History);

protected:
    virtual void NativeOnInitialized() override;

private:
    bool BindAuthoredLayout();
    UPROPERTY(Transient)
    TObjectPtr<UTextBlock> LineText;
    UPROPERTY(Transient)
    TObjectPtr<UTextBlock> LoadsText;
    UPROPERTY(Transient) TObjectPtr<UTextBlock> NoticeTitle;
    UPROPERTY(Transient) TObjectPtr<UBorder> NoticeAccent;
    UPROPERTY(Transient) TArray<TObjectPtr<UProgressBar>> BatteryGauge;
    UPROPERTY(Transient) TObjectPtr<UBorder> BatteryPanel;
    UPROPERTY(Transient) TObjectPtr<UBorder> NoticePanel;
    UPROPERTY(Transient) TObjectPtr<UBorder> TelemetryPanel;
    UPROPERTY(Transient) TObjectPtr<UTextBlock> StateText;
    UPROPERTY(Transient) TObjectPtr<UTextBlock> SpeedText;
    UPROPERTY(Transient) TObjectPtr<UTextBlock> AltitudeText;
    UPROPERTY(Transient) TObjectPtr<UTextBlock> SpeedScaleText;
    UPROPERTY(Transient) TObjectPtr<UTextBlock> AltitudeScaleText;
    UPROPERTY(Transient) TObjectPtr<USaskartaTelemetryGraph> SpeedGraph;
    UPROPERTY(Transient) TObjectPtr<USaskartaTelemetryGraph> AltitudeGraph;
    UPROPERTY(Transient) TObjectPtr<UTextBlock> TelemetryHint;
    UPROPERTY(Transient) TObjectPtr<UTextBlock> TelemetryDatum;
    UPROPERTY(Transient) TObjectPtr<UVerticalBox> PowerContent;
    UPROPERTY(Transient) TObjectPtr<UCanvasPanelSlot> DisplaySlot;
    bool bDisplayAlongRightEdge = false;
};

UCLASS()
class SASKARTACORE_API USaskartaPowerSubsystem : public UWorldSubsystem
{
    GENERATED_BODY()

public:
    virtual bool ShouldCreateSubsystem(UObject* Outer) const override;
    virtual void Initialize(FSubsystemCollectionBase& Collection) override;
    virtual void OnWorldBeginPlay(UWorld& InWorld) override;
    virtual void Deinitialize() override;

    /** Called after DriveStep's base limits: the empty-cell stop and the powered turbo speed. */
    static void ApplyDriveLimits(ACharacter* Carrier, float Throttle, bool bReversing);

    UFUNCTION(BlueprintPure, Category = "Saskarta|Power")
    float GetCharge() const { return Core.Charge; }
    UFUNCTION(BlueprintPure, Category = "Saskarta|Power")
    bool IsLimp() const { return Core.bLimp; }
    /** The canonical charge threshold at which an empty cell permits driving again. */
    float GetRestartCharge() const { return Core.Tuning.LimpExitPercent; }
    UFUNCTION(BlueprintPure, Category = "Saskarta|Power")
    bool IsTurbo() const { return Core.bTurbo; }
    UFUNCTION(BlueprintPure, Category = "Saskarta|Power")
    bool CanRest() const { return Core.CanRest(); }
    UFUNCTION(BlueprintPure, Category = "Saskarta|Power")
    bool IsCharging() const { return Core.IsCharging(); }
    UFUNCTION(BlueprintPure, Category = "Saskarta|Power")
    bool HasCompletedFirstRecharge() const { return Core.bFirstRechargeComplete; }
    UFUNCTION(BlueprintPure, Category = "Saskarta|Power")
    bool AreLampsOn() const { return bLampsOn; }
    /** True only after looking at the visible physical battery for the inspection dwell. */
    UFUNCTION(BlueprintPure, Category = "Saskarta|Power")
    bool IsInspectingBattery() const { return BatteryGaze.bVisible; }
    static FKey LampPadKey() { return EKeys::Gamepad_RightThumbstick; }
    /** Kilometres left at cruise with the current radio and lamps; -1 when the bar never empties. */
    UFUNCTION(BlueprintPure, Category = "Saskarta|Power")
    float GetRangeKm() const;
    /** Spends charge for a gameplay action. False, and nothing spent, below the cost. */
    UFUNCTION(BlueprintCallable, Category = "Saskarta|Power")
    bool Spend(float Percent) { return Core.TrySpend(Percent); }
    UFUNCTION(BlueprintCallable, Category = "Saskarta|Power")
    void SetCharge(float Percent);
    /** One line under the power line for Seconds (STOP TO TUNE MOTOR). */
    UFUNCTION(BlueprintCallable, Category = "Saskarta|Power")
    void ShowNotice(const FString& Text, float Seconds = 3.f);
    /** A stationary motor activity may park move input without freezing the recharge timer. */
    UFUNCTION(BlueprintCallable, Category = "Saskarta|Power")
    void SetRestActivityOpen(bool bOpen) { bRestActivityOpen = bOpen; }

    const FSaskartaPowerCore& GetCore() const { return Core; }

private:
    void Poll();
    /** 50 Hz: lamps F/R3 and instruments H/L3. The established package path uses key polling. */
    void PollKeys();
    void OnLampsPressed();
    bool CanUseInstruments(APlayerController* PC) const;
    void UpdateBattery(ACharacter* Carrier);
    void UpdateBatteryGaze(APlayerController* PC, bool bEligible, float DeltaS);
    void ApplyLamps(ACharacter* Carrier);
    void UpdateWidget(APlayerController* PC, bool bShow, const FSaskartaPowerHudInput& HudIn, float DeltaS);
    void AttachDisplayToView(APlayerController* PC);
    APlayerController* FindController() const;
    void HandleWritingRun(UWorld* World, USaskartaSaveGame* Save);
    void HandleRestoredRun(UWorld* World, USaskartaSaveGame* Save);
    void ApplyEmptyDrive(ACharacter* Carrier);
    void ReleaseEmptyDrive();
    void StartEmptyAudio();
    void UpdateEmptyAudio();
    void StopEmptyAudio();
    UFUNCTION() void HandleCaptionShow(const FText& Text, FName Target, float DurationS);
    UFUNCTION() void HandleCaptionHide(FName Target);

    FSaskartaPowerCore Core;
    FSaskartaPowerHud Hud;
    FSaskartaPowerTelemetry Telemetry;
    FSaskartaBatteryGaze BatteryGaze;
    bool bLampsOn = true;
    bool bLampsKeyWasDown = false;
    bool bRestActivityOpen = false;
    bool bTelemetryOpen = false;
    bool bTelemetryKeyWasDown = false;
    bool bBatteryTutorialShown = false;
    bool bRestTutorialShown = false;
    float TutorialDriveS = 0.f;
    bool bInscriptionReading = false;
    TWeakObjectPtr<USaskartaEventRunner> CaptionRunner;
    double LastBatterySearchS = -10.0;
    TWeakObjectPtr<ACharacter> BatteryCarrier;
    TWeakObjectPtr<AActor> BatteryActor;
    TWeakObjectPtr<UPrimitiveComponent> BatteryBody;
    UPROPERTY(Transient) TArray<TObjectPtr<UMaterialInstanceDynamic>> BatterySegments;
    float LastPhysicalCharge = -1.f;
    int32 AppliedLamps = -1;   // -1 unknown, else 0/1: visibility is set on change only
    double LastPollS = -1.0;
    TWeakObjectPtr<ACharacter> ActiveCarrier;
    TWeakObjectPtr<ACharacter> EmptyDriveCarrier;
    bool bEmptyEpisode = false;
    bool bEmptyCoasting = false;
    bool bEmptyBrakesOwned = false;
    bool bPreviousSeparateBraking = false;
    float PreviousEmptyMaxSpeed = 0.f;
    float PreviousEmptyAcceleration = 0.f;
    float PreviousEmptyBraking = 0.f;
    float PreviousEmptyFriction = 0.f;
    float PreviousEmptyFrictionFactor = 0.f;
    float AppliedEmptyMaxSpeed = 0.f;
    float EmptyCoastBraking = 0.f;
    double EmptyCoastStartedS = -1.0;
    double LastEmptyDriveS = -1.0;
    double EmptyAudioStartedS = -1.0;
    int32 EmptyAudioStage = 0;
    UPROPERTY(Transient) TArray<TObjectPtr<USoundBase>> EmptySounds;
    UPROPERTY(Transient) TObjectPtr<UAudioComponent> EmptyAudio;
    UPROPERTY(Transient) TObjectPtr<USaskartaChargeAudio> ChargeAudio;
    TSharedPtr<FStreamableHandle> EmptySoundLoad;
    TWeakObjectPtr<ACharacter> LampCarrier;
    UPROPERTY(Transient)
    TObjectPtr<USaskartaPowerWidget> Widget;
    UPROPERTY(Transient)
    TObjectPtr<UWidgetComponent> WidgetPlane;
    TWeakObjectPtr<UCameraComponent> DisplayCamera;
    FTimerHandle Timer;
    FTimerHandle KeyTimer;
    FDelegateHandle WritingRunHandle;
    FDelegateHandle RestoredRunHandle;
};
