// Look keys along the road, for USaskartaLightingDirector (Task L7).
//
// One FSaskartaLookKey per key in Tools/Look/look_keys.json. The data asset
// DA_Saskarta_LookKeys (/Game/SaskartaGaea/Look) is built from that JSON by
// Tools/Look/build_look_keys_asset.py, which runs once the module has built.
// Units follow the JSON; the director converts them (m -> cm, fog colour x the
// fog luminance scale) exactly as Tools/Look/apply_look.py does.

#pragma once

#include "CoreMinimal.h"
#include "Engine/DataAsset.h"
#include "SaskartaLookKeys.generated.h"

/** One look key: everything the lighting director blends between two keys. */
USTRUCT(BlueprintType)
struct SASKARTACORE_API FSaskartaLookKey
{
    GENERATED_BODY()

    /** Key name (Valley, Basin, Climb, InCloud, Above). Not blended. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Look")
    FName Name;

    /** Walk metres from the carrier dock (spline point 54) where this key applies exactly. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Look")
    float RoadM = 0.f;

    // --- sun (the actor tagged Saskarta_Sun)
    /** Actor pitch in degrees (negative = above the horizon). */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Look|Sun")
    float SunPitch = -8.f;

    /** Actor yaw in degrees. Blended along the shortest arc. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Look|Sun")
    float SunYaw = 0.f;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Look|Sun")
    float SunIntensityLux = 2.2f;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Look|Sun")
    float SunTemperatureK = 4500.f;

    // --- sky atmosphere (Saskarta_Sky)
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Look|Atmosphere")
    float MieScatteringScale = 0.006f;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Look|Atmosphere")
    float MieAnisotropy = 0.75f;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Look|Atmosphere")
    float RayleighScatteringScale = 0.0331f;

    // --- clouds (Saskarta_Clouds, and MPC_Saskarta_Sky Coverage/Density/BaseAltitude)
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Look|Clouds")
    float CloudCoverage = 0.7f;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Look|Clouds")
    float CloudDensity = 0.55f;

    /** Cloud layer bottom, km above the SkyAtmosphere planet top (Z -450 m). */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Look|Clouds")
    float CloudBaseKm = 1.f;

    /** Cloud layer top, km above the planet top. Layer height = top - base. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Look|Clouds")
    float CloudTopKm = 4.f;

    // --- height fog (Saskarta_Fog)
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Look|Fog")
    float FogDensity = 0.015f;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Look|Fog")
    float FogFalloff = 0.6f;

    /** The key's fog colour as a linear hue (from sRGB hex), before the fog luminance scale. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Look|Fog")
    FLinearColor FogColor = FLinearColor(0.155f, 0.114f, 0.091f, 1.f);

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Look|Fog")
    float FogStartM = 150.f;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Look|Fog")
    float FogSecondDensity = 0.0003f;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Look|Fog")
    float FogSecondHeightM = 250.f;

    // --- grade volumes (Saskarta_GradeStorm / Saskarta_GradeClear)
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Look|Grade")
    float GradeStormWeight = 1.f;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Look|Grade")
    float GradeClearWeight = 0.f;

    /** 0-1. Drives the cloud material, lightning and the storm soundscape. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Look|Storm")
    float StormIntensity = 0.45f;
};

/** DA_Saskarta_LookKeys: the road's look keys, sorted by RoadM. */
UCLASS(BlueprintType)
class SASKARTACORE_API USaskartaLookKeys : public UPrimaryDataAsset
{
    GENERATED_BODY()

public:
    /** Sorted by RoadM, ascending (build_look_keys_asset.py sorts and checks). */
    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Look")
    TArray<FSaskartaLookKey> Keys;
};
