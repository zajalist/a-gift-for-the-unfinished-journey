#pragma once

#include "CoreMinimal.h"
#include "UObject/Object.h"
#include "Engine/StreamableManager.h"
#include "SaskartaChargeAudio.generated.h"

class UAudioComponent;
class USoundBase;

/** Stationary biofuel recharge sound: relay in, a hum that rises with the charge, a tick every 5 %,
 * rare quiet arcs, a bloom at full, a clunk when the carrier pulls away. Driven by the power poll. */
UCLASS()
class SASKARTACORE_API USaskartaChargeAudio : public UObject
{
    GENERATED_BODY()
public:
    void Start();
    /** bCharging: Core.IsCharging() or a full cell still resting. Charge is 0..100. */
    void Update(bool bCharging, float Charge, double NowS);
    void Shutdown();

private:
    enum ESound : int32 { RelayIn, RelayOut, Hum, Buzz, Tick1, Tick2, Tick3, Tick4, Arc1, Arc2, Full, Count };
    USoundBase* Get(ESound Sound);
    void OneShot(ESound Sound, float Volume, float Pitch);
    void StopLoops(float FadeS);

    UPROPERTY(Transient) TArray<TObjectPtr<USoundBase>> Sounds;
    UPROPERTY(Transient) TObjectPtr<UAudioComponent> HumVoice;
    UPROPERTY(Transient) TObjectPtr<UAudioComponent> BuzzVoice;
    TSharedPtr<FStreamableHandle> Load;
    bool bActive = false;
    bool bFullPlayed = false;
    int32 LastStep = -1;
    double NextArcS = 0.0;
};
