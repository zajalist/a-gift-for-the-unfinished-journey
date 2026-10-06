// Hardware detection and the pure recommendation rules. See SaskartaHardwareProfile.h and
// Tools/Perf/SCALABILITY.md (the tier table).

#include "SaskartaHardwareProfile.h"
#include "SaskartaGameUserSettings.h"

#include "DynamicRHI.h"
#include "Engine/Engine.h"
#include "GameFramework/GameUserSettings.h"
#include "HAL/PlatformMemory.h"
#include "HAL/PlatformMisc.h"
#include "RHI.h"
#include "RHIGlobals.h"
#include "RHIStats.h"

#if PLATFORM_WINDOWS
#include "Windows/AllowWindowsPlatformTypes.h"
#include <windows.h>
#include "Windows/HideWindowsPlatformTypes.h"
#endif

#define LOCTEXT_NAMESPACE "SaskartaHardwareProfile"

// Named namespace, not anonymous: unity builds merge this file with the others.
namespace SaskartaHardwareProfileLocal
{
    /**
     * The model number after Token in a lower-case adapter name, e.g. "rtx" in
     * "nvidia geforce rtx 4070 super" -> 4070. Spaces and dashes after the token are skipped;
     * with bAllowLetterPrefix one letter is too ("arc a770" -> 770, Letter 'a').
     * OutMobileSuffix is true when the digits end in 'm' ("rx 6600m"). -1 if absent.
     */
    static int32 ModelAfter(const FString& Lower, const TCHAR* Token, bool bAllowLetterPrefix, TCHAR* OutLetter, bool* OutMobileSuffix)
    {
        int32 Search = 0;
        while (Search < Lower.Len())
        {
            const int32 Idx = Lower.Find(Token, ESearchCase::CaseSensitive, ESearchDir::FromStart, Search);
            if (Idx == INDEX_NONE)
            {
                return -1;
            }
            int32 I = Idx + FCString::Strlen(Token);
            while (I < Lower.Len() && (Lower[I] == TEXT(' ') || Lower[I] == TEXT('-')))
            {
                ++I;
            }
            TCHAR Letter = 0;
            if (bAllowLetterPrefix && I < Lower.Len() && FChar::IsAlpha(Lower[I]))
            {
                Letter = Lower[I];
                ++I;
            }
            int32 Value = 0;
            int32 Digits = 0;
            while (I < Lower.Len() && FChar::IsDigit(Lower[I]) && Digits < 5)
            {
                Value = Value * 10 + (Lower[I] - TEXT('0'));
                ++I;
                ++Digits;
            }
            if (Digits >= 2)
            {
                if (OutLetter)
                {
                    *OutLetter = Letter;
                }
                if (OutMobileSuffix)
                {
                    *OutMobileSuffix = I < Lower.Len() && Lower[I] == TEXT('m');
                }
                return Value;
            }
            Search = Idx + 1;
        }
        return -1;
    }

    static ESaskartaGPUClass ClassifyNvidia(const FString& L)
    {
        if (L.Contains(TEXT(" mx")) || L.Contains(TEXT("geforce mx")))
        {
            return ESaskartaGPUClass::Integrated;
        }
        const int32 Rtx = ModelAfter(L, TEXT("rtx"), false, nullptr, nullptr);
        if (Rtx >= 1000 && Rtx < 10000)
        {
            const int32 Series = Rtx / 1000; // 2 = 20xx, 3 = 30xx ...
            const int32 Model = (Rtx % 100) / 10; // 4070 -> 7, 2060 -> 6, 5050 -> 5
            switch (Series)
            {
            case 2:
                return Model <= 5 ? ESaskartaGPUClass::Entry : Model == 6 ? ESaskartaGPUClass::Mainstream : ESaskartaGPUClass::Performance;
            case 3:
                return Model <= 5 ? ESaskartaGPUClass::Mainstream : Model <= 7 ? ESaskartaGPUClass::Performance : ESaskartaGPUClass::Enthusiast;
            case 4:
                return Model <= 5 ? ESaskartaGPUClass::Mainstream : Model == 6 ? ESaskartaGPUClass::Performance : ESaskartaGPUClass::Enthusiast;
            default: // 50xx and later
                return Model <= 6 ? ESaskartaGPUClass::Performance : ESaskartaGPUClass::Enthusiast;
            }
        }
        const int32 Gtx = ModelAfter(L, TEXT("gtx"), false, nullptr, nullptr);
        if (Gtx >= 1600 && Gtx < 1700)
        {
            return Gtx >= 1660 ? ESaskartaGPUClass::Mainstream : ESaskartaGPUClass::Entry; // 1630/1650 Entry
        }
        if (Gtx >= 1000 && Gtx < 1100)
        {
            if (Gtx >= 1080) { return ESaskartaGPUClass::Mainstream; }
            if (Gtx >= 1050) { return ESaskartaGPUClass::Entry; }
            return ESaskartaGPUClass::Integrated;
        }
        if (Gtx >= 900 && Gtx < 1000)
        {
            return Gtx >= 970 ? ESaskartaGPUClass::Entry : ESaskartaGPUClass::Integrated;
        }
        if (Gtx > 0 || ModelAfter(L, TEXT("gt "), false, nullptr, nullptr) > 0)
        {
            return ESaskartaGPUClass::Integrated; // GTX 7xx and older, GT 710/730/1030
        }
        return ESaskartaGPUClass::Unknown; // Quadro/RTX Axxxx/Titan: the score decides
    }

    static ESaskartaGPUClass ClassifyAmd(const FString& L, bool& bOutMobile)
    {
        if (L.Contains(TEXT("vega")))
        {
            // RX Vega 56/64 are discrete; "Radeon (RX) Vega 3/8/11 Graphics" are Ryzen iGPUs.
            return (L.Contains(TEXT("56")) || L.Contains(TEXT("64"))) ? ESaskartaGPUClass::Mainstream : ESaskartaGPUClass::Integrated;
        }
        bool bMobile = false;
        const int32 Rx = ModelAfter(L, TEXT("rx"), false, nullptr, &bMobile);
        bOutMobile = bMobile;
        if (Rx >= 9000 && Rx < 10000)
        {
            return ((Rx % 100) / 10) >= 7 ? ESaskartaGPUClass::Enthusiast : ESaskartaGPUClass::Performance; // 9060 / 9070
        }
        if (Rx >= 5000 && Rx < 9000)
        {
            const int32 Series = Rx / 1000;
            const int32 Model = (Rx % 1000) / 100; // 6600 -> 6, 7800 -> 8
            switch (Series)
            {
            case 5:
                return Model <= 5 ? ESaskartaGPUClass::Entry : ESaskartaGPUClass::Mainstream;
            case 6:
                return Model <= 5 ? ESaskartaGPUClass::Entry : Model == 6 ? ESaskartaGPUClass::Mainstream : Model == 7 ? ESaskartaGPUClass::Performance : ESaskartaGPUClass::Enthusiast;
            case 7:
                return Model <= 5 ? ESaskartaGPUClass::Mainstream : Model <= 7 ? ESaskartaGPUClass::Performance : ESaskartaGPUClass::Enthusiast;
            default:
                return ESaskartaGPUClass::Performance;
            }
        }
        if (Rx >= 400 && Rx < 600)
        {
            const int32 Model = (Rx % 100) / 10; // 580 -> 8, 550 -> 5
            return Model <= 5 ? ESaskartaGPUClass::Integrated : ESaskartaGPUClass::Entry; // RX 550 is GT 1030 class
        }
        // "AMD Radeon(TM) Graphics", "Radeon 780M Graphics": APUs.
        const int32 Bare = ModelAfter(L, TEXT("radeon"), false, nullptr, &bMobile);
        if (L.Contains(TEXT("radeon graphics")) || (Bare > 0 && bMobile))
        {
            return ESaskartaGPUClass::Integrated;
        }
        return ESaskartaGPUClass::Unknown;
    }

    static ESaskartaGPUClass ClassifyIntel(const FString& L)
    {
        TCHAR Letter = 0;
        const int32 Arc = ModelAfter(L, TEXT("arc"), true, &Letter, nullptr);
        if (Arc >= 100 && (Letter == TEXT('a') || Letter == TEXT('b')))
        {
            if (Letter == TEXT('b')) { return ESaskartaGPUClass::Performance; } // B570/B580
            if (Arc >= 700) { return ESaskartaGPUClass::Performance; } // A750/A770
            if (Arc >= 500) { return ESaskartaGPUClass::Mainstream; } // A580
            return ESaskartaGPUClass::Entry; // A310/A380
        }
        return ESaskartaGPUClass::Integrated; // UHD, Iris Xe, "Arc Graphics" (Meteor/Lunar Lake iGPU)
    }

    static FString VRAMText(int32 VRAMMB)
    {
        if (VRAMMB >= 1024)
        {
            return FString::Printf(TEXT("%d GB"), FMath::RoundToInt(VRAMMB / 1024.f));
        }
        if (VRAMMB > 0)
        {
            return FString::Printf(TEXT("%d MB"), VRAMMB);
        }
        return TEXT("VRAM unknown");
    }

    static void Cap(int32& Level, int32 Max, const TCHAR* Group, const FString& Why, TArray<FString>& Reasons)
    {
        if (Level > Max)
        {
            Reasons.Add(FString::Printf(TEXT("%s capped at %s (%s)"), Group, *USaskartaHardwareProfileLibrary::LevelName(Max), *Why));
            Level = Max;
        }
    }
}

FSaskartaHardwareSpecs USaskartaHardwareProfileLibrary::GatherHardwareSpecs()
{
    FSaskartaHardwareSpecs S;
    S.GPUName = GRHIAdapterName.TrimStartAndEnd();
    S.VendorId = static_cast<int32>(GRHIVendorId);
    S.bIntegrated = GRHIDeviceIsIntegrated;
    S.DriverVersion = GRHIAdapterUserDriverVersion;

    if (GDynamicRHI)
    {
        FTextureMemoryStats Stats;
        RHIGetTextureMemoryStats(Stats);
        if (Stats.DedicatedVideoMemory > 0)
        {
            S.VRAMMB = static_cast<int32>(Stats.DedicatedVideoMemory / (1024 * 1024));
        }
    }

    S.CPUBrand = FPlatformMisc::GetCPUBrand().TrimStartAndEnd();
    S.CPUCores = FPlatformMisc::NumberOfCores();
    S.CPUThreads = FPlatformMisc::NumberOfCoresIncludingHyperthreads();
    S.RAMGB = static_cast<int32>(FPlatformMemory::GetConstants().TotalPhysicalGB);

    if (GEngine && GEngine->GetGameUserSettings())
    {
        S.DisplayResolution = GEngine->GetGameUserSettings()->GetDesktopResolution();
    }

#if PLATFORM_WINDOWS
    DEVMODEW Mode;
    FMemory::Memzero(Mode);
    Mode.dmSize = sizeof(Mode);
    if (::EnumDisplaySettingsW(nullptr, ENUM_CURRENT_SETTINGS, &Mode) && Mode.dmDisplayFrequency > 1)
    {
        S.RefreshHz = static_cast<int32>(Mode.dmDisplayFrequency);
    }
    DWORD MHz = 0;
    DWORD Size = sizeof(MHz);
    if (::RegGetValueW(HKEY_LOCAL_MACHINE, L"HARDWARE\\DESCRIPTION\\System\\CentralProcessor\\0", L"~MHz",
            RRF_RT_REG_DWORD, nullptr, &MHz, &Size) == ERROR_SUCCESS)
    {
        S.CPUClockMHz = static_cast<int32>(MHz);
    }
#endif

    if (S.RefreshHz <= 0 && GDynamicRHI)
    {
        // Fallback: the highest refresh the adapter offers at the desktop resolution.
        FScreenResolutionArray Modes;
        if (RHIGetAvailableResolutions(Modes, false))
        {
            for (const FScreenResolutionRHI& M : Modes)
            {
                if (static_cast<int32>(M.Width) == S.DisplayResolution.X && static_cast<int32>(M.Height) == S.DisplayResolution.Y)
                {
                    S.RefreshHz = FMath::Max(S.RefreshHz, static_cast<int32>(M.RefreshRate));
                }
            }
        }
    }
    return S;
}

ESaskartaGPUClass USaskartaHardwareProfileLibrary::ClassifyGPU(const FString& GPUName, int32 VendorId, bool bIntegrated)
{
    using namespace SaskartaHardwareProfileLocal;
    // "Intel(R) Arc(TM) A770 Graphics" -> "intel arc a770 graphics".
    FString L = GPUName.ToLower();
    for (const TCHAR* Mark : { TEXT("(tm)"), TEXT("(r)"), TEXT("™"), TEXT("®") })
    {
        L.ReplaceInline(Mark, TEXT(""), ESearchCase::CaseSensitive);
    }
    if (bIntegrated)
    {
        return ESaskartaGPUClass::Integrated;
    }
    if (L.IsEmpty())
    {
        return ESaskartaGPUClass::Unknown;
    }
    if (L.Contains(TEXT("basic render")) || L.Contains(TEXT("llvmpipe")) || L.Contains(TEXT("swiftshader")))
    {
        return ESaskartaGPUClass::Integrated;
    }

    const bool bLaptopName = L.Contains(TEXT("laptop")) || L.Contains(TEXT("mobile")) || L.Contains(TEXT("max-q"));
    bool bMobileSuffix = false;
    ESaskartaGPUClass C = ESaskartaGPUClass::Unknown;
    if (VendorId == 0x10DE || L.Contains(TEXT("nvidia")) || L.Contains(TEXT("geforce")))
    {
        C = ClassifyNvidia(L);
    }
    else if (VendorId == 0x1002 || L.Contains(TEXT("radeon")) || L.Contains(TEXT("amd")))
    {
        C = ClassifyAmd(L, bMobileSuffix);
    }
    else if (VendorId == 0x8086 || L.Contains(TEXT("intel")))
    {
        C = ClassifyIntel(L);
    }

    // A laptop part is roughly one class below its desktop namesake.
    if ((bLaptopName || bMobileSuffix) && C >= ESaskartaGPUClass::Mainstream)
    {
        C = static_cast<ESaskartaGPUClass>(static_cast<uint8>(C) - 1);
    }
    return C;
}

float USaskartaHardwareProfileLibrary::ExpectedScore(ESaskartaGPUClass Class)
{
    // PROVISIONAL: the synth benchmark GPU index expected of the weakest card in each class.
    switch (Class)
    {
    case ESaskartaGPUClass::Mainstream: return 350.f;
    case ESaskartaGPUClass::Performance: return 700.f;
    case ESaskartaGPUClass::Enthusiast: return 1400.f;
    default: return 0.f;
    }
}

int32 USaskartaHardwareProfileLibrary::TextureCapForVRAM(int32 VRAMMB)
{
    if (VRAMMB <= 0) { return 3; }
    if (VRAMMB < 4096) { return 0; }
    if (VRAMMB < 6144) { return 1; }
    if (VRAMMB < 8192) { return 2; }
    if (VRAMMB >= 11264) { return 4; }
    return 3;
}

int32 USaskartaHardwareProfileLibrary::VRAMHeadroomMB(int32 VRAMMB)
{
    if (VRAMMB <= 0) { return VRAMHeadroomFloorMB; }
    return FMath::Max(VRAMHeadroomFloorMB, FMath::RoundToInt(VRAMMB * VRAMHeadroomShare));
}

int32 USaskartaHardwareProfileLibrary::RAMHeadroomMB(int32 RAMGB)
{
    if (RAMGB <= 0) { return RAMHeadroomFloorMB; }
    return FMath::Max(RAMHeadroomFloorMB, FMath::RoundToInt(RAMGB * 1024.f * RAMHeadroomShare));
}

int32 USaskartaHardwareProfileLibrary::StreamingPoolForVRAM(int32 VRAMMB, int32 RAMGB)
{
    // Hardware detection can raise the conservative startup pool for larger GPUs. Smaller
    // cards get a pool that leaves room for Nanite, VSM, Lumen and the render targets.
    if (VRAMMB <= 0) { return -1; }
    int32 Pool;
    if (VRAMMB < 3072) { Pool = 600; }
    else if (VRAMMB < 4096) { Pool = 1000; }
    else if (VRAMMB < 6144) { Pool = 1400; }
    else if (VRAMMB < 8192) { Pool = 2000; }
    else if (VRAMMB < 10240) { Pool = 2560; }
    else { Pool = 3072; }

    // task HEADROOM: never let the pool alone claim the VRAM this tier must leave free.
    const int32 VRAMBudgetMB = FMath::Max(0, VRAMMB - VRAMHeadroomMB(VRAMMB));
    Pool = FMath::Min(Pool, VRAMBudgetMB);

    // task HEADROOM: streamed textures are RAM-resident before upload; also respect the system
    // RAM reserve once RAM is known (unknown RAMGB <= 0 leaves this side alone, matching every
    // call site from before task HEADROOM, which passed no RAMGB at all).
    if (RAMGB > 0)
    {
        const int32 RAMBudgetMB = FMath::Max(0, RAMGB * 1024 - RAMHeadroomMB(RAMGB));
        Pool = FMath::Min(Pool, RAMBudgetMB);
    }

    return FMath::Max(Pool, StreamingPoolFloorMB);
}

FString USaskartaHardwareProfileLibrary::LevelName(int32 Level)
{
    static const TCHAR* Names[] = { TEXT("Low"), TEXT("Medium"), TEXT("High"), TEXT("Epic"), TEXT("Cinematic") };
    return Level >= 0 && Level < UE_ARRAY_COUNT(Names) ? FString(Names[Level]) : FString(TEXT("Custom"));
}

FText USaskartaHardwareProfileLibrary::MakeSummary(const FSaskartaHardwareSpecs& Specs, int32 RecommendedLevel)
{
    const FString Gpu = Specs.GPUName.IsEmpty() ? FString(TEXT("unknown GPU")) : Specs.GPUName;
    return FText::Format(LOCTEXT("DetectedSummary", "Detected: {0}, {1}, recommended: {2}"),
        FText::FromString(Gpu),
        FText::FromString(SaskartaHardwareProfileLocal::VRAMText(Specs.VRAMMB)),
        FText::FromString(LevelName(RecommendedLevel)));
}

float USaskartaHardwareProfileLibrary::ScreenPercentageFor(int32 UpscalerMethod, int32 UpscalerMode)
{
    // Must match USaskartaGameUserSettings::ComputeCVars.
    static const float Pct[3] = { 66.7f, 58.f, 50.f };
    return UpscalerMethod == 2 ? 100.f : Pct[FMath::Clamp(UpscalerMode, 0, 2)];
}

FSaskartaDetectedProfile USaskartaHardwareProfileLibrary::Recommend(const FSaskartaHardwareSpecs& S)
{
    using namespace SaskartaHardwareProfileLocal;
    FSaskartaDetectedProfile P;
    P.Specs = S;
    P.GPUClass = ClassifyGPU(S.GPUName, S.VendorId, S.bIntegrated);
    TArray<FString> Why;

    // 1. The GPU class decides the preset; the benchmark only nudges it.
    int32 Level = 1;
    switch (P.GPUClass)
    {
    case ESaskartaGPUClass::Integrated:
        Level = 0;
        Why.Add(TEXT("integrated GPU: Low"));
        break;
    case ESaskartaGPUClass::Entry:
        Level = 0;
        if (S.GPUScore >= EntryMediumScore && S.VRAMMB >= 6144)
        {
            Level = 1;
            Why.Add(FString::Printf(TEXT("entry GPU with score %.0f and %d MB: Medium"), S.GPUScore, S.VRAMMB));
        }
        else
        {
            Why.Add(TEXT("entry GPU: Low"));
        }
        break;
    case ESaskartaGPUClass::Mainstream:
        Level = 1;
        break;
    case ESaskartaGPUClass::Performance:
        Level = 2;
        break;
    case ESaskartaGPUClass::Enthusiast:
        Level = 3;
        break;
    default:
        if (S.GPUScore < 0.f)
        {
            Level = 1;
            Why.Add(TEXT("unknown GPU, no benchmark: Medium"));
        }
        else
        {
            Level = S.GPUScore < UnknownMediumScore ? 0 : S.GPUScore < UnknownHighScore ? 1 : 2;
            Why.Add(FString::Printf(TEXT("unknown GPU, score %.0f: %s (unknown GPUs are capped at High)"), S.GPUScore, *LevelName(Level)));
        }
        break;
    }
    if (P.GPUClass >= ESaskartaGPUClass::Mainstream && S.GPUScore >= 0.f
        && S.GPUScore < ExpectedScore(P.GPUClass) * ClassGuardShare)
    {
        --Level;
        Why.Add(FString::Printf(TEXT("GPU score %.0f far below its class (%.0f): one level down"), S.GPUScore, ExpectedScore(P.GPUClass)));
    }
    Level = FMath::Clamp(Level, 0, 3);
    // Automatic Cinematic needs both throughput and memory headroom. The 11 GB
    // threshold tolerates driver-reserved memory on a nominal 12 GB card.
    if (Level == 3 && P.GPUClass == ESaskartaGPUClass::Enthusiast
        && S.VRAMMB >= 11264 && S.RAMGB >= 24 && S.CPUCores >= 6
        && S.CPUScore >= 100.f && S.GPUScore >= 1400.f)
    {
        Level = 4;
        Why.Add(TEXT("strong benchmark, CPU and memory headroom: Cinematic"));
    }
    if (S.VRAMMB > 0 && S.VRAMMB <= 4096)
    {
        Cap(Level, 1, TEXT("Preset"), TEXT("4 GB or less VRAM"), Why);
    }
    P.RecommendedLevel = Level;

    // 2. Per-group levels, then the machine's caps.
    P.ViewDistanceQuality = P.ShadowQuality = P.GlobalIlluminationQuality = P.ReflectionQuality = Level;
    P.PostProcessQuality = P.TextureQuality = P.EffectsQuality = P.FoliageQuality = P.ShadingQuality = Level;
    P.AntiAliasingQuality = FMath::Max(Level, 1); // TSR at low screen percentages needs its history features

    const int32 TexCap = TextureCapForVRAM(S.VRAMMB);
    Cap(P.TextureQuality, TexCap, TEXT("Textures"), FString::Printf(TEXT("%d MB VRAM"), S.VRAMMB), Why);
    if (S.VRAMMB > 0 && S.VRAMMB <= 4096)
    {
        const FString V = FString::Printf(TEXT("%d MB VRAM"), S.VRAMMB);
        Cap(P.ShadowQuality, 1, TEXT("Shadows"), V, Why);
        Cap(P.GlobalIlluminationQuality, 1, TEXT("Global illumination"), V, Why);
    }
    if (S.RAMGB > 0)
    {
        const int32 RamCap = S.RAMGB < 8 ? 0 : S.RAMGB < 12 ? 1 : S.RAMGB < 16 ? 2 : S.RAMGB < 24 ? 3 : 4;
        const FString R = FString::Printf(TEXT("%d GB RAM"), S.RAMGB);
        Cap(P.ViewDistanceQuality, RamCap, TEXT("View distance"), R, Why);
        Cap(P.FoliageQuality, RamCap, TEXT("Foliage"), R, Why);
        Cap(P.TextureQuality, RamCap, TEXT("Textures"), R, Why);
    }
    const bool bWeakCpu = (S.CPUCores > 0 && S.CPUCores < 4) || (S.CPUScore >= 0.f && S.CPUScore < 60.f);
    if (bWeakCpu)
    {
        const FString C = FString::Printf(TEXT("%d cores, CPU score %.0f"), S.CPUCores, S.CPUScore);
        Cap(P.ViewDistanceQuality, 1, TEXT("View distance"), C, Why);
        Cap(P.FoliageQuality, 1, TEXT("Foliage"), C, Why);
        Cap(P.EffectsQuality, 1, TEXT("Effects"), C, Why);
        Cap(P.ShadowQuality, 1, TEXT("Shadows"), C, Why);
    }
    else if (S.CPUCores > 0 && S.CPUCores < 6)
    {
        const FString C = FString::Printf(TEXT("%d cores"), S.CPUCores);
        Cap(P.ViewDistanceQuality, 2, TEXT("View distance"), C, Why);
        Cap(P.FoliageQuality, 2, TEXT("Foliage"), C, Why);
    }

    // 3. Upscaler: TSR, screen percentage by preset and output size.
    const int64 Pixels = S.DisplayResolution.X > 0 && S.DisplayResolution.Y > 0
        ? int64(S.DisplayResolution.X) * S.DisplayResolution.Y : int64(1920) * 1080;
    const int32 PClass = Pixels >= int64(3840 * 2160 * 9 / 10) ? 2 : Pixels >= int64(2560 * 1440 * 9 / 10) ? 1 : 0;
    // [Level][<=1080p, 1440p, 4K]: 0 Quality 66.7 %, 1 Balanced 58 %, 2 Performance 50 %.
    static const int32 ModeTable[5][3] = { { 1, 2, 2 }, { 0, 1, 2 }, { 0, 0, 1 }, { 0, 0, 1 }, { 0, 0, 1 } };
    P.UpscalerMode = P.GPUClass == ESaskartaGPUClass::Integrated ? 2 : ModeTable[Level][PClass];
    P.UpscalerMethod = (Level >= 3 && PClass == 0) ? 2 : 0; // Epic/Cinematic at 1080p render native
    P.ScreenPercentage = ScreenPercentageFor(P.UpscalerMethod, P.UpscalerMode);

    // 4. Frame cap and VSync.
    const int32 Refresh = S.RefreshHz > 0 ? S.RefreshHz : 60;
    // Never above 60 fps on any tier: the GPU keeps headroom for a recorder or a stream.
    P.FrameRateLimit = static_cast<float>(FMath::Min(Refresh, USaskartaGameUserSettings::MaxFrameRate));
    P.bVSync = S.RefreshHz > 0 && S.RefreshHz <= 75;

    P.Reasons = FString::Join(Why, TEXT("; "));
    P.Summary = MakeSummary(S, Level);
    P.bValid = true;
    return P;
}

#undef LOCTEXT_NAMESPACE
