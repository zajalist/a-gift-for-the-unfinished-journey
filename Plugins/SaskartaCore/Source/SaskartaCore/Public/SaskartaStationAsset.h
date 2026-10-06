// The Low Voice station data (docs/story/station.json, STATION.md).
//
// Packaging: DA_Station (/Game/SaskartaGaea/Audio/Station/DA_Station) is filled from
// station.json in the editor lane by
//   unreal.SaskartaStationImport.import_station_from_files(asset, project_dir)
// and saved; it cooks with the game. In editor builds a missing asset falls back to a
// transient import from docs/story/station.json so PIE works before the asset exists.
//
// The archive filter is not DSP code here: it is a submix effect chain the designer sets
// on the asset (StationSubmix + ArchiveFilterChain). The station applies it with
// SetSubmixEffectChainOverride at BeginPlay; the host takes, songs and static route to
// StationSubmix through their own Sound Submix setting (set at import).

#pragma once

#include "CoreMinimal.h"
#include "Engine/DataAsset.h"
#include "Kismet/BlueprintFunctionLibrary.h"
#include "SaskartaCaptionPaging.h"
#include "SaskartaStationAsset.generated.h"

class USoundEffectSubmixPreset;
class USoundSubmix;

USTRUCT(BlueprintType)
struct SASKARTACORE_API FSaskartaStationSegment
{
    GENERATED_BODY()

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Station")
    FName Id;

    /** NOTICE, WEATHER, DEDIC, KITCHEN, TALK, LETTER, ID, INTRO, OUTRO, REQUEST. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Station")
    FName Category;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Station")
    FName Speaker;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Station")
    FString Text;

    /** Song links: [ ... ] groups kept only when every {SONG}/{SINGER} inside has a value. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Station")
    FString Template;

    /** Fallback length before the take exists; the asset's real duration wins. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Station")
    float TargetS = 5.f;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Station")
    float Weight = 1.f;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Station")
    bool bLeavingHint = false;

    /**
     * LANE5 + the second batch: the writer's zone (VALLEY, HERON, STAIR...) of a ZONE segment. ZONE segments live
     * in one bag per zone (ZONE_<zone>) and are drawn only while the road m is inside RoadMRange.
     */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Station")
    FName Zone;

    /** (from, to) road m where a ZONE or FRAG segment may play; (-1, -1) = anywhere. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Station")
    FVector2f RoadMRange = FVector2f(-1.f, -1.f);

    // --- RADIOSHOW: the live show's fields (station.json segments of SHOW, FILL, LINGER, ROOM, REACT, SONGIN, SONGOUT)

    /** The act (1-5) of a SHOW / FILL / LINGER / SONGIN / SONGOUT line; 0 = any act (ROOM murmurs). */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Station|Show")
    int32 Act = 0;

    /** Backbone rank: 0 optional, 1 MUST (dropped only when late), 2 MUST never dropped. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Station|Show")
    int32 Must = 0;

    /** The earliest road m of a backbone item (at_m); -1 = none. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Station|Show")
    float AtRoadM = -1.f;

    /** The act's turn (its last beat). */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Station|Show")
    bool bTurn = false;

    /** The last line of the show (SHOW_A5_05): the signal dies after it. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Station|Show")
    bool bFinal = false;

    /** Carried to the front of the next act instead of being dropped (SHOW_A1_07, Nuri's letter). */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Station|Show")
    bool bCarry = false;

    /** A FILL time check: played in id order within the act, never repeated (the night's clock only moves forward). */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Station|Show")
    bool bTimeCheck = false;

    /** Waits for the act's song block (or its skip): SHOW_A3_08. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Station|Show")
    bool bAfterSong = false;

    /** Starts ChainGapS after this item ends, ignoring AtRoadM. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Station|Show")
    FName ChainAfter;

    /** Waits for this story beat's line to end (B11, B15; matches a beat id by prefix, B15 -> B15_HIGH_VOICE_IN_RANGE). */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Station|Show")
    FName AfterBeat;

    /** A REACT line's event (LIGHTNING, DROPOUT, ...). */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Station|Show")
    FName Event;

    /** A REACT line's act range (from, to); (0, 0) = any act. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Station|Show")
    FIntPoint Acts = FIntPoint(0, 0);

    /** A PASSING_POI line's road m; -1 = none. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Station|Show")
    float PoiRoadM = -1.f;

    /** Authored page starts relative to the take. Empty uses proportional paging. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Station")
    TArray<FSaskartaCaptionPage> CaptionPages;

};

/** One additional song slot in an act. */
USTRUCT(BlueprintType)
struct SASKARTACORE_API FSaskartaShowSongSlot
{
    GENERATED_BODY()

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Station|Show")
    FName After;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Station|Show")
    bool bMust = false;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Station|Show")
    FName Song;

    /** Seconds into the song when this slot joins an already playing broadcast. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Station|Show")
    float StartAtS = 0.f;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Station|Show")
    FName IntroFixed;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Station|Show")
    FName OutroFixed;
};

/** RADIOSHOW: one act of the live show (station.json show.acts). */
USTRUCT(BlueprintType)
struct SASKARTACORE_API FSaskartaShowAct
{
    GENERATED_BODY()

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Station|Show")
    int32 Act = 0;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Station|Show")
    FString Name;

    /** The act holds the high-water road m in [FromRoadM, ToRoadM). */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Station|Show")
    float FromRoadM = 0.f;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Station|Show")
    float ToRoadM = 0.f;

    /** The backbone ids, in order. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Station|Show")
    TArray<FName> Backbone;

    /** The song slot follows this backbone item; None = no slot (Acts IV-V). */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Station|Show")
    FName SongSlotAfter;

    /** The slot is MUST, never dropped (Act III: the last song on the shelf). */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Station|Show")
    bool bSongSlotMust = false;

    /** A fixed song for the slot (None = the song bag's choice). */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Station|Show")
    FName SongSlotSong;

    /** Fixed slot links (Act III: SONGIN_A3_01 / SONGOUT_A3_01); never used for linger replays. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Station|Show")
    FName SongIntroFixed;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Station|Show")
    FName SongOutroFixed;

    /** Additional slots after the act's first song_slot. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Station|Show")
    TArray<FSaskartaShowSongSlot> SongSlots;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Station|Show")
    TArray<FName> SongIntros;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Station|Show")
    TArray<FName> SongOutros;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Station|Show")
    TArray<FName> Fills;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Station|Show")
    TArray<FName> Linger;
};

/** RADIOSHOW: one reaction event type ("the signal knows"; station.json show.reactions.events). */
USTRUCT(BlueprintType)
struct SASKARTACORE_API FSaskartaShowEvent
{
    GENERATED_BODY()

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Station|Show")
    float Probability = 0.5f;

    /** LIGHTNING: the probability for a close strike; < 0 = Probability. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Station|Show")
    float ProbabilityClose = -1.f;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Station|Show")
    float CooldownS = 0.f;

    /** AFTER_TAPE: the probability of a line tied to the beat that just ended (REACT_AFTER_TAPE_06 / _07). */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Station|Show")
    float AfterBeatProbability = 1.f;

    /** AFTER_TAPE: the delay after the story line before the reaction may start (min, max). */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Station|Show")
    FVector2f DelayS = FVector2f(0.f, 0.f);

    /** STOPPED: seconds without road progress. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Station|Show")
    float StoppedAfterS = 20.f;

    /** SILENCE: seconds of the station's own dead air. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Station|Show")
    float AfterSilenceS = 6.f;

    /** The event is ignored before this act (the author's decision: LIGHTNING starts in Act II). */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Station|Show")
    int32 MinAct = 1;

    /** Seconds the event may wait for the current item to end; < 0 = the global ReactMaxWaitS. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Station|Show")
    float MaxWaitS = -1.f;

    /** The event's lines (their acts are on the segments). */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Station|Show")
    TArray<FName> Lines;
};

/** RADIOSHOW: a ruin the road passes (PASSING_POI; station.json show.reactions.poi). */
USTRUCT(BlueprintType)
struct SASKARTACORE_API FSaskartaShowPoi
{
    GENERATED_BODY()

    /** VALLEY@600 */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Station|Show")
    FName Id;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Station|Show")
    FName Zone;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Station|Show")
    float RoadM = 0.f;

    /** One is drawn (two lines: each p 0.5). */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Station|Show")
    TArray<FName> Lines;
};

/** RADIOSHOW: the live show (station.json scheduler.mode + show; RADIO_SHOW.md). */
USTRUCT(BlueprintType)
struct SASKARTACORE_API FSaskartaShowConfig
{
    GENERATED_BODY()

    /** scheduler.mode == "show"; false = the shuffle loop (the fallback). */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Show")
    bool bShowMode = false;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Show")
    TArray<FSaskartaShowAct> Acts;

    /** Shelf song heard when the station first comes on; skipped on Continue. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Show")
    FName OpeningSong;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Show")
    float OpeningSongStartAtS = 0.f;

    /** A MUST (1) item of an act left behind plays only if the road is less than this past the act end. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Show|Progress")
    float LateDropM = 250.f;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Show|Silence")
    float SilenceMinS = 0.5f;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Show|Silence")
    float SilenceMaxS = 3.f;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Show|Silence")
    FVector2f BetweenItemsS = FVector2f(0.6f, 1.8f);

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Show|Silence")
    float ChainGapS = 1.2f;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Show|Silence")
    FVector2f AfterTurnS = FVector2f(1.5f, 2.5f);

    /** The first item after the station comes on (the show is already in progress). */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Show|Silence")
    FVector2f FirstItemDelayS = FVector2f(1.5f, 3.f);

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Show|Silence")
    float TimeCheckMinSpacingS = 240.f;

    /** No FILL / LINGER / link line repeats within this. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Show|Linger")
    float NoRepeatWindowS = 1200.f;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Show|Linger")
    FVector2f RoomMurmurEveryS = FVector2f(45.f, 90.f);

    /** The song starts under the last this-many seconds of its intro ... */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Show|Songs")
    float SongIntroOverlapS = 2.f;

    /** ... at this level, and comes up to full over SongIntroRiseS after the intro ends. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Show|Songs")
    float SongIntroUnderDb = -10.f;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Show|Songs")
    float SongIntroRiseS = 1.5f;

    /** The outro starts this long before the song ends (it back-announces over the tail). */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Show|Songs")
    float SongOutroOverTailS = 1.5f;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Show|Songs")
    float SongReplayMinSpacingS = 720.f;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Show|Reactions")
    float GlobalCooldownS = 75.f;

    /** Reactions per act, index act - 1. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Show|Reactions")
    TArray<int32> MaxPerAct;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Show|Reactions")
    float ReactMaxWaitS = 8.f;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Show|Reactions")
    TMap<FName, FSaskartaShowEvent> Events;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Show|Reactions")
    TArray<FSaskartaShowPoi> Pois;

    /** SHOW_A5_03, SHOW_A5_04, SHOW_A5_05: back to back once B15 has ended; the first is dropped if the collapse is too close. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Show|Signoff")
    TArray<FName> SignoffItems;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Show|Signoff")
    float SignoffVoiceFloorDb = -14.f;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Show|Signoff")
    float SignalDeathHoldS = 1.5f;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Show|Signoff")
    float SignalDeathFadeS = 4.f;

    /** B18: the sign-off must be over before this road m. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Show|Signoff")
    float CollapseRoadM = 4790.f;

    /** The author's last song (show.last_song.song): a bare id -> <SongFolder>/SONG_<id>, or an object path. Empty = none yet. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Show|End")
    FString LastSong;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Show|End")
    float LastSongStartAfterS = 1.5f;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Show|End")
    float LastSongFadeInS = 2.f;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Show|End")
    float LastSongGainDb = -3.f;

    /** A light radio low-pass on the last song; 0 = none. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Show|End")
    float LastSongLowpassHz = 3200.f;

    /** The title song (eyetae) the end transitions into, for the end card and credits. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Show|End")
    FSoftObjectPath TitleSong = FSoftObjectPath(TEXT("/Game/Pallbearer/UI/eyetae_title.eyetae_title"));

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Show|End")
    float TitleCrossfadeS = 4.f;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Show|End")
    float TitleGainDb = 0.f;
};

/** LANE5: a named stretch of road for zone-aware segments and the radio panel. */
USTRUCT(BlueprintType)
struct SASKARTACORE_API FSaskartaStationZone
{
    GENERATED_BODY()

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Station")
    FName Name;

    /** Shown on the radio panel. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Station")
    FString Label;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Station")
    float FromRoadM = 0.f;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Station")
    float ToRoadM = 0.f;

    /** The writer's segment zone names that belong to this reception zone (VALLEY, HERON + PLATFORM...), for the panel. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Station")
    TArray<FName> Aliases;
};

USTRUCT(BlueprintType)
struct SASKARTACORE_API FSaskartaStationSong
{
    GENERATED_BODY()

    /** Lowercase song id: the asset is SONG_<Id>. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Station")
    FName Id;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Station")
    FString Title;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Station")
    FString Singer;
};

/** Every station.json parameter. Pairs are (min, max) or (value at q = 1, value at q = 0.25). */
USTRUCT(BlueprintType)
struct SASKARTACORE_API FSaskartaStationConfig
{
    GENERATED_BODY()

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Station|On")
    FName StartEvent = TEXT("B01_BOOT_HANDOVER");

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Station|On")
    TArray<FName> PlayFlowStates;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Station|On")
    TArray<FName> HoldFlowStates;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Station|On")
    FName StopFlowState = TEXT("Human");

    /** A positive road fallback also starts the station after a jump; zero waits for the boot handover. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Station|On")
    float StartRoadM = 0.f;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Station|Loop")
    FVector2f FirstSegmentDelayS = FVector2f(20.f, 40.f);

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Station|Loop")
    FVector2f GapS = FVector2f(45.f, 120.f);

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Station|Selection")
    TMap<FName, float> CategoryWeights;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Station|Selection")
    int32 IdEveryNthSegment = 4;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Station|Selection")
    int32 LeavingHintMinSpacing = 3;

    /** LANE5: road zones (reception.zones in station.json), in road order. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Station|Selection")
    TArray<FSaskartaStationZone> Zones;

    /** scheduler.zones.zone_share: on a non-ID slot, the chance to draw a ZONE segment whose road_m contains the road m. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Station|Selection")
    float ZoneShare = 0.5f;

    /** scheduler.fragments: inside FragmentRoadM with q <= FragmentMaxQuality, every Nth slot is a FRAG line... */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Station|Selection")
    FVector2f FragmentRoadM = FVector2f(3550.f, 4790.f);

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Station|Selection")
    float FragmentMaxQuality = 0.45f;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Station|Selection")
    int32 FragmentEveryNthSlot = 2;

    /** ... and the gap after a FRAG line is this instead of GapS (a station breaking up, not one gone quiet). */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Station|Selection")
    FVector2f FragmentGapAfterS = FVector2f(15.f, 40.f);

    /** LANE5: panel titles by category (WEATHER -> Weather). Missing ones use the category in title case. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Station|Captions")
    TMap<FName, FString> CategoryLabels;

    /** (road m from, road m to): no new segment starts inside. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Station|Selection")
    TArray<FVector2f> QuietRangesRoadM;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Station|Songs")
    FVector2f SongIntervalS = FVector2f(240.f, 360.f);

    /** Chance the lead-in is an INTRO (else a REQUEST). */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Station|Songs")
    float IntroChance = 0.75f;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Station|Songs")
    float GapAfterLinkS = 0.6f;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Station|Songs")
    float GapBeforeOutroS = 1.0f;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Station|Story")
    float LookaheadS = 25.f;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Station|Story")
    float FitMarginS = 3.f;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Station|Story")
    float MinSpeedMps = 0.5f;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Station|Story")
    int32 RedrawsBeforeWait = 3;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Station|Story")
    float RetryS = 5.f;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Station|Story")
    float HoldoffAfterLineS = 6.f;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Station|Story")
    float DuckDb = -12.f;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Station|Story")
    float DuckS = 0.3f;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Station|Story")
    float FadeOutS = 1.f;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Station|Story")
    float ReturnToBagIfHeardBelow = 0.5f;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Station|Story")
    FVector2f AfterIdleDelayS = FVector2f(20.f, 40.f);

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Station|Captions")
    FString CaptionPrefix = TEXT("RADIO · ");

    /** (road m, q) pairs. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Station|Reception")
    TArray<FVector2f> QualityByRoadM;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Station|Reception")
    FVector2f VoiceLowpassHz = FVector2f(5500.f, 2400.f);

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Station|Reception")
    FVector2f VoiceHighpassHz = FVector2f(180.f, 450.f);

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Station|Reception")
    FVector2f VoiceGainDb = FVector2f(0.f, -4.f);

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Station|Reception")
    FVector2f StaticBetweenDb = FVector2f(-30.f, -16.f);

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Station|Reception")
    float StaticUnderSpeechDb = -8.f;

    /** Dropouts start below this q ... */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Station|Reception")
    float DropoutStartQ = 0.85f;

    /** ... and reach this rate (per second) at q = 0.25. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Station|Reception")
    float DropoutRateAtLowQ = 0.1667f;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Station|Reception")
    FVector2f DropoutLengthMs = FVector2f(80.f, 400.f);

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Station|Reception")
    float DropoutVoiceDb = -20.f;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Station|Reception")
    float DropoutStaticBoostDb = 6.f;

    /**
     * LANE5: below q = 0.25 the MapQ pairs hold their q = 0.25 value; these continue the fade to q = 0:
     * the voice sinks to VoiceGainDbAtQ0 (fragments in the static) and the static bed rises to
     * StaticBetweenDbAtQ0. At q = 0 the Low Voice is gone.
     */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Station|Reception")
    float VoiceGainDbAtQ0 = -40.f;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Station|Reception")
    float StaticBetweenDbAtQ0 = -6.f;

    /** LANE5: a lightning strike plays StaticIn at this level and forces a dropout on the voice. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Station|Reception")
    float LightningBurstDb = -8.f;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Station|Assets")
    FSoftObjectPath StaticBed;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Station|Assets")
    FSoftObjectPath StaticIn;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Station|Assets")
    FSoftObjectPath StaticOut;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Station|Assets")
    FSoftObjectPath TuneSweep;

    /** VO_Station_<id> lives here; the user's recordings in <HostFolder>/Recorded win over the TTS placeholders. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Station|Assets")
    FString HostFolder = TEXT("/Game/SaskartaGaea/Audio/Station/Host");

    /** SONG_<song_id> assets. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Station|Assets")
    FString SongFolder = TEXT("/Game/SaskartaGaea/Audio/Station/Songs");

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Station|Data")
    TArray<FSaskartaStationSegment> Segments;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Station|Data")
    TArray<FSaskartaStationSong> Songs;

    /** RADIOSHOW: the live show; Show.bShowMode selects it over the shuffle loop. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Station|Show")
    FSaskartaShowConfig Show;
};

UCLASS(BlueprintType)
class SASKARTACORE_API USaskartaStationAsset : public UPrimaryDataAsset
{
    GENERATED_BODY()

public:
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Station")
    FSaskartaStationConfig Config;

    /** The submix the station's sounds route to (their Sound Submix at import). */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Station|Filter")
    TSoftObjectPtr<USoundSubmix> StationSubmix;

    /** The archive filter: applied to StationSubmix as an effect-chain override at BeginPlay. Empty = the submix's own chain. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Station|Filter")
    TArray<TSoftObjectPtr<USoundEffectSubmixPreset>> ArchiveFilterChain;
};

UCLASS()
class SASKARTACORE_API USaskartaStationImport : public UBlueprintFunctionLibrary
{
    GENERATED_BODY()

public:
    static const TCHAR* StationAssetPath;

    /** docs/story/station.json + SourceArt/Audio/StationSongs/<id>.json sidecars -> Asset->Config (does not save). */
    UFUNCTION(BlueprintCallable, Category = "Saskarta|Station")
    static bool ImportStationFromFiles(USaskartaStationAsset* Asset, const FString& ProjectDir, FString& OutReport);

    /** Pure parser (tested). Song titles and singers come from SidecarJsonById (song id -> sidecar JSON). */
    static bool ParseStationJson(const FString& Json, const TMap<FName, FString>& SidecarJsonById, FSaskartaStationConfig& OutConfig, FString& OutError);

    /** DA_Station, or (editor builds only) a transient import of docs/story/station.json. Loads synchronously: debug and tools only (the station itself loads DA_Station asynchronously). */
    static USaskartaStationAsset* LoadStationOrImportTransient(UObject* Outer);

    /** RADIOSHOW: (editor builds only) a transient import of docs/story/station.json, no asset load; nullptr in a packaged game. */
    static USaskartaStationAsset* ImportTransient(UObject* Outer);
};
