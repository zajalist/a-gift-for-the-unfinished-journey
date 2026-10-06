#include "SaskartaChargeAudio.h"

#include "Components/AudioComponent.h"
#include "Engine/AssetManager.h"
#include "Kismet/GameplayStatics.h"
#include "Sound/SoundBase.h"

namespace SaskartaChargeAudio
{
    static const TCHAR* Paths[] = {
        TEXT("/Game/SaskartaGaea/Audio/Story/SFX_RelaySwitch.SFX_RelaySwitch"),
        TEXT("/Game/SaskartaGaea/Audio/Story/SFX_RelayClunk.SFX_RelayClunk"),
        TEXT("/Game/SaskartaGaea/Audio/Ambience2/AMB_Waystation_CradleHum_Loop.AMB_Waystation_CradleHum_Loop"),
        TEXT("/Game/SaskartaGaea/Audio/Storm/AMB_Storm_PowerlineBuzz_Loop.AMB_Storm_PowerlineBuzz_Loop"),
        TEXT("/Game/SaskartaGaea/Audio/Radio/SFX_Radio_Tune_Click_01.SFX_Radio_Tune_Click_01"),
        TEXT("/Game/SaskartaGaea/Audio/Radio/SFX_Radio_Tune_Click_02.SFX_Radio_Tune_Click_02"),
        TEXT("/Game/SaskartaGaea/Audio/Radio/SFX_Radio_Tune_Click_03.SFX_Radio_Tune_Click_03"),
        TEXT("/Game/SaskartaGaea/Audio/Radio/SFX_Radio_Tune_Click_04.SFX_Radio_Tune_Click_04"),
        TEXT("/Game/SaskartaGaea/Audio/Storm/SFX_Electrical_Arc_01.SFX_Electrical_Arc_01"),
        TEXT("/Game/SaskartaGaea/Audio/Storm/SFX_Electrical_Arc_02.SFX_Electrical_Arc_02"),
        TEXT("/Game/SaskartaGaea/Audio/Radio/SFX_Radio_Power_On_Bloom.SFX_Radio_Power_On_Bloom"),
    };
    static_assert(UE_ARRAY_COUNT(Paths) == 11, "one path per ESound");
}

void USaskartaChargeAudio::Start()
{
    Sounds.SetNum(Count);
    if (!UAssetManager::IsInitialized()) return;
    TArray<FSoftObjectPath> Requests;
    for (const TCHAR* Path : SaskartaChargeAudio::Paths) Requests.Add(FSoftObjectPath(Path));
    Load = UAssetManager::GetStreamableManager().RequestAsyncLoad(Requests, FStreamableDelegate());
}

USoundBase* USaskartaChargeAudio::Get(ESound Sound)
{
    if (!Sounds.IsValidIndex(Sound)) return nullptr;
    if (!Sounds[Sound] && Load.IsValid() && Load->HasLoadCompleted())
        Sounds[Sound] = Cast<USoundBase>(FSoftObjectPath(SaskartaChargeAudio::Paths[Sound]).ResolveObject());
    return Sounds[Sound];
}

void USaskartaChargeAudio::OneShot(ESound Sound, float Volume, float Pitch)
{
    if (USoundBase* Asset = Get(Sound)) UGameplayStatics::PlaySound2D(GetOuter(), Asset, Volume, Pitch);
}

void USaskartaChargeAudio::StopLoops(float FadeS)
{
    if (IsValid(HumVoice) && HumVoice->IsPlaying()) HumVoice->FadeOut(FadeS, 0.f);
    if (IsValid(BuzzVoice) && BuzzVoice->IsPlaying()) BuzzVoice->FadeOut(FadeS, 0.f);
}

void USaskartaChargeAudio::Update(bool bCharging, float Charge, double NowS)
{
    if (!bCharging)
    {
        if (bActive)
        {
            bActive = false;
            StopLoops(.35f);
            OneShot(RelayOut, .55f, .9f);
        }
        return;
    }
    const float Fill = FMath::Clamp(Charge / 100.f, 0.f, 1.f);
    const int32 Step = FMath::FloorToInt(Charge / 5.f);
    if (!bActive)
    {
        bActive = true;
        bFullPlayed = Charge >= 99.5f;
        LastStep = Step;
        NextArcS = NowS + FMath::FRandRange(3.f, 7.f);
        OneShot(RelayIn, .6f, 1.f);
    }
    if (Charge >= 99.5f)
    {
        // Full: the cell goes quiet, one bloom.
        if (!bFullPlayed)
        {
            bFullPlayed = true;
            OneShot(Full, .4f, 1.f);
            OneShot(RelayOut, .4f, 1.15f);
        }
        StopLoops(1.2f);
        return;
    }
    bFullPlayed = false;

    // The loops are restarted whenever they end, so a non-looping asset still holds.
    if (USoundBase* HumAsset = Get(Hum))
    {
        if (!IsValid(HumVoice)) HumVoice = UGameplayStatics::CreateSound2D(GetOuter(), HumAsset, 1.f, 1.f, 0.f, nullptr, false, false);
        if (HumVoice && !HumVoice->IsPlaying()) HumVoice->FadeIn(.6f, .42f);
        if (HumVoice) HumVoice->SetPitchMultiplier(FMath::Lerp(.78f, 1.12f, Fill));
    }
    if (USoundBase* BuzzAsset = Get(Buzz))
    {
        if (!IsValid(BuzzVoice)) BuzzVoice = UGameplayStatics::CreateSound2D(GetOuter(), BuzzAsset, 1.f, 1.f, 0.f, nullptr, false, false);
        if (BuzzVoice && !BuzzVoice->IsPlaying()) BuzzVoice->FadeIn(.9f, .1f);
        if (BuzzVoice) BuzzVoice->SetPitchMultiplier(FMath::Lerp(.85f, 1.05f, Fill));
    }
    // A soft tick each 5 %, rising in pitch as the cell fills.
    if (Step > LastStep)
    {
        LastStep = Step;
        OneShot(static_cast<ESound>(Tick1 + FMath::RandRange(0, 3)), .32f, FMath::Lerp(.85f, 1.3f, Fill));
    }
    else if (Step < LastStep) LastStep = Step;
    if (NowS >= NextArcS)
    {
        NextArcS = NowS + FMath::FRandRange(6.f, 13.f);
        OneShot(FMath::RandBool() ? Arc1 : Arc2, .12f, FMath::FRandRange(.9f, 1.15f));
    }
}

void USaskartaChargeAudio::Shutdown()
{
    StopLoops(.05f);
    if (IsValid(HumVoice)) HumVoice->DestroyComponent();
    if (IsValid(BuzzVoice)) BuzzVoice->DestroyComponent();
    HumVoice = nullptr;
    BuzzVoice = nullptr;
    if (Load.IsValid()) Load->CancelHandle();
    Load.Reset();
    Sounds.Reset();
    bActive = false;
}
