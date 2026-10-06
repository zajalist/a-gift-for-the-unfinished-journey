// The Low Voice's reaction to story lines, and its imperfections (CPPBATCH, 2026-09-28).
//
// Pure logic for USaskartaRadioStation, tested by Saskarta.Station.StoryLines and
// Saskarta.Station.Glitches without a world:
//
// Story lines (the event runner's OnStoryLine):
//  - Archive lines (RADIO_* ids, or a beat of priority Critical / Cinematic / Story) force the
//    radio audible even when the player has switched it off: OnRadioForcedOn(beat) fires, the
//    station's own segment is interrupted with a 0.4 s tune-over, and the player's own on/off
//    choice (USaskartaStorySettings::bRadioStation, never written here) is back in charge
//    ForceReleaseHoldS after the line (OnRadioForcedOff). A song that was cut resumes from its
//    position; anything else is followed by a new segment.
//  - Carrier lines (CV_*) only duck the station (-6 dB) for their length; they never force it on.
//
// Imperfections: a Poisson scheduler of dropouts, crackle, noise bursts, pitch jitter, drift
// (detune episodes) and rare squeals whose mean interval runs from about 75 s at a strong signal
// down to about 1.5 s at none; storm intensity eats into the signal. During an archive line only
// light crackle is drawn (the story is never dropped). Each glitch is broadcast as
// OnRadioGlitch(type, duration, intensity) so the RADIOFX one-shots and submix parameters in
// Blueprint can follow it.
//
// No U/F name pairs: the reflected types are ESaskartaRadioLineKind, ESaskartaRadioGlitch and
// FSaskartaRadioGlitchParams; the logic is the plain FSaskartaRadioFxLogic / FSaskartaRadioStoryState.

#pragma once

#include "CoreMinimal.h"
#include "Math/RandomStream.h"
#include "SaskartaRadioFx.generated.h"

/** How the station treats a story line. */
UENUM(BlueprintType)
enum class ESaskartaRadioLineKind : uint8
{
    /** Not a story line (or unknown): the old behaviour (the station yields). */
    None,
    /** A story / archive line: forces the radio audible, interrupts the station. */
    Archive,
    /** A carrier line: ducks the station -6 dB, never forces it on. */
    Carrier
};

/** One imperfection of the signal. */
UENUM(BlueprintType)
enum class ESaskartaRadioGlitch : uint8
{
    Dropout,
    Crackle,
    NoiseBurst,
    PitchJitter,
    Drift,
    Squeal
};

/** Tuning of the imperfection scheduler (the station's GlitchParams; BP may change it). */
USTRUCT(BlueprintType)
struct SASKARTACORE_API FSaskartaRadioGlitchParams
{
    GENERATED_BODY()

    /** Mean seconds between glitches at full signal and no storm (about one per 60-90 s). */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Radio")
    float StrongMeanIntervalS = 75.f;

    /** Mean seconds between glitches with no signal (near-constant). */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Radio")
    float WeakMeanIntervalS = 1.5f;

    /** How much of the signal a full storm takes away (effective q = q x (1 - this x storm)). */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Radio")
    float StormSignalLoss = 0.4f;

    /** Pitch jitter, +- this fraction (0.005 = 0.5 %). */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Radio")
    float PitchJitter = 0.005f;

    /** Drift episodes detune by up to this fraction, for DriftSecondsRange. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Radio")
    float DriftDetune = 0.02f;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Radio")
    FVector2f DriftSecondsRange = FVector2f(1.f, 3.f);

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Radio")
    FVector2f DropoutSecondsRange = FVector2f(0.08f, 0.6f);

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Radio")
    FVector2f CrackleSecondsRange = FVector2f(0.05f, 0.4f);

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Radio")
    FVector2f NoiseBurstSecondsRange = FVector2f(0.2f, 1.2f);

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Radio")
    FVector2f SquealSecondsRange = FVector2f(0.3f, 0.9f);

    /** Squeal weight at no signal (it falls to 0 at SquealMaxQuality): rare. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Radio")
    float SquealWeight = 0.04f;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Radio")
    float SquealMaxQuality = 0.6f;

    /** Crackle intensity during a story / archive line (light). */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Radio")
    float ArchiveCrackleIntensity = 0.3f;

    /** The archive-line crackle is also this much rarer than the normal schedule. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Radio")
    float ArchiveIntervalScale = 3.f;
};

/** One drawn glitch. */
struct SASKARTACORE_API FSaskartaRadioGlitchEvent
{
    ESaskartaRadioGlitch Type = ESaskartaRadioGlitch::Crackle;
    float DurationS = 0.f;
    /** 0-1: how hard (volume dip, crackle level, burst level). */
    float Intensity = 0.f;
    /** Pitch multiplier offset for PitchJitter and Drift (+-), 0 otherwise. */
    float PitchOffset = 0.f;
};

/** What the station must do after a story-line transition. */
struct SASKARTACORE_API FSaskartaRadioStoryStep
{
    bool bForcedOn = false;
    bool bForcedOff = false;
    /** Cut the station's current item with the tune-over. */
    bool bInterrupt = false;
    /** Duck the station's current item -6 dB. */
    bool bDuck = false;
    bool bUnduck = false;
    /** Resume the interrupted song from its position (else: the next scheduled item). */
    bool bResumeSong = false;
    /** The station's own programme may go on (a new segment or the resumed song). */
    bool bResume = false;
};

/** The story-line state machine (plain; the station owns one). */
struct SASKARTACORE_API FSaskartaRadioStoryState
{
    /** The radio is forced audible for an archive line. */
    bool bForced = false;
    FName ForcedBeat;
    /** When the force ends: line end + ForceReleaseHoldS (extended by further lines). */
    double ReleaseAtS = -1.0;
    /** An archive line is playing now. */
    bool bArchiveLineActive = false;
    /** A carrier duck is on. */
    bool bDucked = false;
    /** The station's item was cut by an archive line; a song part is resumed from SongPositionS. */
    bool bInterrupted = false;
    bool bSongInterrupted = false;
    float SongPositionS = 0.f;

    /**
     * A story line starts. bStationPlaying: the station is playing its own item now;
     * bPlayingSong: that item is a song (its position is kept, SongPosS).
     */
    FSaskartaRadioStoryStep OnLineStart(ESaskartaRadioLineKind Kind, FName BeatId, bool bStationPlaying, bool bPlayingSong, float SongPosS,
        double NowS, float LineS);

    /** The story went quiet (the runner's busy false). */
    FSaskartaRadioStoryStep OnLineEnd(double NowS);

    /** Every update: releases the force once ReleaseAtS has passed with no archive line playing. */
    FSaskartaRadioStoryStep Tick(double NowS);
};

struct SASKARTACORE_API FSaskartaRadioFxLogic
{
    /** The station is audible for the force this long after an archive line ends. */
    static constexpr float ForceReleaseHoldS = 1.5f;
    /** The tune-over that cuts the station for an archive line. */
    static constexpr float TuneOverS = 0.4f;
    /** A carrier line's duck. */
    static constexpr float CarrierDuckDb = -6.f;
    static constexpr float CarrierDuckS = 0.3f;
    /** An archive line whose end never arrives is dropped this long after its announced release. */
    static constexpr float StaleLineS = 30.f;

    /** Archive: a RADIO_* id or a beat of priority <= 2 (Critical, Cinematic, Story). Carrier: bCarrier or a CV_* id. */
    static ESaskartaRadioLineKind ClassifyLine(FName LineId, bool bCarrier, int32 BeatPriority);

    /** q x (1 - StormSignalLoss x storm), clamped 0-1. */
    static float EffectiveSignal(const FSaskartaRadioGlitchParams& P, float Quality, float StormIntensity);

    /** Mean seconds between glitches: log-lerp from WeakMeanIntervalS (signal 0) to StrongMeanIntervalS (signal 1); x ArchiveIntervalScale during an archive line. */
    static float MeanIntervalS(const FSaskartaRadioGlitchParams& P, float Quality, float StormIntensity, bool bArchiveLine);

    /** The next glitch time after NowS (exponential, mean MeanIntervalS). */
    static double NextGlitchAtS(const FSaskartaRadioGlitchParams& P, float Quality, float StormIntensity, bool bArchiveLine, double NowS, FRandomStream& Rand);

    /** Draws a glitch. During an archive line only a light Crackle is drawn (story lines are immune to dropouts). */
    static FSaskartaRadioGlitchEvent DrawGlitch(const FSaskartaRadioGlitchParams& P, float Quality, float StormIntensity, bool bArchiveLine, FRandomStream& Rand);

    /** Only Crackle may touch an archive line. */
    static bool AllowedDuringArchive(ESaskartaRadioGlitch Type) { return Type == ESaskartaRadioGlitch::Crackle; }
};
