#pragma once

#include <algorithm>
#include <cmath>

// One clock and one attempt per cue, shared by the recharge lesson and dust pursuit.
// Engine-free so input edges, timing, rewards and suppression can be replayed exactly.
struct FSaskartaMotorResonanceLogic
{
    enum class EMode { None, Tuning, Pursuit };
    enum class EKey { Beat, Left, Right };
    enum class EFeedback { None, Perfect, Good, Early, Late, Miss, Balanced, WrongSide };

    static constexpr double GoodWindowS = 0.22;
    static constexpr double PerfectWindowS = 0.085;
    static constexpr double BalanceWindowS = 0.25;
    static constexpr int LessonBeats = 12;
    static constexpr float MinDrive = 0.65f;
    static constexpr float MaxDrive = 1.5f;

    EMode Mode = EMode::None;
    EFeedback Feedback = EFeedback::None;
    double ElapsedS = 0.0;
    double NextBeatS = 1.2;
    double NextBalanceS = 4.2;
    double PeriodS = 1.2;
    double FeedbackUntilS = 0.0;
    double TimingErrorS = 0.0;
    float Drive = 0.9f;
    float EarnedCharge = 0.f;
    float PendingCharge = 0.f;
    int CompletedBeats = 0;
    int GoodBeats = 0;
    int BalanceIndex = 0;
    bool bBeatJudged = false;
    bool bBalanceJudged = false;
    bool bSuppressed = true;
    bool bComplete = false;
    // An empty carrier remains parked. Its pursuit inputs crank the generator
    // until the power subsystem releases the existing restart threshold.
    bool bRecoveringCell = false;
    bool Held[3] = {false, false, false};

    bool IsActive() const { return Mode != EMode::None; }
    bool IsTuning() const { return Mode == EMode::Tuning; }
    bool WantsLeft() const { return BalanceIndex % 2 == 0; }
    bool BalanceVisible() const { return IsActive() && !bBalanceJudged && NextBalanceS - ElapsedS <= 0.7; }
    bool BeatWindowOpen() const { return !bBeatJudged && std::abs(ElapsedS - NextBeatS) <= GoodWindowS; }
    float DriveMultiplier() const { return Mode == EMode::Pursuit && !bSuppressed ? Drive : 1.f; }
    float BeatPosition() const
    {
        // Target at 80% of the lane, leaving visible room for late presses.
        return static_cast<float>(std::clamp(0.8 + 0.8 * (ElapsedS - NextBeatS) / PeriodS, 0.0, 1.0));
    }

    void Begin(EMode InMode)
    {
        *this = FSaskartaMotorResonanceLogic();
        Mode = InMode;
        PeriodS = InMode == EMode::Tuning ? 1.2 : 1.0;
        NextBeatS = PeriodS;
        NextBalanceS = PeriodS * 3.5;
    }
    void End() { *this = FSaskartaMotorResonanceLogic(); }

    void Result(EFeedback InFeedback, double Error = 0.0)
    {
        Feedback = InFeedback;
        TimingErrorS = Error;
        FeedbackUntilS = ElapsedS + 0.7;
    }
    void Adjust(float Delta) { Drive = std::clamp(Drive + Delta, MinDrive, MaxDrive); }
    void Reward(float Charge)
    {
        if (!IsTuning() && !(Mode == EMode::Pursuit && bRecoveringCell)) return;
        PendingCharge += Charge;
        EarnedCharge += Charge;
    }
    float TakeChargeReward()
    {
        const float Reward = PendingCharge;
        PendingCharge = 0.f;
        return Reward;
    }

    // Pauses, menus and cinematics freeze the timeline and its score. A render stall
    // above half a second also freezes one update instead of issuing a burst of misses.
    void Advance(double DeltaS, bool bBlocked)
    {
        bSuppressed = bBlocked;
        if (!IsActive() || bComplete || bBlocked || !std::isfinite(DeltaS) || DeltaS <= 0.0 || DeltaS > 0.5) return;
        ElapsedS += DeltaS;
        while (ElapsedS > NextBeatS + GoodWindowS)
        {
            if (!bBeatJudged) { Adjust(-0.14f); Result(EFeedback::Miss); }
            ++CompletedBeats;
            NextBeatS += PeriodS;
            bBeatJudged = false;
            if (IsTuning() && CompletedBeats >= LessonBeats)
            {
                bComplete = true;
                return;
            }
        }
        while (ElapsedS > NextBalanceS + BalanceWindowS)
        {
            if (!bBalanceJudged) { Adjust(-0.12f); Result(EFeedback::WrongSide); }
            NextBalanceS += PeriodS * 4.0;
            ++BalanceIndex;
            bBalanceJudged = false;
        }
        if (ElapsedS > FeedbackUntilS) Feedback = EFeedback::None;
    }

    // Key release is processed even during suppression. Repeats and a held key never
    // count twice, and a menu-held key must be released before it can earn a reward.
    bool Input(EKey Key, bool bDown)
    {
        const int Index = static_cast<int>(Key);
        const bool bNewPress = bDown && !Held[Index];
        Held[Index] = bDown;
        if (!bNewPress || !IsActive() || bComplete || bSuppressed) return false;
        if (Key == EKey::Beat)
        {
            if (bBeatJudged) return false;
            // A just-late tap belongs to the missed beat, not the next one. The
            // clock already applied that miss; do not double-penalize or consume
            // the upcoming cue before the player can see it approach.
            if (CompletedBeats > 0 && ElapsedS < NextBeatS - PeriodS * 0.5)
            {
                Result(EFeedback::Late, ElapsedS - (NextBeatS - PeriodS));
                return true;
            }
            bBeatJudged = true;
            const double Error = ElapsedS - NextBeatS;
            if (std::abs(Error) <= GoodWindowS)
            {
                const bool bPerfect = std::abs(Error) <= PerfectWindowS;
                ++GoodBeats;
                Adjust(bPerfect ? 0.11f : 0.065f);
                // The front reaches a stationary car in about ten seconds.
                // Emergency cranking must restart it with ordinary good beats,
                // leaving time to accelerate; the longer tuning lesson keeps
                // its original charge awards.
                Reward(bRecoveringCell ? (bPerfect ? 5.f : 4.f) : (bPerfect ? 2.5f : 1.5f));
                Result(bPerfect ? EFeedback::Perfect : EFeedback::Good, Error);
            }
            else
            {
                Adjust(-0.14f);
                Result(Error < 0.0 ? EFeedback::Early : EFeedback::Late, Error);
            }
            return true;
        }
        if (!BalanceVisible() || bBalanceJudged) return false;
        bBalanceJudged = true;
        const double Error = ElapsedS - NextBalanceS;
        const bool bCorrect = (Key == EKey::Left) == WantsLeft();
        if (bCorrect && std::abs(Error) <= BalanceWindowS)
        {
            Adjust(0.08f);
            Reward(bRecoveringCell ? 2.f : 1.f);
            Result(EFeedback::Balanced, Error);
        }
        else
        {
            Adjust(-0.12f);
            Result(!bCorrect ? EFeedback::WrongSide : Error < 0.0 ? EFeedback::Early : EFeedback::Late, Error);
        }
        return true;
    }
};
