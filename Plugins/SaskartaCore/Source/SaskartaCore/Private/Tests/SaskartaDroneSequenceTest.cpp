#include "Misc/AutomationTest.h"

#if WITH_DEV_AUTOMATION_TESTS

#include "SaskartaDroneSequence.h"
#include <limits>

#define DRONE_TEST_FLAGS (EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaDroneDownwashTest, "Saskarta.Drone.DownwashIsGroundedAndBounded",
    DRONE_TEST_FLAGS)
bool FSaskartaDroneDownwashTest::RunTest(const FString&)
{
    using namespace SaskartaDroneLogic;
    TestTrue(TEXT("low carrier relay emits"), CanEmitDownwash(120.f, false));
    TestFalse(TEXT("human escort does not emit"), CanEmitDownwash(120.f, true));
    TestFalse(TEXT("above 4.5m does not emit"), CanEmitDownwash(450.f, false));
    TestFalse(TEXT("below the ground does not emit"), CanEmitDownwash(-1.f, false));
    TestFalse(TEXT("nonfinite height cannot emit"), CanEmitDownwash(std::numeric_limits<float>::infinity(), false));
    const FDownwashSample Early = SampleDownwash(.08f, 120.f);
    const FDownwashSample Later = SampleDownwash(.5f, 120.f);
    TestTrue(TEXT("puff grows outward and fades within existing 0.7s cadence"),
        Later.WidthCm > Early.WidthCm && Later.HeightCm > Early.HeightCm && Later.Opacity < Early.Opacity);
    TestTrue(TEXT("higher rotors disturb less dust"), SampleDownwash(.08f, 400.f).Opacity < Early.Opacity);
    TestTrue(TEXT("starts transparent"), FMath::IsNearlyZero(SampleDownwash(0.f, 120.f).Opacity));
    TestTrue(TEXT("ends before next puff"), FMath::IsNearlyZero(SampleDownwash(.65f, 120.f).Opacity));
    TestTrue(TEXT("bad clock cannot show a puff"), FMath::IsNearlyZero(SampleDownwash(-1.f, 120.f).Opacity)
        && FMath::IsNearlyZero(SampleDownwash(std::numeric_limits<float>::infinity(), 120.f).Opacity));
    for (int32 I = 0; I <= 100; ++I)
    {
        const FDownwashSample S = SampleDownwash(I * .0065f, 120.f);
        TestTrue(TEXT("two small cards have finite size/opacity"), S.WidthCm <= 240.f && S.HeightCm <= 85.f
            && S.Opacity >= 0.f && S.Opacity <= .42f && FMath::IsFinite(S.Opacity));
    }
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaDroneFallTest, "Saskarta.Drone.FallIsBoundedAndRestores",
    DRONE_TEST_FLAGS)
bool FSaskartaDroneFallTest::RunTest(const FString&)
{
    using namespace SaskartaDroneLogic;
    const auto Start = FallPose(0.f);
    const auto Lurch = FallPose(0.75f);
    const auto Impact = FallPose(1.45f);
    const auto Bounce = FallPose(1.58f);
    const auto Settled = FallPose(2.2f);
    TestTrue(TEXT("start mesh at authored base"), Start.LocalOffset.IsNearlyZero());
    TestTrue(TEXT("left knee gives: the body lurches left"), Lurch.LocalOffset.Y < -5.f && Lurch.LocalRotation.Roll < -5.f);
    TestTrue(TEXT("tips over to the left and forward"), Impact.LocalOffset.Y < -50.f && Impact.LocalOffset.X > 20.f
        && Impact.LocalRotation.Roll < -60.f && Impact.LocalRotation.Pitch < 0.f);
    TestTrue(TEXT("one bounce off the ground"), Bounce.LocalOffset.Z > Impact.LocalOffset.Z + 5.f
        && Settled.LocalOffset.Z < Bounce.LocalOffset.Z);
    TestTrue(TEXT("fall stays within visual bounds"), Impact.LocalOffset.Size() < 150.f && FMath::Abs(Impact.LocalRotation.Roll) <= 85.f);
    TestTrue(TEXT("gravity: most of the tip happens late"), FallPose(1.1f).LocalRotation.Roll > -45.f);
    TestTrue(TEXT("mesh recovers under black before aux vision"), FallPose(4.8f).LocalOffset.IsNearlyZero()
        && FallPose(4.8f).LocalRotation.IsNearlyZero());
    TestTrue(TEXT("skip after fall clamps to base"), FallPose(30.f).LocalOffset.IsNearlyZero());
    // The lens rides its mount on the body (the author: it must tilt and fall with the carrier).
    const FTransform MountBase(FRotator(0.f, -90.f, 0.f), FVector(0.f, 0.f, -60.f), FVector::OneVector);
    const FVector MountInMesh(0.f, 13.f, 160.f);
    const FVector Pivot = MountBase.GetLocation();
    const float MountReach = FVector::Dist(MountBase.TransformPosition(MountInMesh), Pivot);
    for (float T : {0.f, 0.75f, 1.45f, 1.58f, 2.2f, 3.5f})
    {
        const FFallPose Pose = FallPose(T);
        const FTransform Body = ComposeFallRelative(MountBase, Pose);
        TestTrue(TEXT("the mount stays at a fixed reach from the tipping body's pivot"), FMath::IsNearlyEqual(
            float(FVector::Dist(Body.TransformPosition(MountInMesh), Pivot + Pose.LocalOffset)), MountReach, 0.05f));
        const FTransform Lens(FRotator(-8.f, 0.f, 0.f), MountInMesh);
        TestTrue(TEXT("the lens never leaves its mount"), MountedFallView(Lens, T).GetLocation().Equals(MountInMesh, 0.001f));
    }
    TestTrue(TEXT("the lens drops with the body at impact"), ComposeFallRelative(MountBase, Impact).TransformPosition(MountInMesh).Z
        < MountBase.TransformPosition(MountInMesh).Z - 60.f);
    TestTrue(TEXT("no mount shake before impact"), FallMountShake(1.f).IsNearlyZero(0.001f));
    TestTrue(TEXT("the impact rings through the mount"), !FallMountShake(1.47f).IsNearlyZero(0.5f));
    TestTrue(TEXT("the ring has died out under black"), FallMountShake(4.8f).IsNearlyZero(0.001f));
    TestTrue(TEXT("impact snaps the lens"), FallFaultFovDelta(1.47f) < -5.f && FallFaultFovDelta(1.52f) > 0.f);
    TestTrue(TEXT("torn frames sit between settle and black"), !FallSignalTorn(2.25f) && FallSignalTorn(2.31f)
        && FallSignalTorn(2.39f) && !FallSignalTorn(2.41f));
    TestTrue(TEXT("no lens fault once aux vision starts"), FMath::IsNearlyZero(FallFaultFovDelta(5.f)));
    TestTrue(TEXT("dust bursts at impact and partly stays"), FMath::IsNearlyZero(FallLensDust(1.4f))
        && FallLensDust(1.56f) > 0.9f && FallLensDust(2.3f) > 0.5f && FallLensDust(2.3f) < 0.8f);
    TestTrue(TEXT("dust is gone before aux vision"), FMath::IsNearlyZero(FallLensDust(5.f)));
    const float PointZ[] = {10.f, 30.f, 50.f};
    const float GroundZ[] = {12.f, 0.f, -100.f};
    TestTrue(TEXT("contact lift keeps the lowest point clear"),
        FMath::IsNearlyEqual(ContactLift(PointZ, GroundZ, 4.f), 6.f));
    const float Clear[] = {-500.f, -500.f, -500.f};
    TestTrue(TEXT("no lift above the ground"), FMath::IsNearlyZero(ContactLift(PointZ, Clear, 4.f)));
    const FTransform MeshBase(FRotator(0.f, -90.f, 0.f), FVector(0.f, 0.f, -90.f), FVector::OneVector);
    const FTransform Fallen = ComposeFallRelative(MeshBase, Impact);
    TestTrue(TEXT("actor-local fall offset preserved through mesh yaw -90"),
        Fallen.GetLocation().Equals(MeshBase.GetLocation() + Impact.LocalOffset, 0.01f));
    TestTrue(TEXT("actor-local rotation premultiplies the mesh orientation"),
        Fallen.GetRotation().Equals(Impact.LocalRotation.Quaternion() * MeshBase.GetRotation(), 0.0001f));
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaDroneEchoTest, "Saskarta.Drone.EchoTimingAndEdgeCadence",
    DRONE_TEST_FLAGS)
bool FSaskartaDroneEchoTest::RunTest(const FString&)
{
    TestTrue(TEXT("3m edge round trip is about 17.5ms"), FMath::IsNearlyEqual(
        SaskartaDroneLogic::EchoRoundTripSeconds(300.f), 600.f / 34300.f, 0.0001f));
    const float Period = SaskartaDroneLogic::PingPeriodSeconds();
    TestTrue(TEXT("steady cadence sits in the 2.5-4 s band"), Period >= 2.5f && Period <= 4.f);
    TestTrue(TEXT("near edge answers sooner"), SaskartaDroneLogic::EchoRoundTripSeconds(80.f)
        < SaskartaDroneLogic::EchoRoundTripSeconds(520.f));
    TestTrue(TEXT("near edge answers louder"), SaskartaDroneLogic::EchoVolume(80.f)
        > SaskartaDroneLogic::EchoVolume(520.f) + 0.2f);
    TestTrue(TEXT("echo volume stays audible and bounded"), SaskartaDroneLogic::EchoVolume(0.f) <= 1.f
        && SaskartaDroneLogic::EchoVolume(100000.f) >= 0.2f);

    SaskartaDroneLogic::FPingHistory History;
    for (const FLinearColor& Slot : History.Slots)
        TestTrue(TEXT("empty slots are far in the past"), Slot.A <= -1000.f);
    History.Push(FVector(1.f, 2.f, 3.f), 10.f);
    History.Push(FVector(4.f, 5.f, 6.f), 13.f);
    History.Push(FVector(7.f, 8.f, 9.f), 16.f);
    History.Push(FVector(10.f, 11.f, 12.f), 19.f);
    TestTrue(TEXT("newest ping first"), History.Slots[0].Equals(FLinearColor(10.f, 11.f, 12.f, 19.f)));
    TestTrue(TEXT("history keeps the last three"), FMath::IsNearlyEqual(History.Slots[1].A, 16.f)
        && FMath::IsNearlyEqual(History.Slots[2].A, 13.f));
    History.Clear();
    TestTrue(TEXT("clear empties the history"), History.Slots[0].A <= -1000.f);
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaDroneFlightTest, "Saskarta.Drone.FlightAndCameraEnvelope",
    DRONE_TEST_FLAGS)
bool FSaskartaDroneFlightTest::RunTest(const FString&)
{
    using namespace SaskartaDroneLogic;
    FDroneFlight F;
    F.Reset(FVector::ZeroVector);
    float MaxX = 0.f;
    float MinPitch = 0.f;
    for (int32 I = 0; I < 120; ++I)
    {
        F.Step(FVector(1000.f, 0.f, 0.f), 0.f, 1.f / 30.f);
        MaxX = FMath::Max(MaxX, float(F.Position.X));
        MinPitch = FMath::Min(MinPitch, F.PitchDeg);
    }
    TestTrue(TEXT("overshoots, then settles"), MaxX > 1030.f && FMath::Abs(F.Position.X - 1000.f) < 5.f);
    TestTrue(TEXT("pitches nose-down into forward motion"), MinPitch < -10.f);
    TestTrue(TEXT("strain rises on a hard start and eases once settled"), F.Strain < 0.1f);
    {
        FDroneFlight S;
        S.Reset(FVector::ZeroVector);
        for (int32 I = 0; I < 4; ++I) S.Step(FVector(1500.f, 0.f, 0.f), 0.f, 1.f / 60.f);
        TestTrue(TEXT("a hard start strains the motors"), S.Strain > 0.3f);
        FDroneFlight Soft, Tight;
        Soft.Reset(FVector::ZeroVector);
        Tight.Reset(FVector::ZeroVector);
        Tight.Stiffness = 1.8f;
        for (int32 I = 0; I < 12; ++I) { Soft.Step(FVector(600.f, 0.f, 0.f), 0.f, 1.f / 60.f); Tight.Step(FVector(600.f, 0.f, 0.f), 0.f, 1.f / 60.f); }
        TestTrue(TEXT("the feed drone flies tighter"), Tight.Position.X > Soft.Position.X * 1.5f);
    }
    F.Reset(FVector::ZeroVector);
    for (int32 I = 0; I < 30; ++I) F.Step(FVector(0.f, 800.f, 0.f), 0.f, 1.f / 30.f);
    TestTrue(TEXT("banks into a lateral move"), FMath::Abs(F.RollDeg) > 3.f);
    F.Reset(FVector::ZeroVector);
    for (int32 I = 0; I < 15; ++I) F.Step(FVector(0.f, 0.f, 400.f), 0.f, 1.f / 30.f);
    TestTrue(TEXT("rotors spin up to climb"), F.RotorRate > 1.1f);
    F.Reset(FVector::ZeroVector);
    for (int32 I = 0; I < 15; ++I) F.Step(FVector(0.f, 0.f, -400.f), 0.f, 1.f / 30.f);
    TestTrue(TEXT("rotors ease to descend"), F.RotorRate < 0.95f);
    float LowZ = TNumericLimits<float>::Max(), HighZ = TNumericLimits<float>::Lowest();
    for (int32 I = 0; I < 900; ++I)
    {
        const float Z = HoverDrift(0, I / 30.f).Z;
        LowZ = FMath::Min(LowZ, Z);
        HighZ = FMath::Max(HighZ, Z);
    }
    TestTrue(TEXT("hover has a visible slow altitude range"), HighZ - LowZ > 45.f);
    TestTrue(TEXT("hover remains bounded"), HoverDrift(0, 3.7f).Size() < 40.f && !HoverDrift(1, 3.7f).IsNearlyZero());
    TestTrue(TEXT("a gust tilts then settles"), FMath::Abs(GustTilt(0, 0.9f).Roll) > 2.f
        && GustTilt(0, 3.5f).IsNearlyZero());

    // B1 arrival: heard far away, clusters close in, lights, rise into view, sides, boot.
    TestTrue(TEXT("drones start far behind: heard before seen"), SwarmOffset(0, 0.f).X < -5000.f && SwarmOffset(1, 0.f).X < -5000.f);
    TestTrue(TEXT("drones rise into view ahead of the carrier"), SwarmOffset(0, 9.f).X > 300.f && SwarmOffset(1, 9.f).X > 300.f);
    TestTrue(TEXT("lead hands back on the rear station"), FVector::Dist(SwarmOffset(0, 14.f), FollowOffset(0.f, -11.27f)) < 20.f);
    TestTrue(TEXT("wing hands back on the front station"), FVector::Dist(SwarmOffset(1, 14.f), FollowOffset(180.f, -11.27f)) < 20.f);
    TestTrue(TEXT("feed boots looking down at the carrier"), SwarmOffset(0, 12.05f).Z > 400.f);
    TestTrue(TEXT("lights are dark, then show through the dust"), FMath::IsNearlyZero(ArrivalLight(0, 4.f))
        && FMath::IsNearlyEqual(ArrivalLight(0, 8.f), 1.f) && FMath::IsNearlyEqual(ArrivalLight(1, 8.f), 1.f));
    TestTrue(TEXT("lead sweeps its light over the carrier"), ArrivalLightTarget(0, 9.f).X > 1000.f
        && ArrivalLightTarget(0, 10.9f).X < 0.f);
    for (float Pitch : {-80.f, -45.f, -12.f, 5.f, 60.f})
    {
        const FVector Eye = FollowOffset(90.f, Pitch);
        TestTrue(TEXT("eye never exceeds 12m from carrier"), Eye.Size() <= 1200.01f);
        const float ActualPitch = (FVector(0.f, 0.f, 120.f) - Eye).Rotation().Pitch;
        TestTrue(TEXT("aimed camera pitch remains in bound"), ActualPitch >= -45.01f && ActualPitch <= 5.01f);
    }
    TestTrue(TEXT("default eye aligns with B1 handback height"),
        FMath::IsNearlyEqual(FollowOffset(0.f, -11.27f).Z, 250.f, 1.f));
    TestEqual(TEXT("look keeps orbit while recently used"), RecenterYaw(30.f, 2.f, 0.1f), 30.f);
    TestTrue(TEXT("idle orbit eases home"), RecenterYaw(30.f, 5.f, 0.1f) < 30.f);
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaDroneDualViewTest, "Saskarta.Drone.DualCoverageAndLag",
    DRONE_TEST_FLAGS)
bool FSaskartaDroneDualViewTest::RunTest(const FString&)
{
    using namespace SaskartaDroneLogic;
    TestEqual(TEXT("feed starts on the rear drone"), FeedForYaw(0, 0.f), 0);
    TestEqual(TEXT("no switch at the seam itself"), FeedForYaw(0, 95.f), 0);
    TestEqual(TEXT("rear keeps the feed up to 118 degrees"), FeedForYaw(0, 118.f), 0);
    TestEqual(TEXT("front is eligible beyond 118 degrees"), FeedForYaw(0, 119.f), 1);
    TestEqual(TEXT("front keeps the feed at 60 degrees"), FeedForYaw(1, 60.f), 1);
    TestEqual(TEXT("rear is eligible below 60 degrees"), FeedForYaw(1, 59.f), 0);
    float FeedWait = 0.f;
    TestEqual(TEXT("first glance past threshold does not switch"), AdvanceFeedSwitch(0, 120.f, 0.2f, FeedWait), 0);
    TestEqual(TEXT("retreat cancels the pending switch"), AdvanceFeedSwitch(0, 90.f, 0.1f, FeedWait), 0);
    TestTrue(TEXT("retreat clears dwell"), FMath::IsNearlyZero(FeedWait));
    TestEqual(TEXT("second glance still waits"), AdvanceFeedSwitch(0, -120.f, 0.3f, FeedWait), 0);
    TestEqual(TEXT("continuous 0.4-second look changes feed"), AdvanceFeedSwitch(0, -120.f, 0.1f, FeedWait), 1);
    TestEqual(TEXT("front keeps feed until return threshold"), AdvanceFeedSwitch(1, 70.f, 1.f, FeedWait), 1);
    TestEqual(TEXT("return also waits for dwell"), AdvanceFeedSwitch(1, 50.f, 0.39f, FeedWait), 1);
    TestEqual(TEXT("return switches after dwell"), AdvanceFeedSwitch(1, 50.f, 0.02f, FeedWait), 0);
    for (float Yaw : {-179.f, -120.f, -60.f, 0.f, 60.f, 120.f, 179.f})
    {
        const int32 Active = FeedForYaw(FMath::Abs(Yaw) > 90.f ? 1 : 0, Yaw);
        TestTrue(TEXT("active drone follows the look"),
            FMath::Abs(FMath::FindDeltaAngleDegrees(StationYawForDrone(Active, Active, Yaw), Yaw)) < 0.01f);
        TestTrue(TEXT("waiting rear drone holds inside its side"), FMath::Abs(StationYawForDrone(0, 1, Yaw)) <= 75.01f);
        TestTrue(TEXT("waiting front drone holds inside its side"), FMath::Abs(StationYawForDrone(1, 0, Yaw)) >= 104.99f);
    }
    TestTrue(TEXT("waiting drone mirrors the look, so it is ready on that side"),
        FMath::IsNearlyEqual(StationYawForDrone(1, 0, 60.f), 120.f, 0.01f));
    TestTrue(TEXT("relay cut flickers, then clears"), RelayFlicker(0.f, 0.22f) < 0.2f
        && RelayFlicker(0.05f, 0.22f) > 1.2f && FMath::IsNearlyEqual(RelayFlicker(0.3f, 0.22f), 1.f));

    float Actual = 0.f;
    for (int32 I = 0; I < 3; ++I) Actual = AdvanceLaggedYaw(Actual, 150.f, 1.f / 30.f);
    TestEqual(TEXT("feed does not switch before the lagged look crosses"), FeedForYaw(0, Actual), 0);
    TestTrue(TEXT("mechanical response follows but lags mouse target"), Actual > 0.f && Actual < 90.f);
    for (int32 I = 0; I < 90; ++I) Actual = AdvanceLaggedYaw(Actual, 150.f, 1.f / 30.f);
    TestEqual(TEXT("crossing beyond the seam activates the front drone"), FeedForYaw(0, Actual), 1);
    TestTrue(TEXT("camera converges near requested bearing"),
        FMath::Abs(FMath::FindDeltaAngleDegrees(Actual, 150.f)) < 1.f);
    TestTrue(TEXT("look is the control rotation's change, across the wrap"),
        LookOrbitDelta(FRotator(350.f, 359.f, 0.f), FRotator(5.f, 2.f, 0.f)).Equals(FVector2D(3.f, 15.f), 0.001f));
    TestTrue(TEXT("mouse left turns the orbit left"), LookOrbitDelta(FRotator(0.f, 10.f, 0.f), FRotator(0.f, 4.f, 0.f)).X < 0.f);
    TestTrue(TEXT("a scripted snap is not a look"), LookOrbitDelta(FRotator(0.f, 0.f, 0.f), FRotator(0.f, 120.f, 0.f)).IsZero());
    TestTrue(TEXT("pitch response is delayed and bounded"),
        AdvanceLaggedPitch(-11.27f, -45.f, 1.f / 30.f) > -45.f);
    {
        float Quick = 0.f;
        for (int32 I = 0; I < 9; ++I) Quick = AdvanceLaggedYaw(Quick, 60.f, 1.f / 60.f);
        TestTrue(TEXT("look is smoothed, not lagged: most of a 60 deg turn within 0.15 s"), Quick > 45.f && Quick < 60.f);
    }
    TestTrue(TEXT("mouse look is amplified onto the orbit"), OrbitFromLook(FVector2D(10.f, 10.f)).X > 25.f
        && OrbitFromLook(FVector2D(10.f, 10.f)).Y > 14.f && OrbitFromLook(FVector2D(-4.f, 0.f)).X < 0.f);
    {
        const FRotorMix Idle = RotorMix(1.f, 0.f, 0.f, false);
        const FRotorMix Hard = RotorMix(1.4f, 1500.f, 1.f, false);
        const FRotorMix Own = RotorMix(1.f, 0.f, 0.f, true);
        TestTrue(TEXT("rotors are clearly audible at hover"), Idle.Volume > 0.5f);
        TestTrue(TEXT("a hard move is louder and higher"), Hard.Volume > Idle.Volume * 1.3f && Hard.Pitch > Idle.Pitch * 1.15f);
        TestTrue(TEXT("the drone the feed looks through is softer, not silent"), Own.Volume < Idle.Volume && Own.Volume > 0.3f);
        TestTrue(TEXT("no whoosh at hover, a rush on a fast swing"), WhooshLevel(100.f, 0.f) < 0.01f && WhooshLevel(1800.f, 0.6f) > 0.6f);
    }
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaDroneHumanEscortTest, "Saskarta.Drone.HumanEscortAnchors",
    DRONE_TEST_FLAGS)
bool FSaskartaDroneHumanEscortTest::RunTest(const FString&)
{
    using namespace SaskartaDroneLogic;
    const FTransform Wreck(FRotator(0.f, 45.f, 0.f), FVector(1000.f, 2000.f, 300.f));
    const FTransform HumanA(FRotator::ZeroRotator, FVector(1100.f, 2200.f, 300.f));
    const FTransform HumanB(FRotator::ZeroRotator, FVector(2100.f, 2200.f, 300.f));
    const FVector FollowingA = HumanEscortTarget(0, HumanA, Wreck, 10.f);
    const FVector FollowingB = HumanEscortTarget(0, HumanB, Wreck, 10.f);
    const FVector ParkedA = HumanEscortTarget(1, HumanA, Wreck, 10.f);
    const FVector ParkedB = HumanEscortTarget(1, HumanB, Wreck, 10.f);
    TestTrue(TEXT("one drone follows the old man's movement"),
        FollowingB.Equals(FollowingA + FVector(1000.f, 0.f, 0.f), 0.01f));
    TestTrue(TEXT("the second drone remains at the disabled carrier"), ParkedA.Equals(ParkedB, 0.01f));
    TestTrue(TEXT("escort stays nearby without blocking Samyor's eyes"),
        FVector::Dist(FollowingA, HumanA.GetLocation()) < 450.f && FollowingA.Z > HumanA.GetLocation().Z + 200.f);
    TestTrue(TEXT("parked unit stays near the wreck"), FVector::Dist(ParkedA, Wreck.GetLocation()) < 550.f);
    return true;
}

#endif
