#include "SaskartaRadioRepairLogic.h"
#include <cassert>
#include <cstdio>
#include <limits>

int main()
{
    using F = FSaskartaRadioRepairLogic;
    assert(!F::InZone(3029.9f) && F::InZone(3030.f) && F::InZone(3080.f) && !F::InZone(3080.1f));
    F State;
    assert(!State.Confirm() && State.Stage == F::EStage::Aerial);
    const float Original = State.AerialDeg;
    State.Step(0.1f, 1.f, 1.f, false);
    State.Step(2.f, 1.f, 1.f, true);
    assert(State.AerialDeg == Original); // pause and hitch do not move controls
    for (int I = 0; I < 58; ++I) State.Step(0.05f, 1.f, 1.f, true);
    assert(State.CanLockAerial() && State.Frequency == -0.45f && State.StableS == 0.f);
    assert(State.Confirm() && State.Stage == F::EStage::Frequency);
    const float Locked = State.AerialDeg;
    for (int I = 0; I < 122; ++I) State.Step(0.05f, -1.f, 1.f, true);
    assert(State.AerialDeg == Locked && State.Signal() > 0.99f && State.StableS == 0.f);
    for (int I = 0; I < 12; ++I) State.Step(0.1f, 0.f, 0.f, true);
    assert(State.StableS > 1.f && !State.IsComplete());
    F Restored;
    Restored.Restore(1, State.AerialDeg, State.Frequency, State.StableS, false);
    for (int I = 0; I < 30; ++I) Restored.Step(0.1f, 0.f, 0.f, false);
    assert(Restored.StableS == State.StableS);
    for (int I = 0; I < 18; ++I) Restored.Step(0.1f, 0.f, 0.f, true);
    assert(Restored.IsComplete() && Restored.StableS == 3.f && Restored.Signal() == 1.f);
    assert(!Restored.Confirm());
    F Finished;
    Finished.Restore(2, 32.f, 0.16f, 3.f, true);
    Finished.Step(0.1f, 1.f, 1.f, true);
    assert(Finished.IsComplete() && Finished.AerialDeg == 32.f);
    F ReAim;
    ReAim.Restore(1, 32.f, 0.16f, 1.5f, false);
    ReAim.Step(0.1f, 0.f, 1.f, true);
    assert(ReAim.StableS == 0.f); // dial must be released for stable reception
    assert(ReAim.Confirm() && ReAim.Stage == F::EStage::Aerial);
    F Malformed;
    const float NaN = std::numeric_limits<float>::quiet_NaN();
    Malformed.Restore(999, NaN, NaN, NaN, false);
    assert(Malformed.Stage == F::EStage::Aerial && std::isfinite(Malformed.AerialDeg) && std::isfinite(Malformed.Frequency));
    Malformed.Step(0.1f, NaN, NaN, true);
    assert(std::isfinite(Malformed.AerialDeg) && !F::InZone(NaN));
    std::puts("radio repair smoke: ok");
}
