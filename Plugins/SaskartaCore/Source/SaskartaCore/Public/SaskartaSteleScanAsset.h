// DA_Saskarta_SteleScan: the stele scan's data (task STELESCAN, docs/look/STELE_SCAN.md section 4).
//
// Packaging: docs/ is not staged, so the data lives in a DataAsset under /Game. It is filled in the
// editor lane by
//   asset = unreal.load_asset('/Game/SaskartaGaea/Inscriptions/DA_Saskarta_SteleScan')   # or create it
//   ok, report = unreal.SaskartaSteleScanImport.import_stele_scan_from_files(asset, unreal.Paths.project_dir())
// then saved. In editor builds only, when the asset is missing, the scanner imports a transient copy
// straight from docs/story/inscriptions.json so PIE works before the asset exists.
//
// The JSON is written by hand (the author's texts) and by Tools/Story/build_inscription_atlas.py
// (atlas_cell, the meshes' cell_rect_uv1). No Saskartan is ever invented: a text the author has not
// supplied yet is "AUTHOR", and a stele shows only what is carved on it (its "inscription").

#pragma once

#include "CoreMinimal.h"
#include "Engine/DataAsset.h"
#include "Kismet/BlueprintFunctionLibrary.h"
#include "SaskartaSteleScanLogic.h"
#include "SaskartaSteleScanAsset.generated.h"

class USoundBase;

/** One unique text (inscriptions[] in inscriptions.json). */
USTRUCT(BlueprintType)
struct SASKARTACORE_API FSaskartaInscriptionDef
{
    GENERATED_BODY()

    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Saskarta|Steles")
    FName Id;

    /** awaiting_author, scanned, carved, in_atlas, recorded. */
    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Saskarta|Steles")
    FString Status;

    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Saskarta|Steles")
    FString English;

    /** The author's transliteration, verbatim ("AUTHOR" until he supplies it). */
    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Saskarta|Steles")
    FString Saskartan;

    /** Empty = derived (FSaskartaSteleScanCore::MachineTranslit). */
    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Saskarta|Steles")
    FString MachineTranslit;

    /** What the HUD prints after "~ EN:" (markers: check mark, [?], ~WORD, [NAME: X], [ERASED]). */
    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Saskarta|Steles")
    FString EnglishApprox;

    /** A match after this beat has fired shows EnglishApproxResolved (W06 after B08). */
    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Saskarta|Steles")
    FName ResolvesAfterBeat;

    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Saskarta|Steles")
    FString EnglishApproxResolved;

    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Saskarta|Steles")
    int32 AtlasCell = INDEX_NONE;

    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Saskarta|Steles")
    FName VoiceLineId;

    /** VO_Carrier_INSCR_<id> (the author's take through the carrier chain). Unset or missing = text only. */
    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Saskarta|Steles")
    TSoftObjectPtr<USoundBase> Voice;

    /** system or failing (the carrier chain's style; informational here). */
    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Saskarta|Steles")
    FString VoiceStyle;

    /** voice_policy "never". */
    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Saskarta|Steles")
    bool bNeverVoice = false;

    /** The clip's length when known (0 = read it from the sound). */
    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Saskarta|Steles")
    float DurationS = 0.f;
};

/** One placed stone (steles[] in inscriptions.json). */
USTRUCT(BlueprintType)
struct SASKARTACORE_API FSaskartaSteleDef
{
    GENERATED_BODY()

    /** The actor's second tag and its label, e.g. Stele_WayStone_12 (the first tag is "Stele"). */
    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Saskarta|Steles")
    FName Id;

    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Saskarta|Steles")
    FName Mesh;

    /** What is carved on it now. */
    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Saskarta|Steles")
    FName Inscription;

    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Saskarta|Steles")
    float RoadM = 0.f;

    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Saskarta|Steles")
    float Wear = 0.f;

    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Saskarta|Steles")
    bool bDock = false;

    /** Local offset of the face centre from the pivot (cm): (front face x + 1, 0, glyph centre z). */
    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Saskarta|Steles")
    FVector FaceCentreLocalCm = FVector::ZeroVector;
};

UCLASS(BlueprintType)
class SASKARTACORE_API USaskartaSteleScanAsset : public UPrimaryDataAsset
{
    GENERATED_BODY()

public:
    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Saskarta|Steles")
    TArray<FSaskartaInscriptionDef> Inscriptions;

    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Saskarta|Steles")
    TArray<FSaskartaSteleDef> Steles;

    // --- tuning (inscriptions.json "tuning"; the FSaskartaSteleScanTuning defaults otherwise)
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Steles|Tuning")
    float RangeM = 22.f;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Steles|Tuning")
    float MinRangeM = 3.f;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Steles|Tuning")
    float MaxViewDeg = 35.f;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Steles|Tuning")
    float DockViewDeg = 40.f;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Steles|Tuning")
    float MinFaceDot = 0.2f;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Steles|Tuning")
    float AheadM = 60.f;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Steles|Tuning")
    float BehindM = 10.f;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Steles|Tuning")
    float SweepS = 1.4f;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Steles|Tuning")
    float MatchSweepS = 0.6f;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Steles|Tuning")
    float TextAtS = 1.4f;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Steles|Tuning")
    float VoiceAtS = 1.6f;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Steles|Tuning")
    float VoiceWaitMaxS = 4.f;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Steles|Tuning")
    float VoiceMinGapS = 1.5f;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Steles|Tuning")
    float VoiceLeadS = 4.f;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Steles|Tuning")
    float HudWaitMaxS = 3.f;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Steles|Tuning")
    float HoldAfterVoiceS = 2.f;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Steles|Tuning")
    float TextOnlyHoldS = 6.f;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Steles|Tuning")
    float MatchHoldS = 3.f;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Steles|Tuning")
    int32 MaxTextOnlyFullReads = 2;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Steles|Tuning")
    float WornWear = 0.65f;
    /** (from, to) road m: full readings there are text only (the Climb). */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Steles|Tuning")
    TArray<FVector2D> SilentRoadM;

    // --- prompted scan (docs/look/STELE_SCAN.md "Prompted scan")
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Steles|Prompt")
    bool bPrompted = true;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Steles|Prompt")
    float PromptRangeM = 14.f;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Steles|Prompt")
    float PromptViewDeg = 25.f;
    /** Energy hook only: nothing spends it yet. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Steles|Prompt")
    float ScanChargeCost = 0.f;
    /** The runner caption target of the prompt line (WBP_Saskarta_Caption's ScanPromptLine). */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Steles|Prompt")
    FName PromptTarget = TEXT("ScanPrompt");
    /** The words after "E · " (empty: SCAN INSCRIPTION). */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Steles|Prompt")
    FString PromptLabel;

    /** The runner caption target the reading shows on (WBP_Saskarta_Caption's ScanBlock). */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Steles|HUD")
    FName CaptionTarget = TEXT("Scan");

    /** Optional replacement for the check mark. Empty omits it; the header already reports READ. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Steles|HUD")
    FString ResolvedMark;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Steles|HUD")
    TSoftObjectPtr<USoundBase> PingSound;

    /** Optional soft tick for a match (none = silent). */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Steles|HUD")
    TSoftObjectPtr<USoundBase> MatchSound;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Steles|HUD")
    float PingVolume = 0.32f;   // about -10 dB

    const FSaskartaInscriptionDef* FindInscription(FName Id) const;
    const FSaskartaSteleDef* FindStele(FName Id) const;
    FSaskartaSteleScanTuning MakeTuning() const;
};

UCLASS()
class SASKARTACORE_API USaskartaSteleScanImport : public UBlueprintFunctionLibrary
{
    GENERATED_BODY()

public:
    static const TCHAR* AssetPath;

    /** Reads docs/story/inscriptions.json under ProjectDir into Asset (does not save it). */
    UFUNCTION(BlueprintCallable, Category = "Saskarta|Steles")
    static bool ImportSteleScanFromFiles(USaskartaSteleScanAsset* Asset, const FString& ProjectDir, FString& OutReport);

    /** DA_Saskarta_SteleScan, or (editor builds only) a transient import from docs/story. Null otherwise. */
    static USaskartaSteleScanAsset* LoadOrImportTransient(UObject* Outer);

    /**
     * The pure parser (tested on inline JSON). Fills Asset's arrays and tuning; OutReport lists counts
     * and problems. False when the JSON does not parse or a required field is missing.
     */
    static bool ParseInscriptionsJson(const FString& Json, USaskartaSteleScanAsset* Asset, FString& OutReport);
};
