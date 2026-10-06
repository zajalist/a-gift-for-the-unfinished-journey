// FSaskartaPromptLogic: pure rules for the runner's story prompts (the ending's latch, Rise., the lamp,
// the hand) and the ending's data-layer reveal. The runner (SaskartaEventRunnerPrompt.cpp) applies them;
// Saskarta.Prompt tests drive them directly.
//
// The packaged playtest of 2026-09-29 stopped on the collapse's black CRT: B18's prompt "Release the
// inner latch." was broadcast to the caption widget (UMG ZOrder 40), which sits under the boot-log black
// (ZOrder 100, opacity 1), so the player never saw what to press. The runner now types the prompt onto
// the CRT when the black is up, re-shows it on a timer, and draws its own line above every HUD widget
// once the prompt has waited FirstRemindS, so no prompt can leave the player on a dead screen.

#pragma once

#include "CoreMinimal.h"

struct FSaskartaEventAction;

struct SASKARTACORE_API FSaskartaPromptLogic
{
    /** The first reminder comes this long after the prompt appears (world seconds, paused time excluded). */
    static constexpr double FirstRemindS = 10.0;
    /** Then one reminder every RemindEveryS until it is answered. */
    static constexpr double RemindEveryS = 20.0;
    /** Slate ZOrder of the runner's own prompt line: above the boot log (UMG 100 + 10) and the caption (40 + 10), below the pause menu (300 + 10). */
    static constexpr int32 OverlayZOrder = 200;

    /** True when a reminder is due. ShownS: the prompt's age; SinceRemindS: since the last reminder, negative if none yet. */
    static bool ShouldRemind(double ShownS, double SinceRemindS);

    /** Held-key edge: pressed at this poll when down now and up at the previous poll. */
    static bool IsPressEdge(bool bDownNow, bool bWasDown) { return bDownNow && !bWasDown; }

    /** The CRT terminal line: "Release the inner latch." -> "RELEASE THE INNER LATCH  -  PRESS E / A". */
    static FString CrtLine(const FString& PromptText);

    /** The runner's on-top line: the prompt as written, then the keys. */
    static FString OverlayLine(const FString& PromptText);

    /**
     * A SpawnOrReveal id "DL:<ref>": true and the reference (an asset name "DL_Ending", or an object or package
     * path "/Game/.../DL_Ending.DL_Ending"). False for any other id.
     */
    static bool ParseDataLayerRef(const FString& RevealId, FString& OutRef);

    /** Does a UDataLayerAsset (its name and object path) match a reference (an asset name, or an object or package path)? Case-insensitive. */
    static bool DataLayerAssetMatches(const FString& Ref, const FString& AssetName, const FString& AssetObjectPath);

    /**
     * A cinematic whose sequence is missing still runs these cues at once (with its final state): the flow
     * state and the black it would have cleared (Cine_ClearBlack), so a missing LS_CIN_19 cannot leave the
     * Keeper walking under the collapse's black.
     */
    static bool RunsWithoutSequence(const FSaskartaEventAction& Cue);
};
