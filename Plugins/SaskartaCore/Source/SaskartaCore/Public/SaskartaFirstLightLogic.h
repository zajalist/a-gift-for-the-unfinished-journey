// FSaskartaFirstLight: the First Light ending's pure rules (storyline-first-light.md sections 5-6, VOICE_GUIDE 6.2).
//
// Pure: no world, no UObjects. USaskartaLightingDirector::PlayDawn and USaskartaEventRunner use it:
// - the dawn ramp: the override mix from the PreDawn look to the Dawn look, driven by time (never by road m,
//   never a Timeline). It is piecewise linear so the sun's disc clears the cloud-sea horizon exactly at ClearAtS
//   ("Hold on." -> "...It's come up.") and the ramp ends at DurationS;
// - the SkyLight recapture steps (every RecaptureStepS, never per frame: the render-state stall of 2026-09-28);
// - the caption speaker on the live channel: the replies name nobody (ILAAWB · LIVE), and Samyor has no label
//   (the player learns his name when he says it, "No. Samyor.").

#pragma once

#include "CoreMinimal.h"
#include "SaskartaLookKeys.h"

/** The dawn's end look, on top of whatever the road look shows at the mast (PreDawn). */
struct SASKARTACORE_API FSaskartaDawnParams
{
    /** Sun actor pitch at the end of the ramp (negative = above the horizon): 4 deg up. */
    float EndPitch = -4.f;
    /** Sun actor yaw (the light travels along it: the disc shows at yaw + 180). */
    float SunYaw = 176.5f;
    /** Pitch at which the disc's edge clears the cloud sea on that bearing (measure with render_camera). */
    float HorizonPitch = -0.5f;
    float EndLux = 6.f;
    float EndTemperatureK = 3200.f;
    /** The cloud sea stays; the grade goes fully clear. */
    float EndGradeClear = 1.f;
};

struct SASKARTACORE_API FSaskartaFirstLight
{
    static constexpr float DefaultDurationS = 120.f;
    static constexpr float DefaultClearAtS = 62.f;
    static constexpr float RecaptureStepS = 10.f;
    /** The dawn moves about 0.06 deg/s: four applies a second are plenty (30 Hz would dirty the sky every frame). */
    static constexpr float ApplyIntervalS = 0.25f;

    /** The mix (0 = start look, 1 = dawn look) at which the sun pitch reaches HorizonPitch; 0.5 when undefined. */
    static float ClearMix(float StartPitch, float EndPitch, float HorizonPitch);

    /**
     * Mix at ElapsedS: linear 0 -> ClearMixValue over [0, ClearAtS], then linear to 1 at DurationS.
     * Clamped to [0, 1]; DurationS <= 0 jumps to 1; ClearAtS outside (0, DurationS) falls back to one linear ramp.
     */
    static float DawnMix(float ElapsedS, float DurationS, float ClearAtS, float ClearMixValue);

    /** True when a RecaptureStepS boundary lies in (PrevElapsedS, ElapsedS], or at the very start (PrevElapsedS < 0). */
    static bool RecaptureDue(float PrevElapsedS, float ElapsedS, float StepS = RecaptureStepS);

    /** Start with the sun fields replaced by the dawn's end values (everything else kept: the cloud sea, the fog). */
    static FSaskartaLookKey MakeDawnKey(const FSaskartaLookKey& Start, const FSaskartaDawnParams& Params);

    /** The start look for the ramp: Start with its yaw set to the dawn's, so the lerp never swings the sun round. */
    static FSaskartaLookKey MakeStartKey(const FSaskartaLookKey& Start, const FSaskartaDawnParams& Params);

    /**
     * The caption speaker for a line: BELOW_* -> "ILAAWB · LIVE" (the replies name nobody); SAMYOR_B24_* -> None
     * (no label until he names himself); everything else unchanged.
     */
    static FName CaptionSpeaker(FName LineId, FName Speaker);
};
