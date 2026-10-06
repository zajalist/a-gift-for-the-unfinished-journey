// Pure logic of the Low Voice station (STATION.md sections 1-6): shuffle bags, category
// choice, ID slots, song blocks, station time, the story gate, reception and take naming.
// No world and no UObjects: Saskarta.Station.* tests drive these directly, and the
// runtime station (USaskartaRadioStation) and the dry run share FSaskartaStationScheduler.
// Plain C++ types (not USTRUCTs), so nothing here pairs with a UCLASS name.

#pragma once

#include "CoreMinimal.h"
#include "Math/RandomStream.h"
#include "SaskartaStationAsset.h"

/** Weighted draw without replacement. Refills when empty; the refill never starts with the last item played. */
struct SASKARTACORE_API FSaskartaShuffleBag
{
    void Reset(const TArray<int32>& InItems, const TArray<float>& InWeights);

    /** Draws one item, skipping Excluded (they stay in the bag). INDEX_NONE if nothing is drawable. */
    int32 Draw(FRandomStream& Rand, const TSet<int32>* Excluded = nullptr);

    /** Puts a drawn item back (an interrupted segment heard under half, or a draw that did not fit). */
    void PutBack(int32 Item);

    int32 NumRemaining() const { return Remaining.Num(); }
    int32 NumItems() const { return Items.Num(); }
    bool Contains(int32 Item) const { return Remaining.Contains(Item); }
    int32 GetLastPlayed() const { return LastPlayed; }

private:
    float WeightOf(int32 Item) const;

    TArray<int32> Items;
    TArray<float> Weights;
    TArray<int32> Remaining;
    int32 LastPlayed = INDEX_NONE;
    bool bJustRefilled = false;
};

/** Station time: runs only while the station is on and not held or suspended. */
struct SASKARTACORE_API FSaskartaStationClock
{
    double StationTimeS = 0.0;
    double NextSongBlockAtS = 0.0;

    void Advance(double DtS, bool bRunning) { if (bRunning && DtS > 0.0) StationTimeS += DtS; }
    bool SongBlockDue() const { return StationTimeS >= NextSongBlockAtS; }
    void ScheduleNextSongBlock(FRandomStream& Rand, const FVector2f& IntervalS)
    {
        NextSongBlockAtS = StationTimeS + Rand.FRandRange(IntervalS.X, IntervalS.Y);
    }
};

enum class ESaskartaStationGate : uint8 { Open, StoryBusy, Holdoff, BeatTooClose, QuietRange, Idle };

enum class ESaskartaStationMode : uint8 { Off, On, Held, Stopped };

struct SASKARTACORE_API FSaskartaStationGateInput
{
    bool bStoryBusy = false;
    bool bIdle = false;
    float SecondsSinceStory = 1000.f;
    float SecondsToNextBeat = 1.0e6f;
    float RoadM = 0.f;
};

/** One part of a slot: a voice take, a static pause or a song. */
struct SASKARTACORE_API FSaskartaStationPart
{
    enum class EKind : uint8 { Voice, Static, Song };
    EKind Kind = EKind::Voice;
    /** Segment index into Config.Segments (Voice), else INDEX_NONE. */
    int32 SegmentIndex = INDEX_NONE;
    /** The song this part belongs to (song blocks), else None. */
    FName SongId;
    float DurationS = 0.f;
    /** RADIOSHOW: starts this long before the previous part ends (a song under its intro, an outro over the song's tail). */
    float OverlapPrevS = 0.f;
    /** RADIOSHOW: starts this far in (a song resumed after a Continue). */
    float StartAtS = 0.f;
};

struct SASKARTACORE_API FSaskartaStationPick
{
    bool bValid = false;
    bool bSongBlock = false;
    FName Category;
    TArray<FSaskartaStationPart> Parts;
    float TotalS = 0.f;
};

struct SASKARTACORE_API FSaskartaStationLogic
{
    /** A positive road fallback is a checkpoint for jumps; zero means wait for StartEvent. */
    static bool MayStartAtRoad(const FSaskartaStationConfig& Config, FName FlowState, float RoadM);

    static ESaskartaStationMode ModeFor(FName FlowState, bool bStarted, bool bSettingOn, bool bStoppedForGood, const FSaskartaStationConfig& Config);

    /** Category by weight, never Last (ID is not in this draw). None if no weights. */
    static FName PickCategory(const TMap<FName, float>& Weights, FName Last, FRandomStream& Rand);

    /** Slot numbers start at 1; every Nth slot is an ID. */
    static bool IsIdSlot(int32 SlotNumber, int32 Nth) { return Nth > 0 && SlotNumber > 0 && SlotNumber % Nth == 0; }

    static ESaskartaStationGate EvaluateGate(const FSaskartaStationGateInput& In, float SegmentS, const FSaskartaStationConfig& Config);

    /** The longest part that may start now: time to the next beat minus the margin (the gate's fit rule). */
    static float MaxFitS(const FSaskartaStationGateInput& In, const FSaskartaStationConfig& Config);

    /**
     * [ ... ] groups are kept only when every {KEY} inside has a non-empty value; then the
     * brackets go and placeholders are filled. No template: the plain text.
     */
    static FString FillTemplate(const FString& Template, const FString& PlainText, const TMap<FString, FString>& Values);

    /** "Song · {SONG} · {SINGER}", leaving out empty fields (no U+266A: the caption fonts lack it). */
    static FString SongCaption(const FString& Title, const FString& Singer);

    /** Piecewise linear in road m, clamped. 1 with no curve. */
    static float Quality(const TArray<FVector2f>& QualityByRoadM, float RoadM);

    /** Linear between the value at q = 1 (X) and at q = 0.25 (Y), clamped. */
    static float MapQ(float Q, const FVector2f& AtQ1AndQLow);

    /** Reception loss with the authored q=0 endpoint, before the intelligibility floor. */
    static float ReceptionVoiceDb(float Q, const FSaskartaStationConfig& Config);

    /** Ordinary reception remains audible; explicit radio power/repair ownership is separate. */
    static float ProgrammeGainDb(float Q, const FSaskartaStationConfig& Config);

    /** One title-track performance: subdued through the walk, softer under the report, open on credits. */
    static float EndingMusicDb(FName Flow);

    /** Dropouts per second at q: 0 at or above DropoutStartQ, up to DropoutRateAtLowQ at q = 0.25. */
    static float DropoutRate(float Q, const FSaskartaStationConfig& Config);

    static float DbToLinear(float Db) { return FMath::Pow(10.f, Db / 20.f); }

    /** LANE5: extra dB below q = 0.25: 0 at or above it, linear to AtQ0Db at q = 0. */
    static float BelowQuarterDb(float Q, float AtQ0Db) { return Q >= 0.25f ? 0.f : FMath::Lerp(AtQ0Db, 0.f, FMath::Clamp(Q / 0.25f, 0.f, 1.f)); }

    /** LANE5: the zone containing RoadM (FromRoadM <= RoadM < ToRoadM), or None. */
    static FName ZoneAt(const TArray<FSaskartaStationZone>& Zones, float RoadM);

    /** LANE5: the bag a segment lives in: its category, or ZONE_<zone> for a zone-tagged segment. */
    static FName BagKeyFor(const FSaskartaStationSegment& Segment);

    /** LANE5: the panel title for a category (CategoryLabels, else title case: WEATHER -> Weather). */
    static FString CategoryLabel(const TMap<FName, FString>& Labels, FName Category);

    /** An interrupted segment counts as played when at least Threshold of it was heard. */
    static bool CountsAsPlayed(float HeardS, float TotalS, float Threshold) { return TotalS <= 0.f || HeardS / TotalS >= Threshold; }

    /**
     * Host take asset object paths, best first: a named link pickup for SongId, then the
     * plain take; each first from <HostFolder>/Recorded (the user's recording) then
     * <HostFolder> (the TTS placeholder or an in-place replacement).
     */
    static TArray<FString> TakeCandidates(const FString& HostFolder, FName LineId, FName SongId);

    /** Returns the first runtime-priority path accepted by Exists, or empty when none are imported. */
    static FString FirstExistingTakeCandidate(const TArray<FString>& CandidatePaths,
        TFunctionRef<bool(const FString&)> Exists);

    static FString SongAssetPath(const FString& SongFolder, FName SongId);

    /** Ids listed in Saved/RadioRecordings/selected/_tts_manifest.json (the TTS placeholders). */
    static TSet<FName> ParseTtsManifest(const FString& Json);

    enum class ETakeSource : uint8 { Missing, Tts, User };

    /**
     * Which take is on disk: the user's (a raw take exists, or a selected WAV that the TTS
     * manifest does not list), the TTS placeholder (listed and no raw take), or none.
     */
    static ETakeSource ClassifyTake(FName LineId, const TSet<FName>& TtsIds, bool bSelectedWavExists, bool bRawTakeExists);
};

/**
 * The selection state machine shared by the runtime station and the dry run: one bag per
 * category, a song bag, the slot counter, the last category, the leaving spacing and the
 * station clock.
 */
class SASKARTACORE_API FSaskartaStationScheduler
{
public:
    /** Voice length for a segment (optionally a named link for a song). < 0 = no take: not drawable. */
    using FVoiceLenFn = TFunctionRef<float(int32 /*SegmentIndex*/, FName /*SongId*/)>;
    /** Song length. < 0 = no asset. */
    using FSongLenFn = TFunctionRef<float(FName /*SongId*/)>;

    void Init(const FSaskartaStationConfig& InConfig, int32 Seed);

    /** Picks the next slot (a song block if due and it fits, else a segment). Does not commit. */
    FSaskartaStationPick PickSlot(float MaxFitS, const TArray<FName>& AvailableSongs, FVoiceLenFn VoiceLen, FSongLenFn SongLen);

    /** Records a started pick: slot count, last category, leaving spacing, song clock. */
    void CommitPick(const FSaskartaStationPick& Pick);

    /** Returns a segment to its bag (heard under half). */
    void ReturnSegment(int32 SegmentIndex);

    /** Puts every drawn part of an uncommitted pick back. */
    void Unpick(const FSaskartaStationPick& Pick);

    float DrawGapS() { return Rand.FRandRange(Config.GapS.X, Config.GapS.Y); }
    float DrawFirstDelayS() { return Rand.FRandRange(Config.FirstSegmentDelayS.X, Config.FirstSegmentDelayS.Y); }
    float DrawAfterIdleDelayS() { return Rand.FRandRange(Config.AfterIdleDelayS.X, Config.AfterIdleDelayS.Y); }

    /** Forces the song block now (Saskarta.Station.Song). */
    void ForceSongBlockDue() { Clock.NextSongBlockAtS = Clock.StationTimeS; }

    const FSaskartaStationConfig& GetConfig() const { return Config; }
    int32 GetSlotCount() const { return SlotCount; }
    FName GetLastCategory() const { return LastCategory; }
    FString DescribeBags() const;

    FSaskartaStationClock Clock;
    FRandomStream Rand;

    /** LANE5: set by the station every update. CurrentZone is the reception zone (the panel); RoadM and Quality drive ZONE and FRAG draws. */
    FName CurrentZone;
    float CurrentRoadM = 0.f;
    float CurrentQuality = 1.f;

    /** The gap after a finished pick: FragmentGapAfterS after a FRAG line, else GapS. */
    float DrawGapAfter(const FSaskartaStationPick& Pick)
    {
        return Pick.Category == FName(TEXT("FRAG")) ? Rand.FRandRange(Config.FragmentGapAfterS.X, Config.FragmentGapAfterS.Y) : DrawGapS();
    }

private:
    int32 DrawFrom(FName Category, float MaxFitS, FName SongId, FVoiceLenFn VoiceLen, bool bApplyLeaving, float& OutLen);
    bool IsLeavingBlocked() const;
    void SyncSongBag(const TArray<FName>& AvailableSongs);

    FSaskartaStationConfig Config;
    TMap<FName, FSaskartaShuffleBag> Bags;
    FSaskartaShuffleBag SongBag;
    TArray<FName> SongBagIds;
    int32 SlotCount = 0;
    FName LastCategory;
    int32 SegmentsSinceLeaving = 1000;
};

/** Dry run of the schedule with no story (Saskarta.Station.DryRun and the tests). */
struct SASKARTACORE_API FSaskartaStationDryRunStats
{
    int32 Segments = 0;
    int32 Ids = 0;
    int32 SongBlocks = 0;
    int32 SameCategoryRepeats = 0;
    int32 IdSlotViolations = 0;
    int32 LeavingSpacingViolations = 0;
    float MinGapS = 1.0e9f;
    float MaxGapS = 0.f;
    float MinSongSpacingS = 1.0e9f;
};

SASKARTACORE_API FSaskartaStationDryRunStats SaskartaStationDryRun(const FSaskartaStationConfig& Config, float StationSeconds, int32 Seed,
    const TArray<FName>& Songs, float SongLengthS, TArray<FString>* OutLog);
