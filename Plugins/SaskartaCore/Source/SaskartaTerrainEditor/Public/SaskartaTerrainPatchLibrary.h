#pragma once

#include "Kismet/BlueprintFunctionLibrary.h"
#include "SaskartaTerrainPatchLibrary.generated.h"

// Editor-only and restricted to the single reviewed Local42 patch. The three
// calls are separate so a World Partition save never hides a failed readback.
UCLASS()
class SASKARTATERRAINEDITOR_API USaskartaTerrainPatchLibrary : public UBlueprintFunctionLibrary
{
    GENERATED_BODY()

public:
    UFUNCTION(BlueprintCallable, Category="Saskarta|Terrain")
    static FString PreflightLocal42();

    UFUNCTION(BlueprintCallable, Category="Saskarta|Terrain")
    static FString ApplyLocal42();

    UFUNCTION(BlueprintCallable, Category="Saskarta|Terrain")
    static FString VerifyAndSaveLocal42();

    UFUNCTION(BlueprintCallable, Category="Saskarta|Terrain")
    static FString RestoreLocal42();
};
