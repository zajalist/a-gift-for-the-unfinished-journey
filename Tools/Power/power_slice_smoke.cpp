// Offline check of the pure power HUD (ROUTE_BOARD_V3.md THE CRT). Build and run:
//   cl /nologo /EHsc /std:c++17 /utf-8 /I Plugins/SaskartaCore/Source/SaskartaCore/Public Tools/Power/power_slice_smoke.cpp
#include "SaskartaPowerHud.h"
#include "SaskartaPowerLogic.h"

#include <cassert>
#include <cstdio>

int main()
{
    FSaskartaPowerHudInput In;
    In.Charge = 62.f; In.RatePerS = -0.33f; In.RangeKm = 1.4f;
    assert(FSaskartaPowerHud::LineFor(In) == L"PWR ||||||||||||........ 62%  RANGE 1.4 KM");
    In.bAscii = true;
    assert(FSaskartaPowerHud::LineFor(In) == L"PWR ############........ 62%  RANGE 1.4 KM");
    In.bAscii = false;
    In.Charge = 31.f; In.RatePerS = 1.25f; In.bResting = true; In.SecondsToFull = 55.2f;
    assert(FSaskartaPowerHud::LineFor(In) == L"PWR ||||||.............. 31%  ^ FULL IN 55 S");
    In.bResting = false; In.bLimp = true; In.Charge = 0.f;
    assert(FSaskartaPowerHud::LineFor(In) == L"PWR ....................  0%  SYSTEM STOPPED . RECHARGE TO 30%");
    In.bLimp = false; In.RangeKm = -1.f; In.Charge = 50.f;
    assert(FSaskartaPowerHud::LineFor(In) == L"PWR ||||||||||.......... 50%  RANGE FREE");

    // The line under it.
    FSaskartaPowerHudInput R; R.Charge = 44.f; R.RatePerS = 1.25f; R.bResting = true; R.bMotorReady = true;
    assert(FSaskartaPowerHud::SteadySub(R) == L"TAB . TUNE MOTOR");
    R.bGamepad = true;
    assert(FSaskartaPowerHud::SteadySub(R) == L"VIEW . TUNE MOTOR");
    FSaskartaPowerHudInput T; T.bTurbo = true;
    assert(FSaskartaPowerHud::SteadySub(T) == L"SHIFT BOOST . RADIO DROWNED");
    FSaskartaPowerHudInput L; L.Charge = 15.f; L.bLow = true;
    assert(FSaskartaPowerHud::SteadySub(L) == L"PWR LOW . STOP TO CHARGE");

    FSaskartaPowerHud Hud;
    FSaskartaPowerHudInput H; H.Charge = 80.f; H.RatePerS = -0.33f; H.RangeKm = 2.4f;
    assert(Hud.Step(0.1f, H).Opacity == 1.f);
    for (int I = 0; I < 60; ++I) Hud.Step(0.1f, H);
    assert(Hud.Step(0.1f, H).Opacity == FSaskartaPowerHud::DimOpacity);
    H.bRadioOn = false; H.RangeKm = 4.5f;
    FSaskartaPowerHudOutput O = Hud.Step(0.1f, H);
    assert(O.Loads == L"RADIO OFF . RANGE 4.5 KM" && O.Opacity == 1.f);
    for (int I = 0; I < 31; ++I) O = Hud.Step(0.1f, H);
    assert(O.Loads.empty()); // the toggle line holds 3 s
    H.bLampsOn = false;
    assert(Hud.Step(0.1f, H).Loads == L"LAMPS OFF . RANGE 4.5 KM");
    Hud.Notify(L"STOP TO TUNE MOTOR");
    assert(Hud.Step(0.1f, H).Loads == L"STOP TO TUNE MOTOR");
    // Critical warnings stay readable: never flash/dim the whole gauge.
    FSaskartaPowerHud B;
    FSaskartaPowerHudInput K; K.Charge = 8.f; K.bLow = true; K.bBlink = true;
    bool bDimmed = false;
    for (int I = 0; I < 25; ++I) bDimmed |= B.Step(0.1f, K).Opacity < 0.5f;
    assert(!bDimmed);

    assert(SaskartaBatterySegmentFill(0.f, 0) == 0.f);
    assert(SaskartaBatterySegmentFill(100.f, 6) == 1.f);
    assert(SaskartaBatterySegmentFill(50.f, 2) == 1.f);
    assert(std::fabs(SaskartaBatterySegmentFill(50.f, 3) - 0.5f) < 0.001f);
    assert(SaskartaBatterySegmentFill(50.f, 4) == 0.f);
    FSaskartaBatteryGaze Gaze;
    assert(!Gaze.Step(0.1f, true, true, true));
    assert(!Gaze.Step(0.1f, true, true, true));
    assert(Gaze.Step(0.1f, true, true, true));
    assert(Gaze.Step(0.1f, true, false, false));
    assert(!Gaze.Step(0.1f, true, false, false));
    for (int N = 0; N < 3; ++N) Gaze.Step(0.1f, true, true, true);
    assert(!Gaze.Step(0.1f, false, true, true)); // occlusion/flow loss hides immediately
    FSaskartaPowerTelemetry History;
    for (int N = 0; N < 150; ++N) History.Push(1000.f, -45000.f + N * 10.f, N * 0.1);
    assert(History.Count == 120);
    assert(std::fabs(History.SpeedKph[History.Index(119)] - 36.f) < 0.001f);
    assert(std::fabs(History.AltitudeM[History.Index(119)] + 435.1f) < 0.001f);
    History.Push(1000.f, 100.f, 14.9); // same timer instant does not invent another sample
    assert(History.Count == 120);
    History.Push(1000.f, 100.f, 30.0); // hitch drops stale history rather than drawing a fake 12 s trace
    assert(History.Count == 1 && History.AltitudeM[History.Index(0)] == 1.f);

    // Limp keeps the radio and lamps as they were, but a moving carrier cannot recharge.
    FSaskartaPowerCore P;
    P.Load({0.5f, 0.f, false});
    FSaskartaPowerInput I; I.bPlaying = true; I.DeltaS = 0.25f; I.SpeedMps = 8.f; I.bTurboHeld = true;
    for (int K2 = 0; K2 < 8; ++K2) P.Step(I);
    assert(P.bLimp && P.SpeedCapMps(5.f, 0.f) == 0.f);
    I.SpeedMps = 2.5f; P.Step(I);
    assert(P.LastRatePerS <= 0.f && P.Charge == 0.f && !P.bTurbo);
    std::puts("power slice smoke: ok");
    return 0;
}
