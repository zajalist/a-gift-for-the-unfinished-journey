// Automation tests for the CRT route map's pure core (SaskartaRouteMapLogic.h): north-up fitting, nothing
// ahead of the high-water mark but the fading road and the mast, selection in road order, query marks and
// the header strings. Written offline (no build ran). Run after the build:
//   Automation RunTests Saskarta.RouteMap

#include "Misc/AutomationTest.h"

#if WITH_DEV_AUTOMATION_TESTS

#include "SaskartaRouteMapLogic.h"
#include "SaskartaRouteMap.h"
#include "SaskartaPower.h"

#define SASKARTA_ROUTEMAP_TEST_FLAGS (EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)

namespace SaskartaRouteMapTest
{
    /** A straight road running north (-Y) for 1000 m, a point every 10 m. */
    static FSaskartaRouteMapCore StraightNorth()
    {
        FSaskartaRouteMapCore C;
        TArray<FSaskartaRoutePoint> Road;
        for (int32 M = 0; M <= 1000; M += 10)
        {
            Road.Add({static_cast<float>(M), FVector2D(0.0, -M * 100.0)});
        }
        C.SetRoad(Road);
        return C;
    }

    static FSaskartaRouteNode Node(const TCHAR* Id, ESaskartaRouteNodeKind Kind, float RoadM)
    {
        FSaskartaRouteNode N;
        N.Id = FName(Id);
        N.Kind = Kind;
        N.RoadM = RoadM;
        N.Title = Id;
        return N;
    }

    /** The farthest north (smallest plot y) any line inside the plot reaches (the header and INSPECT rules excluded). */
    static float TopMostY(const FSaskartaRouteFrame& F, const FSaskartaRouteMapTuning& T)
    {
        float Top = TNumericLimits<float>::Max();
        for (const FSaskartaRoutePolyline& L : F.Lines)
        {
            for (const FVector2f& P : L.Points)
            {
                if (P.Y > T.PlotMin.Y - 1.0 && P.Y < T.PlotMax.Y + 1.0)
                {
                    Top = FMath::Min(Top, P.Y);
                }
            }
        }
        return Top;
    }
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaRouteMapFitTest, "Saskarta.RouteMap.Fit", SASKARTA_ROUTEMAP_TEST_FLAGS)
bool FSaskartaRouteMapFitTest::RunTest(const FString&)
{
    using namespace SaskartaRouteMapTest;
    FSaskartaRouteMapCore C = StraightNorth();
    TestTrue(TEXT("fitted"), C.Fit.IsValid());
    const FVector2f Start = C.Fit.ToPlot(C.RoadAt(0.f));
    const FVector2f End = C.Fit.ToPlot(C.RoadAt(1000.f));
    TestTrue(TEXT("north is up: the road's end is above its start"), End.Y < Start.Y);
    TestTrue(TEXT("inside the plot"), End.Y >= C.Tuning.PlotMin.Y - 0.5 && Start.Y <= C.Tuning.PlotMax.Y + 0.5);
    TestTrue(TEXT("a straight north road is centred"), FMath::IsNearlyEqual(Start.X, static_cast<float>(0.5 * (C.Tuning.PlotMin.X + C.Tuning.PlotMax.X)), 0.5f));
    TestTrue(TEXT("RoadAt interpolates"), C.RoadAt(505.f).Equals(FVector2D(0.0, -50500.0), 1.0));
    TestTrue(TEXT("RoadAt clamps"), C.RoadAt(5000.f).Equals(FVector2D(0.0, -100000.0), 1.0));

    // East is right.
    FSaskartaRouteMapCore E;
    E.SetRoad({{0.f, FVector2D(0.0, 0.0)}, {100.f, FVector2D(10000.0, 0.0)}});
    TestTrue(TEXT("east is right"), E.Fit.ToPlot(FVector2D(10000.0, 0.0)).X > E.Fit.ToPlot(FVector2D(0.0, 0.0)).X);
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaRouteMapHighWaterTest, "Saskarta.RouteMap.HighWater", SASKARTA_ROUTEMAP_TEST_FLAGS)
bool FSaskartaRouteMapHighWaterTest::RunTest(const FString&)
{
    using namespace SaskartaRouteMapTest;
    FSaskartaRouteMapCore C = StraightNorth();
    C.Tuning.FadeAheadM = 200.f;
    C.HighWaterRoadM = 400.f;
    C.CarrierRoadM = 400.f;
    C.bHasCarrier = true;
    C.CarrierCm = C.RoadAt(400.f);
    C.CarrierYawDeg = -90.f;
    C.UpsertNode(Node(TEXT("S_behind"), ESaskartaRouteNodeKind::Stele, 300.f));
    C.UpsertNode(Node(TEXT("S_ahead"), ESaskartaRouteNodeKind::Stele, 700.f));
    FSaskartaRouteNode Mast = Node(TEXT("MAST"), ESaskartaRouteNodeKind::Mast, 1000.f);
    Mast.bAlwaysShown = true;
    Mast.bHasWorld = true;
    Mast.WorldCm = FVector2D(0.0, -100000.0);
    C.UpsertNode(Mast);

    TestTrue(TEXT("behind: shown"), C.IsNodeShown(*C.FindNode(FName(TEXT("S_behind")))));
    TestFalse(TEXT("ahead of the high-water mark: hidden"), C.IsNodeShown(*C.FindNode(FName(TEXT("S_ahead")))));
    TestTrue(TEXT("the mast: always"), C.IsNodeShown(*C.FindNode(FName(TEXT("MAST")))));

    // Draw without the mast: nothing reaches past the fade's end (600 m), and the fade dims.
    C.Nodes.RemoveAll([](const FSaskartaRouteNode& N) { return N.Kind == ESaskartaRouteNodeKind::Mast; });
    const FSaskartaRouteFrame F = C.BuildFrame();
    const float FadeEndY = C.Fit.ToPlot(C.RoadAt(600.f)).Y;
    TestTrue(TEXT("nothing beyond the fade"), TopMostY(F, C.Tuning) >= FadeEndY - 0.5f);
    float LastAlpha = 2.f;
    bool bDims = true;
    int32 FadeSegments = 0;
    const float HwY = C.Fit.ToPlot(C.RoadAt(400.f)).Y;
    for (const FSaskartaRoutePolyline& L : F.Lines)
    {
        if (L.Points.Num() == 2 && L.Points[0].X == L.Points[1].X && L.Points[0].Y <= HwY + 0.01f && L.Points[1].Y < L.Points[0].Y)
        {
            bDims &= L.Alpha < LastAlpha;
            LastAlpha = L.Alpha;
            ++FadeSegments;
        }
    }
    TestTrue(TEXT("the road fades ahead"), FadeSegments >= 3);
    TestTrue(TEXT("fading alpha falls"), bDims);
    TestTrue(TEXT("fade starts dimmer than the driven road"), LastAlpha < C.Tuning.FadeStartAlpha);
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaRouteMapSelectionTest, "Saskarta.RouteMap.Selection", SASKARTA_ROUTEMAP_TEST_FLAGS)
bool FSaskartaRouteMapSelectionTest::RunTest(const FString&)
{
    using namespace SaskartaRouteMapTest;
    FSaskartaRouteMapCore C = StraightNorth();
    C.HighWaterRoadM = 500.f;
    C.CarrierRoadM = 500.f;
    C.bHasCarrier = true;
    C.UpsertNode(Node(TEXT("Q2"), ESaskartaRouteNodeKind::Query, 300.f));
    C.UpsertNode(Node(TEXT("S1"), ESaskartaRouteNodeKind::Stele, 100.f));
    C.UpsertNode(Node(TEXT("W3"), ESaskartaRouteNodeKind::Wreck, 450.f));
    C.UpsertNode(Node(TEXT("S_ahead"), ESaskartaRouteNodeKind::Stele, 900.f));

    C.EnsureSelection();
    TestEqual(TEXT("opens on the latest node behind the carrier"), C.SelectedId, FName(TEXT("W3")));
    C.Step(1);
    TestEqual(TEXT("clamped at the newest (nothing ahead is selectable)"), C.SelectedId, FName(TEXT("W3")));
    C.Step(-1);
    TestEqual(TEXT("road order"), C.SelectedId, FName(TEXT("Q2")));
    C.Step(-5);
    TestEqual(TEXT("clamped at the first"), C.SelectedId, FName(TEXT("S1")));

    FSaskartaRouteNode Updated = Node(TEXT("S1"), ESaskartaRouteNodeKind::Stele, 100.f);
    Updated.Lines = {TEXT("RZAG-ZRIRIT"), TEXT("~ EN: THE WAY")};
    C.UpsertNode(Updated);
    TestEqual(TEXT("upsert replaces by id"), C.Nodes.Num(), 4);
    const FSaskartaRouteFrame F = C.BuildFrame();
    bool bTranslit = false;
    bool bEnglish = false;
    for (const FSaskartaRouteText& T : F.Texts)
    {
        bTranslit |= T.Text == TEXT("RZAG-ZRIRIT");
        bEnglish |= T.Text == TEXT("~ EN: THE WAY");
    }
    TestTrue(TEXT("INSPECT shows the transliteration"), bTranslit);
    TestTrue(TEXT("INSPECT shows the ~ EN line"), bEnglish);
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaRouteMapStringsTest, "Saskarta.RouteMap.Strings", SASKARTA_ROUTEMAP_TEST_FLAGS)
bool FSaskartaRouteMapStringsTest::RunTest(const FString&)
{
    TestEqual(TEXT("resolved"), FSaskartaRouteMapCore::MarkForQuery(TEXT("STONE √ INSCRIBED")), ESaskartaRouteMark::Resolved);
    TestEqual(TEXT("no open ? any more (ROUTE_BOARD_V3.md)"), FSaskartaRouteMapCore::MarkForQuery(TEXT("POST 2 . NO WALL")), ESaskartaRouteMark::Resolved);
    TestEqual(TEXT("no result"), FSaskartaRouteMapCore::MarkForQuery(TEXT("")), ESaskartaRouteMark::None);
    TestEqual(TEXT("grouped"), FSaskartaRouteMapCore::GroupedMetres(1312.4f), FString(TEXT("1,312")));
    TestEqual(TEXT("small"), FSaskartaRouteMapCore::GroupedMetres(85.f), FString(TEXT("85")));
    TestEqual(TEXT("header"), FSaskartaRouteMapCore::Header(1312.f), FString(TEXT("MAP . ^ YOU 1,312 M")));
    TestTrue(TEXT("pad footer names D-pad down"), FSaskartaRouteMapCore::Footer(true).Contains(TEXT("D-PAD DOWN")));
    TestTrue(TEXT("keyboard footer names M"), FSaskartaRouteMapCore::Footer(false).Contains(TEXT("M  CLOSE")));
    TestTrue(TEXT("map uses D-pad down"), USaskartaRouteMap::MapPadKey() == EKeys::Gamepad_DPad_Down);
    TestTrue(TEXT("lamps use R3"), USaskartaPowerSubsystem::LampPadKey() == EKeys::Gamepad_RightThumbstick);
    TestTrue(TEXT("map and lamps have separate pad keys"), USaskartaRouteMap::MapPadKey() != USaskartaPowerSubsystem::LampPadKey());
    return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS
