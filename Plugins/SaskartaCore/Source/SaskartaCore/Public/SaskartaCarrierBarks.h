// USaskartaCarrierBarks: short, random carrier remarks along the road (2026-10-05, the author: "add a bunch of TTS
// for the carrier that it randomly says along the road ... the carrier can speak over radio music without
// interrupting it").
//
// A world subsystem (game and PIE). Every 0.5 s (a timer, no Tick) it checks for a free driving window: FlowState
// Playing / Carrier, the carrier moving forward along the road, the runner's Voice channel free (no story, aux or
// storm line, no cinematic, no prompt, no input hold, no story subtitle), the next road beat far enough away, and
// the radio host not talking (the station's programme envelope has been silent for StationQuietS). Then, every
// 45-90 s, it plays one bark not heard among the last few as a plain 2D sound. It does NOT take the runner's Voice
// channel or broadcast OnStoryBusyChanged, so the station keeps playing its song or static at full level. If the
// host starts talking or a story line / cinematic starts while a bark plays, the bark fades out at once.
//
// The text goes through the runner's station caption path (ShowStationSubtitle), prefixed "CARRIER: ".
// Sounds: /Game/SaskartaGaea/Audio/CarrierBarks/CARRIER_BARK_NN (Tools/Audio/import_carrier_barks.py, sources in
// SourceArt/Audio/CarrierBarks). Only packages that exist are loaded (asynchronously); with none, it stays silent.
//
// Console: Saskarta.CarrierBarks 0/1 (default 1), Saskarta.CarrierBarks.Now (the next free window plays one).

#pragma once

#include "CoreMinimal.h"
#include "Subsystems/WorldSubsystem.h"
#include "TimerManager.h"
#include "SaskartaCarrierBarks.generated.h"

class UAudioComponent;
class USoundBase;
class USaskartaEventRunner;
class USaskartaRadioStation;
struct FStreamableHandle;

UCLASS()
class SASKARTACORE_API USaskartaCarrierBarks : public UWorldSubsystem
{
    GENERATED_BODY()

public:
    UFUNCTION(BlueprintPure, Category = "Saskarta|CarrierBarks", meta = (WorldContext = "WorldContextObject"))
    static USaskartaCarrierBarks* GetCarrierBarks(const UObject* WorldContextObject);

    /** True while a bark is audible. */
    UFUNCTION(BlueprintPure, Category = "Saskarta|CarrierBarks")
    bool IsBarkPlaying() const;

    /** Makes the next bark due now (it still waits for a free window). */
    UFUNCTION(BlueprintCallable, Category = "Saskarta|CarrierBarks")
    void ForceNextBark();

    virtual void Initialize(FSubsystemCollectionBase& Collection) override;
    virtual void Deinitialize() override;
    virtual void OnWorldBeginPlay(UWorld& InWorld) override;

protected:
    virtual bool DoesSupportWorldType(const EWorldType::Type WorldType) const override;

private:
    void Poll();
    void StartLoad();
    bool CanStartBark(const USaskartaEventRunner* R, const USaskartaRadioStation* Station, float DurationS) const;
    void PlayBark(int32 Index);
    void EndBark(bool bFade);
    void ScheduleNext(double FromS);
    double Now() const;

    struct FBark
    {
        FSoftObjectPath Path;
        FString Text;
    };
    TArray<FBark> Barks;
    TArray<int32> Recent;

    UPROPERTY(Transient)
    TObjectPtr<UAudioComponent> BarkComp;

    TSharedPtr<FStreamableHandle> LoadHandle;
    FTimerHandle PollTimer;
    double NextBarkAtS = 0.0;
    double BarkEndS = -1.0;
    double LastStationSpeechS = -1.0e9;
    double LastStoryBusyS = -1.0e9;
    double MovingSinceS = -1.0;
    float LastRoadM = -1.f;
    int32 PlayingIndex = INDEX_NONE;
    bool bStationHeardDuringBark = false;
    bool bLoadStarted = false;
};
