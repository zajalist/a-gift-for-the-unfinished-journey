// manifest.json -> USaskartaAmbienceAsset (DA_Ambience).
//
// The manifest (Saved/GameAudio/Ambience2/manifest.json, written by Tools/Audio/make_ambience_v2.py)
// holds the files, zones, pools, spot placement and the dose table. The AMBIENCE2 brief's placement
// rules (where each pool plays, storm gating, the zone wind multipliers, the bed modifiers) are not
// in the manifest; ApplyBriefRules adds them here, so re-importing a regenerated manifest keeps them.
//
// Editor lane (README_Ambience.md):
//   asset = unreal.load_asset('/Game/SaskartaGaea/Audio/Ambience2/DA_Ambience')   # or create it
//   ok, report = unreal.SaskartaAmbienceImport.import_ambience_from_manifest(asset, '')
//   unreal.EditorAssetLibrary.save_loaded_asset(asset)

#pragma once

#include "CoreMinimal.h"
#include "Kismet/BlueprintFunctionLibrary.h"
#include "SaskartaAmbienceImport.generated.h"

class USaskartaAmbienceAsset;

UCLASS()
class SASKARTACORE_API USaskartaAmbienceImport : public UBlueprintFunctionLibrary
{
    GENERATED_BODY()

public:
    /** /Game/SaskartaGaea/Audio/Ambience2/DA_Ambience.DA_Ambience */
    static const TCHAR* AmbienceAssetPath;

    /** /Game/SaskartaGaea/Audio/Ambience2 (where the WAVs are imported). */
    static const TCHAR* AmbienceFolder;

    /**
     * Reads the manifest into Asset (does not save it). ManifestPath empty = the project's
     * Saved/GameAudio/Ambience2/manifest.json. OutReport lists the counts and any problem.
     */
    UFUNCTION(BlueprintCallable, Category = "Saskarta|Ambience")
    static bool ImportAmbienceFromManifest(USaskartaAmbienceAsset* Asset, const FString& ManifestPath, FString& OutReport);

    /** Pure: the manifest text into Asset (cleared first), then ApplyBriefRules. */
    static bool ParseManifestJson(const FString& Json, USaskartaAmbienceAsset* Asset, FString& OutReport);

    /** The brief's rules on an imported asset (pool placement/gating, bed modifiers, zone multipliers). */
    static void ApplyBriefRules(USaskartaAmbienceAsset* Asset);

    /** "/Game/.../Folder/Name.Name". */
    static FSoftObjectPath SoundPath(const FString& Folder, const FString& AssetName);

    /** Editor builds only: a transient asset imported from the manifest when DA_Ambience does not exist yet. */
    static USaskartaAmbienceAsset* ImportTransient(UObject* Outer);
};
