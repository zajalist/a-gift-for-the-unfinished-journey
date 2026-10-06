#pragma once

#include "CoreMinimal.h"
#include "Blueprint/UserWidget.h"
#include "InputCoreTypes.h"
#include "Subsystems/WorldSubsystem.h"
#include "SaskartaRadioRepairLogic.h"
#include "SaskartaRadioRepair.generated.h"

class APlayerController;
class APawn;
class UBorder;
class UCanvasPanel;
class UProgressBar;
class URetainerBox;
class UTextBlock;
class UImage;
class USizeBox;
class USaskartaSaveGame;
class USaskartaTelemetryGraph;
class FSaskartaRadioRepairInput;

UCLASS(meta=(DisableNativeTick))
class SASKARTACORE_API USaskartaRadioRepairWidget : public UUserWidget
{
    GENERATED_BODY()
public:
    void Present(bool bOpen, bool bPrompt, bool bParked, bool bPad, const FSaskartaRadioRepairLogic& State,
        const TArray<FVector2D>& VoiceEnvelope);
protected:
    virtual void NativeOnInitialized() override;
private:
    UPROPERTY(Transient) TObjectPtr<UCanvasPanel> Card;
    UPROPERTY(Transient) TObjectPtr<UBorder> Prompt;
    UPROPERTY(Transient) TObjectPtr<URetainerBox> Retainer;
    UPROPERTY(Transient) TObjectPtr<UTextBlock> PromptText;
    UPROPERTY(Transient) TObjectPtr<UTextBlock> PromptKey;
    UPROPERTY(Transient) TObjectPtr<UImage> PromptGlyph;
    UPROPERTY(Transient) TObjectPtr<USizeBox> PromptGlyphBounds;
    UPROPERTY(Transient) TObjectPtr<UTextBlock> StageText;
    UPROPERTY(Transient) TObjectPtr<UTextBlock> ValueText;
    UPROPERTY(Transient) TObjectPtr<UTextBlock> HintText;
    UPROPERTY(Transient) TObjectPtr<UTextBlock> StabilityText;
    UPROPERTY(Transient) TObjectPtr<UTextBlock> FooterText;
    UPROPERTY(Transient) TObjectPtr<UProgressBar> SignalBar;
    UPROPERTY(Transient) TObjectPtr<UProgressBar> StabilityBar;
    UPROPERTY(Transient) TObjectPtr<USaskartaTelemetryGraph> EnvelopeGraph;
};

/** Optional parked radio adjustment. Owns one move lock and a transient station reception layer. */
UCLASS()
class SASKARTACORE_API USaskartaRadioRepairSubsystem : public UTickableWorldSubsystem
{
    GENERATED_BODY()
public:
    virtual bool ShouldCreateSubsystem(UObject* Outer) const override;
    virtual void OnWorldBeginPlay(UWorld& InWorld) override;
    virtual void Deinitialize() override;
    virtual void Tick(float DeltaTime) override;
    virtual TStatId GetStatId() const override;
    virtual bool IsTickableWhenPaused() const override { return true; }
    bool IsOpen() const { return bOpen; }
    bool IsComplete() const { return Logic.IsComplete(); }
    bool HandleKey(const FKey& Key, bool bDown, bool bRepeat);
private:
    APlayerController* GetPC() const;
    bool InEncounter() const;
    bool ControlsAvailable() const;
    bool CanOpen() const;
    void Open();
    void Close(bool bSave);
    void ClearReception();
    void UpdateDisplay(bool bAllowed);
    void SaveProgress();
    void HandleWritingRun(UWorld* World, USaskartaSaveGame* Save);
    void HandleRestoredRun(UWorld* World, USaskartaSaveGame* Save);
    FSaskartaRadioRepairLogic Logic;
    TSharedPtr<FSaskartaRadioRepairInput> Processor;
    TSet<FKey> HeldKeys;
    TWeakObjectPtr<APlayerController> LockedController;
    TWeakObjectPtr<APawn> SessionPawn;
    UPROPERTY(Transient) TObjectPtr<USaskartaRadioRepairWidget> Widget;
    bool bOpen = false;
    bool bOwnsMoveLock = false;
    bool bResumePending = false;
    bool bWasAllowed = false;
    bool bPad = false;
    float UiAgeS = 0.f;
    float CompleteAgeS = 0.f;
    TArray<float> EnvelopeHistory;
    FDelegateHandle WritingRunHandle;
    FDelegateHandle RestoredRunHandle;
};
