#include "SaskartaMotorAssistLogic.h"
#include <cassert>
#include <cmath>
#include <limits>
#include <cstdio>

int main()
{
    using F = FSaskartaMotorAssistLogic;
    F S;
    assert(S.Step(0.f, true, true, 1.f, false, false, .3f));
    assert(S.Amount == 0.f); // Eligible immediately: suppress the backwards unstuck launch.
    float Previous = 0.f;
    for (int I = 0; I < 18; ++I)
    {
        assert(S.Step(1.f / 30.f, true, true, 1.f, false, false, .3f));
        assert(S.Amount >= Previous && S.Amount - Previous <= .056f);
        const F::FLimits L = S.Apply(35.f, 225.f);
        assert(L.MaxAcceleration <= 215.f && L.MaxWalkSpeed <= 380.f);
        Previous = S.Amount;
    }
    assert(std::abs(S.Amount - 1.f) < 1e-5f);
    const F::FLimits Full = S.Apply(35.f, 225.f);
    assert(std::abs(Full.MaxAcceleration - 215.f) < 1e-4f);
    assert(std::abs(Full.MaxWalkSpeed - 380.f) < 1e-4f);
    assert(S.Apply(190.f, 520.f).MaxWalkSpeed == 520.f);

    for (int Gate = 0; Gate < 7; ++Gate)
    {
        S.Amount = 1.f;
        const bool Active = S.Step(.1f, Gate != 0, Gate != 1, Gate == 2 ? 0.f : 1.f,
            Gate == 3, Gate == 4, Gate == 5 ? 0.f : Gate == 6 ? -.1f : .3f);
        assert(!Active && S.Amount == 0.f);
        const auto Disabled = S.Apply(35.f, 225.f);
        assert(Disabled.MaxAcceleration == 35.f && Disabled.MaxWalkSpeed == 225.f);
    }
    for (float Bad : {std::numeric_limits<float>::quiet_NaN(), std::numeric_limits<float>::infinity()})
    {
        assert(!F::CanAssist(true, true, Bad, false, false, .3f));
        assert(!F::CanAssist(true, true, 1.f, false, false, Bad));
        S.Reset();
        assert(S.Step(Bad, true, true, 1.f, false, false, .3f));
        assert(S.Amount == 0.f);
        const auto Safe = S.Apply(Bad, Bad);
        assert(std::isfinite(Safe.MaxAcceleration) && std::isfinite(Safe.MaxWalkSpeed));
    }
    F Fast, Slow;
    for (int I = 0; I < 18; ++I) Fast.Step(1.f / 60.f, true, true, 1.f, false, false, .3f);
    for (int I = 0; I < 9; ++I) Slow.Step(1.f / 30.f, true, true, 1.f, false, false, .3f);
    assert(std::abs(Fast.Amount - Slow.Amount) < 1e-5f);
    assert(std::abs(Fast.Amount - .5f) < 1e-5f);
    S.Reset();
    S.Step(10.f, true, true, 1.f, false, false, .3f);
    assert(S.Amount <= .167f); // A stall cannot instantly engage full torque.
    S.Reset();
    for (int I = 0; I < 100; ++I) S.Step(.1f, true, true, 1.f, false, false, .1375f);
    assert(std::abs(S.Amount - .5f) < 1e-5f); // Half grade demand.
    assert(S.Apply(35.f, 225.f).MaxWalkSpeed < 380.f);
    std::puts("motor assist: automatic ramp, cancellation, grade, finite bounds and frame rate passed");
}
