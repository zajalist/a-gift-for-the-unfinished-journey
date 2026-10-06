// USaskartaAmbienceDirector. See the header.

#include "SaskartaAmbienceDirector.h"
#include "SaskartaAmbienceAsset.h"
#include "SaskartaAmbienceImport.h"
#include "SaskartaAmbienceSettings.h"
#include "SaskartaEventRunner.h"
#include "SaskartaLightingDirector.h"
#include "SaskartaRadioStation.h"

#include "AssetRegistry/AssetRegistryModule.h"
#include "AudioDevice.h"
#include "Camera/PlayerCameraManager.h"
#include "Components/AudioComponent.h"
#include "Engine/AssetManager.h"
#include "Engine/Engine.h"
#include "Engine/StreamableManager.h"
#include "Engine/World.h"
#include "EngineUtils.h"
#include "GameFramework/Pawn.h"
#include "GameFramework/PlayerController.h"
#include "HAL/IConsoleManager.h"
#include "Modules/ModuleManager.h"
#include "Sound/AmbientSound.h"
#include "Sound/SoundAttenuation.h"
#include "Sound/SoundBase.h"
#include "Sound/SoundClass.h"
#include "Sound/SoundSubmix.h"

DEFINE_LOG_CATEGORY_STATIC(LogSaskartaAmbience, Log, All);

namespace SaskartaAmbience
{
    static const FName FlowPlaying(TEXT("Playing"));
    static const FName FlowCollapsing(TEXT("Collapsing"));
    static const FName FlowHuman(TEXT("Human"));
    static const FName FlowTitle(TEXT("Title"));
    static const FName CauseGust(TEXT("Gust"));
    static const FName CauseDustWall(TEXT("DustWall"));
    static const FName CauseLightning(TEXT("Lightning"));
    static const FName BedBreeze(TEXT("Wind_Breeze"));
    static const FName BedStrong(TEXT("Wind_Strong"));
    static const FName BedGale(TEXT("Wind_Gale"));

    static constexpr float PriorityWind = 100.f;
    static constexpr float PriorityGeiger = 95.f;
    static constexpr float PriorityGrit = 80.f;
    static constexpr float PriorityZoneBed = 70.f;
    static constexpr float PrioritySpot = 50.f;
    static constexpr float DuckStepS = 1.f / 30.f;
    static constexpr float DustWallIntensity = 0.8f;
    static constexpr float GustCapCps = 60.f;

    static FSoundAttenuationSettings MakeAttenuation(float InnerM, float FalloffM)
    {
        FSoundAttenuationSettings S;
        S.bAttenuate = true;
        S.bSpatialize = true;
        S.AttenuationShape = EAttenuationShape::Sphere;
        S.AttenuationShapeExtents = FVector(FMath::Max(InnerM, 0.5f) * 100.f, 0.f, 0.f);
        S.FalloffDistance = FMath::Max(FalloffM, 1.f) * 100.f;
        S.DistanceAlgorithm = EAttenuationDistanceModel::NaturalSound;
        // Air absorption.
        S.bAttenuateWithLPF = true;
        S.LPFRadiusMin = FMath::Max(InnerM, 0.5f) * 100.f;
        S.LPFRadiusMax = (FMath::Max(InnerM, 0.5f) + FMath::Max(FalloffM, 1.f)) * 100.f;
        // Non-spatialised inside the inner radius (the reeds' stereo bed).
        S.NonSpatializedRadiusStart = FMath::Max(InnerM, 0.5f) * 100.f;
        S.NonSpatializedRadiusEnd = FMath::Max(InnerM, 0.5f) * 50.f;
        return S;
    }
}

// ============================================================================ access

USaskartaAmbienceDirector* USaskartaAmbienceDirector::GetAmbienceDirector(const UObject* WorldContextObject)
{
    const UWorld* World = GEngine ? GEngine->GetWorldFromContextObject(WorldContextObject, EGetWorldErrorMode::ReturnNull) : nullptr;
    return World ? World->GetSubsystem<USaskartaAmbienceDirector>() : nullptr;
}

bool USaskartaAmbienceDirector::DoesSupportWorldType(const EWorldType::Type WorldType) const
{
    return WorldType == EWorldType::Game || WorldType == EWorldType::PIE;
}

double USaskartaAmbienceDirector::Now() const
{
    const UWorld* W = GetWorld();
    return W ? W->GetTimeSeconds() : 0.0;
}

APawn* USaskartaAmbienceDirector::GetCarrier() const
{
    const UWorld* W = GetWorld();
    const APlayerController* PC = W ? W->GetFirstPlayerController() : nullptr;
    return PC ? PC->GetPawn() : nullptr;
}

FName USaskartaAmbienceDirector::GetCurrentZone() const
{
    return (Asset && Asset->Zones.IsValidIndex(DominantZone)) ? Asset->Zones[DominantZone].Name : NAME_None;
}

int32 USaskartaAmbienceDirector::GetActiveVoiceCount() const
{
    int32 N = 0;
    for (const FVoice& V : Voices)
    {
        const UAudioComponent* C = V.Comp.Get();
        if (C && C->IsPlaying())
        {
            ++N;
        }
    }
    return N;
}

// ============================================================================ lifecycle

void USaskartaAmbienceDirector::Initialize(FSubsystemCollectionBase& Collection)
{
    Super::Initialize(Collection);
    Collection.InitializeDependency<USaskartaEventRunner>();
    Collection.InitializeDependency<USaskartaLightingDirector>();
    Random.Initialize(static_cast<int32>(FPlatformTime::Cycles()));
}

void USaskartaAmbienceDirector::OnWorldBeginPlay(UWorld& InWorld)
{
    Super::OnWorldBeginPlay(InWorld);
    BindSources();
    RequestAsset();
    InWorld.GetTimerManager().SetTimer(UpdateTimer, FTimerDelegate::CreateUObject(this, &USaskartaAmbienceDirector::Update),
        UpdateIntervalS, true, UpdateIntervalS);
}

void USaskartaAmbienceDirector::Deinitialize()
{
    if (UWorld* W = GetWorld())
    {
        FTimerManager& TM = W->GetTimerManager();
        TM.ClearTimer(UpdateTimer);
        TM.ClearTimer(GustTimer);
        TM.ClearTimer(ClickTimer);
        TM.ClearTimer(DuckTimer);
        TM.ClearAllTimersForObject(this);
    }
    UnbindSources();
    for (const TObjectPtr<UAudioComponent>& C : OwnedComps)
    {
        if (IsValid(C))
        {
            C->Stop();
        }
    }
    OwnedComps.Reset();
    Voices.Reset();
    Beds.Reset();
    for (TPair<int32, TSharedPtr<FStreamableHandle>>& KV : ZoneHandles)
    {
        if (KV.Value.IsValid())
        {
            KV.Value->ReleaseHandle();
        }
    }
    ZoneHandles.Reset();
    if (CoreHandle.IsValid())
    {
        CoreHandle->ReleaseHandle();
        CoreHandle.Reset();
    }
    if (AssetHandle.IsValid())
    {
        AssetHandle->ReleaseHandle();
        AssetHandle.Reset();
    }
    Super::Deinitialize();
}

void USaskartaAmbienceDirector::BindSources()
{
    if (bBound)
    {
        return;
    }
    UWorld* W = GetWorld();
    if (!W)
    {
        return;
    }
    if (USaskartaEventRunner* Runner = W->GetSubsystem<USaskartaEventRunner>())
    {
        Runner->OnStoryBusyChanged.AddUniqueDynamic(this, &USaskartaAmbienceDirector::HandleStoryBusy);
        Runner->OnBeatStarted.AddUniqueDynamic(this, &USaskartaAmbienceDirector::HandleBeatStarted);
    }
    if (USaskartaLightingDirector* LD = W->GetSubsystem<USaskartaLightingDirector>())
    {
        LD->OnLightningStrike.AddUniqueDynamic(this, &USaskartaAmbienceDirector::HandleLightning);
    }
    if (USaskartaRadioStation* Radio = W->GetSubsystem<USaskartaRadioStation>())
    {
        Radio->OnRadioForcedOn.AddUniqueDynamic(this, &USaskartaAmbienceDirector::HandleRadioForcedOn);
        Radio->OnRadioForcedOff.AddUniqueDynamic(this, &USaskartaAmbienceDirector::HandleRadioForcedOff);
    }
    bBound = true;
}

void USaskartaAmbienceDirector::UnbindSources()
{
    if (!bBound)
    {
        return;
    }
    if (UWorld* W = GetWorld())
    {
        if (USaskartaEventRunner* Runner = W->GetSubsystem<USaskartaEventRunner>())
        {
            Runner->OnStoryBusyChanged.RemoveDynamic(this, &USaskartaAmbienceDirector::HandleStoryBusy);
            Runner->OnBeatStarted.RemoveDynamic(this, &USaskartaAmbienceDirector::HandleBeatStarted);
        }
        if (USaskartaLightingDirector* LD = W->GetSubsystem<USaskartaLightingDirector>())
        {
            LD->OnLightningStrike.RemoveDynamic(this, &USaskartaAmbienceDirector::HandleLightning);
        }
        if (USaskartaRadioStation* Radio = W->GetSubsystem<USaskartaRadioStation>())
        {
            Radio->OnRadioForcedOn.RemoveDynamic(this, &USaskartaAmbienceDirector::HandleRadioForcedOn);
            Radio->OnRadioForcedOff.RemoveDynamic(this, &USaskartaAmbienceDirector::HandleRadioForcedOff);
        }
    }
    bBound = false;
}

// ============================================================================ data and streaming

void USaskartaAmbienceDirector::SetAmbienceAsset(USaskartaAmbienceAsset* InAsset)
{
    Asset = InAsset;
    OnAssetReady();
}

void USaskartaAmbienceDirector::RequestAsset()
{
    if (Asset)
    {
        OnAssetReady();
        return;
    }
    const FSoftObjectPath Path(USaskartaAmbienceImport::AmbienceAssetPath);
    const FAssetRegistryModule& Registry = FModuleManager::LoadModuleChecked<FAssetRegistryModule>(TEXT("AssetRegistry"));
    if (!Registry.Get().GetAssetByObjectPath(Path).IsValid())
    {
        // No DA_Ambience yet: in the editor, import the manifest into a transient asset.
        Asset = USaskartaAmbienceImport::ImportTransient(this);
        if (!Asset)
        {
            UE_LOG(LogSaskartaAmbience, Warning, TEXT("DA_Ambience not found (%s); the ambience director is idle."), *Path.ToString());
            return;
        }
        OnAssetReady();
        return;
    }
    TWeakObjectPtr<USaskartaAmbienceDirector> WeakThis(this);
    AssetHandle = UAssetManager::GetStreamableManager().RequestAsyncLoad(Path, [WeakThis, Path]()
    {
        USaskartaAmbienceDirector* Self = WeakThis.Get();
        if (!Self)
        {
            return;
        }
        Self->Asset = Cast<USaskartaAmbienceAsset>(Path.ResolveObject());
        if (!Self->Asset)
        {
            UE_LOG(LogSaskartaAmbience, Warning, TEXT("DA_Ambience did not load; the ambience director is idle."));
            return;
        }
        Self->OnAssetReady();
    }, FStreamableManager::DefaultAsyncLoadPriority);
}

void USaskartaAmbienceDirector::OnAssetReady()
{
    if (!Asset)
    {
        return;
    }
    RebuildIndex();

    // The always-resident set: storm layer, storm events, the Geiger, the mix objects.
    TArray<FSoftObjectPath> Core;
    auto Add = [&Core](const FSoftObjectPath& P) { if (P.IsValid()) Core.AddUnique(P); };
    Add(Asset->WindBreeze.ToSoftObjectPath());
    Add(Asset->WindStrong.ToSoftObjectPath());
    Add(Asset->WindGale.ToSoftObjectPath());
    for (const FSaskartaAmbienceBed& B : Asset->StormBeds)
    {
        Add(B.Sound.ToSoftObjectPath());
    }
    for (const FName PoolName : { Asset->GustPool, Asset->SandSprayPool, Asset->ThunderClosePool, Asset->ThunderDistantPool, Asset->RockfallPool })
    {
        if (const FSaskartaAmbiencePool* P = Asset->FindPool(PoolName))
        {
            for (const TSoftObjectPtr<USoundBase>& S : P->Sounds)
            {
                Add(S.ToSoftObjectPath());
            }
        }
    }
    for (const TSoftObjectPtr<USoundBase>& S : Asset->GeigerClicks)
    {
        Add(S.ToSoftObjectPath());
    }
    for (const FSaskartaGeigerLoop& L : Asset->GeigerRateLoops)
    {
        Add(L.Sound.ToSoftObjectPath());
    }
    for (const TSoftObjectPtr<USoundBase>& S : Asset->GeigerChirps)
    {
        Add(S.ToSoftObjectPath());
    }
    Add(Asset->GeigerSwitchOn.ToSoftObjectPath());
    Add(Asset->GeigerSwitchOff.ToSoftObjectPath());
    Add(Asset->AmbienceSubmix.ToSoftObjectPath());
    Add(Asset->AmbienceClass.ToSoftObjectPath());
    Add(Asset->GeigerClass.ToSoftObjectPath());

    if (CoreHandle.IsValid())
    {
        CoreHandle->ReleaseHandle();
        CoreHandle.Reset();
    }
    if (Core.Num() > 0)
    {
        TWeakObjectPtr<USaskartaAmbienceDirector> WeakThis(this);
        CoreHandle = UAssetManager::GetStreamableManager().RequestAsyncLoad(Core, [WeakThis]()
        {
            USaskartaAmbienceDirector* Self = WeakThis.Get();
            if (!Self || !Self->Asset)
            {
                return;
            }
            Self->bSubmixDuck = Self->Asset->AmbienceSubmix.Get() != nullptr;
            // Brief option B: the director plays the Ambience 2 thunder, so the lighting director stays silent.
            bool bHaveThunder = false;
            for (const FName PoolName : { Self->Asset->ThunderClosePool, Self->Asset->ThunderDistantPool })
            {
                if (const FSaskartaAmbiencePool* P = Self->Asset->FindPool(PoolName))
                {
                    for (const TSoftObjectPtr<USoundBase>& S : P->Sounds)
                    {
                        bHaveThunder |= S.Get() != nullptr;
                    }
                }
            }
            if (UWorld* W = Self->GetWorld())
            {
                if (USaskartaLightingDirector* LD = W->GetSubsystem<USaskartaLightingDirector>())
                {
                    LD->bPlayThunder = !(Self->bPlayThunder && bHaveThunder);
                }
            }
            Self->ApplyMixToAll();
            UE_LOG(LogSaskartaAmbience, Log, TEXT("Ambience core set streamed in (submix duck %d, thunder %d)."),
                Self->bSubmixDuck ? 1 : 0, bHaveThunder ? 1 : 0);
        }, FStreamableManager::DefaultAsyncLoadPriority);
    }

    ScheduleGust();
    UE_LOG(LogSaskartaAmbience, Log, TEXT("Ambience director: %d zones, %d pools, %d spots, %d dose points."),
        Asset->Zones.Num(), Asset->Pools.Num(), Asset->Spots.Num(), Asset->DoseByRoadM.Num());
}

void USaskartaAmbienceDirector::RebuildIndex()
{
    PoolStates.SetNum(Asset->Pools.Num());
    SpotStates.SetNum(Asset->Spots.Num());
    ZoneW.SetNumZeroed(Asset->Zones.Num());
    for (TPair<int32, TSharedPtr<FStreamableHandle>>& KV : ZoneHandles)
    {
        if (KV.Value.IsValid())
        {
            KV.Value->ReleaseHandle();
        }
    }
    ZoneHandles.Reset();

    // Each zone's streamed set: its beds, its pools, the spots (and their local pools) within
    // one crossfade of it, and the road-window pools overlapping it.
    ZonePaths.SetNum(Asset->Zones.Num());
    for (int32 i = 0; i < Asset->Zones.Num(); ++i)
    {
        const FSaskartaAmbienceZone& Z = Asset->Zones[i];
        TArray<FSoftObjectPath>& Paths = ZonePaths[i];
        Paths.Reset();
        auto AddPool = [&Paths](const FSaskartaAmbiencePool& P)
        {
            for (const TSoftObjectPtr<USoundBase>& S : P.Sounds)
            {
                if (!S.IsNull()) Paths.AddUnique(S.ToSoftObjectPath());
            }
        };
        for (const FSaskartaAmbienceBed& B : Z.Beds)
        {
            if (!B.Sound.IsNull()) Paths.AddUnique(B.Sound.ToSoftObjectPath());
        }
        for (const FName PoolName : Z.Pools)
        {
            if (const FSaskartaAmbiencePool* P = Asset->FindPool(PoolName))
            {
                AddPool(*P);
            }
        }
        const float Lo = Z.FromM - Z.XfadeM;
        const float Hi = Z.ToM + Z.XfadeM;
        TArray<FName> SpotLabels;
        for (const FSaskartaAmbienceSpot& S : Asset->Spots)
        {
            if (S.RoadM >= Lo && S.RoadM <= Hi)
            {
                SpotLabels.Add(S.Label);
                if (!S.Sound.IsNull()) Paths.AddUnique(S.Sound.ToSoftObjectPath());
            }
        }
        for (const FSaskartaAmbiencePool& P : Asset->Pools)
        {
            bool bHere = P.Emitters.ContainsByPredicate([&SpotLabels](const FName L) { return SpotLabels.Contains(L); });
            if (P.RoadMinM >= 0.f || P.RoadMaxM >= 0.f)
            {
                const float PLo = P.RoadMinM >= 0.f ? P.RoadMinM : -1.0e9f;
                const float PHi = P.RoadMaxM >= 0.f ? P.RoadMaxM : 1.0e9f;
                bHere |= PLo <= Hi && PHi >= Lo;
            }
            if (bHere)
            {
                AddPool(P);
            }
        }
    }
}

void USaskartaAmbienceDirector::UpdateStreaming(int32 Dominant)
{
    if (!Asset || Dominant == INDEX_NONE)
    {
        return;
    }
    // Want: every zone with weight, the dominant one and its neighbours (the next zone is prefetched).
    for (int32 i = 0; i < ZonePaths.Num(); ++i)
    {
        const bool bWant = (ZoneW.IsValidIndex(i) && ZoneW[i] > 0.f) || FMath::Abs(i - Dominant) <= 1;
        if (bWant && !ZoneHandles.Contains(i) && ZonePaths[i].Num() > 0)
        {
            ZoneHandles.Add(i, UAssetManager::GetStreamableManager().RequestAsyncLoad(ZonePaths[i], FStreamableDelegate(),
                FStreamableManager::DefaultAsyncLoadPriority));
        }
    }
    // Release the far ones (two or more zones away; their beds are silent and their spots out of range).
    TArray<int32> Release;
    for (const TPair<int32, TSharedPtr<FStreamableHandle>>& KV : ZoneHandles)
    {
        const bool bHasWeight = ZoneW.IsValidIndex(KV.Key) && ZoneW[KV.Key] > 0.f;
        if (!bHasWeight && FMath::Abs(KV.Key - Dominant) >= 2)
        {
            Release.Add(KV.Key);
        }
    }
    for (const int32 i : Release)
    {
        if (TSharedPtr<FStreamableHandle> H = ZoneHandles.FindAndRemoveChecked(i))
        {
            H->ReleaseHandle();
        }
    }
}

// ============================================================================ the 0.5 s update

bool USaskartaAmbienceDirector::ReadFrame(FAmbienceFrame& Out) const
{
    Out.NowS = Now();
    const UWorld* W = GetWorld();
    APlayerController* PC = W ? W->GetFirstPlayerController() : nullptr;
    if (!PC)
    {
        return false;
    }
    FVector Loc;
    FRotator Rot;
    PC->GetPlayerViewPoint(Loc, Rot);
    Out.Listener = Loc;
    const APawn* P = PC->GetPawn();
    Out.Carrier = P ? P->GetActorLocation() : Loc;
    const FVector V = P ? P->GetVelocity() : FVector::ZeroVector;
    Out.Travel = V.Size2D() > 50.f ? V : Rot.Vector();
    Out.bHasListener = true;
    return true;
}

void USaskartaAmbienceDirector::Update()
{
    if (!Asset)
    {
        if (!bWarnedNoAsset)
        {
            bWarnedNoAsset = true;
            UE_LOG(LogSaskartaAmbience, Verbose, TEXT("No ambience data yet."));
        }
        return;
    }
    UWorld* W = GetWorld();
    if (!W)
    {
        return;
    }
    BindSources();

    FAmbienceFrame F;
    ReadFrame(F);

    const USaskartaEventRunner* Runner = W->GetSubsystem<USaskartaEventRunner>();
    const float RunnerRoad = Runner ? Runner->GetRoadM() : -1.f;
    const float R = RoadOverrideM >= 0.f ? RoadOverrideM : RunnerRoad;
    if (R >= 0.f)
    {
        RoadM = R;
    }
    const USaskartaLightingDirector* LD = W->GetSubsystem<USaskartaLightingDirector>();
    Storm = FMath::Clamp(StormOverride >= 0.f ? StormOverride : (LD ? LD->GetEffectiveStormIntensity() : 0.f), 0.f, 1.f);
    UpdateFlow(Runner ? Runner->GetFlowState() : NAME_None);

    // Settings: the Geiger switch and the volumes.
    const USaskartaAmbienceSettings* Settings = USaskartaAmbienceSettings::Get();
    if (Settings->bGeigerCounter != bGeigerSettingOn)
    {
        bGeigerSettingOn = Settings->bGeigerCounter;
        if (bGeigerPowered)
        {
            PlayGeigerOneShot(bGeigerSettingOn ? Asset->GeigerSwitchOn : Asset->GeigerSwitchOff, SwitchVolumeDb);
        }
        ArmClickTimer();
        ApplyMixToAll();
    }
    const float SettingsVolume = USaskartaAmbienceSettings::GetAmbienceVolume() * (Settings->GeigerVolume + 1.f);
    if (!FMath::IsNearlyEqual(SettingsVolume, LastSettingsVolume, 1.0e-3f))
    {
        LastSettingsVolume = SettingsVolume;
        ApplyMixToAll();
    }

    FSaskartaAmbienceLogic::ZoneWeights(Asset->Zones, RoadM, ZoneW);
    DominantZone = FSaskartaAmbienceLogic::DominantZone(ZoneW);
    UpdateStreaming(DominantZone);

    UpdateDose(F);
    UpdateStormBeds();
    UpdateZoneBeds();
    UpdateSpots(F);
    UpdatePools(F);
    UpdateGeigerLoops();
    PruneVoices(F.NowS);
}

void USaskartaAmbienceDirector::UpdateFlow(FName Flow)
{
    using namespace SaskartaAmbience;
    if (Flow == LastFlow)
    {
        return;
    }
    const FName Prev = LastFlow;
    LastFlow = Flow;
    if (Flow == FlowCollapsing)
    {
        // The carrier shuts down: every pool, zone bed and spot is cut; the wind stays; the counter clicks off.
        bCollapsed = true;
        bHuman = false;
        SetGeigerPowered(false, true);
    }
    else if (Flow == FlowHuman)
    {
        // The handover: the traveller carries the counter on ("wind and Geiger only").
        bCollapsed = false;
        bHuman = true;
        SetGeigerPowered(true, true);
    }
    else if (Flow == FlowPlaying)
    {
        // The carrier boot (FirstBootVisionOnline) or a Continue; a reboot keeps it on.
        bCollapsed = false;
        bHuman = false;
        SetGeigerPowered(true, true);
    }
    else if (Flow == FlowTitle)
    {
        // Quit to title: silent reset.
        bCollapsed = false;
        bHuman = false;
        bFinalBeat = false;
        for (FPoolState& PS : PoolStates)
        {
            PS.bStopped = false;
        }
        SetGeigerPowered(false, false);
    }
    UE_LOG(LogSaskartaAmbience, Log, TEXT("Flow %s -> %s (Geiger %s)"), *Prev.ToString(), *Flow.ToString(), bGeigerPowered ? TEXT("on") : TEXT("off"));
}

// ============================================================================ beds

void USaskartaAmbienceDirector::SetBedTarget(FName Key, const TSoftObjectPtr<USoundBase>& Sound, float Target, float Priority,
    double NowS, bool bGeiger, float BaseVolume)
{
    FBedState& B = Beds.FindOrAdd(Key);
    B.Sound = Sound;
    B.Priority = Priority;
    B.Target = FMath::Clamp(Target, 0.f, 4.f);
    UAudioComponent* C = B.Comp.Get();

    if (B.Target > 0.001f)
    {
        B.SilentSinceS = -1.0;
        if (B.bPlaying && C && C->IsPlaying())
        {
            C->AdjustVolume(BedFadeS, B.Target);
            return;
        }
        USoundBase* S = Sound.Get();
        if (!S)
        {
            return; // still streaming in: retried on the next update
        }
        if (!C)
        {
            C = CreateVoice(S, nullptr, 0.f, 0.f, bGeiger);
            if (!C)
            {
                return;
            }
            B.Comp = C;
        }
        else if (C->Sound != S)
        {
            C->SetSound(S);
        }
        if (!AdmitVoice(C, Priority, BaseVolume, bGeiger, true))
        {
            return;
        }
        // Start each loop at a random point so the beds never phase together.
        const float Dur = S->GetDuration();
        const float Start = (Dur > 2.f && Dur < INDEFINITELY_LOOPING_DURATION) ? Random.FRandRange(0.f, Dur - 1.f) : 0.f;
        C->FadeIn(BedFadeS, B.Target, Start);
        B.bPlaying = true;
    }
    else if (B.bPlaying && C)
    {
        if (B.SilentSinceS < 0.0)
        {
            B.SilentSinceS = NowS;
            C->AdjustVolume(BedFadeS, 0.f);
        }
        else if (NowS - B.SilentSinceS > BedStopAfterSilentS)
        {
            C->FadeOut(BedFadeS, 0.f);
            B.bPlaying = false;
            B.SilentSinceS = -1.0;
        }
    }
}

void USaskartaAmbienceDirector::UpdateStormBeds()
{
    using namespace SaskartaAmbience;
    const double NowS = Now();
    const FVector G = FSaskartaAmbienceLogic::StormWindGains(Storm);
    const float WindMul = FSaskartaAmbienceLogic::WeightedZoneValue(Asset->Zones, ZoneW, &FSaskartaAmbienceZone::WindMultiplier, 1.f);
    const float Level = FSaskartaAmbienceLogic::DbToLin(Asset->WindSumDb) * WindMul;
    SetBedTarget(BedBreeze, Asset->WindBreeze, G.X * Level, PriorityWind, NowS, false, 1.f);
    SetBedTarget(BedStrong, Asset->WindStrong, G.Y * Level, PriorityWind, NowS, false, 1.f);
    SetBedTarget(BedGale, Asset->WindGale, G.Z * Level, PriorityWind, NowS, false, 1.f);
    for (const FSaskartaAmbienceBed& B : Asset->StormBeds)
    {
        SetBedTarget(B.Name, B.Sound, FSaskartaAmbienceLogic::BedGain(B, RoadM, Storm), PriorityGrit, NowS, false, 1.f);
    }
}

void USaskartaAmbienceDirector::UpdateZoneBeds()
{
    const double NowS = Now();
    // Accumulate by bed (a bed listed by two zones sums its weights).
    TMap<FName, TPair<float, const FSaskartaAmbienceBed*>> Targets;
    for (int32 i = 0; i < Asset->Zones.Num(); ++i)
    {
        const float Wz = (bCollapsed || bHuman) ? 0.f : (ZoneW.IsValidIndex(i) ? ZoneW[i] : 0.f);
        for (const FSaskartaAmbienceBed& B : Asset->Zones[i].Beds)
        {
            TPair<float, const FSaskartaAmbienceBed*>& T = Targets.FindOrAdd(B.Name, TPair<float, const FSaskartaAmbienceBed*>(0.f, &B));
            T.Key += Wz * FSaskartaAmbienceLogic::BedGain(B, RoadM, Storm);
        }
    }
    for (const TPair<FName, TPair<float, const FSaskartaAmbienceBed*>>& KV : Targets)
    {
        SetBedTarget(KV.Key, KV.Value.Value->Sound, KV.Value.Key, SaskartaAmbience::PriorityZoneBed, NowS, false, 1.f);
    }
}

// ============================================================================ spots

void USaskartaAmbienceDirector::UpdateSpots(const FAmbienceFrame& F)
{
    UWorld* W = GetWorld();
    for (int32 i = 0; i < Asset->Spots.Num() && i < SpotStates.Num(); ++i)
    {
        const FSaskartaAmbienceSpot& S = Asset->Spots[i];
        FSpotState& St = SpotStates[i];
        if (S.Sound.IsNull())
        {
            continue; // a pool anchor only (A2_WW_GateCreak)
        }
        const bool bAllowed = F.bHasListener && !bCollapsed && !bHuman && (!S.bWaterOption || bWaitingWaterHasWater);
        const float Range = (S.InnerRadiusM + S.FalloffM) * 100.f;
        const float D = bAllowed ? FVector::Dist(F.Listener, S.Location) : TNumericLimits<float>::Max();
        // Hysteresis: on inside 105 % of the audible range, off beyond 120 %.
        const bool bWant = bAllowed && (St.bActive ? D < Range * 1.2f : D < Range * 1.05f);
        UAudioComponent* C = St.Comp.Get();
        if (bWant && !St.bActive)
        {
            USoundBase* Snd = S.Sound.Get();
            if (!Snd)
            {
                continue; // streaming in
            }
            if (!C && W)
            {
                // Prefer a placed AmbientSound tagged with the label (README_Ambience.md), else our own.
                for (TActorIterator<AAmbientSound> It(W); It; ++It)
                {
                    if (It->Tags.Contains(S.Label) && It->GetAudioComponent())
                    {
                        C = It->GetAudioComponent();
                        St.bPlaced = true;
                        break;
                    }
                }
                if (!C)
                {
                    C = CreateVoice(Snd, &S.Location, S.InnerRadiusM, S.FalloffM, false);
                    St.bPlaced = false;
                }
                St.Comp = C;
            }
            if (!C)
            {
                continue;
            }
            if (!C->Sound)
            {
                C->SetSound(Snd);
            }
            if (!AdmitVoice(C, SaskartaAmbience::PrioritySpot, FSaskartaAmbienceLogic::DbToLin(S.VolumeDb), false, true))
            {
                continue;
            }
            const float Dur = C->Sound ? C->Sound->GetDuration() : 0.f;
            const float Start = (Dur > 2.f && Dur < INDEFINITELY_LOOPING_DURATION) ? Random.FRandRange(0.f, Dur - 1.f) : 0.f;
            C->FadeIn(BedFadeS, 1.f, Start);
            St.bActive = true;
        }
        else if (!bWant && St.bActive)
        {
            if (C)
            {
                C->FadeOut(BedFadeS, 0.f);
            }
            St.bActive = false;
        }
    }
}

// ============================================================================ pools

bool USaskartaAmbienceDirector::IsPoolActive(int32 PoolIndex, const FAmbienceFrame& F, FVector* OutEmitter, float* OutInnerM, float* OutFalloffM) const
{
    const FSaskartaAmbiencePool& P = Asset->Pools[PoolIndex];
    if (Storm < P.MinStorm || Storm >= P.MaxStorm)
    {
        return false;
    }
    if ((P.bWaterOption && !bWaitingWaterHasWater) || bCollapsed || (bHuman && !P.bAllowedInHuman))
    {
        return false;
    }
    if (P.bGustLullOnly && F.NowS < GustEndS + 3.0)
    {
        return false;
    }
    if ((P.RoadMinM >= 0.f && RoadM < P.RoadMinM) || (P.RoadMaxM >= 0.f && RoadM > P.RoadMaxM))
    {
        return false;
    }
    bool bZone = false;
    for (int32 z = 0; z < Asset->Zones.Num() && z < ZoneW.Num(); ++z)
    {
        if (ZoneW[z] >= 0.5f && Asset->Zones[z].Pools.Contains(P.Name))
        {
            bZone = true;
            break;
        }
    }
    // The nearest emitter whose audible radius holds the listener.
    bool bNearEmitter = false;
    if (P.Emitters.Num() > 0 && F.bHasListener)
    {
        float Best = TNumericLimits<float>::Max();
        for (const FName Label : P.Emitters)
        {
            const FSaskartaAmbienceSpot* S = Asset->FindSpot(Label);
            if (!S)
            {
                continue;
            }
            const float D = FVector::Dist(F.Listener, S->Location);
            if (D <= (S->InnerRadiusM + S->FalloffM) * 100.f && D < Best)
            {
                Best = D;
                bNearEmitter = true;
                if (OutEmitter) *OutEmitter = S->Location;
                if (OutInnerM) *OutInnerM = S->InnerRadiusM;
                if (OutFalloffM) *OutFalloffM = S->FalloffM;
            }
        }
    }
    if (P.Placement == ESaskartaPoolPlacement::AtEmitter)
    {
        return (bZone || P.bLocal) && bNearEmitter;
    }
    if (P.bLocal)
    {
        return bZone || (P.Emitters.Num() > 0 ? bNearEmitter : true);
    }
    return bZone;
}

USoundBase* USaskartaAmbienceDirector::PickFromPool(int32 PoolIndex)
{
    const FSaskartaAmbiencePool& P = Asset->Pools[PoolIndex];
    FPoolState& PS = PoolStates[PoolIndex];
    // A few draws: a variant still streaming in is skipped, never loaded here.
    for (int32 Try = 0; Try < P.Sounds.Num(); ++Try)
    {
        const int32 I = PS.Bag.Next(P.Sounds.Num(), Random);
        if (P.Sounds.IsValidIndex(I))
        {
            if (USoundBase* S = P.Sounds[I].Get())
            {
                return S;
            }
        }
    }
    return nullptr;
}

bool USaskartaAmbienceDirector::FirePool(int32 PoolIndex, const FAmbienceFrame& F, float ExtraDb, bool bIgnoreCap)
{
    if (!Asset || !Asset->Pools.IsValidIndex(PoolIndex) || !PoolStates.IsValidIndex(PoolIndex))
    {
        return false;
    }
    if (!bIgnoreCap && F.NowS - LastStingerS < StingerSpacingS)
    {
        return false;
    }
    const FSaskartaAmbiencePool& P = Asset->Pools[PoolIndex];
    FVector Loc = F.Carrier;
    float Inner = 5.f;
    float Falloff = 50.f;
    bool b3D = false;
    switch (P.Placement)
    {
    case ESaskartaPoolPlacement::AroundListener:
        if (!F.bHasListener)
        {
            return false;
        }
        Loc = FSaskartaAmbienceLogic::PointAround(F.Carrier, F.Travel, P.MinDistM, P.MaxDistM, P.ArcDeg, P.HeightOffsetM,
            Random.FRand(), Random.FRand());
        Inner = FMath::Max(2.f, P.MinDistM * 0.25f);
        Falloff = P.MaxDistM * 1.5f + 10.f;
        b3D = true;
        break;
    case ESaskartaPoolPlacement::AtEmitter:
        if (!IsPoolActive(PoolIndex, F, &Loc, &Inner, &Falloff))
        {
            return false;
        }
        b3D = true;
        break;
    default:
        break;
    }
    USoundBase* S = PickFromPool(PoolIndex);
    if (!S)
    {
        return false;
    }
    if (!PlayOneShot(S, b3D ? &Loc : nullptr, P.VolumeDb + ExtraDb, P.Priority, Inner, Falloff, 0.03f, 2.f))
    {
        return false;
    }
    LastStingerS = F.NowS;
    return true;
}

bool USaskartaAmbienceDirector::FirePoolByName(FName Pool, float VolumeDbOverride, bool bUseOverride, float RandomDb)
{
    if (!Asset)
    {
        return false;
    }
    const int32 I = Asset->FindPoolIndex(Pool);
    if (I == INDEX_NONE || !PoolStates.IsValidIndex(I))
    {
        return false;
    }
    const FSaskartaAmbiencePool& P = Asset->Pools[I];
    USoundBase* S = PickFromPool(I);
    if (!S)
    {
        return false;
    }
    return PlayOneShot(S, nullptr, bUseOverride ? VolumeDbOverride : P.VolumeDb, P.Priority, 0.f, 0.f, 0.03f, RandomDb) != nullptr;
}

void USaskartaAmbienceDirector::UpdatePools(const FAmbienceFrame& F)
{
    for (int32 i = 0; i < Asset->Pools.Num() && i < PoolStates.Num(); ++i)
    {
        const FSaskartaAmbiencePool& P = Asset->Pools[i];
        FPoolState& PS = PoolStates[i];
        if (P.IntervalMinS <= 0.f && P.IntervalMaxS <= 0.f)
        {
            continue; // event-driven (gusts, thunder)
        }
        const bool bActive = !PS.bStopped && IsPoolActive(i, F, nullptr, nullptr, nullptr);
        if (!bActive)
        {
            PS.NextFireS = -1.0;
            continue;
        }
        if (PS.NextFireS < 0.0)
        {
            PS.NextFireS = F.NowS + FSaskartaAmbienceLogic::PoolIntervalS(P.IntervalMinS, P.IntervalMaxS, Random.FRand());
            continue;
        }
        // Paused under story lines (the release shifts every NextFireS by the ducked time).
        if (bDuckWanted || F.NowS < PS.NextFireS || F.NowS - LastStingerS < StingerSpacingS)
        {
            continue;
        }
        FirePool(i, F, 0.f, false);
        PS.NextFireS = F.NowS + FSaskartaAmbienceLogic::PoolIntervalS(P.IntervalMinS, P.IntervalMaxS, Random.FRand());
    }
}

// ============================================================================ gusts and lightning

void USaskartaAmbienceDirector::ScheduleGust()
{
    UWorld* W = GetWorld();
    if (!W)
    {
        return;
    }
    const float Interval = FSaskartaAmbienceLogic::GustIntervalS(Storm, Random.FRand());
    // Under 0.15 there are no gusts: look again in 10 s.
    W->GetTimerManager().SetTimer(GustTimer, FTimerDelegate::CreateUObject(this, &USaskartaAmbienceDirector::OnGustTimer),
        Interval > 0.f ? Interval : 10.f, false);
}

void USaskartaAmbienceDirector::OnGustTimer()
{
    if (Asset && Storm >= FSaskartaAmbienceLogic::GustMinIntensity)
    {
        TriggerGust();
    }
    ScheduleGust();
}

void USaskartaAmbienceDirector::TriggerGust()
{
    UWorld* W = GetWorld();
    if (!Asset || !W)
    {
        return;
    }
    const double NowS = Now();
    const float Duration = Random.FRandRange(4.f, 7.f);
    GustEndS = NowS + Duration;

    FirePoolByName(Asset->GustPool, 0.f, false, 1.f);
    FTimerManager& TM = W->GetTimerManager();
    if (Random.FRand() < 0.5f)
    {
        FTimerHandle H;
        TM.SetTimer(H, FTimerDelegate::CreateWeakLambda(this, [this]()
        {
            if (Asset) FirePoolByName(Asset->SandSprayPool, 0.f, false, 2.f);
        }), 0.8f, false);
    }
    AddSpike(SaskartaAmbience::CauseGust, 2.5f, Duration, SaskartaAmbience::GustCapCps);

    // The metal, tarp and banners answer the gust.
    FAmbienceFrame F;
    ReadFrame(F);
    for (int32 i = 0; i < Asset->Pools.Num() && i < PoolStates.Num(); ++i)
    {
        if (Asset->Pools[i].bAlsoOnGust && !PoolStates[i].bStopped && !bDuckWanted && IsPoolActive(i, F, nullptr, nullptr, nullptr))
        {
            FTimerHandle H;
            TM.SetTimer(H, FTimerDelegate::CreateWeakLambda(this, [this, i]()
            {
                FAmbienceFrame F2;
                ReadFrame(F2);
                FirePool(i, F2, 0.f, true);
            }), Random.FRandRange(0.5f, 1.5f), false);
        }
    }
    OnGust.Broadcast(Storm, Duration);
}

void USaskartaAmbienceDirector::HandleLightning(float DistanceM, bool bClose)
{
    UWorld* W = GetWorld();
    if (!Asset || !W)
    {
        return;
    }
    // Act I (the valley to 1,000 m) is calm: no lightning there, so no thunder either.
    if (RoadM < ActIEndRoadM)
    {
        return;
    }
    FTimerManager& TM = W->GetTimerManager();
    if (bPlayThunder)
    {
        FTimerHandle H;
        const float Delay = FMath::Max(0.01f, DistanceM / USaskartaLightingDirector::SpeedOfSoundMps);
        TM.SetTimer(H, FTimerDelegate::CreateWeakLambda(this, [this, bClose]()
        {
            if (Asset) FirePoolByName(bClose ? Asset->ThunderClosePool : Asset->ThunderDistantPool, bClose ? -3.f : -6.f, true, 2.f);
        }), Delay, false);

        // The pressure front, 0.4 s after the flash.
        FTimerHandle G;
        TM.SetTimer(G, FTimerDelegate::CreateWeakLambda(this, [this]()
        {
            if (Asset) FirePoolByName(Asset->GustPool, -8.f, true, 1.f);
        }), 0.4f, false);

        if (bClose && Random.FRand() < 0.3f)
        {
            FTimerHandle Rf;
            TM.SetTimer(Rf, FTimerDelegate::CreateWeakLambda(this, [this]()
            {
                if (!Asset) return;
                FAmbienceFrame F;
                ReadFrame(F);
                // The pool's -8 dB, taken to -14.
                FirePool(Asset->FindPoolIndex(Asset->RockfallPool), F, -6.f, true);
            }), Random.FRandRange(3.f, 6.f), false);
        }
    }
    if (bClose)
    {
        AddSpike(SaskartaAmbience::CauseLightning, 3.f, 2.f, FSaskartaAmbienceLogic::MaxClickRateCps);
    }
}

void USaskartaAmbienceDirector::HandleBeatStarted(FName BeatId)
{
    if (BeatId != FinalBeatId || !Asset)
    {
        return;
    }
    // B24: the chorus thins into wind; Above_Wind stops for good.
    bFinalBeat = true;
    for (int32 i = 0; i < Asset->Pools.Num() && i < PoolStates.Num(); ++i)
    {
        if (Asset->Pools[i].bStopOnFinalBeat)
        {
            PoolStates[i].bStopped = true;
            PoolStates[i].NextFireS = -1.0;
        }
    }
}

// ============================================================================ story duck

void USaskartaAmbienceDirector::HandleStoryBusy(bool bBusy, float ExpectedS, bool bCinematic)
{
    bStoryBusy = bBusy;
    SetDuck(bStoryBusy || bRadioForced);
}

void USaskartaAmbienceDirector::HandleRadioForcedOn(FName BeatId)
{
    bRadioForced = true;
    SetDuck(true);
}

void USaskartaAmbienceDirector::HandleRadioForcedOff(bool bRadioOnAfter)
{
    bRadioForced = false;
    SetDuck(bStoryBusy);
}

void USaskartaAmbienceDirector::SetDuck(bool bDuck)
{
    if (bDuck == bDuckWanted)
    {
        return;
    }
    const double NowS = Now();
    bDuckWanted = bDuck;
    DuckFrom = DuckAmount;
    DuckStartS = NowS;
    if (bDuck)
    {
        DuckBeganAtS = NowS;
    }
    else if (DuckBeganAtS >= 0.0)
    {
        // The pool timers were paused: move every pending fire by the time spent ducked.
        const double Paused = NowS - DuckBeganAtS;
        for (FPoolState& PS : PoolStates)
        {
            if (PS.NextFireS >= 0.0)
            {
                PS.NextFireS += Paused;
            }
        }
        DuckBeganAtS = -1.0;
    }
    if (UWorld* W = GetWorld())
    {
        W->GetTimerManager().SetTimer(DuckTimer, FTimerDelegate::CreateUObject(this, &USaskartaAmbienceDirector::OnDuckTimer),
            SaskartaAmbience::DuckStepS, true, 0.f);
    }
}

void USaskartaAmbienceDirector::OnDuckTimer()
{
    const float Dur = bDuckWanted ? DuckAttackS : DuckReleaseS;
    const float T = Dur > 0.f ? FMath::Clamp(static_cast<float>((Now() - DuckStartS) / Dur), 0.f, 1.f) : 1.f;
    DuckAmount = FMath::Lerp(DuckFrom, bDuckWanted ? 1.f : 0.f, T);
    ApplyMixToAll();
    if (T >= 1.f)
    {
        if (UWorld* W = GetWorld())
        {
            W->GetTimerManager().ClearTimer(DuckTimer);
        }
    }
}

float USaskartaAmbienceDirector::MixGain(bool bGeiger) const
{
    float G = USaskartaAmbienceSettings::GetAmbienceVolume();
    const float Duck = FMath::Lerp(1.f, FSaskartaAmbienceLogic::DbToLin(DuckDb), DuckAmount);
    if (!bSubmixDuck)
    {
        G *= Duck;
    }
    if (bGeiger)
    {
        const USaskartaAmbienceSettings* S = USaskartaAmbienceSettings::Get();
        G *= FMath::Lerp(1.f, FSaskartaAmbienceLogic::DbToLin(GeigerExtraDuckDb), DuckAmount);
        G *= S->bGeigerCounter ? FMath::Clamp(S->GeigerVolume, 0.f, 1.f) : 0.f;
    }
    return G;
}

void USaskartaAmbienceDirector::ApplyVoiceVolume(const FVoice& V) const
{
    if (UAudioComponent* C = V.Comp.Get())
    {
        C->SetVolumeMultiplier(V.BaseVolume * MixGain(V.bGeiger));
    }
}

void USaskartaAmbienceDirector::ApplyMixToAll()
{
    for (const FVoice& V : Voices)
    {
        ApplyVoiceVolume(V);
    }
    if (bSubmixDuck && Asset)
    {
        if (USoundSubmix* Smx = Asset->AmbienceSubmix.Get())
        {
            Smx->SetSubmixOutputVolume(this, FMath::Lerp(1.f, FSaskartaAmbienceLogic::DbToLin(DuckDb), DuckAmount));
        }
    }
}

// ============================================================================ voices

UAudioComponent* USaskartaAmbienceDirector::CreateVoice(USoundBase* Sound, const FVector* Location, float InnerM, float FalloffM, bool bGeiger)
{
    UWorld* W = GetWorld();
    if (!W || !Sound)
    {
        return nullptr;
    }
    AActor* Owner = nullptr;
    if (bGeiger)
    {
        // The Geiger rides the camera (the listener), a little to the dashboard side.
        const APlayerController* PC = W->GetFirstPlayerController();
        Owner = PC ? PC->PlayerCameraManager : nullptr;
    }
    FAudioDevice::FCreateComponentParams Params = Owner ? FAudioDevice::FCreateComponentParams(W, Owner) : FAudioDevice::FCreateComponentParams(W);
    Params.bPlay = false;
    Params.bAutoDestroy = false;
    if (Location)
    {
        Params.SetLocation(*Location);
    }
    UAudioComponent* C = FAudioDevice::CreateComponent(Sound, Params);
    if (!C)
    {
        return nullptr;
    }
    if (Location)
    {
        C->bAllowSpatialization = true;
        C->bOverrideAttenuation = true;
        C->AttenuationOverrides = SaskartaAmbience::MakeAttenuation(InnerM, FalloffM);
    }
    else if (bGeiger && Owner && Owner->GetRootComponent())
    {
        C->AttachToComponent(Owner->GetRootComponent(), FAttachmentTransformRules::KeepRelativeTransform);
        const float Pan = FMath::Clamp(GeigerPan, -1.f, 1.f);
        C->SetRelativeLocation(FVector(FMath::Sqrt(1.f - Pan * Pan), Pan, 0.f) * 100.f);
        FSoundAttenuationSettings S;
        S.bAttenuate = false;
        S.bSpatialize = true;
        C->bAllowSpatialization = true;
        C->bOverrideAttenuation = true;
        C->AttenuationOverrides = S;
    }
    else
    {
        C->bAllowSpatialization = false; // 2D
    }
    if (Asset)
    {
        if (USoundClass* Cls = (bGeiger ? Asset->GeigerClass : Asset->AmbienceClass).Get())
        {
            C->SoundClassOverride = Cls;
        }
    }
    OwnedComps.AddUnique(C);
    return C;
}

bool USaskartaAmbienceDirector::AdmitVoice(UAudioComponent* Comp, float Priority, float BaseVolume, bool bGeiger, bool bPersistent)
{
    if (!Comp)
    {
        return false;
    }
    const double NowS = Now();
    // The two click components have their own reserved slots (brief section 5: "Geiger clicks, 2"),
    // so a click never culls anything and nothing culls a click.
    auto IsClick = [this](const UAudioComponent* C) { return C && (C == ClickComps[0].Get() || C == ClickComps[1].Get()); };
    const bool bClick = IsClick(Comp);
    TArray<FSaskartaVoiceInfo> Active;
    TArray<int32> ActiveIndex;
    for (int32 i = 0; i < Voices.Num() && !bClick; ++i)
    {
        UAudioComponent* C = Voices[i].Comp.Get();
        if (C && C != Comp && !IsClick(C) && C->IsPlaying())
        {
            FSaskartaVoiceInfo Info;
            Info.Priority = Voices[i].Priority;
            Info.Volume = Voices[i].BaseVolume;
            Info.StartS = Voices[i].StartS;
            Active.Add(Info);
            ActiveIndex.Add(i);
        }
    }
    FSaskartaVoiceInfo Candidate;
    Candidate.Priority = Priority;
    Candidate.Volume = BaseVolume;
    Candidate.StartS = NowS;
    bool bReject = false;
    const int32 ClickSlots = GeigerAudible() ? 2 : 0;
    const int32 Cull = bClick ? INDEX_NONE
        : FSaskartaAmbienceLogic::PickVoiceToCull(Active, Candidate, FMath::Max(1, MaxVoices - ReservedExternalVoices - ClickSlots), bReject);
    if (bReject)
    {
        UE_LOG(LogSaskartaAmbience, Verbose, TEXT("Voice budget: %s rejected (priority %.0f)."), *GetNameSafe(Comp->Sound), Priority);
        return false;
    }
    if (Cull != INDEX_NONE)
    {
        FVoice& Lowest = Voices[ActiveIndex[Cull]];
        UE_LOG(LogSaskartaAmbience, Verbose, TEXT("Voice budget: culling %s (priority %.0f) for %s."),
            Lowest.Comp.IsValid() ? *GetNameSafe(Lowest.Comp->Sound) : TEXT("?"), Lowest.Priority, *GetNameSafe(Comp->Sound));
        StopVoiceComp(Lowest.Comp.Get(), 0.25f);
    }

    FVoice* V = Voices.FindByPredicate([Comp](const FVoice& X) { return X.Comp.Get() == Comp; });
    if (!V)
    {
        V = &Voices.AddDefaulted_GetRef();
        V->Comp = Comp;
    }
    V->Priority = Priority;
    V->BaseVolume = BaseVolume;
    V->StartS = NowS;
    V->bGeiger = bGeiger;
    V->bPersistent = bPersistent;
    OwnedComps.AddUnique(Comp);
    ApplyVoiceVolume(*V);
    return true;
}

void USaskartaAmbienceDirector::StopVoiceComp(UAudioComponent* Comp, float FadeS)
{
    if (!Comp)
    {
        return;
    }
    Comp->FadeOut(FadeS, 0.f);
    for (TPair<FName, FBedState>& KV : Beds)
    {
        if (KV.Value.Comp.Get() == Comp)
        {
            KV.Value.bPlaying = false;
            KV.Value.SilentSinceS = -1.0;
        }
    }
    for (FSpotState& S : SpotStates)
    {
        if (S.Comp.Get() == Comp)
        {
            S.bActive = false;
        }
    }
}

UAudioComponent* USaskartaAmbienceDirector::PlayOneShot(USoundBase* Sound, const FVector* Location, float VolumeDb, float Priority,
    float InnerM, float FalloffM, float PitchJitter, float DbJitter)
{
    if (!Sound)
    {
        return nullptr;
    }
    const float Db = VolumeDb + (DbJitter > 0.f ? Random.FRandRange(-DbJitter, DbJitter) : 0.f);
    UAudioComponent* C = CreateVoice(Sound, Location, InnerM, FalloffM, false);
    if (!C)
    {
        return nullptr;
    }
    if (!AdmitVoice(C, Priority, FSaskartaAmbienceLogic::DbToLin(Db), false, false))
    {
        OwnedComps.Remove(C);
        C->DestroyComponent();
        return nullptr;
    }
    C->SetPitchMultiplier(1.f + (PitchJitter > 0.f ? Random.FRandRange(-PitchJitter, PitchJitter) : 0.f));
    C->bAutoDestroy = true;
    C->Play();
    return C;
}

void USaskartaAmbienceDirector::PruneVoices(double NowS)
{
    Voices.RemoveAll([NowS](const FVoice& V)
    {
        const UAudioComponent* C = V.Comp.Get();
        return !C || (!V.bPersistent && !C->IsPlaying() && NowS - V.StartS > 0.5);
    });
    OwnedComps.RemoveAll([](const TObjectPtr<UAudioComponent>& C)
    {
        return !IsValid(C) || (C->bAutoDestroy && !C->IsPlaying());
    });
}

// ============================================================================ Geiger

bool USaskartaAmbienceDirector::GeigerAudible() const
{
    return bGeigerPowered && bGeigerSettingOn;
}

void USaskartaAmbienceDirector::SetGeigerPowered(bool bOn, bool bPlaySwitch)
{
    if (bOn == bGeigerPowered)
    {
        return;
    }
    bGeigerPowered = bOn;
    if (bPlaySwitch && bGeigerSettingOn && Asset)
    {
        PlayGeigerOneShot(bOn ? Asset->GeigerSwitchOn : Asset->GeigerSwitchOff, SwitchVolumeDb);
    }
    ArmClickTimer();
    UpdateGeigerLoops();
}

void USaskartaAmbienceDirector::PlayGeigerOneShot(const TSoftObjectPtr<USoundBase>& Sound, float VolumeDb)
{
    USoundBase* S = Sound.Get();
    if (!S)
    {
        return;
    }
    UAudioComponent* C = CreateVoice(S, nullptr, 0.f, 0.f, true);
    if (!C)
    {
        return;
    }
    // The switch itself is heard even as the setting mutes the clicks, so it rides the ambience mix.
    if (!AdmitVoice(C, SaskartaAmbience::PriorityGeiger, FSaskartaAmbienceLogic::DbToLin(VolumeDb), false, false))
    {
        OwnedComps.Remove(C);
        C->DestroyComponent();
        return;
    }
    C->bAutoDestroy = true;
    C->Play();
}

void USaskartaAmbienceDirector::AddSpike(FName Cause, float Multiplier, float HoldS, float CapCps)
{
    const double NowS = Now();
    for (FSaskartaDoseSpike& S : Spikes)
    {
        if (S.Cause == Cause && FSaskartaAmbienceLogic::SpikeMultiplier(S, NowS) > 1.01f)
        {
            // Still live: extend it (the dust wall refreshes every update), no new event.
            S.HoldUntilS = FMath::Max(S.HoldUntilS, NowS + HoldS);
            S.Multiplier = FMath::Max(S.Multiplier, Multiplier);
            return;
        }
    }
    Spikes.RemoveAll([Cause](const FSaskartaDoseSpike& S) { return S.Cause == Cause; });
    FSaskartaDoseSpike& N = Spikes.AddDefaulted_GetRef();
    N.Cause = Cause;
    N.Multiplier = Multiplier;
    N.HoldUntilS = NowS + HoldS;
    N.CapCps = CapCps;
    PrevDose = Dose;
    Dose = FSaskartaAmbienceLogic::ComposeDose(RoadDose, Spikes, NowS);
    OnDoseSpike.Broadcast(Dose, Cause);
    ArmClickTimer();
}

void USaskartaAmbienceDirector::UpdateDose(const FAmbienceFrame& F)
{
    const float ZoneMul = FSaskartaAmbienceLogic::WeightedZoneValue(Asset->Zones, ZoneW, &FSaskartaAmbienceZone::DoseMultiplier, 1.f);
    RoadDose = FSaskartaAmbienceLogic::DoseAtRoadM(Asset->DoseByRoadM, RoadM) * ZoneMul;

    // A dust wall: the storm at 0.8+ with the grit hiss up.
    if (Storm >= SaskartaAmbience::DustWallIntensity && !bCollapsed)
    {
        AddSpike(SaskartaAmbience::CauseDustWall, 1.8f, UpdateIntervalS * 1.5f, FSaskartaAmbienceLogic::MaxClickRateCps);
    }
    Spikes.RemoveAll([&F](const FSaskartaDoseSpike& S)
    {
        return F.NowS > S.HoldUntilS && FSaskartaAmbienceLogic::SpikeMultiplier(S, F.NowS) < 1.01f;
    });

    const float Before = Dose;
    Dose = FSaskartaAmbienceLogic::ComposeDose(RoadDose, Spikes, F.NowS);
    // PrevDose is the dose at the last update (or just before a spike), so a spike rising through the threshold chirps.
    const float From = FMath::Min(PrevDose, Before);
    PrevDose = Dose;

    if (GeigerAudible() && FSaskartaAmbienceLogic::ShouldChirp(From, Dose, ChirpThresholdCps, F.NowS, LastChirpS, ChirpCooldownS))
    {
        const int32 I = ChirpBag.Next(Asset->GeigerChirps.Num(), Random);
        if (Asset->GeigerChirps.IsValidIndex(I) && Asset->GeigerChirps[I].Get())
        {
            UAudioComponent* C = CreateVoice(Asset->GeigerChirps[I].Get(), nullptr, 0.f, 0.f, true);
            if (C && AdmitVoice(C, SaskartaAmbience::PriorityGeiger, FSaskartaAmbienceLogic::DbToLin(ChirpVolumeDb), true, false))
            {
                C->bAutoDestroy = true;
                C->Play();
                LastChirpS = F.NowS;
            }
        }
    }

    // Re-draw the Poisson clock when the rate moved (memoryless, so a re-draw is exact).
    const float Rate = GeigerAudible() ? FSaskartaAmbienceLogic::GeigerMix(Dose, MinClickRateCps).ClickRate : 0.f;
    const UWorld* W = GetWorld();
    const bool bArmed = W && W->GetTimerManager().IsTimerActive(ClickTimer);
    if ((Rate > 0.f) != bArmed || FMath::Abs(Rate - ArmedRate) > 0.2f * FMath::Max(ArmedRate, 0.1f))
    {
        ArmClickTimer();
    }
}

void USaskartaAmbienceDirector::ArmClickTimer()
{
    UWorld* W = GetWorld();
    if (!W)
    {
        return;
    }
    const float Rate = (GeigerAudible() && Asset) ? FSaskartaAmbienceLogic::GeigerMix(Dose, MinClickRateCps).ClickRate : 0.f;
    ArmedRate = Rate;
    bool bAnyClick = false;
    if (Asset)
    {
        for (const TSoftObjectPtr<USoundBase>& S : Asset->GeigerClicks)
        {
            if (S.Get())
            {
                bAnyClick = true;
                break;
            }
        }
    }
    if (Rate <= 0.f || !bAnyClick)
    {
        W->GetTimerManager().ClearTimer(ClickTimer);
        return;
    }
    const float Delay = FMath::Max(0.001f, FSaskartaAmbienceLogic::PoissonIntervalS(Rate, 1.f - Random.FRand()));
    W->GetTimerManager().SetTimer(ClickTimer, FTimerDelegate::CreateUObject(this, &USaskartaAmbienceDirector::OnClickTimer), Delay, false);
}

void USaskartaAmbienceDirector::OnClickTimer()
{
    if (!Asset || !GeigerAudible())
    {
        return;
    }
    const int32 I = ClickBag.Next(Asset->GeigerClicks.Num(), Random);
    USoundBase* S = Asset->GeigerClicks.IsValidIndex(I) ? Asset->GeigerClicks[I].Get() : nullptr;
    if (S)
    {
        // Two components in turn (the brief's click concurrency of 2); no component per click.
        const int32 Slot = NextClickComp;
        NextClickComp = (NextClickComp + 1) % 2;
        UAudioComponent* C = ClickComps[Slot].Get();
        if (!C)
        {
            C = CreateVoice(S, nullptr, 0.f, 0.f, true);
            ClickComps[Slot] = C;
        }
        if (C)
        {
            if (C->Sound != S)
            {
                C->SetSound(S);
            }
            // The clicks' natural level variation, plus a random -2.5..0 dB.
            const float Base = FSaskartaAmbienceLogic::DbToLin(GeigerLevelDb + Random.FRandRange(-2.5f, 0.f));
            if (AdmitVoice(C, SaskartaAmbience::PriorityGeiger, Base, true, true))
            {
                C->Play();
            }
        }
    }
    ArmClickTimer();
}

void USaskartaAmbienceDirector::EnsureGeigerComps()
{
    // Components are made on first use (OnClickTimer, UpdateGeigerLoops); nothing to pre-create.
}

void USaskartaAmbienceDirector::UpdateGeigerLoops()
{
    if (!Asset)
    {
        return;
    }
    const double NowS = Now();
    const int32 N = Asset->GeigerRateLoops.Num();
    TArray<float> Gains;
    Gains.SetNumZeroed(N);
    if (GeigerAudible() && N > 0)
    {
        bool bAnyClick = false;
        for (const TSoftObjectPtr<USoundBase>& S : Asset->GeigerClicks)
        {
            bAnyClick |= S.Get() != nullptr;
        }
        if (bAnyClick)
        {
            // Clicks carry the rate; the fastest loop takes over above 30-50 cps.
            Gains[N - 1] = FSaskartaAmbienceLogic::GeigerMix(Dose, MinClickRateCps).LoopGain;
        }
        else
        {
            // No clicks (not imported): the rate loops crossfaded by log(dose).
            TArray<float> Rates;
            for (const FSaskartaGeigerLoop& L : Asset->GeigerRateLoops)
            {
                Rates.Add(L.RateCps);
            }
            FSaskartaAmbienceLogic::GeigerLoopWeights(Rates, Dose, Gains);
        }
    }
    const float Base = FSaskartaAmbienceLogic::DbToLin(GeigerLevelDb);
    for (int32 i = 0; i < N; ++i)
    {
        SetBedTarget(FName(*FString::Printf(TEXT("Geiger_Loop_%d"), i)), Asset->GeigerRateLoops[i].Sound, Gains[i],
            SaskartaAmbience::PriorityGeiger, NowS, true, Base);
    }
}

// ============================================================================ debug

FString USaskartaAmbienceDirector::DumpState() const
{
    FString S;
    S += FString::Printf(TEXT("Ambience: %s | road %.0f m | zone %s | storm %.2f | flow %s%s%s\n"),
        Asset ? *Asset->GetName() : TEXT("(no data)"), RoadM, *GetCurrentZone().ToString(), Storm, *LastFlow.ToString(),
        bCollapsed ? TEXT(" [collapsed]") : TEXT(""), bHuman ? TEXT(" [human]") : TEXT(""));
    S += TEXT("Zone weights:");
    if (Asset)
    {
        for (int32 i = 0; i < Asset->Zones.Num() && i < ZoneW.Num(); ++i)
        {
            S += FString::Printf(TEXT(" %s=%.2f"), *Asset->Zones[i].Name.ToString(), ZoneW[i]);
        }
    }
    S += FString::Printf(TEXT("\nDose %.2f cps (road %.2f, %d spikes) | Geiger %s%s | duck %.2f%s | voices %d/%d (reserve %d) | streamed zones %d\n"),
        Dose, RoadDose, Spikes.Num(), bGeigerPowered ? TEXT("on") : TEXT("off"), bGeigerSettingOn ? TEXT("") : TEXT(" (muted by setting)"),
        DuckAmount, bSubmixDuck ? TEXT(" (submix)") : TEXT(""), GetActiveVoiceCount(), MaxVoices, ReservedExternalVoices, ZoneHandles.Num());
    for (const TPair<FName, FBedState>& KV : Beds)
    {
        if (KV.Value.bPlaying || KV.Value.Target > 0.f)
        {
            S += FString::Printf(TEXT("  bed %s target %.3f%s\n"), *KV.Key.ToString(), KV.Value.Target,
                KV.Value.Sound.Get() ? TEXT("") : TEXT(" (not loaded)"));
        }
    }
    return S;
}

namespace SaskartaAmbience
{
    static USaskartaAmbienceDirector* DirectorFor(UWorld* World)
    {
        return World ? World->GetSubsystem<USaskartaAmbienceDirector>() : nullptr;
    }

    static FAutoConsoleCommandWithWorldAndArgs CmdDump(TEXT("Saskarta.Ambience.Dump"),
        TEXT("Logs the ambience director's state (zones, dose, beds, voices)."),
        FConsoleCommandWithWorldAndArgsDelegate::CreateLambda([](const TArray<FString>&, UWorld* World)
        {
            if (USaskartaAmbienceDirector* D = DirectorFor(World))
            {
                UE_LOG(LogSaskartaAmbience, Display, TEXT("%s"), *D->DumpState());
            }
        }));

    static FAutoConsoleCommandWithWorldAndArgs CmdGust(TEXT("Saskarta.Ambience.Gust"),
        TEXT("Fires a storm gust now."),
        FConsoleCommandWithWorldAndArgsDelegate::CreateLambda([](const TArray<FString>&, UWorld* World)
        {
            if (USaskartaAmbienceDirector* D = DirectorFor(World))
            {
                D->TriggerGust();
            }
        }));

    static FAutoConsoleCommandWithWorldAndArgs CmdRoad(TEXT("Saskarta.Ambience.Road"),
        TEXT("Saskarta.Ambience.Road <m>: pins the ambience road metre (negative releases it)."),
        FConsoleCommandWithWorldAndArgsDelegate::CreateLambda([](const TArray<FString>& Args, UWorld* World)
        {
            if (USaskartaAmbienceDirector* D = DirectorFor(World))
            {
                D->SetRoadOverride(Args.Num() > 0 ? FCString::Atof(*Args[0]) : -1.f);
            }
        }));

    static FAutoConsoleCommandWithWorldAndArgs CmdStorm(TEXT("Saskarta.Ambience.Storm"),
        TEXT("Saskarta.Ambience.Storm <0-1>: pins the ambience storm intensity (negative releases it)."),
        FConsoleCommandWithWorldAndArgsDelegate::CreateLambda([](const TArray<FString>& Args, UWorld* World)
        {
            if (USaskartaAmbienceDirector* D = DirectorFor(World))
            {
                D->SetStormOverride(Args.Num() > 0 ? FCString::Atof(*Args[0]) : -1.f);
            }
        }));

    static FAutoConsoleCommandWithWorldAndArgs CmdGeiger(TEXT("Saskarta.Ambience.Geiger"),
        TEXT("Saskarta.Ambience.Geiger <0|1>: switches the Geiger counter off or on."),
        FConsoleCommandWithWorldAndArgsDelegate::CreateLambda([](const TArray<FString>& Args, UWorld* World)
        {
            if (USaskartaAmbienceDirector* D = DirectorFor(World))
            {
                D->SetGeigerPowered(Args.Num() == 0 || FCString::Atoi(*Args[0]) != 0, true);
            }
        }));
}
