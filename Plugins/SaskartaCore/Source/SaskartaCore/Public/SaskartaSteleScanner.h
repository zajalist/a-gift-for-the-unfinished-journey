// USaskartaSteleScanner: the carrier reads the steles (task STELESCAN, docs/look/STELE_SCAN.md section 3).
//
// A world subsystem (game and PIE worlds), a thin shell over FSaskartaSteleScanCore
// (SaskartaSteleScanLogic.h), which makes every decision and is what the Saskarta.Steles.* tests drive.
//
//   - Data: DA_Saskarta_SteleScan (editor builds fall back to a transient import of
//     docs/story/inscriptions.json).
//   - Finding the stones: actors tagged "Stele" whose other tag is their id (Stele_WayStone_12; the
//     tags are written by Tools/Look/build_stele_scan.py cpd). Levels already loaded at BeginPlay are
//     walked once; World Partition cells register as they stream in (FWorldDelegates::LevelAddedToWorld).
//     Only weak pointers are kept; a stone that streams back in has its CPD defaults again (no scan).
//   - A 0.25 s timer, no Tick: road m from the event runner, the candidates in the window around it
//     (usually 0-2), their view from the player camera, ONE visibility trace for the best candidate,
//     then Core.Decide.
//   - A reading: runtime Custom Primitive Data 2, 3, 8 on the stone (M_Saskarta_SteleFace sweeps and
//     lights the grooves; no MID, no CVar, no render-state recreation), the scan ping, the text on the
//     runner's caption channel (target CaptionTarget, default "Scan" = WBP_Saskarta_Caption's ScanBlock),
//     OnSteleRead for designers and tests, and for a full reading the author's voice through
//     USaskartaEventRunner::TryPlayAuxCarrierLine (the story Voice channel: never over a story line,
//     the station ducks). A refused voice is retried every 0.25 s for VoiceWaitMaxS, then the reading
//     stays text only and the next stone with the same text gets the full reading.
//   - Voice clips are async-loaded 150 m ahead (never a synchronous load).
//
// Prompted scan (Tuning.bPrompted, the default; docs/look/STELE_SCAN.md "Prompted scan"): the poll only
// picks the stele to offer (Core.PromptTarget) and shows "E · SCAN INSCRIPTION" on the runner caption
// channel (target PromptTarget, default "ScanPrompt" = WBP_Saskarta_Caption's ScanPromptLine). While the
// line is up a 0.01 s timer tracks E / Gamepad_FaceButton_Bottom edges (as the runner's prompts do: a
// looping timer can miss WasInputKeyJustPressed's single frame); a press asks ScanChargeHook (unbound =
// free), then Core.BeginRead and the reading above. Never offered outside Playing, in a cinematic, while
// a story subtitle, a runner prompt or the motor's E prompt is up, or while a reading is in progress.
//
// Console: Saskarta.Steles.Dump, Saskarta.Steles.Read <SteleId>, Saskarta.Steles.Reset.
//
// C++ built only while the editor is closed (never leave an unbuilt plugin enabled).

#pragma once

#include "CoreMinimal.h"
#include "Subsystems/WorldSubsystem.h"
#include "TimerManager.h"
#include "SaskartaSteleScanLogic.h"
#include "SaskartaSteleScanner.generated.h"

class AActor;
class ULevel;
class UPrimitiveComponent;
class USaskartaEventRunner;
class USaskartaSteleScanAsset;
class USoundBase;
struct FSaskartaInscriptionDef;
struct FStreamableHandle;

/** What one reading showed (OnSteleRead). */
USTRUCT(BlueprintType)
struct SASKARTACORE_API FSaskartaSteleReadout
{
    GENERATED_BODY()

    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Steles")
    FName SteleId;

    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Steles")
    FName InscriptionId;

    /** The machine's number for the text (first-read order). */
    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Steles")
    int32 Number = 0;

    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Steles")
    bool bMatch = false;

    /** Exactly what the HUD shows (one line for a match, three for a full reading). */
    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Steles")
    FString Text;

    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Steles")
    FString EnglishApprox;

    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Steles")
    int32 AtlasCell = INDEX_NONE;
};

/** What the machine knows of one stele, for the route map / ROUTE LOG (DescribeStele). */
USTRUCT(BlueprintType)
struct SASKARTACORE_API FSaskartaSteleLogEntry
{
    GENERATED_BODY()

    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Steles")
    FName SteleId;

    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Steles")
    FName InscriptionId;

    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Steles")
    float RoadM = 0.f;

    /** The machine transliteration, as the full reading prints it (RZAG-ZRIRIT). */
    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Steles")
    FString Translit;

    /** "~ EN: ..." exactly as the full reading prints it (resolved when its beat has fired). */
    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Steles")
    FString EnglishLine;

    /** The face centre in world space; valid only while the stone is streamed in (bHasLocation). */
    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Steles")
    FVector Location = FVector::ZeroVector;

    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Steles")
    bool bHasLocation = false;
};

DECLARE_DYNAMIC_MULTICAST_DELEGATE_OneParam(FSaskartaSteleReadSignal, const FSaskartaSteleReadout&, Readout);
DECLARE_DYNAMIC_MULTICAST_DELEGATE_OneParam(FSaskartaStelePromptSignal, FName, SteleId);
/** Energy hook: (stele id, Tuning.ScanChargeCost) -> may this scan start? Unbound = yes. Spend inside it. */
DECLARE_DELEGATE_RetVal_TwoParams(bool, FSaskartaSteleScanChargeHook, FName /*SteleId*/, float /*Cost*/);

UCLASS()
class SASKARTACORE_API USaskartaSteleScanner : public UWorldSubsystem
{
    GENERATED_BODY()

public:
    UFUNCTION(BlueprintPure, Category = "Saskarta|Steles", meta = (WorldContext = "WorldContextObject"))
    static USaskartaSteleScanner* GetSteleScanner(const UObject* WorldContextObject);

    /** A reading's text is on the HUD (a match at once, a full reading at TextAtS). */
    UPROPERTY(BlueprintAssignable, Category = "Saskarta|Steles")
    FSaskartaSteleReadSignal OnSteleRead;

    /** The scan prompt appeared for SteleId (None when it went away). */
    UPROPERTY(BlueprintAssignable, Category = "Saskarta|Steles")
    FSaskartaStelePromptSignal OnScanPromptChanged;

    /** Energy hook for the charge system (not implemented yet: nothing binds it, scans are free). */
    FSaskartaSteleScanChargeHook ScanChargeHook;

    /** The CRT shows "E · SCAN INSCRIPTION" now (the motor assist ignores E while it does). */
    UFUNCTION(BlueprintPure, Category = "Saskarta|Steles")
    bool IsScanPromptVisible() const { return PromptStele != INDEX_NONE; }

    /** The E press on the offered stele (also callable from Blueprint / tests). Returns true if a reading started. */
    UFUNCTION(BlueprintCallable, Category = "Saskarta|Steles")
    bool ScanPromptedStele();

    /** Reads SteleId now if it is registered, ignoring range, angle, sight and pacing (debug). */
    UFUNCTION(BlueprintCallable, Category = "Saskarta|Steles")
    bool ForceRead(FName SteleId);

    /** Every stone unread, the numbering and the voiced texts forgotten. */
    UFUNCTION(BlueprintCallable, Category = "Saskarta|Steles")
    void ResetReadings();

    /** Uses this data instead of DA_Saskarta_SteleScan (tests, level overrides). */
    UFUNCTION(BlueprintCallable, Category = "Saskarta|Steles")
    void SetAsset(USaskartaSteleScanAsset* InAsset);

    UFUNCTION(BlueprintPure, Category = "Saskarta|Steles")
    int32 NumRegisteredSteles() const { return Components.Num(); }

    /** The route map: SteleId's text lines, road m and (if streamed in) location. False for an unknown id. */
    UFUNCTION(BlueprintCallable, Category = "Saskarta|Steles")
    bool DescribeStele(FName SteleId, FSaskartaSteleLogEntry& Out) const;

    /** Multi-line state for Saskarta.Steles.Dump. */
    FString DumpState() const;

    /**
     * Writes runtime Custom Primitive Data (SetCustomPrimitiveDataFloat: a GPU-scene data update, never
     * the component defaults, which would recreate the render state). Returns the number of writes.
     */
    static int32 ApplyCpd(UPrimitiveComponent* Component, const TArray<FSaskartaSteleCpdWrite>& Writes);

    const FSaskartaSteleScanCore& GetCore() const { return Core; }

    // ------------------------------------------------------------------ UWorldSubsystem
    virtual void Initialize(FSubsystemCollectionBase& Collection) override;
    virtual void Deinitialize() override;
    virtual void OnWorldBeginPlay(UWorld& InWorld) override;

protected:
    virtual bool DoesSupportWorldType(const EWorldType::Type WorldType) const override;

private:
    void Poll();
    void RebuildCore();
    void RegisterLevel(ULevel* Level);
    void HandleLevelAdded(ULevel* Level, UWorld* World);
    bool BuildView(int32 Index, const FVector& CamLoc, const FVector& CamFwd, FSaskartaSteleView& OutView, FVector& OutFace) const;
    bool LineOfSight(const FVector& From, const FVector& To, const AActor* Stele) const;
    void StartReading(const FSaskartaSteleReadDecision& Decision, double NowS);
    void ShowReadingText();
    void VoiceStep();
    void EndVoice(bool bAttempted, bool bPlayed, float HideInS);
    void ShowCaption(const FString& Text);
    void HideCaption();
    void Prefetch(float RoadM);
    bool CanPrompt(const USaskartaEventRunner* R) const;
    void SetPromptStele(int32 Index);
    void PollScanKey();
    FString ApproxFor(const FSaskartaInscriptionDef& Ins) const;
    UPrimitiveComponent* ComponentFor(int32 Index) const;
    USaskartaEventRunner* Runner() const;
    double Now() const;

    UFUNCTION()
    void HandleCaptionShow(const FText& Text, FName Target, float DurationS);

    UFUNCTION()
    void HandleCaptionHide(FName Target);

    UPROPERTY()
    TObjectPtr<USaskartaSteleScanAsset> Asset;

    FSaskartaSteleScanCore Core;
    FSaskartaSteleScanTuning Tuning;
    /** Stele id -> its mesh component (weak: World Partition streams them). */
    TMap<FName, TWeakObjectPtr<UPrimitiveComponent>> Components;
    /** Stele id -> local face centre (cm). */
    TMap<FName, FVector> FaceLocal;
    TMap<FName, TSharedPtr<FStreamableHandle>> VoiceHandles;
    TSharedPtr<FStreamableHandle> SoundHandle;
    TWeakObjectPtr<USaskartaEventRunner> BoundRunner;
    FDelegateHandle LevelAddedHandle;
    float LastRoadM = -1.f;
    bool bHudBusy = false;
    /** True while the scanner broadcasts its own caption (so CaptionTarget Hud never marks the HUD busy). */
    bool bSelfCaption = false;
    double HudBusySinceS = 0.0;

    // --- the reading in progress
    int32 ActiveStele = INDEX_NONE;
    ESaskartaSteleReadKind ActiveKind = ESaskartaSteleReadKind::None;
    bool bActiveTryVoice = false;
    int32 ActiveNumber = 0;
    double ActiveStartS = 0.0;
    double VoiceAskSinceS = 0.0;

    // --- the scan prompt
    int32 PromptStele = INDEX_NONE;
    bool bScanKeyWasDown = false;
    bool bScanPadWasDown = false;
    FTimerHandle KeyTimer;

    FTimerHandle PollTimer;
    FTimerHandle TextTimer;
    FTimerHandle VoiceTimer;
    FTimerHandle HideTimer;
    /** Brings the radio back up after a voiced reading (the station ducks under it). */
    FTimerHandle UnderReleaseTimer;
};
