// Ambience player settings: the Geiger counter on/off and its level, plus the ambience volume.
//
// Its own small class (config = GameUserSettings, section [/Script/SaskartaCore.SaskartaAmbienceSettings])
// so this lane adds files only, like USaskartaStorySettings. The ambience volume is NOT duplicated:
// the settings screen's "Ambience" slider already writes USaskartaGameUserSettings::AmbienceVolume,
// so Get/SetAmbienceVolume read and write that one (the director multiplies every voice by it).
// cvar mirrors: saskarta.geiger (0/1), saskarta.volume.geiger (0..1). The director reads Get()
// on its 0.5 s clock, so a toggle takes effect at once (switching the Geiger off plays SwitchOff).

#pragma once

#include "CoreMinimal.h"
#include "UObject/Object.h"
#include "SaskartaAmbienceSettings.generated.h"

UCLASS(config = GameUserSettings, BlueprintType)
class SASKARTACORE_API USaskartaAmbienceSettings : public UObject
{
    GENERATED_BODY()

public:
    /** The mutable class default object (the live settings). */
    static USaskartaAmbienceSettings* Get();

    UFUNCTION(BlueprintPure, Category = "Saskarta|Settings", meta = (DisplayName = "Get Saskarta Ambience Settings"))
    static USaskartaAmbienceSettings* GetAmbienceSettings() { return Get(); }

    /** "Geiger counter": the carrier's clicking counter. Off = silent (the dose is still computed for the HUD). */
    UPROPERTY(Config, BlueprintReadOnly, Category = "Saskarta|Audio")
    bool bGeigerCounter = true;

    /** "Geiger volume" 0..1, on top of the ambience volume. */
    UPROPERTY(Config, BlueprintReadOnly, Category = "Saskarta|Audio")
    float GeigerVolume = 1.f;

    UFUNCTION(BlueprintCallable, Category = "Saskarta|Settings")
    static void SetGeigerCounter(bool bOn);

    UFUNCTION(BlueprintCallable, Category = "Saskarta|Settings")
    static void SetGeigerVolume(float Volume);

    /** The ambience volume 0..1 (USaskartaGameUserSettings::AmbienceVolume; 1 without it). */
    UFUNCTION(BlueprintPure, Category = "Saskarta|Settings")
    static float GetAmbienceVolume();

    /** Writes USaskartaGameUserSettings::AmbienceVolume and saves it. */
    UFUNCTION(BlueprintCallable, Category = "Saskarta|Settings")
    static void SetAmbienceVolume(float Volume);

    UFUNCTION(BlueprintCallable, Category = "Saskarta|Settings")
    static void ApplyAmbienceCVars();

    /** Pure mapping (tested). */
    static TMap<FString, FString> ComputeCVars(bool bGeigerCounter, float GeigerVolume);

private:
    void SaveAndApply();
};
