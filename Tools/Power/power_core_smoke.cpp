// Offline check of the pure power core (ROUTE_BOARD_V3.md POWER). Build and run (x64 Native Tools prompt):
//   cl /nologo /EHsc /std:c++17 /utf-8 /I Plugins/SaskartaCore/Source/SaskartaCore/Public Tools/Power/power_core_smoke.cpp
#include "SaskartaPowerLogic.h"

#include <cassert>
#include <cmath>
#include <cstdio>

static bool Near(float A, float B, float E = 0.0001f) { return std::fabs(A - B) < E; }

int main()
{
    FSaskartaPowerCore P;
    assert(P.Charge == 35.f); // depleted handover cell: an early stop is needed
    FSaskartaPowerInput I;
    I.bPlaying = true;
    I.DeltaS = 0.1f;
    I.SpeedMps = 5.f;
    P.Step(I);
    assert(Near(P.LastRatePerS, -0.33f)); // everything on
    I.bRadioRequested = false;
    P.Step(I);
    assert(Near(P.LastRatePerS, -0.18f)); // radio off
    I.bRadioRequested = true; I.bLampsRequested = false;
    P.Step(I);
    assert(Near(P.LastRatePerS, -0.23f)); // lamps off
    I.bRadioRequested = false;
    P.Step(I);
    assert(Near(P.LastRatePerS, -0.08f)); // all off
    I.bListening = true;
    P.Step(I);
    assert(Near(P.LastRatePerS, -0.23f)); // LISTEN runs the radio load
    I.bListening = false;

    // Range from a full bar at 5 m/s: 1.5 / 2.8 / 2.2 / 6 km.
    P.Charge = 100.f;
    assert(Near(P.RangeKm(true, true), 1.515f, 0.01f));
    assert(Near(P.RangeKm(false, true), 2.78f, 0.01f));
    assert(Near(P.RangeKm(true, false), 2.17f, 0.01f));
    assert(Near(P.RangeKm(false, false), 6.25f, 0.01f));
    // Rest: +1.25 with both on, +1.5 with both off; 20 % to full in about a minute.
    assert(Near(P.RestRatePerS(true, true), 1.25f) && Near(P.RestRatePerS(false, false), 1.5f));
    P.Charge = 20.f;
    assert(Near(P.SecondsToFull(true, true), 64.f, 0.01f));

    // Turbo: about 35 s from full at 8 m/s.
    P.Charge = 100.f;
    I.bRadioRequested = true; I.bLampsRequested = true; I.SpeedMps = 8.f; I.bTurboHeld = true;
    P.Step(I);
    assert(P.bTurbo && P.LastRatePerS < -2.9f && P.LastRatePerS > -3.2f);
    assert(Near(P.SpeedCapMps(5.f, 0.f), 8.f));

    // Stopped 2 s: a rest.
    I.SpeedMps = 0.f; I.bTurboHeld = false;
    for (int N = 0; N < 25; ++N) P.Step(I);
    assert(P.CanRest() && Near(P.LastRatePerS, 1.25f));

    // Empty stops travel. The legacy saved latch releases only after a parked recharge to 30%.
    P.Load({0.f, 0.f, true});
    assert(P.bLimp && P.Charge == 0.f);
    I.SpeedMps = 2.5f; I.bTurboHeld = true;
    P.Step(I);
    assert(P.bLimp && !P.bTurbo && P.LastRatePerS <= 0.f && P.Charge == 0.f);
    assert(Near(P.SpeedCapMps(5.f, 0.f), 0.f));
    P.Tuning.LimpSpeedMps = 99.f;
    assert(P.SpeedCapMps(5.f, 0.f) == 0.f); // stale tuning cannot re-enable a crawl
    P.Charge = 29.f;
    P.Step(I);
    assert(P.bLimp);
    P.Charge = 29.99f;
    I.SpeedMps = 0.f;
    P.Step(I);
    assert(!P.bLimp); // 30 % lifts it
    P.Load({20.f, 0.f, true});
    assert(P.bLimp);  // a saved limp below 30 % stays limp
    P.Load({30.f, 0.f, true});
    assert(!P.bLimp);
    P.Load({0.f, 0.f, false});
    I.SpeedMps = 0.f; I.bTurboHeld = true;
    for (int N = 0; N < 300 && P.bLimp; ++N) P.Step(I);
    assert(P.Charge > 30.f && !P.bLimp && P.CanRest());
    // Before the recovery threshold, holding boost never prevents passive recharge.
    P.Load({20.f, 3.f, true});
    P.Step(I);
    assert(P.Charge > 20.f && P.bLimp && !P.bTurbo && P.SpeedCapMps(5.f, 0.f) == 0.f);
    P.Load({30.f, 0.f, true});

    // A recovered pursuit may replenish only its own saved carrier before restart.
    // The subsystem calls SetCharge(max(saved charge, actual recovery threshold));
    // SetCharge routes through Save/Load, so test the real latch rule at both boundaries.
    for (float SavedCharge : {0.f, 0.01f, 20.f, 29.99f, 30.f, 80.f})
    {
        for (bool SavedLimp : {false, true})
        {
            P.Load({SavedCharge, 3.f, SavedLimp});
            auto Recovered = P.Save();
            Recovered.Charge = std::max(P.Charge, P.Tuning.LimpExitPercent);
            Recovered.bLimp = Recovered.bLimp || Recovered.Charge <= 0.f;
            P.Load(Recovered);
            assert(!P.bLimp && P.Charge >= P.Tuning.LimpExitPercent);
            assert(Near(P.Charge, std::max(SavedCharge, P.Tuning.LimpExitPercent)));
            assert(P.SpeedCapMps(5.f, 0.f) > 0.f);
            const auto Once = P.Save();
            P.Load(Once);
            assert(!P.bLimp && Near(P.Charge, Once.Charge));
        }
    }
    P.Load({30.f, 0.f, true});

    // Frozen outside play; spending.
    const float Charge = P.Charge;
    I.bCinematic = true;
    P.Step(I);
    assert(Near(P.Charge, Charge));
    assert(!P.TrySpend(101.f) && Near(P.Charge, Charge));
    assert(P.CanPin(10.f) && P.TrySpend(10.f) && Near(P.Charge, 20.f));
    std::puts("power core smoke: ok");
    return 0;
}
