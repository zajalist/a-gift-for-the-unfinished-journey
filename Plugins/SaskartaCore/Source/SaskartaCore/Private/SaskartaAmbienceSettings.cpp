// USaskartaAmbienceSettings. See the header.

#include "SaskartaAmbienceSettings.h"
#include "SaskartaGameUserSettings.h"

#include "HAL/IConsoleManager.h"

USaskartaAmbienceSettings* USaskartaAmbienceSettings::Get()
{
    return GetMutableDefault<USaskartaAmbienceSettings>();
}

TMap<FString, FString> USaskartaAmbienceSettings::ComputeCVars(bool bGeigerCounter, float GeigerVolume)
{
    TMap<FString, FString> C;
    C.Add(TEXT("saskarta.geiger"), bGeigerCounter ? TEXT("1") : TEXT("0"));
    C.Add(TEXT("saskarta.volume.geiger"), FString::Printf(TEXT("%.3f"), FMath::Clamp(GeigerVolume, 0.f, 1.f)));
    return C;
}

void USaskartaAmbienceSettings::ApplyAmbienceCVars()
{
    const USaskartaAmbienceSettings* S = Get();
    for (const TPair<FString, FString>& KV : ComputeCVars(S->bGeigerCounter, S->GeigerVolume))
    {
        IConsoleVariable* V = IConsoleManager::Get().FindConsoleVariable(*KV.Key);
        if (!V)
        {
            V = IConsoleManager::Get().RegisterConsoleVariable(*KV.Key, 0.f,
                TEXT("Saskarta ambience setting mirror (USaskartaAmbienceSettings)."), ECVF_Default);
        }
        if (V)
        {
            V->Set(*KV.Value, ECVF_SetByCode);
        }
    }
}

void USaskartaAmbienceSettings::SaveAndApply()
{
    SaveConfig();
    ApplyAmbienceCVars();
}

void USaskartaAmbienceSettings::SetGeigerCounter(bool bOn)
{
    Get()->bGeigerCounter = bOn;
    Get()->SaveAndApply();
}

void USaskartaAmbienceSettings::SetGeigerVolume(float Volume)
{
    Get()->GeigerVolume = FMath::Clamp(Volume, 0.f, 1.f);
    Get()->SaveAndApply();
}

float USaskartaAmbienceSettings::GetAmbienceVolume()
{
    const USaskartaGameUserSettings* S = USaskartaGameUserSettings::GetSaskartaSettings();
    return S ? FMath::Clamp(S->AmbienceVolume, 0.f, 1.f) : 1.f;
}

void USaskartaAmbienceSettings::SetAmbienceVolume(float Volume)
{
    if (USaskartaGameUserSettings* S = USaskartaGameUserSettings::GetSaskartaSettings())
    {
        S->AmbienceVolume = FMath::Clamp(Volume, 0.f, 1.f);
        S->SaveSettings();
    }
}
