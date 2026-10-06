#include "SaskartaMotorResonanceAudio.h"

#include "Components/AudioComponent.h"
#include "Engine/AssetManager.h"
#include "Engine/StreamableManager.h"
#include "Engine/World.h"
#include "Kismet/GameplayStatics.h"
#include "Sound/SoundBase.h"

namespace SaskartaMotorAudio
{
    // All are existing authored local assets. The steering samples differ in
    // motor pitch and stop ticks, making left/right audible without an alarm.
    static const FSoftObjectPath Paths[] = {
        FSoftObjectPath(TEXT("/Game/SaskartaGaea/Audio/Carrier/SFX_Carrier_Mast_Tick_01.SFX_Carrier_Mast_Tick_01")),
        FSoftObjectPath(TEXT("/Game/SaskartaGaea/GameFlow/Audio/SFX_Carrier_Contactor.SFX_Carrier_Contactor")),
        FSoftObjectPath(TEXT("/Game/SaskartaGaea/Audio/Carrier/SFX_Carrier_Steer_Servo_L_01.SFX_Carrier_Steer_Servo_L_01")),
        FSoftObjectPath(TEXT("/Game/SaskartaGaea/Audio/Carrier/SFX_Carrier_Steer_Servo_R_01.SFX_Carrier_Steer_Servo_R_01")),
        FSoftObjectPath(TEXT("/Game/SaskartaGaea/Audio/Carrier/SFX_Carrier_Motor_Idle_Loop.SFX_Carrier_Motor_Idle_Loop"))
    };
    constexpr double BeatLeadS = 0.35;
    constexpr double BalanceLeadS = 0.7;
}

void USaskartaMotorResonanceAudio::Initialize(UWorld* InWorld)
{
    Shutdown();
    AudioWorld = InWorld;
    Sounds.SetNum(static_cast<int32>(ESound::Count));
    if (!InWorld || !InWorld->IsGameWorld() || !UAssetManager::IsInitialized()) return;
    TArray<FSoftObjectPath> Requested;
    for (const FSoftObjectPath& Path : SaskartaMotorAudio::Paths) Requested.Add(Path);
    // No completion callback can play a stale cue after a close or world change.
    // Retain this handle for the helper lifetime, avoiding per-press loads.
    LoadHandle = UAssetManager::GetStreamableManager().RequestAsyncLoad(Requested, FStreamableDelegate());
}

bool USaskartaMotorResonanceAudio::RefreshAssets()
{
    if (!LoadHandle.IsValid() || !LoadHandle->HasLoadCompleted()) return false;
    for (int32 Index = 0; Index < static_cast<int32>(ESound::Count); ++Index)
        if (!Sounds[Index]) Sounds[Index] = Cast<USoundBase>(SaskartaMotorAudio::Paths[Index].ResolveObject());
    return true; // A missing optional sound is skipped individually.
}

void USaskartaMotorResonanceAudio::StopVoice(TObjectPtr<UAudioComponent>& Voice, bool bDestroy)
{
    if (IsValid(Voice))
    {
        if (Voice->IsPlaying()) Voice->Stop();
        if (bDestroy) Voice->DestroyComponent();
    }
    if (bDestroy || !IsValid(Voice)) Voice = nullptr;
}

void USaskartaMotorResonanceAudio::Silence()
{
    StopVoice(WarningVoice);
    StopVoice(ResultVoice);
    StopVoice(FlywheelVoice);
}

void USaskartaMotorResonanceAudio::BeginSession()
{
    EndSession();
    bSession = true;
    WarnedBeat = -1;
    WarnedBalance = -1;
    LastFeedbackUntil = -1.0;
    LastFeedback = FSaskartaMotorResonanceLogic::EFeedback::None;
}

void USaskartaMotorResonanceAudio::EndSession()
{
    bSession = false;
    bAudible = false;
    Silence();
}

void USaskartaMotorResonanceAudio::Shutdown()
{
    EndSession();
    StopVoice(WarningVoice, true);
    StopVoice(ResultVoice, true);
    StopVoice(FlywheelVoice, true);
    if (LoadHandle.IsValid() && !LoadHandle->HasLoadCompleted()) LoadHandle->CancelHandle();
    LoadHandle.Reset();
    Sounds.Reset();
    AudioWorld.Reset();
}

void USaskartaMotorResonanceAudio::Play(ESound Sound, float Volume, float Pitch, bool bResult)
{
    UWorld* World = AudioWorld.Get();
    if (!bSession || !bAudible || !World || World->IsPaused() || !RefreshAssets()) return;
    USoundBase* Asset = Sounds[static_cast<int32>(Sound)];
    if (!Asset) return;
    TObjectPtr<UAudioComponent>& Voice = bResult ? ResultVoice : WarningVoice;
    // Keep three bounded voices for this helper's lifetime. A cue previously
    // destroyed and registered a UObject every beat, adding allocation/GC work
    // during the pursuit. Changing its sound preserves the asset's audio class.
    StopVoice(Voice);
    if (!IsValid(Voice))
        Voice = UGameplayStatics::CreateSound2D(World, Asset, Volume, Pitch, 0.f, nullptr, false, false);
    if (Voice)
    {
        Voice->SetSound(Asset);
        Voice->SetVolumeMultiplier(Volume);
        Voice->SetPitchMultiplier(Pitch);
        Voice->SetUISound(false);
        Voice->Play(); // Preserve the asset's authored class, submix and volume.
    }
}

void USaskartaMotorResonanceAudio::PlayFeedback(const FSaskartaMotorResonanceLogic& Core)
{
    using E = FSaskartaMotorResonanceLogic::EFeedback;
    if (!bSession || !bAudible || Core.bSuppressed || !Core.IsActive() || Core.Feedback == E::None) return;
    if (Core.FeedbackUntilS == LastFeedbackUntil && Core.Feedback == LastFeedback) return;
    LastFeedbackUntil = Core.FeedbackUntilS;
    LastFeedback = Core.Feedback;
    switch (Core.Feedback)
    {
    case E::Perfect: Play(ESound::Engage, 0.20f, 1.08f, true); break;
    case E::Good: Play(ESound::Engage, 0.16f, 0.98f, true); break;
    case E::Balanced: Play(ESound::Engage, 0.14f, 1.20f, true); break;
    // A short motor bog, not another electronic alarm. Same result voice keeps
    // repeated early/late input from stacking noise over radio dialogue.
    case E::Early:
    case E::Late:
    case E::Miss:
    case E::WrongSide: Play(ESound::LeftValve, 0.09f, 0.72f, true); break;
    default: break;
    }
}

void USaskartaMotorResonanceAudio::UpdateCues(const FSaskartaMotorResonanceLogic& Core, bool bAllowed)
{
    if (!bSession) return;
    bAudible = bAllowed && Core.IsActive() && !Core.bSuppressed && !Core.bComplete &&
        AudioWorld.IsValid() && !AudioWorld->IsPaused();
    const double UntilBeat = Core.NextBeatS - Core.ElapsedS;
    const double UntilBalance = Core.NextBalanceS - Core.ElapsedS;
    if (!bAudible)
    {
        Silence();
        // Consume cues already entered while hidden; resume never catches up
        // with a warning/result burst, but future cues still sound normally.
        if (UntilBeat <= SaskartaMotorAudio::BeatLeadS) WarnedBeat = Core.CompletedBeats;
        if (UntilBalance <= SaskartaMotorAudio::BalanceLeadS) WarnedBalance = Core.BalanceIndex;
        LastFeedbackUntil = Core.FeedbackUntilS;
        LastFeedback = Core.Feedback;
        return;
    }
    // Balance warnings take priority when the two lead windows overlap.
    if (!Core.bBalanceJudged && UntilBalance > FSaskartaMotorResonanceLogic::BalanceWindowS &&
        UntilBalance <= SaskartaMotorAudio::BalanceLeadS && WarnedBalance != Core.BalanceIndex)
    {
        WarnedBalance = Core.BalanceIndex;
        Play(Core.WantsLeft() ? ESound::LeftValve : ESound::RightValve, 0.16f,
            Core.WantsLeft() ? 0.94f : 1.10f, false);
        if (UntilBeat <= SaskartaMotorAudio::BeatLeadS) WarnedBeat = Core.CompletedBeats;
    }
    else if (!Core.bBeatJudged && UntilBeat > FSaskartaMotorResonanceLogic::GoodWindowS &&
             UntilBeat <= SaskartaMotorAudio::BeatLeadS && WarnedBeat != Core.CompletedBeats)
    {
        WarnedBeat = Core.CompletedBeats;
        Play(ESound::Lead, 0.12f, 0.86f, false);
    }
    PlayFeedback(Core); // Includes automatic misses produced by Advance().
}

void USaskartaMotorResonanceAudio::SetCrank(float Effort01, float Stability01)
{
    UWorld* World = AudioWorld.Get();
    if (!bSession || !bAudible || !World || World->IsPaused() || !FMath::IsFinite(Effort01) || Effort01 <= 0.f)
    {
        StopVoice(FlywheelVoice);
        return;
    }
    if (!RefreshAssets()) return;
    USoundBase* Asset = Sounds[static_cast<int32>(ESound::Flywheel)];
    if (!Asset) return;
    const float Effort = FMath::Clamp(Effort01, 0.f, 1.f);
    const float Stability = FMath::IsFinite(Stability01) ? FMath::Clamp(Stability01, 0.f, 1.f) : 0.f;
    const float Volume = 0.025f + 0.03f * Effort;
    const float Pitch = 0.62f + 0.32f * Effort + 0.06f * Stability;
    if (!IsValid(FlywheelVoice))
    {
        FlywheelVoice = UGameplayStatics::CreateSound2D(World, Asset, Volume, Pitch, 0.f, nullptr, false, false);
        if (FlywheelVoice)
        {
            FlywheelVoice->SetUISound(false);
            // Fade level multiplies the component's already-small volume.
            FlywheelVoice->FadeIn(0.12f, 1.f);
        }
    }
    else
    {
        FlywheelVoice->SetVolumeMultiplier(Volume);
        FlywheelVoice->SetPitchMultiplier(Pitch);
        if (!FlywheelVoice->IsPlaying()) FlywheelVoice->FadeIn(0.12f, 1.f);
    }
}
