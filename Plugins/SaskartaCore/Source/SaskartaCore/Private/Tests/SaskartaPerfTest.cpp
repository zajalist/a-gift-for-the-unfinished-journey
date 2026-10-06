// Automation tests for the task PERF-AUTO pure logic: the GPU table, the recommendation, the
// per-tier CVars, the auto-detect trigger, the governor target and the governor state machine
// (injected frame times, hysteresis, hitch rejection, flip-flop guard).
//
// Written offline (fail-first waived, as R33). Run after the build:
//   Automation RunTests Saskarta.Perf

#include "Misc/AutomationTest.h"

#if WITH_DEV_AUTOMATION_TESTS

#include "SaskartaGameUserSettings.h"
#include "SaskartaHardwareProfile.h"
#include "SaskartaPerfGovernor.h"

namespace SaskartaPerfTest
{
    static FString ClassName(ESaskartaGPUClass C)
    {
        return StaticEnum<ESaskartaGPUClass>()->GetNameStringByValue(static_cast<int64>(C));
    }

    static FSaskartaHardwareSpecs Specs(const TCHAR* Gpu, int32 Vendor, int32 VRAMMB, float GPUScore,
        int32 W = 1920, int32 H = 1080, int32 Hz = 60, int32 Cores = 8, int32 RAMGB = 32, bool bIntegrated = false)
    {
        FSaskartaHardwareSpecs S;
        S.GPUName = Gpu;
        S.VendorId = Vendor;
        S.bIntegrated = bIntegrated;
        S.VRAMMB = VRAMMB;
        S.GPUScore = GPUScore;
        S.CPUScore = 150.f;
        S.CPUCores = Cores;
        S.CPUThreads = Cores * 2;
        S.RAMGB = RAMGB;
        S.DisplayResolution = FIntPoint(W, H);
        S.RefreshHz = Hz;
        return S;
    }

    /**
     * Feeds one sample every 0.5 s in (From, To]; returns the time of the first action of Kind,
     * or -1. CpuMs < 0 means half the GPU time (a GPU-bound frame).
     */
    static double Feed(FSaskartaGovernorCore& Core, double From, double To, float FrameMs, float GpuMs,
        FSaskartaGovernorCore::EAction Kind, TArray<FSaskartaGovernorCore::FStep>* OutSteps = nullptr, bool bStopAtFirst = true,
        float CpuMs = -1.f)
    {
        const float Cpu = CpuMs < 0.f ? GpuMs * 0.5f : CpuMs;
        double First = -1.0;
        for (double T = From + 0.5; T <= To + 1.0e-9; T += 0.5)
        {
            FSaskartaGovernorCore::FStep Step;
            const FSaskartaGovernorCore::EAction A = Core.Update(T, FrameMs, GpuMs, Cpu, &Step);
            if (A != FSaskartaGovernorCore::EAction::None && OutSteps)
            {
                OutSteps->Add(Step);
            }
            if (A == Kind && First < 0.0)
            {
                First = T;
                if (bStopAtFirst)
                {
                    return First;
                }
            }
        }
        return First;
    }

    static FSaskartaGovernorCore MakeCore(float Pct = 66.7f, int32 Level = 2)
    {
        FSaskartaGovernorCore Core;
        Core.TargetFps = 60.f;
        FSaskartaGovernorCore::FState B;
        B.ScreenPct = Pct;
        for (int32 G = 0; G < FSaskartaGovernorCore::NumGroups; ++G)
        {
            B.Levels[G] = Level;
        }
        Core.Reset(B, 0.0);
        return Core;
    }
}

// ---------------------------------------------------------------------------------------------

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaPerfClassifyTest, "Saskarta.Perf.ClassifyGPU",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)
bool FSaskartaPerfClassifyTest::RunTest(const FString&)
{
    using namespace SaskartaPerfTest;
    struct FCase { const TCHAR* Name; int32 Vendor; bool bIntegrated; ESaskartaGPUClass Expected; };
    const FCase Cases[] = {
        { TEXT("NVIDIA GeForce RTX 5070"), 0x10DE, false, ESaskartaGPUClass::Enthusiast },
        { TEXT("NVIDIA GeForce RTX 5060 Ti"), 0x10DE, false, ESaskartaGPUClass::Performance },
        { TEXT("NVIDIA GeForce RTX 4090"), 0x10DE, false, ESaskartaGPUClass::Enthusiast },
        { TEXT("NVIDIA GeForce RTX 4070 Laptop GPU"), 0x10DE, false, ESaskartaGPUClass::Performance },
        { TEXT("NVIDIA GeForce RTX 4060"), 0x10DE, false, ESaskartaGPUClass::Performance },
        { TEXT("NVIDIA GeForce RTX 3080"), 0x10DE, false, ESaskartaGPUClass::Enthusiast },
        { TEXT("NVIDIA GeForce RTX 3060 Ti"), 0x10DE, false, ESaskartaGPUClass::Performance },
        { TEXT("NVIDIA GeForce RTX 3050"), 0x10DE, false, ESaskartaGPUClass::Mainstream },
        { TEXT("NVIDIA GeForce RTX 2080 SUPER"), 0x10DE, false, ESaskartaGPUClass::Performance },
        { TEXT("NVIDIA GeForce RTX 2060"), 0x10DE, false, ESaskartaGPUClass::Mainstream },
        { TEXT("NVIDIA GeForce GTX 1660 SUPER"), 0x10DE, false, ESaskartaGPUClass::Mainstream },
        { TEXT("NVIDIA GeForce GTX 1650"), 0x10DE, false, ESaskartaGPUClass::Entry },
        { TEXT("NVIDIA GeForce GTX 1060 6GB"), 0x10DE, false, ESaskartaGPUClass::Entry },
        { TEXT("NVIDIA GeForce GTX 1050 Ti"), 0x10DE, false, ESaskartaGPUClass::Entry },
        { TEXT("NVIDIA GeForce GTX 1080 Ti"), 0x10DE, false, ESaskartaGPUClass::Mainstream },
        { TEXT("NVIDIA GeForce GT 1030"), 0x10DE, false, ESaskartaGPUClass::Integrated },
        { TEXT("NVIDIA GeForce MX450"), 0x10DE, false, ESaskartaGPUClass::Integrated },
        { TEXT("AMD Radeon RX 580 2048SP"), 0x1002, false, ESaskartaGPUClass::Entry },
        { TEXT("Radeon RX 570 Series"), 0x1002, false, ESaskartaGPUClass::Entry },
        { TEXT("AMD Radeon RX 6500 XT"), 0x1002, false, ESaskartaGPUClass::Entry },
        { TEXT("AMD Radeon RX 5600 XT"), 0x1002, false, ESaskartaGPUClass::Mainstream },
        { TEXT("AMD Radeon RX 6600"), 0x1002, false, ESaskartaGPUClass::Mainstream },
        { TEXT("AMD Radeon RX 6600M"), 0x1002, false, ESaskartaGPUClass::Entry },
        { TEXT("AMD Radeon RX 6700 XT"), 0x1002, false, ESaskartaGPUClass::Performance },
        { TEXT("AMD Radeon RX 7600"), 0x1002, false, ESaskartaGPUClass::Performance },
        { TEXT("AMD Radeon RX 7900 XTX"), 0x1002, false, ESaskartaGPUClass::Enthusiast },
        { TEXT("AMD Radeon RX 9070 XT"), 0x1002, false, ESaskartaGPUClass::Enthusiast },
        { TEXT("Radeon RX Vega 64"), 0x1002, false, ESaskartaGPUClass::Mainstream },
        { TEXT("AMD Radeon(TM) RX Vega 11 Graphics"), 0x1002, false, ESaskartaGPUClass::Integrated },
        { TEXT("AMD Radeon(TM) Graphics"), 0x1002, false, ESaskartaGPUClass::Integrated },
        { TEXT("AMD Radeon 780M Graphics"), 0x1002, false, ESaskartaGPUClass::Integrated },
        { TEXT("Intel(R) UHD Graphics 630"), 0x8086, false, ESaskartaGPUClass::Integrated },
        { TEXT("Intel(R) Iris(R) Xe Graphics"), 0x8086, false, ESaskartaGPUClass::Integrated },
        { TEXT("Intel(R) Arc(TM) Graphics"), 0x8086, false, ESaskartaGPUClass::Integrated },
        { TEXT("Intel(R) Arc(TM) A770 Graphics"), 0x8086, false, ESaskartaGPUClass::Performance },
        { TEXT("Intel(R) Arc(TM) A380 Graphics"), 0x8086, false, ESaskartaGPUClass::Entry },
        { TEXT("Intel(R) Arc(TM) B580 Graphics"), 0x8086, false, ESaskartaGPUClass::Performance },
        { TEXT("Microsoft Basic Render Driver"), 0x1414, false, ESaskartaGPUClass::Integrated },
        { TEXT("NVIDIA GeForce RTX 4090"), 0x10DE, true, ESaskartaGPUClass::Integrated }, // the RHI's integrated flag wins
        { TEXT("Mystery Accelerator 9000"), 0, false, ESaskartaGPUClass::Unknown },
        { TEXT(""), 0, false, ESaskartaGPUClass::Unknown },
    };
    for (const FCase& C : Cases)
    {
        const ESaskartaGPUClass Got = USaskartaHardwareProfileLibrary::ClassifyGPU(C.Name, C.Vendor, C.bIntegrated);
        TestEqual(*FString::Printf(TEXT("class of '%s'"), C.Name), ClassName(Got), ClassName(C.Expected));
    }
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaPerfRecommendTest, "Saskarta.Perf.Recommend",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)
bool FSaskartaPerfRecommendTest::RunTest(const FString&)
{
    using namespace SaskartaPerfTest;
    using L = USaskartaHardwareProfileLibrary;

    // The user's machine has enough benchmark and memory headroom for Cinematic.
    {
        const FSaskartaDetectedProfile P = L::Recommend(Specs(TEXT("NVIDIA GeForce RTX 5070"), 0x10DE, 12282, 2000.f, 2560, 1440, 165));
        TestTrue("5070 valid", P.bValid);
        TestEqual("5070 Cinematic", P.RecommendedLevel, 4);
        TestEqual("5070 textures", P.TextureQuality, 4);
        TestEqual("5070 TSR", P.UpscalerMethod, 0);
        TestEqual("5070 quality mode", P.UpscalerMode, 0);
        TestEqual("5070 pct", P.ScreenPercentage, 66.7f);
        TestEqual("5070 cap (165 Hz display, hard cap 60)", P.FrameRateLimit, 60.f);
        TestFalse("5070 no vsync", P.bVSync);
        TestEqual("5070 summary", P.Summary.ToString(), FString(TEXT("Detected: NVIDIA GeForce RTX 5070, 12 GB, recommended: Cinematic")));
    }
    // Min spec: GTX 1060 6 GB at 1080p 60 Hz -> Low, TSR Balanced, cap 60, VSync on.
    {
        const FSaskartaDetectedProfile P = L::Recommend(Specs(TEXT("NVIDIA GeForce GTX 1060 6GB"), 0x10DE, 6144, 200.f, 1920, 1080, 60, 4, 16));
        TestEqual("1060 Low", P.RecommendedLevel, 0);
        TestEqual("1060 balanced", P.UpscalerMode, 1);
        TestEqual("1060 pct", P.ScreenPercentage, 58.f);
        TestEqual("1060 cap", P.FrameRateLimit, 60.f);
        TestTrue("1060 vsync on a 60 Hz display", P.bVSync);
        TestEqual("1060 AA at least Medium", P.AntiAliasingQuality, 1);
    }
    // The same card with a good score lifts to Medium (Entry is Low/Medium).
    {
        const FSaskartaDetectedProfile P = L::Recommend(Specs(TEXT("NVIDIA GeForce GTX 1060 6GB"), 0x10DE, 6144, 300.f));
        TestEqual("1060 good score Medium", P.RecommendedLevel, 1);
    }
    // ... but not with 4 GB.
    {
        const FSaskartaDetectedProfile P = L::Recommend(Specs(TEXT("AMD Radeon RX 6500 XT"), 0x1002, 4096, 300.f));
        TestEqual("6500 XT stays Low", P.RecommendedLevel, 0);
    }
    // Integrated: Low, Performance mode, Low textures.
    {
        const FSaskartaDetectedProfile P = L::Recommend(Specs(TEXT("Intel(R) UHD Graphics 630"), 0x8086, 128, 40.f, 1920, 1080, 60, 4, 8, true));
        TestEqual("iGPU Low", P.RecommendedLevel, 0);
        TestEqual("iGPU performance mode", P.UpscalerMode, 2);
        TestEqual("iGPU textures", P.TextureQuality, 0);
        TestEqual("iGPU class", ClassName(P.GPUClass), ClassName(ESaskartaGPUClass::Integrated));
    }
    // Recommended spec: RTX 3060 12 GB at 1080p 144 Hz -> High, TSR Quality, cap 144.
    {
        const FSaskartaDetectedProfile P = L::Recommend(Specs(TEXT("NVIDIA GeForce RTX 3060"), 0x10DE, 12288, 900.f, 1920, 1080, 144, 6, 16));
        TestEqual("3060 High", P.RecommendedLevel, 2);
        TestEqual("3060 pct", P.ScreenPercentage, 66.7f);
        TestEqual("3060 cap (144 Hz display, hard cap 60)", P.FrameRateLimit, 60.f);
        TestFalse("3060 no vsync at 144 Hz", P.bVSync);
    }
    // A score far below the class drops one level.
    {
        const FSaskartaDetectedProfile P = L::Recommend(Specs(TEXT("NVIDIA GeForce RTX 3060"), 0x10DE, 12288, 100.f));
        TestEqual("throttled 3060 Medium", P.RecommendedLevel, 1);
    }
    // VRAM guards.
    {
        const FSaskartaDetectedProfile P = L::Recommend(Specs(TEXT("NVIDIA GeForce RTX 3060"), 0x10DE, 3072, 900.f));
        TestEqual("3 GB textures Low", P.TextureQuality, 0);
        TestEqual("3 GB shadows Medium", P.ShadowQuality, 1);
        TestEqual("3 GB GI Medium", P.GlobalIlluminationQuality, 1);
        TestEqual("3 GB preset limited to Medium", P.RecommendedLevel, 1);
        const FSaskartaDetectedProfile Q = L::Recommend(Specs(TEXT("NVIDIA GeForce RTX 3060"), 0x10DE, 5120, 900.f));
        TestEqual("5 GB textures Medium", Q.TextureQuality, 1);
        TestEqual("TextureCapForVRAM 8 GB", L::TextureCapForVRAM(8192), 3);
        TestEqual("TextureCapForVRAM unknown", L::TextureCapForVRAM(-1), 3);
    }
    // RAM and CPU caps.
    {
        const FSaskartaDetectedProfile P = L::Recommend(Specs(TEXT("NVIDIA GeForce RTX 4080"), 0x10DE, 16384, 3000.f, 2560, 1440, 144, 8, 8));
        TestEqual("8 GB RAM view distance", P.ViewDistanceQuality, 1);
        TestEqual("8 GB RAM foliage", P.FoliageQuality, 1);
        TestEqual("8 GB RAM textures", P.TextureQuality, 1);
        TestEqual("8 GB RAM shadows untouched", P.ShadowQuality, 3);
        const FSaskartaDetectedProfile Q = L::Recommend(Specs(TEXT("NVIDIA GeForce RTX 4080"), 0x10DE, 16384, 3000.f, 2560, 1440, 144, 2, 32));
        TestEqual("2 cores shadows", Q.ShadowQuality, 1);
        TestEqual("2 cores effects", Q.EffectsQuality, 1);
        TestEqual("2 cores GI untouched", Q.GlobalIlluminationQuality, 3);
    }
    // Upscaler by output size.
    {
        const FSaskartaDetectedProfile Native = L::Recommend(Specs(TEXT("NVIDIA GeForce RTX 4080"), 0x10DE, 16384, 3000.f, 1920, 1080, 144));
        TestEqual("Epic 1080p native", Native.UpscalerMethod, 2);
        TestEqual("Epic 1080p 100 %", Native.ScreenPercentage, 100.f);
        const FSaskartaDetectedProfile K4 = L::Recommend(Specs(TEXT("NVIDIA GeForce RTX 4070"), 0x10DE, 12288, 1600.f, 3840, 2160, 60));
        TestEqual("Epic 4K balanced", K4.ScreenPercentage, 58.f);
        TestTrue("4K 60 Hz vsync", K4.bVSync);
        const FSaskartaDetectedProfile Low1440 = L::Recommend(Specs(TEXT("NVIDIA GeForce GTX 1650"), 0x10DE, 4096, 150.f, 2560, 1440, 144));
        TestEqual("Low 1440p 50 %", Low1440.ScreenPercentage, 50.f);
        TestEqual("Low caps at 60", Low1440.FrameRateLimit, 60.f);
        const FSaskartaDetectedProfile Med1440 = L::Recommend(Specs(TEXT("AMD Radeon RX 6600"), 0x1002, 8192, 600.f, 2560, 1440, 144));
        TestEqual("Medium 1440p 58 %", Med1440.ScreenPercentage, 58.f);
    }
    // Unknown GPUs: Medium without a score, never above High with one. Cinematic never.
    {
        TestEqual("unknown no score", L::Recommend(Specs(TEXT("Mystery Accelerator"), 0, 8192, -1.f)).RecommendedLevel, 1);
        TestEqual("unknown low score", L::Recommend(Specs(TEXT("Mystery Accelerator"), 0, 8192, 100.f)).RecommendedLevel, 0);
        TestEqual("unknown huge score", L::Recommend(Specs(TEXT("Mystery Accelerator"), 0, 24576, 9000.f)).RecommendedLevel, 2);
        TestEqual("5090 automatically Cinematic", L::Recommend(Specs(TEXT("NVIDIA GeForce RTX 5090"), 0x10DE, 32768, 9000.f)).RecommendedLevel, 4);
    }
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaConsumerMemoryTest, "Saskarta.Perf.ConsumerMemoryAndCinematic",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)
bool FSaskartaConsumerMemoryTest::RunTest(const FString&)
{
    using namespace SaskartaPerfTest;
    using L = USaskartaHardwareProfileLibrary;
    const FSaskartaDetectedProfile FourGB = L::Recommend(Specs(TEXT("NVIDIA GeForce RTX 5070"), 0x10DE, 4096, 2000.f, 1920, 1080, 60, 8, 16));
    TestEqual("4 GB never promotes despite a strong GPU score", FourGB.RecommendedLevel, 1);
    TestEqual("4 GB shadows Medium", FourGB.ShadowQuality, 1);
    TestEqual("4 GB GI Medium", FourGB.GlobalIlluminationQuality, 1);
    TestEqual("4 GB effects Medium", FourGB.EffectsQuality, 1);
    TestEqual("4 GB textures Medium", FourGB.TextureQuality, 1);
    TestEqual("4 GB 1080p TSR Quality", FourGB.ScreenPercentage, 66.7f);
    const FSaskartaDetectedProfile Strong = L::Recommend(Specs(TEXT("NVIDIA GeForce RTX 5070"), 0x10DE, 11943, 2000.f));
    TestEqual("12 GB driver reserve still permits Cinematic", Strong.RecommendedLevel, 4);
    TestEqual("Cinematic foliage is not accidentally capped at Epic", Strong.FoliageQuality, 4);
    TestEqual("Cinematic 1080p native", Strong.ScreenPercentage, 100.f);
    TestEqual("16 GB RAM does not auto-promote to Cinematic", L::Recommend(Specs(TEXT("NVIDIA GeForce RTX 5070"), 0x10DE, 11943, 2000.f, 1920, 1080, 60, 8, 16)).RecommendedLevel, 3);
    TestEqual("8 GB GPU does not auto-promote to Cinematic", L::Recommend(Specs(TEXT("NVIDIA GeForce RTX 5070"), 0x10DE, 8192, 2000.f)).RecommendedLevel, 3);
    TestEqual("missing GPU benchmark does not promote", L::Recommend(Specs(TEXT("NVIDIA GeForce RTX 5070"), 0x10DE, 11943, -1.f)).RecommendedLevel, 3);
    TestEqual("weak CPU does not promote", L::Recommend(Specs(TEXT("NVIDIA GeForce RTX 5070"), 0x10DE, 11943, 2000.f, 1920, 1080, 60, 4)).RecommendedLevel, 3);
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaPerfTierCVarsTest, "Saskarta.Perf.TierCVars",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)
bool FSaskartaPerfTierCVarsTest::RunTest(const FString&)
{
    const TMap<FString, FString> Low = USaskartaGameUserSettings::ComputeTierCVars(0, 0, 0, 4096, true);
    TestEqual("low vsm bias", Low.FindRef(TEXT("r.Shadow.Virtual.ResolutionLodBiasDirectional")), FString(TEXT("2.00")));
    TestEqual("low nanite edge", Low.FindRef(TEXT("r.Nanite.MaxPixelsPerEdge")), FString(TEXT("2.50")));
    TestEqual("4 GB pool", Low.FindRef(TEXT("r.Streaming.PoolSize")), FString(TEXT("1400")));
    TestEqual("low software lumen", Low.FindRef(TEXT("r.Lumen.HardwareRayTracing")), FString(TEXT("0")));

    const TMap<FString, FString> High = USaskartaGameUserSettings::ComputeTierCVars(2, 2, 2, 12288, true);
    TestEqual("high vsm bias = project value", High.FindRef(TEXT("r.Shadow.Virtual.ResolutionLodBiasDirectional")), FString(TEXT("0.00")));
    TestEqual("high nanite edge = project value", High.FindRef(TEXT("r.Nanite.MaxPixelsPerEdge")), FString(TEXT("1.50")));
    TestEqual("12 GB pool = project value", High.FindRef(TEXT("r.Streaming.PoolSize")), FString(TEXT("3072")));
    TestEqual("high HWRT", High.FindRef(TEXT("r.Lumen.HardwareRayTracing")), FString(TEXT("1")));

    const TMap<FString, FString> Gov = USaskartaGameUserSettings::ComputeTierCVars(1, 1, 2, -1, false);
    TestFalse("governor never recreates render state", Gov.Contains(TEXT("r.Lumen.HardwareRayTracing")));
    TestFalse("unknown VRAM leaves the pool", Gov.Contains(TEXT("r.Streaming.PoolSize")));
    TestEqual("medium vsm bias", Gov.FindRef(TEXT("r.Shadow.Virtual.ResolutionLodBiasDirectional")), FString(TEXT("1.00")));
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaPerfHeadroomCeilingTest, "Saskarta.Perf.HeadroomCeiling",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)
bool FSaskartaPerfHeadroomCeilingTest::RunTest(const FString&)
{
    // Task HEADROOM: the reserve functions themselves - max(floor, share), and unknown (<= 0) falls
    // back to the floor rather than 0.
    using L = USaskartaHardwareProfileLibrary;
    TestEqual("VRAM reserve floor below the share (2 GB card)", L::VRAMHeadroomMB(2048), 1536);
    TestEqual("VRAM reserve is the share above the floor (16 GB card)", L::VRAMHeadroomMB(16384), FMath::RoundToInt(16384 * 0.15f));
    TestEqual("VRAM reserve floor when unknown", L::VRAMHeadroomMB(-1), 1536);
    TestEqual("RAM reserve floor below the share (8 GB machine)", L::RAMHeadroomMB(8), 4096);
    TestEqual("RAM reserve is the share above the floor (32 GB machine)", L::RAMHeadroomMB(32), FMath::RoundToInt(32 * 1024.f * 0.25f));
    TestEqual("RAM reserve floor when unknown", L::RAMHeadroomMB(-1), 4096);

    // Unchanged behaviour for every call site from before task HEADROOM (RAMGB defaults to unknown):
    // the two tiers Saskarta.Perf.TierCVars already pins (4 GB -> 1400, 12 GB -> 3072) are untouched,
    // because their un-clamped step value already fits under the VRAM-only reserve.
    TestEqual("4 GB unchanged (RAM unknown)", L::StreamingPoolForVRAM(4096), 1400);
    TestEqual("12 GB unchanged (RAM unknown)", L::StreamingPoolForVRAM(12288), 3072);
    TestEqual("unknown VRAM still passes through", L::StreamingPoolForVRAM(-1), -1);
    TestEqual("unknown VRAM still passes through (RAM known)", L::StreamingPoolForVRAM(-1, 32), -1);

    // A small card's un-clamped step (600 for < 3 GB) already exceeds what a 2 GB card can spare
    // once its own VRAM reserve (max(1536, 15%) = 1536 MB) comes out of 2048 MB: 2048-1536=512.
    TestEqual("small card: VRAM reserve tightens the pool", L::StreamingPoolForVRAM(2048), 512);

    // A big card is unaffected by the VRAM side (24 GB: reserve 3686, budget 20890, step 3072 fits),
    // but a tight RAM machine (6 GB: reserve max(4096, 1536)=4096, budget 6144-4096=2048) still
    // tightens it via the RAM side.
    TestEqual("big VRAM, tight RAM: RAM reserve tightens the pool", L::StreamingPoolForVRAM(24576, 6), 2048);
    TestEqual("big VRAM, ample RAM: unaffected", L::StreamingPoolForVRAM(24576, 32), 3072);

    // The floor: an old/weak machine (1 GB VRAM, 4 GB RAM) never goes below StreamingPoolFloorMB,
    // even though both reserves alone would drive the budget to 0 or negative.
    TestEqual("floor: pool never collapses to 0", L::StreamingPoolForVRAM(1024, 4), 512);

    // ComputeTierCVars threads RAMGB through unchanged when omitted, and applies it when given.
    const TMap<FString, FString> NoRam = USaskartaGameUserSettings::ComputeTierCVars(0, 0, 0, 2048, true);
    TestEqual("ComputeTierCVars RAM-unaware matches StreamingPoolForVRAM(2048)", NoRam.FindRef(TEXT("r.Streaming.PoolSize")), FString(TEXT("512")));
    const TMap<FString, FString> WithRam = USaskartaGameUserSettings::ComputeTierCVars(2, 2, 2, 24576, true, 6);
    TestEqual("ComputeTierCVars RAM-aware matches StreamingPoolForVRAM(24576, 6)", WithRam.FindRef(TEXT("r.Streaming.PoolSize")), FString(TEXT("2048")));
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaPerfTriggerTest, "Saskarta.Perf.AutoDetectTriggerAndTarget",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)
bool FSaskartaPerfTriggerTest::RunTest(const FString&)
{
    using S = USaskartaGameUserSettings;
    TestTrue("first launch", S::ShouldAutoDetect(false, false, TEXT(""), TEXT("NVIDIA GeForce RTX 5070")));
    TestFalse("existing player keeps settings", S::ShouldAutoDetect(true, false, TEXT(""), TEXT("NVIDIA GeForce RTX 5070")));
    TestTrue("GPU changed", S::ShouldAutoDetect(true, true, TEXT("NVIDIA GeForce RTX 3060"), TEXT("NVIDIA GeForce RTX 5070")));
    TestFalse("same GPU", S::ShouldAutoDetect(true, true, TEXT("NVIDIA GeForce RTX 5070"), TEXT("nvidia geforce rtx 5070")));
    TestFalse("no RHI", S::ShouldAutoDetect(false, false, TEXT(""), TEXT("")));

    TestEqual("60 mode on 144 Hz", S::ComputeAdaptiveTargetFps(1, 0.f, 144, false), 60.f);
    TestEqual("display mode uncapped", S::ComputeAdaptiveTargetFps(2, 0.f, 144, false), 144.f);
    TestEqual("display mode capped", S::ComputeAdaptiveTargetFps(2, 120.f, 144, false), 120.f);
    TestEqual("cap below 60", S::ComputeAdaptiveTargetFps(1, 30.f, 144, false), 30.f);
    TestEqual("30 mode", S::ComputeAdaptiveTargetFps(0, 0.f, 0, false), 30.f);
    TestEqual("display unknown refresh", S::ComputeAdaptiveTargetFps(2, 0.f, -1, false), 60.f);
    TestEqual("vsync 50 Hz", S::ComputeAdaptiveTargetFps(1, 0.f, 50, true), 50.f);
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaPerfGovernorTest, "Saskarta.Perf.Governor",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)
bool FSaskartaPerfGovernorTest::RunTest(const FString&)
{
    using namespace SaskartaPerfTest;
    using EA = FSaskartaGovernorCore::EAction;
    using C = FSaskartaGovernorCore;

    // 1. Below target: the 5 s window fills at t = 5.0, the 10 s hold ends at t = 15.0.
    {
        FSaskartaGovernorCore Core = MakeCore();
        const double T = Feed(Core, 0.0, 30.0, 25.f, 24.f, EA::StepDown);
        TestEqual("first down at 15 s", T, 15.0);
        TestEqual("resolution first (66.7 -> 58.35)", Core.GetCurrent().ScreenPct, 58.35f, 0.01f);
        TestEqual("groups untouched", Core.GetCurrent().Levels[C::Shadow], 2);
    }
    // 2. The whole ladder: resolution to 50 %, then groups in order; GI and Effects stop at Medium.
    {
        FSaskartaGovernorCore Core = MakeCore();
        TArray<C::FStep> Steps;
        Feed(Core, 0.0, 600.0, 25.f, 24.f, EA::StepDown, &Steps, false);
        TestEqual("12 downs to the floor", Steps.Num(), 12);
        TestTrue("at floor", Core.IsAtFloor());
        TestEqual("floor pct", Core.GetCurrent().ScreenPct, 50.f, 0.01f);
        if (Steps.Num() == 12)
        {
            TestTrue("step 1 resolution", Steps[0].bResolution);
            TestTrue("step 2 resolution", Steps[1].bResolution);
            const int32 Order[] = { C::Shadow, C::GlobalIllumination, C::Reflection, C::ViewDistance, C::Effects, C::Foliage,
                C::Shadow, C::Reflection, C::ViewDistance, C::Foliage };
            for (int32 I = 0; I < static_cast<int32>(UE_ARRAY_COUNT(Order)); ++I)
            {
                TestEqual(*FString::Printf(TEXT("step %d group"), I + 3), Steps[I + 2].Group, Order[I]);
            }
        }
        TestEqual("GI floor Medium", Core.GetCurrent().Levels[C::GlobalIllumination], 1);
        TestEqual("Effects floor Medium", Core.GetCurrent().Levels[C::Effects], 1);
        TestEqual("Shadows floor Low", Core.GetCurrent().Levels[C::Shadow], 0);
    }
    // 3. A hitch is dropped, not acted on.
    {
        FSaskartaGovernorCore Core = MakeCore();
        TestEqual("steady", Feed(Core, 0.0, 10.0, 16.f, 12.f, EA::StepDown), -1.0);
        TestTrue("hitch ignored", Core.Update(10.5, 300.f, 290.f, 100.f) == EA::None);
        TestEqual("hitch counted", Core.GetDroppedHitches(), 1);
        TestEqual("still steady", Feed(Core, 10.5, 60.0, 16.f, 12.f, EA::StepDown), -1.0);
        TestEqual("no step", Core.GetDepth(), 0);
    }
    // 4. Hysteresis band: 17.5 ms (57 fps) is neither "below" (> 18.3 ms) nor "headroom"; GPU 13 ms is
    //    inside the 14.2 ms GPU budget.
    {
        FSaskartaGovernorCore Core = MakeCore();
        Core.StepDown(0.0);
        TArray<C::FStep> Steps;
        Feed(Core, 0.0, 300.0, 17.5f, 13.f, EA::StepDown, &Steps, false);
        TestEqual("no action in the band", Steps.Num(), 0);
        TestEqual("depth kept", Core.GetDepth(), 1);
    }
    // 5. Headroom: up only after 30 s of headroom AND 60 s after the last down; never past the baseline.
    FSaskartaGovernorCore Core = MakeCore();
    {
        Core.StepDown(0.0);
        const double Up = Feed(Core, 0.0, 120.0, 16.6f, 8.f, EA::StepUp);
        TestEqual("up at 60 s", Up, 60.0);
        TestEqual("back to baseline", Core.GetDepth(), 0);
        TestTrue("baseline restored", Core.GetCurrent() == Core.GetBaseline());
        TestEqual("never above the user's settings", Feed(Core, 60.0, 300.0, 16.6f, 4.f, EA::StepUp), -1.0);
    }
    // 6. Flip-flop: a down within 90 s of an up blocks ups for 10 minutes.
    {
        FSaskartaGovernorCore Fresh = MakeCore();
        Fresh.StepDown(0.0);
        const double Up = Feed(Fresh, 0.0, 120.0, 16.6f, 8.f, EA::StepUp);
        TestEqual("up", Up, 60.0);
        const double Down = Feed(Fresh, Up, Up + 60.0, 25.f, 24.f, EA::StepDown);
        TestEqual("down 16.5 s after the up", Down, 76.5);
        TestTrue("ups blocked", Fresh.AreUpsBlocked(Down + 599.0));
        const double Up2 = Feed(Fresh, Down, Down + 700.0, 16.6f, 8.f, EA::StepUp);
        TestEqual("next up only after the penalty", Up2, Down + 600.0);
    }
    // 7. Loading/pause invalidation restarts the window.
    {
        FSaskartaGovernorCore Fresh = MakeCore();
        Feed(Fresh, 0.0, 4.0, 25.f, 24.f, EA::StepDown);
        Fresh.Invalidate();
        TestEqual("window restarted", Fresh.GetNumSamples(), 0);
        TestEqual("no down before the new window and hold", Feed(Fresh, 4.0, 18.5, 25.f, 24.f, EA::StepDown), -1.0);
        TestEqual("down after the new window and hold", Feed(Fresh, 18.5, 30.0, 25.f, 24.f, EA::StepDown), 19.0);
    }
    // 8. From native: three even resolution steps.
    {
        FSaskartaGovernorCore Native = MakeCore(100.f);
        Native.StepDown(0.0);
        TestEqual("83.3", Native.GetCurrent().ScreenPct, 83.33f, 0.01f);
        Native.StepDown(1.0);
        TestEqual("66.7", Native.GetCurrent().ScreenPct, 66.67f, 0.01f);
        Native.StepDown(2.0);
        TestEqual("50", Native.GetCurrent().ScreenPct, 50.f, 0.01f);
        Native.StepDown(3.0);
        TestEqual("then shadows", Native.GetCurrent().Levels[C::Shadow], 1);
    }
    // 9. Render-thread bound (the user's 5070 profile: frame 19.7 ms, GPU 8.6 ms, render thread
    //    19 ms): view distance, foliage, shadows, effects; resolution untouched.
    {
        FSaskartaGovernorCore Cpu = MakeCore();
        TArray<C::FStep> Steps;
        Feed(Cpu, 0.0, 600.0, 19.7f, 8.6f, EA::StepDown, &Steps, false, 19.f);
        TestTrue("cpu-bound detected", Steps.Num() > 0 && Steps[0].bCpuBound);
        const int32 Order[] = { C::ViewDistance, C::Foliage, C::Shadow, C::Effects, C::ViewDistance, C::Foliage, C::Shadow };
        TestEqual("7 CPU steps, then nothing", Steps.Num(), static_cast<int32>(UE_ARRAY_COUNT(Order)));
        for (int32 I = 0; I < FMath::Min(Steps.Num(), static_cast<int32>(UE_ARRAY_COUNT(Order))); ++I)
        {
            TestEqual(*FString::Printf(TEXT("cpu step %d group"), I + 1), Steps[I].Group, Order[I]);
        }
        TestEqual("resolution untouched", Cpu.GetCurrent().ScreenPct, 66.7f, 0.01f);
        TestEqual("GI untouched", Cpu.GetCurrent().Levels[C::GlobalIllumination], 2);
    }
    // 10. A user on Low: nothing below their own floor except resolution.
    {
        FSaskartaGovernorCore Low = MakeCore(50.f, 0);
        TestFalse("nothing to lower", Low.StepDown(0.0));
        TestTrue("at floor", Low.IsAtFloor());
    }
    // 11. GPU headroom: on the 60 fps cap (16.6 ms) but the GPU busy 15.5 ms (> 0.85 x 16.7 = 14.2 ms)
    //     -> a step down, so a recorder or a stream keeps some GPU; resolution first.
    {
        FSaskartaGovernorCore Gpu = MakeCore();
        TestEqual("gpu budget down at 15 s", Feed(Gpu, 0.0, 30.0, 16.6f, 15.5f, EA::StepDown), 15.0);
        TestEqual("resolution first", Gpu.GetCurrent().ScreenPct, 58.35f, 0.01f);
    }
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaPerfTransientPIEFpsCapTest, "Saskarta.Perf.TransientPIEFpsCap",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)
bool FSaskartaPerfTransientPIEFpsCapTest::RunTest(const FString&)
{
    constexpr float Cap = 60.f;
    float Restore = -1.f;

    FSaskartaTransientPIEFpsCap Unset;
    TestTrue("unset cap is applied", Unset.Begin(0.f, Cap));
    TestEqual("unset is capped to policy", Unset.AppliedFps, Cap);
    TestTrue("unset cap restores", Unset.GetRestoreValue(Cap, Restore));
    TestEqual("unset restores to uncapped", Restore, 0.f);

    FSaskartaTransientPIEFpsCap High;
    TestTrue("higher user cap is lowered", High.Begin(120.f, Cap));
    TestEqual("higher cap is lowered to policy", High.AppliedFps, Cap);
    TestFalse("do not restore while another PIE world remains", High.CanRestore(1));
    TestTrue("restore becomes eligible after the last PIE world", High.CanRestore(0));
    TestTrue("higher cap restores if untouched", High.GetRestoreValue(Cap, Restore));
    TestEqual("higher cap restored", Restore, 120.f);

    FSaskartaTransientPIEFpsCap Stricter;
    TestFalse("stricter user cap is preserved", Stricter.Begin(24.f, Cap));
    TestFalse("stricter cap is never claimed", Stricter.GetRestoreValue(24.f, Restore));

    FSaskartaTransientPIEFpsCap Equal;
    TestFalse("existing cap equal to policy is preserved", Equal.Begin(Cap, Cap));

    FSaskartaTransientPIEFpsCap ChangedHigher;
    TestTrue("temporary cap starts", ChangedHigher.Begin(120.f, Cap));
    TestFalse("external higher change is preserved", ChangedHigher.GetRestoreValue(90.f, Restore));

    FSaskartaTransientPIEFpsCap ChangedStricter;
    TestTrue("temporary cap starts before stricter change", ChangedStricter.Begin(120.f, Cap));
    TestFalse("external stricter change is preserved", ChangedStricter.GetRestoreValue(20.f, Restore));

    FSaskartaTransientPIEFpsCap ChangedSlightly;
    TestTrue("temporary cap starts before small external change", ChangedSlightly.Begin(120.f, Cap));
    TestFalse("small external change is preserved", ChangedSlightly.GetRestoreValue(59.99f, Restore));
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaPerfTransientPIEQualityCapTest, "Saskarta.Perf.TransientPIEQualityCap",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)
bool FSaskartaPerfTransientPIEQualityCapTest::RunTest(const FString&)
{
    constexpr int32 High = 2;
    const TArray<int32> Current = { 4, 4, 4, 4, 4, 4, 4 };
    const TArray<int32> Applied = { 2, 2, 2, 2, 2, 2, 2 };
    FSaskartaTransientPIEQualityCap Cap;
    TestTrue("PIE claims levels above High", Cap.Begin(Current, High));
    TestTrue("all seven PIE groups are capped at High", Cap.AppliedLevels == Applied);
    TestTrue("do not restore until the last PIE world closes", Cap.CanRestore(0));
    TestFalse("still owned while another PIE world remains", Cap.CanRestore(1));

    TArray<int32> Restore;
    TestTrue("untouched groups restore their original values", Cap.GetRestoreLevels(Cap.AppliedLevels, Restore));
    TestTrue("all untouched groups return to Epic", Restore == Current);

    const TArray<int32> MixedExternal = { 2, 3, 2, 2, 1, 2, 2 };
    const TArray<int32> ExpectedMixedRestore = { 4, 3, 4, 4, 1, 4, 4 };
    TestTrue("at least one group remains ours", Cap.GetRestoreLevels(MixedExternal, Restore));
    TestTrue("only the externally changed group remains changed", Restore == ExpectedMixedRestore);

    FSaskartaTransientPIEQualityCap Stricter;
    const TArray<int32> ExistingLowLevels = { 0, 1, 2, 0, 1, 2, 0 };
    TestFalse("lower or equal user levels are preserved", Stricter.Begin(ExistingLowLevels, High));
    TestTrue("stricter quality is not claimed", Stricter.AppliedLevels == ExistingLowLevels);
    return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS
