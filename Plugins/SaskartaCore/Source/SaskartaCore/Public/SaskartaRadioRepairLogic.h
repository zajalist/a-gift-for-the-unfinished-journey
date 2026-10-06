#pragma once

#include <algorithm>
#include <cmath>

/** One optional receiver alignment at the authored Cistern reception dip. No rhythm, cost or fail state. */
struct FSaskartaRadioRepairLogic
{
    enum class EStage { Aerial, Frequency, Complete };
    static constexpr float FromRoadM = 3030.f;
    static constexpr float ToRoadM = 3080.f;
    static constexpr float StableDurationS = 3.f;
    static constexpr float TargetAerialDeg = 32.f;
    static constexpr float TargetFrequency = 0.16f;
    EStage Stage = EStage::Aerial;
    float AerialDeg = -55.f;
    float Frequency = -0.45f;
    float StableS = 0.f;

    static bool InZone(float RoadM) { return std::isfinite(RoadM) && RoadM >= FromRoadM && RoadM <= ToRoadM; }
    bool IsComplete() const { return Stage == EStage::Complete; }
    float AerialQuality() const { return std::clamp(1.f - std::abs(AerialDeg - TargetAerialDeg) / 65.f, 0.f, 1.f); }
    float FrequencyQuality() const { return std::clamp(1.f - std::abs(Frequency - TargetFrequency) / 0.28f, 0.f, 1.f); }
    bool CanLockAerial() const { return AerialQuality() >= 0.9f; }
    float Signal() const
    {
        if (IsComplete()) return 1.f;
        return Stage == EStage::Aerial ? 0.35f * AerialQuality() : AerialQuality() * FrequencyQuality();
    }
    bool Confirm()
    {
        if (Stage == EStage::Aerial && CanLockAerial()) { Stage = EStage::Frequency; StableS = 0.f; return true; }
        if (Stage == EStage::Frequency) { Stage = EStage::Aerial; StableS = 0.f; return true; }
        return false;
    }
    void Step(float DeltaS, float DirectionAxis, float FrequencyAxis, bool bAllowed)
    {
        if (!bAllowed || IsComplete() || !std::isfinite(DeltaS) || DeltaS <= 0.f || DeltaS > 0.5f) return;
        const float Dt = std::min(DeltaS, 0.1f);
        const float Direction = std::isfinite(DirectionAxis) ? std::clamp(DirectionAxis, -1.f, 1.f) : 0.f;
        const float Fine = std::isfinite(FrequencyAxis) ? std::clamp(FrequencyAxis, -1.f, 1.f) : 0.f;
        if (Stage == EStage::Aerial)
        {
            AerialDeg = std::clamp(AerialDeg + Direction * 30.f * Dt, -90.f, 90.f);
            StableS = 0.f;
        }
        else
        {
            Frequency = std::clamp(Frequency + Fine * 0.10f * Dt, -1.f, 1.f);
            // Stability means releasing the dial in the clearly marked strong-signal band.
            StableS = std::abs(Fine) < 0.01f && Signal() >= 0.86f ? StableS + Dt : 0.f;
            if (StableS + 0.0001f >= StableDurationS) { StableS = StableDurationS; Stage = EStage::Complete; }
        }
    }
    void Restore(int SavedStage, float SavedAerial, float SavedFrequency, float SavedStable, bool bCompleted)
    {
        AerialDeg = std::isfinite(SavedAerial) ? std::clamp(SavedAerial, -90.f, 90.f) : -55.f;
        Frequency = std::isfinite(SavedFrequency) ? std::clamp(SavedFrequency, -1.f, 1.f) : -0.45f;
        Stage = bCompleted ? EStage::Complete : SavedStage == 1 && CanLockAerial() ? EStage::Frequency : EStage::Aerial;
        StableS = Stage == EStage::Frequency && Signal() >= 0.86f && std::isfinite(SavedStable)
            ? std::clamp(SavedStable, 0.f, StableDurationS) : 0.f;
        if (bCompleted) StableS = StableDurationS;
    }
};
