// USaskartaRadioStation. See the header, docs/story/STATION.md (the shuffle loop) and docs/story/RADIO_SHOW.md (the show).

#include "SaskartaRadioStation.h"

#include "SaskartaAudioMix.h"
#include "SaskartaEventRunner.h"
#include "SaskartaEventTypes.h"
#include "SaskartaLightingDirector.h"
#include "SaskartaPower.h"
#include "SaskartaStationAsset.h"
#include "SaskartaStorySettings.h"
#include "SaskartaTetherSubsystem.h"

#include "AssetRegistry/AssetData.h"
#include "AssetRegistry/IAssetRegistry.h"
#include "AudioMixerBlueprintLibrary.h"
#include "Components/AudioComponent.h"
#include "Engine/AssetManager.h"
#include "Engine/Engine.h"
#include "Engine/StreamableManager.h"
#include "Engine/World.h"
#include "HAL/FileManager.h"
#include "HAL/IConsoleManager.h"
#include "HAL/PlatformTime.h"
#include "Kismet/GameplayStatics.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "Sound/SoundBase.h"
#include "Sound/SoundCue.h"
#include "Sound/SoundEffectSubmix.h"
#include "Sound/SoundNodeWavePlayer.h"
#include "Sound/SoundSubmix.h"
#include "Sound/SoundWave.h"

DEFINE_LOG_CATEGORY_STATIC(LogSaskartaStation, Log, All);

namespace SaskartaRadio
{
    static constexpr float UpdateS = 0.25f;
    static constexpr double ScanIntervalS = 10.0;
    static constexpr float DefaultSongS = 120.f;
    /** A due voice take that is still loading waits this long, then plays as a subtitle only. */
    static constexpr double VoiceLoadWaitS = 1.5;
    /** A due song that is still loading waits this long, then is skipped. */
    static constexpr double SongLoadWaitS = 3.0;
    static constexpr double PrefetchIntervalS = 1.0;
    /** The show's window: this many backbone items ahead (plus every MUST left, the next opening, a fill, a linger line). */
    static constexpr int32 PrefetchBackbone = 4;
    /** STORM_UP: the rise over this window. */
    static constexpr double StormWindowS = 20.0;
    static constexpr float StormRise = 0.15f;
    static constexpr double RadioBackOnAfterS = 10.0;
    static constexpr double ResumedAfterS = 15.0;
    /** The song's tail ducks under the outro. */
    static constexpr float TailDuckDb = -6.f;

    static float DurationTag(const FAssetData& Data)
    {
        float D = 0.f;
        FString S;
        if (Data.GetTagValue(FName(TEXT("Duration")), S))
        {
            D = FCString::Atof(*S);
        }
        return D;
    }

    static const TCHAR* Roman(int32 N)
    {
        static const TCHAR* R[] = { TEXT(""), TEXT("I"), TEXT("II"), TEXT("III"), TEXT("IV"), TEXT("V"), TEXT("VI"), TEXT("VII") };
        return (N >= 0 && N < 8) ? R[N] : TEXT("");
    }
}

// ============================================================================ access, lifecycle

USaskartaRadioStation* USaskartaRadioStation::GetRadioStation(const UObject* WorldContextObject)
{
    const UWorld* World = GEngine ? GEngine->GetWorldFromContextObject(WorldContextObject, EGetWorldErrorMode::ReturnNull) : nullptr;
    return World ? World->GetSubsystem<USaskartaRadioStation>() : nullptr;
}

void USaskartaRadioStation::SetUnderVoice(bool bUnder)
{
    UnderTarget = bUnder ? FSaskartaStationLogic::DbToLinear(-8.f) : 1.f;
    if (UWorld* World = GetWorld())
    {
        World->GetTimerManager().SetTimer(UnderTimer, this, &USaskartaRadioStation::StepUnderVoice, 0.05f, true);
    }
}

void USaskartaRadioStation::StepUnderVoice()
{
    // A 0.3 s ramp in 0.05 s steps. VolumeMultiplier, not AdjustVolume, so the station's own fades are untouched;
    // components that start during the duck join it at their own level.
    const float Step = 0.05f / 0.3f;
    UnderNow = UnderTarget < UnderNow ? FMath::Max(UnderTarget, UnderNow - Step) : FMath::Min(UnderTarget, UnderNow + Step);
    for (UAudioComponent* C : { PartComp.Get(), BedComp.Get(), TailComp.Get(), CodaComp.Get(), TitleComp.Get(), RecallComp.Get() })
    {
        if (!C || C == PartComp || C == BedComp || C == TitleComp)
        {
            continue;
        }
        const float* Base = UnderBase.Find(C);
        const float B = Base ? *Base : UnderBase.Add(C, C->VolumeMultiplier);
        C->SetVolumeMultiplier(B * UnderNow);
    }
    // These two components recompute their base reception gain; never cache an authored zero-gain gap.
    if (Asset) ApplyReception();
    RefreshEndingMusicVolume();
    if (UnderTarget >= 1.f && UnderNow >= 1.f)
    {
        UnderBase.Reset();
        if (UWorld* World = GetWorld())
        {
            World->GetTimerManager().ClearTimer(UnderTimer);
        }
    }
}

bool USaskartaRadioStation::DoesSupportWorldType(const EWorldType::Type WorldType) const
{
    return WorldType == EWorldType::Game || WorldType == EWorldType::PIE;
}

double USaskartaRadioStation::Now() const
{
    const UWorld* World = GetWorld();
    return World ? World->GetTimeSeconds() : 0.0;
}

void USaskartaRadioStation::Initialize(FSubsystemCollectionBase& Collection)
{
    Super::Initialize(Collection);
    // The runner must exist first so OnWorldBeginPlay can bind its events.
    Collection.InitializeDependency<USaskartaEventRunner>();
    WritingRunHandle = USaskartaSaveGame::OnWritingRun.AddUObject(this, &USaskartaRadioStation::HandleWritingRun);
    RestoredRunHandle = USaskartaSaveGame::OnRestoredRun.AddUObject(this, &USaskartaRadioStation::HandleRestoredRun);
}

void USaskartaRadioStation::OnWorldBeginPlay(UWorld& InWorld)
{
    Super::OnWorldBeginPlay(InWorld);
    USaskartaStorySettings::ApplyStoryCVars();
    BindRunner();
    if (!Asset)
    {
        BeginStationAssetLoad();
    }
    else
    {
        OnStationAssetReady();
    }
    CheckRecordingsOnDisk();
    InWorld.GetTimerManager().SetTimer(UpdateTimer, this, &USaskartaRadioStation::Update, SaskartaRadio::UpdateS, true);
}

void USaskartaRadioStation::Deinitialize()
{
    USaskartaSaveGame::OnWritingRun.Remove(WritingRunHandle);
    USaskartaSaveGame::OnRestoredRun.Remove(RestoredRunHandle);
    if (UWorld* World = GetWorld())
    {
        FTimerManager& TM = World->GetTimerManager();
        TM.ClearTimer(UpdateTimer);
        TM.ClearTimer(DuckFadeTimer);
        TM.ClearTimer(PitchRestoreTimer);
        TM.ClearTimer(SongRiseTimer);
        TM.ClearTimer(CodaTimer);
        TM.ClearTimer(TitleTimer);
        TM.ClearTimer(RecallTimer);
        TM.ClearTimer(BoostPulseTimer);
    }
    for (UAudioComponent* C : { PartComp.Get(), TailComp.Get(), BedComp.Get(), CodaComp.Get(), TitleComp.Get() })
    {
        if (C) C->Stop();
    }
    for (TPair<FString, TSharedPtr<FStreamableHandle>>& KV : Loads)
    {
        if (KV.Value.IsValid()) KV.Value->CancelHandle();
    }
    Loads.Reset();
    if (StationAssetHandle.IsValid()) StationAssetHandle->CancelHandle();
    if (FilterHandle.IsValid()) FilterHandle->CancelHandle();
    if (EndingTitleLoad.IsValid()) EndingTitleLoad->CancelHandle();
    Super::Deinitialize();
}

void USaskartaRadioStation::SetStationAsset(USaskartaStationAsset* InAsset)
{
    Asset = InAsset;
    bWaitingForStationAsset = false;
    if (Asset)
    {
        Scheduler.Init(Asset->Config, FMath::Rand());
        Show.Init(Asset->Config, FMath::Rand());
        bShowMode = Show.IsShowMode();
        ExistsCache.Reset();
        LastScanS = -1000.0;
        UE_LOG(LogSaskartaStation, Log, TEXT("Station data: %d segments, %d songs listed; %s"), Asset->Config.Segments.Num(), Asset->Config.Songs.Num(),
            bShowMode ? *FString::Printf(TEXT("the live show (%d acts)"), Show.NumActs()) : TEXT("the shuffle loop"));
        OnStationAssetReady();
    }
}

void USaskartaRadioStation::BeginStationAssetLoad()
{
    const FSoftObjectPath Path(USaskartaStationImport::StationAssetPath);
    if (USaskartaStationAsset* InMemory = Cast<USaskartaStationAsset>(Path.ResolveObject()))
    {
        SetStationAsset(InMemory);
        return;
    }
    IAssetRegistry* AR = IAssetRegistry::Get();
    if (AR && AR->GetAssetByObjectPath(Path).IsValid())
    {
        bWaitingForStationAsset = true;
        TWeakObjectPtr<USaskartaRadioStation> WeakThis(this);
        StationAssetHandle = UAssetManager::GetStreamableManager().RequestAsyncLoad(TArray<FSoftObjectPath>{ Path }, [WeakThis, Path]()
        {
            USaskartaRadioStation* Self = WeakThis.Get();
            if (!Self)
            {
                return;
            }
            USaskartaStationAsset* Loaded = Cast<USaskartaStationAsset>(Path.ResolveObject());
            if (!Loaded)
            {
                Loaded = USaskartaStationImport::ImportTransient(Self);
            }
            if (Loaded)
            {
                Self->SetStationAsset(Loaded);
            }
            else
            {
                UE_LOG(LogSaskartaStation, Warning, TEXT("DA_Station did not load; the station is silent."));
            }
        }, FStreamableManager::DefaultAsyncLoadPriority);
        UE_LOG(LogSaskartaStation, Log, TEXT("DA_Station: loading asynchronously"));
        return;
    }
    // No asset (editor, before the re-import): the transient import reads station.json, no asset load.
    if (USaskartaStationAsset* Transient = USaskartaStationImport::ImportTransient(this))
    {
        SetStationAsset(Transient);
    }
    else
    {
        UE_LOG(LogSaskartaStation, Warning, TEXT("DA_Station not found (%s); the station is silent."), USaskartaStationImport::StationAssetPath);
    }
}

void USaskartaRadioStation::OnStationAssetReady()
{
    if (!Asset)
    {
        return;
    }
    ApplyArchiveFilterWhenLoaded();
    // The static sounds stay resident (pinned); they load in the background.
    const FSaskartaStationConfig& C = Asset->Config;
    PinnedPaths.Reset();
    for (const FSoftObjectPath* P : { &C.StaticBed, &C.StaticIn, &C.StaticOut, &C.TuneSweep })
    {
        if (!P->IsNull())
        {
            PinnedPaths.Add(P->ToString());
            RequestLoad(P->ToString(), true);
        }
    }
    if (bHasPendingShowState)
    {
        bHasPendingShowState = false;
        ApplyShowSaveState(PendingShowState);
    }
    if (const USaskartaEventRunner* R = Runner.Get()) SetEndingMusicFlow(R->GetFlowState());
}

void USaskartaRadioStation::ApplyArchiveFilterWhenLoaded()
{
    if (!Asset || Asset->StationSubmix.IsNull() || Asset->ArchiveFilterChain.Num() == 0)
    {
        return;
    }
    TArray<FSoftObjectPath> Paths;
    Paths.Add(Asset->StationSubmix.ToSoftObjectPath());
    for (const TSoftObjectPtr<USoundEffectSubmixPreset>& P : Asset->ArchiveFilterChain)
    {
        if (!P.IsNull()) Paths.Add(P.ToSoftObjectPath());
    }
    TWeakObjectPtr<USaskartaRadioStation> WeakThis(this);
    FilterHandle = UAssetManager::GetStreamableManager().RequestAsyncLoad(Paths, [WeakThis]()
    {
        USaskartaRadioStation* Self = WeakThis.Get();
        if (!Self || !Self->Asset)
        {
            return;
        }
        TArray<USoundEffectSubmixPreset*> Chain;
        for (const TSoftObjectPtr<USoundEffectSubmixPreset>& P : Self->Asset->ArchiveFilterChain)
        {
            if (USoundEffectSubmixPreset* Preset = P.Get()) Chain.Add(Preset);
        }
        Self->SetArchiveFilter(Self->Asset->StationSubmix.Get(), Chain);
    }, FStreamableManager::DefaultAsyncLoadPriority);
}

void USaskartaRadioStation::BindRunner()
{
    if (Runner.IsValid())
    {
        return;
    }
    UWorld* World = GetWorld();
    USaskartaEventRunner* R = World ? World->GetSubsystem<USaskartaEventRunner>() : nullptr;
    if (R)
    {
        Runner = R;
        R->OnStoryBusyChanged.AddUniqueDynamic(this, &USaskartaRadioStation::HandleStoryBusy);
        R->OnBeatFinished.AddUniqueDynamic(this, &USaskartaRadioStation::HandleBeatFinished);
        R->OnStoryLine.AddUniqueDynamic(this, &USaskartaRadioStation::HandleStoryLine);
        if (USaskartaLightingDirector* Director = World->GetSubsystem<USaskartaLightingDirector>())
        {
            Director->OnLightningStrike.AddUniqueDynamic(this, &USaskartaRadioStation::HandleLightning);
        }
    }
}

void USaskartaRadioStation::SetArchiveFilter(USoundSubmix* Submix, const TArray<USoundEffectSubmixPreset*>& Chain)
{
    if (!Submix)
    {
        return;
    }
    UAudioMixerBlueprintLibrary::SetSubmixEffectChainOverride(this, Submix, Chain, 0.f);
    UE_LOG(LogSaskartaStation, Log, TEXT("Archive filter: %d presets on %s"), Chain.Num(), *Submix->GetName());
}

// ============================================================================ assets (asynchronous only)

bool USaskartaRadioStation::AssetExists(const FString& ObjectPath) const
{
    if (const bool* Cached = ExistsCache.Find(ObjectPath))
    {
        return *Cached;
    }
    IAssetRegistry* AR = IAssetRegistry::Get();
    const bool bExists = AR && AR->GetAssetByObjectPath(FSoftObjectPath(ObjectPath)).IsValid();
    ExistsCache.Add(ObjectPath, bExists);
    return bExists;
}

float USaskartaRadioStation::VoiceLength(int32 SegmentIndex, FName SongId)
{
    if (!Asset || !Asset->Config.Segments.IsValidIndex(SegmentIndex))
    {
        return -1.f;
    }
    const FSaskartaStationSegment& Seg = Asset->Config.Segments[SegmentIndex];
    IAssetRegistry* AR = IAssetRegistry::Get();
    for (const FString& Path : FSaskartaStationLogic::TakeCandidates(Asset->Config.HostFolder, Seg.Id, SongId))
    {
        if (AssetExists(Path))
        {
            const float D = AR ? SaskartaRadio::DurationTag(AR->GetAssetByObjectPath(FSoftObjectPath(Path))) : 0.f;
            return D > 0.f ? D : Seg.TargetS;
        }
    }
    return -1.f;
}

float USaskartaRadioStation::SongLength(FName SongId)
{
    if (!Asset)
    {
        return -1.f;
    }
    const FString Path = FSaskartaStationLogic::SongAssetPath(Asset->Config.SongFolder, SongId);
    if (!AssetExists(Path))
    {
        return -1.f;
    }
    IAssetRegistry* AR = IAssetRegistry::Get();
    const float D = AR ? SaskartaRadio::DurationTag(AR->GetAssetByObjectPath(FSoftObjectPath(Path))) : 0.f;
    return D > 0.f ? D : SaskartaRadio::DefaultSongS;
}

float USaskartaRadioStation::PlayRecall(FName ItemId, bool /*bTuneFirst*/)
{
    StopRecall();
    if (ItemId.IsNone())
    {
        return 0.f;
    }
    USaskartaEventRunner* R = Runner.Get();
    FString Text;
    FName Speaker;
    USoundBase* Sound = nullptr;
    float DurationS = 0.f;
    const int32 Idx = Asset ? Show.SegmentIndexOf(ItemId) : INDEX_NONE;
    const FString RecallId = ItemId.ToString();
    if (Asset && RecallId.StartsWith(TEXT("SONG_")))
    {
        const FName SongId(*RecallId.RightChop(5));
        // Songs remain on the station mix and carry no subtitle credit label.
        const FString Path = ResolveSongPath(SongId);
        if (!Path.IsEmpty())
        {
            Sound = GetResidentSound(Path, true);
            if (!Sound) Sound = Cast<USoundBase>(FSoftObjectPath(Path).TryLoad());
        }
    }
    else if (Asset && Asset->Config.Segments.IsValidIndex(Idx))
    {
        const FSaskartaStationSegment& Seg = Asset->Config.Segments[Idx];
        Text = Seg.Text;
        Speaker = Seg.Speaker;
        DurationS = Seg.TargetS;
        const FString Path = ResolveTakePath(Idx, NAME_None);
        if (!Path.IsEmpty())
        {
            Sound = GetResidentSound(Path, true);
            if (!Sound)
            {
                // Explicit narrative replay can resolve its selected take here.
                Sound = Cast<USoundBase>(FSoftObjectPath(Path).TryLoad());
            }
        }
    }
    else if (R)
    {
        Sound = R->ResolveLineSound(ItemId, Text, Speaker);
    }
    if (!Sound && Text.IsEmpty())
    {
        return 0.f;
    }
    if (Sound)
    {
        const float D = Sound->GetDuration();
        if (D > 0.f && D < 3600.f)
        {
            DurationS = D;
        }
        RecallComp = UGameplayStatics::CreateSound2D(this, Sound, USaskartaStorySettings::Get()->StationVolume, 1.f, 0.f, nullptr, false, true);
        if (RecallComp)
        {
            RecallComp->Play();
        }
    }
    DurationS = FMath::Max(DurationS, 1.5f);
    SetUnderVoice(true);
    if (R && !Text.IsEmpty())
    {
        FSaskartaSubtitle Sub;
        Sub.English = FText::FromString(Text);
        Sub.DurationS = DurationS;
        Sub.bStation = true;
        Sub.LineId = ItemId;
        Sub.Speaker = Speaker;
        R->ShowStationSubtitle(Sub);
    }
    const float TotalS = DurationS;
    RecallEndS = Now() + TotalS;
    if (UWorld* World = GetWorld())
    {
        World->GetTimerManager().SetTimer(RecallTimer, this, &USaskartaRadioStation::StopRecall, TotalS, false);
    }
    return TotalS;
}

void USaskartaRadioStation::StopRecall()
{
    if (IsValid(RecallComp))
    {
        if (RecallComp->IsPlaying())
        {
            RecallComp->FadeOut(0.3f, 0.f);
        }
    }
    RecallComp = nullptr;
    if (RecallEndS >= 0.0)
    {
        RecallEndS = -1.0;
        SetUnderVoice(false);
        if (UWorld* World = GetWorld())
        {
            World->GetTimerManager().ClearTimer(RecallTimer);
        }
    }
}

FString USaskartaRadioStation::ResolveTakePath(int32 SegmentIndex, FName SongId) const
{
    if (!Asset || !Asset->Config.Segments.IsValidIndex(SegmentIndex))
    {
        return FString();
    }
    for (const FString& Path : FSaskartaStationLogic::TakeCandidates(Asset->Config.HostFolder, Asset->Config.Segments[SegmentIndex].Id, SongId))
    {
        if (AssetExists(Path))
        {
            return Path;
        }
    }
    return FString();
}

FString USaskartaRadioStation::ResolveSongPath(FName SongId) const
{
    if (!Asset || SongId.IsNone())
    {
        return FString();
    }
    const FString Path = FSaskartaStationLogic::SongAssetPath(Asset->Config.SongFolder, SongId);
    return AssetExists(Path) ? Path : FString();
}

FString USaskartaRadioStation::ResolveLastSongPath() const
{
    if (!Asset)
    {
        return FString();
    }
    const FString Id = Asset->Config.Show.LastSong.TrimStartAndEnd();
    if (Id.IsEmpty())
    {
        return FString();
    }
    // Never one of the shelf's songs (Hayaa, Malak, Weli): the last song is the author's own.
    for (const FSaskartaStationSong& S : Asset->Config.Songs)
    {
        if (S.Id.ToString().Equals(Id, ESearchCase::IgnoreCase))
        {
            UE_LOG(LogSaskartaStation, Warning, TEXT("show.last_song '%s' is a shelf song; it is ignored (the last song must be the author's own)."), *Id);
            return FString();
        }
    }
    FString Path;
    if (Id.Contains(TEXT("/")))
    {
        Path = Id.Contains(TEXT(".")) ? Id : Id + TEXT(".") + FPaths::GetBaseFilename(Id);
    }
    else
    {
        Path = FSaskartaStationLogic::SongAssetPath(Asset->Config.SongFolder, FName(*Id));
    }
    return AssetExists(Path) ? Path : FString();
}

void USaskartaRadioStation::RequestLoad(const FString& ObjectPath, bool bHighPriority)
{
    if (ObjectPath.IsEmpty() || Loads.Contains(ObjectPath))
    {
        return;
    }
    const TSharedPtr<FStreamableHandle> H = UAssetManager::GetStreamableManager().RequestAsyncLoad(
        TArray<FSoftObjectPath>{ FSoftObjectPath(ObjectPath) }, FStreamableDelegate(),
        bHighPriority ? FStreamableManager::AsyncLoadHighPriority : FStreamableManager::DefaultAsyncLoadPriority);
    Loads.Add(ObjectPath, H);
    Prefetch.Touch(ObjectPath, Now());
}

void USaskartaRadioStation::ReleaseLoad(const FString& ObjectPath)
{
    if (TSharedPtr<FStreamableHandle>* H = Loads.Find(ObjectPath))
    {
        if (H->IsValid())
        {
            if ((*H)->IsLoadingInProgress()) (*H)->CancelHandle();
            else (*H)->ReleaseHandle();
        }
        Loads.Remove(ObjectPath);
    }
    Prefetch.Forget(ObjectPath);
}

USoundBase* USaskartaRadioStation::GetResidentSound(const FString& ObjectPath, bool bRequestIfMissing)
{
    if (ObjectPath.IsEmpty())
    {
        return nullptr;
    }
    if (const TSharedPtr<FStreamableHandle>* H = Loads.Find(ObjectPath))
    {
        if (H->IsValid() && (*H)->HasLoadCompleted())
        {
            if (USoundBase* S = Cast<USoundBase>((*H)->GetLoadedAsset())) return S;
        }
    }
    // Already in memory (another system loaded it): use it and keep it with a handle. Not a load.
    if (USoundBase* InMemory = Cast<USoundBase>(FSoftObjectPath(ObjectPath).ResolveObject()))
    {
        if (!Loads.Contains(ObjectPath)) RequestLoad(ObjectPath, false);
        return InMemory;
    }
    if (bRequestIfMissing)
    {
        RequestLoad(ObjectPath, true);
    }
    return nullptr;
}

void USaskartaRadioStation::PickPaths(const FSaskartaStationPick& Pick, TArray<FString>& Out) const
{
    for (const FSaskartaStationPart& P : Pick.Parts)
    {
        const FString Path = P.Kind == FSaskartaStationPart::EKind::Voice ? ResolveTakePath(P.SegmentIndex, P.SongId)
            : P.Kind == FSaskartaStationPart::EKind::Song ? ResolveSongPath(P.SongId) : FString();
        if (!Path.IsEmpty()) Out.AddUnique(Path);
    }
}

void USaskartaRadioStation::UpdatePrefetch(bool bForce)
{
    const double T = Now();
    if (!Asset || (!bForce && T - LastPrefetchS < SaskartaRadio::PrefetchIntervalS))
    {
        return;
    }
    LastPrefetchS = T;
    TSet<FString> Pinned = PinnedPaths;
    TArray<FString> Playing;
    PickPaths(CurrentPick, Playing);
    PickPaths(InterruptedPick, Playing);
    Pinned.Append(Playing);
    if (bSignalDeath)
    {
        Pinned.Add(ResolveLastSongPath());
        if (!Asset->Config.Show.TitleSong.IsNull()) Pinned.Add(Asset->Config.Show.TitleSong.ToString());
    }
    Pinned.Remove(FString());

    TArray<FString> Desired;
    if (bShowMode && !bSignalDeath && Mode == ESaskartaStationMode::On)
    {
        auto AddVoice = [this, &Desired](FName Id, FName Song)
        {
            const int32 Idx = Show.SegmentIndexOf(Id);
            const FString P = Idx != INDEX_NONE ? ResolveTakePath(Idx, Song) : FString();
            if (!P.IsEmpty()) Desired.AddUnique(P);
        };
        // 1. The window: the next backbone items, the MUSTs, the next opening, a fill, a linger line, the song block.
        const FSaskartaShowUpcoming Up = Show.GetUpcoming(SaskartaRadio::PrefetchBackbone);
        for (const FSaskartaShowVoiceRef& V : Up.Voices) AddVoice(V.Id, V.SongId);
        for (const FName& Song : Up.Songs)
        {
            const FString P = ResolveSongPath(Song);
            if (!P.IsEmpty()) Desired.AddUnique(P);
        }
        // 2. The act's reactions (small takes), then the room murmurs.
        TArray<FName> Reacts;
        Show.GetActReactionLines(Show.GetAct(), Reacts);
        for (const FName& Id : Reacts) AddVoice(Id, NAME_None);
        for (const FName& Id : Show.GetRoomIds()) AddVoice(Id, NAME_None);
        // 3. The end: the last song and the title song, from Act V.
        if (Show.GetAct() >= Show.NumActs())
        {
            const FString Last = ResolveLastSongPath();
            if (!Last.IsEmpty()) Desired.AddUnique(Last);
            if (!Asset->Config.Show.TitleSong.IsNull()) Desired.AddUnique(Asset->Config.Show.TitleSong.ToString());
        }
    }
    TArray<FString> ToLoad, ToRelease;
    Prefetch.Plan(Desired, Pinned, T, ToLoad, ToRelease);
    for (const FString& P : ToRelease)
    {
        if (!Pinned.Contains(P)) ReleaseLoad(P);
    }
    for (const FString& P : ToLoad)
    {
        RequestLoad(P, false);
    }
}

void USaskartaRadioStation::ScanAvailability()
{
    const double T = Now();
    if (!Asset || T - LastScanS < SaskartaRadio::ScanIntervalS)
    {
        return;
    }
    LastScanS = T;
    ExistsCache.Reset();
    TArray<FName> Songs;
    for (const FSaskartaStationSong& S : Asset->Config.Songs)
    {
        if (AssetExists(FSaskartaStationLogic::SongAssetPath(Asset->Config.SongFolder, S.Id))) Songs.AddUnique(S.Id);
    }
    // Any SONG_<id> dropped into the folder is picked up too (STATION.md section 8), except the show's last song.
    const FString LastSong = Asset->Config.Show.LastSong.TrimStartAndEnd();
    if (IAssetRegistry* AR = IAssetRegistry::Get())
    {
        TArray<FAssetData> Found;
        AR->GetAssetsByPath(FName(*Asset->Config.SongFolder), Found, false);
        for (const FAssetData& D : Found)
        {
            FString Name = D.AssetName.ToString();
            if (Name.RemoveFromStart(TEXT("SONG_")) && !(LastSong.Len() > 0 && Name.Equals(LastSong, ESearchCase::IgnoreCase)))
            {
                Songs.AddUnique(FName(*Name));
            }
        }
    }
    AvailableSongs = Songs;
    Show.SetAvailableSongs(AvailableSongs);
}

void USaskartaRadioStation::CheckRecordingsOnDisk() const
{
#if WITH_EDITOR
    if (!Asset)
    {
        return;
    }
    const FString Selected = FPaths::Combine(FPaths::ProjectSavedDir(), TEXT("RadioRecordings/selected"));
    const FString Raw = FPaths::Combine(FPaths::ProjectSavedDir(), TEXT("RadioRecordings/raw"));
    FString ManifestJson;
    FFileHelper::LoadFileToString(ManifestJson, *FPaths::Combine(Selected, TEXT("_tts_manifest.json")));
    const TSet<FName> Tts = FSaskartaStationLogic::ParseTtsManifest(ManifestJson);
    int32 User = 0, Placeholder = 0, Missing = 0, NotImported = 0;
    for (const FSaskartaStationSegment& S : Asset->Config.Segments)
    {
        const FString Id = S.Id.ToString();
        const bool bSelected = IFileManager::Get().FileExists(*FPaths::Combine(Selected, Id + TEXT(".wav")));
        TArray<FString> RawTakes;
        IFileManager::Get().FindFiles(RawTakes, *FPaths::Combine(Raw, Id + TEXT("_take*.wav")), true, false);
        switch (FSaskartaStationLogic::ClassifyTake(S.Id, Tts, bSelected, RawTakes.Num() > 0))
        {
        case FSaskartaStationLogic::ETakeSource::User:
        {
            ++User;
            const TArray<FString> Candidates = FSaskartaStationLogic::TakeCandidates(Asset->Config.HostFolder, S.Id, NAME_None);
            const FString Resolved = FSaskartaStationLogic::FirstExistingTakeCandidate(Candidates,
                [this](const FString& Path) { return AssetExists(Path); });
            if (Resolved.IsEmpty())
            {
                ++NotImported;
                UE_LOG(LogSaskartaStation, Warning, TEXT("%s: your recording is on disk but none of its runtime take paths are imported: %s (the TTS take plays until one is)"),
                    *Id, *FString::Join(Candidates, TEXT(", ")));
            }
            break;
        }
        case FSaskartaStationLogic::ETakeSource::Tts: ++Placeholder; break;
        default: ++Missing; break;
        }
    }
    UE_LOG(LogSaskartaStation, Log, TEXT("Station takes on disk: %d yours, %d TTS placeholders, %d missing; %d of yours not imported"),
        User, Placeholder, Missing, NotImported);
#endif
}

// ============================================================================ the loop

void USaskartaRadioStation::Update()
{
    const double T = Now();
    const double Dt = LastUpdateS < 0.0 ? 0.0 : T - LastUpdateS;
    LastUpdateS = T;
    UpdateBoostInterference(T); // also clears our layer before pause/death early returns
    if (!Asset || bMenuPaused)
    {
        return;
    }
    RefreshEndingMusicVolume();
    if (bSignalDeath)
    {
        // The show is over: the coda runs on its own timers; only the resident set is kept tidy.
        UpdatePrefetch();
        return;
    }
    BindRunner();
    const FSaskartaStationConfig& C = Asset->Config;
    USaskartaEventRunner* R = Runner.Get();
    const FName Flow = R ? R->GetFlowState() : NAME_None;
    // The boot handover starts the show. Recover its completion if DA_Station loaded
    // after the delegate fired; never start under the still-running boot cinematic.
    const bool bStartBeatFinished = R && C.PlayFlowStates.Contains(Flow) && R->HasBeatFired(C.StartEvent)
        && R->GetRunningBeatId() != C.StartEvent && !R->IsCinematicActive();
    if (!bStarted && R && (bStartBeatFinished || FSaskartaStationLogic::MayStartAtRoad(C, Flow, R->GetRoadM())))
    {
        bStarted = true;
    }
    const USaskartaStorySettings* Settings = USaskartaStorySettings::Get();
    Mode = FSaskartaStationLogic::ModeFor(Flow, bStarted, Settings->bRadioStation && !bRadioPowerCut, bStoppedForGood, C);
    if (Mode == ESaskartaStationMode::Stopped && !bStoppedForGood)
    {
        bStoppedForGood = true;
        UE_LOG(LogSaskartaStation, Log, TEXT("Station off for good (FlowState %s)"), *Flow.ToString());
    }

    // CPPBATCH: the archive force (runs whatever the mode: the player's radio may be off) and the imperfections.
    ApplyStoryStep(StoryState.Tick(T));
    UpdateGlitches(T);

    if (Mode != ESaskartaStationMode::On || bIdle)
    {
        if (Phase != ESaskartaStationPhase::Silent)
        {
            if (Phase == ESaskartaStationPhase::Playing)
            {
                InterruptSlot(false, bShowMode);
            }
            FadeOutAll(C.FadeOutS, true);
            Phase = ESaskartaStationPhase::Silent;
            // A hold comes back at once with the tune sweep; an idle tape sets its own delay on NotifyIdle(false).
            if (!bIdle)
            {
                NextActionAtS = 0.0;
            }
            UE_LOG(LogSaskartaStation, Log, TEXT("Station silent (mode %d, idle %d)"), static_cast<int32>(Mode), bIdle ? 1 : 0);
        }
        UpdatePrefetch();
        return;
    }
    if (Phase == ESaskartaStationPhase::Silent)
    {
        if (T >= NextActionAtS)
        {
            TuneIn();
        }
        return;
    }
    if (bSuspended)
    {
        return;
    }

    Scheduler.CurrentRoadM = R ? FMath::Max(0.f, R->GetRoadM()) : 0.f;
    Scheduler.CurrentQuality = Quality;
    Scheduler.CurrentZone = FSaskartaStationLogic::ZoneAt(C.Zones, Scheduler.CurrentRoadM);
    Scheduler.Clock.Advance(Dt, true);
    ScanAvailability();
    if (!BedComp)
    {
        // The static bed was still loading at the tune-in: it comes in now.
        if (USoundBase* Bed = GetResidentSoundAt(C.StaticBed))
        {
            BedComp = UGameplayStatics::CreateSound2D(this, Bed, Settings->StationVolume, 1.f, 0.f, nullptr, false, false);
            if (BedComp) BedComp->FadeIn(1.f, 1.f);
        }
    }
    ApplyReception();
    if (bShowMode)
    {
        UpdateShowEvents(T);
        Show.Update(MakeShowInput(true, 1.0e6f));
    }
    UpdatePrefetch();

    if (Phase == ESaskartaStationPhase::Waiting && T >= NextActionAtS && !bHeldForStory)
    {
        TryStartSlot();
    }
    else if (Phase == ESaskartaStationPhase::Playing && CurrentPart != INDEX_NONE)
    {
        // Dropouts now come from the imperfection scheduler (UpdateGlitches), not MaybeDropout.
        if (bPartWaitingLoad)
        {
            StartPart(CurrentPart, PendingStartAtS); // loaded now, or its deadline has passed
        }
        else
        {
            // RADIOSHOW: the next part may start before this one ends (a song under its intro, an outro over the tail).
            const float Lead = CurrentPick.Parts.IsValidIndex(CurrentPart + 1) ? CurrentPick.Parts[CurrentPart + 1].OverlapPrevS : 0.f;
            if (T >= PartEndS - Lead)
            {
                StartPart(CurrentPart + 1);
            }
        }
    }
}

void USaskartaRadioStation::TuneIn()
{
    const FSaskartaStationConfig& C = Asset->Config;
    const float Vol = USaskartaStorySettings::Get()->StationVolume;
    if (USoundBase* Sweep = GetResidentSoundAt(C.TuneSweep))
    {
        UGameplayStatics::PlaySound2D(this, Sweep, Vol);
    }
    if (USoundBase* Bed = GetResidentSoundAt(C.StaticBed))
    {
        if (!BedComp)
        {
            BedComp = UGameplayStatics::CreateSound2D(this, Bed, Vol, 1.f, 0.f, nullptr, false, false);
        }
        if (BedComp)
        {
            BedComp->FadeIn(1.f, 1.f);
        }
    }
    Phase = ESaskartaStationPhase::Waiting;
    // The show is already in progress: the first item comes after 1.5-3 s (the shuffle loop waits its first delay).
    NextActionAtS = Now() + (bShowMode ? Show.DrawFirstDelayS() : Scheduler.DrawFirstDelayS());
    QuietSinceS = Now();
    bSilenceFired = false;
    UE_LOG(LogSaskartaStation, Log, TEXT("Station on: first %s in %.1f s"), bShowMode ? TEXT("show item") : TEXT("segment"), NextActionAtS - Now());
}

FSaskartaShowInput USaskartaRadioStation::MakeShowInput(bool bGateOpen, float MaxFitS) const
{
    const USaskartaEventRunner* R = Runner.Get();
    FSaskartaShowInput In;
    In.NowS = ShowNow();
    In.RoadM = R ? FMath::Max(0.f, R->GetRoadM()) : 0.f;
    In.SpeedMps = R ? R->GetSpeedMps() : 0.f;
    In.bGateOpen = bGateOpen;
    In.MaxFitS = MaxFitS;
    if (Asset)
    {
        In.SecondsToCollapse = (Asset->Config.Show.CollapseRoadM - In.RoadM) / FMath::Max(In.SpeedMps, Asset->Config.MinSpeedMps);
    }
    return In;
}

void USaskartaRadioStation::TryStartSlot()
{
    if (bShowMode)
    {
        TryStartShowItem();
        return;
    }
    const FSaskartaStationConfig& C = Asset->Config;
    USaskartaEventRunner* R = Runner.Get();
    FSaskartaStationGateInput In;
    In.bIdle = bIdle;
    In.bStoryBusy = R && R->IsStationVoiceBusy();
    In.SecondsSinceStory = R ? R->SecondsSinceStationVoice() : 1000.f;
    In.SecondsToNextBeat = R ? R->GetSecondsToNextBeat() : 1.0e6f;
    In.RoadM = R ? R->GetRoadM() : 0.f;
    const ESaskartaStationGate Gate = FSaskartaStationLogic::EvaluateGate(In, 0.f, C);
    if (Gate != ESaskartaStationGate::Open)
    {
        NextActionAtS = Now() + C.RetryS;
        return;
    }
    const FSaskartaStationPick Pick = Scheduler.PickSlot(FSaskartaStationLogic::MaxFitS(In, C), AvailableSongs,
        [this](int32 Seg, FName Song) { return VoiceLength(Seg, Song); },
        [this](FName Song) { return SongLength(Song); });
    if (!Pick.bValid)
    {
        if (!bLoggedNoTakes)
        {
            bLoggedNoTakes = true;
            UE_LOG(LogSaskartaStation, Log, TEXT("No drawable segment (takes not imported under %s, or none fits before the next beat); retrying every %.0f s"),
                *C.HostFolder, C.RetryS);
        }
        NextActionAtS = Now() + C.RetryS;
        return;
    }
    Scheduler.CommitPick(Pick);
    CurrentPick = Pick;
    CurrentShowPick = FSaskartaShowPick();
    Phase = ESaskartaStationPhase::Playing;
    CurrentPart = INDEX_NONE;
    PartEndS = Now();
    // The takes load now (asynchronously); StartPart waits briefly for each.
    TArray<FString> Paths;
    PickPaths(Pick, Paths);
    for (const FString& P : Paths) RequestLoad(P, true);
    if (USoundBase* In2 = GetResidentSoundAt(C.StaticIn))
    {
        UGameplayStatics::PlaySound2D(this, In2, USaskartaStorySettings::Get()->StationVolume);
    }
    UE_LOG(LogSaskartaStation, Log, TEXT("slot: %s%s (%.1f s)"), *Pick.Category.ToString(), Pick.bSongBlock ? TEXT(" song block") : TEXT(""), Pick.TotalS);
    StartPart(0);
}

void USaskartaRadioStation::TryStartShowItem()
{
    const FSaskartaStationConfig& C = Asset->Config;
    USaskartaEventRunner* R = Runner.Get();
    FSaskartaStationGateInput G;
    G.bIdle = bIdle;
    G.bStoryBusy = R && R->IsStationVoiceBusy();
    G.SecondsSinceStory = R ? R->SecondsSinceStationVoice() : 1000.f;
    G.SecondsToNextBeat = R ? R->GetSecondsToNextBeat() : 1.0e6f;
    G.RoadM = R ? R->GetRoadM() : 0.f;
    const ESaskartaStationGate Gate = FSaskartaStationLogic::EvaluateGate(G, 0.f, C);
    // The show's gate: nothing starts during a story line or its hold-off; near a beat only the sign-off may start.
    const bool bGateOpen = Gate == ESaskartaStationGate::Open || Gate == ESaskartaStationGate::BeatTooClose;
    const float MaxFit = Gate == ESaskartaStationGate::BeatTooClose ? 0.f : FSaskartaStationLogic::MaxFitS(G, C);
    const FSaskartaShowPick P = Show.PickNext(MakeShowInput(bGateOpen, MaxFit),
        [this](int32 Seg, FName Song)
        {
            // A missing take still plays, as a subtitle, for its target length.
            const float L = VoiceLength(Seg, Song);
            return L >= 0.f ? L : (Asset && Asset->Config.Segments.IsValidIndex(Seg) ? Asset->Config.Segments[Seg].TargetS : -1.f);
        },
        [this](FName Song) { return SongLength(Song); });
    if (!P.bValid)
    {
        NextActionAtS = Now() + FMath::Clamp(P.RetryS, SaskartaRadio::UpdateS, 5.f);
        return;
    }
    Show.Commit(P, ShowNow());
    CurrentShowPick = P;
    CurrentPick = P.Slot;
    Phase = ESaskartaStationPhase::Playing;
    CurrentPart = INDEX_NONE;
    PartEndS = Now();
    bSilenceFired = false;
    TArray<FString> Paths;
    PickPaths(CurrentPick, Paths);
    for (const FString& Path : Paths) RequestLoad(Path, true);
    UE_LOG(LogSaskartaStation, Log, TEXT("show: act %d %s %s%s%s (%.1f s)"), Show.GetAct(), *CurrentPick.Category.ToString(), *P.Id.ToString(),
        P.SongId.IsNone() ? TEXT("") : *FString::Printf(TEXT(" [%s + SONG_%s + %s]"), *P.IntroId.ToString(), *P.SongId.ToString(), *P.OutroId.ToString()),
        P.Event.IsNone() ? TEXT("") : *FString::Printf(TEXT(" (reacting to %s)"), *P.Event.ToString()), P.Slot.TotalS);
    StartPart(0, CurrentPick.Parts.IsValidIndex(0) ? CurrentPick.Parts[0].StartAtS : 0.f);
}

void USaskartaRadioStation::StartPart(int32 PartIndex, float StartAtS)
{
    USaskartaEventRunner* R = Runner.Get();
    if (!CurrentPick.Parts.IsValidIndex(PartIndex))
    {
        if (R) R->HideStationSubtitle();
        FinishSlot();
        return;
    }
    const double T = Now();
    const FSaskartaStationPart& P = CurrentPick.Parts[PartIndex];
    const float StartAt = StartAtS > 0.f ? StartAtS : P.StartAtS;
    if (P.Kind == FSaskartaStationPart::EKind::Static)
    {
        if (R) R->HideStationSubtitle();
        CurrentPart = PartIndex;
        PartStartS = T;
        PartEndS = T + P.DurationS;
        bPartWaitingLoad = false;
        return;
    }
    // The sound: resident, or still loading (wait briefly), or missing.
    const FString Path = P.Kind == FSaskartaStationPart::EKind::Voice ? ResolveTakePath(P.SegmentIndex, P.SongId) : ResolveSongPath(P.SongId);
    USoundBase* Sound = GetResidentSound(Path, true);
    if (!Sound && !Path.IsEmpty())
    {
        if (!bPartWaitingLoad || CurrentPart != PartIndex)
        {
            bPartWaitingLoad = true;
            CurrentPart = PartIndex;
            PendingStartAtS = StartAt;
            PartLoadDeadlineS = T + (P.Kind == FSaskartaStationPart::EKind::Song ? SaskartaRadio::SongLoadWaitS : SaskartaRadio::VoiceLoadWaitS);
            PartEndS = T + 3600.0; // Update retries this part until the sound arrives or the deadline passes
            return;
        }
        if (T < PartLoadDeadlineS)
        {
            return;
        }
    }
    bPartWaitingLoad = false;
    const bool bPrevWasSong = CurrentPick.Parts.IsValidIndex(PartIndex - 1) && CurrentPick.Parts[PartIndex - 1].Kind == FSaskartaStationPart::EKind::Song;
    const bool bOverlap = P.OverlapPrevS > 0.f && PartComp && PartComp->IsPlaying() && PartIndex > 0;
    CurrentPart = PartIndex;
    // A resumed song starts StartAt in: its start is set back so heard / remaining times stay right.
    PartStartS = T - FMath::Max(0.f, StartAt);
    float CaptionOffsetS = FMath::Max(0.f, StartAt);
    // A song clears the spoken subtitle even when its intro still overlaps in audio.
    const bool bSongUnderIntro = bOverlap && P.Kind == FSaskartaStationPart::EKind::Song;
    if (R)
    {
        R->HideStationSubtitle();
    }
    if (bOverlap)
    {
        // The previous part finishes under this one.
        if (TailComp && TailComp->IsPlaying()) TailComp->Stop();
        TailComp = PartComp;
        PartComp = nullptr;
        if (bPrevWasSong && TailComp)
        {
            TailComp->AdjustVolume(0.5f, FSaskartaStationLogic::DbToLinear(SaskartaRadio::TailDuckDb));
        }
    }
    else if (PartComp && PartComp->IsPlaying())
    {
        PartComp->Stop();
    }
    if (!Sound)
    {
        if (P.Kind == FSaskartaStationPart::EKind::Song)
        {
            UE_LOG(LogSaskartaStation, Log, TEXT("SONG_%s not loaded in time (or missing): skipped"), *P.SongId.ToString());
            PartEndS = T; // skip the song
            return;
        }
        // The take is missing, or did not load in time: the line plays as a subtitle only, for its length. Never a hitch.
        const FName LineId = Asset->Config.Segments.IsValidIndex(P.SegmentIndex) ? Asset->Config.Segments[P.SegmentIndex].Id : NAME_None;
        if (!SubtitleOnlyLogged.Contains(LineId))
        {
            SubtitleOnlyLogged.Add(LineId);
            UE_LOG(LogSaskartaStation, Log, TEXT("%s: %s; subtitle only"), *LineId.ToString(), Path.IsEmpty() ? TEXT("no take imported") : TEXT("take not loaded in time"));
        }
        PartEndS = PartStartS + FMath::Max(0.5f, P.DurationS);
    }
    else
    {
        PartComp = UGameplayStatics::CreateSound2D(this, Sound, USaskartaStorySettings::Get()->StationVolume, 1.f, 0.f, nullptr, false, true);
        float Dur = Sound->GetDuration();
        if (!(Dur > 0.f && Dur < 3600.f))
        {
            Dur = P.DurationS;
        }
        const float Offset = FMath::Clamp(StartAt, 0.f, FMath::Max(0.f, Dur - 0.5f));
        CaptionOffsetS = Offset;
        PartEndS = PartStartS + Dur;
        bDucked = false;
        NextDropoutAtS = -1.0;
        ApplyReception();
        if (PartComp)
        {
            ProgrammeEnvelope = 0.f;
            ProgrammeEnvelopeAtS = -1.0;
            PartComp->EnvelopeFollowerAttackTime = 10;
            PartComp->EnvelopeFollowerReleaseTime = 100;
            PartComp->OnAudioSingleEnvelopeValueNative.AddUObject(this, &USaskartaRadioStation::HandleProgrammeEnvelope);
            PartComp->Play(Offset);
            if (bShowMode && P.Kind == FSaskartaStationPart::EKind::Song && PartComp->IsPlaying())
            {
                Show.NotifySongPlaybackStarted(P.SongId, Dur - Offset, ShowNow());
            }
            if (bSongUnderIntro && Asset)
            {
                // The song comes in under its intro, then rises to full after the intro ends.
                const FSaskartaShowConfig& SC = Asset->Config.Show;
                PartComp->AdjustVolume(0.f, FSaskartaStationLogic::DbToLinear(SC.SongIntroUnderDb));
                TWeakObjectPtr<UAudioComponent> Weak = PartComp;
                const float RiseS = SC.SongIntroRiseS;
                if (UWorld* World = GetWorld())
                {
                    World->GetTimerManager().SetTimer(SongRiseTimer, FTimerDelegate::CreateWeakLambda(this, [Weak, RiseS]()
                    {
                        if (UAudioComponent* A = Weak.Get()) A->AdjustVolume(RiseS, 1.f);
                    }), FMath::Max(0.05f, P.OverlapPrevS), false);
                }
            }
        }
    }
    if (R && P.Kind == FSaskartaStationPart::EKind::Voice)
    {
        FSaskartaSubtitle Sub;
        const FString Caption = CaptionFor(P);
        Sub.English = FText::FromString(Caption);
        Sub.DurationS = FMath::Max(0.5f, static_cast<float>(PartEndS - PartStartS));
        Sub.StartOffsetS = CaptionOffsetS;
        Sub.bStation = true;
        if (Asset->Config.Segments.IsValidIndex(P.SegmentIndex))
        {
            const FSaskartaStationSegment& Segment = Asset->Config.Segments[P.SegmentIndex];
            Sub.LineId = Segment.Id;
            Sub.Speaker = Segment.Speaker;
            FString Plain = Caption;
            const FString& Prefix = Asset->Config.CaptionPrefix;
            if (!Prefix.IsEmpty() && Plain.StartsWith(Prefix))
            {
                Plain.RightChopInline(Prefix.Len());
            }
            Sub.Pages = FSaskartaCaptionPaging::Resolve(Segment.CaptionPages, Plain, FString(), Sub.DurationS);
            FSaskartaCaptionPaging::AddPrefix(Sub.Pages, Prefix);
        }
        R->ShowStationSubtitle(Sub);
    }
}

FString USaskartaRadioStation::CaptionFor(const FSaskartaStationPart& P) const
{
    const FSaskartaStationConfig& C = Asset->Config;
    const FSaskartaStationSong* Song = C.Songs.FindByPredicate([&P](const FSaskartaStationSong& S) { return S.Id == P.SongId; });
    if (P.Kind == FSaskartaStationPart::EKind::Song)
    {
        return FString(); // Song metadata belongs to the radio panel, never the subtitle lane.
    }
    if (!C.Segments.IsValidIndex(P.SegmentIndex))
    {
        return FString();
    }
    const FSaskartaStationSegment& Seg = C.Segments[P.SegmentIndex];
    TMap<FString, FString> Values;
    if (Song)
    {
        Values.Add(TEXT("SONG"), Song->Title);
        Values.Add(TEXT("SINGER"), Song->Singer);
    }
    // Plain takes read the plain text; a named pickup reads the filled template.
    bool bNamed = false;
    if (!P.SongId.IsNone())
    {
        const TArray<FString> Candidates = FSaskartaStationLogic::TakeCandidates(C.HostFolder, Seg.Id, P.SongId);
        bNamed = AssetExists(Candidates[0]) || AssetExists(Candidates[1]);
    }
    const FString Text = bNamed ? FSaskartaStationLogic::FillTemplate(Seg.Template, Seg.Text, Values) : Seg.Text;
    return C.CaptionPrefix + Text;
}

void USaskartaRadioStation::FinishSlot()
{
    const FSaskartaStationConfig& C = Asset->Config;
    if (USaskartaEventRunner* R = Runner.Get())
    {
        R->HideStationSubtitle();
    }
    float GapS = 0.f;
    bool bFinal = false;
    if (bShowMode)
    {
        // A live host: no static between items.
        Show.MarkFinished(CurrentShowPick, ShowNow());
        GapS = Show.DrawGapAfter(CurrentShowPick);
        bFinal = CurrentShowPick.bFinal;
    }
    else
    {
        if (USoundBase* Out = GetResidentSoundAt(C.StaticOut))
        {
            UGameplayStatics::PlaySound2D(this, Out, USaskartaStorySettings::Get()->StationVolume);
        }
        GapS = Scheduler.DrawGapAfter(CurrentPick);
    }
    CurrentPart = INDEX_NONE;
    CurrentPick = FSaskartaStationPick();
    CurrentShowPick = FSaskartaShowPick();
    bPartWaitingLoad = false;
    Phase = ESaskartaStationPhase::Waiting;
    NextActionAtS = Now() + GapS;
    QuietSinceS = Now();
    bSilenceFired = false;
    if (bFinal)
    {
        BeginSignalDeath();
    }
}

float USaskartaRadioStation::HeardFraction() const
{
    const double Total = PartEndS - PartStartS;
    if (bPartWaitingLoad || Total <= 0.0)
    {
        return 0.f;
    }
    return FMath::Clamp(static_cast<float>((Now() - PartStartS) / Total), 0.f, 1.f);
}

void USaskartaRadioStation::ReturnShowPick()
{
    if (!bShowMode || !CurrentShowPick.bValid || !CurrentPick.Parts.IsValidIndex(CurrentPart))
    {
        return;
    }
    if (CurrentPick.bSongBlock)
    {
        // Cut in the intro: the slot comes back if under half heard. Once the song has begun the block counts as played
        // (a cut song resumes from its position).
        if (CurrentPart == 0 && CurrentPick.Parts[0].Kind == FSaskartaStationPart::EKind::Voice)
        {
            Show.ReturnInterrupted(CurrentShowPick, HeardFraction(), ShowNow());
        }
        return;
    }
    Show.ReturnInterrupted(CurrentShowPick, HeardFraction(), ShowNow());
}

void USaskartaRadioStation::StopComp(UAudioComponent* Comp, float FadeS)
{
    if (Comp && Comp->IsPlaying())
    {
        if (FadeS > 0.f) Comp->FadeOut(FadeS, 0.f);
        else Comp->Stop();
    }
}

void USaskartaRadioStation::InterruptSlot(bool bDuckFirst, bool bResumeSongAfterStory)
{
    if (Phase != ESaskartaStationPhase::Playing)
    {
        return;
    }
    const FSaskartaStationConfig& C = Asset->Config;
    const double T = Now();
    if (bResumeSongAfterStory && bShowMode && !bPartWaitingLoad && CurrentPick.Parts.IsValidIndex(CurrentPart)
        && CurrentPick.Parts[CurrentPart].Kind == FSaskartaStationPart::EKind::Song)
    {
        const FSaskartaStationPart& Song = CurrentPick.Parts[CurrentPart];
        Show.RememberInterruptedSong(Song.SongId, static_cast<float>(T - PartStartS), CurrentShowPick.OutroId);
    }
    if (bShowMode)
    {
        ReturnShowPick();
    }
    // A segment heard under half goes back in its bag; otherwise it counts as played.
    else if (!CurrentPick.bSongBlock && CurrentPick.Parts.IsValidIndex(CurrentPart))
    {
        const FSaskartaStationPart& P = CurrentPick.Parts[CurrentPart];
        const float Heard = static_cast<float>(T - PartStartS);
        const float Total = static_cast<float>(PartEndS - PartStartS);
        if (!FSaskartaStationLogic::CountsAsPlayed(Heard, Total, C.ReturnToBagIfHeardBelow))
        {
            Scheduler.ReturnSegment(P.SegmentIndex);
        }
    }
    StopComp(TailComp, C.FadeOutS * 0.5f);
    if (PartComp && PartComp->IsPlaying())
    {
        if (bDuckFirst)
        {
            // -12 dB over 0.3 s so the story line is heard at once, then out over 1 s.
            PartComp->AdjustVolume(C.DuckS, FSaskartaStationLogic::DbToLinear(C.DuckDb));
            TWeakObjectPtr<UAudioComponent> Weak = PartComp;
            const float FadeS = C.FadeOutS;
            if (UWorld* World = GetWorld())
            {
                World->GetTimerManager().SetTimer(DuckFadeTimer, FTimerDelegate::CreateWeakLambda(this, [Weak, FadeS]()
                {
                    if (UAudioComponent* A = Weak.Get()) A->FadeOut(FadeS, 0.f);
                }), FMath::Max(0.01f, C.DuckS), false);
            }
        }
        else
        {
            PartComp->FadeOut(C.FadeOutS, 0.f);
        }
    }
    if (USaskartaEventRunner* R = Runner.Get())
    {
        R->HideStationSubtitle();
    }
    CurrentPart = INDEX_NONE;
    CurrentPick = FSaskartaStationPick();
    CurrentShowPick = FSaskartaShowPick();
    bPartWaitingLoad = false;
    Phase = ESaskartaStationPhase::Waiting;
    QuietSinceS = T;
}

void USaskartaRadioStation::FadeOutAll(float FadeS, bool bIncludeBed)
{
    StopComp(PartComp, FadeS);
    StopComp(TailComp, FadeS);
    if (bIncludeBed)
    {
        StopComp(BedComp, FadeS);
    }
}

void USaskartaRadioStation::HandleStoryBusy(bool bBusy, float ExpectedS, bool bCinematic)
{
    if (!Asset || bSignalDeath)
    {
        return;
    }
    const FSaskartaStationConfig& C = Asset->Config;
    const double T = Now();
    switch (FSaskartaEventLogic::StationReaction(bBusy, bCinematic))
    {
    case ESaskartaStationReaction::DuckThenFade:
        if (bStoryLineInfo)
        {
            // HandleStoryLine already cut (archive) or ducked (carrier) the item.
            if (!StoryState.bDucked)
            {
                NextActionAtS = FMath::Max(NextActionAtS, T + ExpectedS + C.HoldoffAfterLineS);
            }
            break;
        }
        InterruptSlot(true, true);
        // The gap clock restarts after the beat's clip plus the hold-off.
        NextActionAtS = FMath::Max(NextActionAtS, T + ExpectedS + C.HoldoffAfterLineS);
        break;
    case ESaskartaStationReaction::Suspend:
        if (const USaskartaEventRunner* R = Runner.Get(); R && R->ShouldKeepStationPlaying())
        {
            break; // keep the exact part/component/cursor across a camera-only scene
        }
        InterruptSlot(false, true);
        FadeOutAll(C.FadeOutS, true);
        if (!bSuspended)
        {
            bSuspended = true;
            SuspendRemainingS = FMath::Max(0.0, NextActionAtS - T);
        }
        break;
    case ESaskartaStationReaction::Release:
        if (bCinematic && !bSuspended)
        {
            break; // continuous camera scenes never held or rescheduled this programme
        }
        if (bSuspended && bCinematic)
        {
            bSuspended = false;
            NextActionAtS = T + FMath::Max(SuspendRemainingS, static_cast<double>(C.HoldoffAfterLineS));
            if (BedComp && Phase != ESaskartaStationPhase::Silent)
            {
                BedComp->FadeIn(1.f, 1.f);
            }
            // RADIOSHOW: back from a cinematic with a fill, as if the show had gone on meanwhile.
            if (bShowMode) Show.RequestOpenWithFill();
        }
        else
        {
            NextActionAtS = FMath::Max(NextActionAtS, T + C.HoldoffAfterLineS);
        }
        if (!bCinematic)
        {
            // RADIOSHOW: the story line has ended: after_beat items and the AFTER_TAPE reaction (not after a carrier line).
            if (bShowMode && LastStoryKind != ESaskartaRadioLineKind::Carrier && !LastStoryBeat.IsNone())
            {
                Show.OnStoryLineEnded(LastStoryBeat, ShowNow());
            }
            LastStoryBeat = NAME_None;
            LastStoryKind = ESaskartaRadioLineKind::None;
            bStoryLineInfo = false;
            ApplyStoryStep(StoryState.OnLineEnd(T));
        }
        break;
    }
}

void USaskartaRadioStation::HandleBeatFinished(FName BeatId)
{
    if (Asset && BeatId == Asset->Config.StartEvent && !bStarted)
    {
        bStarted = true;
        UE_LOG(LogSaskartaStation, Log, TEXT("%s finished: the station may come on"), *BeatId.ToString());
    }
    if (bShowMode)
    {
        Show.OnBeatFinished(BeatId);
    }
}

void USaskartaRadioStation::NotifyIdle(bool bInIdle)
{
    if (bIdle == bInIdle)
    {
        return;
    }
    bIdle = bInIdle;
    if (!bIdle && Asset)
    {
        // Back with the tune sweep after the idle tape.
        NextActionAtS = Now() + Scheduler.DrawAfterIdleDelayS();
    }
}

// ============================================================================ reception

void USaskartaRadioStation::SetRepairReception(bool bActive, float Signal01)
{
    bRepairReception = bActive;
    RepairSignal = bActive && FMath::IsFinite(Signal01) ? FMath::Clamp(Signal01, 0.f, 1.f) : 1.f;
    if (Asset && !bSignalDeath) ApplyReception();
}

void USaskartaRadioStation::HandleProgrammeEnvelope(const UAudioComponent* Component, const USoundWave*, float Envelope)
{
    if (Component != PartComp) return; // a former part may still be finishing as the tail
    ProgrammeEnvelope = FMath::IsFinite(Envelope) ? FMath::Clamp(Envelope, 0.f, 1.f) : 0.f;
    ProgrammeEnvelopeAtS = Now();
}

float USaskartaRadioStation::GetProgrammeEnvelope() const
{
    if (bMenuPaused || bSignalDeath || Phase != ESaskartaStationPhase::Playing || !PartComp
        || !PartComp->IsPlaying() || !CurrentPick.Parts.IsValidIndex(CurrentPart)
        || CurrentPick.Parts[CurrentPart].Kind != FSaskartaStationPart::EKind::Voice
        || ProgrammeEnvelopeAtS < 0.0 || Now() - ProgrammeEnvelopeAtS > 0.3)
        return 0.f;
    return FMath::Clamp(ProgrammeEnvelope * PartComp->VolumeMultiplier, 0.f, 1.f);
}

void USaskartaRadioStation::ApplyReception()
{
    const FSaskartaStationConfig& C = Asset->Config;
    const USaskartaEventRunner* R = Runner.Get();
    Quality = FSaskartaStationLogic::Quality(C.QualityByRoadM, R ? FMath::Max(0.f, R->GetRoadM()) : 0.f);
    const float Vol = USaskartaStorySettings::Get()->StationVolume;
    const bool bSpeech = Phase == ESaskartaStationPhase::Playing && CurrentPick.Parts.IsValidIndex(CurrentPart)
        && CurrentPick.Parts[CurrentPart].Kind != FSaskartaStationPart::EKind::Static;
    const bool bRepair = bRepairReception && !bSignalDeath && !StoryState.bForced;
    const float Repair = bRepair ? RepairSignal : 1.f;
    const bool bBoostPulse = Now() < BoostPulseUntilS && IsBoostInterferenceEligible();
    if (PartComp && bSpeech)
    {
        PartComp->SetLowPassFilterEnabled(true);
        PartComp->SetLowPassFilterFrequency(FMath::Lerp(600.f, FSaskartaStationLogic::MapQ(Quality, C.VoiceLowpassHz), Repair));
        PartComp->SetHighPassFilterEnabled(true);
        PartComp->SetHighPassFilterFrequency(FSaskartaStationLogic::MapQ(Quality, C.VoiceHighpassHz));
        float GainDb = FSaskartaStationLogic::ProgrammeGainDb(Quality, C);
        // RADIOSHOW: the sign-off is heard through the static (the voice is floored).
        if (bShowMode && CurrentShowPick.bSignoff)
        {
            GainDb = FMath::Max(GainDb, C.Show.SignoffVoiceFloorDb);
        }
        PartComp->SetVolumeMultiplier(Vol * SaskartaAudioMix::RadioProgramGain * FSaskartaStationLogic::DbToLinear(GainDb) *
            UnderNow * FMath::Lerp(0.003f, 1.f, Repair * Repair) * (bBoostPulse ? 0.32f : 1.f));
    }
    if (BedComp)
    {
        const float BedAtQuarter = FSaskartaStationLogic::MapQ(0.25f, C.StaticBetweenDb);
        float BedDb = FSaskartaStationLogic::MapQ(Quality, C.StaticBetweenDb)
            - FSaskartaStationLogic::BelowQuarterDb(Quality, BedAtQuarter - C.StaticBetweenDbAtQ0);
        if (bSpeech) BedDb += C.StaticUnderSpeechDb;
        if (bRepair) BedDb += 9.f * (1.f - Repair);
        if (bBoostPulse) BedDb += 8.f;
        if (Now() < DropoutEndS)
            BedDb += C.DropoutStaticBoostDb;
        BedComp->SetVolumeMultiplier(Vol * FSaskartaStationLogic::DbToLinear(BedDb) * UnderNow);
    }
}

void USaskartaRadioStation::MaybeDropout()
{
    const FSaskartaStationConfig& C = Asset->Config;
    const float Rate = FSaskartaStationLogic::DropoutRate(Quality, C);
    if (Rate <= 0.f || !PartComp || !PartComp->IsPlaying())
    {
        NextDropoutAtS = -1.0;
        return;
    }
    const double T = Now();
    if (NextDropoutAtS < 0.0)
    {
        NextDropoutAtS = T - FMath::Loge(FMath::Max(1.0e-4f, Scheduler.Rand.FRand())) / Rate;
        return;
    }
    if (T < NextDropoutAtS)
    {
        return;
    }
    const float LenS = Scheduler.Rand.FRandRange(C.DropoutLengthMs.X, C.DropoutLengthMs.Y) / 1000.f;
    DropoutEndS = T + LenS;
    PartComp->AdjustVolume(0.03f, FSaskartaStationLogic::DbToLinear(C.DropoutVoiceDb));
    TWeakObjectPtr<UAudioComponent> Weak = PartComp;
    FTimerHandle Restore;
    if (UWorld* World = GetWorld())
    {
        World->GetTimerManager().SetTimer(Restore, FTimerDelegate::CreateWeakLambda(this, [Weak]()
        {
            if (UAudioComponent* A = Weak.Get()) A->AdjustVolume(0.05f, 1.f);
        }), LenS, false);
    }
    NextDropoutAtS = T - FMath::Loge(FMath::Max(1.0e-4f, Scheduler.Rand.FRand())) / Rate;
}

// ============================================================================ LANE5: panel and lightning

FText USaskartaRadioStation::GetCurrentZoneLabel() const
{
    if (!Asset)
    {
        return FText::GetEmpty();
    }
    const FSaskartaStationZone* Z = Asset->Config.Zones.FindByPredicate([this](const FSaskartaStationZone& It) { return It.Name == Scheduler.CurrentZone; });
    return Z ? FText::FromString(Z->Label) : FText::GetEmpty();
}

FText USaskartaRadioStation::GetCurrentItemTitle() const
{
    if (!Asset || Phase != ESaskartaStationPhase::Playing || !CurrentPick.Parts.IsValidIndex(CurrentPart))
    {
        return FText::GetEmpty();
    }
    const FSaskartaStationConfig& C = Asset->Config;
    const FSaskartaStationPart& P = CurrentPick.Parts[CurrentPart];
    if (P.Kind == FSaskartaStationPart::EKind::Song)
    {
        const FSaskartaStationSong* Song = C.Songs.FindByPredicate([&P](const FSaskartaStationSong& S) { return S.Id == P.SongId; });
        FString Title = Song && !Song->Title.IsEmpty() ? Song->Title : P.SongId.ToString();
        if (Title.Len() > 0) Title[0] = FChar::ToUpper(Title[0]);
        return FText::FromString(FSaskartaStationLogic::SongCaption(Title, FString()));
    }
    if (P.Kind == FSaskartaStationPart::EKind::Static)
    {
        return FText::GetEmpty();
    }
    if (bShowMode)
    {
        return FText::FromString(FString::Printf(TEXT("Live · Act %s"), SaskartaRadio::Roman(Show.GetAct())));
    }
    return FText::FromString(FSaskartaStationLogic::CategoryLabel(C.CategoryLabels, CurrentPick.Category));
}

void USaskartaRadioStation::HandleLightning(float DistanceM, bool bClose)
{
    if (!Asset || Phase == ESaskartaStationPhase::Silent || bSignalDeath)
    {
        return;
    }
    const FSaskartaStationConfig& C = Asset->Config;
    // A close strike is a hard burst, a far one softer; either briefly buries the voice.
    const float BurstDb = C.LightningBurstDb + (bClose ? 0.f : -6.f);
    if (USoundBase* Burst = GetResidentSoundAt(C.StaticIn))
    {
        UGameplayStatics::PlaySound2D(this, Burst, FSaskartaStationLogic::DbToLinear(BurstDb) * USaskartaStorySettings::Get()->StationVolume);
    }
    if (PartComp && PartComp->IsPlaying())
    {
        const float LenS = bClose ? 0.6f : 0.3f;
        DropoutEndS = Now() + LenS;
        PartComp->AdjustVolume(0.02f, FSaskartaStationLogic::DbToLinear(C.DropoutVoiceDb));
        TWeakObjectPtr<UAudioComponent> Weak = PartComp;
        FTimerHandle Restore;
        if (UWorld* World = GetWorld())
        {
            World->GetTimerManager().SetTimer(Restore, FTimerDelegate::CreateWeakLambda(this, [Weak]()
            {
                if (UAudioComponent* A = Weak.Get()) A->AdjustVolume(0.08f, 1.f);
            }), LenS, false);
        }
    }
    // RADIOSHOW: the signal knows (LIGHTNING reactions start in Act II; the data's min_act).
    if (bShowMode && Show.OnEvent(FSaskartaShowScheduler::EvLightning, ShowNow(), bClose))
    {
        UE_LOG(LogSaskartaStation, Log, TEXT("show: LIGHTNING (%.0f m%s) queued a reaction"), DistanceM, bClose ? TEXT(", close") : TEXT(""));
    }
}

// ============================================================================ CPPBATCH: the player's radio and story lines

bool USaskartaRadioStation::IsRadioOn() const
{
    const USaskartaStorySettings* S = USaskartaStorySettings::Get();
    return !S || S->bRadioStation;
}

void USaskartaRadioStation::SetRadioOn(bool bOn)
{
    const bool bWasOn = IsRadioOn();
    USaskartaStorySettings::SetRadioStation(bOn);
    UE_LOG(LogSaskartaStation, Log, TEXT("radio %s by the player%s"), bOn ? TEXT("on") : TEXT("off"), StoryState.bForced ? TEXT(" (an archive line holds it audible for now)") : TEXT(""));
    // RADIOSHOW: RADIO_BACK_ON after >= 10 s off.
    if (bWasOn && !bOn)
    {
        RadioOffAtS = Now();
    }
    else if (!bWasOn && bOn)
    {
        if (bShowMode && RadioOffAtS >= 0.0 && Now() - RadioOffAtS >= SaskartaRadio::RadioBackOnAfterS)
        {
            Show.OnEvent(FSaskartaShowScheduler::EvRadioBackOn, ShowNow());
        }
        RadioOffAtS = -1.0;
    }
}

float USaskartaRadioStation::GetStormIntensityForRadio() const
{
    if (StormIntensityInput >= 0.f)
    {
        return FMath::Clamp(StormIntensityInput, 0.f, 1.f);
    }
    const UWorld* World = GetWorld();
    const USaskartaLightingDirector* Director = World ? World->GetSubsystem<USaskartaLightingDirector>() : nullptr;
    return Director ? FMath::Clamp(Director->GetEffectiveStormIntensity(), 0.f, 1.f) : 0.f;
}

float USaskartaRadioStation::CurrentQuality() const
{
    const USaskartaEventRunner* R = Runner.Get();
    return Asset ? FSaskartaStationLogic::Quality(Asset->Config.QualityByRoadM, R ? FMath::Max(0.f, R->GetRoadM()) : 0.f) : Quality;
}

void USaskartaRadioStation::HandleStoryLine(FName LineId, FName BeatId, bool bCarrier, int32 BeatPriority, float DurationS)
{
    if (!Asset || bSignalDeath)
    {
        return;
    }
    const ESaskartaRadioLineKind Kind = FSaskartaRadioFxLogic::ClassifyLine(LineId, bCarrier, BeatPriority);
    const bool bStationPlaying = Phase == ESaskartaStationPhase::Playing && CurrentPick.Parts.IsValidIndex(CurrentPart);
    const bool bSong = bStationPlaying && CurrentPick.Parts[CurrentPart].Kind == FSaskartaStationPart::EKind::Song;
    const float SongPos = bSong ? static_cast<float>(Now() - PartStartS) : 0.f;
    UE_LOG(LogSaskartaStation, Log, TEXT("story line %s (beat %s, priority %d): %s%s"), *LineId.ToString(), *BeatId.ToString(), BeatPriority,
        Kind == ESaskartaRadioLineKind::Archive ? TEXT("archive") : Kind == ESaskartaRadioLineKind::Carrier ? TEXT("carrier") : TEXT("other"),
        bStationPlaying ? (bSong ? TEXT(", cutting a song") : TEXT(", cutting the segment")) : TEXT(""));
    bStoryLineInfo = true;
    // RADIOSHOW: remembered for the AFTER_TAPE reaction and the after_beat items when the line ends.
    LastStoryBeat = BeatId;
    LastStoryKind = Kind;
    ApplyStoryStep(StoryState.OnLineStart(Kind, BeatId, bStationPlaying, bSong, SongPos, Now(), DurationS));
}

void USaskartaRadioStation::ApplyStoryStep(const FSaskartaRadioStoryStep& Step)
{
    if (!Asset)
    {
        return;
    }
    const FSaskartaStationConfig& C = Asset->Config;
    const float Vol = USaskartaStorySettings::Get()->StationVolume;
    if (Step.bForcedOn)
    {
        UE_LOG(LogSaskartaStation, Log, TEXT("radio forced on for %s (player's radio %s)"), *StoryState.ForcedBeat.ToString(), IsRadioOn() ? TEXT("on") : TEXT("off"));
        if (Phase == ESaskartaStationPhase::Silent)
        {
            // The player's radio is off (or not on yet): power it up under the line.
            if (USoundBase* Sweep = GetResidentSoundAt(C.TuneSweep))
            {
                UGameplayStatics::PlaySound2D(this, Sweep, Vol);
            }
            if (USoundBase* Bed = GetResidentSoundAt(C.StaticBed))
            {
                if (!BedComp)
                {
                    BedComp = UGameplayStatics::CreateSound2D(this, Bed, Vol, 1.f, 0.f, nullptr, false, false);
                }
                if (BedComp)
                {
                    BedComp->FadeIn(0.3f, FSaskartaStationLogic::DbToLinear(FSaskartaStationLogic::MapQ(CurrentQuality(), C.StaticBetweenDb) + C.StaticUnderSpeechDb));
                }
            }
        }
        OnRadioForcedOn.Broadcast(StoryState.ForcedBeat);
    }
    if (Step.bInterrupt)
    {
        CutForStoryLine(true);
    }
    if (Step.bDuck && PartComp && PartComp->IsPlaying())
    {
        PartComp->AdjustVolume(FSaskartaRadioFxLogic::CarrierDuckS, FSaskartaStationLogic::DbToLinear(FSaskartaRadioFxLogic::CarrierDuckDb));
    }
    if (Step.bUnduck && PartComp && PartComp->IsPlaying())
    {
        PartComp->AdjustVolume(FSaskartaRadioFxLogic::CarrierDuckS, 1.f);
    }
    if (Step.bForcedOff)
    {
        const bool bOnAfter = IsRadioOn();
        UE_LOG(LogSaskartaStation, Log, TEXT("radio force released; the player's radio is %s"), bOnAfter ? TEXT("on") : TEXT("off"));
        if (Phase == ESaskartaStationPhase::Silent && BedComp && BedComp->IsPlaying())
        {
            BedComp->FadeOut(0.5f, 0.f);
        }
        OnRadioForcedOff.Broadcast(bOnAfter);
    }
    if (Step.bResume)
    {
        ResumeProgramme(Step.bResumeSong);
    }
}

void USaskartaRadioStation::CutForStoryLine(bool bKeepSong)
{
    if (Phase != ESaskartaStationPhase::Playing)
    {
        return;
    }
    const FSaskartaStationConfig& C = Asset->Config;
    const double T = Now();
    const bool bSong = CurrentPick.Parts.IsValidIndex(CurrentPart) && CurrentPick.Parts[CurrentPart].Kind == FSaskartaStationPart::EKind::Song;
    InterruptedPick = FSaskartaStationPick();
    InterruptedShowPick = FSaskartaShowPick();
    InterruptedPart = INDEX_NONE;
    InterruptedSongPosS = 0.f;
    if (bKeepSong && bSong && !bPartWaitingLoad)
    {
        InterruptedPick = CurrentPick;
        InterruptedShowPick = CurrentShowPick;
        InterruptedPart = CurrentPart;
        InterruptedSongPosS = static_cast<float>(T - PartStartS);
        if (bShowMode)
        {
            Show.RememberInterruptedSong(CurrentPick.Parts[CurrentPart].SongId, InterruptedSongPosS, CurrentShowPick.OutroId);
        }
    }
    else if (bShowMode)
    {
        // RADIOSHOW: heard under half, a backbone item goes back to the front of the backbone.
        ReturnShowPick();
    }
    else if (!CurrentPick.bSongBlock && CurrentPick.Parts.IsValidIndex(CurrentPart))
    {
        // A segment heard under the threshold goes back in its bag; otherwise it counts as played.
        const FSaskartaStationPart& P = CurrentPick.Parts[CurrentPart];
        if (!FSaskartaStationLogic::CountsAsPlayed(static_cast<float>(T - PartStartS), static_cast<float>(PartEndS - PartStartS), C.ReturnToBagIfHeardBelow))
        {
            Scheduler.ReturnSegment(P.SegmentIndex);
        }
    }
    // The tune-over: a short static cut, not a duck.
    if (USoundBase* Out = GetResidentSoundAt(C.StaticOut))
    {
        UGameplayStatics::PlaySound2D(this, Out, USaskartaStorySettings::Get()->StationVolume);
    }
    StopComp(PartComp, FSaskartaRadioFxLogic::TuneOverS);
    StopComp(TailComp, FSaskartaRadioFxLogic::TuneOverS);
    if (USaskartaEventRunner* R = Runner.Get())
    {
        R->HideStationSubtitle();
    }
    CurrentPart = INDEX_NONE;
    CurrentPick = FSaskartaStationPick();
    CurrentShowPick = FSaskartaShowPick();
    bPartWaitingLoad = false;
    Phase = ESaskartaStationPhase::Waiting;
    bHeldForStory = true;
    QuietSinceS = T;
    UE_LOG(LogSaskartaStation, Log, TEXT("station cut for the story (tune-over %.1f s)%s"), FSaskartaRadioFxLogic::TuneOverS,
        InterruptedPart != INDEX_NONE ? *FString::Printf(TEXT("; the song resumes at %.1f s"), InterruptedSongPosS) : TEXT(""));
}

void USaskartaRadioStation::ResumeProgramme(bool bResumeSong)
{
    bHeldForStory = false;
    const bool bCanPlay = Asset && Mode == ESaskartaStationMode::On && !bSuspended && !bIdle && Phase == ESaskartaStationPhase::Waiting && !bSignalDeath;
    if (bCanPlay && bResumeSong && InterruptedPick.Parts.IsValidIndex(InterruptedPart))
    {
        CurrentPick = InterruptedPick;
        CurrentShowPick = InterruptedShowPick;
        Phase = ESaskartaStationPhase::Playing;
        if (!bShowMode)
        {
            if (USoundBase* In = GetResidentSoundAt(Asset->Config.StaticIn))
            {
                UGameplayStatics::PlaySound2D(this, In, USaskartaStorySettings::Get()->StationVolume);
            }
        }
        UE_LOG(LogSaskartaStation, Log, TEXT("song resumed at %.1f s"), InterruptedSongPosS);
        StartPart(InterruptedPart, InterruptedSongPosS);
    }
    else if (bCanPlay)
    {
        // A new item (the gate still waits for the story's hold-off).
        NextActionAtS = FMath::Min(NextActionAtS, Now() + 0.5);
        UE_LOG(LogSaskartaStation, Log, TEXT("programme resumes with the next item"));
    }
    InterruptedPick = FSaskartaStationPick();
    InterruptedShowPick = FSaskartaShowPick();
    InterruptedPart = INDEX_NONE;
    InterruptedSongPosS = 0.f;
}

// ============================================================================ CPPBATCH: imperfections

bool USaskartaRadioStation::IsBoostInterferenceEligible() const
{
    const UWorld* World = GetWorld();
    const USaskartaEventRunner* R = Runner.Get();
    const USaskartaPowerSubsystem* Power = World ? World->GetSubsystem<USaskartaPowerSubsystem>() : nullptr;
    const FName Flow = R ? R->GetFlowState() : NAME_None;
    return Asset && World && !World->IsPaused() && !bMenuPaused && !bSignalDeath && !bStoppedForGood
        && Mode == ESaskartaStationMode::On && IsRadioOn() && !bRadioPowerCut && !bIdle && !bSuspended
        && !bRepairReception && !StoryState.bForced && !StoryState.bArchiveLineActive
        && R && !R->IsCinematicActive() && !R->IsHoldingInput() && !R->IsVoiceBusy()
        && (Flow == FName(TEXT("Playing")) || Flow == FName(TEXT("Carrier")))
        && Power && Power->IsTurbo() && Phase == ESaskartaStationPhase::Playing
        && PartComp && PartComp->IsPlaying() && CurrentPick.Parts.IsValidIndex(CurrentPart)
        && CurrentPick.Parts[CurrentPart].Kind != FSaskartaStationPart::EKind::Static
        && !(bShowMode && CurrentShowPick.bSignoff);
}

void USaskartaRadioStation::UpdateBoostInterference(double NowS)
{
    if (!IsBoostInterferenceEligible())
    {
        NextBoostInterferenceS = -1.0;
        if (BoostPulseUntilS >= 0.0)
        {
            if (UWorld* World = GetWorld()) World->GetTimerManager().ClearTimer(BoostPulseTimer);
            EndBoostInterferencePulse();
        }
        return;
    }
    if (NextBoostInterferenceS >= 0.0 && NowS < NextBoostInterferenceS) return;
    // Immediate onset on the next 0.25s station poll, independently of any old
    // long glitch timer. Brief signal dips leave the same recording running.
    static constexpr float Durations[] = { 0.09f, 0.13f, 0.11f };
    static constexpr float Gaps[] = { 1.4f, 1.9f, 1.65f };
    const int32 Variant = BoostPulseIndex;
    BoostPulseIndex = (BoostPulseIndex + 1) % 3;
    BoostPulseUntilS = NowS + Durations[Variant];
    NextBoostInterferenceS = NowS + Gaps[Variant];
    GetWorld()->GetTimerManager().SetTimer(BoostPulseTimer, this, &USaskartaRadioStation::EndBoostInterferencePulse,
        Durations[Variant], false);
    ApplyReception();
}

void USaskartaRadioStation::EndBoostInterferencePulse()
{
    BoostPulseUntilS = -1.0;
    if (Asset && !bSignalDeath) ApplyReception(); // recompute repair/user/duck baseline, never force gain to one
}

void USaskartaRadioStation::UpdateGlitches(double NowS)
{
    if (!Asset)
    {
        return;
    }
    const bool bArchive = StoryState.bArchiveLineActive;
    const bool bStationAudible = Phase == ESaskartaStationPhase::Playing && PartComp && PartComp->IsPlaying() && !bSuspended;
    if (!bArchive && !bStationAudible)
    {
        NextGlitchAtS = -1.0;
        return;
    }
    const float Q = CurrentQuality();
    const float Storm = GetStormIntensityForRadio();
    if (NextGlitchAtS < 0.0 || bArchive != bGlitchScheduleArchive)
    {
        bGlitchScheduleArchive = bArchive;
        NextGlitchAtS = FSaskartaRadioFxLogic::NextGlitchAtS(GlitchParams, Q, Storm, bArchive, NowS, Scheduler.Rand);
        return;
    }
    if (NowS < NextGlitchAtS)
    {
        return;
    }
    const FSaskartaRadioGlitchEvent E = FSaskartaRadioFxLogic::DrawGlitch(GlitchParams, Q, Storm, bArchive, Scheduler.Rand);
    ApplyGlitch(E, bArchive);
    UE_LOG(LogSaskartaStation, Verbose, TEXT("glitch %d %.2f s x%.2f (q %.2f, storm %.2f%s)"), static_cast<int32>(E.Type), E.DurationS, E.Intensity, Q, Storm,
        bArchive ? TEXT(", archive line") : TEXT(""));
    OnRadioGlitch.Broadcast(E.Type, E.DurationS, E.Intensity);
    // RADIOSHOW: a real dropout of the station's own signal may make the host notice.
    if (bShowMode && !bArchive && E.Type == ESaskartaRadioGlitch::Dropout && E.DurationS >= 0.3f)
    {
        Show.OnEvent(FSaskartaShowScheduler::EvDropout, ShowNow());
    }
    NextGlitchAtS = FSaskartaRadioFxLogic::NextGlitchAtS(GlitchParams, Q, Storm, bArchive, NowS, Scheduler.Rand);
}

void USaskartaRadioStation::ApplyGlitch(const FSaskartaRadioGlitchEvent& E, bool bArchiveLine)
{
    // Story / archive lines are never touched here (the runner plays them); Blueprint may add the light crackle.
    if (bArchiveLine)
    {
        return;
    }
    const double T = Now();
    UWorld* World = GetWorld();
    switch (E.Type)
    {
    case ESaskartaRadioGlitch::Dropout:
        if (PartComp && PartComp->IsPlaying())
        {
            DropoutEndS = T + E.DurationS;
            PartComp->AdjustVolume(0.03f, FSaskartaStationLogic::DbToLinear(Asset->Config.DropoutVoiceDb * E.Intensity));
            TWeakObjectPtr<UAudioComponent> Weak = PartComp;
            if (World)
            {
                FTimerHandle Restore;
                World->GetTimerManager().SetTimer(Restore, FTimerDelegate::CreateWeakLambda(this, [Weak]()
                {
                    if (UAudioComponent* A = Weak.Get()) A->AdjustVolume(0.05f, 1.f);
                }), FMath::Max(0.02f, E.DurationS), false);
            }
            ApplyReception();
        }
        break;
    case ESaskartaRadioGlitch::NoiseBurst:
        DropoutEndS = FMath::Max(DropoutEndS, T + E.DurationS); // the static bed rises (DropoutStaticBoostDb)
        ApplyReception();
        break;
    case ESaskartaRadioGlitch::PitchJitter:
    case ESaskartaRadioGlitch::Drift:
        if (PartComp && PartComp->IsPlaying())
        {
            PartComp->SetPitchMultiplier(1.f + E.PitchOffset);
            TWeakObjectPtr<UAudioComponent> Weak = PartComp;
            if (World)
            {
                World->GetTimerManager().SetTimer(PitchRestoreTimer, FTimerDelegate::CreateWeakLambda(this, [Weak]()
                {
                    if (UAudioComponent* A = Weak.Get()) A->SetPitchMultiplier(1.f);
                }), FMath::Max(0.02f, E.DurationS), false);
            }
        }
        break;
    default:
        // Crackle and Squeal are sounds: OnRadioGlitch (RADIOFX one-shots in Blueprint).
        break;
    }
}

// ============================================================================ RADIOSHOW: game events, pause, save, the end

void USaskartaRadioStation::UpdateShowEvents(double NowS)
{
    const double ShowT = ShowNow();
    // STORM_UP: the storm has risen by >= 0.15 over its value 20 s ago (sampled once a second).
    if (NowS - LastStormSampleS >= 1.0)
    {
        LastStormSampleS = NowS;
        const float Storm = GetStormIntensityForRadio();
        StormSamples.Add(FVector2D(NowS, Storm));
        StormSamples.RemoveAll([NowS](const FVector2D& S) { return NowS - S.X > SaskartaRadio::StormWindowS + 0.5; });
        if (StormSamples.Num() > 1 && Storm - StormSamples[0].Y >= SaskartaRadio::StormRise)
        {
            Show.OnEvent(FSaskartaShowScheduler::EvStormUp, ShowT);
            StormSamples.Reset(); // a new baseline: one rise, one event
            StormSamples.Add(FVector2D(NowS, Storm));
        }
    }
    // SILENCE: the station's own dead air (nothing picked, not in a story line or its hold-off) ran past after_silence_s.
    const FSaskartaShowEvent* SilenceCfg = Asset ? Asset->Config.Show.Events.Find(FSaskartaShowScheduler::EvSilence) : nullptr;
    const double AfterS = SilenceCfg ? SilenceCfg->AfterSilenceS : 6.0;
    const USaskartaEventRunner* R = Runner.Get();
    const bool bStoryQuiet = !R || (!R->IsStationVoiceBusy() && R->SecondsSinceStationVoice() >= Asset->Config.HoldoffAfterLineS);
    if (Phase == ESaskartaStationPhase::Waiting && !bHeldForStory && bStoryQuiet && !bSilenceFired && QuietSinceS >= 0.0 && NowS - QuietSinceS >= AfterS)
    {
        bSilenceFired = true;
        Show.OnEvent(FSaskartaShowScheduler::EvSilence, ShowT);
    }
}

void USaskartaRadioStation::NotifyOffroad()
{
    // Task TETHER: only when truly off every allowed path (the road, a tether path, an exploration zone)
    if (const USaskartaTetherSubsystem* Tether = GetWorld() ? GetWorld()->GetSubsystem<USaskartaTetherSubsystem>() : nullptr)
    {
        if (Tether->IsPlayerOnAllowedGround())
        {
            UE_LOG(LogSaskartaStation, Verbose, TEXT("show: OFFROAD ignored (on the road, a tether path or in a zone)"));
            return;
        }
    }
    if (bShowMode && Show.OnEvent(FSaskartaShowScheduler::EvOffroad, ShowNow()))
    {
        UE_LOG(LogSaskartaStation, Log, TEXT("show: OFFROAD queued a reaction"));
    }
}

void USaskartaRadioStation::NotifyPassingPoi(FName Zone)
{
    if (bShowMode)
    {
        Show.OnPoiZone(Zone, ShowNow());
    }
}

bool USaskartaRadioStation::FireShowEvent(FName Event, bool bClose)
{
    if (!bShowMode)
    {
        return false;
    }
    if (Event == FSaskartaShowScheduler::EvAfterTape)
    {
        Show.OnStoryLineEnded(FName(TEXT("DEBUG_TAPE")), ShowNow());
        return true;
    }
    return Show.OnEvent(Event, ShowNow(), bClose);
}

void USaskartaRadioStation::NotifyPaused(bool bPaused)
{
    if (bPaused == bMenuPaused)
    {
        return;
    }
    bMenuPaused = bPaused;
    if (USaskartaEventRunner* R = Runner.Get())
    {
        R->SetStationSubtitlePaused(bPaused);
    }
    for (UAudioComponent* C : { PartComp.Get(), TailComp.Get(), BedComp.Get(), CodaComp.Get(), TitleComp.Get(), RecallComp.Get() })
    {
        if (C) C->SetPaused(bPaused);
    }
    const double T = Now();
    if (bPaused)
    {
        if (UWorld* World = GetWorld())
        {
            World->GetTimerManager().PauseTimer(RecallTimer);
            World->GetTimerManager().PauseTimer(CodaTimer);
            World->GetTimerManager().PauseTimer(TitleTimer);
        }
        PauseStartRealS = FPlatformTime::Seconds();
        PauseStartWorldS = T;
        return;
    }
    // World time that ran while the menu was open (a menu that does not pause the world) is taken off every clock.
    const double WorldS = FMath::Max(0.0, T - PauseStartWorldS);
    PartStartS += WorldS;
    PartEndS += WorldS;
    if (RecallEndS >= 0.0) RecallEndS += WorldS;
    if (UWorld* World = GetWorld())
    {
        World->GetTimerManager().UnPauseTimer(RecallTimer);
        World->GetTimerManager().UnPauseTimer(CodaTimer);
        World->GetTimerManager().UnPauseTimer(TitleTimer);
    }
    if (Asset) ApplyReception();
    RefreshEndingMusicVolume();
    NextActionAtS += WorldS;
    PartLoadDeadlineS += WorldS;
    if (QuietSinceS >= 0.0) QuietSinceS += WorldS;
    LastUpdateS = T;
    const double RealS = FPlatformTime::Seconds() - PauseStartRealS;
    if (bShowMode && !bSignalDeath && RealS >= SaskartaRadio::ResumedAfterS && Show.OnEvent(FSaskartaShowScheduler::EvResumed, ShowNow()))
    {
        UE_LOG(LogSaskartaStation, Log, TEXT("show: back from %.0f s in the pause menu; RESUMED queued"), RealS);
    }
}

FSaskartaShowSaveState USaskartaRadioStation::GetShowSaveState() const
{
    FSaskartaShowSaveState S = Show.SaveState(ShowNow());
    if (!bShowMode)
    {
        S.bValid = false;
        return S;
    }
    // The song position: the one playing now, or the one a story line cut.
    auto SongOf = [](const FSaskartaStationPick& Pick, int32 Part) -> FName
    {
        return Pick.Parts.IsValidIndex(Part) && Pick.Parts[Part].Kind == FSaskartaStationPart::EKind::Song ? Pick.Parts[Part].SongId : NAME_None;
    };
    if (Phase == ESaskartaStationPhase::Playing && !SongOf(CurrentPick, CurrentPart).IsNone())
    {
        S.SongId = SongOf(CurrentPick, CurrentPart);
        S.SongPositionS = static_cast<float>(Now() - PartStartS);
        S.SongOutroId = CurrentShowPick.OutroId;
    }
    else if (!SongOf(InterruptedPick, InterruptedPart).IsNone())
    {
        S.SongId = SongOf(InterruptedPick, InterruptedPart);
        S.SongPositionS = InterruptedSongPosS;
        S.SongOutroId = InterruptedShowPick.OutroId;
    }
    return S;
}

void USaskartaRadioStation::ApplyShowSaveState(const FSaskartaShowSaveState& State)
{
    if (!Asset)
    {
        // DA_Station is still loading: apply when it arrives.
        bHasPendingShowState = true;
        PendingShowState = State;
        return;
    }
    if (!bShowMode)
    {
        return;
    }
    // A checkpoint replaces playback state, including a previously finished Human
    // run or an aborted cinematic. Keep pause ownership and the player's radio setting;
    // the menu/rescue owner releases its pause after the restore is complete.
    if (UWorld* World = GetWorld())
    {
        FTimerManager& TM = World->GetTimerManager();
        TM.ClearTimer(DuckFadeTimer);
        TM.ClearTimer(PitchRestoreTimer);
        TM.ClearTimer(SongRiseTimer);
        TM.ClearTimer(CodaTimer);
        TM.ClearTimer(TitleTimer);
        TM.ClearTimer(RecallTimer);
        TM.ClearTimer(UnderTimer);
        TM.ClearTimer(BoostPulseTimer);
    }
    for (UAudioComponent* C : { PartComp.Get(), TailComp.Get(), BedComp.Get(), CodaComp.Get(), TitleComp.Get(), RecallComp.Get() })
    {
        if (IsValid(C)) C->Stop();
    }
    PartComp = TailComp = BedComp = CodaComp = TitleComp = RecallComp = nullptr;
    EndingTitleLoop = nullptr;
    if (EndingTitleLoad.IsValid()) EndingTitleLoad->CancelHandle();
    EndingTitleLoad.Reset();
    EndingMusicFlow = NAME_None;
    RecallEndS = -1.0;
    UnderBase.Reset();
    UnderNow = UnderTarget = 1.f;
    bRepairReception = false;
    NextBoostInterferenceS = BoostPulseUntilS = -1.0;
    BoostPulseIndex = 0;
    RepairSignal = 1.f;
    ProgrammeEnvelope = 0.f;
    ProgrammeEnvelopeAtS = -1.0;
    const bool bWasForced = StoryState.bForced;
    StoryState = FSaskartaRadioStoryState();
    if (bWasForced) OnRadioForcedOff.Broadcast(IsRadioOn());
    bHeldForStory = bStoryLineInfo = bSuspended = bIdle = bDucked = false;
    bSignalDeath = State.bValid && State.bSignoffDone;
    bStoppedForGood = bSignalDeath;
    bEndMusicStopped = bSignalDeath; // the completed show stays ended; Human resumes its separate title score below
    SuspendRemainingS = 0.0;
    LastStoryBeat = NAME_None;
    LastStoryKind = ESaskartaRadioLineKind::None;
    CurrentPick = FSaskartaStationPick();
    CurrentShowPick = FSaskartaShowPick();
    CurrentPart = INDEX_NONE;
    bPartWaitingLoad = false;
    PartLoadDeadlineS = 0.0;
    PartStartS = PartEndS = 0.0;
    NextDropoutAtS = DropoutEndS = NextGlitchAtS = -1.0;
    bGlitchScheduleArchive = false;
    StormSamples.Reset();
    LastStormSampleS = -1.0;
    QuietSinceS = Now();
    bSilenceFired = false;
    Phase = ESaskartaStationPhase::Silent;
    Mode = ESaskartaStationMode::Off;
    NextActionAtS = 0.0;
    LastUpdateS = Now();
    if (bMenuPaused) PauseStartWorldS = Now();
    InterruptedPick = FSaskartaStationPick();
    InterruptedShowPick = FSaskartaShowPick();
    InterruptedPart = INDEX_NONE;
    InterruptedSongPosS = 0.f;
    Show.LoadState(State, ShowNow());
    // CP0 is already past the boot handover too. Flow/settings still gate audibility.
    bStarted = true;
    UpdatePrefetch(true);
    UE_LOG(LogSaskartaStation, Log, TEXT("show restored: act %d, %d backbone items played, next %s; opening %s, paused %d, signoff done %d"),
        State.Act, State.PlayedBackbone.Num(), *Show.PeekNextBackbone().ToString(),
        Show.WasDropped(FSaskartaShowScheduler::OpeningSlotId()) ? TEXT("already passed") : TEXT("unheard"), bMenuPaused ? 1 : 0, bSignalDeath ? 1 : 0);
    if (const USaskartaEventRunner* R = Runner.Get()) SetEndingMusicFlow(R->GetFlowState());
}

void USaskartaRadioStation::HandleWritingRun(UWorld* World, USaskartaSaveGame* Save)
{
    if (Save && World == GetWorld() && bShowMode)
    {
        Save->ShowState = GetShowSaveState();
    }
}

void USaskartaRadioStation::HandleRestoredRun(UWorld* World, USaskartaSaveGame* Save)
{
    if (Save && World == GetWorld())
    {
        ApplyShowSaveState(Save->ShowState);
    }
}

void USaskartaRadioStation::BeginSignalDeath()
{
    if (bSignalDeath || !Asset)
    {
        return;
    }
    bSignalDeath = true;
    bStoppedForGood = true;
    const FSaskartaShowConfig& SC = Asset->Config.Show;
    UE_LOG(LogSaskartaStation, Log, TEXT("the Low Voice signs off: %.1f s of static, then it dies over %.1f s"), SC.SignalDeathHoldS, SC.SignalDeathFadeS);
    OnShowEnd.Broadcast(FName(TEXT("SignalDeath")));
    if (USaskartaEventRunner* R = Runner.Get())
    {
        R->HideStationSubtitle();
    }
    StopComp(TailComp, 1.f);
    UpdatePrefetch(true);
    UWorld* World = GetWorld();
    if (!World)
    {
        return;
    }
    const float FadeS = SC.SignalDeathFadeS;
    World->GetTimerManager().SetTimer(CodaTimer, FTimerDelegate::CreateWeakLambda(this, [this, FadeS]()
    {
        StopComp(BedComp, FadeS);
        StopComp(PartComp, FadeS);
        StartLastSong();
    }), FMath::Max(0.05f, SC.SignalDeathHoldS), false);
}

void USaskartaRadioStation::StartLastSong()
{
    if (bEndMusicStopped)
    {
        return;
    }
    const FSaskartaShowConfig& SC = Asset->Config.Show;
    const FString Path = ResolveLastSongPath();
    USoundBase* Song = Path.IsEmpty() ? nullptr : GetResidentSound(Path, true);
    if (!Song)
    {
        // No last song yet (or not loaded): straight to the title song as the static dies.
        if (!Path.IsEmpty())
        {
            UE_LOG(LogSaskartaStation, Log, TEXT("the last song %s is not loaded; going to the title song"), *Path);
        }
        StartTitleSongTransition();
        return;
    }
    CodaComp = UGameplayStatics::CreateSound2D(this, Song, USaskartaStorySettings::Get()->StationVolume * SaskartaAudioMix::RadioProgramGain * FSaskartaStationLogic::DbToLinear(SC.LastSongGainDb),
        1.f, 0.f, nullptr, false, false);
    if (!CodaComp)
    {
        StartTitleSongTransition();
        return;
    }
    if (SC.LastSongLowpassHz > 0.f)
    {
        CodaComp->SetLowPassFilterEnabled(true);
        CodaComp->SetLowPassFilterFrequency(SC.LastSongLowpassHz);
    }
    CodaComp->FadeIn(FMath::Max(0.05f, SC.LastSongFadeInS), 1.f);
    OnShowEnd.Broadcast(FName(TEXT("LastSong")));
    UE_LOG(LogSaskartaStation, Log, TEXT("the last song: %s"), *Song->GetName());
    const float Dur = Song->GetDuration();
    const float TitleAtS = (Dur > 0.f && Dur < 3600.f) ? FMath::Max(0.5f, Dur - SC.TitleCrossfadeS) : 120.f;
    if (UWorld* World = GetWorld())
    {
        World->GetTimerManager().SetTimer(TitleTimer, FTimerDelegate::CreateWeakLambda(this, [this]()
        {
            StartTitleSongTransition();
        }), TitleAtS, false);
    }
}

void USaskartaRadioStation::StartTitleSongTransition()
{
    // Paused components also retain their cursor. A duplicate CIN25 cue must never create another player.
    if (bEndMusicStopped || !Asset || TitleComp)
    {
        return;
    }
    const FSaskartaShowConfig& SC = Asset->Config.Show;
    if (SC.TitleSong.IsNull())
    {
        return;
    }
    USoundBase* Title = Cast<USoundBase>(SC.TitleSong.ResolveObject());
    if (!Title)
    {
        // Still loading: start it the moment it arrives (a late transition, never a hitch).
        if (EndingTitleLoad.IsValid() && !EndingTitleLoad->HasLoadCompleted()) return;
        TWeakObjectPtr<USaskartaRadioStation> WeakThis(this);
        EndingTitleLoad = UAssetManager::GetStreamableManager().RequestAsyncLoad(TArray<FSoftObjectPath>{ SC.TitleSong }, [WeakThis]()
        {
            if (USaskartaRadioStation* Self = WeakThis.Get(); Self && Self->bSignalDeath)
                Self->StartTitleSongTransition(); // a checkpoint restore cancels the old run's pending coda load
        }, FStreamableManager::AsyncLoadHighPriority);
        return;
    }
    EndingTitleLoop = Title;
    if (USoundWave* Wave = Cast<USoundWave>(Title))
    {
        // Loop the same authored recording at runtime, including an arbitrarily slow walk. Do not
        // change the shared wave's looping flag or restart its component at each scene boundary.
        USoundCue* Loop = NewObject<USoundCue>(this, NAME_None, RF_Transient);
        USoundNodeWavePlayer* Player = NewObject<USoundNodeWavePlayer>(Loop, NAME_None, RF_Transient);
        Player->SetSoundWave(Wave);
        Player->bLooping = true;
        Loop->FirstNode = Player;
        Loop->VolumeMultiplier = 1.f;
        Loop->PitchMultiplier = 1.f;
        Loop->SoundClassObject = Wave->SoundClassObject;
        Loop->SoundSubmixObject = Wave->SoundSubmixObject;
        Loop->VirtualizationMode = EVirtualizationMode::PlayWhenSilent;
        Loop->CacheAggregateValues();
        EndingTitleLoop = Loop;
    }
    TitleComp = UGameplayStatics::CreateSound2D(this, EndingTitleLoop, 1.f, 1.f, 0.f, nullptr, false, false);
    if (TitleComp)
    {
        RefreshEndingMusicVolume();
        TitleComp->FadeIn(FMath::Max(0.05f, SC.TitleCrossfadeS), FSaskartaStationLogic::DbToLinear(FSaskartaStationLogic::EndingMusicDb(EndingMusicFlow)));
        TitleComp->SetPaused(bMenuPaused);
    }
    StopComp(CodaComp, SC.TitleCrossfadeS);
    OnShowEnd.Broadcast(FName(TEXT("TitleSong")));
    UE_LOG(LogSaskartaStation, Log, TEXT("the title song: %s (one continuous ending player, flow %s)"), *Title->GetName(), *EndingMusicFlow.ToString());
}

void USaskartaRadioStation::RefreshEndingMusicVolume()
{
    if (Asset && TitleComp)
    {
        TitleComp->SetVolumeMultiplier(USaskartaStorySettings::Get()->StationVolume
            * FSaskartaStationLogic::DbToLinear(Asset->Config.Show.TitleGainDb) * UnderNow);
    }
}

void USaskartaRadioStation::SetEndingMusicFlow(FName State)
{
    const bool bHuman = State == FName(TEXT("Human"));
    const bool bTransmit = State == FName(TEXT("Transmit"));
    const bool bEnd = State == FName(TEXT("End"));
    const bool bCollapsing = State == FName(TEXT("Collapsing"));
    if (!bHuman && !bTransmit && !bEnd && !bCollapsing)
    {
        if (!EndingMusicFlow.IsNone() || (State == FName(TEXT("Title")) && bSignalDeath)) StopEndMusic(2.f);
        EndingMusicFlow = NAME_None;
        return;
    }
    const bool bChanged = EndingMusicFlow != State;
    EndingMusicFlow = State;
    if (!Asset) return; // OnStationAssetReady reapplies the current flow.
    if (bHuman || bTransmit || bEnd)
    {
        // The broadcast is finished, but its title score accompanies the person. Continue at CP4
        // enters here too, without replaying the signoff or the optional last song.
        bEndMusicStopped = false;
        if (!bSignalDeath) FadeOutAll(4.f, true);
        bSignalDeath = bStoppedForGood = true;
        if (UWorld* World = GetWorld())
        {
            World->GetTimerManager().ClearTimer(CodaTimer);
            World->GetTimerManager().ClearTimer(TitleTimer);
        }
        StartTitleSongTransition();
    }
    if (bChanged && TitleComp)
    {
        // AdjustVolume only ramps the playing cursor; FadeIn would issue a fresh PlayInternal.
        TitleComp->AdjustVolume(4.f, FSaskartaStationLogic::DbToLinear(FSaskartaStationLogic::EndingMusicDb(State)));
        UE_LOG(LogSaskartaStation, Log, TEXT("ending music continues: %s, %.0f dB"), *State.ToString(), FSaskartaStationLogic::EndingMusicDb(State));
    }
}

void USaskartaRadioStation::StopEndMusic(float FadeS)
{
    bEndMusicStopped = true;
    if (EndingTitleLoad.IsValid()) EndingTitleLoad->CancelHandle();
    EndingTitleLoad.Reset();
    if (UWorld* World = GetWorld())
    {
        World->GetTimerManager().ClearTimer(TitleTimer);
        World->GetTimerManager().ClearTimer(CodaTimer);
    }
    StopComp(CodaComp, FadeS);
    StopComp(TitleComp, FadeS);
    CodaComp = TitleComp = nullptr;
    EndingTitleLoop = nullptr;
}

// ============================================================================ debug

void USaskartaRadioStation::ForceNextSlot()
{
    if (Phase == ESaskartaStationPhase::Waiting)
    {
        NextActionAtS = Now();
    }
}

void USaskartaRadioStation::ForceSongBlock()
{
    Scheduler.ForceSongBlockDue();
    ForceNextSlot();
}

FString USaskartaRadioStation::DescribeState() const
{
    FString Out = FString::Printf(TEXT("mode %d, phase %d, started %d, suspended %d, idle %d, paused %d, q %.2f, next action in %.0f s, songs %d, resident %d/%d; "),
        static_cast<int32>(Mode), static_cast<int32>(Phase), bStarted ? 1 : 0, bSuspended ? 1 : 0, bIdle ? 1 : 0, bMenuPaused ? 1 : 0, Quality,
        NextActionAtS - Now(), AvailableSongs.Num(), Loads.Num(), Prefetch.NumResident());
    Out += bShowMode ? Show.Describe(ShowNow()) : Scheduler.DescribeBags();
    return Out;
}

namespace SaskartaRadio
{
    static USaskartaRadioStation* StationFor(UWorld* World)
    {
        USaskartaRadioStation* S = World ? World->GetSubsystem<USaskartaRadioStation>() : nullptr;
        if (!S)
        {
            UE_LOG(LogSaskartaStation, Warning, TEXT("no station in this world (start PIE or a game world)"));
        }
        return S;
    }

    /** The station's data (a debug command may load it synchronously when no station has it yet). */
    static USaskartaStationAsset* DebugStationData(UWorld* World)
    {
        USaskartaRadioStation* S = World ? World->GetSubsystem<USaskartaRadioStation>() : nullptr;
        if (S && S->GetStationAsset())
        {
            return S->GetStationAsset();
        }
        return USaskartaStationImport::LoadStationOrImportTransient(nullptr);
    }

    static FAutoConsoleCommandWithWorldAndArgs CmdNext(TEXT("Saskarta.Station.Next"), TEXT("Start the next station slot now."),
        FConsoleCommandWithWorldAndArgsDelegate::CreateLambda([](const TArray<FString>&, UWorld* World)
        {
            if (USaskartaRadioStation* S = StationFor(World)) S->ForceNextSlot();
        }));

    static FAutoConsoleCommandWithWorldAndArgs CmdSong(TEXT("Saskarta.Station.Song"), TEXT("Make a song block due now (shuffle mode)."),
        FConsoleCommandWithWorldAndArgsDelegate::CreateLambda([](const TArray<FString>&, UWorld* World)
        {
            if (USaskartaRadioStation* S = StationFor(World)) S->ForceSongBlock();
        }));

    static FAutoConsoleCommandWithWorldAndArgs CmdDebug(TEXT("Saskarta.Station.Debug"), TEXT("Log the station state: bags or the show (act, next backbone item, pools left, reaction cooldowns)."),
        FConsoleCommandWithWorldAndArgsDelegate::CreateLambda([](const TArray<FString>&, UWorld* World)
        {
            if (USaskartaRadioStation* S = StationFor(World)) UE_LOG(LogSaskartaStation, Log, TEXT("%s"), *S->DescribeState());
        }));

    static FAutoConsoleCommandWithWorldAndArgs CmdReact(TEXT("Saskarta.Station.React"),
        TEXT("Saskarta.Station.React <EVENT> [close]: fire a show reaction event (LIGHTNING, DROPOUT, STORM_UP, AFTER_TAPE, SILENCE, STOPPED, OFFROAD, PASSING_POI, RADIO_BACK_ON, RESUMED)."),
        FConsoleCommandWithWorldAndArgsDelegate::CreateLambda([](const TArray<FString>& Args, UWorld* World)
        {
            USaskartaRadioStation* S = StationFor(World);
            if (!S || Args.Num() == 0)
            {
                return;
            }
            const bool bQueued = S->FireShowEvent(FName(*Args[0].ToUpper()), Args.Num() > 1);
            UE_LOG(LogSaskartaStation, Log, TEXT("React %s: %s"), *Args[0], bQueued ? TEXT("queued") : TEXT("ignored (show off, act gate, cooldown or the roll)"));
            S->ForceNextSlot();
        }));

    static FAutoConsoleCommandWithWorldAndArgs CmdDryRun(TEXT("Saskarta.Station.DryRun"),
        TEXT("Saskarta.Station.DryRun [minutes=20] [seed=1]: simulate the shuffle schedule in the log (no audio, no story)."),
        FConsoleCommandWithWorldAndArgsDelegate::CreateLambda([](const TArray<FString>& Args, UWorld* World)
        {
            const float Minutes = Args.Num() > 0 ? FCString::Atof(*Args[0]) : 20.f;
            const int32 Seed = Args.Num() > 1 ? FCString::Atoi(*Args[1]) : 1;
            if (USaskartaStationAsset* A = DebugStationData(World))
            {
                TArray<FName> Songs;
                for (const FSaskartaStationSong& S : A->Config.Songs) Songs.Add(S.Id);
                TArray<FString> Log;
                SaskartaStationDryRun(A->Config, Minutes * 60.f, Seed, Songs, 85.f, &Log);
                for (const FString& L : Log) UE_LOG(LogSaskartaStation, Log, TEXT("%s"), *L);
            }
        }));

    static FAutoConsoleCommandWithWorldAndArgs CmdShowDryRun(TEXT("Saskarta.Station.ShowDryRun"),
        TEXT("Saskarta.Station.ShowDryRun <speed_mps=3> [stop_at_m stop_s] [seed]: simulate the live show over a whole drive (the story beats as 12 s lines) and print the timeline."),
        FConsoleCommandWithWorldAndArgsDelegate::CreateLambda([](const TArray<FString>& Args, UWorld* World)
        {
            USaskartaStationAsset* A = DebugStationData(World);
            if (!A)
            {
                return;
            }
            FSaskartaShowSimParams P;
            P.SpeedMps = Args.Num() > 0 ? FMath::Max(0.1f, FCString::Atof(*Args[0])) : 3.f;
            if (Args.Num() > 2)
            {
                P.Stops.Add(FVector2f(FCString::Atof(*Args[1]), FCString::Atof(*Args[2])));
            }
            P.Seed = Args.Num() > 3 ? FCString::Atoi(*Args[3]) : 1;
            P.Beats = SaskartaShowDefaultBeats(12.f);
            P.EndRoadM = A->Config.Show.CollapseRoadM;
            for (const FSaskartaStationSong& S : A->Config.Songs) P.Songs.Add(S.Id);
            const FSaskartaShowSimResult R = SaskartaShowDryRun(A->Config, P);
            for (const FString& L : R.Log) UE_LOG(LogSaskartaStation, Log, TEXT("%s"), *L);
        }));
}
