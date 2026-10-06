// Storm shells, the pure part (task STORM-SHELLS). See SaskartaStormShells.h for the subsystem and
// docs/look/STORM_SHELLS.md for the recipe.
//
// Engine-free and deterministic, so the Saskarta.StormShells.* automation tests drive it directly:
//   - NextGate: the StormIntensity hysteresis that puts the post-process pass in or out of the frame.
//   - TierFor: the saskarta.stormshells / .layers / .detail cvars -> shells drawn and shells with detail.
//   - The shader math mirrored from Shaders/StormShells.ush (far root, height band, gust drift, layer alpha,
//     storm response), so the tests pin the formulas the material runs. Keep them in step with the .ush
//     and with Tools/Look/storm_shells/shells_model.py.

#pragma once

#include "CoreMinimal.h"

/** How many shells the material draws, and how many of them (nearest first) get the detail octave. */
struct FSaskartaStormShellTier
{
    int32 Shells = 4;
    int32 DetailShells = 3;

    bool operator==(const FSaskartaStormShellTier& O) const { return Shells == O.Shells && DetailShells == O.DetailShells; }
    bool operator!=(const FSaskartaStormShellTier& O) const { return !(*this == O); }
};

namespace SaskartaStormShells
{
    inline constexpr int32 MaxShells = 4;
    inline constexpr float GateOffBelow = 0.005f;   // StormIntensity at or below which the pass leaves the frame
    inline constexpr float GateOnAbove = 0.015f;    // StormIntensity above which it comes back
    inline constexpr float MinHorizontal = 1.0e-3f; // |d.xy| clamp: zenith and nadir rays stay finite

    /** The gate with hysteresis: on above OnAbove, off at or below OffBelow, unchanged between. */
    SASKARTACORE_API bool NextGate(bool bWasOn, float StormIntensity, float OffBelow = GateOffBelow, float OnAbove = GateOnAbove);

    /** The cvars -> tier. Enabled 0 (or Layers <= 0) gives 0 shells; Layers clamps to 1..4, Detail to 0..Shells. */
    SASKARTACORE_API FSaskartaStormShellTier TierFor(int32 Enabled, int32 Layers, int32 Detail);

    /** The PPV weight: 1 when the gate is on and the tier draws anything, else 0 (never in between). */
    SASKARTACORE_API float PassWeight(bool bGateOn, const FSaskartaStormShellTier& Tier);

    /** Distance along the unit ray Dir from the axis to the vertical cylinder of radius R (the far root). */
    SASKARTACORE_API float FarRootCentered(const FVector3f& Dir, float R);

    /** The general far root with the camera at Offset (horizontal, from the axis, inside the cylinder). */
    SASKARTACORE_API float FarRootOffset(const FVector2f& Offset, const FVector3f& Dir, float R);

    /** The height band: Band = (eye height, halving height, top, depth below), all m; H above the ground, m. */
    SASKARTACORE_API float HeightProfile(float H, const FVector4f& Band);

    /** The two-sine gust (DustVolume.hlsl), -1..1. */
    SASKARTACORE_API double Gust(double TimeS, double PeriodS);

    /** Metres downwind the dust field has moved: Speed (t + Amp * integral of Gust); its rate is Speed (1 + Amp Gust). */
    SASKARTACORE_API double GustDriftM(double TimeS, double SpeedMps, double Amp, double PeriodS);

    /** One shell's alpha: 1 - exp(-Sigma * Storm * Slab * PathK * N * GustK * Prof * Vis). */
    SASKARTACORE_API float LayerAlpha(float Sigma, float Storm, float SlabM, float PathK, float N, float GustK, float Prof, float Vis);

    /** The material's storm input: StormIntensity^Exponent * Scale (StormIntensity clamped to 0..1). */
    SASKARTACORE_API float StormResponse(float StormIntensity, float Exponent, float Scale);
}
