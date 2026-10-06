#pragma once

#include "CoreMinimal.h"
#include "Blueprint/UserWidget.h"
#include "Components/Widget.h"
#include "Components/RetainerBox.h"
#include "InputCoreTypes.h"
#include "Subsystems/WorldSubsystem.h"
#include "SaskartaMotorResonanceLogic.h"
#include "SaskartaMotorResonance.generated.h"

class APlayerController;
class APawn;
class UBorder;
class UCanvasPanelSlot;
class UProgressBar;
class USoundBase;
class UTextBlock;
class FSaskartaMotorResonanceInput;
class SSaskartaMotorDiagram;
class URetainerBox;
class USaskartaMotorResonanceAudio;
class UTexture2D;
struct FStreamableHandle;

/** Render only when the bounded motor presentation clock requests a new frame. */
UCLASS()
class SASKARTACORE_API USaskartaMotorRetainer : public URetainerBox
{
    GENERATED_BODY()
public:
    USaskartaMotorRetainer(const FObjectInitializer& ObjectInitializer);
};

/** A schematic of the active crank cycle; its phase comes from the gameplay clock. */
UCLASS()
class SASKARTACORE_API USaskartaMotorDiagram : public UWidget
{
    GENERATED_BODY()
public:
    /** Set before RebuildWidget so loading never flashes gameplay instructions. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Saskarta|Motor")
    bool bLoadingPresentation = false;

    /** Smoothed readiness only; no gameplay clock, input or automatic advancement. */
    UFUNCTION(BlueprintCallable, Category="Saskarta|Loading")
    void PresentLoading(float Readiness);

    void Configure(UObject* Font);
    void Present(const FSaskartaMotorResonanceLogic& Logic, bool bGamepad, float Charge, float GapM, bool bInspectingBattery);
protected:
    virtual TSharedRef<SWidget> RebuildWidget() override;
    virtual void ReleaseSlateResources(bool bReleaseChildren) override;
    virtual void BeginDestroy() override;
private:
    void LoadGlyphs();
    TSharedPtr<SSaskartaMotorDiagram> Diagram;
    UPROPERTY(Transient) TObjectPtr<UObject> FontObject;
    UPROPERTY(Transient) TMap<FName, TObjectPtr<UTexture2D>> GlyphTextures;
    TSharedPtr<FStreamableHandle> GlyphLoad;
    bool bGlyphLoadRequested = false;
    FSaskartaMotorResonanceLogic Frame;
    float LoadingReadiness = 0.f;
    float ChargePercent = 0.f;
    float DustGapM = 0.f;
    bool bPad = false;
    bool bShowCharge = false;
};

/** The carrier's CRT motor schematic, shared by stationary charging and pursuit. */
UCLASS()
class SASKARTACORE_API USaskartaMotorResonanceWidget : public UUserWidget
{
    GENERATED_BODY()
public:
    void Present(const FSaskartaMotorResonanceLogic& Logic, bool bShow, bool bGamepad,
                 float Charge, float GapM, bool bInspectingBattery);
protected:
    virtual void NativeOnInitialized() override;
private:
    UPROPERTY(Transient) TObjectPtr<USaskartaMotorDiagram> Diagram;
    UPROPERTY(Transient) TObjectPtr<URetainerBox> Retainer;
    double LastPaintS = -1.0;
    FSaskartaMotorResonanceLogic::EFeedback LastFeedback = FSaskartaMotorResonanceLogic::EFeedback::None;
    bool bLastInspectingBattery = false;
};

/** Owns timing and input only. EarlyStorm owns pursuit movement, distance and failure. */
UCLASS()
class SASKARTACORE_API USaskartaMotorResonanceSubsystem : public UTickableWorldSubsystem
{
    GENERATED_BODY()
public:
    virtual bool ShouldCreateSubsystem(UObject* Outer) const override;
    virtual void OnWorldBeginPlay(UWorld& InWorld) override;
    virtual void Deinitialize() override;
    virtual void Tick(float DeltaTime) override;
    virtual TStatId GetStatId() const override;
    virtual bool IsTickableWhenPaused() const override { return true; }

    UFUNCTION(BlueprintCallable, Category="Saskarta|Motor") void BeginPursuit();
    UFUNCTION(BlueprintCallable, Category="Saskarta|Motor") void EndPursuit();
    UFUNCTION(BlueprintPure, Category="Saskarta|Motor") float GetDriveMultiplier() const;
    UFUNCTION(BlueprintPure, Category="Saskarta|Motor") bool IsActive() const { return Logic.IsActive(); }
    /** Pursuit must freeze movement AND dust while this shared gate is closed. */
    UFUNCTION(BlueprintPure, Category="Saskarta|Motor") bool CanAcceptInput() const { return IsActive() && ControlsAvailable(); }
    UFUNCTION(BlueprintCallable, Category="Saskarta|Motor") void SetPursuitGap(float GapM);
    UFUNCTION(BlueprintCallable, Category="Saskarta|Motor") void BeginTuning();
    UFUNCTION(BlueprintCallable, Category="Saskarta|Motor") void EndTuning();
    UFUNCTION(BlueprintPure, Category="Saskarta|Motor") bool IsTuning() const { return Logic.IsTuning(); }
    /** Read-only timing state (USaskartaAutopilot). */
    const FSaskartaMotorResonanceLogic& GetLogic() const { return Logic; }
    /** Defer the start of carrier speech while a control warning is approaching. */
    bool IsInputWarningActive() const
    {
        return IsActive() && (Logic.BalanceVisible() ||
            (!Logic.bBeatJudged && Logic.NextBeatS - Logic.ElapsedS <= 0.35));
    }

    /** Real Slate key events, including release; repeats never score. */
    bool HandleKey(const FKey& Key, bool bDown, bool bRepeat);

private:
    APlayerController* GetPC() const;
    bool ControlsAvailable() const;
    bool HasViewportFocus() const;
    void Begin(FSaskartaMotorResonanceLogic::EMode Mode);
    void End();
    void UpdateDisplay(bool bShow);
    void ApplyReward();
    void PlayFeedback(FSaskartaMotorResonanceLogic::EFeedback Result);

    FSaskartaMotorResonanceLogic Logic;
    TSharedPtr<FSaskartaMotorResonanceInput> Processor;
    TSet<FKey> HeldKeys;
    TWeakObjectPtr<APlayerController> TuningController;
    TWeakObjectPtr<APawn> SessionPawn;
    UPROPERTY(Transient) TObjectPtr<USaskartaMotorResonanceWidget> Widget;
    UPROPERTY(Transient) TObjectPtr<USaskartaMotorResonanceAudio> MotorAudio;
    float PursuitGapM = 0.f;
    bool bOwnsMoveLock = false;
    bool bGamepad = false;
};
