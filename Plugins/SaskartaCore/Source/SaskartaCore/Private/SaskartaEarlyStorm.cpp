#include "SaskartaEarlyStorm.h"

#include "SaskartaAmbienceDirector.h"
#include "SaskartaEventRunner.h"
#include "SaskartaLightingDirector.h"
#include "SaskartaMotorResonance.h"
#include "SaskartaPackageRescue.h"
#include "SaskartaDustWreck.h"
#include "SaskartaDustFront.h"
#include "SaskartaSaveGame.h"
#include "SaskartaStoryAsset.h"
#include "Components/SplineComponent.h"
#include "Components/AudioComponent.h"
#include "Engine/AssetManager.h"
#include "Engine/StreamableManager.h"
#include "Sound/SoundBase.h"
#include "GameFramework/Character.h"
#include "GameFramework/CharacterMovementComponent.h"
#include "GameFramework/PlayerController.h"
#include "Kismet/GameplayStatics.h"
#include "UObject/UnrealType.h"
#include "SaskartaPower.h"
#include "SaskartaRadioStation.h"
#include "SaskartaStormShells.h"
#include "Engine/World.h"
#include "TimerManager.h"
#include "Camera/PlayerCameraManager.h"
#include "Components/LocalFogVolumeComponent.h"
#include "Components/SceneComponent.h"
#include "Engine/GameViewportClient.h"
#include "Engine/Texture2D.h"
#include "HAL/IConsoleManager.h"
#include "Rendering/DrawElements.h"
#include "Styling/SlateBrush.h"
#include "Widgets/SLeafWidget.h"
#include "Widgets/SWeakWidget.h"

DEFINE_LOG_CATEGORY_STATIC(LogSaskartaEarlyStorm, Log, All);

/** Lens impacts only. World visibility is supplied by depth-tested extinction, not this overlay. */
class SSaskartaStormLens : public SLeafWidget
{
public:
    SLATE_BEGIN_ARGS(SSaskartaStormLens) {}
    SLATE_END_ARGS()
    void Construct(const FArguments&) { Points.Reserve(2); SetVisibility(EVisibility::HitTestInvisible); }
    void Configure(UTexture2D* Grime)
    {
        GrimeBrush.SetResourceObject(Grime);
        GrimeBrush.DrawAs = ESlateBrushDrawType::Image;
        GrimeBrush.ImageSize = FVector2D(1024.f, 1024.f);
    }
    void Update(float InNear, float InTimeS, FVector2f InWind, bool bVisible)
    {
        Near = InNear;
        TimeS = InTimeS;
        Wind = InWind.GetSafeNormal();
        if (Wind.IsNearlyZero()) Wind = FVector2f(-1.f, .18f);
        SetVisibility(bVisible ? EVisibility::HitTestInvisible : EVisibility::Collapsed);
        Invalidate(EInvalidateWidgetReason::Paint);
    }
    virtual FVector2D ComputeDesiredSize(float) const override { return FVector2D(1.f, 1.f); }
    virtual int32 OnPaint(const FPaintArgs&, const FGeometry& Geometry, const FSlateRect&,
        FSlateWindowElementList& Elements, int32 Layer, const FWidgetStyle&, bool) const override
    {
        const FVector2f Size(Geometry.GetLocalSize());
        if (Near <= .01f || Size.X <= 0.f || Size.Y <= 0.f) return Layer;
        // The existing grime texture has transparent clear glass in its centre.
        if (GrimeBrush.GetResourceObject())
            FSlateDrawElement::MakeBox(Elements, Layer, Geometry.ToPaintGeometry(), &GrimeBrush,
                ESlateDrawEffect::None, FLinearColor(.16f, .12f, .075f, Near * .22f));
        const int32 Count = 16 + FMath::RoundToInt(56.f * Near);
        const float Scale = Size.Y / 1080.f;
        for (int32 Index = 0; Index < Count; ++Index)
        {
            const float Seed = FMath::Frac(FMath::Sin((Index + 1.f) * 78.233f) * 43758.547f);
            const float SeedY = FMath::Frac(FMath::Sin((Index + 3.f) * 39.425f) * 23743.213f);
            const float Speed = 220.f + 360.f * Seed + 220.f * Near;
            const float Travel = TimeS * Speed * Scale;
            const FVector2f Position(
                FMath::Frac(Seed + Wind.X * Travel / Size.X) * Size.X,
                FMath::Frac(SeedY + Wind.Y * Travel / Size.Y) * Size.Y);
            const float Edge = FMath::Max(FMath::Abs(Position.X / Size.X - .5f), FMath::Abs(Position.Y / Size.Y - .5f)) * 2.f;
            const float Alpha = Near * (.05f + .14f * Edge) * (.6f + .4f * SeedY);
            Points.Reset();
            Points.Add(FVector2d(Position));
            Points.Add(FVector2d(Position - Wind * ((4.f + 16.f * Seed) * Scale)));
            FSlateDrawElement::MakeLines(Elements, Layer + 1, Geometry.ToPaintGeometry(), Points,
                ESlateDrawEffect::None, FLinearColor(.32f, .23f, .13f, Alpha), true,
                FMath::Max(.6f, (.6f + Seed * 1.2f) * Scale));
        }
        return Layer + 1;
    }
private:
    FSlateBrush GrimeBrush;
    mutable TArray<FVector2d> Points;
    float Near = 0.f;
    float TimeS = 0.f;
    FVector2f Wind = FVector2f(-1.f, .18f);
};

namespace SaskartaEarlyStorm
{
    constexpr float StartRoadM = 650.f;
    constexpr float ShelterRoadM = 1220.f;
    constexpr float PollS = 0.25f;
    constexpr float FrontMps = 6.2f;
    constexpr float InitialGapM = 65.f;
    constexpr float IntroGapM = 70.f;
    constexpr float IntroDurationS = 6.f;
    constexpr float BaseRoadSpeedMps = 6.1f;
    constexpr float ProximityRattleGapM = 35.f;
    constexpr float ProximityRattleGain = 0.31622777f; // -10 dB, matching the existing tin-rattle pool
    const FSoftObjectPath ProximityRattlePath(TEXT("/Game/SaskartaGaea/Audio/Ambience2/SFX_Storm_TinRattle_02.SFX_Storm_TinRattle_02"));
    const FSoftObjectPath AlarmPaths[] = {
        FSoftObjectPath(TEXT("/Game/SaskartaGaea/Audio/Storm/SFX_Dosimeter_Chirp_01.SFX_Dosimeter_Chirp_01")),
        FSoftObjectPath(TEXT("/Game/SaskartaGaea/Audio/Storm/SFX_Dosimeter_Chirp_02.SFX_Dosimeter_Chirp_02"))
    };
    const FName PursuitCheckpointId(TEXT("CP_EARLY_DUST"));
    const FName StormBeat(TEXT("B04A_DUST_FRONT"));
    const FName StormCine(TEXT("CIN_04_DUST_FRONT"));
    const FName Playing(TEXT("Playing"));
    const FName CarrierFlow(TEXT("Carrier"));

    void SetCarrierNumber(ACharacter* Carrier, const TCHAR* Name, double Value)
    {
        if (FNumericProperty* Property = FindFProperty<FNumericProperty>(Carrier->GetClass(), Name))
            if (Property->IsFloatingPoint()) Property->SetFloatingPointPropertyValue(Property->ContainerPtrToValuePtr<void>(Carrier), Value);
    }

    void SetFlow(APlayerController* PC, FName Flow)
    {
        if (PC)
            if (FNameProperty* Property = FindFProperty<FNameProperty>(PC->GetClass(), TEXT("FlowState")))
                Property->SetPropertyValue_InContainer(PC, Flow);
    }

}

USaskartaEarlyStormSubsystem::USaskartaEarlyStormSubsystem()
{
    LensGrimeAsset = TSoftObjectPtr<UTexture2D>(FSoftObjectPath(
        TEXT("/Game/SaskartaGaea/UI/SensorDamage/T_SensorGrime.T_SensorGrime")));
}

bool USaskartaEarlyStormSubsystem::ShouldCreateSubsystem(UObject* Outer) const
{
    const UWorld* World = Cast<UWorld>(Outer);
    return World && World->IsGameWorld();
}

void USaskartaEarlyStormSubsystem::OnWorldBeginPlay(UWorld& InWorld)
{
    Super::OnWorldBeginPlay(InWorld);
    WriteHandle = USaskartaSaveGame::OnWritingRun.AddUObject(this, &USaskartaEarlyStormSubsystem::HandleWritingRun);
    RestoreHandle = USaskartaSaveGame::OnRestoredRun.AddUObject(this, &USaskartaEarlyStormSubsystem::HandleRestoredRun);
    if (UAssetManager::IsInitialized())
    {
        DustPresentationLoad = UAssetManager::GetStreamableManager().RequestAsyncLoad(
            LensGrimeAsset.ToSoftObjectPath(), FStreamableDelegate());
        TArray<FSoftObjectPath> AlarmAssets;
        for (const FSoftObjectPath& Path : SaskartaEarlyStorm::AlarmPaths) AlarmAssets.Add(Path);
        StormAlarmLoad = UAssetManager::GetStreamableManager().RequestAsyncLoad(AlarmAssets, FStreamableDelegate());
    }
    InWorld.GetTimerManager().SetTimer(PollTimer, this, &USaskartaEarlyStormSubsystem::Poll,
        SaskartaEarlyStorm::PollS, true);
}

void USaskartaEarlyStormSubsystem::Deinitialize()
{
    if (UWorld* World = GetWorld())
    {
        World->GetTimerManager().ClearTimer(PollTimer);
    }
    USaskartaSaveGame::OnRestoredRun.Remove(RestoreHandle);
    USaskartaSaveGame::OnWritingRun.Remove(WriteHandle);
    HideFailure();
    EndChase();
    if (StormAlarmLoad.IsValid()) StormAlarmLoad->CancelHandle();
    StormAlarmLoad.Reset();
    StormAlarmSounds.Reset();
    if (DustPresentationLoad.IsValid()) DustPresentationLoad->CancelHandle();
    DustPresentationLoad.Reset();
    PursuitCheckpoint = nullptr;
    if (USaskartaEventRunner* Runner = BoundRunner.Get())
    {
        Runner->OnCinematicStarted.RemoveDynamic(this, &USaskartaEarlyStormSubsystem::OnCinematicStarted);
        Runner->OnCinematicFinished.RemoveDynamic(this, &USaskartaEarlyStormSubsystem::OnCinematicFinished);
    }
    Super::Deinitialize();
}

void USaskartaEarlyStormSubsystem::BindRunner(USaskartaEventRunner* Runner)
{
    if (!Runner || BoundRunner.Get() == Runner)
    {
        return;
    }
    BoundRunner = Runner;
    Runner->OnCinematicStarted.AddDynamic(this, &USaskartaEarlyStormSubsystem::OnCinematicStarted);
    Runner->OnCinematicFinished.AddDynamic(this, &USaskartaEarlyStormSubsystem::OnCinematicFinished);
}

void USaskartaEarlyStormSubsystem::OnCinematicStarted(FName CinematicId)
{
    if (CinematicId != SaskartaEarlyStorm::StormCine || bChasing || bFailed)
    {
        return;
    }
    if (USaskartaStormShellsSubsystem* Shells = USaskartaStormShellsSubsystem::GetStormShells(this))
    {
        bPreviousShellSuppression = Shells->IsSuppressed();
        Shells->SetSuppressed(true);
        bOwnsShellSuppression = true;
    }
    // The start delegate precedes WaitingStop. Show the front now, but do not
    // approach or run the motor until actual playback and the later handback.
    bIntroActive = true;
    IntroCarrierRoadM = -1.f;
    FrontGapM = SaskartaEarlyStorm::IntroGapM;
    if (BoundRunner.IsValid()) FrontRoadM = BoundRunner->GetRoadM() - FrontGapM;
    ApplyWeather(FrontGapM);
    UE_LOG(LogSaskartaEarlyStorm, Log, TEXT("dust front cinematic started"));
}

void USaskartaEarlyStormSubsystem::OnCinematicFinished(FName CinematicId)
{
    if (CinematicId == SaskartaEarlyStorm::StormCine)
    {
        bIntroActive = false;
        BeginChase();
        if (!bChasing) EndChase();
    }
}

void USaskartaEarlyStormSubsystem::UpdateIntroFront()
{
    if (!bIntroActive) return;
    UWorld* World = GetWorld();
    USaskartaEventRunner* Runner = BoundRunner.Get();
    if (!World || !Runner || Runner->GetActiveCinematicId() != SaskartaEarlyStorm::StormCine
        || Runner->GetFlowState() == TEXT("Title") || Runner->GetFlowState() == TEXT("Loading")
        || Runner->GetFlowState() == TEXT("Human"))
    {
        EndChase(); // StopAll/title/restore may cancel without a finished delegate.
        return;
    }
    if (World->IsPaused() || Runner->GetFlowState() == TEXT("Paused")) return;
    // The runner returns -1 before playback and during the final camera blend.
    // Its sequence/world clock already excludes pause and prompt waits.
    const float PlaybackS = Runner->GetCinematicPlaybackSeconds();
    if (!FMath::IsFinite(PlaybackS) || PlaybackS < 0.f)
    {
        UpdateFrontVisual(FrontGapM);
        return;
    }
    const float RoadM = Runner->GetRoadM();
    if (!FMath::IsFinite(RoadM) || RoadM < 0.f) return;
    if (IntroCarrierRoadM < 0.f) IntroCarrierRoadM = RoadM;
    const float Alpha = FMath::Clamp(PlaybackS / SaskartaEarlyStorm::IntroDurationS, 0.f, 1.f);
    const float Ease = Alpha * Alpha * (3.f - 2.f * Alpha);
    const float StagedGapM = FMath::Lerp(SaskartaEarlyStorm::IntroGapM, SaskartaEarlyStorm::InitialGapM, Ease);
    FrontRoadM = IntroCarrierRoadM - StagedGapM;
    FrontGapM = RoadM - FrontRoadM;
    ApplyWeather(FrontGapM); // Visual/weather only: no scoring, catch, drive or speech.
}

void USaskartaEarlyStormSubsystem::BeginChase(bool bRetry)
{
    if (bChasing)
    {
        return;
    }
    UWorld* World = GetWorld();
    USaskartaEventRunner* Runner = BoundRunner.Get();
    USaskartaPowerSubsystem* Power = World ? World->GetSubsystem<USaskartaPowerSubsystem>() : nullptr;
    if (!World || !Runner || !Power || Runner->GetRoadM() < 0.f)
    {
        return;
    }
    APlayerController* PC = World->GetFirstPlayerController();
    ACharacter* Pawn = PC ? Cast<ACharacter>(PC->GetPawn()) : nullptr;
    if (!PC || !Pawn || !Runner->GetRoadSpline()) return;
    bool bRefueled = false;
    // A rescued/continued pursuit needs a powered carrier before the front restarts.
    // Fresh entries and ordinary empty-cell stops still use stationary recharge.
    if (bRetry && !RestoreRecoveryFuel(bRefueled)) return;
    const float Charge = Power->GetCharge();
    if (!bRetry)
    {
        PursuitCheckpoint = Runner->CreateCheckpointSnapshot(SaskartaEarlyStorm::PursuitCheckpointId, true);
        if (!PursuitCheckpoint) return;
        if (!UGameplayStatics::SaveGameToSlot(PursuitCheckpoint, USaskartaSaveGame::RunSlot, 0))
            UE_LOG(LogSaskartaEarlyStorm, Warning, TEXT("pursuit checkpoint disk save failed; in-memory retry remains available"));
    }
    RecoveryCheckpoints.Reset();
    bIntroActive = false;
    IntroCarrierRoadM = -1.f;
    if (PursuitCheckpoint) RecoveryCheckpoints.Add(PursuitCheckpoint);
    LastRecoveryRoadM = Runner->GetRoadM();
    bFailed = false;
    DriveController = PC;
    DriveCarrier = Pawn;
    PC->SetIgnoreMoveInput(true);
    bOwnsMoveLock = true;
    Pawn->ConsumeMovementInputVector();
    UCharacterMovementComponent* Movement = Pawn->GetCharacterMovement();
    PreviousMaxSpeed = Movement->MaxWalkSpeed;
    PreviousAcceleration = Movement->MaxAcceleration;
    PreviousBraking = Movement->BrakingDecelerationWalking;
    bPreviousOrientToMovement = Movement->bOrientRotationToMovement;
    Movement->StopMovementImmediately();
    DriveSpeedCmS = 0.f;
    if (USaskartaMotorResonanceSubsystem* Motor = World->GetSubsystem<USaskartaMotorResonanceSubsystem>()) Motor->BeginPursuit();
    if (!bOwnsShellSuppression)
    {
        if (USaskartaStormShellsSubsystem* Shells = USaskartaStormShellsSubsystem::GetStormShells(this))
        {
            bPreviousShellSuppression = Shells->IsSuppressed();
            Shells->SetSuppressed(true);
            bOwnsShellSuppression = true;
        }
    }
    FrontSpeedMps = SaskartaEarlyStorm::FrontMps;
    FrontGapM = SaskartaEarlyStorm::InitialGapM;
    FrontRoadM = Runner->GetRoadM() - FrontGapM;
    LastPollS = World->GetTimeSeconds();
    LastNoticeS = LastPollS;
    bChasing = true;
    bStormAlarmArmed = true;
    bStormAlarmOnset = true;
    StormAlarmPulsesLeft = 0;
    NextStormAlarmS = World->GetTimeSeconds() + .35;
    ClearProximityRattle();
    if (UAssetManager::IsInitialized())
        ProximityRattleLoad = UAssetManager::GetStreamableManager().RequestAsyncLoad(SaskartaEarlyStorm::ProximityRattlePath, FStreamableDelegate());
    ApplyWeather(FrontGapM);
    if (USaskartaAmbienceDirector* Ambience = USaskartaAmbienceDirector::GetAmbienceDirector(this))
    {
        Ambience->TriggerGust();
    }
    Power->ShowNotice(bRefueled
        ? TEXT("RECOVERY FUEL RESTORED . CRANK E ON THE BEAT . A / D BALANCE")
        : TEXT("AUTO DRIVE . CRANK E ON THE BEAT . A / D BALANCE"), 6.f);
    UE_LOG(LogSaskartaEarlyStorm, Log, TEXT("dust chase begins at road %.0f m, charge %.1f%%, gap %.0f m, front %.1f m/s"),
        Runner->GetRoadM(), Charge, FrontGapM, FrontSpeedMps);
}

void USaskartaEarlyStormSubsystem::EndChase(bool bKeepWorldFront)
{
    bIntroActive = false;
    IntroCarrierRoadM = -1.f;
    if (BoundRunner.IsValid()) BoundRunner->UpdateStormPanic(0.f, false, false);
    ClearProximityRattle();
    bStormAlarmArmed = false;
    bStormAlarmOnset = false;
    StopStormAlarm();
    bBackgroundActive = bKeepWorldFront && IsValid(FrontActor);
    if (bBackgroundActive)
    {
        // Escape releases gameplay immediately; the surrounding haze clears
        // gradually while the actual world front remains behind the channel.
        bDustFading = IsValid(CloseDustVolume);
        DustFadeS = 0.f;
    }
    else
    {
        bDustFading = false;
        ClearDustPresentation();
        if (IsValid(FrontActor)) FrontActor->Destroy();
        FrontActor = nullptr;
        FrontFogLobes.Reset();
        FrontFogExtinction.Reset();
        FrontVisibilityAlpha = 0.f;
        AppliedFrontVisibilityAlpha = -1.f;
    }
    ReleaseDrive();
    if (UWorld* World = GetWorld())
        if (USaskartaMotorResonanceSubsystem* Motor = World->GetSubsystem<USaskartaMotorResonanceSubsystem>()) Motor->EndPursuit();
    if (bOwnsShellSuppression && !bDustFading)
    {
        if (USaskartaStormShellsSubsystem* Shells = USaskartaStormShellsSubsystem::GetStormShells(this))
        {
            Shells->SetSuppressed(bPreviousShellSuppression);
        }
        bOwnsShellSuppression = false;
    }
    if (bOwnsWeather)
    {
        if (USaskartaLightingDirector* Director = USaskartaLightingDirector::GetLightingDirector(this))
        {
            if (!bDustFading && FMath::IsNearlyEqual(Director->GetStormOverride(), LastStormIntensity))
                Director->SetStormOverride(PreviousStormIntensity);
        }
        if (!bDustFading) bOwnsWeather = false;
    }
    if (bChasing && !bFailed)
    {
        if (UWorld* World = GetWorld())
        {
            if (USaskartaPowerSubsystem* Power = World->GetSubsystem<USaskartaPowerSubsystem>())
            {
                const bool bAtChannel = BoundRunner.IsValid()
                    && BoundRunner->GetRoadM() >= SaskartaEarlyStorm::ShelterRoadM;
                Power->ShowNotice(bAtChannel
                    ? TEXT("CHANNEL . DUST PASSING")
                    : TEXT("DUST PASSED . SCAN RESUMED"), 4.f);
            }
        }
        UE_LOG(LogSaskartaEarlyStorm, Log, TEXT("dust front cleared at road %.0f m"),
            BoundRunner.IsValid() ? BoundRunner->GetRoadM() : -1.f);
    }
    bChasing = false;
}

void USaskartaEarlyStormSubsystem::TryPlayProximityRattle()
{
    const USaskartaMotorResonanceSubsystem* Motor = GetWorld() ? GetWorld()->GetSubsystem<USaskartaMotorResonanceSubsystem>() : nullptr;
    const USaskartaEventRunner* Runner = BoundRunner.Get();
    if (!bChasing || !Motor || !Motor->CanAcceptInput() || Motor->IsInputWarningActive()
        || !Runner || !Runner->CanPlayStormAlarm() || IsStormAlarmBusy() || bProximityRattleFired ||
        FrontGapM <= 0.f || FrontGapM > SaskartaEarlyStorm::ProximityRattleGapM ||
        !ProximityRattleLoad.IsValid() || !ProximityRattleLoad->HasLoadCompleted()) return;
    // Resolve only the retained async result. Missing or late audio must never
    // block driving, and no PlayNamedSfx/LoadSynchronous fallback is permitted.
    ProximityRattleSound = Cast<USoundBase>(ProximityRattleLoad->GetLoadedAsset());
    if (!ProximityRattleSound) return;
    bProximityRattleFired = true; // one attempt per chase, including a failed voice allocation
    ProximityRattleAudio = UGameplayStatics::CreateSound2D(this, ProximityRattleSound,
        SaskartaEarlyStorm::ProximityRattleGain, 1.f, 0.f, nullptr, false, true);
    if (ProximityRattleAudio)
    {
        // Keep the wave's authored SC_Ambience / SMX_Ambience routing. This is
        // world audio, so pause must not leave a UI sound playing over the menu.
        ProximityRattleAudio->bIsUISound = false;
        ProximityRattleAudio->Play();
    }
}

void USaskartaEarlyStormSubsystem::StopProximityRattle()
{
    if (IsValid(ProximityRattleAudio)) ProximityRattleAudio->Stop();
    ProximityRattleAudio = nullptr;
}

void USaskartaEarlyStormSubsystem::ClearProximityRattle()
{
    StopProximityRattle();
    if (ProximityRattleLoad.IsValid()) ProximityRattleLoad->CancelHandle();
    ProximityRattleLoad.Reset();
    ProximityRattleSound = nullptr;
    bProximityRattleFired = false;
}

bool USaskartaEarlyStormSubsystem::IsStormAlarmBusy() const
{
    return StormAlarmPulsesLeft > 0 || (IsValid(StormAlarmAudio) && StormAlarmAudio->IsPlaying())
        || (IsValid(ProximityRattleAudio) && ProximityRattleAudio->IsPlaying());
}

void USaskartaEarlyStormSubsystem::StopStormAlarm()
{
    if (IsValid(StormAlarmAudio))
    {
        StormAlarmAudio->Stop();
        StormAlarmAudio->DestroyComponent();
    }
    StormAlarmAudio = nullptr;
    StormAlarmPulsesLeft = 0;
    if (const UWorld* World = GetWorld()) NextStormAlarmS = World->GetTimeSeconds() + 2.0;
}

void USaskartaEarlyStormSubsystem::UpdateStormAlarm(bool bInputWarningActive)
{
    UWorld* World = GetWorld();
    const USaskartaEventRunner* Runner = BoundRunner.Get();
    if (!bStormAlarmArmed || !bChasing || !World || !Runner || World->IsPaused()
        || bInputWarningActive || !Runner->CanPlayStormAlarm())
    {
        // A new line or input cue can interrupt a pulse, never the radio cursor.
        if (IsStormAlarmBusy()) StopStormAlarm();
        return;
    }
    if (StormAlarmSounds.IsEmpty())
    {
        if (!StormAlarmLoad.IsValid() || !StormAlarmLoad->HasLoadCompleted()) return;
        for (const FSoftObjectPath& Path : SaskartaEarlyStorm::AlarmPaths)
            if (USoundBase* Sound = Cast<USoundBase>(Path.ResolveObject())) StormAlarmSounds.Add(Sound);
        if (StormAlarmSounds.IsEmpty()) return;
    }
    const double NowS = World->GetTimeSeconds();
    if (NowS < NextStormAlarmS || (IsValid(StormAlarmAudio) && StormAlarmAudio->IsPlaying())) return;
    if (StormAlarmPulsesLeft <= 0) StormAlarmPulsesLeft = (bStormAlarmOnset || FrontGapM > 25.f) ? 2 : 3;
    USoundBase* Sound = StormAlarmSounds[StormAlarmVariant++ % StormAlarmSounds.Num()];
    const float DurationS = Sound->GetDuration();
    if (!FMath::IsFinite(DurationS) || DurationS <= 0.f || DurationS > .8f)
    {
        StormAlarmPulsesLeft = 0;
        NextStormAlarmS = NowS + 12.0;
        return;
    }
    if (!IsValid(StormAlarmAudio))
    {
        StormAlarmAudio = UGameplayStatics::CreateSound2D(this, Sound, 1.f, 1.f, 0.f, nullptr, false, false);
        if (!StormAlarmAudio) { StormAlarmPulsesLeft = 0; NextStormAlarmS = NowS + 8.0; return; }
        StormAlarmAudio->bIsUISound = false;
    }
    StormAlarmAudio->SetSound(Sound);
    // Reuse the approved short pager alarm takes; density of the cadence grows,
    // not an unbounded siren loop. The wave keeps its authored sound-class route.
    const float Gain = FMath::Lerp(.45f, .7f, FMath::Clamp((65.f - FrontGapM) / 45.f, 0.f, 1.f));
    StormAlarmAudio->FadeIn(.035f, Gain);
    --StormAlarmPulsesLeft;
    bStormAlarmOnset = false;
    NextStormAlarmS = NowS + (StormAlarmPulsesLeft > 0 ? .5 : FrontGapM <= 25.f ? 6.0 : FrontGapM <= 50.f ? 9.0 : 12.0);
}

void USaskartaEarlyStormSubsystem::ApplyWeather(float GapM)
{
    UpdateFrontVisual(GapM);
    UpdateDustPresentation(GapM);
    USaskartaLightingDirector* Director = USaskartaLightingDirector::GetLightingDirector(this);
    if (!Director)
    {
        return;
    }
    const float Approach = FMath::Clamp((80.f - GapM) / 80.f, 0.f, 1.f);
    const float Near = Approach * Approach * (3.f - 2.f * Approach);
    // 0.8+ arms the ambience director's dust-wall Geiger spike at first sight of the front.
    const float Storm = FMath::Lerp(0.84f, 1.f, Near);
    if (!bOwnsWeather) PreviousStormIntensity = Director->GetStormOverride();
    if (!bOwnsWeather || FMath::Abs(Storm - LastStormIntensity) >= 0.04f)
    {
        Director->SetStormOverride(Storm);
        LastStormIntensity = Storm;
    }
    bOwnsWeather = true;
}

void USaskartaEarlyStormSubsystem::UpdateDustPresentation(float GapM)
{
    UWorld* World = GetWorld();
    APlayerCameraManager* Camera = UGameplayStatics::GetPlayerCameraManager(World, 0);
    if (!World || !Camera || !FMath::IsFinite(GapM)) return;
    const FVector View = Camera->GetCameraLocation();
    if (View.ContainsNaN()) return;
    const double NowS = World->GetTimeSeconds();
    if (LastDustPresentationS >= 0.0 && NowS - LastDustPresentationS < .1) return;
    const float VisualDeltaS = LastDustPresentationS < 0.0 ? 0.f
        : FMath::Clamp(static_cast<float>(NowS - LastDustPresentationS), 0.f, .25f);
    LastDustPresentationS = NowS;
    const float Approach = FMath::Clamp((80.f - GapM) / 80.f, 0.f, 1.f);
    DustProximity = FMath::FInterpTo(DustProximity, Approach * Approach * (3.f - 2.f * Approach), VisualDeltaS, 2.f);
    const float Entry = FMath::Clamp(DustTimeS / 6.f, 0.f, 1.f);
    DustEffectAlpha = Entry * Entry * (3.f - 2.f * Entry);
    if (bDustFading)
    {
        const float Exit = FMath::Clamp(DustFadeS / 4.5f, 0.f, 1.f);
        DustEffectAlpha *= 1.f - Exit * Exit * (3.f - 2.f * Exit);
    }
    DustNear = FMath::Lerp(.42f, 1.f, DustProximity);
    if (USaskartaLightingDirector* Director = USaskartaLightingDirector::GetLightingDirector(this))
    {
        // Surround the player throughout this encounter, including a 65 m gap.
        // The approaching wall tightens the 10%-transmission distance to 20 m.
        const float VisibilityM = FMath::Lerp(40.f, 20.f, DustProximity);
        Director->SetPursuitDustFog(this, DustEffectAlpha, VisibilityM, static_cast<float>(View.Z));
    }
    if (!IsValid(CloseDustVolume))
    {
        FActorSpawnParameters Spawn;
        Spawn.ObjectFlags |= RF_Transient;
        CloseDustVolume = World->SpawnActor<AActor>(FVector::ZeroVector, FRotator::ZeroRotator, Spawn);
        if (!CloseDustVolume) return;
        CloseDustVolume->SetActorEnableCollision(false);
        USceneComponent* Root = NewObject<USceneComponent>(CloseDustVolume, TEXT("SurroundingDustAnchor"));
        Root->SetMobility(EComponentMobility::Movable);
        CloseDustVolume->SetRootComponent(Root);
        CloseDustVolume->AddInstanceComponent(Root);
        Root->RegisterComponent();
        // The old 10 m global near limit overruled the component's zero start.
        // Use the existing setter priority and release only values still owned
        // by this encounter; do not raise quality settings or their priorities.
        auto OwnCvar = [this](const TCHAR* Name, float Value)
        {
            IConsoleVariable* Cvar = IConsoleManager::Get().FindConsoleVariable(Name);
            if (!Cvar || (Cvar->GetFlags() & ECVF_ReadOnly) != 0) return;
            FOwnedDustCvar Owned;
            Owned.Name = FName(Name);
            Owned.Previous = Cvar->GetFloat();
            Owned.SetBy = Cvar->GetFlags() & ECVF_SetByMask;
            Owned.Applied = Value;
            Cvar->Set(Value, static_cast<EConsoleVariableFlags>(Owned.SetBy));
            if (FMath::IsNearlyEqual(Cvar->GetFloat(), Value)) OwnedDustCvars.Add(Owned);
        };
        OwnCvar(TEXT("r.LocalFogVolume.GlobalStartDistance"), 10.f); // engine's minimum is 10 cm
        OwnCvar(TEXT("r.VolumetricCloud.ApplyFogOnAllPixel"), 1.f);
        OwnCvar(TEXT("r.VolumetricCloud.ApplyFogLate"), 1.f); // fog after cloud reconstruction, including Lumen async
        for (int32 Index = 0; Index < 3; ++Index)
        {
            ULocalFogVolumeComponent* Fog = NewObject<ULocalFogVolumeComponent>(CloseDustVolume,
                FName(*FString::Printf(TEXT("EnclosingDustGust%d"), Index)));
            Fog->SetupAttachment(Root);
            Fog->SetMobility(EComponentMobility::Movable);
            Fog->RadialFogExtinction = 0.f;
            Fog->HeightFogExtinction = 0.f;
            // UI falloff is multiplied by .01, clamped to >=1 by UE. A value1
            // is almost uniform in the sphere; the old120 cut off the sky half.
            Fog->HeightFogFalloff = 1.f;
            Fog->FogPhaseG = .05f;
            Fog->FogAlbedo = FLinearColor(.22f, .20f, .17f);
            Fog->FogEmissive = FLinearColor::Black;
            Fog->FogStartDistance = 0.f;
            Fog->FogSortPriority = 0;
            CloseDustVolume->AddInstanceComponent(Fog);
            Fog->RegisterComponent();
            CloseFogLobes.Add(Fog);
        }
        if (World->GetGameViewport())
        {
            DustViewport = World->GetGameViewport();
            DustLens = SNew(SSaskartaStormLens);
            DustLensWrapper = SNew(SWeakWidget).PossiblyNullContent(DustLens);
            DustViewport->AddViewportWidgetContent(DustLensWrapper.ToSharedRef(), 20);
        }
        UE_LOG(LogSaskartaEarlyStorm, Log, TEXT("surrounding dust: native 20-40m distance fog, three enclosing gusts, transparent grit; no billboard/PP shells"));
    }
    // Texture loading cannot delay the enclosing fog. Resolve this one retained
    // asynchronous lens resource once; no synchronous loads in the pursuit.
    if (!LensGrimeTexture && DustPresentationLoad.IsValid() && DustPresentationLoad->HasLoadCompleted())
    {
        LensGrimeTexture = LensGrimeAsset.Get();
        if (DustLens && LensGrimeTexture) DustLens->Configure(LensGrimeTexture);
    }
    const FVector Wind = FVector(1.f, .35f, 0.f).GetSafeNormal();
    const FVector Across = FVector::CrossProduct(FVector::UpVector, Wind);
    for (int32 Index = 0; Index < CloseFogLobes.Num(); ++Index)
    {
        const float Phase = DustTimeS * .72f + Index * 2.1f;
        const float RadiusM = (Index == 0 ? 65.f : 48.f) * (1.f + .035f * FMath::Sin(Phase));
        // Every sphere contains the camera well inside its radius, in every
        // direction. Turning back or changing pitch cannot reveal clear holes.
        const FVector Position = View + Across * (Index - 1.f) * 1000.f
            + Wind * FMath::Sin(Phase * .8f) * 700.f + FVector(0.f, 0.f, 150.f * FMath::Sin(Phase));
        ULocalFogVolumeComponent* Fog = CloseFogLobes[Index];
        Fog->SetWorldTransform(FTransform(FQuat::Identity, Position,
            FVector(RadiusM * 100.f / ULocalFogVolumeComponent::GetBaseVolumeSize())));
        const float Extinction = (.055f + .018f * (1.f + FMath::Sin(Phase))) * DustEffectAlpha;
        // Native coverage combines radial AND height extinction, so both must
        // exist. These low-strength gusts add depth variation over the continuous
        // EHF medium, rather than being separate clouds with gaps between them.
        if (!FMath::IsNearlyEqual(Fog->RadialFogExtinction, Extinction, .004f))
        {
            Fog->SetRadialFogExtinction(Extinction);
            Fog->SetHeightFogExtinction(Extinction);
        }
    }
}

void USaskartaEarlyStormSubsystem::TickDustLens(float DeltaSeconds, bool bVisible)
{
    if (bVisible)
    {
        DustTimeS += FMath::Clamp(DeltaSeconds, 0.f, .1f);
        if (bIntroActive || bChasing || bDustFading) UpdateDustPresentation(FrontGapM);
    }
    if (!DustLens) return;
    FVector2f WindOnScreen(-1.f, .18f);
    if (APlayerCameraManager* Camera = UGameplayStatics::GetPlayerCameraManager(GetWorld(), 0))
    {
        const FVector ViewWind = Camera->GetCameraRotation().UnrotateVector(FVector(1.f, .35f, 0.f));
        WindOnScreen = FVector2f(ViewWind.Y, -ViewWind.Z + .12f);
        if (WindOnScreen.SizeSquared() < .02f) WindOnScreen = FVector2f(-1.f, .18f);
    }
    DustLens->Update(DustNear * DustEffectAlpha, DustTimeS, WindOnScreen, bVisible);
}

void USaskartaEarlyStormSubsystem::ClearDustPresentation()
{
    if (DustViewport.IsValid() && DustLensWrapper)
        DustViewport->RemoveViewportWidgetContent(DustLensWrapper.ToSharedRef());
    if (DustLens) DustLens->Configure(nullptr);
    DustLensWrapper.Reset();
    DustLens.Reset();
    DustViewport.Reset();
    LensGrimeTexture = nullptr;
    CloseFogLobes.Reset();
    if (IsValid(CloseDustVolume)) CloseDustVolume->Destroy();
    CloseDustVolume = nullptr;
    if (USaskartaLightingDirector* Director = USaskartaLightingDirector::GetLightingDirector(this))
        Director->ReleasePursuitDustFog(this);
    for (const FOwnedDustCvar& Owned : OwnedDustCvars)
    {
        IConsoleVariable* Cvar = IConsoleManager::Get().FindConsoleVariable(*Owned.Name.ToString());
        if (Cvar && (Cvar->GetFlags() & ECVF_SetByMask) == Owned.SetBy
            && FMath::IsNearlyEqual(Cvar->GetFloat(), Owned.Applied))
            Cvar->Set(Owned.Previous, static_cast<EConsoleVariableFlags>(Owned.SetBy));
    }
    OwnedDustCvars.Reset();
    DustNear = 0.f;
    DustProximity = 0.f;
    if (!bBackgroundActive) DustTimeS = 0.f;
    DustEffectAlpha = 0.f;
    LastDustPresentationS = -1.0;
}

void USaskartaEarlyStormSubsystem::UpdateFrontVisual(float GapM)
{
    UWorld* World = GetWorld();
    USaskartaEventRunner* Runner = BoundRunner.Get();
    USplineComponent* Road = Runner ? Runner->GetRoadSpline() : nullptr;
    const USaskartaStoryAsset* Story = Runner ? Runner->GetStory() : nullptr;
    if (!World || !Road || !Story) return;
    if (!IsValid(FrontActor))
    {
        FrontActor = World->SpawnActorDeferred<ASaskartaDustFront>(ASaskartaDustFront::StaticClass(), FTransform::Identity,
            nullptr, nullptr, ESpawnActorCollisionHandlingMethod::AlwaysSpawn);
        if (FrontActor)
        {
            FrontFogLobes.Reset();
            FrontFogExtinction.Reset();
            FrontActor->GetComponents<ULocalFogVolumeComponent>(FrontFogLobes);
            for (ULocalFogVolumeComponent* Fog : FrontFogLobes)
            {
                // The old staggered decorative cloud spheres are retired. The
                // front's dust component now supplies a contiguous world mass.
                FrontFogExtinction.Add(FVector2f::ZeroVector);
                Fog->RadialFogExtinction = 0.f;
                Fog->HeightFogExtinction = 0.f;
            }
            UGameplayStatics::FinishSpawningActor(FrontActor, FTransform::Identity);
        }
    }
    if (!FrontActor) return;
    const float UeM = FSaskartaEventLogic::UeMFromRoadM(Story->RoadMToUeM, FrontRoadM);
    if (UeM < 0.f) return;
    const FVector Centre = Road->GetLocationAtDistanceAlongSpline(UeM * 100.f, ESplineCoordinateSpace::World);
    const FVector Forward = -Road->GetDirectionAtDistanceAlongSpline(UeM * 100.f, ESplineCoordinateSpace::World);
    FrontActor->UpdateFront(Centre, Forward, GapM);
    const float Entry = FMath::Clamp(DustTimeS / 6.f, 0.f, 1.f);
    FrontVisibilityAlpha = Entry * Entry * (3.f - 2.f * Entry);
    if (FMath::Abs(FrontVisibilityAlpha - AppliedFrontVisibilityAlpha) >= .035f
        || (FrontVisibilityAlpha >= 1.f && AppliedFrontVisibilityAlpha < 1.f))
    {
        for (int32 Index = 0; Index < FrontFogLobes.Num(); ++Index)
        {
            FrontFogLobes[Index]->SetRadialFogExtinction(FrontFogExtinction[Index].X * FrontVisibilityAlpha);
            FrontFogLobes[Index]->SetHeightFogExtinction(FrontFogExtinction[Index].Y * FrontVisibilityAlpha);
        }
        AppliedFrontVisibilityAlpha = FrontVisibilityAlpha;
    }
}

void USaskartaEarlyStormSubsystem::TickBackgroundDust(float DeltaSeconds)
{
    if (!bBackgroundActive) return;
    UWorld* World = GetWorld();
    USaskartaEventRunner* Runner = BoundRunner.Get();
    if (!World || !Runner) { EndChase(); return; }
    const FName Flow = Runner->GetFlowState();
    if (Flow == TEXT("Title") || Flow == TEXT("Loading") || Flow == TEXT("Human"))
    {
        EndChase();
        return;
    }
    if (World->IsPaused() || Flow == TEXT("Paused")) { TickDustLens(0.f, false); return; }
    if (bDustFading)
    {
        DustFadeS += FMath::Clamp(DeltaSeconds, 0.f, .1f);
        UpdateDustPresentation(FrontGapM);
        TickDustLens(DeltaSeconds, true);
        if (DustFadeS >= 4.5f)
        {
            bDustFading = false;
            ClearDustPresentation();
            if (bOwnsWeather)
            {
                if (USaskartaLightingDirector* Director = USaskartaLightingDirector::GetLightingDirector(this))
                    if (FMath::IsNearlyEqual(Director->GetStormOverride(), LastStormIntensity))
                        Director->SetStormOverride(PreviousStormIntensity);
                bOwnsWeather = false;
            }
            if (bOwnsShellSuppression)
            {
                if (USaskartaStormShellsSubsystem* Shells = USaskartaStormShellsSubsystem::GetStormShells(this))
                    Shells->SetSuppressed(bPreviousShellSuppression);
                bOwnsShellSuppression = false;
            }
        }
    }
    else DustTimeS += FMath::Clamp(DeltaSeconds, 0.f, .1f);
    // No further catch/scoring occurs. Keep the front's final exact world anchor;
    // driving away increases its separation. Three grounded fog masses remain
    // at that world anchor after the enclosing medium has cleared.
    UpdateFrontVisual(FMath::Max(1.f, Runner->GetRoadM() - FrontRoadM));
}

TStatId USaskartaEarlyStormSubsystem::GetStatId() const
{
    RETURN_QUICK_DECLARE_CYCLE_STAT(USaskartaEarlyStormSubsystem, STATGROUP_Tickables);
}

void USaskartaEarlyStormSubsystem::ReleaseDrive()
{
    if (APlayerController* PC = DriveController.Get())
        if (bOwnsMoveLock) PC->SetIgnoreMoveInput(false);
    bOwnsMoveLock = false;
    if (ACharacter* Carrier = DriveCarrier.Get())
    {
        Carrier->ConsumeMovementInputVector();
        if (UCharacterMovementComponent* Movement = Carrier->GetCharacterMovement())
        {
            Movement->MaxWalkSpeed = PreviousMaxSpeed;
            Movement->MaxAcceleration = PreviousAcceleration;
            Movement->BrakingDecelerationWalking = PreviousBraking;
            Movement->bOrientRotationToMovement = bPreviousOrientToMovement;
        }
        SaskartaEarlyStorm::SetCarrierNumber(Carrier, TEXT("MoveX"), 0.0);
        SaskartaEarlyStorm::SetCarrierNumber(Carrier, TEXT("MoveY"), 0.0);
        SaskartaEarlyStorm::SetCarrierNumber(Carrier, TEXT("Steer"), 0.0);
        SaskartaEarlyStorm::SetCarrierNumber(Carrier, TEXT("Throttle"), 0.0);
        SaskartaEarlyStorm::SetCarrierNumber(Carrier, TEXT("InputScale"), 0.0);
    }
    DriveController.Reset();
    DriveCarrier.Reset();
}

bool USaskartaEarlyStormSubsystem::UpdateCarrierForPursuit(ACharacter* Carrier)
{
    if (!bChasing || !Carrier || Carrier != DriveCarrier.Get()) return false;
    UCharacterMovementComponent* Move = Carrier->GetCharacterMovement();
    if (!Move) return false;
    if (const USaskartaPowerSubsystem* Power = GetWorld()->GetSubsystem<USaskartaPowerSubsystem>();
        Power && Power->IsLimp())
    {
        SaskartaEarlyStorm::SetCarrierNumber(Carrier, TEXT("Throttle"), 0.0);
        Carrier->ConsumeMovementInputVector();
        USaskartaPowerSubsystem::ApplyDriveLimits(Carrier, 0.f, false);
        return true;
    }
    const USaskartaMotorResonanceSubsystem* Motor = GetWorld()->GetSubsystem<USaskartaMotorResonanceSubsystem>();
    if (!Motor || !Motor->CanAcceptInput())
    {
        SaskartaEarlyStorm::SetCarrierNumber(Carrier, TEXT("Throttle"), 0.0);
        Carrier->ConsumeMovementInputVector();
        Move->StopMovementImmediately();
        return true;
    }
    Move->MaxWalkSpeed = FMath::Max(DriveSpeedCmS, 50.f);
    Move->MaxAcceleration = 650.f;
    Move->BrakingDecelerationWalking = 320.f;
    Move->bOrientRotationToMovement = false;
    // Keep normal engine animation/audio informed, while physical steering belongs
    // to this encounter and A/D belong to the motor balance prompts.
    SaskartaEarlyStorm::SetCarrierNumber(Carrier, TEXT("Throttle"), 1.0);
    SaskartaEarlyStorm::SetCarrierNumber(Carrier, TEXT("MoveX"), 0.0);
    SaskartaEarlyStorm::SetCarrierNumber(Carrier, TEXT("Steer"), 0.0);
    SaskartaEarlyStorm::SetCarrierNumber(Carrier, TEXT("TurnRateNow"), 0.0);
    SaskartaEarlyStorm::SetCarrierNumber(Carrier, TEXT("InputScale"), 0.0);
    SaskartaEarlyStorm::SetCarrierNumber(Carrier, TEXT("StuckTime"), 0.0);
    return true;
}

void USaskartaEarlyStormSubsystem::Tick(float DeltaSeconds)
{
    Super::Tick(DeltaSeconds);
    UWorld* World = GetWorld();
    if (!World) return;
    TickBackgroundDust(DeltaSeconds);
    if (bIntroActive)
    {
        if (BoundRunner.IsValid()) BoundRunner->UpdateStormPanic(0.f, false, false);
        StopProximityRattle();
        StopStormAlarm();
        UpdateIntroFront();
        const USaskartaEventRunner* Runner = BoundRunner.Get();
        TickDustLens(DeltaSeconds, !World->IsPaused() && Runner
            && Runner->GetFlowState() != TEXT("Paused") && Runner->GetCinematicPlaybackSeconds() >= 0.f);
        return;
    }
    if (bFailed)
    {
        const double Elapsed = FPlatformTime::Seconds() - RescueStartedRealS;
        if (!bRescueRestored && Elapsed >= 1.2) CompleteRescue();
        if (bRescueRestored && FPlatformTime::Seconds() - RescueSucceededRealS >= 3.0)
        {
            HideFailure();
            bFailed = false;
            bRestoredPursuit = false;
            BeginChase(true);
        }
        return;
    }
    if (!bChasing || World->IsPaused())
    {
        if (!bBackgroundActive || !bDustFading || World->IsPaused()) TickDustLens(0.f, false);
        if (BoundRunner.IsValid()) BoundRunner->UpdateStormPanic(0.f, false, false);
        StopProximityRattle();
        StopStormAlarm();
        return;
    }
    USaskartaEventRunner* Runner = BoundRunner.Get();
    APlayerController* PC = DriveController.Get();
    ACharacter* Carrier = DriveCarrier.Get();
    if (!Runner || !PC || !Carrier || PC->GetPawn() != Carrier)
    {
        TickDustLens(0.f, false);
        if (Runner) Runner->UpdateStormPanic(0.f, false, false);
        StopProximityRattle();
        StopStormAlarm();
        return;
    }
    if (Runner->IsVoiceBusy())
    {
        StopProximityRattle();
        StopStormAlarm();
    }
    const USaskartaMotorResonanceSubsystem* Motor = World->GetSubsystem<USaskartaMotorResonanceSubsystem>();
    if (!Motor || !Motor->CanAcceptInput())
    {
        TickDustLens(0.f, false);
        Runner->UpdateStormPanic(FrontGapM, false, false);
        StopProximityRattle();
        StopStormAlarm();
        LastPollS = World->GetTimeSeconds();
        Carrier->ConsumeMovementInputVector();
        Carrier->GetCharacterMovement()->StopMovementImmediately();
        return;
    }
    if (!FMath::IsFinite(DeltaSeconds) || DeltaSeconds > .5f)
    {
        // Resonance rejects this frame too. A render/compile stall must not
        // simulate driving or dust loss while no timed motor input can count.
        LastPollS = World->GetTimeSeconds();
        TickDustLens(0.f, true);
        Carrier->ConsumeMovementInputVector();
        Carrier->GetCharacterMovement()->StopMovementImmediately();
        return;
    }
    // PC.ClosePause resets input flags in PIE; reinstate only our own missing lock.
    if (bOwnsMoveLock && !PC->IsMoveInputIgnored()) PC->SetIgnoreMoveInput(true);
    if (const USaskartaPowerSubsystem* Power = World->GetSubsystem<USaskartaPowerSubsystem>();
        Power && Power->IsLimp())
    {
        // The front still advances while the empty carrier recharges. Keep its
        // visual entry clock alive behind the same flow/pause/input gates.
        const FName DustFlow = Runner->GetFlowState();
        TickDustLens(DeltaSeconds, DustFlow == SaskartaEarlyStorm::Playing || DustFlow == SaskartaEarlyStorm::CarrierFlow);
        DriveSpeedCmS = 0.f;
        UpdateCarrierForPursuit(Carrier);
        return;
    }
    const FName Flow = Runner->GetFlowState();
    if (Flow != SaskartaEarlyStorm::Playing && Flow != SaskartaEarlyStorm::CarrierFlow)
    {
        TickDustLens(0.f, false);
        return;
    }
    TickDustLens(DeltaSeconds, true);
    USplineComponent* Spline = Runner->GetRoadSpline();
    const USaskartaStoryAsset* Story = Runner->GetStory();
    if (!Spline || !Story) return;
    const float RoadM = Runner->GetRoadM();
    const float UeM = FSaskartaEventLogic::UeMFromRoadM(Story->RoadMToUeM, RoadM);
    const float NextUeM = FSaskartaEventLogic::UeMFromRoadM(Story->RoadMToUeM, RoadM + 5.f);
    const float CmPerRoadM = FMath::Clamp(FMath::Abs(NextUeM - UeM) * 20.f, 20.f, 500.f);
    const float Multiplier = Motor ? Motor->GetDriveMultiplier() : 0.9f;
    const float DesiredSpeed = SaskartaEarlyStorm::BaseRoadSpeedMps * CmPerRoadM * Multiplier;
    DriveSpeedCmS = FMath::FInterpConstantTo(DriveSpeedCmS, DesiredSpeed, DeltaSeconds, 420.f);
    const float NearKey = Spline->FindInputKeyClosestToWorldLocation(Carrier->GetActorLocation());
    const float NearCm = Spline->GetDistanceAlongSplineAtSplineInputKey(NearKey);
    const float LookAheadCm = FMath::Clamp(DriveSpeedCmS * 0.8f, 250.f, 900.f);
    const float TargetCm = FMath::Max(0.f, NearCm - LookAheadCm);
    FVector Target = Spline->GetLocationAtDistanceAlongSpline(TargetCm, ESplineCoordinateSpace::World);
    const FVector Forward = -Spline->GetDirectionAtDistanceAlongSpline(TargetCm, ESplineCoordinateSpace::World);
    // Pass the old carrier on the shoulder; its failed XY position stays exact.
    float OffsetCm = 0.f;
    for (const FSaskartaDustWreckSave& Wreck : Wrecks)
    {
        const float Separation = FMath::Abs(Wreck.RoadM - RoadM);
        OffsetCm = FMath::Max(OffsetCm, 320.f * FMath::Clamp((28.f - Separation) / 16.f, 0.f, 1.f));
    }
    Target += FVector::CrossProduct(FVector::UpVector, Forward).GetSafeNormal2D() * OffsetCm;
    const FVector Direction = (Target - Carrier->GetActorLocation()).GetSafeNormal2D();
    if (Direction.IsNearlyZero()) return;
    FRotator Facing = Carrier->GetActorRotation();
    Facing.Yaw = FMath::FInterpTo(Facing.Yaw, Facing.Yaw + FMath::FindDeltaAngleDegrees(Facing.Yaw, Direction.Rotation().Yaw), DeltaSeconds, 5.f);
    Carrier->SetActorRotation(Facing);
    UpdateCarrierForPursuit(Carrier);
    Carrier->ConsumeMovementInputVector();
    Carrier->AddMovementInput(Direction, 1.f, true);
}

void USaskartaEarlyStormSubsystem::HandleWritingRun(UWorld* World, USaskartaSaveGame* Save)
{
    if (World == GetWorld() && Save) Save->DustWrecks = Wrecks;
}

void USaskartaEarlyStormSubsystem::HandleRestoredRun(UWorld* World, USaskartaSaveGame* Save)
{
    if (World != GetWorld() || !Save) return;
    EndChase();
    Wrecks = Save->DustWrecks;
    RebuildWrecks();
    bRequested = false;
    bRestoredPursuit = Save->CheckpointId == SaskartaEarlyStorm::PursuitCheckpointId;
    if (bRestoredPursuit) PursuitCheckpoint = DuplicateObject<USaskartaSaveGame>(Save, this);
    if (Save->CheckpointId == TEXT("CP_EARLY_DUST_CLEAR"))
    {
        // This checkpoint has crossed the channel. Rebuild a background storm
        // behind it, never a chase, without inventing a new saved catch position.
        FrontRoadM = SaskartaEarlyStorm::ShelterRoadM - SaskartaEarlyStorm::InitialGapM;
        FrontGapM = SaskartaEarlyStorm::InitialGapM;
        bBackgroundActive = true;
    }
}

void USaskartaEarlyStormSubsystem::RebuildWrecks()
{
    UWorld* World = GetWorld();
    if (!World) return;
    for (ASaskartaDustWreck* Wreck : WreckActors) if (IsValid(Wreck)) Wreck->Destroy();
    WreckActors.Reset();
    if (Wrecks.IsEmpty()) return;
    // CP4 restores Traveller possession before OnRestoredRun. Clone only the
    // already-resident carrier class, never the currently possessed character.
    UClass* CarrierClass = FindObject<UClass>(nullptr,
        TEXT("/Game/SaskartaGaea/Characters/Carrier/BP_Saskarta_Carrier.BP_Saskarta_Carrier_C"));
    ACharacter* Carrier = CarrierClass ? Cast<ACharacter>(UGameplayStatics::GetActorOfClass(World, CarrierClass)) : nullptr;
    if (!Carrier) return; // Poll retries when the actual carrier becomes resident.
    for (const FSaskartaDustWreckSave& Saved : Wrecks)
    {
        ASaskartaDustWreck* Wreck = World->SpawnActor<ASaskartaDustWreck>();
        if (Wreck)
        {
            Wreck->BuildFromCarrier(Carrier, Saved.CarrierPose);
            WreckActors.Add(Wreck);
        }
    }
}

void USaskartaEarlyStormSubsystem::FailPursuit()
{
    UWorld* World = GetWorld();
    APlayerController* PC = DriveController.Get();
    ACharacter* Carrier = DriveCarrier.Get();
    USaskartaEventRunner* Runner = BoundRunner.Get();
    if (!World || !PC || !Carrier || !Runner || bFailed || RecoveryCheckpoints.IsEmpty()) return;
    FSaskartaDustWreckSave Lost;
    Lost.CarrierPose = Carrier->GetActorTransform();
    Lost.RoadM = Runner->GetRoadM();
    Wrecks.Add(Lost);
    // Choose a real snapshot roughly 75 m before the catch, or the encounter
    // entrance if the player was caught before enough road had been travelled.
    PursuitCheckpoint = RecoveryCheckpoints[0];
    for (USaskartaSaveGame* Snapshot : RecoveryCheckpoints)
        if (Snapshot && Snapshot->CheckpointRoadM <= Lost.RoadM - 75.f) PursuitCheckpoint = Snapshot;
    PursuitCheckpoint->DustWrecks = Wrecks;
    UGameplayStatics::SaveGameToSlot(PursuitCheckpoint, USaskartaSaveGame::RunSlot, 0);
    bFailed = true;
    bRescueRestored = false;
    RescueStartedRealS = FPlatformTime::Seconds();
    RescueSucceededRealS = -1.0;
    EndChase();
    Runner->StopAll();
    if (USaskartaRadioStation* Radio = World->GetSubsystem<USaskartaRadioStation>())
    {
        Radio->NotifyPaused(true);
        bOwnsRadioPause = true;
    }
    Carrier->GetCharacterMovement()->StopMovementImmediately();
    SaskartaEarlyStorm::SetFlow(PC, TEXT("PackageRescue"));
    bOwnsPause = PC->SetPause(true) || bOwnsPause;
    RescueWidget = CreateWidget<USaskartaPackageRescueWidget>(PC);
    if (RescueWidget)
    {
        RescueWidget->AddToViewport(900);
        FInputModeUIOnly Input;
        Input.SetWidgetToFocus(RescueWidget->TakeWidget());
        PC->SetInputMode(Input);
        PC->bShowMouseCursor = false;
    }
    UE_LOG(LogSaskartaEarlyStorm, Log, TEXT("carrier lost at road %.1f; package rescue returns to %.1f; wrecks %d"),
        Lost.RoadM, PursuitCheckpoint->CheckpointRoadM, Wrecks.Num());
}

bool USaskartaEarlyStormSubsystem::RestoreRecoveryFuel(bool& bRefueled)
{
    bRefueled = false;
    USaskartaPowerSubsystem* Power = GetWorld() ? GetWorld()->GetSubsystem<USaskartaPowerSubsystem>() : nullptr;
    if (!Power || !PursuitCheckpoint ||
        PursuitCheckpoint->CheckpointId != SaskartaEarlyStorm::PursuitCheckpointId) return false;
    const float Before = Power->GetCharge();
    const float Minimum = Power->GetCore().Tuning.LimpExitPercent;
    // SetCharge uses the canonical load rule to release the saved empty-cell latch.
    // Keep a healthy saved reserve; never change the original checkpoint or invent motion at zero.
    bRefueled = Before < Minimum || Power->IsLimp();
    Power->SetCharge(FMath::Max(Before, Minimum));
    const bool bReady = !Power->IsLimp() && Power->GetCharge() >= Minimum;
    UE_LOG(LogSaskartaEarlyStorm, Log, TEXT("recovered package fuel reserve %.1f%% -> %.1f%%; ready %d"),
        Before, Power->GetCharge(), bReady ? 1 : 0);
    return bReady;
}

void USaskartaEarlyStormSubsystem::CompleteRescue()
{
    USaskartaEventRunner* Runner = BoundRunner.Get();
    APlayerController* PC = GetWorld() ? GetWorld()->GetFirstPlayerController() : nullptr;
    if (!Runner || !PC || !PursuitCheckpoint) { ReturnToTitle(); return; }
    if (!Runner->RestoreCheckpointSnapshot(PursuitCheckpoint))
    {
        if (RescueWidget) RescueWidget->SetRecoveryFailed();
        ReturnToTitle();
        return;
    }
    bool bRefueled = false;
    if (!RestoreRecoveryFuel(bRefueled))
    {
        if (RescueWidget) RescueWidget->SetRecoveryFailed();
        ReturnToTitle();
        return;
    }
    bRescueRestored = true;
    RescueSucceededRealS = FPlatformTime::Seconds();
    SaskartaEarlyStorm::SetFlow(PC, TEXT("PackageRescue"));
    bOwnsPause = PC->SetPause(true) || bOwnsPause;
    if (RescueWidget) RescueWidget->SetSuccessful(bRefueled);
}

void USaskartaEarlyStormSubsystem::HideFailure()
{
    if (!bFailed && !RescueWidget && !bOwnsPause && !bOwnsRadioPause) return;
    if (RescueWidget) { RescueWidget->RemoveFromParent(); RescueWidget = nullptr; }
    if (bOwnsRadioPause && GetWorld())
        if (USaskartaRadioStation* Radio = GetWorld()->GetSubsystem<USaskartaRadioStation>()) Radio->NotifyPaused(false);
    bOwnsRadioPause = false;
    APlayerController* PC = GetWorld() ? GetWorld()->GetFirstPlayerController() : nullptr;
    if (PC)
    {
        if (bOwnsPause) PC->SetPause(false);
        PC->SetInputMode(FInputModeGameOnly());
        PC->bShowMouseCursor = false;
        PC->FlushPressedKeys();
        if (bFailed) SaskartaEarlyStorm::SetFlow(PC, SaskartaEarlyStorm::Playing);
    }
    bOwnsPause = false;
}

void USaskartaEarlyStormSubsystem::ReturnToTitle()
{
    HideFailure();
    bFailed = false;
    EndChase();
    if (APlayerController* PC = GetWorld() ? GetWorld()->GetFirstPlayerController() : nullptr)
        if (UFunction* Quit = PC->FindFunction(TEXT("QuitToTitle"))) PC->ProcessEvent(Quit, nullptr);
}

void USaskartaEarlyStormSubsystem::Poll()
{
    UWorld* World = GetWorld();
    if (!World)
    {
        return;
    }
    USaskartaEventRunner* Runner = World->GetSubsystem<USaskartaEventRunner>();
    USaskartaPowerSubsystem* Power = World->GetSubsystem<USaskartaPowerSubsystem>();
    if (!Runner || !Power)
    {
        return;
    }
    BindRunner(Runner);
    const float RoadM = Runner->GetRoadM();
    const FName Flow = Runner->GetFlowState();
    const bool bPlaying = Flow == SaskartaEarlyStorm::Playing || Flow == SaskartaEarlyStorm::CarrierFlow;
    if (bFailed) return;
    if (!Wrecks.IsEmpty() && WreckActors.IsEmpty() && World->GetFirstPlayerController() && World->GetFirstPlayerController()->GetPawn()) RebuildWrecks();
    if (bRestoredPursuit && bPlaying && !Runner->IsCinematicActive() && !Runner->IsHoldingInput())
    {
        bRestoredPursuit = false;
        bRequested = true;
        BeginChase(true);
        return;
    }
    if (bChasing)
    {
        if (Flow == TEXT("Title") || Flow == TEXT("Loading") || Flow == TEXT("Human"))
        {
            EndChase();
            bRequested = false;
            return;
        }
        if (RoadM >= SaskartaEarlyStorm::ShelterRoadM)
        {
            EndChase(true);
            USaskartaSaveGame* Cleared = Runner->CreateCheckpointSnapshot(TEXT("CP_EARLY_DUST_CLEAR"), true);
            if (Cleared) UGameplayStatics::SaveGameToSlot(Cleared, USaskartaSaveGame::RunSlot, 0);
            return;
        }
        USaskartaMotorResonanceSubsystem* Motor = World->GetSubsystem<USaskartaMotorResonanceSubsystem>();
        if (!bPlaying || !Motor || !Motor->CanAcceptInput())
        {
            Runner->UpdateStormPanic(FrontGapM, false, false);
            StopProximityRattle();
            StopStormAlarm();
            LastPollS = World->GetTimeSeconds();
            if (ACharacter* Carrier = DriveCarrier.Get())
            {
                Carrier->ConsumeMovementInputVector();
                Carrier->GetCharacterMovement()->StopMovementImmediately();
            }
            return;
        }
        const double NowS = World->GetTimeSeconds();
        const double ElapsedS = LastPollS < 0.0 ? SaskartaEarlyStorm::PollS : NowS - LastPollS;
        LastPollS = NowS;
        if (!FMath::IsFinite(ElapsedS) || ElapsedS > .5 || ElapsedS < 0.0)
        {
            // Match the motor's rejected >0.5s frame. Refresh presentation at
            // the current world position, but award the dust no unseen progress
            // and perform no catch on a frame the player could not crank.
            FrontGapM = RoadM - FrontRoadM;
            Motor->SetPursuitGap(FrontGapM);
            ApplyWeather(FrontGapM);
            Runner->UpdateStormPanic(FrontGapM, true, Motor->IsInputWarningActive() || IsStormAlarmBusy());
            if (ACharacter* Carrier = DriveCarrier.Get())
            {
                Carrier->ConsumeMovementInputVector();
                Carrier->GetCharacterMovement()->StopMovementImmediately();
            }
            return;
        }
        const float DeltaS = static_cast<float>(ElapsedS);
        FrontRoadM += FrontSpeedMps * DeltaS;
        FrontGapM = RoadM - FrontRoadM;
        Motor->SetPursuitGap(FrontGapM);
        if (FrontGapM <= 0.f)
        {
            FailPursuit();
            return;
        }
        ApplyWeather(FrontGapM);
        TryPlayProximityRattle();
        Runner->UpdateStormPanic(FrontGapM, true, Motor->IsInputWarningActive() || IsStormAlarmBusy());
        UpdateStormAlarm(Motor->IsInputWarningActive());
        // A small rolling window restores the state actually reached before the
        // loss, including radio, power and route progress, rather than teleporting
        // the exhausted current carrier backwards.
        if (RoadM >= LastRecoveryRoadM + 10.f)
        {
            if (USaskartaSaveGame* Recovery = Runner->CreateCheckpointSnapshot(SaskartaEarlyStorm::PursuitCheckpointId, true))
            {
                RecoveryCheckpoints.Add(Recovery);
                if (RecoveryCheckpoints.Num() > 12) RecoveryCheckpoints.RemoveAt(0);
                LastRecoveryRoadM = RoadM;
            }
        }
        return;
    }

    if (bRequested && !bChasing && bPlaying && RequestedAtS >= 0.0
        && World->GetTimeSeconds() - RequestedAtS > 20.0
        && !Runner->IsCinematicActive()
        && RoadM < SaskartaEarlyStorm::ShelterRoadM)
    {
        UE_LOG(LogSaskartaEarlyStorm, Warning,
            TEXT("dust cinematic did not finish after 20 s; continuing with playable chase"));
        BeginChase();
        return;
    }
    if (bRequested || !bPlaying || Runner->IsCinematicActive()
        || Runner->GetSpeedMps() <= 0.5f
        || RoadM < SaskartaEarlyStorm::StartRoadM || RoadM >= SaskartaEarlyStorm::ShelterRoadM)
    {
        return;
    }
    // Old saves may already carry the fired intro beat; resume at a fresh encounter checkpoint.
    if (Runner->HasBeatFired(SaskartaEarlyStorm::StormBeat))
    {
        bRequested = true;
        BeginChase();
    }
    else if (Runner->FireBeat(SaskartaEarlyStorm::StormBeat))
    {
        bRequested = true;
        RequestedAtS = World->GetTimeSeconds();
        UE_LOG(LogSaskartaEarlyStorm, Log, TEXT("moving carrier queued radioactive dust front at road %.0f m"), RoadM);
    }
    else
    {
        // A missing story import must not remove the playable encounter as well.
        bRequested = true;
        UE_LOG(LogSaskartaEarlyStorm, Warning, TEXT("dust beat unavailable; starting playable chase at road %.0f m"), RoadM);
        BeginChase();
    }
}
