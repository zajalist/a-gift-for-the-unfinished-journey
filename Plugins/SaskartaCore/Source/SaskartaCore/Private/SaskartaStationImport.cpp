// USaskartaStationImport: station.json -> FSaskartaStationConfig. See SaskartaStationAsset.h.

#include "SaskartaStationAsset.h"

#include "Dom/JsonObject.h"
#include "Dom/JsonValue.h"
#include "HAL/FileManager.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"

DEFINE_LOG_CATEGORY_STATIC(LogSaskartaStationImport, Log, All);

const TCHAR* USaskartaStationImport::StationAssetPath = TEXT("/Game/SaskartaGaea/Audio/Station/DA_Station.DA_Station");

namespace SaskartaStationImportPrivate
{
    static TSharedPtr<FJsonObject> Obj(const TSharedPtr<FJsonObject>& O, const TCHAR* Key)
    {
        const TSharedPtr<FJsonObject>* Out = nullptr;
        return (O.IsValid() && O->TryGetObjectField(Key, Out) && Out) ? *Out : nullptr;
    }

    static float Num(const TSharedPtr<FJsonObject>& O, const TCHAR* Key, float Default)
    {
        double D = 0.0;
        return (O.IsValid() && O->TryGetNumberField(Key, D)) ? static_cast<float>(D) : Default;
    }

    static FString Str(const TSharedPtr<FJsonObject>& O, const TCHAR* Key)
    {
        FString S;
        if (O.IsValid()) O->TryGetStringField(Key, S);
        return S;
    }

    static FSoftObjectPath AssetPath(const FString& PackagePath)
    {
        if (PackagePath.IsEmpty())
        {
            return FSoftObjectPath();
        }
        return FSoftObjectPath(PackagePath.Contains(TEXT(".")) ? PackagePath : PackagePath + TEXT(".") + FPaths::GetBaseFilename(PackagePath));
    }

    /** [a, b] -> (a, b); keeps Default when absent. */
    static FVector2f Pair(const TSharedPtr<FJsonObject>& O, const TCHAR* Key, const FVector2f& Default)
    {
        const TArray<TSharedPtr<FJsonValue>>* Arr = nullptr;
        if (O.IsValid() && O->TryGetArrayField(Key, Arr) && Arr && Arr->Num() >= 2)
        {
            return FVector2f(static_cast<float>((*Arr)[0]->AsNumber()), static_cast<float>((*Arr)[1]->AsNumber()));
        }
        return Default;
    }

    /** [[q=1, v], [q=0.25, v]] -> (v at q=1, v at q=0.25). */
    static FVector2f QPair(const TSharedPtr<FJsonObject>& O, const TCHAR* Key, const FVector2f& Default)
    {
        const TArray<TSharedPtr<FJsonValue>>* Arr = nullptr;
        if (!O.IsValid() || !O->TryGetArrayField(Key, Arr) || !Arr || Arr->Num() < 2)
        {
            return Default;
        }
        const TArray<TSharedPtr<FJsonValue>>& A = (*Arr)[0]->AsArray();
        const TArray<TSharedPtr<FJsonValue>>& B = (*Arr)[1]->AsArray();
        if (A.Num() < 2 || B.Num() < 2)
        {
            return Default;
        }
        return FVector2f(static_cast<float>(A[1]->AsNumber()), static_cast<float>(B[1]->AsNumber()));
    }

    static TArray<FName> Names(const TSharedPtr<FJsonObject>& O, const TCHAR* Key)
    {
        TArray<FName> Out;
        const TArray<TSharedPtr<FJsonValue>>* Arr = nullptr;
        if (O.IsValid() && O->TryGetArrayField(Key, Arr) && Arr)
        {
            for (const TSharedPtr<FJsonValue>& V : *Arr)
            {
                FString S;
                if (V.IsValid() && V->TryGetString(S)) Out.Add(FName(*S));
            }
        }
        return Out;
    }

    static bool Bool(const TSharedPtr<FJsonObject>& O, const TCHAR* Key)
    {
        bool b = false;
        if (O.IsValid()) O->TryGetBoolField(Key, b);
        return b;
    }

    /** A string field as a name; None when absent, null or empty. */
    static FName NameOf(const TSharedPtr<FJsonObject>& O, const TCHAR* Key)
    {
        FString S;
        return (O.IsValid() && O->TryGetStringField(Key, S) && !S.IsEmpty()) ? FName(*S) : NAME_None;
    }

    /** RADIOSHOW: station.json show -> FSaskartaShowConfig (the mode comes from scheduler.mode). */
    static void ParseShow(const TSharedPtr<FJsonObject>& Root, const TSharedPtr<FJsonObject>& Sched, FSaskartaShowConfig& Show)
    {
        Show.bShowMode = Str(Sched, TEXT("mode")).Equals(TEXT("show"), ESearchCase::IgnoreCase);
        const TSharedPtr<FJsonObject> S = Obj(Root, TEXT("show"));
        if (!S.IsValid())
        {
            // A show mode with no show block cannot run: the shuffle loop plays instead.
            Show.bShowMode = false;
            return;
        }
        const TArray<TSharedPtr<FJsonValue>>* ActsArr = nullptr;
        if (S->TryGetArrayField(TEXT("acts"), ActsArr) && ActsArr)
        {
            for (const TSharedPtr<FJsonValue>& V : *ActsArr)
            {
                const TSharedPtr<FJsonObject>* AO = nullptr;
                if (!V.IsValid() || !V->TryGetObject(AO) || !AO) continue;
                FSaskartaShowAct A;
                A.Act = static_cast<int32>(Num(*AO, TEXT("act"), 0.f));
                A.Name = Str(*AO, TEXT("name"));
                const FVector2f Road = Pair(*AO, TEXT("road_m"), FVector2f(0.f, 0.f));
                A.FromRoadM = Road.X;
                A.ToRoadM = Road.Y;
                A.Backbone = Names(*AO, TEXT("backbone"));
                if (const TSharedPtr<FJsonObject> Slot = Obj(*AO, TEXT("song_slot")))
                {
                    A.SongSlotAfter = NameOf(Slot, TEXT("after"));
                    A.bSongSlotMust = Bool(Slot, TEXT("must"));
                    A.SongSlotSong = NameOf(Slot, TEXT("song"));
                    A.SongIntroFixed = NameOf(Slot, TEXT("intro_fixed"));
                    A.SongOutroFixed = NameOf(Slot, TEXT("outro_fixed"));
                }
                const TArray<TSharedPtr<FJsonValue>>* SlotsArr = nullptr;
                if ((*AO)->TryGetArrayField(TEXT("song_slots"), SlotsArr) && SlotsArr)
                {
                    for (const TSharedPtr<FJsonValue>& SV : *SlotsArr)
                    {
                        const TSharedPtr<FJsonObject>* SO = nullptr;
                        if (!SV.IsValid() || !SV->TryGetObject(SO) || !SO) continue;
                        FSaskartaShowSongSlot Extra;
                        Extra.After = NameOf(*SO, TEXT("after"));
                        Extra.bMust = Bool(*SO, TEXT("must"));
                        Extra.Song = NameOf(*SO, TEXT("song"));
                        Extra.StartAtS = Num(*SO, TEXT("start_at_s"), 0.f);
                        Extra.IntroFixed = NameOf(*SO, TEXT("intro_fixed"));
                        Extra.OutroFixed = NameOf(*SO, TEXT("outro_fixed"));
                        if (!Extra.After.IsNone()) A.SongSlots.Add(Extra);
                    }
                }
                A.SongIntros = Names(*AO, TEXT("song_intros"));
                A.SongOutros = Names(*AO, TEXT("song_outros"));
                A.Fills = Names(*AO, TEXT("fills"));
                A.Linger = Names(*AO, TEXT("linger"));
                if (A.Act > 0) Show.Acts.Add(A);
            }
            Show.Acts.Sort([](const FSaskartaShowAct& X, const FSaskartaShowAct& Y) { return X.Act < Y.Act; });
        }
        if (const TSharedPtr<FJsonObject> Opening = Obj(S, TEXT("opening_song")))
        {
            Show.OpeningSong = NameOf(Opening, TEXT("song"));
            Show.OpeningSongStartAtS = Num(Opening, TEXT("start_at_s"), 0.f);
        }
        if (const TSharedPtr<FJsonObject> Progress = Obj(S, TEXT("progress")))
        {
            Show.LateDropM = Num(Progress, TEXT("late_drop_m"), Show.LateDropM);
        }
        if (const TSharedPtr<FJsonObject> Sil = Obj(S, TEXT("silence")))
        {
            Show.SilenceMinS = Num(Sil, TEXT("min_s"), Show.SilenceMinS);
            Show.SilenceMaxS = Num(Sil, TEXT("max_s"), Show.SilenceMaxS);
            Show.BetweenItemsS = Pair(Sil, TEXT("between_items_s"), Show.BetweenItemsS);
            Show.ChainGapS = Num(Sil, TEXT("chain_gap_s"), Show.ChainGapS);
            Show.AfterTurnS = Pair(Sil, TEXT("after_turn_s"), Show.AfterTurnS);
            Show.FirstItemDelayS = Pair(Sil, TEXT("first_item_delay_s"), Show.FirstItemDelayS);
            Show.TimeCheckMinSpacingS = Num(Sil, TEXT("time_check_min_spacing_s"), Show.TimeCheckMinSpacingS);
        }
        if (const TSharedPtr<FJsonObject> Linger = Obj(S, TEXT("linger")))
        {
            Show.NoRepeatWindowS = Num(Linger, TEXT("no_repeat_window_s"), Show.NoRepeatWindowS);
            Show.RoomMurmurEveryS = Pair(Linger, TEXT("room_murmur_every_s"), Show.RoomMurmurEveryS);
        }
        if (const TSharedPtr<FJsonObject> Songs = Obj(S, TEXT("songs")))
        {
            Show.SongIntroOverlapS = Num(Songs, TEXT("intro_overlap_s"), Show.SongIntroOverlapS);
            Show.SongIntroUnderDb = Num(Songs, TEXT("intro_under_db"), Show.SongIntroUnderDb);
            Show.SongIntroRiseS = Num(Songs, TEXT("intro_rise_s"), Show.SongIntroRiseS);
            Show.SongOutroOverTailS = Num(Songs, TEXT("outro_over_tail_s"), Show.SongOutroOverTailS);
            Show.SongReplayMinSpacingS = Num(Songs, TEXT("replay_min_spacing_s"), Show.SongReplayMinSpacingS);
        }
        if (const TSharedPtr<FJsonObject> Sign = Obj(S, TEXT("signoff")))
        {
            Show.SignoffItems = Names(Sign, TEXT("items"));
            Show.SignoffVoiceFloorDb = Num(Sign, TEXT("voice_floor_db"), Show.SignoffVoiceFloorDb);
            Show.SignalDeathHoldS = Num(Sign, TEXT("signal_death_hold_s"), Show.SignalDeathHoldS);
            Show.SignalDeathFadeS = Num(Sign, TEXT("signal_death_fade_s"), Show.SignalDeathFadeS);
            Show.CollapseRoadM = Num(Sign, TEXT("collapse_road_m"), Show.CollapseRoadM);
        }
        if (const TSharedPtr<FJsonObject> Last = Obj(S, TEXT("last_song")))
        {
            Show.LastSong = Str(Last, TEXT("song")).TrimStartAndEnd();
            Show.LastSongStartAfterS = Num(Last, TEXT("starts_after_signoff_s"), Show.LastSongStartAfterS);
            Show.LastSongFadeInS = Num(Last, TEXT("fade_in_s"), Show.LastSongFadeInS);
            Show.LastSongGainDb = Num(Last, TEXT("gain_db"), Show.LastSongGainDb);
            Show.LastSongLowpassHz = Num(Last, TEXT("lowpass_hz"), Show.LastSongLowpassHz);
            const FString Title = Str(Last, TEXT("title_song"));
            if (!Title.IsEmpty()) Show.TitleSong = AssetPath(Title);
            Show.TitleCrossfadeS = Num(Last, TEXT("title_crossfade_s"), Show.TitleCrossfadeS);
            Show.TitleGainDb = Num(Last, TEXT("title_gain_db"), Show.TitleGainDb);
        }
        if (const TSharedPtr<FJsonObject> R = Obj(S, TEXT("reactions")))
        {
            Show.GlobalCooldownS = Num(R, TEXT("global_cooldown_s"), Show.GlobalCooldownS);
            Show.ReactMaxWaitS = Num(R, TEXT("max_wait_s"), Show.ReactMaxWaitS);
            if (const TSharedPtr<FJsonObject> Max = Obj(R, TEXT("max_per_act")))
            {
                for (const TPair<FString, TSharedPtr<FJsonValue>>& KV : Max->Values)
                {
                    const int32 Act = FCString::Atoi(*KV.Key);
                    double D = 0.0;
                    if (Act >= 1 && Act <= 16 && KV.Value.IsValid() && KV.Value->TryGetNumber(D))
                    {
                        if (Show.MaxPerAct.Num() < Act) Show.MaxPerAct.SetNumZeroed(Act);
                        Show.MaxPerAct[Act - 1] = static_cast<int32>(D);
                    }
                }
            }
            if (const TSharedPtr<FJsonObject> Events = Obj(R, TEXT("events")))
            {
                for (const TPair<FString, TSharedPtr<FJsonValue>>& KV : Events->Values)
                {
                    const TSharedPtr<FJsonObject>* EO = nullptr;
                    if (!KV.Value.IsValid() || !KV.Value->TryGetObject(EO) || !EO) continue;
                    FSaskartaShowEvent E;
                    E.Probability = Num(*EO, TEXT("probability"), E.Probability);
                    E.ProbabilityClose = Num(*EO, TEXT("probability_close"), E.ProbabilityClose);
                    E.CooldownS = Num(*EO, TEXT("cooldown_s"), E.CooldownS);
                    E.AfterBeatProbability = Num(*EO, TEXT("after_beat_probability"), E.AfterBeatProbability);
                    E.DelayS = Pair(*EO, TEXT("delay_s"), E.DelayS);
                    E.StoppedAfterS = Num(*EO, TEXT("stopped_after_s"), E.StoppedAfterS);
                    E.AfterSilenceS = Num(*EO, TEXT("after_silence_s"), E.AfterSilenceS);
                    E.MinAct = static_cast<int32>(Num(*EO, TEXT("min_act"), static_cast<float>(E.MinAct)));
                    E.MaxWaitS = Num(*EO, TEXT("max_wait_s"), E.MaxWaitS);
                    const TArray<TSharedPtr<FJsonValue>>* Lines = nullptr;
                    if ((*EO)->TryGetArrayField(TEXT("lines"), Lines) && Lines)
                    {
                        for (const TSharedPtr<FJsonValue>& L : *Lines)
                        {
                            const TSharedPtr<FJsonObject>* LO = nullptr;
                            FString Id;
                            if (L.IsValid() && L->TryGetObject(LO) && LO && (*LO)->TryGetStringField(TEXT("id"), Id) && !Id.IsEmpty()) E.Lines.Add(FName(*Id));
                            else if (L.IsValid() && L->TryGetString(Id) && !Id.IsEmpty()) E.Lines.Add(FName(*Id));
                        }
                    }
                    Show.Events.Add(FName(*KV.Key), E);
                }
            }
            const TArray<TSharedPtr<FJsonValue>>* PoiArr = nullptr;
            if (R->TryGetArrayField(TEXT("poi"), PoiArr) && PoiArr)
            {
                for (const TSharedPtr<FJsonValue>& V : *PoiArr)
                {
                    const TSharedPtr<FJsonObject>* PO = nullptr;
                    if (!V.IsValid() || !V->TryGetObject(PO) || !PO) continue;
                    FSaskartaShowPoi P;
                    P.Id = NameOf(*PO, TEXT("id"));
                    P.Zone = NameOf(*PO, TEXT("zone"));
                    P.RoadM = Num(*PO, TEXT("road_m"), 0.f);
                    P.Lines = Names(*PO, TEXT("lines"));
                    if (P.Lines.Num() > 0) Show.Pois.Add(P);
                }
                Show.Pois.Sort([](const FSaskartaShowPoi& X, const FSaskartaShowPoi& Y) { return X.RoadM < Y.RoadM; });
            }
        }
        if (Show.Acts.Num() == 0)
        {
            Show.bShowMode = false;
        }
    }
}

bool USaskartaStationImport::ParseStationJson(const FString& Json, const TMap<FName, FString>& SidecarJsonById,
    FSaskartaStationConfig& OutConfig, FString& OutError)
{
    using namespace SaskartaStationImportPrivate;
    TSharedPtr<FJsonObject> Root;
    const TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(Json);
    if (!FJsonSerializer::Deserialize(Reader, Root) || !Root.IsValid())
    {
        OutError = TEXT("station.json: not valid JSON");
        return false;
    }
    FSaskartaStationConfig C;

    const TSharedPtr<FJsonObject> Sched = Obj(Root, TEXT("scheduler"));
    const TSharedPtr<FJsonObject> On = Obj(Sched, TEXT("station_on"));
    if (On.IsValid())
    {
        const FString Start = Str(On, TEXT("start_event"));
        if (!Start.IsEmpty()) C.StartEvent = FName(*Start);
        C.PlayFlowStates = Names(On, TEXT("plays_in_flow_states"));
        C.HoldFlowStates = Names(On, TEXT("holds_in_flow_states"));
        const FString Stop = Str(On, TEXT("stop_flow_state"));
        if (!Stop.IsEmpty()) C.StopFlowState = FName(*Stop);
    }
    if (C.PlayFlowStates.Num() == 0)
    {
        C.PlayFlowStates.Add(TEXT("Playing"));
    }
    C.FirstSegmentDelayS = Pair(Sched, TEXT("first_segment_delay_s"), C.FirstSegmentDelayS);
    C.GapS = Pair(Sched, TEXT("gap_s"), C.GapS);
    if (const TSharedPtr<FJsonObject> W = Obj(Sched, TEXT("category_weights")))
    {
        for (const TPair<FString, TSharedPtr<FJsonValue>>& KV : W->Values)
        {
            double D = 0.0;
            if (KV.Value.IsValid() && KV.Value->TryGetNumber(D)) C.CategoryWeights.Add(FName(*KV.Key), static_cast<float>(D));
        }
    }
    C.IdEveryNthSegment = static_cast<int32>(Num(Sched, TEXT("id_every_nth_segment"), 4.f));
    C.LeavingHintMinSpacing = static_cast<int32>(Num(Sched, TEXT("leaving_hint_min_spacing"), 3.f));
    {
        const TArray<TSharedPtr<FJsonValue>>* Arr = nullptr;
        if (Sched.IsValid() && Sched->TryGetArrayField(TEXT("quiet_ranges_road_m"), Arr) && Arr)
        {
            for (const TSharedPtr<FJsonValue>& V : *Arr)
            {
                const TArray<TSharedPtr<FJsonValue>>& R = V->AsArray();
                if (R.Num() >= 2) C.QuietRangesRoadM.Add(FVector2f(static_cast<float>(R[0]->AsNumber()), static_cast<float>(R[1]->AsNumber())));
            }
        }
    }
    if (const TSharedPtr<FJsonObject> Song = Obj(Sched, TEXT("song_block")))
    {
        C.SongIntervalS = Pair(Song, TEXT("interval_s"), C.SongIntervalS);
        if (const TSharedPtr<FJsonObject> Lead = Obj(Song, TEXT("lead_in")))
        {
            C.IntroChance = Num(Lead, TEXT("INTRO"), C.IntroChance);
        }
        C.GapAfterLinkS = Num(Song, TEXT("gap_after_link_s"), C.GapAfterLinkS);
        C.GapBeforeOutroS = Num(Song, TEXT("gap_before_outro_s"), C.GapBeforeOutroS);
    }
    // LANE5 + second batch: zones, fragments, the start road m and the panel labels.
    if (const TSharedPtr<FJsonObject> ZonesObj = Obj(Sched, TEXT("zones")))
    {
        C.ZoneShare = Num(ZonesObj, TEXT("zone_share"), C.ZoneShare);
    }
    if (const TSharedPtr<FJsonObject> Frag = Obj(Sched, TEXT("fragments")))
    {
        C.FragmentRoadM = Pair(Frag, TEXT("road_m"), C.FragmentRoadM);
        C.FragmentMaxQuality = Num(Frag, TEXT("max_quality"), C.FragmentMaxQuality);
        C.FragmentEveryNthSlot = static_cast<int32>(Num(Frag, TEXT("every_nth_slot"), static_cast<float>(C.FragmentEveryNthSlot)));
        C.FragmentGapAfterS = Pair(Frag, TEXT("gap_after_s"), C.FragmentGapAfterS);
    }
    if (const TSharedPtr<FJsonObject> StationOn = Obj(Sched, TEXT("station_on")))
    {
        C.StartRoadM = Num(StationOn, TEXT("start_road_m"), C.StartRoadM);
    }
    if (const TSharedPtr<FJsonObject> Labels = Obj(Sched, TEXT("category_labels")))
    {
        for (const TPair<FString, TSharedPtr<FJsonValue>>& KV : Labels->Values)
        {
            C.CategoryLabels.Add(FName(*KV.Key), KV.Value.IsValid() ? KV.Value->AsString() : FString());
        }
    }
    if (const TSharedPtr<FJsonObject> SP = Obj(Sched, TEXT("story_priority")))
    {
        C.LookaheadS = Num(SP, TEXT("lookahead_s"), C.LookaheadS);
        C.FitMarginS = Num(SP, TEXT("fit_margin_s"), C.FitMarginS);
        C.MinSpeedMps = Num(SP, TEXT("min_speed_mps"), C.MinSpeedMps);
        C.RedrawsBeforeWait = static_cast<int32>(Num(SP, TEXT("redraws_before_wait"), static_cast<float>(C.RedrawsBeforeWait)));
        C.RetryS = Num(SP, TEXT("retry_s"), C.RetryS);
        C.HoldoffAfterLineS = Num(SP, TEXT("holdoff_after_line_s"), C.HoldoffAfterLineS);
        C.AfterIdleDelayS = Pair(SP, TEXT("after_idle_delay_s"), C.AfterIdleDelayS);
        if (const TSharedPtr<FJsonObject> I = Obj(SP, TEXT("interrupt")))
        {
            C.DuckDb = Num(I, TEXT("duck_db"), C.DuckDb);
            C.DuckS = Num(I, TEXT("duck_s"), C.DuckS);
            C.FadeOutS = Num(I, TEXT("fade_out_s"), C.FadeOutS);
            C.ReturnToBagIfHeardBelow = Num(I, TEXT("return_to_bag_if_heard_below"), C.ReturnToBagIfHeardBelow);
        }
    }
    if (const TSharedPtr<FJsonObject> Cap = Obj(Sched, TEXT("captions")))
    {
        const FString Prefix = Str(Cap, TEXT("prefix"));
        if (!Prefix.IsEmpty()) C.CaptionPrefix = Prefix;
    }

    if (const TSharedPtr<FJsonObject> Rec = Obj(Root, TEXT("reception")))
    {
        const TArray<TSharedPtr<FJsonValue>>* Arr = nullptr;
        if (Rec->TryGetArrayField(TEXT("quality_by_road_m"), Arr) && Arr)
        {
            for (const TSharedPtr<FJsonValue>& V : *Arr)
            {
                const TArray<TSharedPtr<FJsonValue>>& P = V->AsArray();
                if (P.Num() >= 2) C.QualityByRoadM.Add(FVector2f(static_cast<float>(P[0]->AsNumber()), static_cast<float>(P[1]->AsNumber())));
            }
        }
        C.VoiceLowpassHz = QPair(Rec, TEXT("voice_lowpass_hz"), C.VoiceLowpassHz);
        C.VoiceHighpassHz = QPair(Rec, TEXT("voice_highpass_hz"), C.VoiceHighpassHz);
        C.VoiceGainDb = QPair(Rec, TEXT("voice_gain_db"), C.VoiceGainDb);
        if (const TSharedPtr<FJsonObject> Bed = Obj(Rec, TEXT("static_bed")))
        {
            C.StaticBed = AssetPath(Str(Bed, TEXT("asset")));
            C.StaticBetweenDb = QPair(Bed, TEXT("between_segments_db"), C.StaticBetweenDb);
            C.StaticUnderSpeechDb = Num(Bed, TEXT("under_speech_duck_db"), C.StaticUnderSpeechDb);
        }
        // LANE5: zones, below-quarter fade, lightning burst.
        const TArray<TSharedPtr<FJsonValue>>* ZonesArr = nullptr;
        if (Rec->TryGetArrayField(TEXT("zones"), ZonesArr) && ZonesArr)
        {
            for (const TSharedPtr<FJsonValue>& V : *ZonesArr)
            {
                const TSharedPtr<FJsonObject>* ZO = nullptr;
                if (!V.IsValid() || !V->TryGetObject(ZO) || !ZO) continue;
                FSaskartaStationZone Z;
                Z.Name = FName(*Str(*ZO, TEXT("name")));
                Z.Label = Str(*ZO, TEXT("label"));
                Z.FromRoadM = Num(*ZO, TEXT("from_m"), 0.f);
                Z.ToRoadM = Num(*ZO, TEXT("to_m"), 0.f);
                const TArray<TSharedPtr<FJsonValue>>* Al = nullptr;
                if ((*ZO)->TryGetArrayField(TEXT("aliases"), Al) && Al)
                {
                    for (const TSharedPtr<FJsonValue>& A : *Al) Z.Aliases.Add(FName(*A->AsString()));
                }
                if (!Z.Name.IsNone()) C.Zones.Add(Z);
            }
        }
        if (const TSharedPtr<FJsonObject> BQ = Obj(Rec, TEXT("below_quarter")))
        {
            C.VoiceGainDbAtQ0 = Num(BQ, TEXT("voice_gain_db_at_q0"), C.VoiceGainDbAtQ0);
            C.StaticBetweenDbAtQ0 = Num(BQ, TEXT("static_between_db_at_q0"), C.StaticBetweenDbAtQ0);
        }
        C.LightningBurstDb = Num(Rec, TEXT("lightning_burst_db"), C.LightningBurstDb);
        C.StaticIn = AssetPath(Str(Rec, TEXT("static_in")));
        C.StaticOut = AssetPath(Str(Rec, TEXT("static_out")));
        if (const TSharedPtr<FJsonObject> Sweep = Obj(Rec, TEXT("tune_sweep")))
        {
            C.TuneSweep = AssetPath(Str(Sweep, TEXT("asset")));
        }
        if (const TSharedPtr<FJsonObject> Drop = Obj(Rec, TEXT("dropouts")))
        {
            const TArray<TSharedPtr<FJsonValue>>* Rate = nullptr;
            if (Drop->TryGetArrayField(TEXT("rate_per_s"), Rate) && Rate && Rate->Num() >= 2)
            {
                const TArray<TSharedPtr<FJsonValue>>& A = (*Rate)[0]->AsArray();
                const TArray<TSharedPtr<FJsonValue>>& B = (*Rate)[1]->AsArray();
                if (A.Num() >= 2 && B.Num() >= 2)
                {
                    C.DropoutStartQ = static_cast<float>(A[0]->AsNumber());
                    C.DropoutRateAtLowQ = static_cast<float>(B[1]->AsNumber());
                }
            }
            C.DropoutLengthMs = Pair(Drop, TEXT("length_ms"), C.DropoutLengthMs);
            C.DropoutVoiceDb = Num(Drop, TEXT("voice_db"), C.DropoutVoiceDb);
            C.DropoutStaticBoostDb = Num(Drop, TEXT("static_boost_db"), C.DropoutStaticBoostDb);
        }
    }

    if (const TSharedPtr<FJsonObject> Songs = Obj(Root, TEXT("songs")))
    {
        FString Folder = Str(Songs, TEXT("asset_folder"));
        Folder.RemoveFromEnd(TEXT("/"));
        if (!Folder.IsEmpty()) C.SongFolder = Folder;
        for (const FName& Id : Names(Songs, TEXT("files")))
        {
            FSaskartaStationSong S;
            S.Id = Id;
            if (const FString* Side = SidecarJsonById.Find(Id))
            {
                TSharedPtr<FJsonObject> SO;
                const TSharedRef<TJsonReader<>> SR = TJsonReaderFactory<>::Create(*Side);
                if (FJsonSerializer::Deserialize(SR, SO) && SO.IsValid())
                {
                    S.Title = Str(SO, TEXT("title"));
                    S.Singer = Str(SO, TEXT("singer"));
                }
            }
            C.Songs.Add(S);
        }
    }
    if (const TSharedPtr<FJsonObject> Naming = Obj(Root, TEXT("audio_naming")))
    {
        // "/Game/SaskartaGaea/Audio/Station/Host/VO_Station_<id>" -> the folder.
        FString AssetPattern = Str(Naming, TEXT("asset"));
        int32 Slash = INDEX_NONE;
        if (AssetPattern.FindLastChar(TEXT('/'), Slash) && Slash > 0)
        {
            C.HostFolder = AssetPattern.Left(Slash);
        }
    }

    const TArray<TSharedPtr<FJsonValue>>* Segs = nullptr;
    if (Root->TryGetArrayField(TEXT("segments"), Segs) && Segs)
    {
        for (const TSharedPtr<FJsonValue>& V : *Segs)
        {
            const TSharedPtr<FJsonObject>* SO = nullptr;
            if (!V.IsValid() || !V->TryGetObject(SO) || !SO)
            {
                continue;
            }
            FSaskartaStationSegment S;
            S.Id = FName(*Str(*SO, TEXT("id")));
            S.Category = FName(*Str(*SO, TEXT("category")));
            S.Speaker = FName(*Str(*SO, TEXT("speaker")));
            S.Text = Str(*SO, TEXT("text"));
            S.Template = Str(*SO, TEXT("template"));
            S.TargetS = Num(*SO, TEXT("target_s"), 5.f);
            S.Weight = Num(*SO, TEXT("weight"), 1.f);
            if (const TSharedPtr<FJsonObject> Tags = Obj(*SO, TEXT("tags")))
            {
                Tags->TryGetBoolField(TEXT("leaving_hint"), S.bLeavingHint);
            }
            const FString SegZone = Str(*SO, TEXT("zone"));
            if (!SegZone.IsEmpty()) S.Zone = FName(*SegZone);
            S.RoadMRange = Pair(*SO, TEXT("road_m"), S.RoadMRange);
            // RADIOSHOW fields.
            S.Act = static_cast<int32>(Num(*SO, TEXT("act"), 0.f));
            S.Must = static_cast<int32>(Num(*SO, TEXT("must"), 0.f));
            S.AtRoadM = Num(*SO, TEXT("at_m"), -1.f);
            S.bTurn = Bool(*SO, TEXT("turn"));
            S.bFinal = Bool(*SO, TEXT("final"));
            S.bCarry = Bool(*SO, TEXT("carry"));
            S.bTimeCheck = Bool(*SO, TEXT("time_check"));
            S.bAfterSong = Bool(*SO, TEXT("after_song"));
            S.ChainAfter = NameOf(*SO, TEXT("chain_after"));
            S.AfterBeat = NameOf(*SO, TEXT("after_beat"));
            S.Event = NameOf(*SO, TEXT("event"));
            const FVector2f Acts = Pair(*SO, TEXT("acts"), FVector2f(0.f, 0.f));
            S.Acts = FIntPoint(FMath::RoundToInt(Acts.X), FMath::RoundToInt(Acts.Y));
            S.PoiRoadM = Num(*SO, TEXT("poi_m"), -1.f);
            const TArray<TSharedPtr<FJsonValue>>* PageArray = nullptr;
            if ((*SO)->TryGetArrayField(TEXT("caption_pages"), PageArray) && PageArray)
            {
                for (const TSharedPtr<FJsonValue>& Value : *PageArray)
                {
                    const TSharedPtr<FJsonObject>* PageObj = nullptr;
                    if (!Value.IsValid() || !Value->TryGetObject(PageObj) || !PageObj || !PageObj->IsValid())
                    {
                        continue;
                    }
                    FSaskartaCaptionPage Page;
                    Page.StartS = Num(*PageObj, TEXT("t"), -1.f);
                    Page.Text = Str(*PageObj, TEXT("text"));
                    Page.Saskartan = Str(*PageObj, TEXT("sks"));
                    if (Page.StartS >= 0.f && !Page.Text.IsEmpty())
                    {
                        S.CaptionPages.Add(MoveTemp(Page));
                    }
                }
                S.CaptionPages.Sort([](const FSaskartaCaptionPage& A, const FSaskartaCaptionPage& B)
                {
                    return A.StartS < B.StartS;
                });
            }
            if (!S.Id.IsNone())
            {
                C.Segments.Add(S);
            }
        }
    }
    ParseShow(Root, Sched, C.Show);
    OutConfig = MoveTemp(C);
    return OutConfig.Segments.Num() > 0;
}

bool USaskartaStationImport::ImportStationFromFiles(USaskartaStationAsset* Asset, const FString& ProjectDir, FString& OutReport)
{
    if (!Asset)
    {
        OutReport = TEXT("no asset");
        return false;
    }
    FString Json;
    if (!FFileHelper::LoadFileToString(Json, *FPaths::Combine(ProjectDir, TEXT("docs/story/station.json"))))
    {
        OutReport = TEXT("missing docs/story/station.json");
        return false;
    }
    TMap<FName, FString> Sidecars;
    const FString SongDir = FPaths::Combine(ProjectDir, TEXT("SourceArt/Audio/StationSongs"));
    TArray<FString> Files;
    IFileManager::Get().FindFiles(Files, *FPaths::Combine(SongDir, TEXT("*.json")), true, false);
    for (const FString& F : Files)
    {
        FString Side;
        if (FFileHelper::LoadFileToString(Side, *FPaths::Combine(SongDir, F)))
        {
            Sidecars.Add(FName(*FPaths::GetBaseFilename(F)), Side);
        }
    }
    FSaskartaStationConfig Config;
    FString Error;
    if (!ParseStationJson(Json, Sidecars, Config, Error))
    {
        OutReport = Error.IsEmpty() ? TEXT("station.json has no segments") : Error;
        return false;
    }
    Asset->Modify();
    Asset->Config = MoveTemp(Config);
    OutReport = FString::Printf(TEXT("segments %d, songs %d, categories %d, gap %.0f-%.0f s, quiet ranges %d; mode %s (%d acts, %d reaction events, %d POIs, last song '%s')"),
        Asset->Config.Segments.Num(), Asset->Config.Songs.Num(), Asset->Config.CategoryWeights.Num(),
        Asset->Config.GapS.X, Asset->Config.GapS.Y, Asset->Config.QuietRangesRoadM.Num(),
        Asset->Config.Show.bShowMode ? TEXT("show") : TEXT("shuffle"), Asset->Config.Show.Acts.Num(), Asset->Config.Show.Events.Num(),
        Asset->Config.Show.Pois.Num(), *Asset->Config.Show.LastSong);
    UE_LOG(LogSaskartaStationImport, Log, TEXT("ImportStationFromFiles: %s"), *OutReport);
    return true;
}

USaskartaStationAsset* USaskartaStationImport::LoadStationOrImportTransient(UObject* Outer)
{
    if (USaskartaStationAsset* Asset = LoadObject<USaskartaStationAsset>(nullptr, StationAssetPath, nullptr, LOAD_NoWarn | LOAD_Quiet))
    {
        return Asset;
    }
    if (USaskartaStationAsset* Transient = ImportTransient(Outer))
    {
        return Transient;
    }
    UE_LOG(LogSaskartaStationImport, Warning, TEXT("DA_Station not found (%s); the station is silent."), StationAssetPath);
    return nullptr;
}

USaskartaStationAsset* USaskartaStationImport::ImportTransient(UObject* Outer)
{
#if WITH_EDITOR
    USaskartaStationAsset* Transient = NewObject<USaskartaStationAsset>(Outer ? Outer : GetTransientPackage());
    FString Report;
    if (ImportStationFromFiles(Transient, FPaths::ProjectDir(), Report))
    {
        UE_LOG(LogSaskartaStationImport, Warning, TEXT("DA_Station not found; imported a transient copy from docs/story (editor only). %s"), *Report);
        return Transient;
    }
#endif
    return nullptr;
}
