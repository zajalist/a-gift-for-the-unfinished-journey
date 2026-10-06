// Story event data types: triggers, actions, beats, lines and cinematics.
//
// Spec: docs/story/EVENTS.md sections 2, 4 and 5; data: docs/story/story-events.json.
// The structs mirror the JSON one to one. USaskartaStoryImport fills them from the JSON
// (editor lane: DA_Saskarta_Story), and USaskartaEventRunner executes them.
//
// A cinematic cue is an FSaskartaEventAction with AtS set (EVENTS.md names a separate
// FSaskartaCinematicCue {AtS, Action}; one struct is simpler and keeps the cue flags
// keep_on_skip, keep_after_cinematic, pauses_sequence and after_prompt in one place).

#pragma once

#include "CoreMinimal.h"
#include "SaskartaCaptionPaging.h"
#include "UObject/SoftObjectPtr.h"
#include "SaskartaEventTypes.generated.h"

class ULevelSequence;
class USoundBase;

UENUM(BlueprintType)
enum class ESaskartaTriggerType : uint8
{
    None,
    /** Fires when the high-water UE m first drops to or below UeDistanceM (carrier). */
    RoadPass,
    /** The same, but only while FlowState is Human (the traveller on foot). */
    RoadPassHuman,
    /** ASaskartaEventVolume with a matching TriggerId. */
    Volume,
    /** USaskartaEventLibrary::ReportFlow with a matching FlowEvent. */
    Flow,
    /** Chained from a Prompt action's NextBeat. */
    Prompt,
    /** FireBeat from Blueprint or the console. */
    Scripted,
    Manual
};

UENUM(BlueprintType)
enum class ESaskartaActionType : uint8
{
    None,
    PlayRadioLine,
    PlayCarrierLine,
    PlayCinematic,
    ShowCaption,
    ShowSubtitle,
    /** "SetLook" in the JSON (the user's brief calls it SetLookKey; both spellings import). */
    SetLook,
    SetFog,
    SpawnOrReveal,
    SetFlowState,
    Wait,
    Prompt,
    PlaySfx,
    Glance,
    SetInputLock,
    CallHook,
    Checkpoint,
    SetMode,
    SetControlRotation,
    ShowLetterbox,
    SetGeiger,
    ShowEndCard,
    OpenLevel,
    /** HUD query on HudLine (SaskartaHudQueryLogic.h): Text, then ResultText; ColumnText joins the ?-column. TargetTag HudColumn: Value 1 shows / 0 fades the column. */
    ShowHudQuery,
    /** First light (USaskartaLightingDirector::PlayDawn): DurationS the ramp, Value the second the disc clears, Pitch the horizon pitch, Yaw the sun yaw. */
    PlayDawn,
    /** Stops the sound a PlaySfx with the same Id started (the newest one), fading over DurationS (0 = a hard cut). */
    StopSfx
};

/** Lower runs first. */
UENUM(BlueprintType)
enum class ESaskartaEventPriority : uint8
{
    Critical = 0,
    Cinematic = 1,
    Story = 2,
    Hint = 3
};

UENUM(BlueprintType)
enum class ESaskartaSkipRule : uint8
{
    Never,
    /** Skippable once it has been seen in any playthrough (the profile save). */
    HoldAfterSeen,
    HoldAlways,
    /** The end card: any key after SkipMinS. */
    AnyKeyAfter
};

USTRUCT(BlueprintType)
struct SASKARTACORE_API FSaskartaEventTrigger
{
    GENERATED_BODY()

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Events")
    ESaskartaTriggerType Type = ESaskartaTriggerType::None;

    /** RoadPass*: RoadSpline distance from point 0, in metres (it falls as the carrier advances). */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Events")
    float UeDistanceM = -1.f;

    /** Road m (from the dock) for docs and debug. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Events")
    float RoadM = -1.f;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Events")
    FName VolumeId;

    /** Flow: FirstBootVisionOnline, RebootVisionOnline, TetherWarning, Collapsing, HumanPossessed, TitleStart. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Events")
    FName FlowEvent;

    /** Optional gate on PC_Saskarta.FlowState. None = any state. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Events")
    FName RequiredFlowState;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Events")
    bool bOneShot = true;

    /** Repeatable beats: minimum seconds between firings. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Events")
    float CooldownS = 0.f;

    /** Dropped if it waits in the queue longer than this. 0 = never (Hint beats always drop after 4 s). */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Events")
    float MaxLatenessS = 0.f;
};

USTRUCT(BlueprintType)
struct SASKARTACORE_API FSaskartaEventAction
{
    GENERATED_BODY()

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Events")
    ESaskartaActionType Type = ESaskartaActionType::None;

    /** Line id, cinematic id, look key, reveal tag, hook name, flow state, glance id or checkpoint. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Events")
    FName Id;

    /** Cinematic cues only: seconds from the sequence start. -1 on beat actions. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Events")
    float AtS = -1.f;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Events")
    float DelayS = 0.f;

    /** Start the next action together with this one. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Events")
    bool bParallel = false;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Events")
    float DurationS = 0.f;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Events")
    FText Text;

    /** Target actor tag. The keywords PC and Pawn mean the player controller and its pawn; Hud routes a caption to the HUD line. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Events")
    FName TargetTag;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Events")
    float Value = 0.f;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Events")
    float Pitch = 0.f;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Events")
    float Yaw = 0.f;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Events")
    bool bReapplyOnLoad = false;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Events")
    TArray<FName> RequiresTags;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Events")
    TArray<FName> ExcludesTags;

    /** Prompt: the beat fired on the key press. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Events")
    FName NextBeat;

    /** Cue: still plays after a skip (it teaches something). */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Events")
    bool bKeepOnSkip = false;

    /** Cue: the line moves to the normal Voice channel at the hand-back instead of stopping. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Events")
    bool bKeepAfterCinematic = false;

    /** Prompt cue: pause the sequence until the key press. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Events")
    bool bPausesSequence = false;

    /** Cue: waits for the previous prompt's key press. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Events")
    bool bAfterPrompt = false;

    /** Skipped once the game has been completed (the profile save). */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Events")
    bool bFirstPlaythroughOnly = false;

    /** ShowHudQuery: the result shown after the query (empty: the query alone, e.g. BEND 3 or a cinematic's borrowed line). */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Events")
    FText ResultText;

    /** ShowHudQuery: the entry this query leaves in the ?-column when it ends (empty: it clears). */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Events")
    FText ColumnText;
};

USTRUCT(BlueprintType)
struct SASKARTACORE_API FSaskartaBeatDef
{
    GENERATED_BODY()

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Events")
    FName Id;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Events")
    FSaskartaEventTrigger Trigger;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Events")
    ESaskartaEventPriority Priority = ESaskartaEventPriority::Story;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Events")
    TArray<FSaskartaEventAction> Actions;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Events")
    TArray<FName> RequiresTags;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Events")
    TArray<FName> ExcludesTags;

    /** From optional_beats[]. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Events")
    bool bOptional = false;

    /** From system_beats[] (repeatable flow beats, never saved). */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Events")
    bool bSystem = false;
};

USTRUCT(BlueprintType)
struct SASKARTACORE_API FSaskartaLineDef
{
    GENERATED_BODY()

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Events")
    FName Id;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Events")
    FName Speaker;

    /** /Game/SaskartaGaea/Audio/Lines/<Id> by convention; empty = resolved by name at runtime. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Events")
    TSoftObjectPtr<USoundBase> Sound;

    /** The English subtitle (for a Saskartan line, its translation). */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Events")
    FString English;

    /** TSV column "Saskartan translation". */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Events")
    FString Saskartan;

    /** TSV column Language == SKS. Never hard-coded by id. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Events")
    bool bSaskartan = false;

    /** ARCHIVE nn · PLACE, shown for 4 s at the start of the line. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Events")
    FString CaptionHeader;

    /** Recorded duration (durations.json), else the TSV target. The sound's own duration wins at runtime. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Events")
    float DurationS = 0.f;

    /** Carrier voice style: system, warning, failing. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Events")
    FName Style;

    /** CV_* lines: subtitle prefix "CARRIER: ". */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Events")
    bool bCarrier = false;

    /** Authored page starts relative to the sound's beginning. Empty uses proportional paging. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Events")
    TArray<FSaskartaCaptionPage> CaptionPages;
};

USTRUCT(BlueprintType)
struct SASKARTACORE_API FSaskartaCinematicDef
{
    GENERATED_BODY()

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Cinematics")
    FName Id;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Cinematics")
    TSoftObjectPtr<ULevelSequence> Sequence;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Cinematics")
    float DurationS = 0.f;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Cinematics")
    float BlendInS = 0.f;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Cinematics")
    float BlendOutS = 2.f;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Cinematics")
    bool bLetterbox = true;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Cinematics")
    ESaskartaSkipRule SkipRule = ESaskartaSkipRule::HoldAfterSeen;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Cinematics")
    float SkipMinS = 1.f;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Cinematics")
    bool bStopPawn = true;

    /** Camera-only scene: keep the same station audio component and playback cursor.
     * Carrier cues briefly duck it; archive/ending scenes retain the default suspension. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Events")
    bool bKeepStationPlaying = false;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Cinematics")
    bool bRelativeToPawn = true;

    /** Sorted by AtS on import. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Cinematics")
    TArray<FSaskartaEventAction> Cues;

    /** CarrierPOV (default), Traveller, EndingSet or None. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Cinematics")
    FName HandBack = TEXT("CarrierPOV");

    /** Run at the end or on skip. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Cinematics")
    TArray<FSaskartaEventAction> FinalState;
};

USTRUCT(BlueprintType)
struct SASKARTACORE_API FSaskartaGlanceDef
{
    GENERATED_BODY()

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Events")
    FName Id;

    /** Actor tag of the TargetPoint, e.g. Saskarta.Glance.Platform. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Events")
    FName TargetTag;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Events")
    float EaseInS = 1.5f;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Events")
    float HoldS = 2.f;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Events")
    bool bLockMove = false;
};

/** What the subtitle widget shows. Broadcast by the runner (story lines and, at lower priority, the station). */
USTRUCT(BlueprintType)
struct SASKARTACORE_API FSaskartaSubtitle
{
    GENERATED_BODY()

    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Subtitles")
    FName LineId;

    /** The English line, with the CARRIER: or RADIO · prefix already applied. */
    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Subtitles")
    FText English;

    /** Small, dim, above the English line. Empty unless the line is SKS and "Show original Saskartan" is on. */
    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Subtitles")
    FText Saskartan;

    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Subtitles")
    bool bSaskartan = false;

    /** ARCHIVE nn · PLACE (4 s), or empty. */
    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Subtitles")
    FText Header;

    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Subtitles")
    FName Speaker;

    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Subtitles")
    float DurationS = 0.f;

    /** A station caption: any story subtitle replaces it at once. */
    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Subtitles")
    bool bStation = false;

    /** Input pages for a station line; emitted subtitle events contain only the current page. */
    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Subtitles")
    TArray<FSaskartaCaptionPage> Pages;

    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Subtitles")
    int32 PageIndex = 0;

    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Subtitles")
    int32 PageCount = 1;

    /** Seconds already heard when resuming a station take. */
    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Subtitles")
    float StartOffsetS = 0.f;
};
