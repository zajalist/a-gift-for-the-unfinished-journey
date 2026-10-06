#include "SaskartaMotorResonanceLogic.h"
#include <cstdio>
#include <limits>
#include <vector>

using F = FSaskartaMotorResonanceLogic;
static int Checks = 0, Failures = 0;
static void Check(bool Pass, const char* Name)
{
    ++Checks;
    if (!Pass) { ++Failures; std::printf("FAIL %s\n", Name); }
}
static void Until(F& Core, double Time)
{
    while (Core.ElapsedS + 1e-10 < Time) Core.Advance(std::min(0.1, Time - Core.ElapsedS), false);
}
static void Tap(F& Core, F::EKey Key)
{
    Core.Input(Key, true);
    Core.Input(Key, false);
}
int main()
{
    F Core;
    Check(!Core.IsActive() && Core.DriveMultiplier() == 1.f, "inactive neutral");
    for (const auto Mode : {F::EMode::Tuning, F::EMode::Pursuit})
    {
        for (const double Offset : {-0.23, -0.22, -0.20, -0.085, -0.08, 0.0, 0.08, 0.085, 0.20, 0.22})
        {
            Core.Begin(Mode);
            Until(Core, Core.NextBeatS + Offset);
            Tap(Core, F::EKey::Beat);
            const bool Perfect = std::abs(Offset) <= F::PerfectWindowS;
            const bool Good = std::abs(Offset) <= F::GoodWindowS;
            Check(Core.GoodBeats == (Good ? 1 : 0), "beat timing acceptance");
            Check(Core.Feedback == (Perfect ? F::EFeedback::Perfect : Good ? F::EFeedback::Good : F::EFeedback::Early), "visible timing verdict");
            const float Expected = Mode == F::EMode::Tuning && Good ? (Perfect ? 2.5f : 1.5f) : 0.f;
            Check(Core.TakeChargeReward() == Expected && Core.TakeChargeReward() == 0.f, "charge delivered exactly once; pursuit has no charge reward");
        }
    }
    Core.Begin(F::EMode::Pursuit);
    Until(Core, Core.NextBeatS);
    Check(Core.Input(F::EKey::Beat, true), "first E edge scores");
    Check(!Core.Input(F::EKey::Beat, true), "repeat does not score");
    Until(Core, 2.0);
    Check(!Core.Input(F::EKey::Beat, true) && Core.GoodBeats == 1, "held E cannot score next beat");
    Core.Input(F::EKey::Beat, false);
    Check(Core.Input(F::EKey::Beat, true) && Core.GoodBeats == 2, "release rearms E");
    Core.Input(F::EKey::Beat, false);
    Check(!Core.Input(F::EKey::Beat, true), "one attempt per beat even after release");

    Core.Begin(F::EMode::Pursuit);
    Core.Advance(0.1, false);
    Tap(Core, F::EKey::Beat);
    Until(Core, 1.0);
    Tap(Core, F::EKey::Beat);
    Check(Core.GoodBeats == 0 && Core.bBeatJudged, "spam cannot recover consumed early attempt");
    Core.Begin(F::EMode::Pursuit);
    Until(Core, 30.0);
    Check(Core.Drive == F::MinDrive, "misses reach lower bounded speed");
    Core.Begin(F::EMode::Pursuit);
    Until(Core, 1.23);
    const float AfterMiss = Core.Drive;
    Tap(Core, F::EKey::Beat);
    Check(Core.Feedback == F::EFeedback::Late && !Core.bBeatJudged && Core.Drive == AfterMiss,
          "just-late press does not double punish or consume next beat");
    Until(Core, 2.0);
    Tap(Core, F::EKey::Beat);
    Check(Core.GoodBeats == 1, "recover on next beat after late tap");

    Core.Begin(F::EMode::Pursuit);
    for (int I = 0; I < 30; ++I)
    {
        Until(Core, Core.NextBeatS);
        Tap(Core, F::EKey::Beat);
        Until(Core, Core.NextBeatS + 0.23);
        Check(Core.Drive <= F::MaxDrive && Core.Drive >= F::MinDrive, "drive always bounded");
    }
    Check(Core.Drive > 1.3f, "accurate timing outruns missed timing despite untended balance");

    Core.Begin(F::EMode::Tuning);
    Until(Core, Core.NextBalanceS);
    Check(Core.WantsLeft() && Core.BalanceVisible(), "first balance is left at visible window");
    Tap(Core, F::EKey::Left);
    Check(Core.Feedback == F::EFeedback::Balanced && Core.TakeChargeReward() == 1.f, "A balances at cue");
    Check(!Core.Input(F::EKey::Right, true), "second side cannot score same correction");
    Until(Core, Core.NextBalanceS + 0.26);
    Check(!Core.WantsLeft(), "balance alternates");
    Until(Core, Core.NextBalanceS);
    Tap(Core, F::EKey::Left);
    Check(Core.Feedback == F::EFeedback::WrongSide && Core.TakeChargeReward() == 0.f, "wrong direction never earns charge");

    Core.Begin(F::EMode::Pursuit);
    Until(Core, 0.6);
    const double BeforeTime = Core.ElapsedS;
    const float BeforeDrive = Core.Drive;
    for (int I = 0; I < 100; ++I) Core.Advance(0.1, true);
    Check(Core.ElapsedS == BeforeTime && Core.Drive == BeforeDrive && Core.DriveMultiplier() == 1.f, "menu cinematic pause freeze clock and score");
    Core.Input(F::EKey::Beat, true);
    Until(Core, 1.0);
    Check(!Core.Input(F::EKey::Beat, true) && Core.GoodBeats == 0, "menu-held key must release after resume");
    Core.Input(F::EKey::Beat, false);
    Check(Core.Input(F::EKey::Beat, true) && Core.GoodBeats == 1, "fresh resumed edge scores");
    const double Stable = Core.ElapsedS;
    Core.Advance(5.0, false);
    Core.Advance(std::numeric_limits<double>::quiet_NaN(), false);
    Core.Advance(-1.0, false);
    Check(Core.ElapsedS == Stable, "stall and invalid deltas do not create catch-up penalties");

    Core.Begin(F::EMode::Tuning);
    for (int I = 0; I < F::LessonBeats; ++I)
    {
        Until(Core, Core.NextBeatS);
        Tap(Core, F::EKey::Beat);
        Until(Core, Core.NextBeatS + 0.23);
    }
    Check(Core.bComplete && Core.CompletedBeats == F::LessonBeats && Core.GoodBeats == F::LessonBeats, "short lesson completes after twelve beats");
    Check(Core.EarnedCharge == 30.f && Core.TakeChargeReward() == 30.f, "lesson perfect beats supply real reward amount");
    Check(!Core.Input(F::EKey::Beat, true), "completed lesson cannot farm reward");
    Core.End();
    Check(!Core.IsActive() && !Core.IsTuning() && Core.TakeChargeReward() == 0.f, "cleanup clears session and reward");
    Core.Begin(F::EMode::Pursuit);
    Check(Core.CompletedBeats == 0 && Core.NextBeatS == 1.0 && Core.Drive == 0.9f, "pursuit restart resets sequence");
    auto Lesson = [](double FrameS)
    {
        F Replay;
        Replay.Begin(F::EMode::Tuning);
        std::vector<std::pair<double, F::EKey>> Events;
        for (int I = 1; I <= F::LessonBeats; ++I) Events.emplace_back(1.2 * I, F::EKey::Beat);
        Events.emplace_back(4.2, F::EKey::Left);
        Events.emplace_back(9.0, F::EKey::Right);
        Events.emplace_back(13.8, F::EKey::Left);
        std::sort(Events.begin(), Events.end(), [](const auto& A, const auto& B) { return A.first < B.first; });
        for (const auto& Event : Events)
        {
            while (Replay.ElapsedS + 1e-10 < Event.first)
                Replay.Advance(std::min(FrameS, Event.first - Replay.ElapsedS), false);
            Tap(Replay, Event.second);
        }
        return Replay;
    };
    const F Fast = Lesson(0.016), Slow = Lesson(0.137);
    Check(Fast.GoodBeats == 12 && Fast.EarnedCharge == 33.f, "all beats and three balance corrections earn at most33 percent");
    Check(Fast.GoodBeats == Slow.GoodBeats && Fast.EarnedCharge == Slow.EarnedCharge && Fast.Drive == Slow.Drive,
          "identical event timing gives identical outcome at different frame rates");
    std::printf("Motor resonance: %d checks, %d failures\n", Checks, Failures);
    return Failures ? 1 : 0;
}
