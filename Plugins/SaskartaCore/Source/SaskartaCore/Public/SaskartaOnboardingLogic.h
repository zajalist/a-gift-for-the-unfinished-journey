// Onboarding hints: the pure scheduler. Engine-free (FName, containers, FString, Json), so the
// Saskarta.Onboarding.* tests drive it directly. USaskartaOnboarding (SaskartaOnboarding.h) computes the
// named conditions and actions from the game every 0.25 s and shows what Step decides in the gameplay overlay.
//
// Data: docs/story/onboarding.json (ParseJson). Each hint has
//   when        conditions that must all hold (names the C++ computes; the JSON's "conditions" lists them)
//   road_m      optional [from, to] road window (-1 = open end)
//   delay_s     how long the trigger must have held before the hint may show
//   after       hint ids that must have been shown first
//   done_when   tokens that dismiss it at once: a condition or action name, or "!name" (that condition is false)
//   skip_if_known  a done_when name already seen this session: the hint is marked shown and never appears
//   hold_s, priority
//
// Rules (Step):
//   - one hint at a time; one show or hide per step;
//   - first time only: a shown hint is in Seen (saved) and never shows again;
//   - never while blocked (a story line, a cinematic, the ending, another prompt, the route map); a hint
//     that gets blocked is hidden at once, and if it was up for less than MinReadS it may come back;
//   - dismissed the moment a done_when token holds, or after hold_s (8 s);
//   - GapS of quiet between two hints; the highest priority wins, then file order.

#pragma once

#include "CoreMinimal.h"

struct SASKARTACORE_API FSaskartaHintDef
{
    FName Id;
    /** Keyboard and mouse. */
    FString Text;
    /** Gamepad (empty = Text). */
    FString PadText;
    TArray<FName> When;
    float FromRoadM = -1.f;
    float ToRoadM = -1.f;
    float DelayS = 0.f;
    TArray<FName> After;
    TArray<FName> DoneWhen;
    bool bSkipIfKnown = false;
    float HoldS = 8.f;
    int32 Priority = 0;
};

/** What the game looks like this step (built by USaskartaOnboarding). */
struct SASKARTACORE_API FSaskartaHintFacts
{
    double NowS = 0.0;
    /** -1 when unknown (off the road, no runner). */
    float RoadM = -1.f;
    bool bBlocked = false;
    /** States that hold now ("playing", "moving", "charging" ...). */
    TSet<FName> Conditions;
    /** Things the player did since the last step ("radio_toggled", "map_opened" ...). */
    TSet<FName> Actions;
};

enum class ESaskartaHintEvent : uint8
{
    None,
    Show,
    Hide,
};

struct SASKARTACORE_API FSaskartaHintStep
{
    ESaskartaHintEvent Event = ESaskartaHintEvent::None;
    /** Index into Hints. */
    int32 Hint = INDEX_NONE;
    /** Hide: "done", "timeout" or "blocked". */
    FName Reason;
};

struct SASKARTACORE_API FSaskartaOnboardingCore
{
    TArray<FSaskartaHintDef> Hints;
    /** Hint ids shown (or skipped as known): saved, never shown again. */
    TSet<FName> Seen;
    /** Every action and condition name seen this session (skip_if_known). */
    TSet<FName> Known;
    /** Hint id -> when its trigger started holding. */
    TMap<FName, double> TrueSinceS;
    int32 Active = INDEX_NONE;
    double ActiveSinceS = 0.0;
    double LastHideS = -1.0e9;
    float GapS = 3.f;
    float MinReadS = 1.5f;

    FSaskartaHintStep Step(const FSaskartaHintFacts& Facts);

    int32 FindHint(FName Id) const;
    bool IsActive() const { return Active != INDEX_NONE; }
    const FSaskartaHintDef* ActiveHint() const { return Hints.IsValidIndex(Active) ? &Hints[Active] : nullptr; }

    /** When conditions and the road window. */
    static bool TriggerHolds(const FSaskartaHintDef& Hint, const FSaskartaHintFacts& Facts);
    /** "name" holds when it is a condition or an action this step; "!name" when that condition does not hold. */
    static bool TokenHolds(FName Token, const FSaskartaHintFacts& Facts);
    static bool IsDone(const FSaskartaHintDef& Hint, const FSaskartaHintFacts& Facts);
    static FString TextFor(const FSaskartaHintDef& Hint, bool bGamepad);

    /** Reads onboarding.json: the hints, gap_s and default hold_s. False (and OutError) when malformed. */
    bool ParseJson(const FString& Json, FString& OutError);
};
