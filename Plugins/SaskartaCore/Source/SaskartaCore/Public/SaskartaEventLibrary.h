// Static Blueprint wrappers for the story runner (EVENTS.md section 3). Hayba can author
// calls to these (no arrays, no Tick): PC_Saskarta reports flow changes, the pause menu
// pauses or skips a cinematic, QuitToTitle calls StopAll.

#pragma once

#include "CoreMinimal.h"
#include "Kismet/BlueprintFunctionLibrary.h"
#include "SaskartaEventLibrary.generated.h"

UCLASS()
class SASKARTACORE_API USaskartaEventLibrary : public UBlueprintFunctionLibrary
{
    GENERATED_BODY()

public:
    UFUNCTION(BlueprintCallable, Category = "Saskarta|Events", meta = (WorldContext = "WorldContext"))
    static void ReportFlow(const UObject* WorldContext, FName FlowEvent);

    UFUNCTION(BlueprintCallable, Category = "Saskarta|Events", meta = (WorldContext = "WorldContext"))
    static bool FireBeat(const UObject* WorldContext, FName BeatId);

    UFUNCTION(BlueprintPure, Category = "Saskarta|Events", meta = (WorldContext = "WorldContext"))
    static bool IsCinematicActive(const UObject* WorldContext);

    UFUNCTION(BlueprintPure, Category = "Saskarta|Events", meta = (WorldContext = "WorldContext"))
    static bool IsVoiceBusy(const UObject* WorldContext);

    UFUNCTION(BlueprintPure, Category = "Saskarta|Events", meta = (WorldContext = "WorldContext"))
    static float SecondsSinceVoice(const UObject* WorldContext);

    UFUNCTION(BlueprintPure, Category = "Saskarta|Events", meta = (WorldContext = "WorldContext"))
    static bool CanSkipCinematic(const UObject* WorldContext);

    UFUNCTION(BlueprintCallable, Category = "Saskarta|Events", meta = (WorldContext = "WorldContext"))
    static void SkipCurrentCinematic(const UObject* WorldContext);

    UFUNCTION(BlueprintCallable, Category = "Saskarta|Events", meta = (WorldContext = "WorldContext"))
    static void PauseCinematic(const UObject* WorldContext, bool bPause);

    UFUNCTION(BlueprintCallable, Category = "Saskarta|Events", meta = (WorldContext = "WorldContext"))
    static void StopAll(const UObject* WorldContext);

    UFUNCTION(BlueprintCallable, Category = "Saskarta|Events", meta = (WorldContext = "WorldContext"))
    static bool SaveCheckpoint(const UObject* WorldContext, FName CheckpointId);

    UFUNCTION(BlueprintCallable, Category = "Saskarta|Events", meta = (WorldContext = "WorldContext"))
    static bool RestoreFromSave(const UObject* WorldContext);
};
