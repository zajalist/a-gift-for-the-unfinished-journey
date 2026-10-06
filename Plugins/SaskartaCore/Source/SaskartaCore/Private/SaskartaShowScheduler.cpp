// FSaskartaShowScheduler, FSaskartaPrefetchPlanner and the show dry run. See SaskartaShowScheduler.h and
// docs/story/RADIO_SHOW.md.

#include "SaskartaShowScheduler.h"

// The run checkpoint hooks (SaskartaSaveGame.h): the runner broadcasts them, the station listens.
FSaskartaRunSaveHook USaskartaSaveGame::OnWritingRun;
FSaskartaRunSaveHook USaskartaSaveGame::OnRestoredRun;

const FName FSaskartaShowScheduler::EvLightning(TEXT("LIGHTNING"));
const FName FSaskartaShowScheduler::EvDropout(TEXT("DROPOUT"));
const FName FSaskartaShowScheduler::EvStormUp(TEXT("STORM_UP"));
const FName FSaskartaShowScheduler::EvAfterTape(TEXT("AFTER_TAPE"));
const FName FSaskartaShowScheduler::EvSilence(TEXT("SILENCE"));
const FName FSaskartaShowScheduler::EvStopped(TEXT("STOPPED"));
const FName FSaskartaShowScheduler::EvOffroad(TEXT("OFFROAD"));
const FName FSaskartaShowScheduler::EvPassingPoi(TEXT("PASSING_POI"));
const FName FSaskartaShowScheduler::EvRadioBackOn(TEXT("RADIO_BACK_ON"));
const FName FSaskartaShowScheduler::EvResumed(TEXT("RESUMED"));

namespace SaskartaShow
{
    static const FName CatRoom(TEXT("ROOM"));
    static const FName CatReact(TEXT("REACT"));
    static const FName CatSongIn(TEXT("SONGIN"));
    static const FName EbHere(TEXT("SHOW_A2_11"));
    static const FName EbGone(TEXT("SHOW_A3_01"));
    // Internal save markers are not programme entries or dialogue, so old saves remain readable.
    static const FName EbSongPending(TEXT("__Saskarta_EbSongPending_v13"));
    static const FName EbSongRetry(TEXT("__Saskarta_EbSongRetry_v13"));

    /** An after_beat item also becomes due this far past its at_m when its beat never ends (the story is off). */
    static constexpr float AfterBeatFallbackM = 60.f;
    /** A POI passed further back than this (a teleport, a Continue) gets no reaction. */
    static constexpr float PoiLateM = 150.f;
    /** A song slot's length when estimating the sign-off budget. */
    static constexpr float SlotEstimateS = 160.f;
    /** Optional slots may start if the song gets a real opening before the next story line cuts it. */
    static constexpr float MinSongWindowS = 25.f;
    /** Events that play after a song rather than expiring during it. */
    static constexpr float AfterSongWaitS = 300.f;
    /** A tied AFTER_TAPE line (after B11, B15) waits this long for the hold-off and the gate. */
    static constexpr float TiedWaitS = 30.f;
    /** The repeat pool: quiet (static / room tone) before an already-heard flavour line is re-aired. */
    static constexpr double RepeatQuietS = 12.0;
    /** The repeat pool: a line is re-aired at most this often. */
    static constexpr double RepeatMinAgeS = 150.0;

    static const TCHAR* KindName(ESaskartaShowKind K)
    {
        switch (K)
        {
        case ESaskartaShowKind::Backbone: return TEXT("SHOW");
        case ESaskartaShowKind::SongSlot: return TEXT("SONG");
        case ESaskartaShowKind::Fill: return TEXT("FILL");
        case ESaskartaShowKind::Linger: return TEXT("LINGER");
        case ESaskartaShowKind::Room: return TEXT("ROOM");
        case ESaskartaShowKind::React: return TEXT("REACT");
        case ESaskartaShowKind::SongReplay: return TEXT("REPLAY");
        case ESaskartaShowKind::SongResume: return TEXT("RESUME");
        default: return TEXT("-");
        }
    }
}

// ============================================================================ setup

FName FSaskartaShowScheduler::SongSlotId(int32 Act, int32 Index)
{
    return Index <= 0 ? FName(*FString::Printf(TEXT("SONGSLOT_A%d"), Act)) : FName(*FString::Printf(TEXT("SONGSLOT_A%d_%d"), Act, Index + 1));
}

FName FSaskartaShowScheduler::OpeningSlotId()
{
    return FName(TEXT("SONGSLOT_OPEN"));
}

bool FSaskartaShowScheduler::BeatMatches(FName AfterBeat, FName BeatId)
{
    if (AfterBeat.IsNone() || BeatId.IsNone())
    {
        return false;
    }
    if (AfterBeat == BeatId)
    {
        return true;
    }
    const FString Prefix = AfterBeat.ToString() + TEXT("_");
    return BeatId.ToString().StartsWith(Prefix, ESearchCase::IgnoreCase);
}

void FSaskartaShowScheduler::Init(const FSaskartaStationConfig& InConfig, int32 Seed)
{
    Config = InConfig;
    Rand.Initialize(Seed);
    Acts.Reset();
    SegIndexById.Reset();
    RoomIds.Reset();
    ShelfSongs.Reset();
    for (int32 i = 0; i < Config.Segments.Num(); ++i)
    {
        const FSaskartaStationSegment& S = Config.Segments[i];
        SegIndexById.Add(S.Id, i);
        if (S.Category == SaskartaShow::CatRoom)
        {
            RoomIds.Add(S.Id);
        }
    }
    FSaskartaShowConfig& Show = Config.Show;
    Show.Acts.Sort([](const FSaskartaShowAct& A, const FSaskartaShowAct& B) { return A.Act < B.Act; });
    for (int32 a = 0; a < Show.Acts.Num(); ++a)
    {
        // Acts are numbered 1..N in road order.
        FSaskartaShowAct& A = Show.Acts[a];
        A.Act = a + 1;
        TArray<FEntry>& Seq = Acts.AddDefaulted_GetRef();
        // The act's song slots: song_slot first (SONGSLOT_A<n>), then song_slots (SONGSLOT_A<n>_2, ...).
        TArray<FSaskartaShowSongSlot> Slots;
        if (!A.SongSlotAfter.IsNone())
        {
            FSaskartaShowSongSlot& First = Slots.AddDefaulted_GetRef();
            First.After = A.SongSlotAfter;
            First.bMust = A.bSongSlotMust;
            First.Song = A.SongSlotSong;
            First.IntroFixed = A.SongIntroFixed;
            First.OutroFixed = A.SongOutroFixed;
        }
        Slots.Append(A.SongSlots);
        if (a == 0 && !Show.OpeningSong.IsNone())
        {
            // The opening song: the station comes on mid-song and Act I's first line is the host coming back from it.
            FEntry Open;
            Open.Id = OpeningSlotId();
            Open.Act = A.Act;
            Open.Must = 1; // never dropped for a later MUST that is due (it is first); dropped once Act I is left
            Open.bSongSlot = true;
            Open.bOpening = true;
            Open.Slot.Song = Show.OpeningSong;
            Open.Slot.StartAtS = Show.OpeningSongStartAtS;
            Seq.Add(Open);
        }
        for (const FName& Id : A.Backbone)
        {
            const int32* Idx = SegIndexById.Find(Id);
            if (!Idx)
            {
                continue; // a backbone id with no line: skipped
            }
            const FSaskartaStationSegment& S = Config.Segments[*Idx];
            FEntry E;
            E.Id = Id;
            E.SegIndex = *Idx;
            E.Act = A.Act;
            E.Must = S.Must;
            E.AtM = S.AtRoadM;
            E.ChainAfter = S.ChainAfter;
            E.AfterBeat = S.AfterBeat;
            E.bAfterSong = S.bAfterSong;
            E.bTurn = S.bTurn;
            E.bFinal = S.bFinal;
            E.bCarry = S.bCarry;
            Seq.Add(E);
            for (int32 k = 0; k < Slots.Num(); ++k)
            {
                if (Slots[k].After != Id) continue;
                FEntry Slot;
                Slot.Id = SongSlotId(A.Act, k);
                Slot.Act = A.Act;
                Slot.Must = Slots[k].bMust ? 2 : 0;
                Slot.bSongSlot = true;
                Slot.Slot = Slots[k];
                Seq.Add(Slot);
            }
        }
    }
    if (Show.MaxPerAct.Num() == 0)
    {
        Show.MaxPerAct = { 3, 5, 4, 5, 3 };
    }
    ResetRunState();
}

void FSaskartaShowScheduler::ResetRunState()
{
    CurrentAct = 0;
    Played.Reset();
    Dropped.Reset();
    Front.Reset();
    Closing.Reset();
    Carry.Reset();
    SongsPlayed.Reset();
    SongLastS.Reset();
    UsedS.Reset();
    EventLastS.Reset();
    LastReactS = -1.0e9;
    ReactsPerAct.Reset();
    ReactsPerAct.SetNumZeroed(Acts.Num() + 1);
    LastTimeCheckS = -1.0e9;
    PoisPassed.Reset();
    EndedBeats.Reset();
    bSignoffGate = false;
    bSignoffStarted = false;
    bSignoffDone = false;
    bOpenWithFill = false;
    LastKind = ESaskartaShowKind::None;
    FillsSinceBackbone = 0;
    NextRoomAtS = -1.0e9;
    LastFinishedS = -1.0e9;
    Pending.Reset();
    bHaveAnchor = false;
    AnchorRoadM = 0.f;
    AnchorS = 0.0;
    bStopped = false;
    StopRoadM = 0.f;
    bNeedsSync = true;
    LastRoadM = 0.f;
    ResumeSongId = NAME_None;
    ResumeSongPosS = 0.f;
    ResumeOutroId = NAME_None;
    EbSeparationSong = NAME_None;
    EbPlaybackStartS = -1.0e9;
    EbPlaybackExpectedS = 0.f;
    PlannedFill = PlannedLinger = NAME_None;
    PlannedSlotSong = PlannedSlotIntro = PlannedSlotOutro = PlannedSlotFor = NAME_None;
    PlannedReplaySong = PlannedReplayIntro = PlannedReplayOutro = NAME_None;
}

void FSaskartaShowScheduler::SetAvailableSongs(const TArray<FName>& Songs)
{
    ShelfSongs = Songs;
}

// ============================================================================ lookups

const FSaskartaShowAct* FSaskartaShowScheduler::ActConfig(int32 Act) const
{
    return Config.Show.Acts.IsValidIndex(Act - 1) ? &Config.Show.Acts[Act - 1] : nullptr;
}

const FSaskartaShowScheduler::FEntry* FSaskartaShowScheduler::FindEntry(FName Id) const
{
    for (const TArray<FEntry>& Seq : Acts)
    {
        for (const FEntry& E : Seq)
        {
            if (E.Id == Id) return &E;
        }
    }
    return nullptr;
}

int32 FSaskartaShowScheduler::SegmentIndexOf(FName Id) const
{
    const int32* Idx = SegIndexById.Find(Id);
    return Idx ? *Idx : INDEX_NONE;
}

int32 FSaskartaShowScheduler::ActOfRoadM(float RoadM) const
{
    const TArray<FSaskartaShowAct>& A = Config.Show.Acts;
    if (A.Num() == 0)
    {
        return 0;
    }
    for (int32 i = 0; i < A.Num(); ++i)
    {
        if (RoadM < A[i].ToRoadM) return i + 1;
    }
    return A.Num();
}

double FSaskartaShowScheduler::LastUsedS(FName Id) const
{
    const double* T = UsedS.Find(Id);
    return T ? *T : -1.0e9;
}

bool FSaskartaShowScheduler::HasSlot(int32 Act) const
{
    return Acts.IsValidIndex(Act - 1) && Acts[Act - 1].ContainsByPredicate([](const FEntry& E) { return E.bSongSlot; });
}

bool FSaskartaShowScheduler::IsEbSeparationSlot(FName Id) const
{
    if (Id != SongSlotId(2)) return false;
    const FEntry* Entry = FindEntry(Id);
    return Entry && Entry->bSongSlot && Entry->Slot.After == SaskartaShow::EbHere;
}

bool FSaskartaShowScheduler::NeedsEbSeparation() const
{
    return CurrentAct <= 3 && !bSignoffGate && IsEbSeparationSlot(SongSlotId(2)) &&
        Played.Contains(SaskartaShow::EbHere) && !IsDone(SaskartaShow::EbGone) && !IsDone(SongSlotId(2));
}

void FSaskartaShowScheduler::TrackEbPlayback(const FSaskartaShowPick& Pick, double NowS)
{
    EbSeparationSong = Pick.SongId;
    EbPlaybackStartS = NowS;
    EbPlaybackExpectedS = Pick.Slot.TotalS;
}

void FSaskartaShowScheduler::RemoveFromQueues(FName Id)
{
    Front.Remove(Id);
    Closing.Remove(Id);
    Carry.Remove(Id);
}

void FSaskartaShowScheduler::PruneQueues()
{
    auto Prune = [this](TArray<FName>& Q) { Q.RemoveAll([this](const FName& Id) { return IsDone(Id) || !FindEntry(Id); }); };
    Prune(Front);
    Prune(Closing);
    Prune(Carry);
}

const FSaskartaShowScheduler::FEntry* FSaskartaShowScheduler::NextPending(ESource& OutSource) const
{
    const TArray<FName>* Queues[] = { &Front, &Closing, &Carry };
    const ESource Sources[] = { ESource::Front, ESource::Closing, ESource::Carry };
    for (int32 q = 0; q < 3; ++q)
    {
        for (const FName& Id : *Queues[q])
        {
            if (IsDone(Id)) continue;
            if (const FEntry* E = FindEntry(Id))
            {
                OutSource = Sources[q];
                return E;
            }
        }
    }
    if (Acts.IsValidIndex(CurrentAct - 1))
    {
        for (const FEntry& E : Acts[CurrentAct - 1])
        {
            if (!IsDone(E.Id) && !InQueues(E.Id))
            {
                OutSource = ESource::Seq;
                return &E;
            }
        }
    }
    OutSource = ESource::None;
    return nullptr;
}

void FSaskartaShowScheduler::PendingOrder(TArray<const FEntry*>& Out, bool bIncludeNextActOpening) const
{
    Out.Reset();
    TSet<FName> Seen;
    for (const TArray<FName>* Q : { &Front, &Closing, &Carry })
    {
        for (const FName& Id : *Q)
        {
            if (IsDone(Id) || Seen.Contains(Id)) continue;
            if (const FEntry* E = FindEntry(Id))
            {
                Out.Add(E);
                Seen.Add(Id);
            }
        }
    }
    if (Acts.IsValidIndex(CurrentAct - 1))
    {
        for (const FEntry& E : Acts[CurrentAct - 1])
        {
            if (!IsDone(E.Id) && !Seen.Contains(E.Id))
            {
                Out.Add(&E);
                Seen.Add(E.Id);
            }
        }
    }
    if (bIncludeNextActOpening && Acts.IsValidIndex(CurrentAct))
    {
        for (const FEntry& E : Acts[CurrentAct])
        {
            if (!IsDone(E.Id) && !Seen.Contains(E.Id))
            {
                Out.Add(&E);
                break;
            }
        }
    }
}

bool FSaskartaShowScheduler::AfterBeatEnded(FName AfterBeat) const
{
    for (const FName& B : EndedBeats)
    {
        if (BeatMatches(AfterBeat, B)) return true;
    }
    return false;
}

bool FSaskartaShowScheduler::LaterMustDue(const FEntry& E, float RoadM) const
{
    if (!Acts.IsValidIndex(E.Act - 1))
    {
        return false;
    }
    const TArray<FEntry>& Seq = Acts[E.Act - 1];
    bool bAfter = false;
    for (const FEntry& L : Seq)
    {
        if (&L == &E)
        {
            bAfter = true;
            continue;
        }
        if (!bAfter || IsDone(L.Id) || L.Must < 1 || !L.AfterBeat.IsNone())
        {
            continue;
        }
        if (L.AtM >= 0.f && RoadM >= L.AtM)
        {
            return true;
        }
    }
    return false;
}

bool FSaskartaShowScheduler::IsDue(const FEntry& E, const FSaskartaShowInput& In, ESource Source) const
{
    if (Source != ESource::Seq || E.bSongSlot)
    {
        return true; // queued items and the slot (reached in order) are due at once
    }
    if (!E.AfterBeat.IsNone())
    {
        return AfterBeatEnded(E.AfterBeat) || (E.AtM >= 0.f && In.RoadM >= E.AtM + SaskartaShow::AfterBeatFallbackM);
    }
    if (!E.ChainAfter.IsNone() && Played.Contains(E.ChainAfter))
    {
        return true;
    }
    if (E.bAfterSong && HasSlot(E.Act))
    {
        return SlotDone(E.Act);
    }
    return E.AtM < 0.f || In.RoadM >= E.AtM;
}

float FSaskartaShowScheduler::SecondsToCollapse(const FSaskartaShowInput& In) const
{
    if (In.SecondsToCollapse >= 0.f)
    {
        return In.SecondsToCollapse;
    }
    return (Config.Show.CollapseRoadM - In.RoadM) / FMath::Max(In.SpeedMps, 0.5f);
}

bool FSaskartaShowScheduler::SignoffGateOpen(float RoadM) const
{
    for (const FName& Id : Config.Show.SignoffItems)
    {
        const FEntry* E = FindEntry(Id);
        if (!E) continue;
        if (!E->AfterBeat.IsNone())
        {
            return AfterBeatEnded(E->AfterBeat) || (E->AtM >= 0.f && RoadM >= E->AtM + SaskartaShow::AfterBeatFallbackM);
        }
    }
    return false;
}

void FSaskartaShowScheduler::EnterSignoff()
{
    // Everything else gives way: the optional items still pending are dropped now; MUST ones only if the budget needs it.
    TArray<const FEntry*> Order;
    PendingOrder(Order, false);
    for (const FEntry* E : Order)
    {
        if (!IsSignoffItem(E->Id) && E->Must <= 0)
        {
            Dropped.Add(E->Id);
        }
    }
    PruneQueues();
    Pending.RemoveAll([](const FPendingEvent& P) { return !P.bTied; });
}

float FSaskartaShowScheduler::EntryLen(const FEntry& E, FVoiceLenFn VoiceLen) const
{
    if (E.bSongSlot)
    {
        return SaskartaShow::SlotEstimateS;
    }
    const float L = VoiceLen(E.SegIndex, NAME_None);
    return L > 0.f ? L : 0.f;
}

float FSaskartaShowScheduler::PendingNeedS(FVoiceLenFn VoiceLen) const
{
    TArray<const FEntry*> Order;
    PendingOrder(Order, false);
    float S = 0.f;
    for (const FEntry* E : Order)
    {
        S += EntryLen(*E, VoiceLen);
    }
    return S + Config.Show.ChainGapS * FMath::Max(0, Order.Num() - 1);
}

void FSaskartaShowScheduler::EnforceSignoffBudget(const FSaskartaShowInput& In, FVoiceLenFn VoiceLen)
{
    const float Budget = SecondsToCollapse(In);
    for (int32 Guard = 0; Guard < 64; ++Guard)
    {
        if (PendingNeedS(VoiceLen) <= Budget)
        {
            return;
        }
        TArray<const FEntry*> Order;
        PendingOrder(Order, false);
        // Tiers: optional, then MUST, then MUST-never-dropped outside the sign-off, then the sign-off's own MUST (SHOW_A5_03).
        const FEntry* Victim = nullptr;
        for (int32 Tier = 0; Tier < 4 && !Victim; ++Tier)
        {
            for (const FEntry* E : Order)
            {
                const bool bSign = IsSignoffItem(E->Id);
                const bool bMatch =
                    Tier == 0 ? (!bSign && E->Must <= 0) :
                    Tier == 1 ? (!bSign && E->Must == 1) :
                    Tier == 2 ? (!bSign && E->Must >= 2) :
                                (bSign && E->Must < 2 && !E->bFinal);
                if (bMatch)
                {
                    Victim = E;
                    break;
                }
            }
        }
        if (!Victim)
        {
            return; // only SHOW_A5_04 and SHOW_A5_05 are left: they are never dropped
        }
        Dropped.Add(Victim->Id);
        RemoveFromQueues(Victim->Id);
    }
}

// ============================================================================ update

void FSaskartaShowScheduler::AdvanceAct(float RoadM, int32 Target)
{
    const int32 Old = CurrentAct;
    const int32 New = Old + 1;
    const bool bJump = Target > New;
    const FSaskartaShowAct* OA = ActConfig(Old);
    const bool bLate = !OA || RoadM > OA->ToRoadM + Config.Show.LateDropM;
    if (bJump)
    {
        // A teleport over a whole act: what was still queued from before is moot.
        for (const FName& Id : Closing)
        {
            if (!IsDone(Id)) Dropped.Add(Id);
        }
        Closing.Reset();
    }
    if (Acts.IsValidIndex(Old - 1))
    {
        for (const FEntry& E : Acts[Old - 1])
        {
            if (IsDone(E.Id) || InQueues(E.Id))
            {
                continue;
            }
            if (E.bOpening)
            {
                Dropped.Add(E.Id); // an opening song never plays once Act I is behind
            }
            else if (E.bCarry && (bLate || bJump))
            {
                Carry.Add(E.Id);
            }
            else if (bJump)
            {
                Dropped.Add(E.Id);
            }
            else if (E.Must >= 2 || E.bTurn || (E.Must == 1 && !bLate))
            {
                Closing.Add(E.Id);
            }
            else
            {
                Dropped.Add(E.Id);
            }
        }
    }
    // A late carried letter follows the turn, but still precedes the new act's opening.
    if (!bJump)
    {
        for (int32 i = 0; i < Carry.Num();)
        {
            const FEntry* E = FindEntry(Carry[i]);
            if (E && E->Act == Old)
            {
                Closing.Add(Carry[i]);
                Carry.RemoveAt(i);
            }
            else
            {
                ++i;
            }
        }
    }
    // If the road outruns an act's song, finish its spoken closing lines first.
    // Most new openings precede carried music. Eb's departure is the exception:
    // the authored terminal Act II song represents time passing while she leaves.
    TArray<FName> DeferredSongs;
    for (int32 i = Closing.Num() - 1; i >= 0; --i)
    {
        const FEntry* E = FindEntry(Closing[i]);
        if (E && E->Act == Old && E->bSongSlot)
        {
            DeferredSongs.Insert(Closing[i], 0);
            Closing.RemoveAt(i);
        }
    }
    Closing.Append(DeferredSongs);
    if (!bJump && Acts.IsValidIndex(New - 1) && !Acts[New - 1].IsEmpty())
    {
        const FEntry& Opening = Acts[New - 1][0];
        if (Opening.Must >= 1 && !IsDone(Opening.Id) && !InQueues(Opening.Id))
        {
            const int32 SongIndex = Closing.IndexOfByPredicate([this, Old](FName Id)
            {
                const FEntry* E = FindEntry(Id);
                return E && E->Act == Old && E->bSongSlot;
            });
            if (SongIndex != INDEX_NONE)
            {
                const bool bEbTransition = Old == 2 && New == 3 && Opening.Id == SaskartaShow::EbGone && IsEbSeparationSlot(Closing[SongIndex]);
                Closing.Insert(Opening.Id, SongIndex + (bEbTransition ? 1 : 0));
            }
        }
    }
    CurrentAct = New;
    if (New > 3)
    {
        // A fast checkpoint jump joins the later show; it must not resurrect a skipped room transition.
        if (Played.Contains(SaskartaShow::EbSongPending))
        {
            Dropped.Add(SongSlotId(2));
            RemoveFromQueues(SongSlotId(2));
            if (!IsDone(SaskartaShow::EbGone))
            {
                Dropped.Add(SaskartaShow::EbGone);
                RemoveFromQueues(SaskartaShow::EbGone);
            }
        }
        Played.Remove(SaskartaShow::EbSongPending);
        Played.Remove(SaskartaShow::EbSongRetry);
        EbPlaybackStartS = -1.0e9;
    }
    PlannedFill = PlannedLinger = NAME_None;
    PlannedReplayIntro = PlannedReplayOutro = NAME_None;
}

bool FSaskartaShowScheduler::QueueEvent(FName Event, double NowS, bool bClose, const TArray<FName>* Lines)
{
    if (!IsShowMode() || bSignoffDone || bSignoffGate)
    {
        return false;
    }
    const FSaskartaShowEvent* Cfg = Config.Show.Events.Find(Event);
    if (!Cfg || !ReactAllowedNow(Event, NowS))
    {
        return false;
    }
    const float P = (bClose && Cfg->ProbabilityClose >= 0.f) ? Cfg->ProbabilityClose : Cfg->Probability;
    if (Rand.FRand() >= P)
    {
        return false;
    }
    FPendingEvent E;
    E.Event = Event;
    E.AtS = NowS;
    E.ReadyAtS = NowS + (Cfg->DelayS.Y > 0.f ? Rand.FRandRange(Cfg->DelayS.X, Cfg->DelayS.Y) : 0.f);
    E.MaxWaitS = Cfg->MaxWaitS >= 0.f ? Cfg->MaxWaitS
        : ((Event == EvRadioBackOn || Event == EvResumed) ? SaskartaShow::AfterSongWaitS : Config.Show.ReactMaxWaitS);
    E.Lines = Lines ? *Lines : Cfg->Lines;
    Pending.RemoveAll([Event](const FPendingEvent& X) { return !X.bTied && X.Event == Event; });
    Pending.Add(E);
    return true;
}

bool FSaskartaShowScheduler::OnEvent(FName Event, double NowS, bool bClose)
{
    if (Event == EvPassingPoi)
    {
        // A bare PASSING_POI: the next POI ahead within reach.
        for (const FSaskartaShowPoi& Poi : Config.Show.Pois)
        {
            if (!PoisPassed.Contains(Poi.Id) && FMath::Abs(Poi.RoadM - LastRoadM) <= SaskartaShow::PoiLateM)
            {
                PoisPassed.Add(Poi.Id);
                return QueueEvent(EvPassingPoi, NowS, false, &Poi.Lines);
            }
        }
        return false;
    }
    return QueueEvent(Event, NowS, bClose, nullptr);
}

bool FSaskartaShowScheduler::OnPoiZone(FName Zone, double NowS)
{
    for (const FSaskartaShowPoi& Poi : Config.Show.Pois)
    {
        if (Poi.Zone == Zone && !PoisPassed.Contains(Poi.Id))
        {
            PoisPassed.Add(Poi.Id);
            return QueueEvent(EvPassingPoi, NowS, false, &Poi.Lines);
        }
    }
    return false;
}

void FSaskartaShowScheduler::OnStoryLineEnded(FName BeatId, double NowS)
{
    if (!IsShowMode() || BeatId.IsNone())
    {
        return;
    }
    EndedBeats.Add(BeatId);
    if (bSignoffDone)
    {
        return;
    }
    // A line tied to this beat (REACT_AFTER_TAPE_06 after B11, _07 after B15) comes first, by after_beat_probability.
    TArray<FName> Tied;
    for (const FSaskartaStationSegment& S : Config.Segments)
    {
        if (S.Category == SaskartaShow::CatReact && !S.AfterBeat.IsNone() && BeatMatches(S.AfterBeat, BeatId) && !UsedS.Contains(S.Id))
        {
            Tied.Add(S.Id);
        }
    }
    if (Tied.Num() > 0)
    {
        const FSaskartaShowEvent* Cfg = Config.Show.Events.Find(EvAfterTape);
        if (Rand.FRand() < (Cfg ? Cfg->AfterBeatProbability : 1.f))
        {
            FPendingEvent E;
            E.Event = EvAfterTape;
            E.AtS = NowS;
            E.ReadyAtS = NowS;
            E.MaxWaitS = SaskartaShow::TiedWaitS;
            E.Lines = Tied;
            E.bTied = true;
            Pending.Add(E);
        }
        return;
    }
    QueueEvent(EvAfterTape, NowS, false, nullptr);
}

void FSaskartaShowScheduler::OnBeatFinished(FName BeatId)
{
    if (!BeatId.IsNone())
    {
        EndedBeats.Add(BeatId);
    }
}

void FSaskartaShowScheduler::Update(const FSaskartaShowInput& In)
{
    if (!IsShowMode())
    {
        return;
    }
    const double T = In.NowS;
    const int32 Target = FMath::Max(1, ActOfRoadM(In.RoadM));
    if (CurrentAct == 0)
    {
        // Joining late (the radio switched on mid-road, an old save): the acts behind are gone.
        CurrentAct = Target;
        for (int32 a = 1; a < Target; ++a)
        {
            for (const FEntry& E : Acts[a - 1])
            {
                if (!IsDone(E.Id)) Dropped.Add(E.Id);
            }
        }
    }
    while (CurrentAct < Target)
    {
        AdvanceAct(In.RoadM, Target);
    }
    LastRoadM = In.RoadM;

    // PASSING_POI: the road passes a ruin (once each; the ones behind at a restore pass silently).
    for (const FSaskartaShowPoi& Poi : Config.Show.Pois)
    {
        if (PoisPassed.Contains(Poi.Id) || In.RoadM < Poi.RoadM)
        {
            continue;
        }
        PoisPassed.Add(Poi.Id);
        if (!bNeedsSync && In.RoadM - Poi.RoadM <= SaskartaShow::PoiLateM)
        {
            QueueEvent(EvPassingPoi, T, false, &Poi.Lines);
        }
    }

    // STOPPED: less than 1 m of progress for StoppedAfterS; once per stop (a stop ends after 5 m).
    const FSaskartaShowEvent* StopCfg = Config.Show.Events.Find(EvStopped);
    const float StopAfterS = StopCfg ? StopCfg->StoppedAfterS : 20.f;
    if (!bHaveAnchor || In.RoadM > AnchorRoadM + 1.f)
    {
        bHaveAnchor = true;
        AnchorRoadM = In.RoadM;
        AnchorS = T;
    }
    if (bStopped && In.RoadM >= StopRoadM + 5.f)
    {
        bStopped = false;
    }
    if (!bStopped && T - AnchorS >= StopAfterS)
    {
        bStopped = true;
        StopRoadM = In.RoadM;
        QueueEvent(EvStopped, T, false, nullptr);
    }

    Pending.RemoveAll([T](const FPendingEvent& E) { return T > E.ReadyAtS + E.MaxWaitS; });

    if (!bSignoffGate && SignoffGateOpen(In.RoadM))
    {
        bSignoffGate = true;
        EnterSignoff();
    }
    PlanAhead(T);
    bNeedsSync = false;
}

// ============================================================================ eligibility and draws

bool FSaskartaShowScheduler::LineInAct(FName Id, int32 Act) const
{
    const int32 Idx = SegmentIndexOf(Id);
    if (Idx == INDEX_NONE)
    {
        return false;
    }
    const FIntPoint& A = Config.Segments[Idx].Acts;
    return (A.X == 0 && A.Y == 0) || (Act >= A.X && Act <= A.Y);
}

bool FSaskartaShowScheduler::LinkEligible(FName Id, double NowS) const
{
    if (SegmentIndexOf(Id) == INDEX_NONE)
    {
        return false;
    }
    const double* T = UsedS.Find(Id);
    return !T || NowS - *T >= Config.Show.NoRepeatWindowS;
}

bool FSaskartaShowScheduler::LingerEligible(FName Id, double NowS) const
{
    return LinkEligible(Id, NowS);
}

bool FSaskartaShowScheduler::FillEligible(FName Id, double NowS) const
{
    const int32 Idx = SegmentIndexOf(Id);
    if (Idx == INDEX_NONE)
    {
        return false;
    }
    const FSaskartaStationSegment& S = Config.Segments[Idx];
    if (!S.bTimeCheck)
    {
        return LinkEligible(Id, NowS);
    }
    // A time check: never twice, in id order within its act, TimeCheckMinSpacingS apart (the clock only moves forward).
    if (UsedS.Contains(Id) || NowS - LastTimeCheckS < Config.Show.TimeCheckMinSpacingS)
    {
        return false;
    }
    const FSaskartaShowAct* A = ActConfig(S.Act);
    return !A || FirstTimeCheckDue(*A, NowS) == Id;
}

FName FSaskartaShowScheduler::FirstTimeCheckDue(const FSaskartaShowAct& A, double) const
{
    for (const FName& Id : A.Fills)
    {
        const int32 Idx = SegmentIndexOf(Id);
        if (Idx != INDEX_NONE && Config.Segments[Idx].bTimeCheck && !UsedS.Contains(Id))
        {
            return Id;
        }
    }
    return NAME_None;
}

bool FSaskartaShowScheduler::ReactAllowedNow(FName Event, double NowS) const
{
    const FSaskartaShowEvent* Cfg = Config.Show.Events.Find(Event);
    if (!Cfg || CurrentAct < FMath::Max(1, Cfg->MinAct))
    {
        return false;
    }
    if (const double* Last = EventLastS.Find(Event))
    {
        if (NowS - *Last < Cfg->CooldownS) return false;
    }
    if (NowS - LastReactS < Config.Show.GlobalCooldownS)
    {
        return false;
    }
    const int32 Max = Config.Show.MaxPerAct.IsValidIndex(CurrentAct - 1) ? Config.Show.MaxPerAct[CurrentAct - 1] : 99;
    return ReactsInAct(CurrentAct) < Max;
}

FName FSaskartaShowScheduler::DrawFill(const FSaskartaShowAct& A, double NowS, const TFunction<bool(FName)>& Fits)
{
    TArray<FName> Candidates;
    for (const FName& Id : A.Fills)
    {
        if (FillEligible(Id, NowS) && Fits(Id)) Candidates.Add(Id);
    }
    if (Candidates.Num() == 0)
    {
        return NAME_None;
    }
    return Candidates.Contains(PlannedFill) ? PlannedFill : Candidates[Rand.RandRange(0, Candidates.Num() - 1)];
}

FName FSaskartaShowScheduler::DrawLinger(const FSaskartaShowAct& A, double NowS, const TFunction<bool(FName)>& Fits)
{
    TArray<FName> Candidates;
    for (const FName& Id : A.Linger)
    {
        if (LingerEligible(Id, NowS) && Fits(Id)) Candidates.Add(Id);
    }
    if (Candidates.Num() == 0)
    {
        return NAME_None;
    }
    return Candidates.Contains(PlannedLinger) ? PlannedLinger : Candidates[Rand.RandRange(0, Candidates.Num() - 1)];
}

FName FSaskartaShowScheduler::DrawLink(const TArray<FName>& Pool, FName Exclude, double NowS)
{
    TArray<FName> Candidates;
    for (const FName& Id : Pool)
    {
        if (Id != Exclude && LinkEligible(Id, NowS)) Candidates.Add(Id);
    }
    return Candidates.Num() > 0 ? Candidates[Rand.RandRange(0, Candidates.Num() - 1)] : NAME_None;
}

const TArray<FName>* FSaskartaShowScheduler::SlotIntros(const FEntry& Slot) const
{
    const FSaskartaShowAct* A = Slot.bOpening ? nullptr : ActConfig(Slot.Act);
    return A ? &A->SongIntros : nullptr;
}

const TArray<FName>* FSaskartaShowScheduler::SlotOutros(const FEntry& Slot) const
{
    const FSaskartaShowAct* A = Slot.bOpening ? nullptr : ActConfig(Slot.Act);
    return A ? &A->SongOutros : nullptr;
}

FName FSaskartaShowScheduler::ChooseSlotSong(const FEntry& Slot)
{
    if (!Slot.Slot.Song.IsNone() && ShelfSongs.Contains(Slot.Slot.Song))
    {
        return Slot.Slot.Song;
    }
    // Spread the shelf: never the song heard last, nor a song fixed for a slot still ahead in this act
    // (Act I: the bag's mid-act song is not the act's closing hayaa), while another one is left.
    FName LastSong;
    double LastT = -1.0e18;
    for (const TPair<FName, double>& KV : SongLastS)
    {
        if (KV.Value > LastT)
        {
            LastT = KV.Value;
            LastSong = KV.Key;
        }
    }
    TSet<FName> Ahead;
    if (Acts.IsValidIndex(Slot.Act - 1))
    {
        for (const FEntry& E : Acts[Slot.Act - 1])
        {
            if (E.bSongSlot && E.Id != Slot.Id && !IsDone(E.Id) && !E.Slot.Song.IsNone()) Ahead.Add(E.Slot.Song);
        }
    }
    auto Spread = [&](TArray<FName>& Pool)
    {
        TArray<FName> Kept = Pool;
        Kept.RemoveAll([&](FName S) { return S == LastSong || Ahead.Contains(S); });
        if (Kept.Num() == 0)
        {
            Kept = Pool;
            Kept.Remove(LastSong);
        }
        if (Kept.Num() > 0) Pool = Kept;
    };
    // The song bag: a song not yet played in a slot, else the one played longest ago.
    TArray<FName> Fresh;
    for (const FName& S : ShelfSongs)
    {
        if (!SongsPlayed.Contains(S)) Fresh.Add(S);
    }
    Spread(Fresh);
    if (Fresh.Num() > 0 && !(Fresh.Num() == 1 && Fresh[0] == LastSong))
    {
        return Fresh[Rand.RandRange(0, Fresh.Num() - 1)];
    }
    FName Best;
    double BestT = 1.0e18;
    for (const FName& S : ShelfSongs)
    {
        const double* T = SongLastS.Find(S);
        const double V = T ? *T : -1.0e9;
        if (V < BestT)
        {
            BestT = V;
            Best = S;
        }
    }
    return Best;
}

FName FSaskartaShowScheduler::ChooseReplaySong(double NowS, FName Avoid)
{
    TArray<FName> Never;
    FName Oldest;
    double OldestT = 1.0e18;
    for (const FName& S : ShelfSongs)
    {
        const double* T = SongLastS.Find(S);
        if (T && NowS - *T < Config.Show.SongReplayMinSpacingS)
        {
            continue;
        }
        if (!T)
        {
            Never.Add(S);
        }
        else if (*T < OldestT && S != Avoid)
        {
            // Never the next slot's song (it would play twice back to back).
            OldestT = *T;
            Oldest = S;
        }
    }
    Never.Remove(Avoid);
    if (Never.Num() > 0)
    {
        return Never[Rand.RandRange(0, Never.Num() - 1)];
    }
    return Oldest; // None when only the next slot's song is left: no replay (the pools and the room fill)
}

void FSaskartaShowScheduler::PlanAhead(double NowS)
{
    const FSaskartaShowAct* A = ActConfig(CurrentAct);
    if (!A)
    {
        return;
    }
    const TFunction<bool(FName)> Any = [](FName) { return true; };
    if (PlannedFill.IsNone() || !A->Fills.Contains(PlannedFill) || !FillEligible(PlannedFill, NowS))
    {
        PlannedFill = NAME_None;
        PlannedFill = DrawFill(*A, NowS, Any);
    }
    if (PlannedLinger.IsNone() || !A->Linger.Contains(PlannedLinger) || !LingerEligible(PlannedLinger, NowS))
    {
        PlannedLinger = NAME_None;
        PlannedLinger = DrawLinger(*A, NowS, Any);
    }
    // The next song slot in play order (the Act III slot may still be closing while Act IV has begun).
    TArray<const FEntry*> Order;
    PendingOrder(Order, false);
    const FEntry* Slot = nullptr;
    for (const FEntry* E : Order)
    {
        if (E->bSongSlot)
        {
            Slot = E;
            break;
        }
    }
    if (Slot)
    {
        if (PlannedSlotFor != Slot->Id)
        {
            PlannedSlotSong = PlannedSlotIntro = PlannedSlotOutro = NAME_None;
            PlannedSlotFor = Slot->Id;
        }
        const FSaskartaShowSongSlot& SS = Slot->Slot;
        const TArray<FName>* Intros = SlotIntros(*Slot);
        const TArray<FName>* Outros = SlotOutros(*Slot);
        if (PlannedSlotSong.IsNone() || !ShelfSongs.Contains(PlannedSlotSong) || (SongsPlayed.Contains(PlannedSlotSong) && SongsPlayed.Num() < ShelfSongs.Num()))
        {
            PlannedSlotSong = ChooseSlotSong(*Slot);
        }
        if (!SS.IntroFixed.IsNone())
        {
            PlannedSlotIntro = SS.IntroFixed;
        }
        else if (!Intros)
        {
            PlannedSlotIntro = NAME_None;
        }
        else if (PlannedSlotIntro.IsNone() || !Intros->Contains(PlannedSlotIntro) || !LinkEligible(PlannedSlotIntro, NowS))
        {
            PlannedSlotIntro = DrawLink(*Intros, SS.IntroFixed, NowS);
        }
        if (!SS.OutroFixed.IsNone())
        {
            PlannedSlotOutro = SS.OutroFixed;
        }
        else if (!Outros)
        {
            PlannedSlotOutro = NAME_None;
        }
        else if (PlannedSlotOutro.IsNone() || !Outros->Contains(PlannedSlotOutro) || !LinkEligible(PlannedSlotOutro, NowS))
        {
            PlannedSlotOutro = DrawLink(*Outros, SS.OutroFixed, NowS);
        }
    }
    else
    {
        PlannedSlotSong = PlannedSlotIntro = PlannedSlotOutro = PlannedSlotFor = NAME_None;
    }
    // A linger replay (the act's own links, never the fixed last-song ones).
    const double* ReplayT = PlannedReplaySong.IsNone() ? nullptr : SongLastS.Find(PlannedReplaySong);
    if (PlannedReplaySong.IsNone() || PlannedReplaySong == PlannedSlotSong || !ShelfSongs.Contains(PlannedReplaySong) || (ReplayT && NowS - *ReplayT < Config.Show.SongReplayMinSpacingS))
    {
        PlannedReplaySong = ChooseReplaySong(NowS, PlannedSlotSong);
    }
    if (PlannedReplayIntro.IsNone() || !A->SongIntros.Contains(PlannedReplayIntro) || !LinkEligible(PlannedReplayIntro, NowS) || PlannedReplayIntro == PlannedSlotIntro)
    {
        PlannedReplayIntro = DrawLink(A->SongIntros, A->SongIntroFixed, NowS);
    }
    if (PlannedReplayOutro.IsNone() || !A->SongOutros.Contains(PlannedReplayOutro) || !LinkEligible(PlannedReplayOutro, NowS) || PlannedReplayOutro == PlannedSlotOutro)
    {
        PlannedReplayOutro = DrawLink(A->SongOutros, A->SongOutroFixed, NowS);
    }
}

// ============================================================================ picks

void FSaskartaShowScheduler::MakeVoicePick(FSaskartaShowPick& P, ESaskartaShowKind Kind, FName Id, float LenS) const
{
    P = FSaskartaShowPick();
    P.bValid = true;
    P.Kind = Kind;
    P.Id = Id;
    P.Act = CurrentAct;
    const int32 Idx = SegmentIndexOf(Id);
    FSaskartaStationPart Part;
    Part.Kind = FSaskartaStationPart::EKind::Voice;
    Part.SegmentIndex = Idx;
    Part.DurationS = LenS;
    P.Slot.bValid = true;
    P.Slot.Category = Idx != INDEX_NONE ? Config.Segments[Idx].Category : NAME_None;
    P.Slot.Parts.Add(Part);
    P.Slot.TotalS = LenS;
}

bool FSaskartaShowScheduler::MakeSongBlock(FSaskartaShowPick& P, ESaskartaShowKind Kind, FName Intro, FName Song, FName Outro, float SongStartAtS,
    FVoiceLenFn VoiceLen, FSongLenFn SongLen) const
{
    const float SongS = Song.IsNone() ? -1.f : SongLen(Song);
    if (SongS <= 0.f || SongStartAtS >= SongS - 1.f)
    {
        return false;
    }
    const FSaskartaShowConfig& S = Config.Show;
    P = FSaskartaShowPick();
    P.bValid = true;
    P.Kind = Kind;
    P.SongId = Song;
    P.Act = CurrentAct;
    P.Slot.bValid = true;
    P.Slot.bSongBlock = true;
    P.Slot.Category = SaskartaShow::CatSongIn;
    float Total = 0.f;
    float IntroS = 0.f;
    const int32 IntroIdx = Intro.IsNone() ? INDEX_NONE : SegmentIndexOf(Intro);
    if (IntroIdx != INDEX_NONE)
    {
        IntroS = VoiceLen(IntroIdx, Song);
    }
    if (IntroS > 0.f)
    {
        FSaskartaStationPart Part;
        Part.Kind = FSaskartaStationPart::EKind::Voice;
        Part.SegmentIndex = IntroIdx;
        Part.SongId = Song;
        Part.DurationS = IntroS;
        P.Slot.Parts.Add(Part);
        P.IntroId = Intro;
        Total += IntroS;
    }
    FSaskartaStationPart SongPart;
    SongPart.Kind = FSaskartaStationPart::EKind::Song;
    SongPart.SongId = Song;
    SongPart.DurationS = SongS;
    SongPart.StartAtS = SongStartAtS;
    SongPart.OverlapPrevS = IntroS > 0.f ? FMath::Min(S.SongIntroOverlapS, IntroS * 0.5f) : 0.f;
    P.Slot.Parts.Add(SongPart);
    const float SongHeardS = SongS - SongStartAtS;
    Total += SongHeardS - SongPart.OverlapPrevS;
    const int32 OutroIdx = Outro.IsNone() ? INDEX_NONE : SegmentIndexOf(Outro);
    const float OutroS = OutroIdx != INDEX_NONE ? VoiceLen(OutroIdx, Song) : -1.f;
    if (OutroS > 0.f)
    {
        FSaskartaStationPart Part;
        Part.Kind = FSaskartaStationPart::EKind::Voice;
        Part.SegmentIndex = OutroIdx;
        Part.SongId = Song;
        Part.DurationS = OutroS;
        Part.OverlapPrevS = FMath::Min(S.SongOutroOverTailS, SongHeardS * 0.25f);
        P.Slot.Parts.Add(Part);
        P.OutroId = Outro;
        Total += OutroS - Part.OverlapPrevS;
    }
    P.Slot.TotalS = Total;
    return true;
}

bool FSaskartaShowScheduler::TryReaction(const FSaskartaShowInput& In, FVoiceLenFn VoiceLen, FSaskartaShowPick& P)
{
    if (bSignoffDone || Pending.Num() == 0)
    {
        return false;
    }
    const double T = In.NowS;
    const float Budget = bSignoffGate ? SecondsToCollapse(In) - PendingNeedS(VoiceLen) : 1.0e9f;
    // Tied lines (after B11, B15) first, then the rest in the order they happened.
    for (int32 Pass = 0; Pass < 2; ++Pass)
    {
        for (int32 i = 0; i < Pending.Num(); ++i)
        {
            FPendingEvent& E = Pending[i];
            if (E.bTied != (Pass == 0) || T < E.ReadyAtS)
            {
                continue;
            }
            if (!E.bTied && (bSignoffGate || bSignoffStarted || !ReactAllowedNow(E.Event, T)))
            {
                Pending.RemoveAt(i--);
                continue;
            }
            TArray<FName> Lines;
            for (const FName& Id : E.Lines)
            {
                const int32 Idx = SegmentIndexOf(Id);
                if (Idx == INDEX_NONE || UsedS.Contains(Id) || !LineInAct(Id, CurrentAct))
                {
                    continue;
                }
                if (!E.bTied && !Config.Segments[Idx].AfterBeat.IsNone())
                {
                    continue; // a tied line only plays after its beat
                }
                const float L = VoiceLen(Idx, NAME_None);
                if (L < 0.f || L > In.MaxFitS || L > Budget)
                {
                    continue;
                }
                Lines.Add(Id);
            }
            if (Lines.Num() == 0)
            {
                Pending.RemoveAt(i--);
                continue;
            }
            const FName Pick = Lines[Rand.RandRange(0, Lines.Num() - 1)];
            const FName Ev = E.Event;
            MakeVoicePick(P, ESaskartaShowKind::React, Pick, VoiceLen(SegmentIndexOf(Pick), NAME_None));
            P.Event = Ev;
            return true;
        }
    }
    return false;
}

bool FSaskartaShowScheduler::TrySongResume(const FSaskartaShowInput& In, FVoiceLenFn VoiceLen, FSongLenFn SongLen, FSaskartaShowPick& P)
{
    if (ResumeSongId.IsNone())
    {
        return false;
    }
    FSaskartaShowPick Block;
    if (Played.Contains(SaskartaShow::EbSongPending) && ResumeSongId == EbSeparationSong)
    {
        const float Duration = SongLen(ResumeSongId);
        if (Duration > 0.f && ResumeSongPosS >= Duration - .5f)
        {
            // An authoritative interrupted/saved cursor has already reached the
            // end; do not replay a whole song because its tiny tail cannot form a block.
            Played.Add(SongSlotId(2));
            Played.Remove(SaskartaShow::EbSongPending);
            Played.Remove(SaskartaShow::EbSongRetry);
            RemoveFromQueues(SongSlotId(2));
            ResumeSongId = NAME_None;
            return false;
        }
    }
    if (!ShelfSongs.Contains(ResumeSongId) || !MakeSongBlock(Block, ESaskartaShowKind::SongResume, NAME_None, ResumeSongId, ResumeOutroId, ResumeSongPosS, VoiceLen, SongLen))
    {
        ResumeSongId = NAME_None; // gone, or nearly over: forget it
        return false;
    }
    if (In.MaxFitS < SaskartaShow::MinSongWindowS)
    {
        return false;
    }
    P = Block;
    return true;
}

bool FSaskartaShowScheduler::TryBackbone(const FSaskartaShowInput& In, FVoiceLenFn VoiceLen, FSongLenFn SongLen, FSaskartaShowPick& P)
{
    PruneQueues();
    if (bSignoffGate)
    {
        EnforceSignoffBudget(In, VoiceLen);
    }
    for (int32 Guard = 0; Guard < 256; ++Guard)
    {
        ESource Src = ESource::None;
        const FEntry* E = NextPending(Src);
        if (!E)
        {
            return false;
        }
        if (E->Id == SaskartaShow::EbGone && NeedsEbSeparation())
        {
            // A restored/closing queue may already contain the old reversed order.
            // Repair it using the same real terminal song, never a silent delay.
            if (Played.Contains(SaskartaShow::EbSongPending) && !ResumeSongId.IsNone()) return false;
            const FName Slot = SongSlotId(2);
            RemoveFromQueues(Slot);
            Front.Insert(Slot, 0);
            continue;
        }
        // The road has outrun the backbone: an optional item gives way to a later MUST that is already due.
        if (Src == ESource::Seq && IsOptional(*E) && LaterMustDue(*E, In.RoadM))
        {
            Dropped.Add(E->Id);
            continue;
        }
        if (!IsDue(*E, In, Src))
        {
            return false; // waiting for the road (or the story)
        }
        const bool bSign = IsSignoffItem(E->Id);
        if (E->bSongSlot)
        {
            const bool bPlanned = PlannedSlotFor == E->Id && !PlannedSlotSong.IsNone() && ShelfSongs.Contains(PlannedSlotSong);
            FName Song = bPlanned ? PlannedSlotSong : ChooseSlotSong(*E);
            if (!Song.IsNone() && SongLen(Song) <= 0.f)
            {
                // The planned song has no asset: any other shelf song.
                Song = NAME_None;
                for (const FName& S : ShelfSongs)
                {
                    if (SongLen(S) > 0.f)
                    {
                        Song = S;
                        break;
                    }
                }
            }
            if (Song.IsNone())
            {
                if (IsEbSeparationSlot(E->Id) && NeedsEbSeparation())
                {
                    Dropped.Add(SaskartaShow::EbGone);
                    RemoveFromQueues(SaskartaShow::EbGone);
                    Played.Remove(SaskartaShow::EbSongPending);
                }
                Dropped.Add(E->Id); // no song on the shelf: the slot is skipped (the turn after it still plays)
                continue;
            }
            const FSaskartaShowSongSlot& SS = E->Slot;
            const TArray<FName>* Intros = SlotIntros(*E);
            const TArray<FName>* Outros = SlotOutros(*E);
            const bool bPlannedLinks = PlannedSlotFor == E->Id;
            const FName Intro = !SS.IntroFixed.IsNone() ? SS.IntroFixed
                : !Intros ? NAME_None
                : ((bPlannedLinks && !PlannedSlotIntro.IsNone() && Intros->Contains(PlannedSlotIntro) && LinkEligible(PlannedSlotIntro, In.NowS)) ? PlannedSlotIntro
                    : DrawLink(*Intros, SS.IntroFixed, In.NowS));
            const FName Outro = !SS.OutroFixed.IsNone() ? SS.OutroFixed
                : !Outros ? NAME_None
                : ((bPlannedLinks && !PlannedSlotOutro.IsNone() && Outros->Contains(PlannedSlotOutro) && LinkEligible(PlannedSlotOutro, In.NowS)) ? PlannedSlotOutro
                    : DrawLink(*Outros, SS.OutroFixed, In.NowS));
            FSaskartaShowPick Block;
            if (!MakeSongBlock(Block, ESaskartaShowKind::SongSlot, Intro, Song, Outro, SS.StartAtS, VoiceLen, SongLen))
            {
                if (IsEbSeparationSlot(E->Id) && NeedsEbSeparation())
                {
                    Dropped.Add(SaskartaShow::EbGone);
                    RemoveFromQueues(SaskartaShow::EbGone);
                    Played.Remove(SaskartaShow::EbSongPending);
                }
                Dropped.Add(E->Id);
                continue;
            }
            // The song can be cut by a story line and resumed. An optional slot needs a useful first window,
            // while a MUST slot still needs only its intro to fit.
            const float FirstS = Block.Slot.Parts[0].Kind == FSaskartaStationPart::EKind::Voice ? Block.Slot.Parts[0].DurationS : 0.f;
            const bool bFits = E->Must >= 2 ? FirstS <= In.MaxFitS : FirstS + SaskartaShow::MinSongWindowS <= In.MaxFitS;
            if (!bFits)
            {
                return false;
            }
            Block.Id = E->Id;
            Block.Act = E->Act;
            P = Block;
            return true;
        }
        const float Len = VoiceLen(E->SegIndex, NAME_None);
        if (Len < 0.f)
        {
            Dropped.Add(E->Id);
            continue;
        }
        if (!bSign && Len > In.MaxFitS)
        {
            return false; // it waits for the story beat to pass; the pools fill the time
        }
        MakeVoicePick(P, ESaskartaShowKind::Backbone, E->Id, Len);
        P.Act = E->Act;
        P.bTurn = E->bTurn;
        P.bFinal = E->bFinal;
        P.bSignoff = bSign;
        return true;
    }
    return false;
}

bool FSaskartaShowScheduler::TryFill(const FSaskartaShowInput& In, FVoiceLenFn VoiceLen, FSaskartaShowPick& P, bool bRelaxed)
{
    const FSaskartaShowAct* A = ActConfig(CurrentAct);
    if (!A)
    {
        return false;
    }
    // Never two FILLs in a row, unless the air has been dead for nearly SilenceMaxS and nothing else can play.
    const bool bDeadAir = In.NowS - LastFinishedS >= Config.Show.SilenceMaxS - 0.5f;
    if (LastKind == ESaskartaShowKind::Fill && !(bRelaxed && bDeadAir))
    {
        return false;
    }
    // At most one FILL between two backbone items while moving.
    if (!bRelaxed && FillsSinceBackbone >= 1 && !bStopped)
    {
        return false;
    }
    const TFunction<bool(FName)> Fits = [this, &In, &VoiceLen](FName Id)
    {
        const float L = VoiceLen(SegmentIndexOf(Id), NAME_None);
        return L >= 0.f && L <= In.MaxFitS;
    };
    const FName Id = DrawFill(*A, In.NowS, Fits);
    if (Id.IsNone())
    {
        return false;
    }
    MakeVoicePick(P, ESaskartaShowKind::Fill, Id, VoiceLen(SegmentIndexOf(Id), NAME_None));
    return true;
}

bool FSaskartaShowScheduler::TryLinger(const FSaskartaShowInput& In, FVoiceLenFn VoiceLen, FSaskartaShowPick& P)
{
    const FSaskartaShowAct* A = ActConfig(CurrentAct);
    if (!A)
    {
        return false;
    }
    const TFunction<bool(FName)> Fits = [this, &In, &VoiceLen](FName Id)
    {
        const float L = VoiceLen(SegmentIndexOf(Id), NAME_None);
        return L >= 0.f && L <= In.MaxFitS;
    };
    const FName Id = DrawLinger(*A, In.NowS, Fits);
    if (Id.IsNone())
    {
        return false;
    }
    MakeVoicePick(P, ESaskartaShowKind::Linger, Id, VoiceLen(SegmentIndexOf(Id), NAME_None));
    return true;
}

bool FSaskartaShowScheduler::TrySongReplay(const FSaskartaShowInput& In, FVoiceLenFn VoiceLen, FSongLenFn SongLen, FSaskartaShowPick& P)
{
    const FSaskartaShowAct* A = ActConfig(CurrentAct);
    if (!A || ShelfSongs.Num() == 0)
    {
        return false;
    }
    const double T = In.NowS;
    FName Song = PlannedReplaySong;
    const double* Last = Song.IsNone() ? nullptr : SongLastS.Find(Song);
    if (Song.IsNone() || Song == PlannedSlotSong || !ShelfSongs.Contains(Song) || (Last && T - *Last < Config.Show.SongReplayMinSpacingS) || SongLen(Song) <= 0.f)
    {
        Song = ChooseReplaySong(T, PlannedSlotSong);
    }
    if (Song.IsNone() || SongLen(Song) <= 0.f)
    {
        return false;
    }
    const FName Intro = (!PlannedReplayIntro.IsNone() && LinkEligible(PlannedReplayIntro, T) && PlannedReplayIntro != A->SongIntroFixed)
        ? PlannedReplayIntro : DrawLink(A->SongIntros, A->SongIntroFixed, T);
    const FName Outro = (!PlannedReplayOutro.IsNone() && LinkEligible(PlannedReplayOutro, T) && PlannedReplayOutro != A->SongOutroFixed)
        ? PlannedReplayOutro : DrawLink(A->SongOutros, A->SongOutroFixed, T);
    FSaskartaShowPick Block;
    if (!MakeSongBlock(Block, ESaskartaShowKind::SongReplay, Intro, Song, Outro, 0.f, VoiceLen, SongLen))
    {
        return false;
    }
    const float IntroS = Block.Slot.Parts[0].Kind == FSaskartaStationPart::EKind::Voice ? Block.Slot.Parts[0].DurationS : 0.f;
    if (IntroS + SaskartaShow::MinSongWindowS > In.MaxFitS)
    {
        return false;
    }
    P = Block;
    return true;
}

bool FSaskartaShowScheduler::TryRoom(const FSaskartaShowInput& In, FVoiceLenFn VoiceLen, FSaskartaShowPick& P)
{
    if (RoomIds.Num() == 0 || In.NowS < NextRoomAtS)
    {
        return false;
    }
    // Murmurs may repeat: the one heard longest ago (never heard first).
    TArray<FName> Best;
    double BestT = 1.0e18;
    for (const FName& Id : RoomIds)
    {
        const float L = VoiceLen(SegmentIndexOf(Id), NAME_None);
        if (L < 0.f || L > In.MaxFitS)
        {
            continue;
        }
        const double V = LastUsedS(Id);
        if (V < BestT - 1.0e-6)
        {
            BestT = V;
            Best.Reset();
            Best.Add(Id);
        }
        else if (FMath::Abs(V - BestT) <= 1.0e-6)
        {
            Best.Add(Id);
        }
    }
    if (Best.Num() == 0)
    {
        return false;
    }
    const FName Id = Best[Rand.RandRange(0, Best.Num() - 1)];
    MakeVoicePick(P, ESaskartaShowKind::Room, Id, VoiceLen(SegmentIndexOf(Id), NAME_None));
    return true;
}

FSaskartaShowPick FSaskartaShowScheduler::PickNext(const FSaskartaShowInput& In, FVoiceLenFn VoiceLen, FSongLenFn SongLen)
{
    FSaskartaShowPick P;
    if (!IsShowMode())
    {
        P.RetryS = 5.f;
        return P;
    }
    if (bSignoffDone)
    {
        P.RetryS = 3600.f; // the signal is dead
        return P;
    }
    Update(In);
    if (!In.bGateOpen)
    {
        P.RetryS = 0.5f;
        return P;
    }
    // 1. Joining a show in progress (a Continue, the end of a cinematic): a fill first. Not before the opening
    //    song: the station's first minutes (after the boot cinematic) open on the song.
    if (bOpenWithFill && CurrentAct <= 1 && !IsDone(OpeningSlotId()) && FindEntry(OpeningSlotId()))
    {
        bOpenWithFill = false;
    }
    if (bOpenWithFill)
    {
        bOpenWithFill = false;
        if (TryFill(In, VoiceLen, P, true) || TryLinger(In, VoiceLen, P))
        {
            return P;
        }
        // Acts with no fill or linger left (III and IV after the 9/29 cut for music): a room murmur opens instead,
        // whatever the murmur timer says.
        const double RoomAt = NextRoomAtS;
        NextRoomAtS = -1.0e18;
        const bool bRoom = TryRoom(In, VoiceLen, P);
        NextRoomAtS = RoomAt;
        if (bRoom)
        {
            return P;
        }
    }
    // Once B15 has ended, the pending backbone is trimmed so SHOW_A5_04 and SHOW_A5_05 end before the collapse.
    if (bSignoffGate)
    {
        EnforceSignoffBudget(In, VoiceLen);
    }
    // The scheduled show keeps priority over a song interrupted by story. Resume it in the
    // next usable gap so a carried song cannot postpone required lines into later acts.
    // Finish the audible, cursor-preserving separation before the departure opening.
    // Story gate/sign-off still have priority; unrelated acts keep their usual order.
    if (NeedsEbSeparation() && Played.Contains(SaskartaShow::EbSongPending) &&
        ResumeSongId == EbSeparationSong && TrySongResume(In, VoiceLen, SongLen, P)) return P;
    if (TryReaction(In, VoiceLen, P) || TryBackbone(In, VoiceLen, SongLen, P) || TrySongResume(In, VoiceLen, SongLen, P))
    {
        return P;
    }
    if (bSignoffGate)
    {
        // Nothing else during the sign-off.
        P = FSaskartaShowPick();
        P.RetryS = 0.25f;
        return P;
    }
    // 5. The silence filler: FILL, LINGER, FILL (relaxed), a song replay, a room murmur.
    if (TryFill(In, VoiceLen, P, false) || TryLinger(In, VoiceLen, P) || TryFill(In, VoiceLen, P, true)
        || TrySongReplay(In, VoiceLen, SongLen, P) || TryRoom(In, VoiceLen, P))
    {
        return P;
    }
    // 6. The repeat pool (2026-10-05, the author: "the radio doesnt speak enough ... even if it means repeating").
    //    Once the act's fresh FILL / LINGER lines are used up (Acts III and IV have none at all), the host
    //    re-airs a flavour line already heard instead of leaving only static: after RepeatQuietS of quiet,
    //    the least recently heard FILL / LINGER (never a time check, a SHOW / REACT / sign-off line) that is
    //    at least RepeatMinAgeS old and fits the story gate. Acts I-IV draw from their own and earlier acts'
    //    pools; Act V only from its own (no earlier jokes over the ending).
    if (CurrentAct >= 1 && In.NowS - LastFinishedS >= SaskartaShow::RepeatQuietS)
    {
        FName Best;
        double BestT = 1.0e18;
        const int32 FirstAct = CurrentAct >= 5 ? CurrentAct : 1;
        for (int32 ActIdx = FirstAct; ActIdx <= CurrentAct; ++ActIdx)
        {
            const FSaskartaShowAct* A = ActConfig(ActIdx);
            if (!A) continue;
            auto Consider = [&](const FName& Id)
            {
                const int32 Idx = SegmentIndexOf(Id);
                if (Idx == INDEX_NONE || Config.Segments[Idx].bTimeCheck) return;
                const double* Used = UsedS.Find(Id);
                if (!Used || In.NowS - *Used < SaskartaShow::RepeatMinAgeS) return; // only lines already heard
                const float L = VoiceLen(Idx, NAME_None);
                if (L < 0.f || L > In.MaxFitS) return;
                if (*Used < BestT) { BestT = *Used; Best = Id; }
            };
            for (const FName& Id : A->Fills) Consider(Id);
            for (const FName& Id : A->Linger) Consider(Id);
        }
        if (!Best.IsNone())
        {
            MakeVoicePick(P, ESaskartaShowKind::Linger, Best, VoiceLen(SegmentIndexOf(Best), NAME_None));
            return P;
        }
    }
    P = FSaskartaShowPick();
    P.RetryS = static_cast<float>(FMath::Clamp(NextRoomAtS - In.NowS, 0.5, 5.0)); // room tone
    return P;
}

void FSaskartaShowScheduler::Commit(const FSaskartaShowPick& P, double NowS)
{
    if (!P.bValid)
    {
        return;
    }
    auto UseLinks = [this, &P, NowS]()
    {
        if (!P.IntroId.IsNone()) UsedS.Add(P.IntroId, NowS);
        if (!P.OutroId.IsNone()) UsedS.Add(P.OutroId, NowS);
    };
    switch (P.Kind)
    {
    case ESaskartaShowKind::Backbone:
        Played.Add(P.Id);
        RemoveFromQueues(P.Id);
        FillsSinceBackbone = 0;
        if (P.bSignoff) bSignoffStarted = true;
        break;
    case ESaskartaShowKind::SongSlot:
        if (IsEbSeparationSlot(P.Id) && CurrentAct <= 3 && !IsDone(SaskartaShow::EbGone))
        {
            Played.Remove(P.Id);
            Played.Add(SaskartaShow::EbSongPending);
            TrackEbPlayback(P, NowS);
        }
        else Played.Add(P.Id);
        RemoveFromQueues(P.Id);
        SongsPlayed.Add(P.SongId);
        SongLastS.Add(P.SongId, NowS);
        UseLinks();
        FillsSinceBackbone = 0;
        PlannedSlotSong = PlannedSlotIntro = PlannedSlotOutro = PlannedSlotFor = NAME_None;
        break;
    case ESaskartaShowKind::SongReplay:
        SongLastS.Add(P.SongId, NowS);
        UseLinks();
        PlannedReplaySong = PlannedReplayIntro = PlannedReplayOutro = NAME_None;
        break;
    case ESaskartaShowKind::SongResume:
        if (Played.Contains(SaskartaShow::EbSongPending) && P.SongId == EbSeparationSong) TrackEbPlayback(P, NowS);
        SongLastS.Add(P.SongId, NowS);
        UseLinks();
        ResumeSongId = NAME_None;
        break;
    case ESaskartaShowKind::Fill:
    {
        UsedS.Add(P.Id, NowS);
        const int32 Idx = SegmentIndexOf(P.Id);
        if (Idx != INDEX_NONE && Config.Segments[Idx].bTimeCheck) LastTimeCheckS = NowS;
        ++FillsSinceBackbone;
        PlannedFill = NAME_None;
        break;
    }
    case ESaskartaShowKind::Linger:
        UsedS.Add(P.Id, NowS);
        PlannedLinger = NAME_None;
        break;
    case ESaskartaShowKind::Room:
        UsedS.Add(P.Id, NowS);
        NextRoomAtS = NowS + Rand.FRandRange(Config.Show.RoomMurmurEveryS.X, Config.Show.RoomMurmurEveryS.Y);
        break;
    case ESaskartaShowKind::React:
    {
        UsedS.Add(P.Id, NowS);
        EventLastS.Add(P.Event, NowS);
        LastReactS = NowS;
        if (ReactsPerAct.IsValidIndex(CurrentAct)) ++ReactsPerAct[CurrentAct];
        const FName Ev = P.Event;
        Pending.RemoveAll([Ev](const FPendingEvent& E) { return E.Event == Ev; });
        break;
    }
    default:
        break;
    }
    LastKind = P.Kind;
}

void FSaskartaShowScheduler::MarkFinished(const FSaskartaShowPick& P, double NowS)
{
    const bool bEbSong = Played.Contains(SaskartaShow::EbSongPending) &&
        (IsEbSeparationSlot(P.Id) || (P.Kind == ESaskartaShowKind::SongResume && P.SongId == EbSeparationSong));
    if (bEbSong)
    {
        // The station calls this after its media parts end. A missing/late sound
        // can also be skipped immediately, so Commit/Played alone is insufficient.
        const bool bCompletedPlayback = EbPlaybackStartS >= 0.0 && EbPlaybackExpectedS > .5f &&
            NowS - EbPlaybackStartS >= FMath::Max(.5f, EbPlaybackExpectedS - .5f);
        if (bCompletedPlayback)
        {
            Played.Add(SongSlotId(2));
            Played.Remove(SaskartaShow::EbSongPending);
            Played.Remove(SaskartaShow::EbSongRetry);
            RemoveFromQueues(SongSlotId(2));
        }
        else if (!Played.Contains(SaskartaShow::EbSongRetry))
        {
            Played.Add(SaskartaShow::EbSongRetry);
            RemoveFromQueues(SongSlotId(2));
            Front.Insert(SongSlotId(2), 0); // one real media retry, not an invented silent interval
        }
        else
        {
            // A permanently unavailable song cannot prove the transition. Omit
            // the contradictory departure opening and let the later show continue.
            Dropped.Add(SaskartaShow::EbGone);
            Dropped.Add(SongSlotId(2));
            RemoveFromQueues(SaskartaShow::EbGone);
            RemoveFromQueues(SongSlotId(2));
            Played.Remove(SaskartaShow::EbSongPending);
        }
        EbPlaybackStartS = -1.0e9;
    }
    LastFinishedS = NowS;
    if (P.bValid && P.bFinal)
    {
        bSignoffDone = true;
        Pending.Reset();
    }
}

float FSaskartaShowScheduler::DrawGapAfter(const FSaskartaShowPick& P)
{
    const FSaskartaShowConfig& S = Config.Show;
    if (P.bFinal)
    {
        return 0.f;
    }
    if (P.bTurn)
    {
        return Rand.FRandRange(S.AfterTurnS.X, S.AfterTurnS.Y);
    }
    if (P.bSignoff)
    {
        return S.ChainGapS;
    }
    ESource Src = ESource::None;
    if (const FEntry* Next = NextPending(Src))
    {
        if (Next->ChainAfter == P.Id) return S.ChainGapS;
    }
    return Rand.FRandRange(S.BetweenItemsS.X, S.BetweenItemsS.Y);
}

float FSaskartaShowScheduler::DrawFirstDelayS()
{
    return Rand.FRandRange(Config.Show.FirstItemDelayS.X, Config.Show.FirstItemDelayS.Y);
}

void FSaskartaShowScheduler::ReturnInterrupted(const FSaskartaShowPick& P, float HeardFraction, double NowS)
{
    if (!P.bValid || FSaskartaStationLogic::CountsAsPlayed(HeardFraction, 1.f, Config.ReturnToBagIfHeardBelow))
    {
        return; // heard enough: it counts as played
    }
    switch (P.Kind)
    {
    case ESaskartaShowKind::Backbone:
        Played.Remove(P.Id);
        RemoveFromQueues(P.Id);
        Front.Insert(P.Id, 0);
        break;
    case ESaskartaShowKind::SongSlot:
        // Cut in its intro: the whole slot comes back.
        Played.Remove(P.Id);
        RemoveFromQueues(P.Id);
        Front.Insert(P.Id, 0);
        SongsPlayed.Remove(P.SongId);
        if (!P.IntroId.IsNone()) UsedS.Remove(P.IntroId);
        if (!P.OutroId.IsNone()) UsedS.Remove(P.OutroId);
        break;
    case ESaskartaShowKind::Fill:
    case ESaskartaShowKind::Linger:
    case ESaskartaShowKind::Room:
    case ESaskartaShowKind::React:
        UsedS.Remove(P.Id);
        break;
    default:
        break;
    }
}

void FSaskartaShowScheduler::RememberInterruptedSong(FName SongId, float PositionS, FName OutroId)
{
    if (!SongId.IsNone() && PositionS >= 0.f)
    {
        ResumeSongId = SongId;
        ResumeSongPosS = PositionS;
        ResumeOutroId = OutroId;
        if (Played.Contains(SaskartaShow::EbSongPending) && SongId == EbSeparationSong)
            EbPlaybackStartS = -1.0e9; // completion must be measured on the resumed media attempt
    }
}

void FSaskartaShowScheduler::NotifySongPlaybackStarted(FName SongId, float RemainingS, double NowS)
{
    if (Played.Contains(SaskartaShow::EbSongPending) && SongId == EbSeparationSong && RemainingS > 0.f)
    {
        EbPlaybackStartS = NowS;
        EbPlaybackExpectedS = RemainingS;
    }
}

// ============================================================================ save

FSaskartaShowSaveState FSaskartaShowScheduler::SaveState(double NowS) const
{
    FSaskartaShowSaveState S;
    S.bValid = true;
    S.Act = CurrentAct;
    S.PlayedBackbone = Played.Array();
    S.DroppedBackbone = Dropped.Array();
    S.BackboneFront = Front;
    S.ClosingQueue = Closing;
    S.CarryQueue = Carry;
    S.SongsPlayed = SongsPlayed.Array();
    for (const TPair<FName, double>& KV : SongLastS)
    {
        S.SongLastIds.Add(KV.Key);
        S.SongLastAgeS.Add(static_cast<float>(NowS - KV.Value));
    }
    for (const TPair<FName, double>& KV : UsedS)
    {
        S.UsedIds.Add(KV.Key);
        S.UsedAgeS.Add(static_cast<float>(NowS - KV.Value));
    }
    for (const TPair<FName, double>& KV : EventLastS)
    {
        S.EventIds.Add(KV.Key);
        S.EventAgeS.Add(static_cast<float>(NowS - KV.Value));
    }
    S.LastReactAgeS = LastReactS > -1.0e8 ? static_cast<float>(NowS - LastReactS) : -1.f;
    S.ReactsPerAct = ReactsPerAct;
    S.LastTimeCheckAgeS = LastTimeCheckS > -1.0e8 ? static_cast<float>(NowS - LastTimeCheckS) : -1.f;
    S.PoisPassed = PoisPassed.Array();
    S.EndedBeats = EndedBeats.Array();
    S.bSignoffStarted = bSignoffStarted;
    S.bSignoffDone = bSignoffDone;
    if (!ResumeSongId.IsNone())
    {
        S.SongId = ResumeSongId;
        S.SongPositionS = ResumeSongPosS;
        S.SongOutroId = ResumeOutroId;
    }
    return S;
}

void FSaskartaShowScheduler::LoadState(const FSaskartaShowSaveState& S, double NowS)
{
    ResetRunState();
    bOpenWithFill = true;
    // CP0 can be saved before the station airs anything. Keep that unheard opening;
    // an established show (or a legacy save without show state) still joins in progress.
    const bool bUnheardOpening = S.bValid && S.Act == 0 && S.PlayedBackbone.IsEmpty()
        && S.DroppedBackbone.IsEmpty() && S.SongsPlayed.IsEmpty() && S.SongId.IsNone();
    if (!bUnheardOpening) Dropped.Add(OpeningSlotId());
    if (!S.bValid)
    {
        return; // a save from before the show: the act comes from the road
    }
    CurrentAct = FMath::Clamp(S.Act, 0, Acts.Num());
    Played.Append(S.PlayedBackbone);
    Dropped.Append(S.DroppedBackbone);
    Front = S.BackboneFront;
    Closing = S.ClosingQueue;
    Carry = S.CarryQueue;
    SongsPlayed.Append(S.SongsPlayed);
    for (int32 i = 0; i < S.SongLastIds.Num() && i < S.SongLastAgeS.Num(); ++i)
    {
        SongLastS.Add(S.SongLastIds[i], NowS - S.SongLastAgeS[i]);
    }
    for (int32 i = 0; i < S.UsedIds.Num() && i < S.UsedAgeS.Num(); ++i)
    {
        UsedS.Add(S.UsedIds[i], NowS - S.UsedAgeS[i]);
    }
    for (int32 i = 0; i < S.EventIds.Num() && i < S.EventAgeS.Num(); ++i)
    {
        EventLastS.Add(S.EventIds[i], NowS - S.EventAgeS[i]);
    }
    LastReactS = S.LastReactAgeS >= 0.f ? NowS - S.LastReactAgeS : -1.0e9;
    for (int32 i = 0; i < S.ReactsPerAct.Num() && i < ReactsPerAct.Num(); ++i)
    {
        ReactsPerAct[i] = S.ReactsPerAct[i];
    }
    LastTimeCheckS = S.LastTimeCheckAgeS >= 0.f ? NowS - S.LastTimeCheckAgeS : -1.0e9;
    PoisPassed.Append(S.PoisPassed);
    EndedBeats.Append(S.EndedBeats);
    bSignoffStarted = S.bSignoffStarted;
    bSignoffDone = S.bSignoffDone;
    ResumeSongId = S.SongId;
    ResumeSongPosS = S.SongPositionS;
    ResumeOutroId = S.SongOutroId;
    EbPlaybackStartS = -1.0e9;
    EbPlaybackExpectedS = 0.f;
    EbSeparationSong = Played.Contains(SaskartaShow::EbSongPending) ? ResumeSongId : NAME_None;
    // Legacy saves retain their Played semantics. New saves with an unfinished
    // song keep its cursor and pending marker; a quick jump beyond Act III expires it.
    if (CurrentAct > 3)
    {
        if (Played.Contains(SaskartaShow::EbSongPending))
        {
            Dropped.Add(SongSlotId(2));
            RemoveFromQueues(SongSlotId(2));
            if (!IsDone(SaskartaShow::EbGone))
            {
                Dropped.Add(SaskartaShow::EbGone);
                RemoveFromQueues(SaskartaShow::EbGone);
            }
        }
        Played.Remove(SaskartaShow::EbSongPending);
        Played.Remove(SaskartaShow::EbSongRetry);
    }
}

// ============================================================================ prefetch window and debug

FSaskartaShowUpcoming FSaskartaShowScheduler::GetUpcoming(int32 MaxBackbone) const
{
    FSaskartaShowUpcoming Out;
    if (!IsShowMode() || bSignoffDone)
    {
        return Out;
    }
    TSet<FName> Added;
    auto AddVoice = [&Out](FName Id, FName Song)
    {
        if (!Id.IsNone() && !Out.Voices.ContainsByPredicate([Id](const FSaskartaShowVoiceRef& V) { return V.Id == Id; }))
        {
            Out.Voices.Add({ Id, Song });
        }
    };
    auto AddEntry = [&](const FEntry* E)
    {
        if (Added.Contains(E->Id)) return;
        Added.Add(E->Id);
        if (E->bSongSlot)
        {
            AddVoice(PlannedSlotIntro, PlannedSlotSong);
            if (!PlannedSlotSong.IsNone()) Out.Songs.AddUnique(PlannedSlotSong);
            AddVoice(PlannedSlotOutro, PlannedSlotSong);
        }
        else
        {
            AddVoice(E->Id, NAME_None);
        }
    };
    if (!ResumeSongId.IsNone())
    {
        Out.Songs.AddUnique(ResumeSongId);
        AddVoice(ResumeOutroId, ResumeSongId);
    }
    TArray<const FEntry*> Order;
    PendingOrder(Order, false);
    int32 Count = 0;
    for (const FEntry* E : Order)
    {
        if (Count >= MaxBackbone) break;
        const bool bSeq = E->Act == CurrentAct && !InQueues(E->Id);
        if (bSeq && IsOptional(*E) && LaterMustDue(*E, LastRoadM))
        {
            continue; // will be dropped for a MUST that is due
        }
        AddEntry(E);
        ++Count;
    }
    // Every MUST still ahead in the act (a fast drive jumps to them), and the next act's opening.
    for (const FEntry* E : Order)
    {
        if (E->Must >= 1) AddEntry(E);
    }
    if (Acts.IsValidIndex(CurrentAct))
    {
        for (const FEntry& E : Acts[CurrentAct])
        {
            if (!IsDone(E.Id))
            {
                AddEntry(&E);
                break;
            }
        }
    }
    AddVoice(PlannedFill, NAME_None);
    AddVoice(PlannedLinger, NAME_None);
    // A replay only when the talk pools are nearly spent (or the carrier is stopped).
    if (!PlannedReplaySong.IsNone() && !bSignoffGate)
    {
        const FSaskartaShowAct* A = ActConfig(CurrentAct);
        int32 PoolLeft = 0;
        if (A)
        {
            for (const FName& Id : A->Fills) PoolLeft += FillEligible(Id, LastPlanS) ? 1 : 0;
            for (const FName& Id : A->Linger) PoolLeft += LingerEligible(Id, LastPlanS) ? 1 : 0;
        }
        if (bStopped || PoolLeft <= 3)
        {
            AddVoice(PlannedReplayIntro, PlannedReplaySong);
            Out.Songs.AddUnique(PlannedReplaySong);
            AddVoice(PlannedReplayOutro, PlannedReplaySong);
        }
    }
    return Out;
}

void FSaskartaShowScheduler::GetActReactionLines(int32 Act, TArray<FName>& Out) const
{
    for (const TPair<FName, FSaskartaShowEvent>& KV : Config.Show.Events)
    {
        if (Act < KV.Value.MinAct || KV.Key == EvPassingPoi)
        {
            continue;
        }
        for (const FName& Id : KV.Value.Lines)
        {
            if (!UsedS.Contains(Id) && LineInAct(Id, Act)) Out.AddUnique(Id);
        }
    }
    // Lines of events already queued (a POI just passed), then the POIs of this act not passed yet.
    for (const FPendingEvent& E : Pending)
    {
        for (const FName& Id : E.Lines)
        {
            if (!UsedS.Contains(Id) && LineInAct(Id, Act)) Out.AddUnique(Id);
        }
    }
    for (const FSaskartaShowPoi& Poi : Config.Show.Pois)
    {
        if (PoisPassed.Contains(Poi.Id)) continue;
        for (const FName& Id : Poi.Lines)
        {
            if (!UsedS.Contains(Id) && LineInAct(Id, Act)) Out.AddUnique(Id);
        }
    }
}

FName FSaskartaShowScheduler::PeekNextBackbone() const
{
    ESource Src = ESource::None;
    const FEntry* E = NextPending(Src);
    return E ? E->Id : NAME_None;
}

float FSaskartaShowScheduler::PeekNextBackboneAtM() const
{
    ESource Src = ESource::None;
    const FEntry* E = NextPending(Src);
    return E ? E->AtM : -1.f;
}

int32 FSaskartaShowScheduler::CountEligiblePool(const FSaskartaShowInput& In, FVoiceLenFn VoiceLen) const
{
    const FSaskartaShowAct* A = ActConfig(CurrentAct);
    if (!A)
    {
        return 0;
    }
    int32 N = 0;
    auto Fits = [&](FName Id)
    {
        const float L = VoiceLen(SegmentIndexOf(Id), NAME_None);
        return L >= 0.f && L <= In.MaxFitS;
    };
    for (const FName& Id : A->Fills) N += (FillEligible(Id, In.NowS) && Fits(Id)) ? 1 : 0;
    for (const FName& Id : A->Linger) N += (LingerEligible(Id, In.NowS) && Fits(Id)) ? 1 : 0;
    return N;
}

FString FSaskartaShowScheduler::Describe(double NowS) const
{
    const FSaskartaShowAct* A = ActConfig(CurrentAct);
    int32 Fills = 0, Linger = 0;
    if (A)
    {
        for (const FName& Id : A->Fills) Fills += FillEligible(Id, NowS) ? 1 : 0;
        for (const FName& Id : A->Linger) Linger += LingerEligible(Id, NowS) ? 1 : 0;
    }
    FString Out = FString::Printf(TEXT("show: act %d (%s), next %s at %.0f m, played %d, dropped %d, queues %d/%d/%d; fills %d/%d, linger %d/%d left; reactions in act %d/%d, pending %d, last %.0f s ago; stopped %d; sign-off gate %d started %d done %d"),
        CurrentAct, A ? *A->Name : TEXT("-"), *PeekNextBackbone().ToString(), PeekNextBackboneAtM(), Played.Num(), Dropped.Num(),
        Front.Num(), Closing.Num(), Carry.Num(), Fills, A ? A->Fills.Num() : 0, Linger, A ? A->Linger.Num() : 0,
        ReactsInAct(CurrentAct), Config.Show.MaxPerAct.IsValidIndex(CurrentAct - 1) ? Config.Show.MaxPerAct[CurrentAct - 1] : 0,
        Pending.Num(), NowS - LastReactS, bStopped ? 1 : 0, bSignoffGate ? 1 : 0, bSignoffStarted ? 1 : 0, bSignoffDone ? 1 : 0);
    Out += TEXT("; cooldowns:");
    for (const TPair<FName, FSaskartaShowEvent>& KV : Config.Show.Events)
    {
        const double* L = EventLastS.Find(KV.Key);
        const float Left = L ? FMath::Max(0.f, static_cast<float>(KV.Value.CooldownS - (NowS - *L))) : 0.f;
        Out += FString::Printf(TEXT(" %s %.0f"), *KV.Key.ToString(), Left);
    }
    return Out;
}

// ============================================================================ prefetch planner

void FSaskartaPrefetchPlanner::Plan(const TArray<FString>& Desired, const TSet<FString>& Pinned, double NowS, TArray<FString>& OutLoad, TArray<FString>& OutRelease)
{
    OutLoad.Reset();
    OutRelease.Reset();
    TSet<FString> Wanted;
    for (const FString& P : Pinned)
    {
        Wanted.Add(P);
        LastWantedS.Add(P, NowS);
    }
    for (const FString& P : Desired)
    {
        Wanted.Add(P);
    }
    // Release what nobody wanted for the grace period.
    for (const TPair<FString, double>& KV : LastWantedS)
    {
        if (!Wanted.Contains(KV.Key) && NowS - KV.Value >= ReleaseGraceS)
        {
            OutRelease.Add(KV.Key);
        }
    }
    for (const FString& P : OutRelease)
    {
        LastWantedS.Remove(P);
    }
    // Load the desired paths best first, up to the cap; over the cap, the stalest unwanted resident path makes room.
    for (const FString& P : Desired)
    {
        if (LastWantedS.Contains(P))
        {
            LastWantedS.Add(P, NowS);
            continue;
        }
        if (LastWantedS.Num() >= MaxResident)
        {
            FString Stalest;
            double StalestT = 1.0e18;
            for (const TPair<FString, double>& KV : LastWantedS)
            {
                if (!Wanted.Contains(KV.Key) && KV.Value < StalestT)
                {
                    StalestT = KV.Value;
                    Stalest = KV.Key;
                }
            }
            if (Stalest.IsEmpty())
            {
                break; // everything resident is wanted: the rest waits
            }
            LastWantedS.Remove(Stalest);
            OutRelease.Add(Stalest);
        }
        LastWantedS.Add(P, NowS);
        OutLoad.Add(P);
    }
}

// ============================================================================ dry run

TArray<FSaskartaShowSimBeat> SaskartaShowDefaultBeats(float LineS)
{
    struct FBeatDef { const TCHAR* Id; float RoadM; };
    static const FBeatDef Beats[] = {
        { TEXT("B03_PROMISE"), 450.f }, { TEXT("B05_WAITING_WATER"), 1220.f }, { TEXT("B06_ROAD_AHEAD"), 1980.f },
        { TEXT("B08_NUMBERED_STOP"), 2480.f }, { TEXT("B09_DEPARTURE_PLATFORM"), 2560.f }, { TEXT("B10_DRY_CISTERN"), 3050.f },
        { TEXT("B11_LAST_WAYSTATION"), 3400.f }, { TEXT("B14_LOOK_BACK"), 4460.f }, { TEXT("B15_HIGH_VOICE_IN_RANGE"), 4520.f } };
    TArray<FSaskartaShowSimBeat> Out;
    for (const FBeatDef& B : Beats)
    {
        FSaskartaShowSimBeat S;
        S.Id = FName(B.Id);
        S.RoadM = B.RoadM;
        S.LineS = LineS;
        Out.Add(S);
    }
    return Out;
}

FSaskartaShowSimResult SaskartaShowDryRun(const FSaskartaStationConfig& Config, const FSaskartaShowSimParams& Pm, FSaskartaShowScheduler* InOut, double StartS)
{
    FSaskartaShowSimResult R;
    FSaskartaShowScheduler Own;
    FSaskartaShowScheduler& S = InOut ? *InOut : Own;
    if (!InOut)
    {
        S.Init(Config, Pm.Seed);
    }
    S.SetAvailableSongs(Pm.Songs);
    if (!S.IsShowMode())
    {
        R.Log.Add(TEXT("ShowDryRun: station.json is not in show mode (or has no show block)."));
        return R;
    }
    const auto VoiceLen = [&Config](int32 Seg, FName) { return Config.Segments.IsValidIndex(Seg) ? Config.Segments[Seg].TargetS : -1.f; };
    const auto SongLen = [&Pm](FName Song)
    {
        if (!Pm.Songs.Contains(Song)) return -1.f;
        const float* Actual = Pm.SongLengthsS.Find(Song);
        return Actual && *Actual > 0.f ? *Actual : Pm.SongLenS;
    };
    TArray<FSaskartaShowSimBeat> Beats = Pm.Beats;
    Beats.Sort([](const FSaskartaShowSimBeat& A, const FSaskartaShowSimBeat& B) { return A.RoadM < B.RoadM; });
    int32 NextBeat = 0;
    while (NextBeat < Beats.Num() && Beats[NextBeat].RoadM < Pm.StartRoadM) ++NextBeat;
    TArray<bool> StopDone;
    StopDone.Init(false, Pm.Stops.Num());

    double T = StartS;
    float Road = Pm.StartRoadM;
    double StoryUntil = -1.0, HoldoffUntil = -1.0, StopUntil = -1.0;
    FName StoryBeat;
    bool bPlaying = false;
    FSaskartaShowPick Cur;
    int32 CurItem = INDEX_NONE;
    double CurStart = 0.0, CurEnd = 0.0;
    double NextActionAt = T + S.DrawFirstDelayS();
    double LastEnd = T;
    const double EndT = StartS + Pm.MaxS;
    auto EndCurrent = [&](bool bCut)
    {
        FSaskartaShowSimItem& It = R.Items[CurItem];
        It.EndS = T;
        It.EndRoadM = Road;
        It.bCut = bCut;
        bPlaying = false;
        LastEnd = T;
    };
    while (T < EndT)
    {
        for (int32 i = 0; i < Pm.Stops.Num(); ++i)
        {
            if (!StopDone[i] && Road >= Pm.Stops[i].X)
            {
                StopDone[i] = true;
                StopUntil = T + Pm.Stops[i].Y;
                R.StopWindows.Add(FVector2D(T, StopUntil));
            }
        }
        const float Speed = T < StopUntil ? 0.f : Pm.SpeedMps;
        // The story: end the line first, then start the next beat's line (it cuts the station).
        if (!StoryBeat.IsNone() && T >= StoryUntil)
        {
            S.OnStoryLineEnded(StoryBeat, T);
            S.OnBeatFinished(StoryBeat);
            HoldoffUntil = T + Pm.HoldoffS;
            StoryBeat = NAME_None;
            NextActionAt = FMath::Max(NextActionAt, HoldoffUntil);
        }
        if (StoryBeat.IsNone() && NextBeat < Beats.Num() && Road >= Beats[NextBeat].RoadM)
        {
            StoryBeat = Beats[NextBeat].Id;
            StoryUntil = T + Beats[NextBeat].LineS;
            ++NextBeat;
            if (bPlaying)
            {
                const bool bSong = Cur.Kind == ESaskartaShowKind::SongSlot || Cur.Kind == ESaskartaShowKind::SongReplay || Cur.Kind == ESaskartaShowKind::SongResume;
                if (bSong)
                {
                    float PartStart = 0.f;
                    for (int32 PartIndex = 0; PartIndex < Cur.Slot.Parts.Num(); ++PartIndex)
                    {
                        const FSaskartaStationPart& Part = Cur.Slot.Parts[PartIndex];
                        if (PartIndex > 0)
                        {
                            const FSaskartaStationPart& Prev = Cur.Slot.Parts[PartIndex - 1];
                            PartStart += Prev.DurationS - Prev.StartAtS - Part.OverlapPrevS;
                        }
                        if (Part.Kind != FSaskartaStationPart::EKind::Song)
                        {
                            continue;
                        }
                        const float IntoBlock = static_cast<float>(T - CurStart);
                        if (IntoBlock >= PartStart && IntoBlock < PartStart + Part.DurationS - Part.StartAtS)
                        {
                            S.RememberInterruptedSong(Part.SongId, Part.StartAtS + IntoBlock - PartStart, Cur.OutroId);
                        }
                        else if (IntoBlock < PartStart && Cur.Kind == ESaskartaShowKind::SongSlot)
                        {
                            S.ReturnInterrupted(Cur, IntoBlock / FMath::Max(0.01f, PartStart), T);
                        }
                        break;
                    }
                }
                else
                {
                    S.ReturnInterrupted(Cur, static_cast<float>((T - CurStart) / FMath::Max(0.01, CurEnd - CurStart)), T);
                }
                EndCurrent(true);
            }
        }
        const bool bStory = !StoryBeat.IsNone() || T < HoldoffUntil;
        const float EffSpeed = FMath::Max(Speed, 0.5f);
        const float NextBeatRoad = NextBeat < Beats.Num() ? Beats[NextBeat].RoadM : 1.0e9f;
        const float SecToBeat = (NextBeatRoad - Road) / EffSpeed;
        FSaskartaShowInput In;
        In.NowS = T;
        In.RoadM = Road;
        In.SpeedMps = Speed;
        In.bGateOpen = !bStory;
        In.MaxFitS = SecToBeat < Pm.LookaheadS ? 0.f : SecToBeat - Pm.FitMarginS;
        In.SecondsToCollapse = (Pm.EndRoadM - Road) / EffSpeed;
        if (Pm.OnTick)
        {
            Pm.OnTick(S, T, Road);
        }
        S.Update(In);
        if (bPlaying && T >= CurEnd)
        {
            S.MarkFinished(Cur, T);
            EndCurrent(false);
            if (Cur.bFinal)
            {
                R.bSignoffDone = true;
                R.FinalEndRoadM = Road;
                R.Log.Add(FString::Printf(TEXT("%7.1fs %6.0fm  -- the signal dies"), T, Road));
                break;
            }
            NextActionAt = T + S.DrawGapAfter(Cur);
        }
        if (!bPlaying && T >= NextActionAt)
        {
            const FSaskartaShowPick P = S.PickNext(In, VoiceLen, SongLen);
            if (P.bValid)
            {
                S.Commit(P, T);
                Cur = P;
                bPlaying = true;
                CurStart = T;
                CurEnd = T + FMath::Max(0.25f, P.Slot.TotalS);
                FSaskartaShowSimItem It;
                It.Kind = P.Kind;
                It.Id = P.Id;
                It.IntroId = P.IntroId;
                It.OutroId = P.OutroId;
                It.SongId = P.SongId;
                It.Event = P.Event;
                It.Act = P.Act;
                It.RoadAct = S.ActOfRoadM(Road);
                It.StartS = T;
                It.EndS = CurEnd;
                It.StartRoadM = Road;
                CurItem = R.Items.Add(It);
                R.Log.Add(FString::Printf(TEXT("%7.1fs %6.0fm  A%d %-6s %s%s%s (%.1f s)"), T, Road, S.GetAct(), SaskartaShow::KindName(P.Kind), *P.Id.ToString(),
                    P.SongId.IsNone() ? TEXT("") : *(TEXT(" ") + P.IntroId.ToString() + TEXT(" + SONG_") + P.SongId.ToString() + TEXT(" + ") + P.OutroId.ToString()),
                    P.Event.IsNone() ? TEXT("") : *(TEXT(" [") + P.Event.ToString() + TEXT("]")), P.Slot.TotalS));
            }
            else
            {
                if (In.bGateOpen && !S.IsSignoffGateOpen() && T - LastEnd >= Config.Show.SilenceMaxS && S.CountEligiblePool(In, VoiceLen) > 0)
                {
                    ++R.SilenceViolations;
                }
                NextActionAt = T + FMath::Clamp(P.RetryS, Pm.StepS, 1.f);
            }
        }
        if (Road >= Pm.EndRoadM)
        {
            break;
        }
        Road += Speed * Pm.StepS;
        T += Pm.StepS;
    }
    R.EndS = T;
    R.EndRoadM = Road;
    R.bSignoffDone = R.bSignoffDone || S.IsSignoffDone();
    R.Log.Add(FString::Printf(TEXT("ShowDryRun: %d items, sign-off %s%s, silence violations %d, ended at %.0f s, road %.0f m"),
        R.Items.Num(), R.bSignoffDone ? TEXT("done") : TEXT("NOT done"),
        R.FinalEndRoadM >= 0.f ? *FString::Printf(TEXT(" at road %.0f m"), R.FinalEndRoadM) : TEXT(""), R.SilenceViolations, R.EndS, R.EndRoadM));
    return R;
}
