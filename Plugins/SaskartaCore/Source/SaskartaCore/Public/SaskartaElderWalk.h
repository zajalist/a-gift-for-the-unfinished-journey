#pragma once

#include "CoreMinimal.h"
#include "Blueprint/UserWidget.h"
#include "Engine/DataAsset.h"
#include "Subsystems/WorldSubsystem.h"
#include "SaskartaElderWalk.generated.h"

class ACharacter;
class APlayerController;
class UAnimationAsset;
class UAudioComponent;
class UStaticMesh;
class UStaticMeshComponent;
class UHorizontalBox;
class USaskartaEventRunner;
class USaskartaElderWalkHint;
class UImage;
class UTextBlock;
class USoundBase;
struct FStreamableHandle;

/** Real, reviewed staff/boot contact clips. Missing certification leaves normal walking intact. */
UCLASS(BlueprintType)
class SASKARTACORE_API USaskartaElderWalkProfile : public UDataAsset
{
    GENERATED_BODY()
public:
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Contacts") bool bContactsReviewed = false;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Contacts") TSoftObjectPtr<UAnimationAsset> StaffEnter;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Contacts") TSoftObjectPtr<UAnimationAsset> StaffHold;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Contacts") TSoftObjectPtr<UAnimationAsset> StaffRecover;
    /** Authored Hayba UMG presentation; the native transparent row is temporary until this is assigned. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Presentation") TSoftClassPtr<USaskartaElderWalkHint> HintWidgetClass;
    /** Source mesh component centimetres, including the real staff surface rather than its pivot. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Contacts") FVector StaffTipComponent = FVector::ZeroVector;
    /** Lowest source staff vertex in staff011 local space; follows the animated bone. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Contacts") FVector StaffTipBoneLocal = FVector(-0.013812895864, 0.0, -0.025146557018);
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Contacts", meta=(ClampMin="0",ClampMax="12")) float MaxContactSlopeDegrees = 4.f;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Contacts", meta=(ClampMin="0",ClampMax="8")) float MaxContactErrorCm = 3.f;
};

/** Temporary transparent UMG row. Authored widget can inherit this class after the editor pass. */
UCLASS()
class SASKARTACORE_API USaskartaElderWalkHint : public UUserWidget
{
    GENERATED_BODY()
public:
    void Show(const FString& Caption, UObject* KeyTexture, UObject* CaptionFont);
    void Hide();
protected:
    virtual void NativeOnInitialized() override;
private:
    UPROPERTY(Transient) TObjectPtr<UHorizontalBox> Row;
    UPROPERTY(Transient) TObjectPtr<UImage> AuthoredGlyph;
    UPROPERTY(Transient) TObjectPtr<UTextBlock> AuthoredCaption;
    bool bAuthoredLayout = false;
    FString LastCaption;
};

UENUM(BlueprintType)
enum class ESaskartaElderFooting : uint8 { Walking, Unsteady, StaffEnter, StaffHold, Recovering };

/** Samyor's human-only climb. Never moves the camera, warps the actor, scales a bone, or resets a beat. */
UCLASS()
class SASKARTACORE_API USaskartaElderWalk : public UTickableWorldSubsystem
{
    GENERATED_BODY()
public:
    virtual bool ShouldCreateSubsystem(UObject* Outer) const override;
    virtual void OnWorldBeginPlay(UWorld& InWorld) override;
    virtual void Deinitialize() override;
    virtual void Tick(float DeltaTime) override;
    virtual bool IsTickableWhenPaused() const override { return true; }
    virtual TStatId GetStatId() const override;

    UFUNCTION(BlueprintPure, Category="Saskarta|Elder") bool IsActive() const { return bActive; }
    UFUNCTION(BlueprintPure, Category="Saskarta|Elder") ESaskartaElderFooting GetFooting() const { return Footing; }
    UFUNCTION(BlueprintPure, Category="Saskarta|Elder") float GetWeightShift() const { return WeightShift; }
    UFUNCTION(BlueprintPure, Category="Saskarta|Elder") float GetWindWarning() const;
    UFUNCTION(BlueprintPure, Category="Saskarta|Elder") bool HasReviewedContacts() const;
    // Read-only footing-check state for USaskartaAutopilot (no behaviour change).
    bool IsFootingCheckActive() const { return bActive && SlipTime >= 0.f; }
    int32 GetFootingCheckMode() const { return SlipMode; }
    float GetFootingSway() const { return Sway; }
    float GetFootingSwayPush() const { return SwayPush; }
    int32 GetFootingHealth() const { return Health; }
    /** Designer handoff: call after source-contact and rendered review, never infer approval from an asset name. */
    UFUNCTION(BlueprintCallable, Category="Saskarta|Elder") void ConfigureContacts(USaskartaElderWalkProfile* ReviewedProfile);
    UFUNCTION(BlueprintCallable, Category="Saskarta|Elder") void SetReducedGusts(bool bReduced) { bReducedGusts = bReduced; }
    UFUNCTION(BlueprintCallable, Category="Saskarta|Elder") void SetToggleStaff(bool bToggle) { bToggleStaff = bToggle; bReleaseToRearm = true; bStaffLatched = false; }

private:
    void LoadAssets();
    void ResolveAssets();
    void AttachStaffVisuals(float DeltaTime);
    void Suspend(bool bCanRestoreAnimation);
    void PollSupport(ACharacter* Human);
    void SetSpeedLimit(float Limit);
    void ReleaseSpeedLimit();
    void AcquireFacing();
    void ReleaseFacing();
    bool PlayOwnedAnimation(UAnimationAsset* Animation, FName Mode, bool bLoop);
    void ReleaseAnimation(bool bCanRestore);
    void BeginPlant();
    void BeginRecovery();
    void Cue(USoundBase* Sound, float Volume);
    void UpdateHint(APlayerController* PC, const USaskartaEventRunner* Runner, float DeltaTime);
    // 2026-10-05: quick-press footing check (mash SPACE / A) with three health pips.
    void TickSlip(APlayerController* PC, ACharacter* Human, float DeltaTime, bool bWalking);
    void ShowSlipOverlay();
    void HideSlipOverlay();

    UPROPERTY(Transient) TObjectPtr<USaskartaElderWalkProfile> Profile;
    UPROPERTY(Transient) TObjectPtr<UAnimationAsset> EnterClip;
    UPROPERTY(Transient) TObjectPtr<UAnimationAsset> HoldClip;
    UPROPERTY(Transient) TObjectPtr<UAnimationAsset> RecoverClip;
    UPROPERTY(Transient) TObjectPtr<USoundBase> GustSound;
    UPROPERTY(Transient) TObjectPtr<USoundBase> GravelSound;
    UPROPERTY(Transient) TObjectPtr<USoundBase> StaffSound;
    UPROPERTY(Transient) TObjectPtr<UObject> Glyph;
    UPROPERTY(Transient) TObjectPtr<UObject> CaptionFont;
    UPROPERTY(Transient) TObjectPtr<UAudioComponent> CueAudio;
    UPROPERTY(Transient) TObjectPtr<UStaticMesh> StaffMesh;
    UPROPERTY(Transient) TObjectPtr<USaskartaElderWalkHint> Hint;
    UPROPERTY(Transient) TObjectPtr<UAnimationAsset> PreviousAnimation;
    UPROPERTY(Transient) TObjectPtr<class UMaterialInstanceDynamic> FatigueMID;
    TSharedPtr<FStreamableHandle> AssetsLoad;
    TSharedPtr<FStreamableHandle> StaffVisualLoad;
    TSharedPtr<FStreamableHandle> ContactLoad;
    TMap<TWeakObjectPtr<ACharacter>, TWeakObjectPtr<UStaticMeshComponent>> StaffVisuals;
    float StaffVisualPoll = 0.f;
    TWeakObjectPtr<ACharacter> ActiveHuman;
    TWeakObjectPtr<APlayerController> ActiveController;
    TWeakObjectPtr<UAnimationAsset> OwnedAnimation;
    FName PreviousAnimMode;
    FName OwnedAnimMode;
    ESaskartaElderFooting Footing = ESaskartaElderFooting::Walking;
    float SupportPoll = 0.f;
    float StateSeconds = 0.f;
    float GustCountdown = 16.f;
    float WarningSeconds = 0.f;
    float RecoveryImmunity = 0.f;
    float HintVisibleSeconds = 0.f;
    float WeightShift = 0.f;
    float SavedSpeed = 0.f;
    float WrittenSpeed = 0.f;
    float RoadM = 0.f;
    float ContactSlope = 90.f;
    float ContactError = BIG_NUMBER;
    FVector GroundNormal = FVector::UpVector;
    int32 GustNumber = 0;
    bool bActive = false;
    bool bSupportValid = false;
    bool bStaffReachable = false;
    bool bStaffSupportValid = false;
    bool bLoose = false;
    bool bSheltered = false;
    bool bHasSpeedLease = false;
    bool bHasAnimationLease = false;
    bool bHasFacingLease = false;
    bool bSavedOrientToMovement = false;
    bool bSavedControllerDesiredRotation = false;
    bool bSavedControllerYaw = false;
    bool bMovementContested = false;
    bool bPreviousLoose = false;
    bool bReleaseToRearm = true;
    bool bPreviousStaffDown = false;
    bool bStaffLatched = false;
    bool bReducedGusts = false;
    bool bToggleStaff = false;
    bool bHintTaught = false;
    bool bLoggedMissingContacts = false;
    float SlipCountdown = 10.f;
    float SlipTime = -1.f;
    float StumbleSeconds = 0.f;
    int32 SlipPresses = 0;
    int32 SlipNeeded = 6;
    int32 Health = 3;
    bool bPrevMashDown = false;
    int32 SlipMode = 0;            // 0 grip (mash), 1 balance (A/D against the sway)
    int32 SlipCount = 0;
    int32 SlipStreak = 0;
    float Sway = 0.f;
    float SwayPush = 0.f;
    float BalancedSeconds = 0.f;
    float StillSeconds = 0.f;
    float BreathCooldown = 0.f;
    float FlashSeconds = 0.f;
    FString FlashText;
    float AppliedRoll = 0.f;
    ESaskartaElderFooting PrevFootingForSlip = ESaskartaElderFooting::Walking;
    TSharedPtr<class SWidget> SlipOverlay;
    TWeakObjectPtr<class UGameViewportClient> SlipViewport;
    TSharedPtr<struct FSlateBrush> FatigueBrush;
    float FatigueLevel = 0.f;
};
