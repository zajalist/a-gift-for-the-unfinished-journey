// Story and station player settings (STATION.md section 7, EVENTS.md section 4 subtitles).
//
// Kept in its own class (config = GameUserSettings, section
// [/Script/SaskartaCore.SaskartaStorySettings]) rather than new UPROPERTYs on
// USaskartaGameUserSettings, so this lane adds files only. The settings screen reads and
// writes it through the static BlueprintCallable functions; each setter saves the ini and
// updates the cvar mirrors:
//   saskarta.radio                 0/1   Radio station on/off
//   saskarta.volume.station        0..1  Station volume
//   saskarta.subtitles.saskartan   0/1   Show original Saskartan above the English subtitle
// The station polls Get() on its own 0.25 s clock, so a toggle takes effect at once
// (switching the station off mid-segment fades it over 1 s).

#pragma once

#include "CoreMinimal.h"
#include "UObject/Object.h"
#include "SaskartaStorySettings.generated.h"

UCLASS(config = GameUserSettings, BlueprintType)
class SASKARTACORE_API USaskartaStorySettings : public UObject
{
    GENERATED_BODY()

public:
    /** The mutable class default object (the live settings). */
    static USaskartaStorySettings* Get();

    UFUNCTION(BlueprintPure, Category = "Saskarta|Settings", meta = (DisplayName = "Get Saskarta Story Settings"))
    static USaskartaStorySettings* GetStorySettings() { return Get(); }

    /** "Radio station": when off the station never comes on. Story, idle and carrier lines are unaffected. */
    UPROPERTY(Config, BlueprintReadOnly, Category = "Saskarta|Audio")
    bool bRadioStation = true;

    /** "Station volume" 0..1 (a little under story lines by default). */
    UPROPERTY(Config, BlueprintReadOnly, Category = "Saskarta|Audio")
    float StationVolume = 0.8f;

    /** "Show original Saskartan": the small Saskartan line above the English subtitle. */
    UPROPERTY(Config, BlueprintReadOnly, Category = "Saskarta|Accessibility")
    bool bShowSaskartan = true;

    UFUNCTION(BlueprintCallable, Category = "Saskarta|Settings")
    static void SetRadioStation(bool bOn);

    UFUNCTION(BlueprintCallable, Category = "Saskarta|Settings")
    static void SetStationVolume(float Volume);

    UFUNCTION(BlueprintCallable, Category = "Saskarta|Settings")
    static void SetShowSaskartan(bool bOn);

    /** Writes the cvar mirrors (registering them on first use, like USaskartaGameUserSettings). */
    UFUNCTION(BlueprintCallable, Category = "Saskarta|Settings")
    static void ApplyStoryCVars();

    /** Pure mapping, tested by Saskarta.Station.SettingsCVars. */
    static TMap<FString, FString> ComputeCVars(bool bRadioStation, float StationVolume, bool bShowSaskartan);

private:
    void SaveAndApply();
};
