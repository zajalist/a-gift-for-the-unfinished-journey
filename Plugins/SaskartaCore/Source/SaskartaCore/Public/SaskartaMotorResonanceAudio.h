#pragma once

#include "CoreMinimal.h"
#include "UObject/Object.h"
#include "SaskartaMotorResonanceLogic.h"
#include "SaskartaMotorResonanceAudio.generated.h"

class UAudioComponent;
class USoundBase;
class UWorld;
struct FStreamableHandle;

/** Mechanical motor feedback. Owns only its voices; never changes the radio or a sound mix. */
UCLASS()
class SASKARTACORE_API USaskartaMotorResonanceAudio : public UObject
{
    GENERATED_BODY()
public:
    void Initialize(UWorld* InWorld);
    void BeginSession();
    void UpdateCues(const FSaskartaMotorResonanceLogic& Core, bool bAllowed);
    void PlayFeedback(const FSaskartaMotorResonanceLogic& Core);
    /** Optional quiet flywheel layer, shared by timed and held-crank controls. */
    void SetCrank(float Effort01, float Stability01);
    void EndSession();
    void Shutdown();

private:
    enum class ESound : uint8 { Lead, Engage, LeftValve, RightValve, Flywheel, Count };
    bool RefreshAssets();
    void Silence();
    void Play(ESound Sound, float Volume, float Pitch, bool bResult);
    static void StopVoice(TObjectPtr<UAudioComponent>& Voice, bool bDestroy = false);
    TWeakObjectPtr<UWorld> AudioWorld;
    TSharedPtr<FStreamableHandle> LoadHandle;
    UPROPERTY(Transient) TArray<TObjectPtr<USoundBase>> Sounds;
    UPROPERTY(Transient) TObjectPtr<UAudioComponent> WarningVoice;
    UPROPERTY(Transient) TObjectPtr<UAudioComponent> ResultVoice;
    UPROPERTY(Transient) TObjectPtr<UAudioComponent> FlywheelVoice;
    bool bSession = false;
    bool bAudible = false;
    int32 WarnedBeat = -1;
    int32 WarnedBalance = -1;
    double LastFeedbackUntil = -1.0;
    FSaskartaMotorResonanceLogic::EFeedback LastFeedback = FSaskartaMotorResonanceLogic::EFeedback::None;
};
