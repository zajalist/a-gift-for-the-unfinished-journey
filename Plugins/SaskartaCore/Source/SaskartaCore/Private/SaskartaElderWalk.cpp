#include "SaskartaElderWalk.h"

#include "SaskartaEventRunner.h"
#include "SaskartaOnboarding.h"
#include "SaskartaTetherSubsystem.h"
#include "Animation/AnimSingleNodeInstance.h"
#include "Animation/AnimSequence.h"
#include "Animation/AnimationAsset.h"
#include "Animation/BlendSpace.h"
#include "Animation/Skeleton.h"
#include "Blueprint/WidgetTree.h"
#include "Components/AudioComponent.h"
#include "Components/CanvasPanel.h"
#include "Components/CanvasPanelSlot.h"
#include "Components/CapsuleComponent.h"
#include "Components/HorizontalBox.h"
#include "Components/HorizontalBoxSlot.h"
#include "Components/Image.h"
#include "Components/SkeletalMeshComponent.h"
#include "Components/SplineComponent.h"
#include "Components/StaticMeshComponent.h"
#include "Components/TextBlock.h"
#include "Engine/AssetManager.h"
#include "Engine/Font.h"
#include "Engine/SkeletalMesh.h"
#include "Engine/StaticMesh.h"
#include "Engine/StreamableManager.h"
#include "Engine/Texture2D.h"
#include "Engine/World.h"
#include "GameFramework/Character.h"
#include "GameFramework/CharacterMovementComponent.h"
#include "GameFramework/PlayerController.h"
#include "InputCoreTypes.h"
#include "Kismet/GameplayStatics.h"
#include "EngineUtils.h"
#include "Sound/SoundBase.h"
#include "Styling/CoreStyle.h"
#include "UObject/UnrealType.h"
#include "Engine/GameViewportClient.h"
#include "Widgets/SBoxPanel.h"
#include "Widgets/SOverlay.h"
#include "Widgets/Layout/SBox.h"
#include "Widgets/Layout/SBorder.h"
#include "Widgets/Text/STextBlock.h"
#include "Widgets/Notifications/SProgressBar.h"
#include "HAL/PlatformTime.h"
#include "Widgets/Images/SImage.h"
#include "Materials/MaterialInstanceDynamic.h"
#include "Materials/MaterialInterface.h"
#include "Styling/SlateBrush.h"
#include "Brushes/SlateRoundedBoxBrush.h"
#include "Engine/Texture2D.h"

DEFINE_LOG_CATEGORY_STATIC(LogSaskartaElderWalk, Log, All);

namespace ElderWalk
{
    const FSoftObjectPath ProfilePath(TEXT("/Game/SaskartaGaea/Characters/Traveller/DA_Traveller_StaffContacts.DA_Traveller_StaffContacts"));
    const FSoftObjectPath GustPath(TEXT("/Game/SaskartaGaea/Audio/Ambience/SFX_Wind_Gust_Heavy.SFX_Wind_Gust_Heavy"));
    const FSoftObjectPath GravelPath(TEXT("/Game/SaskartaGaea/Audio/Environment/SFX_Gravel_Trickle_01.SFX_Gravel_Trickle_01"));
    const FSoftObjectPath StaffPath(TEXT("/Game/SaskartaGaea/Audio/Foley/SFX_WalkingAid_Tap_Gravel_01.SFX_WalkingAid_Tap_Gravel_01"));
    const FSoftObjectPath StaffMeshPath(TEXT("/Game/SaskartaGaea/Characters/Traveller/SM_Traveller_Staff.SM_Traveller_Staff"));
    const FSoftObjectPath GlyphPath(TEXT("/Game/SaskartaGaea/UI/Prompts/Light/T_Prompt_Key_E.T_Prompt_Key_E"));
    const FSoftObjectPath FontPath(TEXT("/Game/SaskartaGaea/GameFlow/UI/Fonts/F_ArefRuqaa_Caption.F_ArefRuqaa_Caption"));

    FName AnimMode(const ACharacter* Human)
    {
        const FNameProperty* Property = Human ? FindFProperty<FNameProperty>(Human->GetClass(), TEXT("AnimMode")) : nullptr;
        return Property ? Property->GetPropertyValue_InContainer(Human) : NAME_None;
    }

    void SetAnimMode(ACharacter* Human, FName Value)
    {
        if (FNameProperty* Property = Human ? FindFProperty<FNameProperty>(Human->GetClass(), TEXT("AnimMode")) : nullptr)
            Property->SetPropertyValue_InContainer(Human, Value);
    }

    bool WalkingEnabled(const ACharacter* Human)
    {
        const FBoolProperty* Property = Human ? FindFProperty<FBoolProperty>(Human->GetClass(), TEXT("bWalking")) : nullptr;
        return Property && Property->GetPropertyValue_InContainer(Human);
    }
}

void USaskartaElderWalkHint::NativeOnInitialized()
{
    Super::NativeOnInitialized();
    SetIsFocusable(false);
    if (!WidgetTree) return;
    Row = Cast<UHorizontalBox>(GetWidgetFromName(TEXT("ElderHintRow")));
    bAuthoredLayout = WidgetTree->RootWidget != nullptr;
    if (bAuthoredLayout)
    {
        AuthoredGlyph = Cast<UImage>(GetWidgetFromName(TEXT("ElderStaffGlyph")));
        AuthoredCaption = Cast<UTextBlock>(GetWidgetFromName(TEXT("ElderStaffCaption")));
    }
    if (!Row && !WidgetTree->RootWidget)
    {
        UCanvasPanel* Root = WidgetTree->ConstructWidget<UCanvasPanel>();
        WidgetTree->RootWidget = Root;
        Row = WidgetTree->ConstructWidget<UHorizontalBox>(UHorizontalBox::StaticClass(), TEXT("ElderHintRow"));
        UCanvasPanelSlot* HintCanvasSlot = Root->AddChildToCanvas(Row);
        HintCanvasSlot->SetAnchors(FAnchors(0.f, 1.f));
        HintCanvasSlot->SetPosition(FVector2D(32.f, -178.f));
        HintCanvasSlot->SetAutoSize(true);
    }
    Hide();
}

void USaskartaElderWalkHint::Show(const FString& Caption, UObject* KeyTexture, UObject* FontObject)
{
    if (!Row) return;
    if (bAuthoredLayout)
    {
        if (!AuthoredGlyph || !AuthoredCaption) return;
        if (UTexture2D* Texture = Cast<UTexture2D>(KeyTexture))
        {
            AuthoredGlyph->SetBrushFromTexture(Texture, false);
            AuthoredGlyph->SetVisibility(ESlateVisibility::HitTestInvisible);
        }
        else AuthoredGlyph->SetVisibility(ESlateVisibility::Collapsed);
        AuthoredCaption->SetText(FText::FromString(Caption));
        SetVisibility(ESlateVisibility::HitTestInvisible);
        return;
    }
    if (LastCaption != Caption || GetVisibility() == ESlateVisibility::Collapsed)
    {
        LastCaption = Caption;
        Row->ClearChildren();
        if (UTexture2D* Texture = Cast<UTexture2D>(KeyTexture))
        {
            UImage* Image = WidgetTree->ConstructWidget<UImage>();
            Image->SetBrushFromTexture(Texture);
            Image->SetDesiredSizeOverride(FVector2D(32.f, 32.f));
            Row->AddChildToHorizontalBox(Image)->SetVerticalAlignment(VAlign_Center);
        }
        UTextBlock* Text = WidgetTree->ConstructWidget<UTextBlock>();
        Text->SetText(FText::FromString(Cast<UTexture2D>(KeyTexture) ? Caption : TEXT("E  ") + Caption));
        FSlateFontInfo Font = FCoreStyle::GetDefaultFontStyle(TEXT("Regular"), 23);
        if (UFont* LoadedFont = Cast<UFont>(FontObject)) Font = FSlateFontInfo(LoadedFont, 23);
        Text->SetFont(Font);
        Text->SetColorAndOpacity(FSlateColor(FLinearColor(.94f,.91f,.81f,1.f)));
        Text->SetShadowOffset(FVector2D(1.f, 2.f));
        Text->SetShadowColorAndOpacity(FLinearColor(0.f,0.f,0.f,.8f));
        Text->SetWrapTextAt(610.f);
        UHorizontalBoxSlot* CaptionSlot = Row->AddChildToHorizontalBox(Text);
        CaptionSlot->SetPadding(FMargin(9.f,0.f,0.f,0.f));
        CaptionSlot->SetVerticalAlignment(VAlign_Center);
    }
    SetVisibility(ESlateVisibility::HitTestInvisible);
}

void USaskartaElderWalkHint::Hide() { SetVisibility(ESlateVisibility::Collapsed); }

bool USaskartaElderWalk::ShouldCreateSubsystem(UObject* Outer) const
{
    const UWorld* World = Cast<UWorld>(Outer);
    return World && World->IsGameWorld();
}

TStatId USaskartaElderWalk::GetStatId() const
{
    RETURN_QUICK_DECLARE_CYCLE_STAT(USaskartaElderWalk, STATGROUP_Tickables);
}

void USaskartaElderWalk::OnWorldBeginPlay(UWorld& InWorld)
{
    Super::OnWorldBeginPlay(InWorld);
    // The prop must follow the Traveller during the cinematic handoff as well as the playable walk.
    // Contact animation and challenge assets still load only when the human handoff occurs.
    StaffVisualLoad = UAssetManager::GetStreamableManager().RequestAsyncLoad(
        ElderWalk::StaffMeshPath, FStreamableDelegate::CreateWeakLambda(this, [this]()
        {
            StaffMesh = Cast<UStaticMesh>(ElderWalk::StaffMeshPath.ResolveObject());
            if (StaffMesh) AttachStaffVisuals(1.f);
            else UE_LOG(LogSaskartaElderWalk, Error, TEXT("Traveller staff mesh is missing; ending prop cannot render."));
        }));
}

void USaskartaElderWalk::AttachStaffVisuals(float DeltaTime)
{
    UWorld* World = GetWorld();
    if (!World || !StaffMesh) return;
    StaffVisualPoll += FMath::Max(0.f, DeltaTime);
    if (StaffVisualPoll < .5f) return;
    StaffVisualPoll = 0.f;

    for (auto It = StaffVisuals.CreateIterator(); It; ++It)
        if (!It.Key().IsValid() || !It.Value().IsValid()) It.RemoveCurrent();

    for (TActorIterator<ACharacter> It(World); It; ++It)
    {
        ACharacter* Traveller = *It;
        if (!Traveller || Traveller->GetClass()->GetName() != TEXT("BP_Saskarta_Traveller_C") ||
            StaffVisuals.Contains(TWeakObjectPtr<ACharacter>(Traveller))) continue;
        USkeletalMeshComponent* Body = Traveller->GetMesh();
        if (!Body || Body->GetBoneIndex(TEXT("staff011")) == INDEX_NONE) continue;

        // A later authored Blueprint prop takes priority; never create a second staff.
        bool bAlreadyAttached = false;
        TArray<UStaticMeshComponent*> ExistingVisuals;
        Traveller->GetComponents(ExistingVisuals);
        for (UStaticMeshComponent* Existing : ExistingVisuals)
            if (Existing && Existing->GetStaticMesh() == StaffMesh && Existing->GetAttachParent() == Body &&
                Existing->GetAttachSocketName() == TEXT("staff011")) { bAlreadyAttached = true; break; }
        if (bAlreadyAttached) continue;

        // The source staff OBJ was exported in staff011 local coordinates. The imported bone
        // carries the original 100x scale, so an identity relative transform yields 145 cm.
        UStaticMeshComponent* Visual = NewObject<UStaticMeshComponent>(Traveller, NAME_None, RF_Transient);
        Visual->SetMobility(EComponentMobility::Movable);
        Visual->SetStaticMesh(StaffMesh);
        Visual->SetCollisionEnabled(ECollisionEnabled::NoCollision);
        Visual->SetGenerateOverlapEvents(false);
        Visual->SetupAttachment(Body, TEXT("staff011"));
        Visual->SetRelativeTransform(FTransform::Identity);
        Traveller->AddInstanceComponent(Visual);
        Visual->RegisterComponent();
        StaffVisuals.Add(Traveller, Visual);
        UE_LOG(LogSaskartaElderWalk, Log, TEXT("Attached visible staff to Traveller %s at staff011."), *Traveller->GetName());
    }
}

void USaskartaElderWalk::LoadAssets()
{
    if (AssetsLoad.IsValid()) return;
    AssetsLoad = UAssetManager::GetStreamableManager().RequestAsyncLoad(
        TArray<FSoftObjectPath>{ElderWalk::ProfilePath, ElderWalk::GustPath, ElderWalk::GravelPath,
            ElderWalk::StaffPath, ElderWalk::GlyphPath, ElderWalk::FontPath},
        FStreamableDelegate::CreateWeakLambda(this, [this]() { ResolveAssets(); }));
}

void USaskartaElderWalk::ResolveAssets()
{
    GustSound = Cast<USoundBase>(ElderWalk::GustPath.ResolveObject());
    GravelSound = Cast<USoundBase>(ElderWalk::GravelPath.ResolveObject());
    StaffSound = Cast<USoundBase>(ElderWalk::StaffPath.ResolveObject());
    Glyph = ElderWalk::GlyphPath.ResolveObject();
    CaptionFont = ElderWalk::FontPath.ResolveObject();
    if (USaskartaElderWalkProfile* Loaded = Cast<USaskartaElderWalkProfile>(ElderWalk::ProfilePath.ResolveObject()))
        ConfigureContacts(Loaded);
}

void USaskartaElderWalk::ConfigureContacts(USaskartaElderWalkProfile* ReviewedProfile)
{
    Suspend(true);
    if (Hint) { Hint->RemoveFromParent(); Hint = nullptr; }
    if (ContactLoad.IsValid()) ContactLoad->CancelHandle();
    ContactLoad.Reset();
    Profile = ReviewedProfile;
    EnterClip = HoldClip = RecoverClip = nullptr;
    if (!Profile || !Profile->bContactsReviewed) return;
    TArray<FSoftObjectPath> Paths{Profile->StaffEnter.ToSoftObjectPath(), Profile->StaffHold.ToSoftObjectPath(), Profile->StaffRecover.ToSoftObjectPath()};
    if (!Profile->HintWidgetClass.IsNull()) Paths.Add(Profile->HintWidgetClass.ToSoftObjectPath());
    Paths.RemoveAll([](const FSoftObjectPath& Path) { return Path.IsNull(); });
    ContactLoad = UAssetManager::GetStreamableManager().RequestAsyncLoad(Paths,
        FStreamableDelegate::CreateWeakLambda(this, [this]()
        {
            if (!Profile) return;
            EnterClip = Profile->StaffEnter.Get();
            HoldClip = Profile->StaffHold.Get();
            RecoverClip = Profile->StaffRecover.Get();
        }));
}

bool USaskartaElderWalk::HasReviewedContacts() const
{
    const ACharacter* Human = ActiveHuman.Get();
    const USkeletalMeshComponent* Mesh = Human ? Human->GetMesh() : nullptr;
    const USkeleton* Skeleton = Mesh && Mesh->GetSkeletalMeshAsset() ? Mesh->GetSkeletalMeshAsset()->GetSkeleton() : nullptr;
    const UAnimSequence* Enter = Cast<UAnimSequence>(EnterClip.Get());
    const UAnimSequence* Recover = Cast<UAnimSequence>(RecoverClip.Get());
    const UBlendSpace* Hold = Cast<UBlendSpace>(HoldClip.Get());
    if (!Profile || !Profile->bContactsReviewed || !Skeleton || !Enter || !Recover || !Hold ||
        Enter->GetSkeleton() != Skeleton || Recover->GetSkeleton() != Skeleton || Hold->GetSkeleton() != Skeleton ||
        Enter->HasRootMotion() || Recover->HasRootMotion() || Hold->GetBlendSamples().Num() != 3) return false;
    for (const FBlendSample& Sample : Hold->GetBlendSamples())
        if (!Sample.Animation || Sample.Animation->GetSkeleton() != Skeleton || Sample.Animation->HasRootMotion()) return false;
    return true;
}

float USaskartaElderWalk::GetWindWarning() const { return FMath::Clamp(1.f - GustCountdown / 2.4f, 0.f, 1.f); }

void USaskartaElderWalk::SetSpeedLimit(float Limit)
{
    ACharacter* Human = ActiveHuman.Get();
    UCharacterMovementComponent* Move = Human ? Human->GetCharacterMovement() : nullptr;
    if (!Move) return;
    if (bMovementContested) return;
    // A changed speed is another owner's write: surrender this lease rather than overwriting it.
    if (bHasSpeedLease && !FMath::IsNearlyEqual(Move->MaxWalkSpeed, WrittenSpeed, .01f))
    {
        bHasSpeedLease = false;
        bMovementContested = true;
        return;
    }
    if (!bHasSpeedLease) SavedSpeed = Move->MaxWalkSpeed;
    WrittenSpeed = FMath::Min(SavedSpeed, FMath::Max(0.f, Limit));
    Move->MaxWalkSpeed = WrittenSpeed;
    bHasSpeedLease = true;
}

void USaskartaElderWalk::ReleaseSpeedLimit()
{
    if (ACharacter* Human = ActiveHuman.Get())
        if (UCharacterMovementComponent* Move = Human->GetCharacterMovement(); bHasSpeedLease && Move && FMath::IsNearlyEqual(Move->MaxWalkSpeed, WrittenSpeed, .01f))
            Move->MaxWalkSpeed = SavedSpeed;
    bHasSpeedLease = false;
}

void USaskartaElderWalk::AcquireFacing()
{
    ACharacter* Human = ActiveHuman.Get();
    UCharacterMovementComponent* Move = Human ? Human->GetCharacterMovement() : nullptr;
    if (!Move || bHasFacingLease) return;
    bSavedOrientToMovement = Move->bOrientRotationToMovement;
    bSavedControllerDesiredRotation = Move->bUseControllerDesiredRotation;
    bSavedControllerYaw = Human->bUseControllerRotationYaw;
    Move->bOrientRotationToMovement = false;
    Move->bUseControllerDesiredRotation = false;
    Human->bUseControllerRotationYaw = false;
    bHasFacingLease = true;
}

void USaskartaElderWalk::ReleaseFacing()
{
    ACharacter* Human = ActiveHuman.Get();
    UCharacterMovementComponent* Move = Human ? Human->GetCharacterMovement() : nullptr;
    if (bHasFacingLease && Move)
    {
        if (!Move->bOrientRotationToMovement) Move->bOrientRotationToMovement = bSavedOrientToMovement;
        if (!Move->bUseControllerDesiredRotation) Move->bUseControllerDesiredRotation = bSavedControllerDesiredRotation;
        if (!Human->bUseControllerRotationYaw) Human->bUseControllerRotationYaw = bSavedControllerYaw;
    }
    bHasFacingLease = false;
}

bool USaskartaElderWalk::PlayOwnedAnimation(UAnimationAsset* Animation, FName Mode, bool bLoop)
{
    ACharacter* Human = ActiveHuman.Get();
    USkeletalMeshComponent* Mesh = Human ? Human->GetMesh() : nullptr;
    if (!HasReviewedContacts() || !Mesh || !Animation || !Mesh->GetSkeletalMeshAsset() ||
        Animation->GetSkeleton() != Mesh->GetSkeletalMeshAsset()->GetSkeleton() || !Mesh->GetSingleNodeInstance()) return false;
    if (!bHasAnimationLease)
    {
        PreviousAnimation = Mesh->GetSingleNodeInstance()->GetCurrentAsset();
        PreviousAnimMode = ElderWalk::AnimMode(Human);
    }
    Mesh->PlayAnimation(Animation, bLoop);
    ElderWalk::SetAnimMode(Human, Mode);
    OwnedAnimation = Animation;
    OwnedAnimMode = Mode;
    bHasAnimationLease = true;
    return true;
}

void USaskartaElderWalk::ReleaseAnimation(bool bCanRestore)
{
    ACharacter* Human = ActiveHuman.Get();
    USkeletalMeshComponent* Mesh = Human ? Human->GetMesh() : nullptr;
    UAnimSingleNodeInstance* Instance = Mesh ? Mesh->GetSingleNodeInstance() : nullptr;
    if (bHasAnimationLease && bCanRestore && Instance && Instance->GetCurrentAsset() == OwnedAnimation.Get() &&
        ElderWalk::AnimMode(Human) == OwnedAnimMode)
    {
        // Use the pawn's established locomotion handoff, not a guessed posture or bone scale.
        if (UFunction* Function = Human->FindFunction(TEXT("EnterLoco"))) Human->ProcessEvent(Function, nullptr);
        else if (PreviousAnimation)
        {
            Mesh->PlayAnimation(PreviousAnimation, true);
            ElderWalk::SetAnimMode(Human, PreviousAnimMode);
        }
    }
    bHasAnimationLease = false;
    OwnedAnimation.Reset();
    PreviousAnimation = nullptr;
}

void USaskartaElderWalk::Suspend(bool bCanRestoreAnimation)
{
    HideSlipOverlay();
    SlipTime = -1.f;
    StumbleSeconds = 0.f;
    if (APlayerController* RollPC = ActiveController.Get())
    {
        FRotator R = RollPC->GetControlRotation(); R.Roll = 0.f; RollPC->SetControlRotation(R);
    }
    AppliedRoll = 0.f;
    ReleaseSpeedLimit();
    ReleaseFacing();
    ReleaseAnimation(bCanRestoreAnimation);
    if (Hint) Hint->Hide();
    if (CueAudio) CueAudio->Stop();
    bActive = false;
    bReleaseToRearm = true;
    bStaffLatched = false;
    bMovementContested = false;
    bPreviousLoose = false;
    Footing = ESaskartaElderFooting::Walking;
    StateSeconds = WeightShift = WarningSeconds = 0.f;
    RecoveryImmunity = 1.5f;
    GustCountdown = FMath::Max(GustCountdown, 4.f);
    ActiveHuman.Reset();
    ActiveController.Reset();
}

void USaskartaElderWalk::PollSupport(ACharacter* Human)
{
    UWorld* World = GetWorld();
    bSupportValid = bStaffReachable = bStaffSupportValid = bLoose = bSheltered = false;
    ContactSlope = 90.f;
    ContactError = BIG_NUMBER;
    if (!World || !Human) return;
    FCollisionQueryParams Params(SCENE_QUERY_STAT(ElderFooting), false, Human);
    Params.bReturnPhysicalMaterial = false;
    const FVector Origin = Human->GetActorLocation();
    const float HalfHeight = Human->GetCapsuleComponent()->GetScaledCapsuleHalfHeight();
    FHitResult Ground;
    bSupportValid = World->LineTraceSingleByChannel(Ground, Origin, Origin-FVector(0,0,HalfHeight+38.f), ECC_WorldStatic, Params)
        && Ground.bBlockingHit && Ground.ImpactNormal.Z > .55f;
    if (!bSupportValid) return; // A streaming miss never becomes a gust/loose-ground penalty.
    GroundNormal = Ground.ImpactNormal;
    const AActor* GroundActor = Ground.GetActor();
    bLoose = (GroundActor && GroundActor->ActorHasTag(TEXT("Saskarta.Elder.Loose"))) ||
        (Ground.GetComponent() && Ground.GetComponent()->ComponentHasTag(TEXT("Saskarta.Elder.Loose")));
    if (Profile && Human->GetMesh() && Human->GetMesh()->GetBoneIndex(TEXT("staff011")) != INDEX_NONE)
    {
        // The source tip is attached to staff011. Following that bone keeps the
        // contact query aligned with the visible staff during weight shifts.
        const FVector Tip = Human->GetMesh()->GetSocketTransform(TEXT("staff011"), RTS_World)
            .TransformPosition(Profile->StaffTipBoneLocal);
        FHitResult Contact;
        if (World->LineTraceSingleByChannel(Contact, Tip+FVector(0,0,25), Tip-FVector(0,0,35), ECC_WorldStatic, Params))
        {
            const float TipHeight = Tip.Z - Contact.ImpactPoint.Z;
            ContactError = FMath::Abs(TipHeight);
            ContactSlope = FMath::RadiansToDegrees(FMath::Acos(FMath::Clamp(Contact.ImpactNormal.Z, 0.f, 1.f)));
            bStaffReachable = Contact.bBlockingHit && TipHeight >= -Profile->MaxContactErrorCm && TipHeight <= 30.f &&
                ContactSlope <= Profile->MaxContactSlopeDegrees;
            bStaffSupportValid = bStaffReachable && ContactError <= Profile->MaxContactErrorCm;
        }
    }
    // A nearby physical wall actually shelters him; no invisible shelter volume or guessed cliff normal.
    FHitResult Shelter;
    bSheltered = World->LineTraceSingleByChannel(Shelter, Origin, Origin+FVector(-.65f,.76f,0.f)*350.f, ECC_WorldStatic, Params);
}

void USaskartaElderWalk::Cue(USoundBase* Sound, float Volume)
{
    if (!Sound || !GetWorld()) return;
    if (!CueAudio)
    {
        CueAudio = NewObject<UAudioComponent>(this);
        CueAudio->bAutoActivate = false;
        CueAudio->bAutoDestroy = false;
        CueAudio->bAllowSpatialization = false;
        CueAudio->RegisterComponentWithWorld(GetWorld());
    }
    // No radio/music stop, duck, new looping voice, or accumulated one-shot components.
    if (CueAudio->IsPlaying()) return;
    CueAudio->SetSound(Sound);
    CueAudio->SetVolumeMultiplier(Volume);
    CueAudio->Play();
}

void USaskartaElderWalk::BeginPlant()
{
    ACharacter* Human = ActiveHuman.Get();
    if (!Human || !bStaffReachable || !PlayOwnedAnimation(EnterClip, TEXT("StaffEnter"), false)) return;
    SetSpeedLimit(0.f);
    AcquireFacing();
    Human->GetCharacterMovement()->StopMovementImmediately();
    Footing = ESaskartaElderFooting::StaffEnter;
    StateSeconds = WeightShift = 0.f;
    Cue(StaffSound, .32f);
}

void USaskartaElderWalk::BeginRecovery()
{
    if (!PlayOwnedAnimation(RecoverClip, TEXT("StaffRecover"), false))
    {
        ReleaseAnimation(true);
        ReleaseSpeedLimit();
        ReleaseFacing();
        Footing = ESaskartaElderFooting::Walking;
        RecoveryImmunity = 1.5f;
        return;
    }
    SetSpeedLimit(0.f);
    Footing = ESaskartaElderFooting::Recovering;
    StateSeconds = 0.f;
}

void USaskartaElderWalk::UpdateHint(APlayerController* PC, const USaskartaEventRunner* Runner, float DeltaTime)
{
    const USaskartaOnboarding* Onboarding = GetWorld()->GetSubsystem<USaskartaOnboarding>();
    const bool bContactsReady = HasReviewedContacts();
    const bool bGustWarning = WarningSeconds > 0.f && GustCountdown <= 2.4f;
    const bool bHazard = bGustWarning || Footing == ESaskartaElderFooting::Unsteady;
    const bool bWant = bHazard || (bContactsReady && (!bHintTaught || Footing != ESaskartaElderFooting::Walking));
    if (!bWant || Runner->IsStorySubtitleActive() || (Onboarding && Onboarding->IsHintVisible()))
    {
        if (Hint) Hint->Hide();
        return;
    }
    if (!Hint)
    {
        UClass* HintClass = Profile && Profile->HintWidgetClass.Get() ? Profile->HintWidgetClass.Get() : USaskartaElderWalkHint::StaticClass();
        Hint = CreateWidget<USaskartaElderWalkHint>(PC, HintClass);
        if (Hint) Hint->AddToViewport(16);
    }
    if (!Hint) return;
    if (Footing == ESaskartaElderFooting::Unsteady)
        Hint->Show(TEXT("LOOSE FOOTING · KEEP TO FIRM GROUND"), nullptr, CaptionFont);
    else if (bGustWarning)
        Hint->Show(bSheltered ? TEXT("WALL SHELTER · GUST PASSING") : TEXT("WIND RISING · SEEK WALL SHELTER"), nullptr, CaptionFont);
    else
    {
        Hint->Show(Footing == ESaskartaElderFooting::StaffHold ? TEXT("STAFF PLANTED   A / D · SHIFT WEIGHT   RELEASE · WALK") :
            bToggleStaff ? TEXT("PLANT / RELEASE STAFF · PRESS   FIND FIRM FOOTING") : TEXT("HOLD · PLANT STAFF   RELEASE · WALK   FIND FIRM FOOTING"), Glyph, CaptionFont);
        HintVisibleSeconds += DeltaTime;
        if (HintVisibleSeconds >= 5.f) bHintTaught = true;
    }
}

void USaskartaElderWalk::Tick(float DeltaTime)
{
    UWorld* World = GetWorld();
    AttachStaffVisuals(DeltaTime);
    USaskartaEventRunner* Runner = World ? World->GetSubsystem<USaskartaEventRunner>() : nullptr;
    APlayerController* PC = World ? World->GetFirstPlayerController() : nullptr;
    ACharacter* Human = PC ? Cast<ACharacter>(PC->GetPawn()) : nullptr;
    const bool bHuman = Runner && Runner->GetFlowState() == FName(TEXT("Human")) && Human && ElderWalk::WalkingEnabled(Human);
    const bool bCinematicOwns = Runner && Runner->IsCinematicActive();
    if (bHuman) LoadAssets();
    const bool bBlocked = !bHuman || !World || World->IsPaused() || bCinematicOwns || Runner->IsHoldingInput() ||
        Runner->IsPromptActive() || !PC || PC->IsMoveInputIgnored() || PC->IsLookInputIgnored() ||
        (Human && World->GetSubsystem<USaskartaTetherSubsystem>() && World->GetSubsystem<USaskartaTetherSubsystem>()->IsDetour(Human->GetActorLocation()));
    if (bBlocked)
    {
        const bool bSamePawn = Human && Human == ActiveHuman.Get() && PC == ActiveController.Get();
        if (bActive || bHasSpeedLease || bHasAnimationLease) Suspend(bSamePawn && !bCinematicOwns);
        if (Hint) Hint->Hide();
        return;
    }
    if (ActiveHuman.Get() != Human || ActiveController.Get() != PC)
    {
        Suspend(false);
        ActiveHuman = Human;
        ActiveController = PC;
        bReleaseToRearm = true;
        SupportPoll = .1f;
    }
    bActive = true;
    // A hitch buys a reprieve: no missed brace, accumulated hazard, time jump or displacement.
    if (DeltaTime <= 0.f || DeltaTime > .25f)
    {
        ReleaseSpeedLimit(); ReleaseFacing(); ReleaseAnimation(true);
        Footing = ESaskartaElderFooting::Walking;
        bReleaseToRearm = true;
        bStaffLatched = false;
        if (Hint) Hint->Hide();
        GustCountdown = FMath::Max(GustCountdown, 3.f);
        RecoveryImmunity = 1.5f;
        return;
    }
    RoadM = Runner->GetRoadM();
    // Submission 2026-10-05: road leash. The elder stays within 2 m (horizontal) of the road spline; beyond that he is
    // put back 1 m off the centre line at the closest point. Skipped in the last 25 m so the summit console stays reachable.
    {
        static TWeakObjectPtr<USplineComponent> LeashSpline;
        if (LeashSpline.IsValid() && LeashSpline->GetWorld() != World) LeashSpline.Reset();
        if (!LeashSpline.IsValid())
        {
            for (TActorIterator<AActor> It(World); It; ++It)
            {
                TArray<USplineComponent*> Splines;
                It->GetComponents(Splines);
                for (USplineComponent* S : Splines)
                {
                    if (S && S->GetName() == TEXT("RoadSpline")) { LeashSpline = S; break; }
                }
                if (LeashSpline.IsValid()) break;
            }
        }
        if (USplineComponent* Road = LeashSpline.Get())
        {
            const FVector P = Human->GetActorLocation();
            const float Key = Road->FindInputKeyClosestToWorldLocation(P);
            const float AlongCm = Road->GetDistanceAlongSplineAtSplineInputKey(Key);
            const FVector C = Road->GetLocationAtSplineInputKey(Key, ESplineCoordinateSpace::World);
            const FVector Side = FVector(P.X - C.X, P.Y - C.Y, 0.f);
            if (AlongCm > 2500.f && Side.Size() > 200.f)
            {
                const float Half = Human->GetCapsuleComponent() ? Human->GetCapsuleComponent()->GetScaledCapsuleHalfHeight() : 90.f;
                FVector Dest = C + Side.GetSafeNormal() * 100.f;
                Dest.Z = FMath::Max(P.Z, C.Z + Half) + 30.f;
                if (UCharacterMovementComponent* Move = Human->GetCharacterMovement()) Move->StopMovementImmediately();
                Human->SetActorLocation(Dest, false, nullptr, ETeleportType::TeleportPhysics);
                UE_LOG(LogSaskartaElderWalk, Log, TEXT("Road leash: elder %.0f cm off the road at %.0f m; returned to the road."), Side.Size(), AlongCm / 100.f);
            }
        }
    }
    StateSeconds += DeltaTime;
    RecoveryImmunity = FMath::Max(0.f, RecoveryImmunity-DeltaTime);
    WarningSeconds = FMath::Max(0.f, WarningSeconds-DeltaTime);
    SupportPoll += DeltaTime;
    if (SupportPoll >= .1f) { SupportPoll = 0.f; PollSupport(Human); }
    const bool bDown = PC->IsInputKeyDown(EKeys::E);
    const bool bPressed = bDown && !bPreviousStaffDown;
    bPreviousStaffDown = bDown;
    if (!bDown) bReleaseToRearm = false;
    if (bToggleStaff && bPressed && !bReleaseToRearm) bStaffLatched = !bStaffLatched;
    const bool bWantsStaff = !bReleaseToRearm && (bToggleStaff ? bStaffLatched : bDown);
    const bool bContactsReady = HasReviewedContacts();
    if (!bContactsReady)
    {
        // Visual certification gates staff poses only. Wind and loose ground remain
        // playable with their speed, warning, and recovery behavior below.
        if (Footing == ESaskartaElderFooting::StaffEnter ||
            Footing == ESaskartaElderFooting::StaffHold ||
            Footing == ESaskartaElderFooting::Recovering || bHasAnimationLease || bHasFacingLease)
        {
            ReleaseSpeedLimit(); ReleaseFacing(); ReleaseAnimation(true);
            Footing = ESaskartaElderFooting::Walking;
        }
        if (Hint) Hint->Hide();
        if (!bLoggedMissingContacts)
        {
            UE_LOG(LogSaskartaElderWalk, Warning, TEXT("Human walk: staff poses guarded until DA_Traveller_StaffContacts has reviewed real boot/staff clips. Wind and loose footing remain active."));
            bLoggedMissingContacts = true;
        }
    }
    UCharacterMovementComponent* Move = Human->GetCharacterMovement();
    if (!Move || !Move->IsMovingOnGround() || !bSupportValid)
    {
        ReleaseSpeedLimit();
        ReleaseFacing();
        ReleaseAnimation(true);
        Footing = ESaskartaElderFooting::Walking;
        RecoveryImmunity = 1.5f;
        return;
    }
    if (bMovementContested) { Suspend(true); return; }
    if (bHasAnimationLease)
    {
        UAnimSingleNodeInstance* Instance = Human->GetMesh()->GetSingleNodeInstance();
        if (!Instance || Instance->GetCurrentAsset() != OwnedAnimation.Get() || ElderWalk::AnimMode(Human) != OwnedAnimMode)
        {
            Suspend(false); // A rest/story/animation driver has taken the body; surrender only our leases.
            return;
        }
    }
    const bool bPlanting = Footing == ESaskartaElderFooting::StaffEnter || Footing == ESaskartaElderFooting::StaffHold;
    if (bContactsReady && bPlanting)
    {
        if (!bWantsStaff || !bStaffReachable ||
            (Footing == ESaskartaElderFooting::StaffHold && !bStaffSupportValid)) BeginRecovery();
        else if (Footing == ESaskartaElderFooting::StaffEnter && StateSeconds >= .35f)
        {
            if (bStaffSupportValid && PlayOwnedAnimation(HoldClip, TEXT("StaffHold"), true))
            { Footing = ESaskartaElderFooting::StaffHold; StateSeconds = 0.f; }
            else BeginRecovery();
        }
        if (Footing == ESaskartaElderFooting::StaffHold)
        {
            const float Desired = (PC->IsInputKeyDown(EKeys::D) ? 1.f : 0.f) - (PC->IsInputKeyDown(EKeys::A) ? 1.f : 0.f);
            WeightShift = FMath::FInterpTo(WeightShift, Desired, DeltaTime, 3.f);
            if (UAnimSingleNodeInstance* Instance = Human->GetMesh()->GetSingleNodeInstance(); Instance && Cast<UBlendSpace>(HoldClip.Get()))
                Instance->SetBlendSpacePosition(FVector(WeightShift, 0.f, 0.f));
        }
    }
    else if (bContactsReady && Footing == ESaskartaElderFooting::Recovering)
    {
        if (StateSeconds >= .7f)
        {
            ReleaseSpeedLimit(); ReleaseAnimation(true);
            ReleaseFacing();
            Footing = ESaskartaElderFooting::Walking;
            RecoveryImmunity = 1.5f;
        }
    }
    else if (bContactsReady && bWantsStaff && bStaffReachable) BeginPlant();

    const bool bWalking = Human->GetVelocity().Size2D() > 12.f && Footing != ESaskartaElderFooting::Recovering;
    // The first section is exposed; ruins/station reduce gust frequency, with real walls offering shelter.
    // Exposure follows the ground under the player. A staff tip that cannot yet plant
    // on this slope must not suppress the gust or its warning.
    if ((bWalking || bPlanting || GustCountdown <= 2.4f) && RoadM >= 4790.f && RoadM < 4990.f && !bReducedGusts && bSupportValid)
    {
        GustCountdown -= DeltaTime;
        if (GustCountdown <= 2.4f && WarningSeconds <= 0.f)
        {
            WarningSeconds = 3.f;
            Cue(GustSound, bSheltered ? .08f : .2f);
        }
        if (GustCountdown <= 0.f)
        {
            ++GustNumber;
            GustCountdown = (RoadM < 4845.f ? 16.f : RoadM < 4925.f ? 23.f : 34.f) + (GustNumber % 3)*3.f;
            if (!bSheltered && !bPlanting && RecoveryImmunity <= 0.f)
            {
                Footing = ESaskartaElderFooting::Unsteady;
                StateSeconds = 0.f;
                SetSpeedLimit(65.f);
            }
        }
    }
    if (Footing == ESaskartaElderFooting::Walking && bWalking && bLoose && !bPreviousLoose && RecoveryImmunity <= 0.f && bSupportValid)
    {
        Footing = ESaskartaElderFooting::Unsteady;
        StateSeconds = 0.f;
        WarningSeconds = 2.f;
        Cue(GravelSound, .22f);
        SetSpeedLimit(65.f);
    }
    bPreviousLoose = bLoose;
    if (Footing == ESaskartaElderFooting::Unsteady && StateSeconds >= .7f && SlipTime < 0.f && StumbleSeconds <= 0.f)
    {
        ReleaseSpeedLimit();
        Footing = ESaskartaElderFooting::Walking;
        RecoveryImmunity = 1.5f;
    }
    ShowSlipOverlay();
    TickSlip(PC, Human, DeltaTime, bWalking);
    UpdateHint(PC, Runner, DeltaTime);
}

void USaskartaElderWalk::TickSlip(APlayerController* PC, ACharacter* Human, float DeltaTime, bool bWalking)
{
    // 2026-10-05: the climb's body. Two challenges alternate on the last 200 m:
    //  GRIP     - loose stones: tap SPACE / (A) fast enough before he slides (more taps higher up);
    //  BALANCE  - a gust leans him: hold A / D against the sway and keep him upright for 1.8 s.
    // Failing costs one of three footing pips (stumble or fall). Standing still lets him breathe:
    // every 2.5 s of rest gives a pip back. Low footing = heavier breath, slower legs.
    const bool bOnClimb = RoadM >= 4790.f && RoadM < 4990.f;
    const bool bMashDown = PC && (PC->IsInputKeyDown(EKeys::SpaceBar) || PC->IsInputKeyDown(EKeys::Gamepad_FaceButton_Bottom));
    const bool bMashPress = bMashDown && !bPrevMashDown;
    bPrevMashDown = bMashDown;
    const bool bBecameUnsteady = Footing == ESaskartaElderFooting::Unsteady && PrevFootingForSlip != ESaskartaElderFooting::Unsteady;
    PrevFootingForSlip = Footing;
    FlashSeconds = FMath::Max(0.f, FlashSeconds - DeltaTime);
    {
        const float Want = FMath::Clamp((3 - Health) / 3.f * 0.65f + (SlipTime >= 0.f ? 0.15f + 0.35f * FMath::Abs(Sway) : 0.f) + (StumbleSeconds > 0.f ? 0.35f : 0.f), 0.f, 1.f);
        FatigueLevel = FMath::FInterpTo(FatigueLevel, Want, DeltaTime, 2.5f);
        if (FatigueMID)
        {
            FatigueMID->SetScalarParameterValue(TEXT("Intensity"), FatigueLevel);
            FatigueMID->SetScalarParameterValue(TEXT("HeartRate"), 1.1f + 1.4f * FatigueLevel);
        }
    }
    BreathCooldown = FMath::Max(0.f, BreathCooldown - DeltaTime);
    auto Breath = [this](const TCHAR* Name, float Vol)
    {
        if (BreathCooldown > 0.f) return;
        const FString P = FString::Printf(TEXT("/Game/SaskartaGaea/Audio/Breaths/%s.%s"), Name, Name);
        if (USoundBase* S = LoadObject<USoundBase>(nullptr, *P, nullptr, LOAD_NoWarn | LOAD_Quiet)) UGameplayStatics::PlaySound2D(this, S, Vol);
        BreathCooldown = 2.5f;
    };
    auto SetRoll = [this, PC](float Roll)
    {
        if (!PC) return;
        FRotator R = PC->GetControlRotation();
        R.Roll = FMath::FInterpTo(AppliedRoll, Roll, 0.016f, 10.f);
        AppliedRoll = R.Roll;
        PC->SetControlRotation(R);
    };

    // Rest: standing still recovers footing; low footing breathes hard and walks slower.
    const bool bStill = Human && Human->GetVelocity().Size2D() < 8.f;
    StillSeconds = (bStill && SlipTime < 0.f && StumbleSeconds <= 0.f) ? StillSeconds + DeltaTime : 0.f;
    if (Health < 3 && StillSeconds >= 2.5f)
    {
        ++Health; StillSeconds = 0.f; BreathCooldown = 0.f;
        Breath(TEXT("BREATH_02"), .55f);
        FlashText = TEXT("He catches his breath."); FlashSeconds = 1.6f;
    }
    else if (Health <= 1 && bWalking) Breath(TEXT("BREATH_04A"), .45f);

    if (StumbleSeconds > 0.f)
    {
        StumbleSeconds -= DeltaTime;
        SetSpeedLimit(0.f);
        SetRoll(Health <= 0 ? 14.f * FMath::Sin(StumbleSeconds * 3.f) : 6.f * FMath::Sin(StumbleSeconds * 9.f));
        if (StumbleSeconds <= 0.f)
        {
            ReleaseSpeedLimit();
            Footing = ESaskartaElderFooting::Walking;
            RecoveryImmunity = 2.f;
            if (Health <= 0) { Health = 1; FlashText = TEXT("He gets back up."); FlashSeconds = 2.f; }
            SetRoll(0.f); AppliedRoll = 0.f;
            if (PC) { FRotator R = PC->GetControlRotation(); R.Roll = 0.f; PC->SetControlRotation(R); }
        }
        return;
    }
    if (SlipTime < 0.f)
    {
        if (!FMath::IsNearlyZero(AppliedRoll, 0.05f)) SetRoll(0.f);
        if (Health <= 1 && bHasSpeedLease == false && bOnClimb) SetSpeedLimit(85.f);
        else if (Health > 1 && bHasSpeedLease && Footing == ESaskartaElderFooting::Walking && RecoveryImmunity <= 0.f) ReleaseSpeedLimit();
        if (bOnClimb && bWalking) SlipCountdown -= DeltaTime;
        if (bOnClimb && (bBecameUnsteady || (SlipCountdown <= 0.f && bWalking && Footing == ESaskartaElderFooting::Walking)))
        {
            SlipTime = 0.f;
            SlipPresses = 0;
            ++SlipCount;
            SlipMode = bBecameUnsteady && !bLoose ? 1 : (bLoose ? 0 : (SlipCount % 2));
            SlipNeeded = 5 + (RoadM > 4900.f ? 2 : RoadM > 4850.f ? 1 : 0);
            Sway = FMath::RandBool() ? .25f : -.25f;
            SwayPush = FMath::Sign(Sway) * (0.9f + 0.25f * (RoadM > 4900.f ? 2 : RoadM > 4850.f ? 1 : 0));
            BalancedSeconds = 0.f;
            Cue(SlipMode == 0 ? GravelSound : GustSound, SlipMode == 0 ? .45f : .35f);
            Breath(TEXT("BREATH_05"), .5f);
            UE_LOG(LogSaskartaElderWalk, Log, TEXT("Footing check %d: %s (health %d)"), SlipCount, SlipMode == 0 ? TEXT("grip") : TEXT("balance"), Health);
        }
        return;
    }

    SlipTime += DeltaTime;
    bool bWon = false, bLost = false;
    if (SlipMode == 0)
    {
        SetSpeedLimit(30.f);
        if (bMashPress) { ++SlipPresses; if (StaffSound && (SlipPresses % 2 == 0)) UGameplayStatics::PlaySound2D(this, StaffSound, .25f, 1.1f + .05f * SlipPresses); }
        SetRoll(2.5f * FMath::Sin(SlipTime * 17.f) * (1.f - float(SlipPresses) / float(FMath::Max(1, SlipNeeded))));
        bWon = SlipPresses >= SlipNeeded;
        bLost = !bWon && SlipTime >= 2.4f;
    }
    else
    {
        SetSpeedLimit(25.f);
        const float In = (PC && PC->IsInputKeyDown(EKeys::D) ? 1.f : 0.f) - (PC && PC->IsInputKeyDown(EKeys::A) ? 1.f : 0.f)
            + (PC ? PC->GetInputAnalogKeyState(EKeys::Gamepad_LeftX) : 0.f);
        // the gust shoves, gusts within the gust, and the player's counter-weight
        const float Gusty = SwayPush * (0.8f + 0.5f * FMath::Sin(SlipTime * 5.3f) + 0.3f * FMath::Sin(SlipTime * 11.f));
        // lean = gust + instability (a lean feeds itself) + the player's counter-weight (A pushes left, D right)
        Sway = FMath::Clamp(Sway + (Gusty + Sway * 0.8f + FMath::Clamp(In, -1.f, 1.f) * 2.2f) * DeltaTime, -1.2f, 1.2f);
        if (FMath::Abs(Sway) < .35f) BalancedSeconds += DeltaTime;
        SetRoll(Sway * 11.f);
        if (FMath::Abs(Sway) >= 1.f) bLost = true;
        bWon = BalancedSeconds >= 1.8f;
        if (!bWon && SlipTime >= 5.f) bLost = true;
    }
    if (bWon)
    {
        SlipTime = -1.f;
        ++SlipStreak;
        SlipCountdown = FMath::FRandRange(11.f, 18.f);
        ReleaseSpeedLimit();
        if (Footing == ESaskartaElderFooting::Unsteady) Footing = ESaskartaElderFooting::Walking;
        RecoveryImmunity = 1.5f;
        if (StaffSound) UGameplayStatics::PlaySound2D(this, StaffSound, .7f, .9f);
        FlashText = SlipStreak >= 3 ? FString(TEXT("Sure-footed.")) : FString(TEXT("Steady."));
        FlashSeconds = 1.2f;
        return;
    }
    if (bLost)
    {
        SlipTime = -1.f;
        SlipStreak = 0;
        SlipCountdown = FMath::FRandRange(12.f, 19.f);
        --Health;
        StumbleSeconds = Health <= 0 ? 3.2f : 1.4f;
        if (Human)
        {
            if (UCharacterMovementComponent* Move = Human->GetCharacterMovement()) Move->StopMovementImmediately();
            if (GravelSound) UGameplayStatics::PlaySound2D(this, GravelSound, 1.f, .7f);
            if (StaffSound) UGameplayStatics::PlaySound2D(this, StaffSound, .9f, .7f);
        }
        BreathCooldown = 0.f;
        Breath(Health <= 0 ? TEXT("BREATH_06") : TEXT("BREATH_03"), .8f);
        UE_LOG(LogSaskartaElderWalk, Log, TEXT("Footing lost: health %d"), Health);
    }
}

namespace SlipUi
{
    // Brushes live for the process; the three glyph textures are rooted once (tiny, project UI art).
    static const FSlateBrush* Glyph(const TCHAR* Name)
    {
        static TMap<FString, TSharedPtr<FSlateBrush>> Cache;
        if (TSharedPtr<FSlateBrush>* Found = Cache.Find(Name)) return Found->Get();
        TSharedPtr<FSlateBrush> B = MakeShared<FSlateBrush>();
        const FString Path = FString::Printf(TEXT("/Game/SaskartaGaea/UI/Prompts/Light/%s.%s"), Name, Name);
        if (UTexture2D* T = LoadObject<UTexture2D>(nullptr, *Path, nullptr, LOAD_NoWarn | LOAD_Quiet))
        {
            T->AddToRoot();
            B->SetResourceObject(T);
            B->ImageSize = FVector2D(34.f, 34.f);
            B->DrawAs = ESlateBrushDrawType::Image;
        }
        else
        {
            B->DrawAs = ESlateBrushDrawType::NoDrawType;
        }
        Cache.Add(Name, B);
        return B.Get();
    }
    static const FSlateBrush* Dot()
    {
        static FSlateRoundedBoxBrush B(FLinearColor::White, 5.f, FVector2f(10.f, 10.f));
        return &B;
    }
    static const FSlateBrush* Line()
    {
        static FSlateRoundedBoxBrush B(FLinearColor::White, 1.f, FVector2f(2.f, 2.f));
        return &B;
    }
    static const FLinearColor Ivory(.94f, .90f, .81f, 1.f);
}

void USaskartaElderWalk::ShowSlipOverlay()
{
    if (SlipOverlay.IsValid()) return;
    UWorld* World = GetWorld();
    UGameViewportClient* Viewport = World ? World->GetGameViewport() : nullptr;
    if (!Viewport) return;
    TWeakObjectPtr<USaskartaElderWalk> Self(this);
    FSlateFontInfo Cap = FCoreStyle::GetDefaultFontStyle("Regular", 24);
    if (UFont* F = Cast<UFont>(CaptionFont)) Cap = FSlateFontInfo(F, 24);
    // Fatigue: a full-screen vignette + heartbeat that thickens as footing is lost (M_UI_ElderFatigue, Intensity 0..1).
    if (!FatigueMID)
    {
        if (UMaterialInterface* Base = LoadObject<UMaterialInterface>(nullptr, TEXT("/Game/Submission1005/UI/M_UI_ElderFatigue.M_UI_ElderFatigue"), nullptr, LOAD_NoWarn | LOAD_Quiet))
            FatigueMID = UMaterialInstanceDynamic::Create(Base, this);
    }
    if (FatigueMID && !FatigueBrush.IsValid())
    {
        FatigueBrush = MakeShared<FSlateBrush>();
        FatigueBrush->SetResourceObject(FatigueMID);
        FatigueBrush->ImageSize = FVector2D(1920.f, 1080.f);
        FatigueBrush->DrawAs = ESlateBrushDrawType::Image;
    }
    const FSlateBrush* FatigueImg = FatigueBrush.IsValid() ? FatigueBrush.Get() : FCoreStyle::Get().GetBrush("NoBrush");
    const FSlateBrush* KeySpace = SlipUi::Glyph(TEXT("T_Prompt_Key_Space"));
    const FSlateBrush* KeyA = SlipUi::Glyph(TEXT("T_Prompt_Key_A"));
    const FSlateBrush* KeyD = SlipUi::Glyph(TEXT("T_Prompt_Key_D"));
    const float BarW = 280.f;
    TSharedRef<SWidget> W = SNew(SBox).Visibility(EVisibility::HitTestInvisible)
    [
        SNew(SOverlay)
        + SOverlay::Slot().HAlign(HAlign_Fill).VAlign(VAlign_Fill)
        [
            SNew(SImage).Image(FatigueImg)
            .Visibility_Lambda([Self]() { return Self.IsValid() && Self->FatigueLevel > 0.01f ? EVisibility::HitTestInvisible : EVisibility::Collapsed; })
        ]
        // the challenge: glyph(s) + one quiet line + a hairline gauge, low centre
        + SOverlay::Slot().HAlign(HAlign_Center).VAlign(VAlign_Bottom).Padding(FMargin(0.f, 0.f, 0.f, 210.f))
        [
            SNew(SVerticalBox)
            .Visibility_Lambda([Self]() { return Self.IsValid() && Self->SlipTime >= 0.f ? EVisibility::HitTestInvisible : EVisibility::Collapsed; })
            + SVerticalBox::Slot().AutoHeight().HAlign(HAlign_Center)
            [
                SNew(SHorizontalBox)
                + SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center)
                [
                    SNew(SImage).Image(KeySpace)
                    .Visibility_Lambda([Self]() { return Self.IsValid() && Self->SlipMode == 0 ? EVisibility::HitTestInvisible : EVisibility::Collapsed; })
                ]
                + SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center)
                [
                    SNew(SImage).Image(KeyA)
                    .Visibility_Lambda([Self]() { return Self.IsValid() && Self->SlipMode == 1 ? EVisibility::HitTestInvisible : EVisibility::Collapsed; })
                ]
                + SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center).Padding(FMargin(4.f, 0.f, 0.f, 0.f))
                [
                    SNew(SImage).Image(KeyD)
                    .Visibility_Lambda([Self]() { return Self.IsValid() && Self->SlipMode == 1 ? EVisibility::HitTestInvisible : EVisibility::Collapsed; })
                ]
                + SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center).Padding(FMargin(12.f, 0.f, 0.f, 0.f))
                [
                    SNew(STextBlock).Font(Cap)
                    .ColorAndOpacity(FSlateColor(SlipUi::Ivory))
                    .ShadowOffset(FVector2D(1.f, 2.f)).ShadowColorAndOpacity(FLinearColor(0, 0, 0, .8f))
                    .Text_Lambda([Self]() {
                        if (!Self.IsValid()) return FText::GetEmpty();
                        return FText::FromString(Self->SlipMode == 0 ? TEXT("Loose stones. Find your footing.") : TEXT("The wind. Lean against it."));
                    })
                ]
            ]
            + SVerticalBox::Slot().AutoHeight().HAlign(HAlign_Center).Padding(FMargin(0.f, 14.f, 0.f, 0.f))
            [
                SNew(SBox).WidthOverride(BarW).HeightOverride(12.f)
                [
                    SNew(SOverlay)
                    // track
                    + SOverlay::Slot().VAlign(VAlign_Center)
                    [
                        SNew(SBox).HeightOverride(2.f)
                        [ SNew(SImage).Image(SlipUi::Line()).ColorAndOpacity(FLinearColor(.94f, .90f, .81f, .22f)) ]
                    ]
                    // grip: fill grows from the left
                    + SOverlay::Slot().HAlign(HAlign_Left).VAlign(VAlign_Center)
                    [
                        SNew(SBox).HeightOverride(2.f)
                        .Visibility_Lambda([Self]() { return Self.IsValid() && Self->SlipMode == 0 ? EVisibility::HitTestInvisible : EVisibility::Collapsed; })
                        .WidthOverride_Lambda([Self, BarW]() -> FOptionalSize {
                            if (!Self.IsValid() || Self->SlipNeeded <= 0) return 0.f;
                            return BarW * FMath::Clamp(float(Self->SlipPresses) / float(Self->SlipNeeded), 0.f, 1.f); })
                        [ SNew(SImage).Image(SlipUi::Line()).ColorAndOpacity(FLinearColor(.94f, .90f, .81f, .9f)) ]
                    ]
                    // balance: the safe middle brightens as he holds it
                    + SOverlay::Slot().HAlign(HAlign_Center).VAlign(VAlign_Center)
                    [
                        SNew(SBox).WidthOverride(BarW * .35f / 1.2f * 2.f).HeightOverride(2.f)
                        .Visibility_Lambda([Self]() { return Self.IsValid() && Self->SlipMode == 1 ? EVisibility::HitTestInvisible : EVisibility::Collapsed; })
                        [
                            SNew(SImage).Image(SlipUi::Line())
                            .ColorAndOpacity_Lambda([Self]() {
                                const float P = Self.IsValid() ? FMath::Clamp(Self->BalancedSeconds / 1.8f, 0.f, 1.f) : 0.f;
                                return FSlateColor(FLinearColor(.94f, .90f, .81f, .35f + .55f * P)); })
                        ]
                    ]
                    // balance: the dot is him
                    + SOverlay::Slot().HAlign(HAlign_Left).VAlign(VAlign_Center)
                    .Padding(TAttribute<FMargin>::CreateLambda([Self, BarW]() {
                        const float S = Self.IsValid() ? FMath::Clamp(Self->Sway / 1.2f, -1.f, 1.f) : 0.f;
                        return FMargin(BarW * .5f - 5.f + S * (BarW * .5f - 5.f), 0.f, 0.f, 0.f); }))
                    [
                        SNew(SImage).Image(SlipUi::Dot())
                        .Visibility_Lambda([Self]() { return Self.IsValid() && Self->SlipMode == 1 ? EVisibility::HitTestInvisible : EVisibility::Collapsed; })
                        .ColorAndOpacity(FLinearColor(.94f, .90f, .81f, 1.f))
                    ]
                ]
            ]
        ]
        // after the check: one short line that fades (stumble, fall, steady, breath)
        + SOverlay::Slot().HAlign(HAlign_Center).VAlign(VAlign_Bottom).Padding(FMargin(0.f, 0.f, 0.f, 220.f))
        [
            SNew(STextBlock).Font(Cap)
            .ShadowOffset(FVector2D(1.f, 2.f)).ShadowColorAndOpacity(FLinearColor(0, 0, 0, .8f))
            .Visibility_Lambda([Self]() { return Self.IsValid() && Self->SlipTime < 0.f && (Self->StumbleSeconds > 0.f || Self->FlashSeconds > 0.f) ? EVisibility::HitTestInvisible : EVisibility::Collapsed; })
            .ColorAndOpacity_Lambda([Self]() {
                float A = 1.f;
                if (Self.IsValid() && Self->StumbleSeconds <= 0.f) A = FMath::Clamp(Self->FlashSeconds / .6f, 0.f, 1.f);
                return FSlateColor(FLinearColor(.94f, .90f, .81f, .9f * A)); })
            .Text_Lambda([Self]() {
                if (!Self.IsValid()) return FText::GetEmpty();
                if (Self->StumbleSeconds > 0.f) return FText::FromString(Self->Health <= 0 ? TEXT("He falls.") : TEXT("He stumbles."));
                return FText::FromString(Self->FlashText); })
        ]
        // footing: three small dots, only while it matters
        + SOverlay::Slot().HAlign(HAlign_Center).VAlign(VAlign_Bottom).Padding(FMargin(0.f, 0.f, 0.f, 180.f))
        [
            SNew(SHorizontalBox)
            .Visibility_Lambda([Self]() { return Self.IsValid() && (Self->SlipTime >= 0.f || Self->StumbleSeconds > 0.f || Self->Health < 3) ? EVisibility::HitTestInvisible : EVisibility::Collapsed; })
            + SHorizontalBox::Slot().AutoWidth().Padding(FMargin(5.f, 0.f))
            [ SNew(SImage).Image(SlipUi::Dot()).ColorAndOpacity_Lambda([Self]() { return FSlateColor(FLinearColor(.94f, .90f, .81f, Self.IsValid() && Self->Health >= 1 ? .85f : .18f)); }) ]
            + SHorizontalBox::Slot().AutoWidth().Padding(FMargin(5.f, 0.f))
            [ SNew(SImage).Image(SlipUi::Dot()).ColorAndOpacity_Lambda([Self]() { return FSlateColor(FLinearColor(.94f, .90f, .81f, Self.IsValid() && Self->Health >= 2 ? .85f : .18f)); }) ]
            + SHorizontalBox::Slot().AutoWidth().Padding(FMargin(5.f, 0.f))
            [ SNew(SImage).Image(SlipUi::Dot()).ColorAndOpacity_Lambda([Self]() { return FSlateColor(FLinearColor(.94f, .90f, .81f, Self.IsValid() && Self->Health >= 3 ? .85f : .18f)); }) ]
        ]
    ];
    Viewport->AddViewportWidgetContent(W, 150);
    SlipOverlay = W;
    SlipViewport = Viewport;
}

void USaskartaElderWalk::HideSlipOverlay()
{
    if (SlipOverlay.IsValid())
        if (UGameViewportClient* V = SlipViewport.Get()) V->RemoveViewportWidgetContent(SlipOverlay.ToSharedRef());
    SlipOverlay.Reset();
    SlipViewport.Reset();
    FatigueBrush.Reset();
    FatigueLevel = 0.f;
}

void USaskartaElderWalk::Deinitialize()
{
    Suspend(false);
    if (AssetsLoad.IsValid()) AssetsLoad->CancelHandle();
    if (StaffVisualLoad.IsValid()) StaffVisualLoad->CancelHandle();
    if (ContactLoad.IsValid()) ContactLoad->CancelHandle();
    AssetsLoad.Reset(); StaffVisualLoad.Reset(); ContactLoad.Reset();
    for (const auto& Pair : StaffVisuals)
        if (UStaticMeshComponent* Visual = Pair.Value.Get()) Visual->DestroyComponent();
    StaffVisuals.Empty();
    HideSlipOverlay();
    if (Hint) Hint->RemoveFromParent();
    if (CueAudio) CueAudio->DestroyComponent();
    Hint = nullptr; CueAudio = nullptr;
    Super::Deinitialize();
}
