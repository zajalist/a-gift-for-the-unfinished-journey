// The CRT route map (M / View): the pure part. Engine-free (FName, containers, FString, FVector2D, FMath),
// so the Saskarta.RouteMap.* tests drive it directly. USaskartaRouteMap (SaskartaRouteMap.h) feeds it the
// road polyline, the carrier and the nodes, and paints the FSaskartaRouteFrame it builds as phosphor
// vector lines and text on the carrier's CRT.
//
// Rules:
//   - north-up top-down (north = -Y is up, east = +X is right; road-profile.json's convention), fitted
//     once to the whole road and the mast so the picture never rescales while driving;
//   - the road is drawn up to the high-water road m, then fades into the dark over FadeAheadM; nothing
//     else is drawn ahead of the high-water mark except the mast (bAlwaysShown);
//   - the node list is general (the energy design's ROUTE LOG board reuses it): a kind, a road m, an
//     optional world position (else the road point at its road m), a mark (resolved / open), a short
//     label and the INSPECT lines shown when it is selected;
//   - selection steps through the shown, selectable nodes in road order (D-pad / arrows / wheel).
//
// Font_Terminal (VT323) has no check mark: a resolved query is drawn as a two-segment vector tick.

#pragma once

#include "CoreMinimal.h"

enum class ESaskartaRouteNodeKind : uint8
{
    Stele,
    Query,
    Wreck,
    Mast,
    Site,
};

enum class ESaskartaRouteMark : uint8
{
    None,
    Resolved,
    Open,
};

struct SASKARTACORE_API FSaskartaRouteNode
{
    FName Id;
    ESaskartaRouteNodeKind Kind = ESaskartaRouteNodeKind::Site;
    float RoadM = 0.f;
    /** World XY in cm; used when bHasWorld, else the road point at RoadM. */
    FVector2D WorldCm = FVector2D::ZeroVector;
    bool bHasWorld = false;
    ESaskartaRouteMark Mark = ESaskartaRouteMark::None;
    /** Short text drawn beside the node ("03", "?"); may be empty. */
    FString Label;
    /** INSPECT header when selected. */
    FString Title;
    /** INSPECT body when selected (at most MaxInspectLines are drawn). */
    TArray<FString> Lines;
    /** Drawn even ahead of the high-water mark (the mast). */
    bool bAlwaysShown = false;
    bool bSelectable = true;
};

struct SASKARTACORE_API FSaskartaRoutePoint
{
    float RoadM = 0.f;
    FVector2D WorldCm = FVector2D::ZeroVector;
};

struct SASKARTACORE_API FSaskartaRouteMapTuning
{
    /** Widget draw size (px). */
    FVector2D Size = FVector2D(640.f, 440.f);
    /** The plot rectangle inside it (between the header and the INSPECT lines). */
    FVector2D PlotMin = FVector2D(20.f, 40.f);
    FVector2D PlotMax = FVector2D(620.f, 346.f);
    /** Road drawn past the high-water mark, fading to nothing. */
    float FadeAheadM = 220.f;
    float FadeStartAlpha = 0.55f;
    /** Nodes up to this far past the high-water mark count as passed (a stele read from the road ahead). */
    float PassedSlackM = 30.f;
    float NodePx = 4.f;
    float CarrierPx = 9.f;
    float RoadThickness = 1.5f;
    int32 HeaderSize = 18;
    int32 LabelSize = 12;
    int32 InspectSize = 16;
    int32 FooterSize = 12;
    int32 MaxInspectLines = 2;
    /** Footer keys: pad labels when the last input was a gamepad. */
    bool bGamepad = false;
};

struct SASKARTACORE_API FSaskartaRoutePolyline
{
    TArray<FVector2f> Points;
    float Alpha = 1.f;
    float Thickness = 1.f;
};

struct SASKARTACORE_API FSaskartaRouteText
{
    FVector2f Pos = FVector2f::ZeroVector;
    FString Text;
    float Alpha = 1.f;
    int32 Size = 12;
};

/** Everything one paint draws, in widget px. */
struct SASKARTACORE_API FSaskartaRouteFrame
{
    TArray<FSaskartaRoutePolyline> Lines;
    TArray<FSaskartaRouteText> Texts;
};

/** World cm -> plot px (uniform scale, north-up). */
struct SASKARTACORE_API FSaskartaRouteFit
{
    FVector2D MinCm = FVector2D::ZeroVector;
    double PxPerCm = 0.0;
    FVector2D OffsetPx = FVector2D::ZeroVector;

    bool IsValid() const { return PxPerCm > 0.0; }
    FVector2f ToPlot(const FVector2D& WorldCm) const
    {
        return FVector2f(OffsetPx + (WorldCm - MinCm) * PxPerCm);
    }
};

struct SASKARTACORE_API FSaskartaRouteMapCore
{
    FSaskartaRouteMapTuning Tuning;
    /** Sorted by road m (SetRoad). */
    TArray<FSaskartaRoutePoint> Road;
    TArray<FSaskartaRouteNode> Nodes;
    float HighWaterRoadM = 0.f;
    float CarrierRoadM = 0.f;
    FVector2D CarrierCm = FVector2D::ZeroVector;
    /** Unreal yaw (atan2(dY, dX)) in degrees. */
    float CarrierYawDeg = 0.f;
    bool bHasCarrier = false;
    FName SelectedId;
    FSaskartaRouteFit Fit;

    /** Sorts, drops points with the same road m, and refits. */
    void SetRoad(TArray<FSaskartaRoutePoint> Points);
    /** Replaces the node with the same id, or adds it. */
    void UpsertNode(const FSaskartaRouteNode& Node);
    const FSaskartaRouteNode* FindNode(FName Id) const;
    /** Fits the road and every bAlwaysShown node into the plot rectangle. */
    void Refit();

    /** The road point at RoadM (clamped to the ends; zero when there is no road). */
    FVector2D RoadAt(float RoadM) const;
    FVector2D NodeWorld(const FSaskartaRouteNode& Node) const;

    /** Passed (RoadM <= HighWaterRoadM + PassedSlackM) or bAlwaysShown. */
    bool IsNodeShown(const FSaskartaRouteNode& Node) const;
    /** Shown, selectable nodes, as indices into Nodes, in road order. */
    TArray<int32> SelectableOrder() const;
    /** The last selectable node at or behind the carrier (else the first). None when nothing is shown. */
    FName LatestNode() const;
    /** Moves the selection Dir steps in road order (clamped); selects the latest node first. */
    void Step(int32 Dir);
    /** Keeps SelectedId valid: the latest node when it is None or no longer selectable. */
    void EnsureSelection();

    /** The whole picture for one paint. */
    FSaskartaRouteFrame BuildFrame() const;

    // ------------------------------------------------------------------ helpers (tested)
    /** A query's mark: Resolved when it has a result line (ROUTE_BOARD_V3.md: no open ? any more). */
    static ESaskartaRouteMark MarkForQuery(const FString& Result);
    /** The player position: "MAP . ^ YOU 1,312 M". */
    static FString Header(float RoadM);
    static FString Footer(bool bGamepad);
    /** "1,312" */
    static FString GroupedMetres(float M);
};
