#include "SaskartaFirstLightLogic.h"

float FSaskartaFirstLight::ClearMix(float StartPitch, float EndPitch, float HorizonPitch)
{
    const float Span = EndPitch - StartPitch;
    if (FMath::IsNearlyZero(Span))
    {
        return 0.5f;
    }
    return FMath::Clamp((HorizonPitch - StartPitch) / Span, 0.f, 1.f);
}

float FSaskartaFirstLight::DawnMix(float ElapsedS, float DurationS, float ClearAtS, float ClearMixValue)
{
    if (DurationS <= 0.f || ElapsedS >= DurationS)
    {
        return 1.f;
    }
    if (ElapsedS <= 0.f)
    {
        return 0.f;
    }
    if (ClearAtS <= 0.f || ClearAtS >= DurationS)
    {
        return FMath::Clamp(ElapsedS / DurationS, 0.f, 1.f);
    }
    const float C = FMath::Clamp(ClearMixValue, 0.f, 1.f);
    if (ElapsedS <= ClearAtS)
    {
        return C * (ElapsedS / ClearAtS);
    }
    return FMath::Clamp(C + (1.f - C) * ((ElapsedS - ClearAtS) / (DurationS - ClearAtS)), 0.f, 1.f);
}

bool FSaskartaFirstLight::RecaptureDue(float PrevElapsedS, float ElapsedS, float RecaptureIntervalS)
{
    if (PrevElapsedS < 0.f)
    {
        return true;
    }
    if (RecaptureIntervalS <= 0.f || ElapsedS <= PrevElapsedS)
    {
        return false;
    }
    return FMath::FloorToInt(ElapsedS / RecaptureIntervalS) > FMath::FloorToInt(PrevElapsedS / RecaptureIntervalS);
}

FSaskartaLookKey FSaskartaFirstLight::MakeDawnKey(const FSaskartaLookKey& Start, const FSaskartaDawnParams& Params)
{
    FSaskartaLookKey K = Start;
    K.Name = FName(TEXT("Dawn"));
    K.SunPitch = Params.EndPitch;
    K.SunYaw = Params.SunYaw;
    K.SunIntensityLux = Params.EndLux;
    K.SunTemperatureK = Params.EndTemperatureK;
    K.GradeClearWeight = Params.EndGradeClear;
    K.GradeStormWeight = 1.f - Params.EndGradeClear;
    K.StormIntensity = 0.f;
    return K;
}

FSaskartaLookKey FSaskartaFirstLight::MakeStartKey(const FSaskartaLookKey& Start, const FSaskartaDawnParams& Params)
{
    FSaskartaLookKey K = Start;
    K.Name = FName(TEXT("DawnStart"));
    K.SunYaw = Params.SunYaw;
    return K;
}

FName FSaskartaFirstLight::CaptionSpeaker(FName LineId, FName Speaker)
{
    const FString S = LineId.ToString();
    if (S.StartsWith(TEXT("BELOW_")))
    {
        return FName(TEXT("ILAAWB · LIVE"));
    }
    if (S.StartsWith(TEXT("SAMYOR_B24_")))
    {
        return NAME_None;
    }
    return Speaker;
}
