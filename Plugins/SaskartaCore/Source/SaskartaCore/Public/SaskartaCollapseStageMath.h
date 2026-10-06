// The collapse stage's pose math on plain doubles (task COLLAPSE-STAGE). No engine types, so the
// same functions are checked by the Saskarta.Collapse.Stage automation tests and by a standalone
// cl harness while the editor holds the module.
//
// Frames follow the runner's road cinematics (USaskartaEventRunner::StartSequence): the direction
// of travel is toward FALLING spline distance, i.e. -tangent; local +X is up-road, +Y is the
// carrier's right, +Z is up. UE yaw turns +X toward +Y.

#pragma once

#include <cmath>

namespace SaskartaCollapseStageMath
{
    constexpr double Pi = 3.14159265358979323846;

    /** Wraps degrees into (-180, 180]. */
    inline double WrapDeg(double Deg)
    {
        double D = std::fmod(Deg, 360.0);
        if (D <= -180.0) D += 360.0;
        if (D > 180.0) D -= 360.0;
        return D;
    }

    /**
     * The carrier's yaw at the stage: the yaw of -tangent (the direction of travel) plus the authored offset.
     * A (near) zero tangent falls back to the chord Behind -> Ahead reversed (Ahead is farther along the spline).
     */
    inline double TravelYawDeg(double TangentX, double TangentY, double BehindX, double BehindY, double AheadX, double AheadY, double YawOffsetDeg)
    {
        double X = -TangentX;
        double Y = -TangentY;
        if (X * X + Y * Y < 1.0)
        {
            X = BehindX - AheadX;
            Y = BehindY - AheadY;
        }
        const double Base = (X * X + Y * Y) > 0.0 ? std::atan2(Y, X) * 180.0 / Pi : 0.0;
        return WrapDeg(Base + YawOffsetDeg);
    }

    /** Local (Lx up-road, Ly right) at yaw YawDeg around (Cx, Cy) -> world X/Y. */
    inline void LocalToWorld2D(double Cx, double Cy, double YawDeg, double Lx, double Ly, double& OutX, double& OutY)
    {
        const double R = YawDeg * Pi / 180.0;
        const double C = std::cos(R);
        const double S = std::sin(R);
        OutX = Cx + Lx * C - Ly * S;
        OutY = Cy + Lx * S + Ly * C;
    }

    /**
     * The support height under the carrier: the highest of its wheel-column hits, so no wheel sinks into the
     * ground (a lower wheel floats by at most the spread, which OutSpread reports). False when nothing hit.
     */
    inline bool SupportZ(const double* HitZ, const bool* bHit, int Count, double& OutZ, double& OutSpread)
    {
        bool bAny = false;
        double Hi = 0.0;
        double Lo = 0.0;
        for (int I = 0; I < Count; ++I)
        {
            if (!bHit[I] || !std::isfinite(HitZ[I]))
            {
                continue;
            }
            if (!bAny)
            {
                Hi = Lo = HitZ[I];
                bAny = true;
            }
            else
            {
                Hi = HitZ[I] > Hi ? HitZ[I] : Hi;
                Lo = HitZ[I] < Lo ? HitZ[I] : Lo;
            }
        }
        OutZ = Hi;
        OutSpread = bAny ? Hi - Lo : 0.0;
        return bAny;
    }

    /** Ground slope along the heading, deg (+ = climbing): front and rear axle heights RunCm apart. */
    inline double SlopeDeg(double FrontZ, double RearZ, double RunCm)
    {
        return RunCm > 1.0 ? std::atan2(FrontZ - RearZ, RunCm) * 180.0 / Pi : 0.0;
    }

    /** The actor's Z: the support plus the collision half height plus a small clearance. */
    inline double ActorZ(double Support, double HalfHeight, double LiftCm)
    {
        return Support + (HalfHeight > 0.0 ? HalfHeight : 0.0) + (LiftCm > 0.0 ? LiftCm : 0.0);
    }

    /** The snap is covered (black, then a fade in) when the carrier moves more than BeyondM. */
    inline bool NeedsCover(double DistanceCm, double BeyondM)
    {
        return DistanceCm > (BeyondM > 0.0 ? BeyondM : 0.0) * 100.0;
    }
}
