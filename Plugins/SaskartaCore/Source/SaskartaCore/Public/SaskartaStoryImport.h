// JSON/TSV -> USaskartaStoryAsset (EVENTS.md section 6).
//
// The parsers are pure (string in, structs out) so Saskarta.Events.Import tests run them
// on inline snippets. ImportStoryFromFiles is the editor-lane entry point:
//
//   asset = unreal.load_asset('/Game/SaskartaGaea/Story/DA_Saskarta_Story')   # or create it
//   ok, report = unreal.SaskartaStoryImport.import_story_from_files(asset, unreal.Paths.project_dir())
//
// Sources, all relative to the project dir:
//   docs/story/story-events.json            beats, optional_beats, system_beats, cinematics, glances
//   docs/story/radio-lines-for-translation.tsv   every line (English, Language EN/SKS, Saskartan text)
//   docs/story/carrier-voice-lines.json     carrier styles
//   docs/story/caption-pages.json           word-timed pages for long story takes
//   docs/story/road-profile.json            samples -> RoadMToUeM
//   Saved/RadioRecordings/durations.json    recorded durations (optional; {"ID": seconds} or {"ID": {"duration_s": s}})

#pragma once

#include "CoreMinimal.h"
#include "Kismet/BlueprintFunctionLibrary.h"
#include "SaskartaEventTypes.h"
#include "SaskartaStoryImport.generated.h"

class USaskartaStoryAsset;

UCLASS()
class SASKARTACORE_API USaskartaStoryImport : public UBlueprintFunctionLibrary
{
    GENERATED_BODY()

public:
    static const TCHAR* StoryAssetPath;

    /** Reads every source file under ProjectDir into Asset (does not save it). OutReport lists counts and problems. */
    UFUNCTION(BlueprintCallable, Category = "Saskarta|Story")
    static bool ImportStoryFromFiles(USaskartaStoryAsset* Asset, const FString& ProjectDir, FString& OutReport);

    /**
     * DA_Saskarta_Story, or (editor builds only) a transient asset imported from docs/story/
     * when the DataAsset does not exist yet. Null in a packaged build without the asset.
     */
    static USaskartaStoryAsset* LoadStoryOrImportTransient(UObject* Outer);

    // ------------------------------------------------------------------ pure parsers (tested)
    static bool ParseStoryJson(const FString& Json, TArray<FSaskartaBeatDef>& OutBeats,
        TArray<FSaskartaCinematicDef>& OutCinematics, TArray<FSaskartaGlanceDef>& OutGlances, FString& OutError);

    /** One action or cue object. */
    static FSaskartaEventAction ParseAction(const TSharedPtr<class FJsonObject>& Obj);

    /** "pass", "pass:human", "flow:first_boot", "prompt:…", "scripted:…", "none", "curve:…". */
    static FSaskartaEventTrigger ParseTriggerString(const FString& Trigger, float UeDistanceM, float RoadM);

    static ESaskartaActionType ParseActionType(const FString& Name);
    static bool ParsePriority(const FString& Name, ESaskartaEventPriority& Out);
    static ESaskartaSkipRule ParseSkipRule(const FString& Name);

    /** The translation TSV (header row required). Rows without an ID are skipped. */
    static void ParseLinesTsv(const FString& Tsv, TArray<FSaskartaLineDef>& OutLines);

    /** Splits one TSV line with CSV-style quoting ("" inside quotes is a quote). */
    static TArray<FString> SplitTsvLine(const FString& Line);

    /** Drops stage directions "(beat)", "(2 s pause)" and the literal quotes around spoken text. */
    static FString CleanSpokenText(const FString& Text);

    /** "7 s", "20 s", "re-time from the take" -> 7, 20, 0. */
    static float ParseTargetSeconds(const FString& Target);

    static void ApplyCarrierLinesJson(const FString& Json, TArray<FSaskartaLineDef>& InOutLines);
    static void ApplyDurationsJson(const FString& Json, TArray<FSaskartaLineDef>& InOutLines);
    static bool ApplyCaptionPagesJson(const FString& Json, TArray<FSaskartaLineDef>& InOutLines);
    static bool ParseRoadProfile(const FString& Json, TArray<FVector2f>& OutRoadMToUeM);

    /** The priority the importer gives a beat that does not state one (EVENTS.md section 3). */
    static ESaskartaEventPriority DerivePriority(const FSaskartaBeatDef& Beat);
};
