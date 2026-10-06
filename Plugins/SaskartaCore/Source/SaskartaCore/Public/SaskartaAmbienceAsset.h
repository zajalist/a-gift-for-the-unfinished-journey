// USaskartaAmbienceAsset (DA_Ambience): the Ambience 2 data the ambience director plays.
//
// Built from Saved/GameAudio/Ambience2/manifest.json by USaskartaAmbienceImport (the brief's
// placement rules are applied there), then saved as /Game/SaskartaGaea/Audio/Ambience2/DA_Ambience.
// Brief: .superpowers/sdd/2026-09-26-saskarta-world-sprint/task-AMBIENCE2-brief.md.
//
// Every sound is a soft reference: the director streams each zone's sounds in asynchronously
// (current + next zone) and releases the far ones. Nothing here is loaded synchronously.

#pragma once

#include "CoreMinimal.h"
#include "Engine/DataAsset.h"
#include "SaskartaAmbienceAsset.generated.h"

class USoundBase;
class USoundClass;
class USoundMix;
class USoundSubmix;

/** How a bed's gain follows the storm intensity I (0-1). */
UENUM(BlueprintType)
enum class ESaskartaBedStormMode : uint8
{
    /** Not storm-dependent. */
    None,
    /** x I (AMB_Storm_WhistleRocks_Loop). */
    Linear,
    /** x I^2 (AMB_Storm_SandHiss_Loop: only the dust walls really hiss). */
    Squared,
    /** x max(0, I - 0.5) x 2 (AMB_Storm_SandOnMetal_Loop). */
    AboveHalf,
    /** x max(0, 1 - I / StormRef) (AMB_Valley_Insects_Loop, StormRef 0.7). */
    InverseToRef
};

/** Where a pool's one-shot plays. */
UENUM(BlueprintType)
enum class ESaskartaPoolPlacement : uint8
{
    /** 2D (no position). */
    TwoD,
    /** A random point MinDistM-MaxDistM from the carrier, within +-ArcDeg of travel, HeightOffsetM up/down. */
    AroundListener,
    /** At the nearest of Emitters (spot labels); only while the listener is within that spot's inner + falloff. */
    AtEmitter
};

/** A looping bed (2D). */
USTRUCT(BlueprintType)
struct SASKARTACORE_API FSaskartaAmbienceBed
{
    GENERATED_BODY()

    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Ambience")
    FName Name;

    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Ambience")
    TSoftObjectPtr<USoundBase> Sound;

    /** Level on SC_Ambience. */
    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Ambience")
    float VolumeDb = 0.f;

    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Ambience")
    ESaskartaBedStormMode StormMode = ESaskartaBedStormMode::None;

    /** The reference intensity of InverseToRef. */
    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Ambience")
    float StormRef = 0.7f;

    /** Silent past this road metre (negative = never). Insects: 1,700. */
    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Ambience")
    float OffAfterRoadM = -1.f;

    /** An extra level over [ExtraFromM, ExtraToM] (the ridge's grass: -4 dB over 1,550-2,020). */
    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Ambience")
    float ExtraFromM = -1.f;

    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Ambience")
    float ExtraToM = -1.f;

    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Ambience")
    float ExtraDb = 0.f;
};

/** A road zone: its beds crossfade in and out over XfadeM centred on FromM and ToM. */
USTRUCT(BlueprintType)
struct SASKARTACORE_API FSaskartaAmbienceZone
{
    GENERATED_BODY()

    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Ambience")
    FName Name;

    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Ambience")
    float FromM = 0.f;

    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Ambience")
    float ToM = 0.f;

    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Ambience")
    float XfadeM = 150.f;

    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Ambience")
    TArray<FSaskartaAmbienceBed> Beds;

    /** Pools that run while this zone dominates (weight >= 0.5). */
    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Ambience")
    TArray<FName> Pools;

    /** Storm wind bed multiplier (Valley/Basin 1, Foot 0.9, Climb 0.8, Cloud 0.4, Above 0.15). */
    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Ambience")
    float WindMultiplier = 1.f;

    /** Geiger dose multiplier (Cloud 0.8: the washout). */
    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Ambience")
    float DoseMultiplier = 1.f;
};

/** A one-shot pool. */
USTRUCT(BlueprintType)
struct SASKARTACORE_API FSaskartaAmbiencePool
{
    GENERATED_BODY()

    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Ambience")
    FName Name;

    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Ambience")
    TArray<TSoftObjectPtr<USoundBase>> Sounds;

    /** Random interval between fires; both <= 0 means event-driven only (gusts, thunder). */
    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Ambience")
    float IntervalMinS = 0.f;

    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Ambience")
    float IntervalMaxS = 0.f;

    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Ambience")
    float VolumeDb = -10.f;

    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Ambience")
    ESaskartaPoolPlacement Placement = ESaskartaPoolPlacement::TwoD;

    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Ambience")
    float MinDistM = 0.f;

    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Ambience")
    float MaxDistM = 0.f;

    /** Half-angle around the direction of travel (180 = anywhere). */
    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Ambience")
    float ArcDeg = 180.f;

    /** Added to the carrier's height (negative = downslope). */
    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Ambience")
    float HeightOffsetM = 0.f;

    /** Spot labels this pool plays at (AtEmitter), or whose radius makes it active (local pools). */
    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Ambience")
    TArray<FName> Emitters;

    /** Active while the storm is within [MinStorm, MaxStorm). */
    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Ambience")
    float MinStorm = 0.f;

    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Ambience")
    float MaxStorm = 2.f;

    /** Only between these road metres (negative = unbounded). */
    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Ambience")
    float RoadMinM = -1.f;

    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Ambience")
    float RoadMaxM = -1.f;

    /** Also fires 0.5-1.5 s after a gust (metal, tarp, banners), when active. */
    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Ambience")
    bool bAlsoOnGust = false;

    /** Only in a gust lull (Valley_Insects). */
    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Ambience")
    bool bGustLullOnly = false;

    /** WATER OPTION: only when the director's bWaitingWaterHasWater is set. */
    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Ambience")
    bool bWaterOption = false;

    /** Active by its emitters' radius alone (not by zone). */
    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Ambience")
    bool bLocal = false;

    /** Still allowed in the Human state (Above_Wind). */
    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Ambience")
    bool bAllowedInHuman = false;

    /** Stops for good on B24 (the chorus thins into wind). */
    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Ambience")
    bool bStopOnFinalBeat = false;

    /** Voice-budget priority (higher survives). */
    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Ambience")
    float Priority = 30.f;
};

/** A spot emitter: a 3D loop at a world position (or only a pool anchor when Sound is unset). */
USTRUCT(BlueprintType)
struct SASKARTACORE_API FSaskartaAmbienceSpot
{
    GENERATED_BODY()

    /** The AmbientSound's actor tag (and editor label), A2_*. */
    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Ambience")
    FName Label;

    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Ambience")
    TSoftObjectPtr<USoundBase> Sound;

    /** UE world cm. */
    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Ambience")
    FVector Location = FVector::ZeroVector;

    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Ambience")
    float RoadM = 0.f;

    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Ambience")
    float InnerRadiusM = 5.f;

    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Ambience")
    float FalloffM = 40.f;

    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Ambience")
    float VolumeDb = -8.f;

    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Ambience")
    bool bWaterOption = false;

    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Ambience")
    FString Note;
};

/** A Geiger fallback rate loop. */
USTRUCT(BlueprintType)
struct SASKARTACORE_API FSaskartaGeigerLoop
{
    GENERATED_BODY()

    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Ambience")
    float RateCps = 1.f;

    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Ambience")
    TSoftObjectPtr<USoundBase> Sound;
};

UCLASS(BlueprintType)
class SASKARTACORE_API USaskartaAmbienceAsset : public UPrimaryDataAsset
{
    GENERATED_BODY()

public:
    // ------------------------------------------------------------------ road zones
    /** Sorted by FromM. */
    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Zones")
    TArray<FSaskartaAmbienceZone> Zones;

    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Pools")
    TArray<FSaskartaAmbiencePool> Pools;

    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Spots")
    TArray<FSaskartaAmbienceSpot> Spots;

    // ------------------------------------------------------------------ storm layer
    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Storm")
    TSoftObjectPtr<USoundBase> WindBreeze;

    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Storm")
    TSoftObjectPtr<USoundBase> WindStrong;

    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Storm")
    TSoftObjectPtr<USoundBase> WindGale;

    /** The wind sum's level on SC_Ambience. */
    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Storm")
    float WindSumDb = -3.f;

    /** Grit beds (sand hiss, sand on metal): 2D, storm-scaled, not zone-weighted. */
    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Storm")
    TArray<FSaskartaAmbienceBed> StormBeds;

    /** Pool names the storm events use. */
    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Storm")
    FName GustPool = TEXT("Storm_Gust");

    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Storm")
    FName SandSprayPool = TEXT("Storm_Sand");

    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Storm")
    FName ThunderClosePool = TEXT("Storm_ThunderClose");

    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Storm")
    FName ThunderDistantPool = TEXT("Storm_ThunderDistant");

    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Storm")
    FName RockfallPool = TEXT("Storm_Rockfall");

    // ------------------------------------------------------------------ Geiger
    /** Dose (counts/s) by road metre: (X = road m, Y = cps), sorted by X, linear between. */
    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Geiger")
    TArray<FVector2D> DoseByRoadM;

    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Geiger")
    TArray<TSoftObjectPtr<USoundBase>> GeigerClicks;

    /** Sorted by rate (1, 5, 20, 80). */
    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Geiger")
    TArray<FSaskartaGeigerLoop> GeigerRateLoops;

    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Geiger")
    TSoftObjectPtr<USoundBase> GeigerSwitchOn;

    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Geiger")
    TSoftObjectPtr<USoundBase> GeigerSwitchOff;

    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Geiger")
    TArray<TSoftObjectPtr<USoundBase>> GeigerChirps;

    // ------------------------------------------------------------------ mix (optional; built by the editor lane)
    /** SMX_Ambience: when set, the story duck moves its output volume (else the director ducks its own voices). */
    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Mix")
    TSoftObjectPtr<USoundSubmix> AmbienceSubmix;

    /** SC_Ambience / SC_Geiger: set as the class override on every voice the director creates. */
    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Mix")
    TSoftObjectPtr<USoundClass> AmbienceClass;

    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Mix")
    TSoftObjectPtr<USoundClass> GeigerClass;

    // ------------------------------------------------------------------ lookups
    const FSaskartaAmbiencePool* FindPool(FName Name) const;
    const FSaskartaAmbienceSpot* FindSpot(FName Label) const;
    int32 FindPoolIndex(FName Name) const;
    int32 FindSpotIndex(FName Label) const;
};
