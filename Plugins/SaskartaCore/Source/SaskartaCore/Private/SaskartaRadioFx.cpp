// FSaskartaRadioFxLogic and FSaskartaRadioStoryState. See the header.

#include "SaskartaRadioFx.h"

// ============================================================================ story lines

ESaskartaRadioLineKind FSaskartaRadioFxLogic::ClassifyLine(FName LineId, bool bCarrier, int32 BeatPriority)
{
    const FString Id = LineId.ToString();
    if (bCarrier || Id.StartsWith(TEXT("CV_")))
    {
        return ESaskartaRadioLineKind::Carrier;
    }
    if (Id.StartsWith(TEXT("RADIO_")) || (BeatPriority >= 0 && BeatPriority <= 2))
    {
        return ESaskartaRadioLineKind::Archive;
    }
    return ESaskartaRadioLineKind::None;
}

FSaskartaRadioStoryStep FSaskartaRadioStoryState::OnLineStart(ESaskartaRadioLineKind Kind, FName BeatId, bool bStationPlaying, bool bPlayingSong,
    float SongPosS, double NowS, float LineS)
{
    FSaskartaRadioStoryStep Step;
    switch (Kind)
    {
    case ESaskartaRadioLineKind::Carrier:
        // A carrier line over the station: duck only (never forced on, never cut).
        if (bStationPlaying && !bDucked && !bArchiveLineActive)
        {
            bDucked = true;
            Step.bDuck = true;
        }
        break;
    case ESaskartaRadioLineKind::Archive:
        if (!bForced)
        {
            bForced = true;
            Step.bForcedOn = true;
        }
        ForcedBeat = BeatId;
        bArchiveLineActive = true;
        ReleaseAtS = FMath::Max(ReleaseAtS, NowS + FMath::Max(0.f, LineS) + FSaskartaRadioFxLogic::ForceReleaseHoldS);
        if (bDucked)
        {
            bDucked = false; // the cut replaces the duck
        }
        if (bStationPlaying && !bInterrupted)
        {
            bInterrupted = true;
            bSongInterrupted = bPlayingSong;
            SongPositionS = bPlayingSong ? FMath::Max(0.f, SongPosS) : 0.f;
            Step.bInterrupt = true;
        }
        break;
    default:
        // Unclassified story line: the station yields (cut; after the line a song resumes, else a new segment).
        if (bStationPlaying && !bInterrupted)
        {
            bInterrupted = true;
            bSongInterrupted = bPlayingSong;
            SongPositionS = bPlayingSong ? FMath::Max(0.f, SongPosS) : 0.f;
            Step.bInterrupt = true;
        }
        break;
    }
    return Step;
}

FSaskartaRadioStoryStep FSaskartaRadioStoryState::OnLineEnd(double NowS)
{
    FSaskartaRadioStoryStep Step;
    if (bDucked)
    {
        bDucked = false;
        Step.bUnduck = true;
    }
    if (bArchiveLineActive)
    {
        bArchiveLineActive = false;
        // The force holds ForceReleaseHoldS past the line's end (never shorter than announced).
        ReleaseAtS = FMath::Max(ReleaseAtS, NowS + FSaskartaRadioFxLogic::ForceReleaseHoldS);
    }
    if (!bForced && bInterrupted)
    {
        // An unclassified line's cut: the programme goes on (a new segment).
        Step.bResume = true;
        Step.bResumeSong = bSongInterrupted;
        bInterrupted = false;
        bSongInterrupted = false;
    }
    return Step;
}

FSaskartaRadioStoryStep FSaskartaRadioStoryState::Tick(double NowS)
{
    FSaskartaRadioStoryStep Step;
    if (bArchiveLineActive && ReleaseAtS >= 0.0 && NowS >= ReleaseAtS + FSaskartaRadioFxLogic::StaleLineS)
    {
        // The line's end was never reported (a stopped runner): do not hold the radio for ever.
        bArchiveLineActive = false;
    }
    if (bForced && !bArchiveLineActive && NowS >= ReleaseAtS)
    {
        bForced = false;
        ForcedBeat = NAME_None;
        ReleaseAtS = -1.0;
        Step.bForcedOff = true;
        Step.bResume = true;
        Step.bResumeSong = bInterrupted && bSongInterrupted;
        bInterrupted = false;
        bSongInterrupted = false;
    }
    return Step;
}

// ============================================================================ imperfections

float FSaskartaRadioFxLogic::EffectiveSignal(const FSaskartaRadioGlitchParams& P, float Quality, float StormIntensity)
{
    const float Storm = FMath::Clamp(StormIntensity, 0.f, 1.f);
    return FMath::Clamp(FMath::Clamp(Quality, 0.f, 1.f) * (1.f - FMath::Clamp(P.StormSignalLoss, 0.f, 1.f) * Storm), 0.f, 1.f);
}

float FSaskartaRadioFxLogic::MeanIntervalS(const FSaskartaRadioGlitchParams& P, float Quality, float StormIntensity, bool bArchiveLine)
{
    const float S = EffectiveSignal(P, Quality, StormIntensity);
    const float Weak = FMath::Max(0.05f, P.WeakMeanIntervalS);
    const float Strong = FMath::Max(Weak, P.StrongMeanIntervalS);
    // Log-linear: halfway signal is the geometric mean (about 10 s with the defaults).
    const float Mean = FMath::Exp(FMath::Lerp(FMath::Loge(Weak), FMath::Loge(Strong), S));
    return bArchiveLine ? Mean * FMath::Max(1.f, P.ArchiveIntervalScale) : Mean;
}

double FSaskartaRadioFxLogic::NextGlitchAtS(const FSaskartaRadioGlitchParams& P, float Quality, float StormIntensity, bool bArchiveLine, double NowS,
    FRandomStream& Rand)
{
    const float Mean = MeanIntervalS(P, Quality, StormIntensity, bArchiveLine);
    return NowS - FMath::Loge(FMath::Max(1.0e-4f, Rand.FRand())) * Mean;
}

FSaskartaRadioGlitchEvent FSaskartaRadioFxLogic::DrawGlitch(const FSaskartaRadioGlitchParams& P, float Quality, float StormIntensity, bool bArchiveLine,
    FRandomStream& Rand)
{
    auto InRange = [&Rand](const FVector2f& R) { return Rand.FRandRange(FMath::Min(R.X, R.Y), FMath::Max(R.X, R.Y)); };
    const float S = EffectiveSignal(P, Quality, StormIntensity);
    const float Weakness = 1.f - S;
    FSaskartaRadioGlitchEvent E;

    if (bArchiveLine)
    {
        // Story / archive lines are immune to dropouts: light crackle only.
        E.Type = ESaskartaRadioGlitch::Crackle;
        E.DurationS = InRange(P.CrackleSecondsRange);
        E.Intensity = FMath::Clamp(P.ArchiveCrackleIntensity, 0.f, 1.f) * (0.5f + 0.5f * Rand.FRand());
        return E;
    }

    // Weights: crackle and jitter at any signal; dropouts, bursts and drift grow as it weakens; squeals are rare and only when weak.
    float W[6];
    W[static_cast<int32>(ESaskartaRadioGlitch::Dropout)] = 0.3f + 3.f * Weakness;
    W[static_cast<int32>(ESaskartaRadioGlitch::Crackle)] = 3.f;
    W[static_cast<int32>(ESaskartaRadioGlitch::NoiseBurst)] = 0.2f + 2.f * Weakness;
    W[static_cast<int32>(ESaskartaRadioGlitch::PitchJitter)] = 2.f;
    W[static_cast<int32>(ESaskartaRadioGlitch::Drift)] = 0.2f + 1.5f * Weakness;
    float Others = 0.f;
    for (int32 i = 0; i < 5; ++i)
    {
        Others += W[i];
    }
    const float SquealScale = P.SquealMaxQuality > 0.f ? FMath::Clamp(1.f - S / P.SquealMaxQuality, 0.f, 1.f) : 0.f;
    W[static_cast<int32>(ESaskartaRadioGlitch::Squeal)] = FMath::Max(0.f, P.SquealWeight) * Others * SquealScale;
    float Total = 0.f;
    for (float X : W)
    {
        Total += X;
    }
    float Pick = Rand.FRand() * Total;
    int32 Index = 0;
    for (; Index < 5; ++Index)
    {
        if (Pick < W[Index])
        {
            break;
        }
        Pick -= W[Index];
    }
    E.Type = static_cast<ESaskartaRadioGlitch>(Index);
    switch (E.Type)
    {
    case ESaskartaRadioGlitch::Dropout:
        E.DurationS = InRange(P.DropoutSecondsRange) * (0.5f + Weakness);
        E.Intensity = FMath::Lerp(0.4f, 1.f, Weakness);
        break;
    case ESaskartaRadioGlitch::Crackle:
        E.DurationS = InRange(P.CrackleSecondsRange);
        E.Intensity = FMath::Clamp(0.2f + 0.6f * Weakness * Rand.FRand() + 0.2f * Rand.FRand(), 0.f, 1.f);
        break;
    case ESaskartaRadioGlitch::NoiseBurst:
        E.DurationS = InRange(P.NoiseBurstSecondsRange);
        E.Intensity = FMath::Lerp(0.3f, 1.f, Weakness);
        break;
    case ESaskartaRadioGlitch::PitchJitter:
        E.DurationS = InRange(P.CrackleSecondsRange) * 2.f;
        E.Intensity = 0.5f;
        E.PitchOffset = Rand.FRandRange(-1.f, 1.f) * FMath::Abs(P.PitchJitter);
        break;
    case ESaskartaRadioGlitch::Drift:
        E.DurationS = InRange(P.DriftSecondsRange);
        E.Intensity = FMath::Lerp(0.3f, 1.f, Weakness);
        E.PitchOffset = (Rand.FRand() < 0.5f ? -1.f : 1.f) * FMath::Abs(P.DriftDetune) * FMath::Lerp(0.4f, 1.f, Rand.FRand());
        break;
    case ESaskartaRadioGlitch::Squeal:
    default:
        E.Type = ESaskartaRadioGlitch::Squeal;
        E.DurationS = InRange(P.SquealSecondsRange);
        E.Intensity = FMath::Lerp(0.5f, 1.f, Weakness);
        break;
    }
    return E;
}
