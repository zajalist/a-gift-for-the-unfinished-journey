// Automation tests for the collapse stage's pose math (task COLLAPSE-STAGE). Pure, no world.
//
//   Automation RunTests Saskarta.Collapse
//
// Written offline while the editor held the module; the same math (SaskartaCollapseStageMath.h) was
// checked by a standalone cl harness in the lane.

#include "Misc/AutomationTest.h"

#if WITH_DEV_AUTOMATION_TESTS

#include "SaskartaCollapseStageLogic.h"
#include "SaskartaCollapseStageMath.h"

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaCollapseYawTest, "Saskarta.Collapse.Stage.YawAlongTravel",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)
bool FSaskartaCollapseYawTest::RunTest(const FString&)
{
    using namespace SaskartaCollapseStageMath;
    // Travel is toward falling spline distance: a tangent along +X means the carrier faces -X.
    TestEqual(TEXT("tangent +X -> yaw 180"), static_cast<float>(TravelYawDeg(100, 0, 0, 0, 0, 0, 0)), 180.f, 0.01f);
    TestEqual(TEXT("tangent +Y -> yaw -90"), static_cast<float>(TravelYawDeg(0, 100, 0, 0, 0, 0, 0)), -90.f, 0.01f);
    TestEqual(TEXT("offset wraps"), static_cast<float>(TravelYawDeg(100, 0, 0, 0, 0, 0, 30)), -150.f, 0.01f);
    // A zero tangent (at a spline point) uses the chord: Ahead is farther along, so travel is Ahead -> Behind.
    TestEqual(TEXT("zero tangent -> chord"), static_cast<float>(TravelYawDeg(0, 0, 0, 0, 0, 300, 0)), -90.f, 0.01f);
    TestEqual(TEXT("wrap 190"), static_cast<float>(WrapDeg(190.0)), -170.f, 0.001f);
    TestEqual(TEXT("wrap -180"), static_cast<float>(WrapDeg(-180.0)), 180.f, 0.001f);
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaCollapsePoseTest, "Saskarta.Collapse.Stage.PoseAndFootprint",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)
bool FSaskartaCollapsePoseTest::RunTest(const FString&)
{
    FSaskartaCollapseStageDef Def;
    Def.LateralCm = 100.f;
    Def.YawOffsetDeg = 10.f;
    // Tangent -X: travel +X (yaw 0), so the road's right is +Y.
    const FSaskartaCollapsePose P = FSaskartaCollapseStageLogic::Pose(Def, FVector(1000, 2000, 300), FVector(-500, 0, 0), FVector::ZeroVector, FVector::ZeroVector);
    TestEqual(TEXT("road yaw"), P.RoadYawDeg, 0.f, 0.01f);
    TestEqual(TEXT("carrier yaw = road + offset"), P.YawDeg, 10.f, 0.01f);
    TestTrue(TEXT("lateral goes right across the road"), P.Centre.Equals(FVector(1000, 2100, 300), 0.01));

    FSaskartaCollapseStageDef Plain;
    TArray<FVector2D> Local;
    FSaskartaCollapseStageLogic::Footprint(Plain, Local);
    TestEqual(TEXT("six columns"), Local.Num(), 6);
    const FSaskartaCollapsePose Q = FSaskartaCollapseStageLogic::Pose(Plain, FVector(0, 0, 0), FVector(0, -500, 0), FVector::ZeroVector, FVector::ZeroVector);
    TestEqual(TEXT("tangent -Y -> yaw 90"), Q.YawDeg, 90.f, 0.01f);
    // Facing +Y: the front-left wheel (x 110, y -70) is at world (+70, +110); the capsule is behind (-Y).
    TestTrue(TEXT("front-left wheel"), FSaskartaCollapseStageLogic::FootprintWorld(Q, Local[0]).Equals(FVector(70, 110, 0), 0.01));
    TestTrue(TEXT("capsule behind"), FSaskartaCollapseStageLogic::FootprintWorld(Q, Local[4]).Y < -300.0);
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaCollapseGroundTest, "Saskarta.Collapse.Stage.Grounding",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)
bool FSaskartaCollapseGroundTest::RunTest(const FString&)
{
    using namespace SaskartaCollapseStageMath;
    const double Z[4] = { 100.0, 104.0, 98.0, 250.0 };
    const bool Hit[4] = { true, true, true, false };
    double S = 0.0, Spread = 0.0;
    TestTrue(TEXT("hits"), SupportZ(Z, Hit, 4, S, Spread));
    TestEqual(TEXT("highest hit, the miss ignored"), static_cast<float>(S), 104.f, 0.001f);
    TestEqual(TEXT("spread"), static_cast<float>(Spread), 6.f, 0.001f);
    const bool None[4] = { false, false, false, false };
    TestFalse(TEXT("no hits"), SupportZ(Z, None, 4, S, Spread));
    TestEqual(TEXT("actor z"), static_cast<float>(ActorZ(104.0, 60.0, 2.0)), 166.f, 0.001f);
    TestEqual(TEXT("negative half height ignored"), static_cast<float>(ActorZ(104.0, -5.0, 0.0)), 104.f, 0.001f);
    TestEqual(TEXT("climbing"), static_cast<float>(SlopeDeg(10.0, 0.0, 10.0)), 45.f, 0.01f);
    TestEqual(TEXT("flat"), static_cast<float>(SlopeDeg(5.0, 5.0, 200.0)), 0.f, 0.001f);
    TestFalse(TEXT("2.9 m in view"), NeedsCover(290.0, 3.0));
    TestTrue(TEXT("3.1 m covered"), NeedsCover(310.0, 3.0));
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaCollapseParseTest, "Saskarta.Collapse.Stage.ParseJson",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)
bool FSaskartaCollapseParseTest::RunTest(const FString&)
{
    FSaskartaCollapseStageDef D;
    TestFalse(TEXT("absent -> false"), FSaskartaCollapseStageLogic::ParseJson(TEXT("{\"beats\": []}"), D));
    TestEqual(TEXT("defaults kept"), D.RoadM, 4790.f);
    TestFalse(TEXT("bad json"), FSaskartaCollapseStageLogic::ParseJson(TEXT("{"), D));
    TestTrue(TEXT("read"), FSaskartaCollapseStageLogic::ParseJson(
        TEXT("{\"collapse_stage\": {\"road_m\": 4801.5, \"lateral_cm\": -40, \"yaw_offset_deg\": 3, \"beat\": \"B99\", \"enabled\": false}}"), D));
    TestEqual(TEXT("road"), D.RoadM, 4801.5f);
    TestEqual(TEXT("lateral"), D.LateralCm, -40.f);
    TestEqual(TEXT("yaw"), D.YawOffsetDeg, 3.f);
    TestEqual(TEXT("beat"), D.Beat, FName(TEXT("B99")));
    TestEqual(TEXT("cinematic default kept"), D.Cinematic, FName(TEXT("CIN_18_COLLAPSE")));
    TestFalse(TEXT("disabled"), D.bEnabled);
    TestFalse(TEXT("disabled never triggers"), FSaskartaCollapseStageLogic::Triggers(D, TEXT("B99")));
    FSaskartaCollapseStageDef E;
    TestTrue(TEXT("beat triggers"), FSaskartaCollapseStageLogic::Triggers(E, TEXT("B18_COLLAPSE")));
    TestTrue(TEXT("cinematic triggers"), FSaskartaCollapseStageLogic::Triggers(E, TEXT("CIN_18_COLLAPSE")));
    TestFalse(TEXT("other beat"), FSaskartaCollapseStageLogic::Triggers(E, TEXT("B17_FAIL")));
    return true;
}

#endif
