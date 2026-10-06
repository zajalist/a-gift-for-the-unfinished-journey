// Hardware detection and the graphics recommendation built from it (task PERF-AUTO).
//
// GatherHardwareSpecs() reads the machine: GPU (RHI adapter name, vendor, integrated flag,
// driver, dedicated VRAM), CPU (brand, cores, threads, clock), system RAM and the desktop
// display (resolution, refresh rate). Recommend() is PURE: specs (plus the synth-benchmark
// scores) in, a full settings recommendation out. It is what the automation tests exercise
// (Saskarta.Perf.*) and what USaskartaGameUserSettings::RunAutoDetect() applies.
//
// The rules (the tier table in Tools/Perf/SCALABILITY.md):
//   1. ClassifyGPU(): a small known-GPU table by name -> ESaskartaGPUClass. Integrated GPUs
//      (Intel UHD/Iris Xe/Arc iGPU, AMD Vega/7x0M iGPU, NVIDIA MX) -> Integrated. Laptop
//      variants drop one class.
//   2. Class -> preset: Integrated Low, Entry Low (Medium when the GPU score and 6 GB VRAM
//      allow), Mainstream Medium, Performance High, Enthusiast Epic. Enthusiast GPUs with
//      strong benchmarks, >= 11 GB reported VRAM, >= 24 GB RAM and >= 6 CPU cores can use
//      Cinematic automatically. A GPU score far below the class's expectation drops one level (a throttled
//      laptop or a mislabelled card). Unknown GPUs are placed by the GPU score alone, capped
//      at High.
//   3. Caps per group: VRAM (< 4 GB Low textures, < 6 GB Medium textures), RAM, CPU cores
//      and CPU score.
//   4. Upscaler: TSR; screen percentage by preset and output resolution (50-58 % on
//      Low/Medium at 1440p+), Native at Epic on 1080p.
//   5. Frame cap = display refresh, at most 60 on every tier; VSync on for displays <= 75 Hz.
//   6. (task HEADROOM) StreamingPoolForVRAM's per-VRAM-class step value is then clamped so it
//      never eats into a fixed machine-wide reserve: at least VRAMHeadroomMB(VRAMMB) of VRAM and
//      (RAM known) RAMHeadroomMB(RAMGB) of system RAM stay free, so a recorder/browser/second
//      GPU workload alongside the game has somewhere to live. This only ever tightens the
//      existing step value, never loosens it (the project's own 3072 MB ceiling is unchanged).
//
// The benchmark score thresholds are PROVISIONAL until the PERF2 lane records real scores
// (task-PERF2-brief.md); the name table is what decides for every known card.

#pragma once

#include "CoreMinimal.h"
#include "Kismet/BlueprintFunctionLibrary.h"
#include "SaskartaHardwareProfile.generated.h"

/** Coarse GPU performance class from the known-GPU name table. */
UENUM(BlueprintType)
enum class ESaskartaGPUClass : uint8
{
    Unknown,
    /** Intel UHD/Iris Xe/Arc iGPU, AMD Vega/680M/780M iGPU, NVIDIA MX, software renderers. */
    Integrated,
    /** GTX 1050-1070, GTX 1650, RX 470-590, RX 5300/5500, RX 6400/6500, Arc A380. */
    Entry,
    /** GTX 1660/1080, RTX 2060, RTX 3050, RTX 4050, RX 5600-5700, RX 6600, Arc A580. */
    Mainstream,
    /** RTX 2070-2080 Ti, RTX 3060-3070 Ti, RTX 4060/Ti, RTX 5050-5060 Ti, RX 6700-6750, RX 7600-7700, Arc A750/A770/B580. */
    Performance,
    /** RTX 3080+, RTX 4070+, RTX 5070+, RX 6800+, RX 7800+, RX 9070. */
    Enthusiast,
};

/** What GatherHardwareSpecs() read from this machine. -1 / empty = unknown. */
USTRUCT(BlueprintType)
struct SASKARTACORE_API FSaskartaHardwareSpecs
{
    GENERATED_BODY()

    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Hardware")
    FString GPUName;

    /** PCI vendor id: 0x10DE NVIDIA, 0x1002 AMD, 0x8086 Intel. */
    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Hardware")
    int32 VendorId = 0;

    /** The RHI's own integrated-GPU flag (GRHIDeviceIsIntegrated). */
    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Hardware")
    bool bIntegrated = false;

    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Hardware")
    FString DriverVersion;

    /** Dedicated video memory in MB. */
    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Hardware")
    int32 VRAMMB = -1;

    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Hardware")
    FString CPUBrand;

    /** Physical cores. */
    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Hardware")
    int32 CPUCores = -1;

    /** Logical cores (with SMT). */
    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Hardware")
    int32 CPUThreads = -1;

    /** Nominal clock from the registry (Windows only). */
    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Hardware")
    int32 CPUClockMHz = -1;

    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Hardware")
    int32 RAMGB = -1;

    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Hardware")
    FIntPoint DisplayResolution = FIntPoint::ZeroValue;

    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Hardware")
    int32 RefreshHz = -1;

    /** UGameUserSettings::RunHardwareBenchmark CPU perf index (100 = the engine's reference machine). */
    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Hardware")
    float CPUScore = -1.f;

    /** UGameUserSettings::RunHardwareBenchmark GPU perf index. */
    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Hardware")
    float GPUScore = -1.f;
};

/** A complete settings recommendation, and the line the Settings menu shows. */
USTRUCT(BlueprintType)
struct SASKARTACORE_API FSaskartaDetectedProfile
{
    GENERATED_BODY()

    /** False until Recommend() filled it. */
    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Hardware")
    bool bValid = false;

    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Hardware")
    FSaskartaHardwareSpecs Specs;

    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Hardware")
    ESaskartaGPUClass GPUClass = ESaskartaGPUClass::Unknown;

    /** The overall preset: 0 Low, 1 Medium, 2 High, 3 Epic, 4 Cinematic. */
    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Hardware")
    int32 RecommendedLevel = 1;

    // Per-group levels after the VRAM/RAM/CPU caps (0 Low .. 4 Cinematic).
    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Hardware")
    int32 ViewDistanceQuality = 1;
    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Hardware")
    int32 AntiAliasingQuality = 1;
    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Hardware")
    int32 ShadowQuality = 1;
    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Hardware")
    int32 GlobalIlluminationQuality = 1;
    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Hardware")
    int32 ReflectionQuality = 1;
    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Hardware")
    int32 PostProcessQuality = 1;
    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Hardware")
    int32 TextureQuality = 1;
    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Hardware")
    int32 EffectsQuality = 1;
    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Hardware")
    int32 FoliageQuality = 1;
    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Hardware")
    int32 ShadingQuality = 1;

    /** USaskartaGameUserSettings::UpscalerMethod: 0 TSR, 2 Native. */
    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Hardware")
    int32 UpscalerMethod = 0;

    /** USaskartaGameUserSettings::UpscalerMode: 0 Quality (66.7 %), 1 Balanced (58 %), 2 Performance (50 %). */
    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Hardware")
    int32 UpscalerMode = 0;

    /** The r.ScreenPercentage UpscalerMethod/Mode give. */
    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Hardware")
    float ScreenPercentage = 66.7f;

    /** 0 = unlimited. */
    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Hardware")
    float FrameRateLimit = 60.f;

    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Hardware")
    bool bVSync = false;

    /** Why each cap was applied, "; "-separated (logged, and handy in a tooltip). */
    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Hardware")
    FString Reasons;

    /** "Detected: NVIDIA GeForce RTX 5070, 12 GB, recommended: Epic". */
    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Hardware")
    FText Summary;
};

UCLASS()
class SASKARTACORE_API USaskartaHardwareProfileLibrary : public UBlueprintFunctionLibrary
{
    GENERATED_BODY()

public:
    /** Reads this machine (no benchmark; CPUScore/GPUScore stay -1). Game thread, after RHI init. */
    UFUNCTION(BlueprintCallable, Category = "Saskarta|Hardware")
    static FSaskartaHardwareSpecs GatherHardwareSpecs();

    /** The known-GPU table. Pure; case-insensitive on the adapter name. */
    UFUNCTION(BlueprintPure, Category = "Saskarta|Hardware")
    static ESaskartaGPUClass ClassifyGPU(const FString& GPUName, int32 VendorId, bool bIntegrated);

    /** Specs (with benchmark scores, if any) -> the full recommendation. Pure. */
    UFUNCTION(BlueprintPure, Category = "Saskarta|Hardware")
    static FSaskartaDetectedProfile Recommend(const FSaskartaHardwareSpecs& Specs);

    /** TextureQuality cap: < 4 GB 0, < 6 GB 1, < 8 GB 2, < 11 GB 3, else 4. Unknown VRAM: 3. */
    UFUNCTION(BlueprintPure, Category = "Saskarta|Hardware")
    static int32 TextureCapForVRAM(int32 VRAMMB);

    /**
     * r.Streaming.PoolSize (MB) for a VRAM class, clamped so it never eats into the headroom
     * task HEADROOM reserves for the rest of the machine: at most VRAMMB - VRAMHeadroomMB(VRAMMB)
     * of VRAM, and (RAMGB > 0) at most RAMGB*1024 - RAMHeadroomMB(RAMGB) of host RAM (streamed
     * textures are RAM-resident before upload). RAMGB <= 0 skips the RAM side (unknown), matching
     * every caller from before task HEADROOM. -1 = VRAMMB unknown, leave the project value alone.
     * Never below StreamingPoolFloorMB nor above the un-clamped per-VRAM-class step value.
     */
    UFUNCTION(BlueprintPure, Category = "Saskarta|Hardware")
    static int32 StreamingPoolForVRAM(int32 VRAMMB, int32 RAMGB = -1);

    /** VRAM (MB) task HEADROOM always leaves free: max(VRAMHeadroomFloorMB, VRAMHeadroomShare of VRAMMB). */
    UFUNCTION(BlueprintPure, Category = "Saskarta|Hardware")
    static int32 VRAMHeadroomMB(int32 VRAMMB);

    /** System RAM (MB) task HEADROOM always leaves free: max(RAMHeadroomFloorMB, RAMHeadroomShare of RAMGB). */
    UFUNCTION(BlueprintPure, Category = "Saskarta|Hardware")
    static int32 RAMHeadroomMB(int32 RAMGB);

    /** "Low", "Medium", "High", "Epic", "Cinematic". */
    UFUNCTION(BlueprintPure, Category = "Saskarta|Hardware")
    static FString LevelName(int32 Level);

    /** "Detected: <GPU>, <VRAM>, recommended: <Level>". */
    UFUNCTION(BlueprintPure, Category = "Saskarta|Hardware")
    static FText MakeSummary(const FSaskartaHardwareSpecs& Specs, int32 RecommendedLevel);

    /** The r.ScreenPercentage an UpscalerMethod/UpscalerMode pair gives (matches ComputeCVars). */
    static float ScreenPercentageFor(int32 UpscalerMethod, int32 UpscalerMode);

    // PROVISIONAL synth-benchmark GPU-score thresholds (calibrate in PERF2).
    /** Entry class is lifted to Medium at or above this score (with >= 6 GB VRAM). */
    static constexpr float EntryMediumScore = 250.f;
    /** A known class drops one level below this share of its expected score. */
    static constexpr float ClassGuardShare = 0.4f;
    /** Unknown GPUs: score bands for Low / Medium / High. */
    static constexpr float UnknownMediumScore = 150.f;
    static constexpr float UnknownHighScore = 350.f;
    /** Expected GPU score per class (Mainstream, Performance, Enthusiast). */
    static float ExpectedScore(ESaskartaGPUClass Class);

    // ---- task HEADROOM: the machine-wide reserve StreamingPoolForVRAM leaves free ----
    /** Fraction of VRAM the reserve is, above the floor. */
    static constexpr float VRAMHeadroomShare = 0.15f;
    /** Minimum VRAM the reserve ever is, regardless of card size. */
    static constexpr int32 VRAMHeadroomFloorMB = 1536;
    /** Fraction of system RAM the reserve is, above the floor. */
    static constexpr float RAMHeadroomShare = 0.25f;
    /** Minimum system RAM the reserve ever is, regardless of machine size. */
    static constexpr int32 RAMHeadroomFloorMB = 4096;
    /** StreamingPoolForVRAM never returns less than this once VRAMMB > 0 (the streamer still needs a working pool). */
    static constexpr int32 StreamingPoolFloorMB = 512;
};
