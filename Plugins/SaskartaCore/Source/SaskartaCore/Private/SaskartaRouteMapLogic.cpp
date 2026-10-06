#include "SaskartaRouteMapLogic.h"

namespace SaskartaRouteMapLogic
{
    static void AddSegment(FSaskartaRouteFrame& F, const FVector2f& A, const FVector2f& B, float Alpha, float Thickness)
    {
        FSaskartaRoutePolyline& L = F.Lines.AddDefaulted_GetRef();
        L.Points = {A, B};
        L.Alpha = Alpha;
        L.Thickness = Thickness;
    }

    /** A closed shape of N segments around C (N = 4: a square turned 45 deg, a diamond). */
    static void AddRing(FSaskartaRouteFrame& F, const FVector2f& C, float R, int32 N, float Alpha, float PhaseDeg = 0.f)
    {
        FSaskartaRoutePolyline& L = F.Lines.AddDefaulted_GetRef();
        for (int32 I = 0; I <= N; ++I)
        {
            const float A = FMath::DegreesToRadians(PhaseDeg + 360.f * I / N);
            L.Points.Add(C + FVector2f(FMath::Cos(A), FMath::Sin(A)) * R);
        }
        L.Alpha = Alpha;
        L.Thickness = 1.f;
    }

    static void AddText(FSaskartaRouteFrame& F, const FVector2f& Pos, const FString& Text, int32 Size, float Alpha = 1.f)
    {
        if (Text.IsEmpty())
        {
            return;
        }
        FSaskartaRouteText& T = F.Texts.AddDefaulted_GetRef();
        T.Pos = Pos;
        T.Text = Text;
        T.Size = Size;
        T.Alpha = Alpha;
    }
}

void FSaskartaRouteMapCore::SetRoad(TArray<FSaskartaRoutePoint> Points)
{
    Points.StableSort([](const FSaskartaRoutePoint& A, const FSaskartaRoutePoint& B) { return A.RoadM < B.RoadM; });
    Road.Reset(Points.Num());
    for (const FSaskartaRoutePoint& P : Points)
    {
        if (Road.Num() == 0 || P.RoadM > Road.Last().RoadM + KINDA_SMALL_NUMBER)
        {
            Road.Add(P);
        }
    }
    Refit();
}

void FSaskartaRouteMapCore::UpsertNode(const FSaskartaRouteNode& Node)
{
    for (FSaskartaRouteNode& N : Nodes)
    {
        if (N.Id == Node.Id)
        {
            N = Node;
            return;
        }
    }
    Nodes.Add(Node);
    if (Node.bAlwaysShown)
    {
        Refit();
    }
}

const FSaskartaRouteNode* FSaskartaRouteMapCore::FindNode(FName Id) const
{
    return Nodes.FindByPredicate([Id](const FSaskartaRouteNode& N) { return N.Id == Id; });
}

void FSaskartaRouteMapCore::Refit()
{
    FBox2D Box(ForceInit);
    for (const FSaskartaRoutePoint& P : Road)
    {
        Box += P.WorldCm;
    }
    for (const FSaskartaRouteNode& N : Nodes)
    {
        if (N.bAlwaysShown)
        {
            Box += NodeWorld(N);
        }
    }
    Fit = FSaskartaRouteFit();
    if (!Box.bIsValid)
    {
        return;
    }
    const FVector2D Extent = Box.GetSize();
    const FVector2D PlotSize = Tuning.PlotMax - Tuning.PlotMin;
    const double Sx = Extent.X > 1.0 ? PlotSize.X / Extent.X : TNumericLimits<double>::Max();
    const double Sy = Extent.Y > 1.0 ? PlotSize.Y / Extent.Y : TNumericLimits<double>::Max();
    double S = FMath::Min(Sx, Sy);
    if (S == TNumericLimits<double>::Max())
    {
        S = 1.0; // a single point
    }
    Fit.MinCm = Box.Min;
    Fit.PxPerCm = S;
    // Centre the picture in the plot rectangle.
    Fit.OffsetPx = Tuning.PlotMin + (PlotSize - Extent * S) * 0.5;
}

FVector2D FSaskartaRouteMapCore::RoadAt(float RoadM) const
{
    if (Road.Num() == 0)
    {
        return FVector2D::ZeroVector;
    }
    if (RoadM <= Road[0].RoadM)
    {
        return Road[0].WorldCm;
    }
    if (RoadM >= Road.Last().RoadM)
    {
        return Road.Last().WorldCm;
    }
    int32 Lo = 0;
    int32 Hi = Road.Num() - 1;
    while (Hi - Lo > 1)
    {
        const int32 Mid = (Lo + Hi) / 2;
        (Road[Mid].RoadM <= RoadM ? Lo : Hi) = Mid;
    }
    const float Span = Road[Hi].RoadM - Road[Lo].RoadM;
    const float T = Span > 0.f ? (RoadM - Road[Lo].RoadM) / Span : 0.f;
    return FMath::Lerp(Road[Lo].WorldCm, Road[Hi].WorldCm, static_cast<double>(T));
}

FVector2D FSaskartaRouteMapCore::NodeWorld(const FSaskartaRouteNode& Node) const
{
    return Node.bHasWorld ? Node.WorldCm : RoadAt(Node.RoadM);
}

bool FSaskartaRouteMapCore::IsNodeShown(const FSaskartaRouteNode& Node) const
{
    return Node.bAlwaysShown || Node.RoadM <= HighWaterRoadM + Tuning.PassedSlackM;
}

TArray<int32> FSaskartaRouteMapCore::SelectableOrder() const
{
    TArray<int32> Out;
    for (int32 I = 0; I < Nodes.Num(); ++I)
    {
        if (Nodes[I].bSelectable && IsNodeShown(Nodes[I]))
        {
            Out.Add(I);
        }
    }
    Out.StableSort([this](int32 A, int32 B) { return Nodes[A].RoadM < Nodes[B].RoadM; });
    return Out;
}

FName FSaskartaRouteMapCore::LatestNode() const
{
    const TArray<int32> Order = SelectableOrder();
    if (Order.Num() == 0)
    {
        return NAME_None;
    }
    const float At = bHasCarrier ? CarrierRoadM : HighWaterRoadM;
    int32 Best = Order[0];
    for (const int32 I : Order)
    {
        if (Nodes[I].RoadM <= At + Tuning.PassedSlackM)
        {
            Best = I;
        }
    }
    return Nodes[Best].Id;
}

void FSaskartaRouteMapCore::EnsureSelection()
{
    const TArray<int32> Order = SelectableOrder();
    for (const int32 I : Order)
    {
        if (Nodes[I].Id == SelectedId)
        {
            return;
        }
    }
    SelectedId = LatestNode();
}

void FSaskartaRouteMapCore::Step(int32 Dir)
{
    const TArray<int32> Order = SelectableOrder();
    if (Order.Num() == 0)
    {
        SelectedId = NAME_None;
        return;
    }
    int32 Pos = Order.IndexOfByPredicate([this](int32 I) { return Nodes[I].Id == SelectedId; });
    if (Pos == INDEX_NONE)
    {
        SelectedId = LatestNode();
        return;
    }
    Pos = FMath::Clamp(Pos + Dir, 0, Order.Num() - 1);
    SelectedId = Nodes[Order[Pos]].Id;
}

FSaskartaRouteFrame FSaskartaRouteMapCore::BuildFrame() const
{
    using namespace SaskartaRouteMapLogic;
    const FSaskartaRouteMapTuning& T = Tuning;
    FSaskartaRouteFrame F;
    const float X0 = static_cast<float>(T.PlotMin.X);
    const float X1 = static_cast<float>(T.PlotMax.X);
    const float FooterY = static_cast<float>(T.Size.Y) - 18.f;
    AddText(F, FVector2f(X0, 8.f), Header(bHasCarrier ? CarrierRoadM : HighWaterRoadM), T.HeaderSize);
    {
        // The rule under the header and above the INSPECT lines, as on the ROUTE LOG board.
        const float Y0 = static_cast<float>(T.PlotMin.Y) - 8.f;
        const float Y1 = static_cast<float>(T.PlotMax.Y) + 8.f;
        AddSegment(F, FVector2f(X0, Y0), FVector2f(X1, Y0), 0.35f, 1.f);
        AddSegment(F, FVector2f(X0, Y1), FVector2f(X1, Y1), 0.35f, 1.f);
    }
    if (!Fit.IsValid() || Road.Num() < 2)
    {
        AddText(F, FVector2f(X0, static_cast<float>(T.PlotMax.Y) + 16.f), TEXT("NO ROUTE DATA"), T.InspectSize);
        AddText(F, FVector2f(X0, FooterY), Footer(T.bGamepad), T.FooterSize, 0.6f);
        return F;
    }

    // --- the road: solid to the high-water mark, then fading into the dark.
    const float Hw = HighWaterRoadM;
    const float FadeEnd = Hw + FMath::Max(T.FadeAheadM, 0.f);
    FSaskartaRoutePolyline Driven;
    Driven.Alpha = 1.f;
    Driven.Thickness = T.RoadThickness;
    for (const FSaskartaRoutePoint& P : Road)
    {
        if (P.RoadM >= Hw)
        {
            break;
        }
        Driven.Points.Add(Fit.ToPlot(P.WorldCm));
    }
    Driven.Points.Add(Fit.ToPlot(RoadAt(Hw)));
    if (Driven.Points.Num() >= 2)
    {
        F.Lines.Add(MoveTemp(Driven));
    }
    if (FadeEnd > Hw && Hw < Road.Last().RoadM)
    {
        TArray<float> Stops = {Hw};
        for (const FSaskartaRoutePoint& P : Road)
        {
            if (P.RoadM > Hw && P.RoadM < FadeEnd)
            {
                Stops.Add(P.RoadM);
            }
        }
        Stops.Add(FMath::Min(FadeEnd, Road.Last().RoadM));
        for (int32 I = 0; I + 1 < Stops.Num(); ++I)
        {
            const float Mid = 0.5f * (Stops[I] + Stops[I + 1]);
            const float Alpha = T.FadeStartAlpha * (1.f - (Mid - Hw) / (FadeEnd - Hw));
            if (Alpha > 0.02f && Stops[I + 1] > Stops[I])
            {
                AddSegment(F, Fit.ToPlot(RoadAt(Stops[I])), Fit.ToPlot(RoadAt(Stops[I + 1])), Alpha, 1.f);
            }
        }
    }

    // --- the nodes.
    const float R = T.NodePx;
    for (const FSaskartaRouteNode& N : Nodes)
    {
        if (!IsNodeShown(N))
        {
            continue;
        }
        const FVector2f C = Fit.ToPlot(NodeWorld(N));
        const bool bSel = N.Id == SelectedId;
        const float A = bSel ? 1.f : 0.75f;
        switch (N.Kind)
        {
        case ESaskartaRouteNodeKind::Stele:
            AddRing(F, C, R * 1.2f, 4, A, 45.f); // a square
            break;
        case ESaskartaRouteNodeKind::Mast:
            AddRing(F, C, R * 1.6f, 10, A); // hollow, the goal
            AddSegment(F, C + FVector2f(0.f, -R * 1.6f), C + FVector2f(0.f, -R * 4.f), A, 1.f);
            break;
        case ESaskartaRouteNodeKind::Wreck:
            AddSegment(F, C + FVector2f(-R, -R), C + FVector2f(R, R), A, 1.f);
            AddSegment(F, C + FVector2f(-R, R), C + FVector2f(R, -R), A, 1.f);
            break;
        case ESaskartaRouteNodeKind::Query:
            if (N.Mark == ESaskartaRouteMark::Resolved)
            {
                // The vector tick (the terminal font has no check mark).
                FSaskartaRoutePolyline& L = F.Lines.AddDefaulted_GetRef();
                L.Points = {C + FVector2f(-R, 0.f), C + FVector2f(-R * 0.3f, R * 0.8f), C + FVector2f(R * 1.1f, -R * 1.1f)};
                L.Alpha = A;
            }
            else if (N.Mark != ESaskartaRouteMark::Open)
            {
                AddSegment(F, C + FVector2f(0.f, -R * 0.6f), C + FVector2f(0.f, R * 0.6f), A, 1.f);
            }
            break;
        default:
            AddRing(F, C, R, 6, A);
            break;
        }
        // ROUTE_BOARD_V3.md: a place shows its name or its number, never a ?.
        AddText(F, C + FVector2f(R + 3.f, -R - 10.f), N.Label, T.LabelSize, A);
        if (bSel)
        {
            // Corner brackets around the selected node.
            const float B = R * 2.6f;
            const float K = R * 1.1f;
            for (const FVector2f& S : {FVector2f(-1.f, -1.f), FVector2f(1.f, -1.f), FVector2f(1.f, 1.f), FVector2f(-1.f, 1.f)})
            {
                const FVector2f P = C + S * B;
                FSaskartaRoutePolyline& L = F.Lines.AddDefaulted_GetRef();
                L.Points = {P - FVector2f(S.X * K, 0.f), P, P - FVector2f(0.f, S.Y * K)};
                L.Alpha = 1.f;
            }
        }
    }

    // --- the carrier: a chevron along its heading.
    if (bHasCarrier)
    {
        const FVector2f C = Fit.ToPlot(CarrierCm);
        const float Yaw = FMath::DegreesToRadians(CarrierYawDeg);
        const FVector2f Fwd(FMath::Cos(Yaw), FMath::Sin(Yaw));
        const FVector2f Side(-Fwd.Y, Fwd.X);
        const float S = T.CarrierPx;
        FSaskartaRoutePolyline& L = F.Lines.AddDefaulted_GetRef();
        L.Points = {C + Fwd * S, C - Fwd * (S * 0.6f) + Side * (S * 0.6f), C - Fwd * (S * 0.25f), C - Fwd * (S * 0.6f) - Side * (S * 0.6f), C + Fwd * S};
        L.Alpha = 1.f;
        L.Thickness = 1.5f;
    }

    // --- INSPECT and the keys.
    const float InspectY = static_cast<float>(T.PlotMax.Y) + 14.f;
    if (const FSaskartaRouteNode* Sel = FindNode(SelectedId))
    {
        AddText(F, FVector2f(X0, InspectY), Sel->Title, T.InspectSize);
        for (int32 I = 0; I < Sel->Lines.Num() && I < T.MaxInspectLines; ++I)
        {
            AddText(F, FVector2f(X0, InspectY + (I + 1) * (T.InspectSize + 3.f)), Sel->Lines[I], T.InspectSize, 0.85f);
        }
    }
    else
    {
        AddText(F, FVector2f(X0, InspectY), TEXT("NO NODES LOGGED"), T.InspectSize, 0.6f);
    }
    AddText(F, FVector2f(X0, FooterY), Footer(T.bGamepad), T.FooterSize, 0.6f);
    return F;
}

ESaskartaRouteMark FSaskartaRouteMapCore::MarkForQuery(const FString& Result)
{
    return Result.IsEmpty() ? ESaskartaRouteMark::None : ESaskartaRouteMark::Resolved;
}

FString FSaskartaRouteMapCore::GroupedMetres(float M)
{
    const int32 V = FMath::Max(0, FMath::RoundToInt(M));
    return V >= 1000 ? FString::Printf(TEXT("%d,%03d"), V / 1000, V % 1000) : FString::Printf(TEXT("%d"), V);
}

FString FSaskartaRouteMapCore::Header(float RoadM)
{
    return FString::Printf(TEXT("MAP . ^ YOU %s M"), *GroupedMetres(RoadM));
}

FString FSaskartaRouteMapCore::Footer(bool bGamepad)
{
    return bGamepad ? FString(TEXT("D-PAD LEFT RIGHT . SELECT . D-PAD DOWN CLOSE"))
                    : FString(TEXT("LEFT RIGHT . WHEEL SELECT . M  CLOSE"));
}
