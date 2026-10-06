// Loading budget (task LOADBUDGET). See SaskartaLoadingBudget.h for the rules and
// Tools/GameFlow/specs/README_LoadingBudget.md for the CVar table.

#include "SaskartaLoadingBudget.h"

#include "CoreGlobals.h"
#include "Blueprint/UserWidget.h"
#include "DynamicRHI.h"
#include "Engine/Engine.h"
#include "Engine/GameInstance.h"
#include "Engine/GameViewportClient.h"
#include "Engine/World.h"
#include "HAL/IConsoleManager.h"
#include "HAL/PlatformTime.h"
#include "Misc/CoreDelegates.h"
#include "RenderTimer.h"
#include "ShaderPipelineCache.h"
#include "SaskartaReadiness.h"
#include "TimerManager.h"

DEFINE_LOG_CATEGORY_STATIC(LogSaskartaLoadBudget, Log, All);

static TAutoConsoleVariable<int32> CVarLoadBudgetEnable(
    TEXT("saskarta.loadbudget.Enable"), 1,
    TEXT("Saskarta: 1 applies the loading budget (time-sliced streaming, 30 fps cap) while the loading screen is up."),
    ECVF_Default);

static TAutoConsoleVariable<int32> CVarLoadBudgetLog(
    TEXT("saskarta.loadbudget.Log"), 1,
    TEXT("Saskarta: 1 logs one line per second during loading (frame ms, max frame, game/render/GPU ms, readiness)."),
    ECVF_Default);

static TAutoConsoleVariable<float> CVarLoadBudgetMaxFPS(
    TEXT("saskarta.loadbudget.MaxFPS"), 30.f,
    TEXT("Saskarta: frame cap during loading (t.MaxFPS, never raised above the user's cap). 0 leaves t.MaxFPS alone."),
    ECVF_Default);

static TAutoConsoleVariable<float> CVarLoadBudgetScreenPct(
    TEXT("saskarta.loadbudget.ScreenPercentage"), 0.f,
    TEXT("Saskarta: r.ScreenPercentage cap behind the opaque loading screen (texture streaming uses the unscaled view,\n")
    TEXT("so it is safe for mips). 0 (default) leaves it alone: restoring it resets TSR history and VSM pages at the reveal."),
    ECVF_Default);

static TAutoConsoleVariable<int32> CVarLoadBudgetGCAtEnd(
    TEXT("saskarta.loadbudget.GCAtEnd"), 1,
    TEXT("Saskarta: GC when the loading budget ends. 0 none (the normal interval GC runs soon after),\n")
    TEXT("1 (default) one normal GC with incremental purge, 2 one full GC with a blocking purge (the old behaviour;\n")
    TEXT("in PIE it also walks every editor object)."),
    ECVF_Default);

// ============================================================================================
// FSaskartaLoadBudgetCore: pure
// ============================================================================================

FString FSaskartaLoadBudgetCore::FormatValue(float Value)
{
    if (FMath::IsNearlyEqual(Value, FMath::RoundToFloat(Value), 1.0e-4f))
    {
        return FString::Printf(TEXT("%d"), FMath::RoundToInt(Value));
    }
    return FString::SanitizeFloat(Value);
}

bool FSaskartaLoadBudgetCore::ValuesEqual(const FString& A, const FString& B)
{
    if (A == B)
    {
        return true;
    }
    if (A.IsNumeric() && B.IsNumeric())
    {
        return FMath::IsNearlyEqual(FCString::Atod(*A), FCString::Atod(*B), 1.0e-3);
    }
    return false;
}

float FSaskartaLoadBudgetCore::Resolve(EOp Op, float Current, float Value)
{
    switch (Op)
    {
    case EOp::Cap:
        // <= 0 means unlimited on both sides.
        if (Value <= 0.f)
        {
            return Current;
        }
        return Current <= 0.f ? Value : FMath::Min(Current, Value);
    case EOp::AtLeast:
        return FMath::Max(Current, Value);
    default:
        return Value;
    }
}

bool FSaskartaLoadBudgetCore::Begin(FName Owner, const TArray<FSetting>& Settings, ISaskartaCVarAccess& CVars)
{
    if (Owners.Contains(Owner))
    {
        return false;
    }
    const bool bFirst = Owners.Num() == 0;
    Owners.Add(Owner);
    if (!bFirst)
    {
        return false;
    }
    Saved.Reset();
    KeptOnRestore.Reset();
    for (const FSetting& S : Settings)
    {
        FString Current;
        if (!CVars.Read(S.Name, Current))
        {
            continue; // not in this build
        }
        if (Saved.ContainsByPredicate([&S](const FSaved& X) { return X.Name == S.Name; }))
        {
            continue; // first setting for a name wins
        }
        const float Cur = Current.IsNumeric() ? static_cast<float>(FCString::Atod(*Current)) : 0.f;
        const FString Applied = FormatValue(Resolve(S.Op, Cur, S.Value));
        if (ValuesEqual(Applied, Current))
        {
            continue; // already within budget: nothing to restore either
        }
        FSaved Entry;
        Entry.Name = S.Name;
        Entry.Original = Current;
        CVars.Write(S.Name, Applied);
        // Keep what the CVar reports back (its own formatting), for the restore compare.
        FString After;
        Entry.Applied = CVars.Read(S.Name, After) ? After : Applied;
        Saved.Add(Entry);
    }
    return true;
}

void FSaskartaLoadBudgetCore::Restore(ISaskartaCVarAccess& CVars)
{
    KeptOnRestore.Reset();
    // Reverse order, in case two settings interact.
    for (int32 I = Saved.Num() - 1; I >= 0; --I)
    {
        const FSaved& S = Saved[I];
        FString Now;
        if (!CVars.Read(S.Name, Now))
        {
            continue;
        }
        if (ValuesEqual(Now, S.Applied))
        {
            CVars.Write(S.Name, S.Original);
        }
        else
        {
            KeptOnRestore.Add(S.Name); // changed by someone else during loading: keep theirs
        }
    }
    Saved.Reset();
}

bool FSaskartaLoadBudgetCore::End(FName Owner, ISaskartaCVarAccess& CVars)
{
    if (Owners.Remove(Owner) == 0)
    {
        return false;
    }
    if (Owners.Num() > 0)
    {
        return false;
    }
    Restore(CVars);
    return true;
}

bool FSaskartaLoadBudgetCore::ForceRestore(ISaskartaCVarAccess& CVars)
{
    const bool bWasActive = Owners.Num() > 0;
    Owners.Reset();
    Restore(CVars);
    return bWasActive;
}

// ============================================================================================
// FSaskartaFrameWindow
// ============================================================================================

void FSaskartaFrameWindow::AddFrame(float FrameMs)
{
    SumMs += FrameMs;
    MaxFrameMs = FMath::Max(MaxFrameMs, FrameMs);
    ++Frames;
    if (FrameMs > HitchMs)
    {
        ++Hitches;
    }
}

void FSaskartaFrameWindow::Reset()
{
    SumMs = 0.0;
    MaxFrameMs = 0.f;
    Frames = 0;
    Hitches = 0;
}

// ============================================================================================
// USaskartaLoadingBudget: the engine side
// ============================================================================================

namespace SaskartaLoadBudgetLocal
{
    class FConsoleCVarAccess final : public ISaskartaCVarAccess
    {
    public:
        // Keep the CVar's own SetBy priority, so the settings class and scalability can still write it
        // afterwards; but never below SetByScalability. SetWithCurrentPriority refuses a CVar that
        // still has its constructor priority ("Trying to Replace Cvar=... Set By Constructor", 7 of the
        // budget's CVars) and falls back to the reserved SETBY_ERROR priority, so the write and the
        // restore both go through an explicit Set at the lowest legitimate priority instead.
        static EConsoleVariableFlags WritePriority(EConsoleVariableFlags Flags)
        {
            const uint32 Current = static_cast<uint32>(Flags) & static_cast<uint32>(ECVF_SetByMask);
            return static_cast<EConsoleVariableFlags>(FMath::Max(Current, static_cast<uint32>(ECVF_SetByScalability)));
        }

        virtual bool Read(const FString& Name, FString& OutValue) const override
        {
            const IConsoleVariable* V = IConsoleManager::Get().FindConsoleVariable(*Name);
            if (!V)
            {
                return false;
            }
            OutValue = V->GetString();
            return true;
        }

        virtual void Write(const FString& Name, const FString& Value) override
        {
            if (IConsoleVariable* V = IConsoleManager::Get().FindConsoleVariable(*Name))
            {
                V->Set(*Value, WritePriority(V->GetFlags()));
            }
        }
    };
}

TArray<FSaskartaLoadBudgetCore::FSetting> USaskartaLoadingBudget::BuildSettings()
{
    using EOp = FSaskartaLoadBudgetCore::EOp;
    TArray<FSaskartaLoadBudgetCore::FSetting> S;
    auto Add = [&S](const TCHAR* Name, float Value, EOp Op) { S.Add({ Name, Value, Op }); };

    // Frame cadence: steady 33 ms slices; the per-frame budgets below fit inside one.
    Add(TEXT("t.MaxFPS"), CVarLoadBudgetMaxFPS.GetValueOnGameThread(), EOp::Cap);

    // Async loading on the game thread (CoreSettings.cpp): the 5 ms slice stays (at 30 fps it already
    // runs half as often); the unsliced extras go: no +15 ms for priority loads, no full slice
    // while blocked on I/O.
    Add(TEXT("s.AsyncLoadingTimeLimit"), 5.f, EOp::Cap);
    Add(TEXT("s.AsyncLoadingUseFullTimeLimit"), 0.f, EOp::Set);
    Add(TEXT("s.PriorityAsyncLoadingExtraTime"), 0.f, EOp::Set);

    // Level streaming AddToWorld (World.cpp): 5 ms -> 4 ms, no +5 ms priority extra, smaller batches
    // so the time limit is checked more often (one batch can overrun it).
    Add(TEXT("s.LevelStreamingActorsUpdateTimeLimit"), 4.f, EOp::Cap);
    Add(TEXT("s.PriorityLevelStreamingActorsUpdateExtraTime"), 0.f, EOp::Set);
    Add(TEXT("s.LevelStreamingComponentsRegistrationGranularity"), 4.f, EOp::Cap);
    Add(TEXT("s.LevelStreamingAddPrimitiveGranularity"), 40.f, EOp::Cap);
    Add(TEXT("s.LevelStreamingComponentsUnregistrationGranularity"), 2.f, EOp::Cap);
    Add(TEXT("s.LevelStreamingRouteActorInitializationGranularity"), 4.f, EOp::Cap);

    // World Partition: fewer cells loading at once (their heavy instance components land in
    // different frames), and never block the game thread to catch up while the screen hides it.
    Add(TEXT("wp.Runtime.MaxLoadingStreamingCells"), 2.f, EOp::Cap);
    Add(TEXT("wp.Runtime.BlockOnSlowStreaming"), 0.f, EOp::Set);

    // PCG runtime generation: fewer components generating at once (pcg.FrameTime is already 3 ms).
    Add(TEXT("pcg.RuntimeGeneration.NumGeneratingComponents"), 2.f, EOp::Cap);

    // Landscape grass: no 4x burst when grass creation is prioritized (camera cut to the title view).
    Add(TEXT("grass.GrassCreationPrioritizedMultipler"), 1.f, EOp::Cap);
    Add(TEXT("grass.MaxCreatePerFrame"), 1.f, EOp::Cap);

    // Bundled/file PSO cache: cover both UE 5.8 paths. With PSO precaching enabled, the
    // cache reads the thread-pool settings instead of the legacy Fast batch settings
    // (ShaderPipelineCache.cpp, SetBatchMode). These do not bound uncached draw-time PSOs.
    auto AddEnabledPSOCap = [&Add](const TCHAR* Name, float Ceiling)
    {
        const IConsoleVariable* Variable = IConsoleManager::Get().FindConsoleVariable(Name);
        // Unlike t.MaxFPS, a zero PSO batch/time setting can deliberately disable
        // compilation. Do not turn that into enabled work via the generic Cap op.
        if (Variable && Variable->GetFloat() > 0.f)
        {
            Add(Name, Ceiling, EOp::Cap);
        }
    };
    AddEnabledPSOCap(TEXT("r.ShaderPipelineCache.BatchTime"), 8.f);
    AddEnabledPSOCap(TEXT("r.ShaderPipelineCache.BatchSize"), 25.f);
    AddEnabledPSOCap(TEXT("r.ShaderPipelineCache.PSOPrecacheThreadPoolBatchTime"), 8.f);
    AddEnabledPSOCap(TEXT("r.ShaderPipelineCache.PSOPrecacheThreadPoolBatchSize"), 25.f);

    // GC: none during loading (one forced at the end instead); no forced GC per streamed-out level.
    Add(TEXT("gc.TimeBetweenPurgingPendingKillObjects"), 600.f, EOp::AtLeast);
    Add(TEXT("s.ForceGCAfterLevelStreamedOut"), 0.f, EOp::Set);

    // Optional GPU cheapening behind the opaque screen (off by default, see the CVar help).
    const float Pct = CVarLoadBudgetScreenPct.GetValueOnGameThread();
    if (Pct > 0.f)
    {
        Add(TEXT("r.ScreenPercentage"), FMath::Clamp(Pct, 25.f, 100.f), EOp::Cap);
    }
    return S;
}

USaskartaLoadingBudget* USaskartaLoadingBudget::GetLoadingBudget(const UObject* WorldContext)
{
    const UWorld* World = GEngine ? GEngine->GetWorldFromContextObject(WorldContext, EGetWorldErrorMode::ReturnNull) : nullptr;
    const UGameInstance* GI = World ? World->GetGameInstance() : nullptr;
    return GI ? GI->GetSubsystem<USaskartaLoadingBudget>() : nullptr;
}

void USaskartaLoadingBudget::Initialize(FSubsystemCollectionBase& Collection)
{
    Super::Initialize(Collection);
    CleanupHandle = FWorldDelegates::OnWorldCleanup.AddUObject(this, &USaskartaLoadingBudget::OnWorldCleanup);
}

void USaskartaLoadingBudget::Deinitialize()
{
    FWorldDelegates::OnWorldCleanup.Remove(CleanupHandle);
    RestoreAll(TEXT("game instance shutdown"));
    Super::Deinitialize();
}

void USaskartaLoadingBudget::OnWorldCleanup(UWorld* World, bool bSessionEnded, bool bCleanupResources)
{
    if (World && World->IsGameWorld() && World->GetGameInstance() == GetGameInstance())
    {
        RestoreForWorldTeardown();
    }
}

void USaskartaLoadingBudget::RestoreForWorldTeardown()
{
    RestoreAll(TEXT("world teardown"));
}

void USaskartaLoadingBudget::BeginLoadingBudget(FName Owner)
{
    if (!CVarLoadBudgetEnable.GetValueOnGameThread())
    {
        return;
    }
    SaskartaLoadBudgetLocal::FConsoleCVarAccess CVars;
    if (!Core.Begin(Owner, BuildSettings(), CVars))
    {
        UE_LOG(LogSaskartaLoadBudget, Verbose, TEXT("Loading budget: owner %s added (%d owners)."), *Owner.ToString(), Core.NumOwners());
        return;
    }

    TArray<FString> Changed;
    for (const FSaskartaLoadBudgetCore::FSaved& S : Core.GetSaved())
    {
        Changed.Add(FString::Printf(TEXT("%s %s->%s"), *S.Name, *S.Original, *S.Applied));
    }
    UE_LOG(LogSaskartaLoadBudget, Log, TEXT("Loading budget ON (%s): %s"), *Owner.ToString(), *FString::Join(Changed, TEXT(", ")));

    // Batch settings are sampled, not live-read each tick. Refresh an active file
    // cache after applying the caps; SetBatchMode preserves its paused state and
    // does not create a cache, add workers, or enable PSO precaching.
    // Refresh even before the first cache task starts: an existing cache instance
    // may begin precompiling later during this loading window. The API is a no-op
    // when no instance exists.
    FShaderPipelineCache::SetBatchMode(FShaderPipelineCache::BatchMode::Fast);
    bRefreshedPipelineCache = true;

    BeganS = FPlatformTime::Seconds();
    LastFrameS = BeganS;
    Window.Reset();
    if (!EndFrameHandle.IsValid())
    {
        EndFrameHandle = FCoreDelegates::OnEndFrame.AddUObject(this, &USaskartaLoadingBudget::OnEndFrame);
    }
    if (UGameInstance* GI = GetGameInstance())
    {
        GI->GetTimerManager().SetTimer(LogTimer, this, &USaskartaLoadingBudget::OnLogTimer, 1.0f, true);
    }
}

void USaskartaLoadingBudget::EndLoadingBudget(FName Owner)
{
    // Startup presentation ends with its named owner, even if another budget owner
    // remains, or the optional CVar budget was disabled. Restore before Title can draw.
    if (Owner == FName(TEXT("Loading")))
    {
        RestoreStartupWorldRendering(TEXT("startup loading ended"));
    }
    SaskartaLoadBudgetLocal::FConsoleCVarAccess CVars;
    const int32 NumSaved = Core.GetSaved().Num();
    if (!Core.End(Owner, CVars))
    {
        return;
    }
    RefreshPipelineCacheAfterLoading();
    if (UGameInstance* GI = GetGameInstance())
    {
        GI->GetTimerManager().ClearTimer(LogTimer);
    }
    FCoreDelegates::OnEndFrame.Remove(EndFrameHandle);
    EndFrameHandle.Reset();

    UE_LOG(LogSaskartaLoadBudget, Log, TEXT("Loading budget OFF (%s) after %.1f s: %d CVar(s) restored%s%s."),
        *Owner.ToString(), FPlatformTime::Seconds() - BeganS, NumSaved - Core.GetKeptOnRestore().Num(),
        Core.GetKeptOnRestore().Num() ? TEXT(", kept (changed meanwhile): ") : TEXT(""),
        *FString::Join(Core.GetKeptOnRestore(), TEXT(", ")));

    // The GC held back during loading runs now, while the loading screen is still on screen.
    const int32 GCAtEnd = CVarLoadBudgetGCAtEnd.GetValueOnGameThread();
    if (GEngine && GCAtEnd > 0)
    {
        GEngine->ForceGarbageCollection(GCAtEnd >= 2);
    }
}

void USaskartaLoadingBudget::RestoreAll(const TCHAR* Why)
{
    RestoreStartupWorldRendering(Why);
    if (UGameInstance* GI = GetGameInstance())
    {
        GI->GetTimerManager().ClearTimer(LogTimer);
    }
    FCoreDelegates::OnEndFrame.Remove(EndFrameHandle);
    EndFrameHandle.Reset();
    SaskartaLoadBudgetLocal::FConsoleCVarAccess CVars;
    if (Core.ForceRestore(CVars))
    {
        UE_LOG(LogSaskartaLoadBudget, Log, TEXT("Loading budget restored on %s."), Why);
    }
    RefreshPipelineCacheAfterLoading();
}

void USaskartaLoadingBudget::SetStartupLoadingScreenVisible(UUserWidget* LoadingScreen, bool bVisible)
{
    if (!bVisible)
    {
        RestoreStartupWorldRendering(TEXT("startup screen hidden"));
        return;
    }

    UWorld* World = GetWorld();
    UGameInstance* GI = GetGameInstance();
    UGameViewportClient* Viewport = GI ? GI->GetGameViewportClient() : nullptr;
    if (!World || !World->IsGameWorld() || World->bIsTearingDown || World->IsBeingCleanedUp()
        || World->GetNetMode() == NM_DedicatedServer || !Viewport || Viewport->GetGameInstance() != GI
        || !IsValid(LoadingScreen) || LoadingScreen->GetWorld() != World || !LoadingScreen->IsInViewport()
        || !LoadingScreen->IsVisible() || LoadingScreen->GetRenderOpacity() <= 0.f)
    {
        RestoreStartupWorldRendering(TEXT("startup screen unavailable"));
        return;
    }

    if (bHoldingStartupWorldRendering && StartupViewport.Get() == Viewport && StartupLoadingScreen.Get() == LoadingScreen)
    {
        OnStartupViewportBeginDraw();
        return;
    }
    RestoreStartupWorldRendering(TEXT("startup screen replaced"));
    StartupViewport = Viewport;
    StartupLoadingScreen = LoadingScreen;
    bSavedDisableWorldRendering = Viewport->bDisableWorldRendering;
    bHoldingStartupWorldRendering = true;
    // GameViewportClient still calculates player views and AddStreamingViewInfo,
    // clears the backbuffer, and draws UI; only BeginRenderingViewFamily is skipped.
    // The loading widget supplies its opaque black background.
    Viewport->bDisableWorldRendering = true;
    StartupBeginDrawHandle = Viewport->OnBeginDraw().AddUObject(this, &USaskartaLoadingBudget::OnStartupViewportBeginDraw);
    UE_LOG(LogSaskartaLoadBudget, Log, TEXT("Startup loading world rendering suspended; prior_disabled=%d."), bSavedDisableWorldRendering);
}

void USaskartaLoadingBudget::OnStartupViewportBeginDraw()
{
    UGameInstance* GI = GetGameInstance();
    UWorld* World = GetWorld();
    UGameViewportClient* Viewport = StartupViewport.Get();
    UUserWidget* Screen = StartupLoadingScreen.Get();
    if (!bHoldingStartupWorldRendering || !GI || !World || World->bIsTearingDown || World->IsBeingCleanedUp()
        || !Viewport || GI->GetGameViewportClient() != Viewport || Viewport->GetGameInstance() != GI
        || !Screen || Screen->GetWorld() != World || !Screen->IsInViewport() || !Screen->IsVisible()
        || Screen->GetRenderOpacity() <= 0.f)
    {
        RestoreStartupWorldRendering(TEXT("startup screen no longer visible"));
    }
    else if (!Viewport->bDisableWorldRendering)
    {
        // A newer writer explicitly enabled this viewport. Relinquish rather than
        // reasserting a hidden hold or restoring our old value over its selection.
        RestoreStartupWorldRendering(TEXT("viewport changed by another writer"));
    }
}

void USaskartaLoadingBudget::RestoreStartupWorldRendering(const TCHAR* Why)
{
    UGameViewportClient* Viewport = StartupViewport.Get();
    if (Viewport)
    {
        Viewport->OnBeginDraw().Remove(StartupBeginDrawHandle);
        if (bHoldingStartupWorldRendering && Viewport->GetGameInstance() == GetGameInstance() && Viewport->bDisableWorldRendering)
        {
            Viewport->bDisableWorldRendering = bSavedDisableWorldRendering;
        }
    }
    if (bHoldingStartupWorldRendering)
    {
        UE_LOG(LogSaskartaLoadBudget, Log, TEXT("Startup loading world rendering released on %s; viewport_disabled=%d."),
            Why, Viewport ? static_cast<int32>(Viewport->bDisableWorldRendering) : -1);
    }
    StartupBeginDrawHandle.Reset();
    StartupViewport.Reset();
    StartupLoadingScreen.Reset();
    bHoldingStartupWorldRendering = false;
    bSavedDisableWorldRendering = false;
}

void USaskartaLoadingBudget::RefreshPipelineCacheAfterLoading()
{
    if (bRefreshedPipelineCache)
    {
        // Return the cache to its documented interactive-menu mode after releasing
        // our temporary CVar caps. Do not resume a paused cache or force completion.
        FShaderPipelineCache::SetBatchMode(FShaderPipelineCache::BatchMode::Background);
        bRefreshedPipelineCache = false;
    }
}

void USaskartaLoadingBudget::OnEndFrame()
{
    const double Now = FPlatformTime::Seconds();
    Window.AddFrame(static_cast<float>((Now - LastFrameS) * 1000.0));
    LastFrameS = Now;
}

void USaskartaLoadingBudget::OnLogTimer()
{
    if (!Core.IsActive() || !CVarLoadBudgetLog.GetValueOnGameThread())
    {
        Window.Reset();
        return;
    }
    float Fraction = -1.f;
    FString Unmet;
    double AgeS = 0.0;
    const bool bPolled = USaskartaReadiness::GetLastPolled(Fraction, Unmet, AgeS);
    UE_LOG(LogSaskartaLoadBudget, Log,
        TEXT("Loading t=%5.1f s | frames %d, mean %.1f ms, max %.1f ms, >50 ms %d | game %.1f, render %.1f, GPU %.1f ms | readiness %s%s"),
        FPlatformTime::Seconds() - BeganS, Window.NumFrames(), Window.MeanMs(), Window.MaxMs(), Window.NumHitches(),
        FPlatformTime::ToMilliseconds(GGameThreadTime), FPlatformTime::ToMilliseconds(GRenderThreadTime),
        FPlatformTime::ToMilliseconds(RHIGetGPUFrameCycles(0)),
        bPolled ? *FString::Printf(TEXT("%.0f %%"), Fraction * 100.f) : TEXT("n/a"),
        bPolled && !Unmet.IsEmpty() ? *FString::Printf(TEXT(" (waiting: %s)"), *Unmet) : TEXT(""));
    Window.Reset();
}
