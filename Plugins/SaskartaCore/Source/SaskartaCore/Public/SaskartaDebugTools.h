// Debug mode support for the story (LANE5, Tools/GameFlow/specs/README_Debug.md).
//
// The debug menu itself is Blueprint (CM_Saskarta, the cheat manager, and WBP_Saskarta_Debug).
// This file adds what Blueprint cannot reach:
// - the runner's one-shot flags (USaskartaEventRunner::ResetBeat / ResetAllBeats, defined in
//   SaskartaDebugTools.cpp so the runner's own .cpp stays untouched);
// - the last N LogSaskartaEvents / LogSaskartaStation lines, for the on-screen event log;
// - dotted console commands (saskarta.debug, saskarta.tp, saskarta.beat, saskarta.skip,
//   saskarta.resetbeats) that forward to the cheat manager's exec functions, so both spellings work.
//
// Everything here is debug only: the log capture registers on first use (the debug menu or a
// console command), never in a normal run.

#pragma once

#include "CoreMinimal.h"
#include "Kismet/BlueprintFunctionLibrary.h"
#include "SaskartaDebugTools.generated.h"

UCLASS()
class SASKARTACORE_API USaskartaDebugLibrary : public UBlueprintFunctionLibrary
{
    GENERATED_BODY()

public:
    /**
     * The last MaxLines lines logged by LogSaskartaEvents and LogSaskartaStation, oldest first,
     * joined with newlines (the time prefix is the world-independent log time, HH:MM:SS).
     * The capture starts on the first call, so the first call returns only what came after it.
     */
    UFUNCTION(BlueprintCallable, Category = "Saskarta|Debug")
    static FString GetRecentEventLog(int32 MaxLines = 10);

    /** Clears one beat's one-shot flag and rewinds the high-water mark to the pawn, so the beat fires again when the carrier reaches it. */
    UFUNCTION(BlueprintCallable, Category = "Saskarta|Debug", meta = (WorldContext = "WorldContext"))
    static bool ResetBeat(const UObject* WorldContext, FName BeatId);

    /** Clears every one-shot flag and rewinds the high-water mark to the pawn (a fresh run from here on). */
    UFUNCTION(BlueprintCallable, Category = "Saskarta|Debug", meta = (WorldContext = "WorldContext"))
    static void ResetAllBeats(const UObject* WorldContext);

    /** Arms one beat (USaskartaEventRunner::ArmBeat): road beats teleport LeadM before it; B01 (flow) fires on its next flow report. Never writes the Continue save. */
    UFUNCTION(BlueprintCallable, Category = "Saskarta|Debug", meta = (WorldContext = "WorldContext"))
    static bool ArmBeat(const UObject* WorldContext, FName BeatId, float LeadM = 30.f);

    /** The beat the runner is running now, or None. */
    UFUNCTION(BlueprintPure, Category = "Saskarta|Debug", meta = (WorldContext = "WorldContext"))
    static FName GetRunningBeat(const UObject* WorldContext);

    /** Starts the log capture (idempotent). */
    static void EnsureLogCapture();
};
