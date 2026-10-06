// USaskartaStorySettings. See the header.

#include "SaskartaStorySettings.h"

#include "HAL/IConsoleManager.h"

USaskartaStorySettings* USaskartaStorySettings::Get()
{
    return GetMutableDefault<USaskartaStorySettings>();
}

TMap<FString, FString> USaskartaStorySettings::ComputeCVars(bool bRadioStation, float StationVolume, bool bShowSaskartan)
{
    TMap<FString, FString> C;
    C.Add(TEXT("saskarta.radio"), bRadioStation ? TEXT("1") : TEXT("0"));
    C.Add(TEXT("saskarta.volume.station"), FString::Printf(TEXT("%.3f"), FMath::Clamp(StationVolume, 0.f, 1.f)));
    C.Add(TEXT("saskarta.subtitles.saskartan"), bShowSaskartan ? TEXT("1") : TEXT("0"));
    return C;
}

void USaskartaStorySettings::ApplyStoryCVars()
{
    const USaskartaStorySettings* S = Get();
    for (const TPair<FString, FString>& KV : ComputeCVars(S->bRadioStation, S->StationVolume, S->bShowSaskartan))
    {
        IConsoleVariable* V = IConsoleManager::Get().FindConsoleVariable(*KV.Key);
        if (!V)
        {
            V = IConsoleManager::Get().RegisterConsoleVariable(*KV.Key, 0.f,
                TEXT("Saskarta story/station setting mirror (USaskartaStorySettings)."), ECVF_Default);
        }
        if (V)
        {
            V->Set(*KV.Value, ECVF_SetByCode);
        }
    }
}

void USaskartaStorySettings::SaveAndApply()
{
    SaveConfig();
    ApplyStoryCVars();
}

void USaskartaStorySettings::SetRadioStation(bool bOn)
{
    Get()->bRadioStation = bOn;
    Get()->SaveAndApply();
}

void USaskartaStorySettings::SetStationVolume(float Volume)
{
    Get()->StationVolume = FMath::Clamp(Volume, 0.f, 1.f);
    Get()->SaveAndApply();
}

void USaskartaStorySettings::SetShowSaskartan(bool bOn)
{
    Get()->bShowSaskartan = bOn;
    Get()->SaveAndApply();
}
