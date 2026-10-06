// The Low Voice as one continuous live show (docs/story/RADIO_SHOW.md; station.json scheduler.mode "show" and
// the show block; task-RADIOSHOW-brief.md part B).
//
// Pure logic, no world and no UObjects: the runtime station (USaskartaRadioStation), the dry run
// (Saskarta.Station.ShowDryRun) and the tests (Saskarta.Station.Show.*) drive it with an injected clock
// (FSaskartaShowInput::NowS). It answers one question, "what plays next?":
//
//   1. the sign-off is done               -> nothing, ever again (the signal is dead);
//   2. the act holding the high-water road m (forward only). Leaving an act: a playing item finishes; its
//      optional items are dropped; its must = 2 items and its turn play; its must = 1 items play only if the road
//      is less than LateDropM past the act end; a carry item (Nuri's letter) moves to the front of the next act;
//   3. a due reaction ("the signal knows": act gate, per-event cooldown, the global cooldown, MaxPerAct, drawn
//      without replacement, dropped when it cannot start within ReactMaxWaitS of its event);
//   4. the next backbone item of the act, strictly in order, once the road reaches its at_m (or its chain_after /
//      after_beat / after_song is satisfied), if it fits the story gate. When the road outruns the backbone, an
//      optional item is dropped as soon as a later MUST of the act is due (a fast drive hears the MUSTs);
//   5. the act's song slot (intro over the song's start, outro over its tail);
//   6. otherwise the silence filler, current act only: a FILL (never two in a row; time checks in order, 240 s
//      apart), a LINGER line (no talk line within NoRepeatWindowS), a song replay with the act's links, a ROOM
//      murmur every 45-90 s, else room tone;
//   7. the sign-off: once B15's line has ended, everything else pending gives way; items are dropped (optional,
//      then MUST, then SHOW_A5_03) until SHOW_A5_04 + SHOW_A5_05 end before the collapse.
//
// The prefetch side: GetUpcoming() is the window the runtime keeps loaded (the next backbone items, every MUST
// left in the act, the next act's opening, the planned fill / linger line and the planned song block), and
// GetActReactionLines() the small reaction takes to pre-warm. FSaskartaPrefetchPlanner turns the wanted set into
// bounded load / release requests.
//
// Plain C++ types (not USTRUCTs) so nothing here pairs with a UCLASS name; the save payload is the reflected
// FSaskartaShowSaveState (SaskartaSaveGame.h).

#pragma once

#include "CoreMinimal.h"
#include "Math/RandomStream.h"
#include "SaskartaSaveGame.h"
#include "SaskartaStationAsset.h"
#include "SaskartaStationLogic.h"

enum class ESaskartaShowKind : uint8 { None, Backbone, SongSlot, Fill, Linger, Room, React, SongReplay, SongResume };

/** What the scheduler needs to know now. */
struct SASKARTACORE_API FSaskartaShowInput
{
    /** The show clock (the station's time; tests inject their own). */
    double NowS = 0.0;
    /** The carrier's high-water road m. */
    float RoadM = 0.f;
    float SpeedMps = 0.f;
    /** False while a story line plays or in its hold-off (nothing may start, not even the sign-off). */
    bool bGateOpen = true;
    /** The longest item that may start before the next story beat (the sign-off ignores it). */
    float MaxFitS = 1.0e6f;
    /** Seconds to the collapse beat (B18); < 0 = (CollapseRoadM - RoadM) / max(SpeedMps, 0.5). */
    float SecondsToCollapse = -1.f;
};

/** One pick: a voice item or a song block, as station parts. */
struct SASKARTACORE_API FSaskartaShowPick
{
    bool bValid = false;
    ESaskartaShowKind Kind = ESaskartaShowKind::None;
    /** The line id; for a song slot, the slot's id (SONGSLOT_A<n>). */
    FName Id;
    /** Song blocks: the links and the song. */
    FName IntroId;
    FName OutroId;
    FName SongId;
    /** Reactions: the event. */
    FName Event;
    int32 Act = 0;
    bool bTurn = false;
    bool bFinal = false;
    bool bSignoff = false;
    /** The parts to play (voice, song with OverlapPrevS, voice). */
    FSaskartaStationPick Slot;
    /** !bValid: ask again after this. */
    float RetryS = 0.5f;
};

struct SASKARTACORE_API FSaskartaShowVoiceRef
{
    FName Id;
    /** A song link's song (a named pickup VO_Station_<id>__<song> is preferred). */
    FName SongId;
};

/** The prefetch window, best first. */
struct SASKARTACORE_API FSaskartaShowUpcoming
{
    TArray<FSaskartaShowVoiceRef> Voices;
    TArray<FName> Songs;
};

class SASKARTACORE_API FSaskartaShowScheduler
{
public:
    /** Voice length (the take's duration, or the line's target_s when the take is missing: subtitle only). < 0 = unknown line. */
    using FVoiceLenFn = TFunctionRef<float(int32 /*SegmentIndex*/, FName /*SongId*/)>;
    /** Song length; < 0 = no asset. */
    using FSongLenFn = TFunctionRef<float(FName /*SongId*/)>;

    static const FName EvLightning;
    static const FName EvDropout;
    static const FName EvStormUp;
    static const FName EvAfterTape;
    static const FName EvSilence;
    static const FName EvStopped;
    static const FName EvOffroad;
    static const FName EvPassingPoi;
    static const FName EvRadioBackOn;
    static const FName EvResumed;

    void Init(const FSaskartaStationConfig& InConfig, int32 Seed);

    /** scheduler.mode == "show" with at least one act. */
    bool IsShowMode() const { return Config.Show.bShowMode && Acts.Num() > 0; }

    /** The shelf's songs with an asset (the last song is never among them). */
    void SetAvailableSongs(const TArray<FName>& Songs);

    /** Act changes, POIs passed, stops, event expiry and the plans. PickNext calls it too. */
    void Update(const FSaskartaShowInput& In);

    /** What plays next (not committed). */
    FSaskartaShowPick PickNext(const FSaskartaShowInput& In, FVoiceLenFn VoiceLen, FSongLenFn SongLen);

    /** A pick has started. */
    void Commit(const FSaskartaShowPick& Pick, double NowS);

    /** A pick has ended (the last line ends the show). */
    void MarkFinished(const FSaskartaShowPick& Pick, double NowS);

    /** The silence after a finished pick: BetweenItemsS, ChainGapS before a chained item or in the sign-off, AfterTurnS after a turn. */
    float DrawGapAfter(const FSaskartaShowPick& Pick);

    /** The first item after the station comes on (the show is already in progress). */
    float DrawFirstDelayS();

    /** An interrupted pick: heard under ReturnToBagIfHeardBelow, a backbone item goes back to the front, a pool line becomes unused. */
    void ReturnInterrupted(const FSaskartaShowPick& Pick, float HeardFraction, double NowS);

    /** A game event (LIGHTNING, DROPOUT, ...): rolls its probability and queues it. False = ignored (act gate, cooldown, the roll). */
    bool OnEvent(FName Event, double NowS, bool bClose = false);

    /** PASSING_POI from a zone (a Blueprint volume): the next POI of that zone not yet passed. */
    bool OnPoiZone(FName Zone, double NowS);

    /** A story line ended: its beat counts as ended (after_beat items), and a tied or plain AFTER_TAPE reaction is queued. */
    void OnStoryLineEnded(FName BeatId, double NowS);

    /** A beat finished (its lines are over). */
    void OnBeatFinished(FName BeatId);

    /** The next pick is a FILL (a Continue, the end of a cinematic): joining a show in progress. */
    void RequestOpenWithFill() { bOpenWithFill = true; }

    /** Resume a song that a story line cut, from the heard position after that line ends. */
    void RememberInterruptedSong(FName SongId, float PositionS, FName OutroId);

    /** Runtime integration: call after a real song component starts, including direct story resumes.
     * RemainingS is media duration minus its actual start cursor. Never call for missing/skipped media. */
    void NotifySongPlaybackStarted(FName SongId, float RemainingS, double NowS);

    FSaskartaShowSaveState SaveState(double NowS) const;

    /** Restores a saved show (ages become times before NowS). Joins with a FILL, except a valid unheard act-0 opening. */
    void LoadState(const FSaskartaShowSaveState& State, double NowS);

    /** The window to keep loaded: the next MaxBackbone items (after catch-up drops), every MUST left in the act, the next act's opening, the planned pool lines and song block. */
    FSaskartaShowUpcoming GetUpcoming(int32 MaxBackbone) const;

    /** The act's reaction takes not used yet (to pre-warm), POIs included. */
    void GetActReactionLines(int32 Act, TArray<FName>& Out) const;

    const TArray<FName>& GetRoomIds() const { return RoomIds; }

    int32 ActOfRoadM(float RoadM) const;
    int32 GetAct() const { return CurrentAct; }
    int32 NumActs() const { return Acts.Num(); }
    bool IsSignoffGateOpen() const { return bSignoffGate; }
    bool IsSignoffStarted() const { return bSignoffStarted; }
    bool IsSignoffDone() const { return bSignoffDone; }
    bool IsStopped() const { return bStopped; }
    FName PeekNextBackbone() const;
    float PeekNextBackboneAtM() const;
    bool HasPlayed(FName Id) const { return Played.Contains(Id); }
    bool WasDropped(FName Id) const { return Dropped.Contains(Id); }
    /** When a pool / reaction / link id last started; < -1e8 = never. */
    double LastUsedS(FName Id) const;
    int32 NumPendingEvents() const { return Pending.Num(); }
    int32 ReactsInAct(int32 Act) const { return ReactsPerAct.IsValidIndex(Act) ? ReactsPerAct[Act] : 0; }
    /** FILL and LINGER lines of the act that could play now (eligible and fitting), ignoring the no-two-FILLs rule. */
    int32 CountEligiblePool(const FSaskartaShowInput& In, FVoiceLenFn VoiceLen) const;
    int32 SegmentIndexOf(FName Id) const;
    const FSaskartaStationConfig& GetConfig() const { return Config; }
    FString Describe(double NowS) const;

    /** SONGSLOT_A<n>: the act's song_slot; its song_slots follow as SONGSLOT_A<n>_2, _3, ... */
    static FName SongSlotId(int32 Act, int32 Index = 0);
    /** SONGSLOT_OPEN: the opening song, before Act I's first line. */
    static FName OpeningSlotId();
    /** B15 matches B15 and B15_HIGH_VOICE_IN_RANGE. */
    static bool BeatMatches(FName AfterBeat, FName BeatId);

    FRandomStream Rand;

private:
    struct FEntry
    {
        FName Id;
        int32 SegIndex = INDEX_NONE;
        int32 Act = 0;
        int32 Must = 0;
        float AtM = -1.f;
        FName ChainAfter;
        FName AfterBeat;
        bool bSongSlot = false;
        /** The opening song (no links; played once when the station first comes on). */
        bool bOpening = false;
        /** A song slot's spec (fixed song and links). */
        FSaskartaShowSongSlot Slot;
        bool bAfterSong = false;
        bool bTurn = false;
        bool bFinal = false;
        bool bCarry = false;
    };

    struct FPendingEvent
    {
        FName Event;
        double AtS = 0.0;
        double ReadyAtS = 0.0;
        float MaxWaitS = 8.f;
        TArray<FName> Lines;
        bool bTied = false;
    };

    enum class ESource : uint8 { None, Front, Closing, Carry, Seq };

    void ResetRunState();
    const FSaskartaShowAct* ActConfig(int32 Act) const;
    bool HasSlot(int32 Act) const;
    /** Seconds the pending backbone still needs (the sign-off budget). */
    float PendingNeedS(FVoiceLenFn VoiceLen) const;
    bool QueueEvent(FName Event, double NowS, bool bClose, const TArray<FName>* Lines);
    const FEntry* FindEntry(FName Id) const;
    bool IsDone(FName Id) const { return Played.Contains(Id) || Dropped.Contains(Id); }
    bool InQueues(FName Id) const { return Front.Contains(Id) || Closing.Contains(Id) || Carry.Contains(Id); }
    void RemoveFromQueues(FName Id);
    void PruneQueues();
    bool IsOptional(const FEntry& E) const { return E.Must <= 0; }
    bool IsSignoffItem(FName Id) const { return Config.Show.SignoffItems.Contains(Id); }
    /** The next pending backbone entry and where it comes from (nullptr = none left in the act). */
    const FEntry* NextPending(ESource& OutSource) const;
    /** Pending entries in play order: the queues, then the act's sequence. */
    void PendingOrder(TArray<const FEntry*>& Out, bool bIncludeNextActOpening) const;
    bool LaterMustDue(const FEntry& E, float RoadM) const;
    bool IsDue(const FEntry& E, const FSaskartaShowInput& In, ESource Source) const;
    bool AfterBeatEnded(FName AfterBeat) const;
    bool SlotDone(int32 Act) const { return IsDone(SongSlotId(Act)); }
    float SecondsToCollapse(const FSaskartaShowInput& In) const;
    bool SignoffGateOpen(float RoadM) const;
    void EnterSignoff();
    void EnforceSignoffBudget(const FSaskartaShowInput& In, FVoiceLenFn VoiceLen);
    float EntryLen(const FEntry& E, FVoiceLenFn VoiceLen) const;
    void AdvanceAct(float RoadM, int32 Target);
    void PlanAhead(double NowS);

    // eligibility
    bool FillEligible(FName Id, double NowS) const;
    bool LingerEligible(FName Id, double NowS) const;
    bool LinkEligible(FName Id, double NowS) const;
    FName FirstTimeCheckDue(const FSaskartaShowAct& A, double NowS) const;
    bool ReactAllowedNow(FName Event, double NowS) const;
    bool LineInAct(FName Id, int32 Act) const;
    FName DrawFill(const FSaskartaShowAct& A, double NowS, const TFunction<bool(FName)>& Fits);
    FName DrawLinger(const FSaskartaShowAct& A, double NowS, const TFunction<bool(FName)>& Fits);
    FName DrawLink(const TArray<FName>& Pool, FName Exclude, double NowS);
    FName ChooseSlotSong(const FEntry& Slot);
    /** The song slot's intro / outro pools (none for the opening song). */
    const TArray<FName>* SlotIntros(const FEntry& Slot) const;
    const TArray<FName>* SlotOutros(const FEntry& Slot) const;
    FName ChooseReplaySong(double NowS, FName Avoid);

    // picks
    bool TryReaction(const FSaskartaShowInput& In, FVoiceLenFn VoiceLen, FSaskartaShowPick& P);
    bool TryBackbone(const FSaskartaShowInput& In, FVoiceLenFn VoiceLen, FSongLenFn SongLen, FSaskartaShowPick& P);
    bool TrySongResume(const FSaskartaShowInput& In, FVoiceLenFn VoiceLen, FSongLenFn SongLen, FSaskartaShowPick& P);
    bool TryFill(const FSaskartaShowInput& In, FVoiceLenFn VoiceLen, FSaskartaShowPick& P, bool bRelaxed);
    bool TryLinger(const FSaskartaShowInput& In, FVoiceLenFn VoiceLen, FSaskartaShowPick& P);
    bool TrySongReplay(const FSaskartaShowInput& In, FVoiceLenFn VoiceLen, FSongLenFn SongLen, FSaskartaShowPick& P);
    bool TryRoom(const FSaskartaShowInput& In, FVoiceLenFn VoiceLen, FSaskartaShowPick& P);
    void MakeVoicePick(FSaskartaShowPick& P, ESaskartaShowKind Kind, FName Id, float LenS) const;
    /** Eb leaving the room needs the actual preceding Act II song, including an interrupted cursor. */
    bool NeedsEbSeparation() const;
    bool IsEbSeparationSlot(FName Id) const;
    void TrackEbPlayback(const FSaskartaShowPick& Pick, double NowS);
    /** Intro (optional) + song + outro (optional) with the overlaps. False = no song. */
    bool MakeSongBlock(FSaskartaShowPick& P, ESaskartaShowKind Kind, FName Intro, FName Song, FName Outro, float SongStartAtS,
        FVoiceLenFn VoiceLen, FSongLenFn SongLen) const;

    FSaskartaStationConfig Config;
    /** Per act (index act - 1): the backbone with the song slot in place. */
    TArray<TArray<FEntry>> Acts;
    TMap<FName, int32> SegIndexById;
    TArray<FName> ShelfSongs;
    TArray<FName> RoomIds;

    int32 CurrentAct = 0;
    TSet<FName> Played;
    TSet<FName> Dropped;
    TArray<FName> Front;
    TArray<FName> Closing;
    TArray<FName> Carry;
    TSet<FName> SongsPlayed;
    TMap<FName, double> SongLastS;
    TMap<FName, double> UsedS;
    TMap<FName, double> EventLastS;
    double LastReactS = -1.0e9;
    /** Index = act (0 unused). */
    TArray<int32> ReactsPerAct;
    double LastTimeCheckS = -1.0e9;
    TSet<FName> PoisPassed;
    TSet<FName> EndedBeats;
    bool bSignoffGate = false;
    bool bSignoffStarted = false;
    bool bSignoffDone = false;
    bool bOpenWithFill = false;
    ESaskartaShowKind LastKind = ESaskartaShowKind::None;
    int32 FillsSinceBackbone = 0;
    double NextRoomAtS = -1.0e9;
    double LastFinishedS = -1.0e9;
    TArray<FPendingEvent> Pending;

    // stops
    bool bHaveAnchor = false;
    float AnchorRoadM = 0.f;
    double AnchorS = 0.0;
    bool bStopped = false;
    float StopRoadM = 0.f;
    /** The first Update after Init / LoadState marks the POIs behind as passed without reacting. */
    bool bNeedsSync = true;
    float LastRoadM = 0.f;

    // a song to resume after a Continue
    FName ResumeSongId;
    float ResumeSongPosS = 0.f;
    FName ResumeOutroId;

    // Completion is recorded in the existing Played save payload with a namespaced pending marker.
    // These transient timings measure the current committed playback attempt, never mark it complete at Commit.
    FName EbSeparationSong;
    double EbPlaybackStartS = -1.0e9;
    float EbPlaybackExpectedS = 0.f;

    // plans (the prefetch window)
    FName PlannedFill;
    FName PlannedLinger;
    FName PlannedSlotSong;
    /** The slot PlannedSlotSong / links were planned for. */
    FName PlannedSlotFor;
    FName PlannedSlotIntro;
    FName PlannedSlotOutro;
    FName PlannedReplaySong;
    FName PlannedReplayIntro;
    FName PlannedReplayOutro;
    double LastPlanS = -1.0e9;
};

/**
 * The bounded loaded set. Desired paths (best first) are requested up to MaxResident; a resident path neither
 * desired nor pinned (playing) for ReleaseGraceS is released; over the cap, the stalest unwanted paths go first.
 */
struct SASKARTACORE_API FSaskartaPrefetchPlanner
{
    int32 MaxResident = 64;
    double ReleaseGraceS = 4.0;

    /** Fills OutLoad (paths to request) and OutRelease (paths to let go), and updates the resident set. */
    void Plan(const TArray<FString>& Desired, const TSet<FString>& Pinned, double NowS, TArray<FString>& OutLoad, TArray<FString>& OutRelease);

    /** A path loaded on demand (outside the plan). */
    void Touch(const FString& Path, double NowS) { LastWantedS.Add(Path, NowS); }
    void Forget(const FString& Path) { LastWantedS.Remove(Path); }
    bool IsResident(const FString& Path) const { return LastWantedS.Contains(Path); }
    int32 NumResident() const { return LastWantedS.Num(); }
    void Reset() { LastWantedS.Reset(); }

private:
    TMap<FString, double> LastWantedS;
};

/** A story beat for the dry run: its radio line blocks the show for LineS once the road reaches RoadM. */
struct SASKARTACORE_API FSaskartaShowSimBeat
{
    FName Id;
    float RoadM = 0.f;
    float LineS = 12.f;
};

struct SASKARTACORE_API FSaskartaShowSimParams
{
    float SpeedMps = 3.f;
    float StartRoadM = 0.f;
    /** The drive ends here (the collapse). */
    float EndRoadM = 4790.f;
    /** (road m, seconds): the carrier stops there that long. */
    TArray<FVector2f> Stops;
    TArray<FSaskartaShowSimBeat> Beats;
    TArray<FName> Songs;
    float SongLenS = 150.f;
    /** Per-song lengths for a drive with the imported shelf; SongLenS remains the fallback. */
    TMap<FName, float> SongLengthsS;
    int32 Seed = 1;
    double MaxS = 6.0 * 3600.0;
    float StepS = 0.25f;
    float HoldoffS = 3.f;
    float LookaheadS = 12.f;
    float FitMarginS = 2.f;
    /** Called every step before the scheduler updates (tests inject events, watch the prefetch window). */
    TFunction<void(FSaskartaShowScheduler& /*Show*/, double /*NowS*/, float /*RoadM*/)> OnTick;
};

struct SASKARTACORE_API FSaskartaShowSimItem
{
    ESaskartaShowKind Kind = ESaskartaShowKind::None;
    FName Id;
    FName IntroId;
    FName OutroId;
    FName SongId;
    FName Event;
    int32 Act = 0;
    /** The act holding the road when it started. */
    int32 RoadAct = 0;
    double StartS = 0.0;
    double EndS = 0.0;
    float StartRoadM = 0.f;
    float EndRoadM = 0.f;
    bool bCut = false;
};

struct SASKARTACORE_API FSaskartaShowSimResult
{
    TArray<FSaskartaShowSimItem> Items;
    /** (start, end) seconds of each stop. */
    TArray<FVector2D> StopWindows;
    bool bSignoffDone = false;
    float FinalEndRoadM = -1.f;
    double EndS = 0.0;
    float EndRoadM = 0.f;
    /** Nothing picked with the gate open, SilenceMaxS of dead air, and a FILL / LINGER line still eligible. */
    int32 SilenceViolations = 0;
    TArray<FString> Log;
};

/** The default story beats with radio lines (RADIO_SHOW.md section 8), each LineS long. */
SASKARTACORE_API TArray<FSaskartaShowSimBeat> SaskartaShowDefaultBeats(float LineS = 12.f);

/** Simulates a drive (Saskarta.Station.ShowDryRun and the tests). InOut = nullptr: a fresh scheduler. */
SASKARTACORE_API FSaskartaShowSimResult SaskartaShowDryRun(const FSaskartaStationConfig& Config, const FSaskartaShowSimParams& Params,
    FSaskartaShowScheduler* InOutScheduler = nullptr, double StartS = 0.0);
