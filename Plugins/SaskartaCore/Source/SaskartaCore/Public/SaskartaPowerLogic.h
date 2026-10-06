#pragma once

#include <algorithm>
#include <cmath>

// The carrier's biofuel charge (docs/design/ROUTE_BOARD_V3.md, POWER). Percent of the bar per second; never a
// hard fail. No engine dependencies, so the timer, the save game, the CRT line and the offline smoke
// (Tools/Power/power_core_smoke.cpp) share one rule set.
//
//   depleted handover 35%; generator +1.0; DRIVE (motor + capsule) 1.08 at 5 m/s on the flat,
//   grade scaled; radio 0.15, lamps 0.10,
//   turbo 2.5; at rest the generator gives +1.5 before loads (+1.25 with radio and lamps on).
//   Moving net drain is x MovingDrainScale (0.4): range at 5 m/s from full, all on ~3.75 km, radio off ~7.
//   Empty (0 %): the carrier stops. The saved bLimp latch remains for compatibility and releases at 30 %.
//   Turbo is locked; radio and lamps stay as the player left them. Passive recharge works while parked.
//   Explicit narrative replay runs the radio load while it plays.
struct FSaskartaPowerTuning
{
    // The dock gives the carrier a depleted handover cell. At normal cruise the first stop
    // is needed near the early road sites, before the first motor-tuning stop.
    float InitialChargePercent = 55.f;
    float GeneratorPerS = 1.f;
    // A slow moving carrier can otherwise be net-neutral (or net-positive) because the
    // generator exceeds the low-speed motor load. Movement must still spend charge.
    // 0.08 matches the existing all-off flat cruise drain at 5 m/s.
    float MinimumMovingDrainPerS = 0.08f;
    float RestBonusPerS = 0.5f;   // stopped RestAfterS: the generator runs free of the drive
    float RadioPerS = 0.15f;
    float LampsPerS = 0.1f;
    float MotorBasePerS = 0.68f;  // motor + capsule while moving
    float MotorSpeedPerS = 0.08f; // per m/s: 0.68 + 0.08 * 5 = 1.08
    float UphillFactor = 0.8f;
    float TurboPerS = 2.5f;
    // 2026-10-05: the bar emptied far too fast on the road. Every net drain while moving (drive, loads,
    // turbo, after the generator) is scaled by this: all-on range 1.5 km -> ~3.75 km, turbo from full ~90 s.
    float MovingDrainScale = 0.4f;
    float LimpExitPercent = 30.f;
    float LimpSpeedMps = 0.f; // legacy tuning field; empty-cell travel is always prohibited
    float RestAfterS = 0.6f;   // 2026-10-05: 2 s felt like Tab was broken
    float CruiseMps = 5.f;        // RangeKm's reference speed (the carrier's usual cruise)
    float LowPercent = 20.f;      // PWR LOW
    float BlinkPercent = 10.f;    // legacy name: critical warning, no flashing whole gauge
    float PinMinPercent = 10.f;
    float WrongPinPercent = 10.f;
    float MachineMatchPercent = 25.f;
};

struct FSaskartaPowerInput
{
    float DeltaS = 0.f;
    float SpeedMps = 0.f;
    float Grade = 0.f; // rise / horizontal run; negative is downhill
    bool bPlaying = false;
    bool bCinematic = false;
    bool bRadioRequested = true;
    bool bRadioForced = false;
    bool bLampsRequested = true;
    bool bTurboHeld = false;
    bool bListening = false; // a narrative clip is replaying: the radio load runs
};

struct FSaskartaPowerSaveState
{
    float Charge = 35.f;
    float StoppedForS = 0.f;
    bool bLimp = false;
    bool bFirstRechargeComplete = false;
};

struct FSaskartaPowerCore
{
    FSaskartaPowerTuning Tuning;
    float Charge = 35.f;
    float StoppedForS = 0.f;
    float LastRatePerS = 0.f;
    bool bLimp = false;
    bool bTurbo = false;
    bool bFirstRechargeComplete = false;

    bool CanRest() const { return StoppedForS >= Tuning.RestAfterS; }
    bool IsCharging() const { return CanRest() && LastRatePerS > 0.f && Charge < 99.5f; }
    bool CanTurbo() const { return !bLimp && Charge > 0.f; }
    bool IsLow() const { return Charge < Tuning.LowPercent; }
    bool CanPin(float MinPercent) const { return Charge >= MinPercent; }
    float SpeedCapMps(float BaseMps, float Grade) const
    {
        if (bLimp || Charge <= 0.f) return 0.f;
        if (bTurbo) return Grade < 0.15f ? 8.f : BaseMps + 2.f;
        return BaseMps;
    }

    float LoadsPerS(bool bRadio, bool bLamps) const
    {
        return (bRadio ? Tuning.RadioPerS : 0.f) + (bLamps ? Tuning.LampsPerS : 0.f);
    }
    float DrivePerS(float Speed, float Grade) const
    {
        if (Speed < 0.3f) return 0.f;
        float Motor = (Tuning.MotorBasePerS + Tuning.MotorSpeedPerS * Speed) * (1.f + Tuning.UphillFactor * std::max(0.f, Grade));
        if (Grade < -0.1f) Motor *= 0.5f;
        return Motor;
    }
    /** Net % per second while stopped for a rest with these loads. */
    float RestRatePerS(bool bRadio, bool bLamps) const
    {
        return Tuning.GeneratorPerS + Tuning.RestBonusPerS - LoadsPerS(bRadio, bLamps);
    }
    /** Net % per second at the reference cruise on the flat with these loads (no turbo). */
    float CruiseRatePerS(bool bRadio, bool bLamps) const
    {
        return Tuning.GeneratorPerS - DrivePerS(Tuning.CruiseMps, 0.f) - LoadsPerS(bRadio, bLamps);
    }
    /** Kilometres left at the reference cruise with these loads; -1 when the bar never empties. */
    float RangeKm(bool bRadio, bool bLamps) const
    {
        const float Net = std::min(CruiseRatePerS(bRadio, bLamps) * Tuning.MovingDrainScale, -Tuning.MinimumMovingDrainPerS);
        return Charge / -Net * Tuning.CruiseMps / 1000.f;
    }
    /** Seconds from now to 100 % at rest with these loads; -1 when the rest does not charge. */
    float SecondsToFull(bool bRadio, bool bLamps) const
    {
        const float Rate = RestRatePerS(bRadio, bLamps);
        if (Rate <= 0.001f) return -1.f;
        return std::max(0.f, 100.f - Charge) / Rate;
    }

    // Forced intermissions use the archive path and never spend player-radio power.
    void Step(const FSaskartaPowerInput& In)
    {
        LastRatePerS = 0.f;
        bTurbo = false;
        if (!In.bPlaying || In.bCinematic || !std::isfinite(In.DeltaS) || In.DeltaS <= 0.f)
        {
            return;
        }
        const float Dt = std::min(In.DeltaS, 0.25f);
        const float Speed = std::isfinite(In.SpeedMps) ? std::max(0.f, In.SpeedMps) : 0.f;
        const float Grade = std::isfinite(In.Grade) ? std::clamp(In.Grade, -2.f, 2.f) : 0.f;
        if (Speed < 0.6f) StoppedForS = std::min(StoppedForS + Dt, 3600.f);
        else StoppedForS = 0.f;

        // A climb may not reach 0.3 m/s without extra torque. Engage the paid
        // boost from a standstill so Shift can start the carrier uphill.
        bTurbo = In.bTurboHeld && CanTurbo();
        const bool bRadio = (In.bRadioRequested && !In.bRadioForced) || In.bListening;
        float Rate = Tuning.GeneratorPerS - LoadsPerS(bRadio, In.bLampsRequested) - DrivePerS(Speed, Grade);
        if (CanRest()) Rate += Tuning.RestBonusPerS;
        if (bTurbo) Rate -= Tuning.TurboPerS;
        // Moving never refills the cell, and the generator may not cancel all motor draw
        // at a crawl. Empty-cell recovery requires a stationary recharge; no travel is provided by
        // the latch itself, even if a save or an external movement supplies a nonzero speed sample.
        if (Speed >= 0.3f)
        {
            if (Rate < 0.f) Rate *= Tuning.MovingDrainScale;
            Rate = std::min(Rate, -Tuning.MinimumMovingDrainPerS);
        }
        LastRatePerS = Rate;
        Charge = std::clamp(Charge + Rate * Dt, 0.f, 100.f);
        if (CanRest() && Charge >= 60.f) bFirstRechargeComplete = true;
        if (Charge <= 0.f) bLimp = true;
        else if (bLimp && Charge >= Tuning.LimpExitPercent) bLimp = false;
        if (bLimp) bTurbo = false;
    }

    bool TrySpend(float Amount)
    {
        if (!std::isfinite(Amount) || Amount < 0.f || Charge < Amount) return false;
        Charge = std::max(0.f, Charge - Amount);
        if (Charge <= 0.f) { bLimp = true; bTurbo = false; }
        return true;
    }

    FSaskartaPowerSaveState Save() const { return {Charge, StoppedForS, bLimp, bFirstRechargeComplete}; }
    void Load(const FSaskartaPowerSaveState& State)
    {
        Charge = std::isfinite(State.Charge) ? std::clamp(State.Charge, 0.f, 100.f) : Tuning.InitialChargePercent;
        StoppedForS = std::isfinite(State.StoppedForS) ? std::clamp(State.StoppedForS, 0.f, 3600.f) : 0.f;
        bLimp = Charge <= 0.f || (State.bLimp && Charge < Tuning.LimpExitPercent);
        bFirstRechargeComplete = State.bFirstRechargeComplete;
        bTurbo = false;
        LastRatePerS = 0.f;
    }
};
