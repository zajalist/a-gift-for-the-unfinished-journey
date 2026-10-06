// Progressive, noninteractive gameplay hints. Loading and title never teach controls.
// CIN01 actual handback (or successful Continue) gates the pure data-driven scheduler.
// Presentation uses existing input glyphs in a small transparent viewport overlay.
// Console: Saskarta.Hints.Dump, Saskarta.Hints.Reset; cvar saskarta.Hints.Enable.

#pragma once

#include "CoreMinimal.h"
#include "Containers/Ticker.h"
#include "Engine/DataAsset.h"
#include "GameFramework/SaveGame.h"
#include "Subsystems/WorldSubsystem.h"
#include "SaskartaOnboardingLogic.h"
#include "SaskartaOnboarding.generated.h"

class APlayerController;
class UInputComponent;
class USaskartaGameplayHintWidget;
class USaskartaSaveGame;

/** The last input device (a Slate input pre-processor): the hints' and the route map's key labels. */
struct SASKARTACORE_API FSaskartaInputDevice
{
    static bool IsGamepad();
    static void Register();
    static void Unregister();
};

/** Saskarta_Hints: the hints already shown. */
UCLASS()
class SASKARTACORE_API USaskartaHintSave : public USaveGame
{
    GENERATED_BODY()

public:
    static const TCHAR* Slot;

    UPROPERTY()
    TArray<FName> SeenHints;
};

/** DA_Saskarta_Onboarding: onboarding.json for packaged builds. */
UCLASS(BlueprintType)
class SASKARTACORE_API USaskartaOnboardingAsset : public UPrimaryDataAsset
{
    GENERATED_BODY()

public:
    static const TCHAR* AssetPath;

    /** The text of docs/story/onboarding.json. */
    UPROPERTY(EditAnywhere, Category = "Saskarta|Onboarding", meta = (MultiLine = true))
    FString Json;

#if WITH_EDITOR
    /** Copies docs/story/onboarding.json into Json (then save the asset). */
    UFUNCTION(CallInEditor, Category = "Saskarta|Onboarding")
    void ReimportFromDocs();
#endif
};

UCLASS()
class SASKARTACORE_API USaskartaOnboarding : public UWorldSubsystem
{
    GENERATED_BODY()

public:
    UFUNCTION(BlueprintPure, Category = "Saskarta|Onboarding", meta = (WorldContext = "WorldContextObject"))
    static USaskartaOnboarding* GetOnboarding(const UObject* WorldContextObject);

    virtual bool ShouldCreateSubsystem(UObject* Outer) const override;
    virtual void OnWorldBeginPlay(UWorld& InWorld) override;
    virtual void Deinitialize() override;

    /** A compact, noninteractive gameplay hint is visible now. */
    UFUNCTION(BlueprintPure, Category = "Saskarta|Onboarding")
    bool IsHintVisible() const { return Core.IsActive(); }

    /** Forgets every shown hint (and the save). */
    UFUNCTION(BlueprintCallable, Category = "Saskarta|Onboarding")
    void ResetHints();

    const FSaskartaOnboardingCore& GetCore() const { return Core; }
    FString DumpState() const;

private:
    void LoadData();
    void LoadSeen();
    void SaveSeen();
    void Poll();
    bool OnTicker(float DeltaTime);
    void BuildFacts(APlayerController* PC, FSaskartaHintFacts& Out);
    void Apply(const FSaskartaHintStep& Step, APlayerController* PC);
    void UpdateWidget(APlayerController* PC, const FString* Text);
    UFUNCTION()
    void HandleCinematicStarted(FName Id);
    UFUNCTION()
    void HandleCinematicFinished(FName Id);
    void HandleRestoredRun(UWorld* World, USaskartaSaveGame* Save);
    void ResetRunTeaching();
    void BindInput(APlayerController* PC);
    void UnbindInput();
    void OnRadioKey();

    FSaskartaOnboardingCore Core;
    bool bLoaded = false;
    bool bInputDeviceRegistered = false;
    int32 SavedSeenCount = -1;
    // Playing is entered before the first cinematic; only its handback opens hints.
    bool bGameplayReady = false;
    bool bOpeningStarted = false;
    bool bDriveMotionSeen = false;
    bool bLookMotionSeen = false;
    bool bHaveLookBaseline = false;
    // Actual displayed, unblocked time for the first MOVE / STEER / LOOK row.
    double DriveHintVisibleS = 0.0;
    double LastDriveHintPollS = -1.0;
    bool bDriveHintCounting = false;
    FRotator LastControlRotation = FRotator::ZeroRotator;

    // --- edge tracking for the actions
    int32 LastRadioOn = -1;
    /** R / D-pad up since the last poll (the station also switches itself on; only the player's key teaches). */
    bool bRadioKey = false;
    double LastRadioKeyS = -1.0e9;
    int32 LastLampsOn = -1;
    bool bLastTurbo = false;
    bool bRadioOffByPlayer = false;
    int32 LastMapOpens = -1;
    int32 LastTuningOpens = -1;
    int32 LastScanned = -1;
    double LastScanS = -1.0e9;

    UPROPERTY(Transient)
    TObjectPtr<USaskartaGameplayHintWidget> Widget;
    TWeakObjectPtr<UInputComponent> BoundInput;
    TWeakObjectPtr<APlayerController> BoundController;
    FTSTicker::FDelegateHandle TickerHandle;
};
