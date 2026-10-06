#pragma once

#include <algorithm>
#include <cmath>

// Automatic low gear for ordinary hill driving. The shared resonance mechanic
// owns deliberate E/A/D timing; this assistance never consumes player inputs.
struct FSaskartaMotorAssistLogic
{
    struct FLimits
    {
        float MaxAcceleration;
        float MaxWalkSpeed;
    };
    static constexpr float GradeStart = 0.055f;
    static constexpr float GradeFull = 0.22f;
    static constexpr float RampSeconds = 0.6f;
    static constexpr float AccelerationBonus = 180.f;
    static constexpr float ClimbSpeedCmS = 380.f;
    float Amount = 0.f;

    static bool CanAssist(bool bControlsAvailable, bool bGrounded, float Throttle,
                          bool bReversing, bool bBraking, float Grade)
    {
        return bControlsAvailable && bGrounded && std::isfinite(Throttle) && Throttle > 0.55f &&
               !bReversing && !bBraking && std::isfinite(Grade) && Grade > GradeStart;
    }

    void Reset() { Amount = 0.f; }

    // Return eligibility even during the ramp: a hill must never trigger the
    // Blueprint's backwards anti-stuck launch. All suppression cancels immediately.
    bool Step(float DeltaSeconds, bool bControlsAvailable, bool bGrounded, float Throttle,
              bool bReversing, bool bBraking, float Grade)
    {
        if (!CanAssist(bControlsAvailable, bGrounded, Throttle, bReversing, bBraking, Grade))
        {
            Reset();
            return false;
        }
        if (!std::isfinite(DeltaSeconds) || DeltaSeconds <= 0.f) return true;
        const float Dt = std::min(DeltaSeconds, 0.1f);
        const float Target = std::clamp((Grade - GradeStart) / (GradeFull - GradeStart), 0.f, 1.f);
        Amount += std::clamp(Target - Amount, -Dt / RampSeconds, Dt / RampSeconds);
        return true;
    }

    FLimits Apply(float BaseAcceleration, float BaseSpeed) const
    {
        const float Acceleration = std::isfinite(BaseAcceleration) ? std::max(0.f, BaseAcceleration) : 0.f;
        const float Speed = std::isfinite(BaseSpeed) ? std::max(0.f, BaseSpeed) : 0.f;
        const float Weight = std::isfinite(Amount) ? std::clamp(Amount, 0.f, 1.f) : 0.f;
        return {Acceleration + AccelerationBonus * Weight,
                Speed + std::max(0.f, ClimbSpeedCmS - Speed) * Weight};
    }
};
