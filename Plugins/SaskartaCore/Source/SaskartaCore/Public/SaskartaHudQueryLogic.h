// FSaskartaHudLane: the carrier's HUD queries and wreck lines on HudLine (storyline-first-light.md 4.2-4.3).
//
// Pure: no world, no UObjects; USaskartaEventRunner owns one and turns its outputs into
// OnCaptionShow / OnCaptionHide (targets Hud and HudColumn) and the tick SFX. Rules:
// - a query shows QueryS (2 s), then its result ResultS (3 s); an item with no result shows QueryS only;
// - optional status text uses HudColumn and can be faded by a HudStatus cue;
// - HudLine is shared: a query waits while another HUD line (a POI line) holds it, and a wreck line
//   (bPriority) goes ahead of waiting queries; a road item that waited MaxWaitS is stale and dropped;
// - while the runner holds the lane (a letterboxed cinematic) nothing road-triggered starts and the wait
//   does not age; a cinematic cue (bImmediate) starts at once and puts an interrupted query back first.
// Transient status text is not checkpoint state.

#pragma once

#include "CoreMinimal.h"
#include "SaskartaEventTypes.h"

struct SASKARTACORE_API FSaskartaHudItem
{
    FName Id;
    FString Query;
    FString Result;
    float QueryS = 2.f;
    float ResultS = 3.f;
    bool bPriority = false;
    bool bImmediate = false;
    double QueuedAtS = 0.0;
};

enum class ESaskartaHudOut : uint8 { ShowLine, HideLine, ShowColumn, HideColumn, Tick };

struct SASKARTACORE_API FSaskartaHudOutput
{
    ESaskartaHudOut Kind = ESaskartaHudOut::ShowLine;
    FString Text;
    float DurationS = 0.f;
};

struct SASKARTACORE_API FSaskartaHudLane
{
    static constexpr float DefaultQueryS = 2.f;
    static constexpr float DefaultResultS = 3.f;
    static constexpr float MaxWaitS = 12.f;
    static const FName ColumnTarget; // HudColumn: the caption target the status lines show on
    static const FName StatusTarget; // HudStatus: Value 1 shows / 0 fades the status lines (as HudColumn did)
    static const FName PriorityTarget; // HudPriority

    TArray<FSaskartaHudItem> Pending;
    FSaskartaHudItem Active;
    bool bActive = false;
    bool bInResult = false;
    double PhaseEndS = 0.0;
    double ExternalBusyUntilS = -1.0;
    /** The status lines (one string, one line a line). */
    FString Column;
    bool bColumnVisible = true;

    /** Queues (or, bImmediate, starts) an item, then advances. */
    void Push(FSaskartaHudItem Item, double NowS, bool bHeld, TArray<FSaskartaHudOutput>& Out);

    /** Another HUD line (ShowCaption on Hud) took HudLine for DurationS. */
    void NoteExternalLine(double NowS, float DurationS, TArray<FSaskartaHudOutput>& Out);

    /** Ends phases that are due and starts the next item when HudLine is free and the lane is not held. */
    void Advance(double NowS, bool bHeld, TArray<FSaskartaHudOutput>& Out);

    void SetColumnVisible(bool bVisible, TArray<FSaskartaHudOutput>& Out);

    /** Replaces the status lines; shown at once unless faded. */
    void SetStatus(const FString& Status, TArray<FSaskartaHudOutput>& Out);

    /** Drops the queue and the active item (the column stays). */
    void Reset(TArray<FSaskartaHudOutput>& Out);

    bool IsIdle() const { return !bActive && Pending.Num() == 0; }

    /** A ShowHudQuery action (not a HudColumn / HudStatus command) as an item. */
    static bool ItemFromAction(const FSaskartaEventAction& A, FSaskartaHudItem& Out);

    /** Every action is ShowHudQuery: the runner plays it on the lane instead of the beat queue (no Voice, no wait). */
    static bool IsHudOnlyBeat(const FSaskartaBeatDef& Beat);


private:
    void Start(FSaskartaHudItem Item, double NowS, TArray<FSaskartaHudOutput>& Out);
    void Finish(bool bHide, TArray<FSaskartaHudOutput>& Out);
};
