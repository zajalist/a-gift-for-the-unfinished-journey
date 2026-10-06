#pragma once

// Pure presentation rules shared by native UI and offline Power smokes. The old LineFor formatter remains
// for callers/tests; the runtime widget renders its percentage only during physical battery inspection.
// Warnings and recharge guidance remain proactive. No full-gauge flashing; instruments use real samples.

#include <cmath>
#include <cstdio>
#include <array>
#include <string>

/** Presentation only: the physical seven-segment indicator uses fractional end segments. */
inline float SaskartaBatterySegmentFill(float Charge, int Segment)
{
    if (!std::isfinite(Charge) || Segment < 0 || Segment >= 7) return 0.f;
    const float Fill = Charge * 0.07f - static_cast<float>(Segment);
    return Fill < 0.f ? 0.f : (Fill > 1.f ? 1.f : Fill);
}

/** A deliberate look reveals the number; a short glance away does not make it chatter. */
struct FSaskartaBatteryGaze
{
    bool bVisible = false;
    float DwellS = 0.f;
    float AwayS = 0.f;
    void Reset() { bVisible = false; DwellS = AwayS = 0.f; }
    bool Step(float DeltaS, bool bEligible, bool bEnter, bool bStay)
    {
        if (!bEligible) { Reset(); return false; }
        const float Dt = std::isfinite(DeltaS) && DeltaS > 0.f ? (DeltaS > 0.1f ? 0.1f : DeltaS) : 0.f;
        if (!bVisible)
        {
            DwellS = bEnter ? DwellS + Dt : 0.f;
            if (DwellS >= 0.25f) { bVisible = true; AwayS = 0.f; }
        }
        else
        {
            AwayS = bStay ? 0.f : AwayS + Dt;
            if (AwayS >= 0.18f) Reset();
        }
        return bVisible;
    }
};

/** Fixed 12-second history at the existing 10 Hz power timer. No synthetic samples after a hitch. */
struct FSaskartaPowerTelemetry
{
    static constexpr int Capacity = 120;
    std::array<float, Capacity> SpeedKph{};
    std::array<float, Capacity> AltitudeM{};
    std::array<double, Capacity> TimeS{};
    int Count = 0;
    int Next = 0;
    void Reset() { Count = Next = 0; }
    void Push(float SpeedCmS, float WorldZCm, double NowS)
    {
        if (!std::isfinite(SpeedCmS) || !std::isfinite(WorldZCm) || !std::isfinite(NowS)) return;
        if (Count && NowS < TimeS[Index(Count - 1)]) Reset();
        if (Count && NowS <= TimeS[Index(Count - 1)]) return;
        while (Count && TimeS[Index(0)] < NowS - 12.0) --Count;
        SpeedKph[Next] = (SpeedCmS < 0.f ? 0.f : SpeedCmS) * 0.036f;
        AltitudeM[Next] = WorldZCm * 0.01f;
        TimeS[Next] = NowS;
        Next = (Next + 1) % Capacity;
        if (Count < Capacity) ++Count;
    }
    int Index(int OldestFirst) const { return (Next - Count + OldestFirst + Capacity) % Capacity; }
};

struct FSaskartaPowerHudInput
{
    float Charge = 100.f;
    float RatePerS = 0.f;
    bool bLimp = false;
    bool bTurbo = false;
    bool bResting = false;   // stopped long enough to count as a rest (FSaskartaPowerCore::CanRest)
    bool bRadioOn = true;    // the player's radio switch (not the forced archive)
    bool bLampsOn = true;
    float RangeKm = -1.f;    // FSaskartaPowerCore::RangeKm with the current switches; -1 = no limit
    float SecondsToFull = -1.f;
    bool bMotorReady = false; // stationary and eligible to tune the motor
    bool bGamepad = false;
    bool bLow = false;       // below the PWR LOW line (20 %)
    bool bBlink = false;     // legacy field: critical charge; the whole gauge never flashes
    bool bAscii = false;     // '#' for the bar if Font_Terminal ever lacks '|'
    float MotorRpm = -1.f;   // actual carrier RPM property, or -1 when unavailable
    bool bInscriptionReading = false; // the actual Scan caption channel owns the reading area
};

struct FSaskartaPowerHudOutput
{
    std::wstring Line;
    std::wstring Loads; // the line under it; empty = hidden
    float Opacity = 1.f;
};

struct FSaskartaPowerHud
{
    // The previous 40% opacity made the power line disappear against bright terrain.
    static constexpr float DimOpacity = 0.8f;
    static constexpr float BrightAfterChangeS = 5.f;
    static constexpr float ToggleLineS = 3.f;
    static constexpr float NoticeS = 3.f;
    static constexpr float DimAbovePercent = 40.f;
    static constexpr int Cells = 20;

    float BrightForS = BrightAfterChangeS;
    float ToggleForS = 0.f;
    float NoticeForS = 0.f;
    int StateKey = -1;
    int LoadKey = -1;
    std::wstring ToggleLine;
    std::wstring NoticeLine;

    static int Filled(float Charge)
    {
        if (!std::isfinite(Charge) || Charge <= 0.f) return 0;
        const int N = static_cast<int>(Charge / (100.f / Cells) + 0.5f);
        return N < 1 ? 1 : (N > Cells ? Cells : N);
    }

    static std::wstring Bar(float Charge, bool bAscii)
    {
        const int N = Filled(Charge);
        std::wstring Out;
        for (int I = 0; I < Cells; ++I) Out += I < N ? (bAscii ? L'#' : L'|') : L'.';
        return Out;
    }

    /** "RANGE 1.4 KM"; "RANGE 9.9 KM" at most; "RANGE FREE" when the bar never empties. */
    static std::wstring Range(float Km)
    {
        if (!std::isfinite(Km) || Km < 0.f) return L"RANGE FREE";
        wchar_t Buf[32];
        std::swprintf(Buf, 32, L"RANGE %.1f KM", Km > 9.9f ? 9.9f : Km);
        return Buf;
    }

    static std::wstring LineFor(const FSaskartaPowerHudInput& In)
    {
        const float C = std::isfinite(In.Charge) ? (In.Charge < 0.f ? 0.f : (In.Charge > 100.f ? 100.f : In.Charge)) : 0.f;
        wchar_t Pct[16];
        std::swprintf(Pct, 16, L"%3d%%", static_cast<int>(C + 0.5f));
        const std::wstring Line = L"PWR " + Bar(C, In.bAscii) + Pct;
        if (In.bLimp && !In.bResting) return Line + L"  SYSTEM STOPPED . RECHARGE TO 30%";
        if (In.bResting && In.RatePerS > 0.f)
        {
            if (C >= 99.5f || In.SecondsToFull < 0.f) return Line + L"  ^ FULL";
            wchar_t Full[40];
            std::swprintf(Full, 40, L"  ^ FULL IN %d S", static_cast<int>(In.SecondsToFull + 0.5f));
            return Line + Full;
        }
        return Line + L"  " + Range(In.RangeKm);
    }

    /** The second line for this input, without the timed toggle / notice lines. */
    static std::wstring SteadySub(const FSaskartaPowerHudInput& In)
    {
        if (In.bTurbo) return In.bRadioOn ? L"SHIFT BOOST . RADIO DROWNED" : L"SHIFT BOOST . CELL DRAIN";
        if (In.bResting && In.bMotorReady) return In.bGamepad ? L"VIEW . TUNE MOTOR" : L"TAB . TUNE MOTOR";
        if (In.bLow && !In.bLimp && !In.bResting) return L"PWR LOW . STOP TO CHARGE";
        return L"";
    }

    /** A notice from the game (STOP TO TUNE MOTOR), shown NoticeS on the second line. */
    void Notify(const std::wstring& Text, float Seconds = NoticeS)
    {
        NoticeLine = Text;
        NoticeForS = Text.empty() ? 0.f : Seconds;
        BrightForS = BrightAfterChangeS;
    }

    // Call on the power timer (0.1 s). Returns what the widget should show; the caller sets text only
    // when a string changes, so the retainer re-renders on change, never per frame for nothing.
    FSaskartaPowerHudOutput Step(float DeltaS, const FSaskartaPowerHudInput& In)
    {
        const float Dt = std::isfinite(DeltaS) && DeltaS > 0.f ? (DeltaS > 1.f ? 1.f : DeltaS) : 0.f;
        const int NewState = In.bLimp ? 3 : In.bTurbo ? 2 : (In.bResting && In.RatePerS > 0.f) ? 1 : 0;
        const int NewLoads = (In.bRadioOn ? 1 : 0) | (In.bLampsOn ? 2 : 0);
        if (NewState != StateKey) { BrightForS = BrightAfterChangeS; StateKey = NewState; }
        if (NewLoads != LoadKey)
        {
            if (LoadKey >= 0)
            {
                const bool bRadioChanged = ((NewLoads ^ LoadKey) & 1) != 0;
                ToggleLine = bRadioChanged ? (In.bRadioOn ? L"RADIO ON . " : L"RADIO OFF . ") : (In.bLampsOn ? L"LAMPS ON . " : L"LAMPS OFF . ");
                ToggleLine += Range(In.RangeKm);
                ToggleForS = ToggleLineS;
            }
            BrightForS = BrightAfterChangeS;
            LoadKey = NewLoads;
        }
        BrightForS = BrightForS > Dt ? BrightForS - Dt : 0.f;
        ToggleForS = ToggleForS > Dt ? ToggleForS - Dt : 0.f;
        NoticeForS = NoticeForS > Dt ? NoticeForS - Dt : 0.f;
        if (NoticeForS <= 0.f) NoticeLine.clear();

        FSaskartaPowerHudOutput Out;
        Out.Line = LineFor(In);
        if (NoticeForS > 0.f) Out.Loads = NoticeLine;
        else if (ToggleForS > 0.f) Out.Loads = ToggleLine;
        else Out.Loads = SteadySub(In);
        const bool bSteady = BrightForS <= 0.f && NewState == 0 && In.Charge > DimAbovePercent && Out.Loads.empty();
        Out.Opacity = bSteady ? DimOpacity : 1.f;
        return Out;
    }
};
