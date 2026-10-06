#include "SaskartaDroneSequence.h"

#include "Materials/MaterialInstance.h"
#include "Animation/AnimSequence.h"
#include "Blueprint/WidgetTree.h"
#include "Camera/CameraActor.h"
#include "Camera/CameraComponent.h"
#include "Camera/PlayerCameraManager.h"
#include "Components/AudioComponent.h"
#include "Components/CanvasPanel.h"
#include "Components/CanvasPanelSlot.h"
#include "Components/SceneComponent.h"
#include "Components/SkeletalMeshComponent.h"
#include "Components/SplineComponent.h"
#include "Components/SpotLightComponent.h"
#include "Components/StaticMeshComponent.h"
#include "Components/TextBlock.h"
#include "Engine/PostProcessVolume.h"
#include "Engine/Engine.h"
#include "Engine/Font.h"
#include "Engine/SkeletalMesh.h"
#include "Engine/StaticMesh.h"
#include "Engine/World.h"
#include "EngineUtils.h"
#include "GameFramework/Character.h"
#include "GameFramework/PlayerController.h"
#include "InputCoreTypes.h"
#include "Kismet/GameplayStatics.h"
#include "Materials/MaterialInstanceDynamic.h"
#include "Materials/Material.h"
#include "Math/RotationMatrix.h"
#include "RHI.h"
#include "SaskartaEventRunner.h"
#include "Sound/SoundBase.h"
#include "Sound/SoundAttenuation.h"
#include "UObject/UObjectGlobals.h"
#include "UObject/UnrealType.h"

namespace
{
    constexpr float StepS = 1.f / 30.f;
    constexpr int32 DefaultSwarm = 2;
    constexpr int32 HardMaxSwarm = 8;
    constexpr float FollowDistanceCm = 650.f;
    constexpr float MaxEyeDistanceCm = 1200.f;
    constexpr float MaxRoadLateralCm = 600.f;
    constexpr float SwarmArrivalS = 7.f;
    constexpr float SwarmHandoverS = 9.f;
    constexpr float SwarmDepartureS = 4.f;
    // B1 arrival (14 s, the carrier keeps driving): heard, clusters in the cloud, lights,
    // rise and sweep, sides taken, then the feed boots from drone 0 looking down.
    constexpr float ArrivalBootS = 12.05f;
    constexpr float ArrivalEndS = 14.f;
    constexpr float ArrivalDriveScale = 0.45f;
    constexpr float DroneLightCandela = 20000.f;
    constexpr float FallImpactS = 1.45f;
    constexpr TCHAR FeedFontPath[] = TEXT("/Game/SaskartaGaea/GameFlow/UI/Fonts/Font_Terminal.Font_Terminal");
    const FName AuxMode(TEXT("AuxSensors"));
    const FName DroneMode(TEXT("DroneCam"));
    const FName FallCine(TEXT("CIN_A1_OPTICS_FAIL"));
    const FName SwarmCine(TEXT("CIN_B1_DRONE"));

    template <typename T>
    T* DroneAsset(const TCHAR* Path)
    {
        return Cast<T>(StaticLoadObject(T::StaticClass(), nullptr, Path));
    }

    template <typename T>
    T* OptionalAsset(const TCHAR* Path)
    {
        return Cast<T>(StaticLoadObject(T::StaticClass(), nullptr, Path, nullptr, LOAD_NoWarn | LOAD_Quiet));
    }

    enum class EFallEase : uint8 { Smooth, In, Out };
    struct FFallKey { float T; FVector P; FRotator R; EFallEase Ease; };

    SaskartaDroneLogic::FFallPose EvalFall(const FFallKey* K, int32 N, float S)
    {
        const float T = FMath::Clamp(S, 0.f, K[N - 1].T);
        for (int32 I = 1; I < N; ++I)
        {
            if (T <= K[I].T)
            {
                float A = FMath::Clamp((T - K[I - 1].T) / FMath::Max(K[I].T - K[I - 1].T, 1e-4f), 0.f, 1.f);
                if (K[I].Ease == EFallEase::In) A = A * A * A;                    // gravity: slow start, fast finish
                else if (K[I].Ease == EFallEase::Out) A = 1.f - (1.f - A) * (1.f - A);
                else A = A * A * (3.f - 2.f * A);
                return {FMath::Lerp(K[I - 1].P, K[I].P, A), FMath::Lerp(K[I - 1].R, K[I].R, A)};
            }
        }
        return {K[N - 1].P, K[N - 1].R};
    }

    struct FPathKey { float T; FVector P; };

    // Catmull-Rom through timed keys: a flown path with no stop at each key.
    FVector EvalPath(const FPathKey* K, int32 N, float S)
    {
        if (S <= K[0].T) return K[0].P;
        for (int32 I = 1; I < N; ++I)
        {
            if (S <= K[I].T)
            {
                const float A = FMath::Clamp((S - K[I - 1].T) / FMath::Max(K[I].T - K[I - 1].T, 1e-4f), 0.f, 1.f);
                const FVector& P0 = K[FMath::Max(I - 2, 0)].P;
                const FVector& P1 = K[I - 1].P;
                const FVector& P2 = K[I].P;
                const FVector& P3 = K[FMath::Min(I + 1, N - 1)].P;
                return 0.5f * (2.f * P1 + (P2 - P0) * A + (2.f * P0 - 5.f * P1 + 4.f * P2 - P3) * A * A
                    + (3.f * P1 - P0 - 3.f * P2 + P3) * A * A * A);
            }
        }
        return K[N - 1].P;
    }

    // Two cards total, using the installed free six-way dust atlas. The old
    // NS_DroneDownwash reference never had a corresponding authored asset.
    UStaticMeshComponent* MakeDownwash(UMaterialInterface* Material, UStaticMesh* Mesh,
        AActor* Owner, UMaterialInstanceDynamic*& Mid)
    {
        Mid = nullptr;
        float Value = 0.f;
        if (!Owner || !Mesh || !Material || !Material->GetMaterial()
            || Material->GetMaterial()->MaterialDomain != MD_Surface
            || Material->GetBlendMode() != BLEND_Translucent
            || Material->GetMaterial()->IsCompilingOrHadCompileError(GMaxRHIShaderPlatform)
            || !Material->GetScalarParameterValue(FHashedMaterialParameterInfo(TEXT("Opacity")), Value)
            || !Material->GetScalarParameterValue(FHashedMaterialParameterInfo(TEXT("CloudVariant")), Value)) return nullptr;
        const FVector MeshSize = Mesh->GetBoundingBox().GetSize();
        if (MeshSize.ContainsNaN() || MeshSize.X <= 0.f || MeshSize.Y <= 0.f) return nullptr;
        Mid = UMaterialInstanceDynamic::Create(Material, Owner);
        Mid->SetScalarParameterValue(TEXT("Opacity"), 0.f);
        UStaticMeshComponent* Fx = NewObject<UStaticMeshComponent>(Owner);
        Owner->AddInstanceComponent(Fx);
        Fx->SetupAttachment(Owner->GetRootComponent());
        Fx->SetMobility(EComponentMobility::Movable);
        Fx->SetStaticMesh(Mesh);
        Fx->SetMaterial(0, Mid);
        Fx->SetVisibility(false);
        Fx->SetCollisionEnabled(ECollisionEnabled::NoCollision);
        Fx->SetGenerateOverlapEvents(false);
        Fx->SetCanEverAffectNavigation(false);
        Fx->SetCastShadow(false);
        Fx->bCastVolumetricTranslucentShadow = false;
        Fx->bReceivesDecals = false;
        Fx->bAllowCullDistanceVolume = false;
        Fx->SetVisibleInRayTracing(false);
        Fx->SetCullDistance(2500.f);
        Fx->SetUsingAbsoluteLocation(true);
        Fx->SetUsingAbsoluteRotation(true);
        Fx->SetUsingAbsoluteScale(true);
        Fx->RegisterComponent();
        return Fx;
    }

    USoundAttenuation* MakeAttenuation(UObject* Outer, float InnerCm, float FalloffCm, float NonSpatialCm)
    {
        USoundAttenuation* A = NewObject<USoundAttenuation>(Outer);
        FSoundAttenuationSettings& S = A->Attenuation;
        S.bAttenuate = true;
        S.bSpatialize = true;
        S.AttenuationShape = EAttenuationShape::Sphere;
        S.AttenuationShapeExtents = FVector(InnerCm, 0.f, 0.f);
        S.FalloffDistance = FalloffCm;
        S.DistanceAlgorithm = EAttenuationDistanceModel::NaturalSound;
        S.NonSpatializedRadiusStart = NonSpatialCm;
        S.NonSpatializedRadiusEnd = NonSpatialCm * 0.5f;
        return A;
    }
}

bool SaskartaDroneLogic::CanEmitDownwash(float HeightCm, bool bHumanEscort)
{
    return !bHumanEscort && FMath::IsFinite(HeightCm) && HeightCm >= 0.f && HeightCm < 450.f;
}

SaskartaDroneLogic::FDownwashSample SaskartaDroneLogic::SampleDownwash(float AgeS, float HeightCm)
{
    if (!FMath::IsFinite(AgeS) || AgeS < 0.f || AgeS >= .65f || !CanEmitDownwash(HeightCm, false)) return {};
    const float T = AgeS / .65f;
    const float HeightGain = FMath::Clamp((450.f - HeightCm) / 250.f, 0.f, 1.f);
    const float Fade = FMath::Clamp(AgeS / .08f, 0.f, 1.f) * FMath::Square(1.f - T);
    return {FMath::Lerp(80.f, 240.f, T), FMath::Lerp(30.f, 85.f, T), .42f * HeightGain * Fade};
}

SaskartaDroneLogic::FFallPose SaskartaDroneLogic::FallPose(float S)
{
    // The left knee gives at 0.4 s; the body tips left and forward under gravity, hits at 1.45 s,
    // bounces once and settles on its side. It recovers under black before aux vision.
    static const FFallKey K[] = {
        {0.f, FVector::ZeroVector, FRotator::ZeroRotator, EFallEase::Smooth},
        {0.25f, FVector(0.f, 0.f, -3.f), FRotator::ZeroRotator, EFallEase::Smooth},
        {0.4f, FVector::ZeroVector, FRotator(0.f, 0.f, -2.f), EFallEase::Smooth},
        {0.75f, FVector(10.f, -15.f, -12.f), FRotator(-4.f, 0.f, -12.f), EFallEase::Smooth},
        {FallImpactS, FVector(45.f, -70.f, -60.f), FRotator(-14.f, 0.f, -78.f), EFallEase::In},
        {1.58f, FVector(47.f, -73.f, -50.f), FRotator(-12.f, 0.f, -70.f), EFallEase::Out},
        {1.85f, FVector(46.f, -72.f, -58.f), FRotator(-14.f, 0.f, -75.f), EFallEase::Smooth},
        {2.6f, FVector(46.f, -72.f, -58.f), FRotator(-14.f, 0.f, -75.f), EFallEase::Smooth},
        {4.8f, FVector::ZeroVector, FRotator::ZeroRotator, EFallEase::Smooth}
    };
    return EvalFall(K, UE_ARRAY_COUNT(K), S);
}

FRotator SaskartaDroneLogic::FallMountShake(float S)
{
    // The lens rides its mount on the body (the author: it must tilt and fall with the carrier);
    // the hard stop only rings through the mount, and the torn frames twitch it.
    FRotator Shake = FRotator::ZeroRotator;
    if (S >= FallImpactS && S < 2.2f)
    {
        const float Age = S - FallImpactS;
        Shake.Roll += 3.5f * FMath::Exp(-Age / 0.12f) * FMath::Sin(2.f * PI * 17.f * Age);
        Shake.Pitch += 2.f * FMath::Exp(-Age / 0.1f) * FMath::Sin(2.f * PI * 13.f * Age + 1.f);
    }
    Shake.Roll += FallFaultFovDelta(S) * 0.9f;
    return Shake;
}

FTransform SaskartaDroneLogic::MountedFallView(const FTransform& Mount, float S)
{
    FTransform Result = Mount;
    Result.SetRotation(Mount.GetRotation() * FallMountShake(S).Quaternion());
    return Result;
}

float SaskartaDroneLogic::FallFaultFovDelta(float S)
{
    if (S >= FallImpactS && S < FallImpactS + 0.05f) return -7.f;   // the snap
    if (S >= FallImpactS + 0.05f && S < FallImpactS + 0.11f) return 3.f;
    if (S >= 2.30f && S < 2.34f) return 2.f;                         // torn frames
    if (S >= 2.34f && S < 2.37f) return -3.f;
    if (S >= 2.37f && S < 2.40f) return 1.5f;
    return 0.f;
}

float SaskartaDroneLogic::FallLensDust(float S)
{
    if (S < FallImpactS || S >= 4.8f) return 0.f;
    if (S < FallImpactS + 0.1f)
    {
        const float A = (S - FallImpactS) / 0.1f;
        return A * A * (3.f - 2.f * A);
    }
    return 0.55f + 0.45f * FMath::Exp(-(S - FallImpactS - 0.1f) / 0.35f);
}

bool SaskartaDroneLogic::FallSignalTorn(float S)
{
    return S >= 2.30f && S < 2.40f;
}

float SaskartaDroneLogic::ContactLift(TConstArrayView<float> PointZ, TConstArrayView<float> GroundZ, float ClearanceCm)
{
    float Lift = 0.f;
    for (int32 I = 0; I < FMath::Min(PointZ.Num(), GroundZ.Num()); ++I)
    {
        Lift = FMath::Max(Lift, GroundZ[I] + ClearanceCm - PointZ[I]);
    }
    return Lift;
}

FTransform SaskartaDroneLogic::ComposeFallRelative(const FTransform& Base, const FFallPose& Pose)
{
    FTransform Result = Base;
    Result.SetLocation(Base.GetLocation() + Pose.LocalOffset);
    Result.SetRotation(Pose.LocalRotation.Quaternion() * Base.GetRotation());
    return Result;
}

float SaskartaDroneLogic::EchoRoundTripSeconds(float DistanceCm)
{
    return 2.f * FMath::Max(0.f, DistanceCm) / 34300.f;
}

float SaskartaDroneLogic::PingPeriodSeconds()
{
    return 3.f;
}

float SaskartaDroneLogic::EchoVolume(float DistanceCm)
{
    return FMath::Clamp(250.f / (FMath::Max(0.f, DistanceCm) + 150.f), 0.2f, 1.f);
}

void SaskartaDroneLogic::FPingHistory::Clear()
{
    for (FLinearColor& Slot : Slots) Slot = FLinearColor(0.f, 0.f, 0.f, EmptyTimeS);
}

void SaskartaDroneLogic::FPingHistory::Push(const FVector& Origin, float TimeS)
{
    Slots[2] = Slots[1];
    Slots[1] = Slots[0];
    Slots[0] = FLinearColor(float(Origin.X), float(Origin.Y), float(Origin.Z), TimeS);
}

FVector SaskartaDroneLogic::SwarmOffset(int32 Index, float S)
{
    // Carrier-local targets for the flight model. Drone 0 ends on the rear station, drone 1 on the front.
    static const FPathKey Lead[] = {
        {0.f, FVector(-7000.f, -900.f, 2200.f)}, {5.5f, FVector(-2200.f, -500.f, 900.f)},
        {7.f, FVector(-1300.f, -350.f, 500.f)}, {9.f, FVector(900.f, -300.f, 420.f)},
        {10.5f, FVector(450.f, -60.f, 480.f)}, {ArrivalBootS, FVector(-500.f, 60.f, 520.f)},
        {ArrivalEndS, FVector(-650.f, 60.f, 250.f)}};
    static const FPathKey Wing[] = {
        {0.f, FVector(-7600.f, 1100.f, 2500.f)}, {5.5f, FVector(-2600.f, 700.f, 1000.f)},
        {7.f, FVector(-1500.f, 450.f, 600.f)}, {9.f, FVector(1100.f, 350.f, 380.f)},
        {10.5f, FVector(1300.f, 450.f, 420.f)}, {ArrivalBootS, FVector(700.f, -40.f, 300.f)},
        {ArrivalEndS, FVector(650.f, -60.f, 250.f)}};
    if (Index == 0) return EvalPath(Lead, UE_ARRAY_COUNT(Lead), S);
    if (Index == 1) return EvalPath(Wing, UE_ARRAY_COUNT(Wing), S);
    const int32 I = FMath::Clamp(Index, 2, HardMaxSwarm - 1);
    return FVector(-2000.f, (I - 4.5f) * 300.f, 1500.f);
}

float SaskartaDroneLogic::ArrivalLight(int32 Index, float S)
{
    if (Index < 0 || Index > 1 || S < 5.4f || S >= 13.5f) return 0.f;
    if (S < 6.4f)
    {
        // Catching through the dust: a stuttering strike-up.
        const float Ramp = (S - 5.4f) / 1.f;
        return Ramp * (FMath::Sin(S * 47.f + Index * 3.f) > 0.2f ? 1.f : 0.35f);
    }
    if (S < 12.2f) return 1.f;
    return FMath::Lerp(1.f, 0.f, (S - 12.2f) / 1.3f);
}

FVector SaskartaDroneLogic::ArrivalLightTarget(int32 Index, float S)
{
    if (Index != 0) return FVector(1500.f, 0.f, 0.f);
    if (S < 9.f) return FVector(900.f, 0.f, 0.f);
    if (S < 11.f)
    {
        // The sweep: from the road ahead, over the carrier, to the road behind it.
        const float A = (S - 9.f) / 2.f;
        const float E = A * A * (3.f - 2.f * A);
        return FVector(FMath::Lerp(1400.f, -300.f, E), 0.f, 100.f * FMath::Sin(PI * E));
    }
    return FVector(0.f, 0.f, 100.f);
}

float SaskartaDroneLogic::RelayFlicker(float Age, float Duration)
{
    if (Age < 0.f || Duration <= 0.f || Age >= Duration) return 1.f;
    const float T = Age / Duration;
    if (T < 0.15f) return 0.08f;
    if (T < 0.3f) return 1.7f;
    if (T < 0.45f) return 0.35f;
    if (T < 0.6f) return 1.25f;
    return FMath::Lerp(0.8f, 1.f, (T - 0.6f) / 0.4f);
}

int32 SaskartaDroneLogic::FeedForYaw(int32 CurrentFeed, float OrbitYawDeg)
{
    const float A = FMath::Abs(FMath::UnwindDegrees(OrbitYawDeg));
    if (CurrentFeed == 0) return A > 118.f ? 1 : 0;
    return A < 60.f ? 0 : 1;
}

int32 SaskartaDroneLogic::AdvanceFeedSwitch(int32 CurrentFeed, float OrbitYawDeg, float DeltaSeconds, float& WaitSeconds)
{
    const int32 Candidate = FeedForYaw(CurrentFeed, OrbitYawDeg);
    if (Candidate == CurrentFeed)
    {
        WaitSeconds = 0.f;
        return CurrentFeed;
    }
    WaitSeconds += FMath::Max(0.f, DeltaSeconds);
    if (WaitSeconds < 0.4f) return CurrentFeed;
    WaitSeconds = 0.f;
    return Candidate;
}

float SaskartaDroneLogic::StationYawForDrone(int32 DroneIndex, int32 ActiveIndex, float OrbitYawDeg)
{
    const float Y = FMath::UnwindDegrees(OrbitYawDeg);
    const float A = FMath::Abs(Y);
    const float S = Y >= 0.f ? 1.f : -1.f;
    constexpr float Reach = 30.f;   // the active drone reaches the new relay threshold before the cut
    constexpr float Inset = 15.f;   // the waiting drone never crowds the seam
    if (DroneIndex == ActiveIndex)
    {
        return DroneIndex == 0 ? S * FMath::Min(A, 90.f + Reach) : S * FMath::Max(A, 90.f - Reach);
    }
    const float Mirror = 180.f - A;
    return DroneIndex == 0 ? S * FMath::Min(Mirror, 90.f - Inset) : S * FMath::Max(Mirror, 90.f + Inset);
}

FVector SaskartaDroneLogic::HoverDrift(int32 Index, float Seconds)
{
    const float T = Seconds;
    return FVector(FMath::Sin(0.38f * T + 1.3f * Index) * 18.f,
                   FMath::Sin(0.31f * T + 2.1f * Index) * 15.f,
                   FMath::Sin(0.42f * T + 0.7f * Index) * 25.f
                       + FMath::Sin(1.17f * T + 2.4f * Index) * 5.f);
}

FRotator SaskartaDroneLogic::GustTilt(int32 Index, float Seconds)
{
    const float Period = 4.6f + 0.7f * Index;
    const float Clock = FMath::Max(0.f, Seconds) + 1.3f * Index;
    const float Phase = FMath::Fmod(Clock, Period);
    const int32 GustIndex = FMath::FloorToInt(Clock / Period);
    const auto Ease = [](float T)
    {
        const float A = FMath::Clamp(T, 0.f, 1.f);
        return A * A * (3.f - 2.f * A);
    };
    const float Envelope = Ease(Phase / 0.4f) * (1.f - Ease((Phase - 0.4f) / 1.7f));
    const float Direction = FMath::Sin(1.9f * GustIndex + 1.2f * Index + 0.7f);
    return FRotator(3.5f * Envelope * Direction,
                    4.5f * Envelope * FMath::Sin(2.3f * GustIndex + Index + 0.4f),
                    7.f * Envelope * Direction);
}

void SaskartaDroneLogic::FDroneFlight::Reset(const FVector& At)
{
    Position = At;
    Velocity = FVector::ZeroVector;
    Accel = FVector::ZeroVector;
    PitchDeg = 0.f;
    RollDeg = 0.f;
    RotorRate = 1.f;
    Strain = 0.f;
    bValid = true;
}

void SaskartaDroneLogic::FDroneFlight::Step(const FVector& Target, float HeadingYawDeg, float DeltaSeconds)
{
    if (!bValid) Reset(Target);
    const float Dt = FMath::Clamp(DeltaSeconds, 0.f, 0.1f);
    if (Dt <= 0.f) return;
    // Lightly damped: visible inertia and overshoot before the station settles.
    const float Stiff = FMath::Clamp(Stiffness, 0.5f, 3.f);
    const float Omega = 3.2f * Stiff;
    constexpr float Zeta = 0.5f;
    const float MaxAccel = 2200.f * Stiff * Stiff;
    const float MaxSpeed = 1600.f * Stiff;
    const int32 Sub = FMath::Max(1, FMath::CeilToInt(Dt * 120.f));
    const float H = Dt / Sub;
    FVector Acc = FVector::ZeroVector;
    for (int32 I = 0; I < Sub; ++I)
    {
        Acc = ((Target - Position) * (Omega * Omega) - Velocity * (2.f * Zeta * Omega)).GetClampedToMaxSize(MaxAccel);
        Velocity = (Velocity + Acc * H).GetClampedToMaxSize(MaxSpeed);
        Position += Velocity * H;
    }
    Accel = Acc;
    const FVector Fwd = FRotator(0.f, HeadingYawDeg, 0.f).Vector();
    const FVector Right(-Fwd.Y, Fwd.X, 0.f);
    // Nose down into forward acceleration, bank into lateral acceleration.
    const float WantPitch = FMath::Clamp(float(-FVector::DotProduct(Acc, Fwd)) * 0.014f, -26.f, 26.f);
    const float WantRoll = FMath::Clamp(float(FVector::DotProduct(Acc, Right)) * 0.014f, -30.f, 30.f);
    const float WantRotor = FMath::Clamp(1.f + float(Acc.Z) * 0.00035f + float(Velocity.Z) * 0.0005f, 0.7f, 1.7f);
    const float K = 1.f - FMath::Exp(-Dt / 0.12f);
    const float KR = 1.f - FMath::Exp(-Dt / 0.2f);
    PitchDeg += (WantPitch - PitchDeg) * K;
    RollDeg += (WantRoll - RollDeg) * K;
    RotorRate += (WantRotor - RotorRate) * KR;
    // Motor load: a hard swing reads as strain well before the acceleration cap.
    const float WantStrain = FMath::Clamp(float(Acc.Size()) / (MaxAccel * 0.6f), 0.f, 1.f);
    const float KS = 1.f - FMath::Exp(-Dt / (WantStrain > Strain ? 0.06f : 0.25f));
    Strain += (WantStrain - Strain) * KS;
}

FVector SaskartaDroneLogic::FollowOffset(float OrbitYawDeg, float OrbitPitchDeg)
{
    const float Pitch = FMath::Clamp(OrbitPitchDeg, -45.f, 5.f);
    const float Horizontal = FMath::Sqrt(FollowDistanceCm * FollowDistanceCm + 60.f * 60.f);
    const FVector Base(-FollowDistanceCm, 60.f, 120.f - Horizontal * FMath::Tan(FMath::DegreesToRadians(Pitch)));
    return Base.RotateAngleAxis(OrbitYawDeg, FVector::UpVector).GetClampedToMaxSize(MaxEyeDistanceCm);
}

FVector SaskartaDroneLogic::HumanEscortTarget(int32 DroneIndex, const FTransform& Human,
    const FTransform& Wreck, float Seconds)
{
    // The two drones have different anchors. The parked unit must not drift up the road with Samyor.
    const FTransform& Anchor = DroneIndex == 0 ? Human : Wreck;
    const FVector Local = DroneIndex == 0 ? FVector(-180.f, 165.f, 260.f)
                                             : FVector(-170.f, -235.f, 190.f);
    const float Yaw = Anchor.GetRotation().Rotator().Yaw;
    return Anchor.GetLocation() + FRotator(0.f, Yaw, 0.f).RotateVector(Local)
        + HoverDrift(DroneIndex, Seconds) * 0.65f;
}

float SaskartaDroneLogic::RecenterYaw(float CurrentYawDeg, float IdleSeconds, float DeltaSeconds)
{
    if (IdleSeconds <= 4.f) return CurrentYawDeg;
    const float Before = FMath::Clamp((IdleSeconds - DeltaSeconds - 4.f) / 1.5f, 0.f, 1.f);
    const float After = FMath::Clamp((IdleSeconds - 4.f) / 1.5f, 0.f, 1.f);
    const auto Ease = [](float T) { return T * T * (3.f - 2.f * T); };
    const float Remaining = 1.f - Ease(Before);
    return Remaining <= KINDA_SMALL_NUMBER ? 0.f : CurrentYawDeg * (1.f - Ease(After)) / Remaining;
}

int32 SaskartaDroneLogic::CameraIndexForYaw(float OrbitYawDeg)
{
    return FMath::Abs(FMath::UnwindDegrees(OrbitYawDeg)) > 90.f ? 1 : 0;
}

float SaskartaDroneLogic::OrbitYawForDrone(int32 DroneIndex, float OrbitYawDeg)
{
    const float Yaw = FMath::UnwindDegrees(OrbitYawDeg);
    const float AbsYaw = FMath::Abs(Yaw);
    if (DroneIndex == 0)
    {
        return AbsYaw <= 90.f ? Yaw : FMath::Sign(Yaw) * (180.f - AbsYaw);
    }
    return AbsYaw >= 90.f ? Yaw : (Yaw >= 0.f ? 180.f - Yaw : -180.f - Yaw);
}

float SaskartaDroneLogic::AdvanceLaggedYaw(float CurrentDeg, float DesiredDeg, float DeltaSeconds)
{
    const float Dt = FMath::Clamp(DeltaSeconds, 0.f, 0.1f);
    const float Delta = FMath::FindDeltaAngleDegrees(CurrentDeg, DesiredDeg);
    // Smoothed, not lagged: ~0.1 s to close most of a look (was 0.25 s and a 180 deg/s cap).
    const float Alpha = 1.f - FMath::Exp(-Dt / 0.1f);
    return FMath::UnwindDegrees(CurrentDeg + FMath::Clamp(Delta * Alpha, -720.f * Dt, 720.f * Dt));
}

FVector2D SaskartaDroneLogic::LookOrbitDelta(const FRotator& Previous, const FRotator& Current)
{
    const FVector2D Delta(FMath::FindDeltaAngleDegrees(Previous.Yaw, Current.Yaw),
                          FMath::FindDeltaAngleDegrees(Previous.Pitch, Current.Pitch));
    // A jump this large in one frame is a scripted snap (respawn, face-the-road), not a look.
    return Delta.GetAbsMax() > 60.f ? FVector2D::ZeroVector : Delta;
}

FVector2D SaskartaDroneLogic::OrbitFromLook(const FVector2D& LookDeg)
{
    // The author: "you have to move too much with the mouse". The control rotation already carries
    // the player's sensitivity and invert; the orbit amplifies it, pitch less (its range is 50 deg).
    return FVector2D(LookDeg.X * 2.75f, LookDeg.Y * 1.6f);
}

SaskartaDroneLogic::FRotorMix SaskartaDroneLogic::RotorMix(float RotorRate, float SpeedCmS, float Strain, bool bOnCamera)
{
    // SFX_Drone_RotorLoop sits at -17.7 dB mean; the old fixed 0.09 put it ~-39 dB, under the radio.
    const float SpeedN = FMath::Clamp(SpeedCmS / 1200.f, 0.f, 1.f);
    const float Load = FMath::Clamp(Strain, 0.f, 1.f);
    const float Rate = FMath::Clamp(RotorRate, 0.5f, 2.f);
    FRotorMix Mix;
    const float Base = bOnCamera ? 0.55f : 0.9f;
    Mix.Volume = FMath::Clamp(Base * (0.85f + 0.3f * (Rate - 1.f) + 0.2f * SpeedN + 0.4f * Load), 0.15f, 1.6f);
    Mix.Pitch = FMath::Sqrt(Rate) * (1.f + 0.07f * SpeedN + 0.16f * Load);
    return Mix;
}

float SaskartaDroneLogic::WhooshLevel(float SpeedCmS, float Strain)
{
    const float SpeedN = FMath::Clamp((SpeedCmS - 250.f) / 1500.f, 0.f, 1.f);
    const float Load = FMath::Clamp(Strain, 0.f, 1.f);
    return FMath::Min(0.9f, 0.75f * SpeedN * FMath::Sqrt(SpeedN) + 0.3f * Load * Load);
}

float SaskartaDroneLogic::AdvanceLaggedPitch(float CurrentDeg, float DesiredDeg, float DeltaSeconds)
{
    const float Dt = FMath::Clamp(DeltaSeconds, 0.f, 0.1f);
    const float Alpha = 1.f - FMath::Exp(-Dt / 0.1f);
    const float Step = FMath::Clamp((DesiredDeg - CurrentDeg) * Alpha, -300.f * Dt, 300.f * Dt);
    return FMath::Clamp(CurrentDeg + Step, -45.f, 5.f);
}

void USaskartaFeedTagWidget::NativeOnInitialized()
{
    Super::NativeOnInitialized();
    if (!WidgetTree || WidgetTree->RootWidget) return;
    UCanvasPanel* Canvas = WidgetTree->ConstructWidget<UCanvasPanel>(UCanvasPanel::StaticClass(), TEXT("FeedTagCanvas"));
    WidgetTree->RootWidget = Canvas;
    Canvas->SetVisibility(ESlateVisibility::HitTestInvisible);
    Label = WidgetTree->ConstructWidget<UTextBlock>(UTextBlock::StaticClass(), TEXT("FeedTag"));
    Label->SetColorAndOpacity(FSlateColor(FLinearColor(0.807f, 0.434f, 0.162f)));
    if (UFont* Font = LoadObject<UFont>(nullptr, FeedFontPath)) Label->SetFont(FSlateFontInfo(Font, 20));
    UCanvasPanelSlot* TagSlot = Canvas->AddChildToCanvas(Label);
    TagSlot->SetAnchors(FAnchors(0.f, 0.f));
    TagSlot->SetAlignment(FVector2D(0.f, 0.f));
    TagSlot->SetPosition(FVector2D(56.f, 44.f));
    TagSlot->SetAutoSize(true);
    SetVisibility(ESlateVisibility::Collapsed);
}

void USaskartaFeedTagWidget::ShowTag(const FString& Text, float Opacity, float JitterPx)
{
    if (!Label) return;
    const bool bShow = !Text.IsEmpty() && Opacity > 0.01f;
    const ESlateVisibility Want = bShow ? ESlateVisibility::HitTestInvisible : ESlateVisibility::Collapsed;
    if (GetVisibility() != Want) SetVisibility(Want);
    if (!bShow) return;
    if (Shown != Text)
    {
        Label->SetText(FText::FromString(Text));
        Shown = Text;
    }
    Label->SetRenderOpacity(Opacity);
    Label->SetRenderTranslation(FVector2D(JitterPx, 0.f));
}

bool USaskartaDroneSequenceSubsystem::ShouldCreateSubsystem(UObject* Outer) const
{
    const UWorld* World = Cast<UWorld>(Outer);
    return World && World->IsGameWorld();
}

USaskartaDroneSequenceSubsystem* USaskartaDroneSequenceSubsystem::GetDroneSequence(const UObject* Context)
{
    const UWorld* World = GEngine ? GEngine->GetWorldFromContextObject(Context, EGetWorldErrorMode::ReturnNull) : nullptr;
    return World ? World->GetSubsystem<USaskartaDroneSequenceSubsystem>() : nullptr;
}

void USaskartaDroneSequenceSubsystem::OnWorldBeginPlay(UWorld& World)
{
    Super::OnWorldBeginPlay(World);
    Runner = World.GetSubsystem<USaskartaEventRunner>();
    if (Runner.IsValid())
    {
        Runner->OnModeChanged.AddDynamic(this, &USaskartaDroneSequenceSubsystem::HandleModeChanged);
        Runner->OnCinematicStarted.AddDynamic(this, &USaskartaDroneSequenceSubsystem::HandleCinematicStarted);
        Runner->OnCinematicFinished.AddDynamic(this, &USaskartaDroneSequenceSubsystem::HandleCinematicFinished);
    }
    DroneMesh = DroneAsset<USkeletalMesh>(TEXT("/Game/SaskartaGaea/Characters/Drone/SK_AuxDrone.SK_AuxDrone"));
    SpinClip = DroneAsset<UAnimSequence>(TEXT("/Game/SaskartaGaea/Characters/Drone/A_AuxDrone_Spin.A_AuxDrone_Spin"));
    PingSound = DroneAsset<USoundBase>(TEXT("/Game/SaskartaGaea/Audio/Drone/SFX_Echo_Ping.SFX_Echo_Ping"));
    ReturnSound = DroneAsset<USoundBase>(TEXT("/Game/SaskartaGaea/Audio/Drone/SFX_Echo_Return.SFX_Echo_Return"));
    // Optional until the next editor pass imports it; the feed runs without the bed.
    WindSound = Cast<USoundBase>(StaticLoadObject(USoundBase::StaticClass(), nullptr,
        TEXT("/Game/SaskartaGaea/Audio/Drone/SFX_Echo_WindLoop.SFX_Echo_WindLoop"), nullptr, LOAD_NoWarn | LOAD_Quiet));
    RotorSound = DroneAsset<USoundBase>(TEXT("/Game/SaskartaGaea/Audio/Drone/SFX_Drone_RotorLoop.SFX_Drone_RotorLoop"));
    ScrapeSound = DroneAsset<USoundBase>(TEXT("/Game/SaskartaGaea/Audio/Drone/SFX_Drone_Scrape.SFX_Drone_Scrape"));
    ImpactSound = DroneAsset<USoundBase>(TEXT("/Game/SaskartaGaea/Audio/Drone/SFX_Drone_FallImpact.SFX_Drone_FallImpact"));
    OpticsSound = DroneAsset<USoundBase>(TEXT("/Game/SaskartaGaea/Audio/Drone/SFX_Drone_OpticsSnap.SFX_Drone_OpticsSnap"));
    // Optional until imported/authored in the next editor pass.
    ShriekSound = OptionalAsset<USoundBase>(TEXT("/Game/SaskartaGaea/Audio/Drone/SFX_Carrier_ServoShriek.SFX_Carrier_ServoShriek"));
    DownwashMaterial = DroneAsset<UMaterialInterface>(TEXT("/Game/SaskartaGaea/Look/Drone/M_DroneDownwash.M_DroneDownwash"));
    DownwashPlane = DroneAsset<UStaticMesh>(TEXT("/Game/SaskartaGaea/Look/Drone/SM_DroneDownwashCard.SM_DroneDownwashCard"));
    PreTickHandle = FWorldDelegates::OnWorldPreActorTick.AddUObject(this, &USaskartaDroneSequenceSubsystem::HandlePreActorTick);
    PingAttenuation = MakeAttenuation(this, 80.f, 3000.f, 80.f);
    EchoAttenuation = MakeAttenuation(this, 30.f, 6000.f, 25.f);
    // Wide falloff: the rotors are heard from ~70 m before the drones are seen.
    RotorAttenuation = MakeAttenuation(this, 200.f, 10000.f, 100.f);
    BindAuxMaterial();
    EchoTimers.SetNum(3);
    World.GetTimerManager().SetTimer(StepTimer, this, &USaskartaDroneSequenceSubsystem::Step, StepS, true);
    if (Runner.IsValid())
    {
        SetAuxActive(Runner->IsPresentationModeActive(AuxMode));
        SetDroneFeedActive(Runner->IsPresentationModeActive(DroneMode));
    }
}

void USaskartaDroneSequenceSubsystem::Deinitialize()
{
    FWorldDelegates::OnWorldPreActorTick.Remove(PreTickHandle);
    StopSequence();
    if (Runner.IsValid())
    {
        Runner->OnModeChanged.RemoveDynamic(this, &USaskartaDroneSequenceSubsystem::HandleModeChanged);
        Runner->OnCinematicStarted.RemoveDynamic(this, &USaskartaDroneSequenceSubsystem::HandleCinematicStarted);
        Runner->OnCinematicFinished.RemoveDynamic(this, &USaskartaDroneSequenceSubsystem::HandleCinematicFinished);
    }
    if (UWorld* World = GetWorld()) World->GetTimerManager().ClearTimer(StepTimer);
    Super::Deinitialize();
}

void USaskartaDroneSequenceSubsystem::HandlePreActorTick(UWorld* InWorld, ELevelTick TickType, float DeltaSeconds)
{
    if (InWorld != GetWorld() || TickType == LEVELTICK_PauseTick || DeltaSeconds <= 0.f) return;
    // Per frame, not per 30 Hz step: movement input is consumed every tick.
    if (bArrivalDriving) DriveCarrierDuringArrival();
    // The relay feed is the player's view: look and flight run every frame, before the camera update.
    const bool bFeedLive = bDroneFeedActive && Runner.IsValid() && !Runner->IsCinematicActive() &&
        Drones.IsValidIndex(1) && Drones[0].IsValid() && Drones[1].IsValid();
    if (bFeedLive)
    {
        PollOrbitInput(DeltaSeconds);
        UpdateFollow(DeltaSeconds);
    }
    else
    {
        bLookBaseline = false;
        if (WhooshLoop) WhooshLoop->SetVolumeMultiplier(0.001f);
        if (bHumanEscort && !bEndingDroneGrounded && Runner.IsValid() &&
            (Runner->GetFlowState() == FName(TEXT("Human")) || Runner->GetFlowState() == FName(TEXT("Transmit"))))
        {
            UpdateHumanEscort(DeltaSeconds);
        }
    }
}

void USaskartaDroneSequenceSubsystem::DriveCarrierDuringArrival()
{
    ACharacter* P = Carrier();
    if (!P) return;
    const FVector Forward = bRoadFrameFresh ? RoadForward : P->GetActorForwardVector().GetSafeNormal2D();
    const FVector Right(-Forward.Y, Forward.X, 0.f);
    const float Lateral = bRoadFrameFresh ? FVector::DotProduct(P->GetActorLocation() - RoadCentre, Right) : 0.f;
    const FVector Dir = (Forward - Right * FMath::Clamp(Lateral / 400.f, -0.5f, 0.5f)).GetSafeNormal2D();
    P->AddMovementInput(Dir, ArrivalDriveScale, true);
}

APlayerController* USaskartaDroneSequenceSubsystem::PlayerController() const
{
    const UWorld* World = GetWorld();
    return World ? World->GetFirstPlayerController() : nullptr;
}

ACharacter* USaskartaDroneSequenceSubsystem::Carrier() const
{
    if (WreckCarrier.IsValid()) return Cast<ACharacter>(WreckCarrier.Get());
    if (FallCarrier.IsValid()) return FallCarrier.Get();
    APlayerController* PC = PlayerController();
    return PC ? Cast<ACharacter>(PC->GetPawn()) : nullptr;
}

FVector USaskartaDroneSequenceSubsystem::LocalAtCarrier(const FVector& Local) const
{
    const ACharacter* P = Carrier();
    if (!P) return FVector::ZeroVector;
    const FVector Forward = bRoadFrameFresh ? RoadForward : P->GetActorForwardVector().GetSafeNormal2D();
    const FVector Feet = P->GetActorLocation() - FVector(0.f, 0.f, P->GetSimpleCollisionHalfHeight());
    return Feet + FRotator(0.f, Forward.Rotation().Yaw, 0.f).RotateVector(Local);
}

AActor* USaskartaDroneSequenceSubsystem::GetDroneViewTarget() const
{
    return Drones.IsValidIndex(ActiveDroneIndex) ? Drones[ActiveDroneIndex].Get() : nullptr;
}

AActor* USaskartaDroneSequenceSubsystem::GetHumanDroneViewTarget() const
{
    return bHumanEscort && Drones.IsValidIndex(0) ? Drones[0].Get() : nullptr;
}

bool USaskartaDroneSequenceSubsystem::HandoverToHumanDrone(float BlendSeconds)
{
    APlayerController* PC = PlayerController();
    AActor* Eye = GetHumanDroneViewTarget();
    if (!PC || !Eye || !PC->GetPawn() || PC->GetPawn() == WreckCarrier.Get()) return false;
    UpdateHumanEscort(0.f);
    if (PC->GetViewTarget() != Eye)
    {
        if (Runner.IsValid()) Runner->SetCollisionSafeViewTarget(PC, Eye, FMath::Max(0.f, BlendSeconds));
        else PC->SetViewTarget(Eye);
    }
    if (USkeletalMeshComponent* Mesh = Eye->FindComponentByClass<USkeletalMeshComponent>())
        Mesh->SetVisibility(false); // the camera's own hull cannot occlude its lens
    return true;
}

void USaskartaDroneSequenceSubsystem::SetRoadFrame(FVector Centre, FVector Forward, float HalfWidthCm)
{
    RoadCentre = Centre;
    RoadForward = Forward.GetSafeNormal2D();
    RoadHalfWidthCm = FMath::Clamp(HalfWidthCm, 200.f, 1000.f);
    bRoadFrameFresh = !RoadForward.IsNearlyZero();
}

void USaskartaDroneSequenceSubsystem::ResolveRoadFrame()
{
    UWorld* World = GetWorld();
    ACharacter* P = Carrier();
    if (!World || !P) return;
    if (!RoadSpline.IsValid() && World->GetTimeSeconds() - LastRoadSearchS >= 1.f)
    {
        LastRoadSearchS = World->GetTimeSeconds();
        static const FName RoadTag(TEXT("Saskarta.Road"));
        for (TActorIterator<AActor> It(World); It; ++It)
        {
            if (It->ActorHasTag(RoadTag) || It->GetClass()->GetName().StartsWith(TEXT("BP_Saskarta_Road")))
            {
                RoadSpline = It->FindComponentByClass<USplineComponent>();
                if (RoadSpline.IsValid()) break;
            }
        }
    }
    if (RoadSpline.IsValid())
    {
        SetRoadFrame(RoadSpline->FindLocationClosestToWorldLocation(P->GetActorLocation(), ESplineCoordinateSpace::World),
            -RoadSpline->FindDirectionClosestToWorldLocation(P->GetActorLocation(), ESplineCoordinateSpace::World), 225.f);
    }
    else
    {
        bRoadFrameFresh = false;
    }
}

void USaskartaDroneSequenceSubsystem::PollOrbitInput(float Dt)
{
    // Look is read as the change of the control rotation, which the carrier's own look input
    // (IA_Look, mouse and right stick) drives; the old per-step mouse-axis poll read the 0.07
    // sensitivity-scaled axis on every other frame, so the drones barely moved (the author:
    // "when i move my mouse to move the drone ... the drone doesnt move in space").
    APlayerController* PC = PlayerController();
    if (!PC || !PC->IsLocalController() ||
        (Runner.IsValid() && (Runner->IsHoldingInput() || Runner->IsPromptActive())))
    {
        bLookBaseline = false;
        return;
    }
    const FRotator Control = PC->GetControlRotation();
    if (bLookBaseline)
    {
        const FVector2D Delta = SaskartaDroneLogic::LookOrbitDelta(LastControlRot, Control);
        const FVector2D Orbit = SaskartaDroneLogic::OrbitFromLook(Delta);
        if (!Orbit.IsNearlyZero(0.001f)) AddOrbitInput(float(Orbit.X), float(Orbit.Y));
    }
    if (PC->IsLookInputIgnored())
    {
        // Someone else holds the look: read the raw axes (legacy 2.5 deg per scaled unit).
        float MX = 0.f, MY = 0.f;
        PC->GetInputMouseDelta(MX, MY);
        const float SX = PC->GetInputAnalogKeyState(EKeys::Gamepad_RightX);
        const float SY = PC->GetInputAnalogKeyState(EKeys::Gamepad_RightY);
        // Stick at full tilt sweeps a side in about a second, as a brisk mouse sweep does.
        const FVector2D Look(MX * 2.5f + (FMath::Abs(SX) > 0.15f ? SX * Dt * 65.f : 0.f),
                             MY * 2.5f + (FMath::Abs(SY) > 0.15f ? SY * Dt * 40.f : 0.f));
        const FVector2D Orbit = SaskartaDroneLogic::OrbitFromLook(Look);
        if (!Orbit.IsNearlyZero(0.001f)) AddOrbitInput(float(Orbit.X), float(Orbit.Y));
    }
    // Hold the controller pitch on the orbit pitch (inside the camera manager's -60..35 clamp),
    // so pitch input never runs into that clamp while the orbit still has room.
    FRotator Hold = Control;
    if (!FMath::IsNearlyZero(FMath::FindDeltaAngleDegrees(Control.Pitch, DesiredOrbitPitchDeg), 0.01f))
    {
        Hold.Pitch = DesiredOrbitPitchDeg;
        PC->SetControlRotation(Hold);
    }
    LastControlRot = Hold;
    bLookBaseline = true;
}

void USaskartaDroneSequenceSubsystem::AddOrbitInput(float YawDegrees, float PitchDegrees)
{
    DesiredOrbitYawDeg = FMath::UnwindDegrees(DesiredOrbitYawDeg + YawDegrees);
    DesiredOrbitPitchDeg = FMath::Clamp(DesiredOrbitPitchDeg + PitchDegrees, -45.f, 5.f);
    if (GetWorld()) LastLookS = GetWorld()->GetTimeSeconds();
}

void USaskartaDroneSequenceSubsystem::HandleModeChanged(FName Mode, bool bOn)
{
    if (Mode == AuxMode) SetAuxActive(bOn);
    if (Mode == DroneMode) SetDroneFeedActive(bOn);
}

void USaskartaDroneSequenceSubsystem::HandleCinematicStarted(FName Id)
{
    if (AActor* Eye = GetHumanDroneViewTarget(); Eye && !bEndingDroneGrounded)
        if (USkeletalMeshComponent* Mesh = Eye->FindComponentByClass<USkeletalMeshComponent>())
            Mesh->SetVisibility(true); // visible to exterior cinematic cameras
    if (Id == FallCine)
    {
        FallCarrier = Carrier();
        FallMesh = FallCarrier.IsValid() ? FallCarrier->GetMesh() : nullptr;
        if (FallMesh.IsValid())
        {
            SavedMeshRelative = FallMesh->GetRelativeTransform();
        }
        if (APlayerController* PC = PlayerController(); PC && FallCarrier.IsValid() && GetWorld())
        {
            FVector ViewLocation;
            FRotator ViewRotation;
            PC->GetPlayerViewPoint(ViewLocation, ViewRotation);
            FActorSpawnParameters Params;
            Params.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
            ACameraActor* View = GetWorld()->SpawnActor<ACameraActor>(ACameraActor::StaticClass(),
                ViewLocation, ViewRotation, Params);
            if (View && FallCarrier->GetRootComponent())
            {
                View->SetActorEnableCollision(false);
                if (PC->PlayerCameraManager)
                {
                    SavedFallViewFov = PC->PlayerCameraManager->GetFOVAngle();
                    View->GetCameraComponent()->SetFieldOfView(SavedFallViewFov);
                }
                // The lens is mounted on the carrier body: ride the tipping mesh, not the upright capsule.
                USceneComponent* Mount = FallMesh.IsValid() ? static_cast<USceneComponent*>(FallMesh.Get())
                                                            : FallCarrier->GetRootComponent();
                View->AttachToComponent(Mount, FAttachmentTransformRules::KeepWorldTransform);
                SavedFallViewRelative = View->GetRootComponent()->GetRelativeTransform();
                SavedFallViewTarget = PC->GetViewTarget();
                FallViewActor = View;
                PC->SetViewTarget(View); // same location, rotation and FOV: no external camera cut
            }
            else if (View)
            {
                View->Destroy();
            }
        }
        if (FallCarrier.IsValid() && GetWorld())
        {
            if (const FStructProperty* GroundProperty = FindFProperty<FStructProperty>(
                    FallCarrier->GetClass(), TEXT("GroundTimer")))
            {
                const FTimerHandle* Handle = GroundProperty->ContainerPtrToValuePtr<FTimerHandle>(FallCarrier.Get());
                if (Handle && GetWorld()->GetTimerManager().IsTimerActive(*Handle))
                {
                    PausedGroundTimer = *Handle;
                    GetWorld()->GetTimerManager().PauseTimer(PausedGroundTimer);
                    bGroundTimerPaused = true;
                }
            }
        }
        bFallActive = FallMesh.IsValid() || FallViewActor.IsValid();
        bScrapePlayed = bImpactPlayed = bOpticsPlayed = bShriekPlayed = false;
    }
    else if (Id == SwarmCine)
    {
        bSwarmPending = true;
        bFeedBooted = false;
    }
    else if (Id == FName(TEXT("CIN_19_HATCH")))
    {
        BeginHumanEscort();
        if (Runner.IsValid())
        {
            Runner->SetPresentationMode(AuxMode, false);
            Runner->SetPresentationMode(DroneMode, false);
        }
    }
    else if (Id == FName(TEXT("CIN_24_TRANSMISSION")))
    {
        // ConfigureCamera hid the neck so Samyor's first-person eye cannot see inside his head.
        // The grounded drone is an exterior camera: restore the whole head subtree for this shot.
        ACharacter* Human = PlayerController() ? Cast<ACharacter>(PlayerController()->GetPawn()) : nullptr;
        if (Human && Human != WreckCarrier.Get() && Human->GetMesh())
        {
            Human->GetMesh()->UnHideBoneByName(FName(TEXT("Neck")));
        }
        GroundEscortDroneAtRadioPost();
    }
}

void USaskartaDroneSequenceSubsystem::HandleCinematicFinished(FName Id)
{
    if (Id == FallCine) RestoreCarrierMesh();
    if (Id == SwarmCine)
    {
        bSwarmPending = false;
        bSwarmActive = false;
        if (Runner.IsValid() && Runner->IsPresentationModeActive(DroneMode)) HandoverToDrone(0.f);
        else ClearDrones();
    }
}

void USaskartaDroneSequenceSubsystem::BindAuxMaterial()
{
    if (AuxMid && AuxVolume.IsValid()) return;
    UWorld* World = GetWorld();
    if (!World) return;
    // The aux view rides the sequence's own unbound volume. Finding the level's sensor volume by
    // tag, name, label or material failed in the packaged World Partition game (the author: the
    // view stayed the normal camera under the acoustic captions), so nothing is looked up here.
    UMaterialInterface* Base = DroneAsset<UMaterialInterface>(TEXT("/Game/SaskartaGaea/Look/AuxSensors/MI_PP_AuxSensors.MI_PP_AuxSensors"));
    if (!Base)
    {
        UE_LOG(LogTemp, Error, TEXT("Drone: aux view unavailable, MI_PP_AuxSensors did not load (check the cook)"));
        return;
    }
    if (!AuxVolume.IsValid())
    {
        FActorSpawnParameters Params;
        Params.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
        Params.ObjectFlags |= RF_Transient;
        APostProcessVolume* Volume = World->SpawnActor<APostProcessVolume>(APostProcessVolume::StaticClass(),
            FVector::ZeroVector, FRotator::ZeroRotator, Params);
        if (!Volume)
        {
            UE_LOG(LogTemp, Error, TEXT("Drone: aux view unavailable, its post-process volume did not spawn"));
            return;
        }
        Volume->bUnbound = true;
        Volume->bEnabled = true;
        Volume->BlendWeight = 1.f;
        Volume->Priority = 1000.f;   // after the sensor volume, like the old appended blendable
        Volume->SetActorEnableCollision(false);
        AuxVolume = Volume;
        AuxMid = nullptr;
    }
    AuxMid = UMaterialInstanceDynamic::Create(Base, AuxVolume.Get());
    FWeightedBlendable Blend;
    Blend.Weight = bAuxActive ? 1.f : 0.f;
    Blend.Object = AuxMid;
    AuxVolume->Settings.WeightedBlendables.Array.Reset();
    AuxBlendIndex = AuxVolume->Settings.WeightedBlendables.Array.Add(Blend);
    UE_LOG(LogTemp, Display, TEXT("Drone: aux view bound on %s (active %d)"), *AuxVolume->GetName(), bAuxActive ? 1 : 0);
}

void USaskartaDroneSequenceSubsystem::SetAuxActive(bool bOn)
{
    if (bAuxActive == bOn) return;
    bAuxActive = bOn;
    if (bOn && (!AuxMid || !AuxVolume.IsValid())) BindAuxMaterial();
    UE_LOG(LogTemp, Display, TEXT("Drone: aux sensors %s (view bound %d)"), bOn ? TEXT("on") : TEXT("off"),
        (AuxMid && AuxVolume.IsValid()) ? 1 : 0);
    UWorld* World = GetWorld();
    if (!World) return;
    World->GetTimerManager().ClearTimer(PingTimer);
    for (FTimerHandle& H : EchoTimers) World->GetTimerManager().ClearTimer(H);
    if (WindLoop)
    {
        WindLoop->FadeOut(0.6f, 0.f);
        WindLoop = nullptr;
    }
    if (bOn)
    {
        PingHistory.Clear();
        const float Period = SaskartaDroneLogic::PingPeriodSeconds();
        if (bFallActive)
        {
            // A1 switches source at 5 s; the first acoustic reveal begins near 7 s.
            World->GetTimerManager().SetTimer(PingTimer, this, &USaskartaDroneSequenceSubsystem::Ping,
                Period, true, 1.8f);
        }
        else
        {
            Ping();
            World->GetTimerManager().SetTimer(PingTimer, this, &USaskartaDroneSequenceSubsystem::Ping, Period, true);
        }
        if (WindSound)
        {
            WindLoop = UGameplayStatics::CreateSound2D(this, WindSound, 1.f, 1.f, 0.f, nullptr, false, true);
            if (WindLoop) WindLoop->FadeIn(2.f, 0.3f);
        }
    }
    if (AuxVolume.IsValid() && AuxVolume->Settings.WeightedBlendables.Array.IsValidIndex(AuxBlendIndex))
    {
        AuxVolume->Settings.WeightedBlendables.Array[AuxBlendIndex].Weight = bOn ? 1.f : 0.f;
    }
}

void USaskartaDroneSequenceSubsystem::UpdateAuxMaterial(double NowS)
{
    if (!bAuxActive || !AuxMid) return;
    const ACharacter* P = Carrier();
    if (!P) return;
    const FVector Centre = bRoadFrameFresh ? RoadCentre : P->GetActorLocation();
    const FVector Forward = bRoadFrameFresh ? RoadForward : P->GetActorForwardVector().GetSafeNormal2D();
    // Look scalars (PingSpeed, Fade, RangeCm, GridCm, SpacingPx, DotPx, Gain) keep the
    // material-instance defaults from Tools/Drone/build_aux_material.py.
    AuxMid->SetScalarParameterValue(TEXT("Clock"), NowS);
    AuxMid->SetScalarParameterValue(TEXT("RoadHalfWidth"), RoadHalfWidthCm);
    AuxMid->SetVectorParameterValue(TEXT("PingA"), PingHistory.Slots[0]);
    AuxMid->SetVectorParameterValue(TEXT("PingB"), PingHistory.Slots[1]);
    AuxMid->SetVectorParameterValue(TEXT("PingC"), PingHistory.Slots[2]);
    AuxMid->SetVectorParameterValue(TEXT("RoadCentre"), FLinearColor(Centre));
    AuxMid->SetVectorParameterValue(TEXT("RoadForward"), FLinearColor(Forward));
    // Arriving drones show as moving dot clusters; a lit searchlight glares and paints its cone.
    for (int32 I = 0; I < 2; ++I)
    {
        FLinearColor Blip(0.f, 0.f, 0.f, 0.f);
        FLinearColor Beam(0.f, 0.f, 0.f, 0.f);
        if (Drones.IsValidIndex(I) && Drones[I].IsValid())
        {
            const FVector L = Drones[I]->GetActorLocation();
            Blip = FLinearColor(float(L.X), float(L.Y), float(L.Z), 1.f);
            if (DroneLights.IsValidIndex(I) && DroneLights[I] && DroneLights[I]->IsVisible())
            {
                const FVector D = DroneLights[I]->GetForwardVector();
                Beam = FLinearColor(float(D.X), float(D.Y), float(D.Z),
                    FMath::Clamp(DroneLights[I]->Intensity / DroneLightCandela, 0.f, 1.f));
            }
        }
        AuxMid->SetVectorParameterValue(I == 0 ? TEXT("BlipA") : TEXT("BlipB"), Blip);
        AuxMid->SetVectorParameterValue(I == 0 ? TEXT("LightA") : TEXT("LightB"), Beam);
    }
}

void USaskartaDroneSequenceSubsystem::PlayEcho(FVector Location, float Volume)
{
    if (bAuxActive && ReturnSound) UGameplayStatics::PlaySoundAtLocation(this, ReturnSound, Location,
        FRotator::ZeroRotator, Volume, 1.f, 0.f, EchoAttenuation);
}

void USaskartaDroneSequenceSubsystem::Ping()
{
    UWorld* World = GetWorld();
    ACharacter* P = Carrier();
    if (!bAuxActive || !World || !P || !Runner.IsValid() || Runner->GetFlowState() == FName(TEXT("Human"))) return;
    ResolveRoadFrame();
    const FVector Origin = P->GetActorLocation() + FVector(0.f, 0.f, 120.f);
    const FVector Forward = bRoadFrameFresh ? RoadForward : P->GetActorForwardVector().GetSafeNormal2D();
    const FVector Right = FVector(-Forward.Y, Forward.X, 0.f);
    const FVector Centre = bRoadFrameFresh ? RoadCentre : P->GetActorLocation();
    const float Lateral = FVector::DotProduct(P->GetActorLocation() - Centre, Right);
    const float Left = FMath::Clamp(RoadHalfWidthCm + Lateral, 30.f, 9000.f);
    const float RightD = FMath::Clamp(RoadHalfWidthCm - Lateral, 30.f, 9000.f);
    // The cadence stays fixed; the nearer edge answers sooner (2d/343 s), louder, and from its side.
    PingHistory.Push(Origin, static_cast<float>(World->GetTimeSeconds()));
    if (PingSound) UGameplayStatics::PlaySoundAtLocation(this, PingSound, Origin,
        FRotator::ZeroRotator, 1.f, 1.f, 0.f, PingAttenuation);
    const FVector Edge[2] = {Centre - Right * RoadHalfWidthCm, Centre + Right * RoadHalfWidthCm};
    const float Dist[2] = {Left, RightD};
    for (int32 I = 0; I < 2; ++I)
    {
        if (!EchoTimers.IsValidIndex(I)) continue;
        const FVector At = Edge[I] + Forward * FVector::DotProduct(P->GetActorLocation() - Centre, Forward) + FVector(0.f, 0.f, 100.f);
        FTimerDelegate D = FTimerDelegate::CreateUObject(this, &USaskartaDroneSequenceSubsystem::PlayEcho, At,
            SaskartaDroneLogic::EchoVolume(Dist[I]));
        World->GetTimerManager().SetTimer(EchoTimers[I], D, FMath::Max(0.005f, SaskartaDroneLogic::EchoRoundTripSeconds(Dist[I])), false);
    }
    FHitResult Hit;
    FCollisionQueryParams Query(SCENE_QUERY_STAT(SaskartaDroneEcho), false, P);
    if (World->LineTraceSingleByChannel(Hit, Origin, Origin + Forward * 9000.f, ECC_Visibility, Query) && EchoTimers.IsValidIndex(2))
    {
        FTimerDelegate D = FTimerDelegate::CreateUObject(this, &USaskartaDroneSequenceSubsystem::PlayEcho, FVector(Hit.ImpactPoint),
            0.6f * SaskartaDroneLogic::EchoVolume(Hit.Distance));
        World->GetTimerManager().SetTimer(EchoTimers[2], D,
            FMath::Max(0.01f, SaskartaDroneLogic::EchoRoundTripSeconds(Hit.Distance)), false);
    }
}

void USaskartaDroneSequenceSubsystem::UpdateFall(float CineS)
{
    if (CineS < 0.f || (!FallMesh.IsValid() && !FallViewActor.IsValid())) return;
    UWorld* World = GetWorld();
    ACharacter* Body = FallCarrier.Get();
    if (!World || !Body) return;
    FCollisionQueryParams Query(SCENE_QUERY_STAT(SaskartaFallGround), false, Body);
    if (FallMesh.IsValid())
    {
        // Trace the tipping body against the terrain every frame and lift it out of any contact.
        SaskartaDroneLogic::FFallPose Pose = SaskartaDroneLogic::FallPose(CineS);
        const float R = Body->GetSimpleCollisionRadius();
        const float Hh = Body->GetSimpleCollisionHalfHeight();
        const FVector Probe[] = {
            FVector(0.f, -R, Hh), FVector(0.f, -R, 1.8f * Hh), FVector(0.8f * R, -0.6f * R, Hh),
            FVector(-0.8f * R, -0.6f * R, Hh), FVector(0.f, 0.f, 2.f * Hh), FVector(R, 0.f, 1.2f * Hh),
            FVector(0.f, R, Hh)};
        constexpr int32 NBody = UE_ARRAY_COUNT(Probe);
        constexpr int32 N = NBody + 1;   // + the lens riding on the body
        float PointZ[N];
        float GroundZ[N];
        const FTransform ActorXf = Body->GetActorTransform();
        const bool bLensOnBody = FallViewActor.IsValid() && FallViewActor->GetRootComponent() &&
            FallViewActor->GetRootComponent()->GetAttachParent() == FallMesh.Get();
        const FTransform Fallen = SaskartaDroneLogic::ComposeFallRelative(SavedMeshRelative, Pose);
        for (int32 I = 0; I < N; ++I)
        {
            if (I == NBody && !bLensOnBody)
            {
                PointZ[I] = 0.f;
                GroundZ[I] = -1.e7f;
                continue;
            }
            const FVector Local = I < NBody
                ? SavedMeshRelative.GetLocation() + Pose.LocalOffset + Pose.LocalRotation.RotateVector(Probe[I])
                : Fallen.TransformPosition(SavedFallViewRelative.GetLocation());
            const FVector W = ActorXf.TransformPosition(Local);
            FHitResult Hit;
            PointZ[I] = float(W.Z);
            GroundZ[I] = World->LineTraceSingleByChannel(Hit, W + FVector(0.f, 0.f, 300.f), W - FVector(0.f, 0.f, 400.f),
                ECC_Visibility, Query) ? float(Hit.ImpactPoint.Z) : float(W.Z) - 1000.f;
            if (I == NBody) GroundZ[I] += 8.f;   // the lens keeps a little more than the body: in the dust, not under it
        }
        Pose.LocalOffset.Z += SaskartaDroneLogic::ContactLift(MakeArrayView(PointZ, N), MakeArrayView(GroundZ, N), 4.f);
        FallMesh->SetRelativeTransform(SaskartaDroneLogic::ComposeFallRelative(SavedMeshRelative, Pose));
    }
    if (FallViewActor.IsValid() && FallViewActor->GetRootComponent())
    {
        // Rigid on its mount: the view tilts and falls with the body and takes the real impact.
        FallViewActor->GetCameraComponent()->SetFieldOfView(
            SavedFallViewFov + SaskartaDroneLogic::FallFaultFovDelta(CineS));
        FallViewActor->GetRootComponent()->SetRelativeTransform(
            SaskartaDroneLogic::MountedFallView(SavedFallViewRelative, CineS));
    }
    UpdateFallLens(CineS);
    const FVector At = Body->GetActorLocation();
    const FVector Back = -Body->GetActorForwardVector() * 150.f;
    const FVector Left = -Body->GetActorRightVector() * 60.f;
    if (!bShriekPlayed && CineS >= 0.35f)
    {
        bShriekPlayed = true;
        if (ShriekSound) UGameplayStatics::PlaySoundAtLocation(this, ShriekSound, At + Left,
            FRotator::ZeroRotator, 1.f, 1.f, 0.f, PingAttenuation);
    }
    if (!bImpactPlayed && CineS >= FallImpactS)
    {
        bImpactPlayed = true;
        if (ImpactSound) UGameplayStatics::PlaySoundAtLocation(this, ImpactSound, At + Left,
            FRotator::ZeroRotator, 1.f, 1.f, 0.f, PingAttenuation);
    }
    if (!bScrapePlayed && CineS >= FallImpactS + 0.05f)
    {
        bScrapePlayed = true;
        // The capsule scraping behind.
        if (ScrapeSound) UGameplayStatics::PlaySoundAtLocation(this, ScrapeSound, At + Back,
            FRotator::ZeroRotator, 1.f, 1.f, 0.f, PingAttenuation);
    }
    if (!bOpticsPlayed && CineS >= 2.3f)
    {
        bOpticsPlayed = true;
        if (OpticsSound) UGameplayStatics::PlaySoundAtLocation(this, OpticsSound, At,
            FRotator::ZeroRotator, 1.f, 1.f, 0.f, PingAttenuation);
        ShowTag(TEXT("OPTICS FAULT"), 1.2f);
    }
}

void USaskartaDroneSequenceSubsystem::UpdateFallLens(float CineS)
{
    if (!FallViewActor.IsValid()) return;
    FPostProcessSettings& PP = FallViewActor->GetCameraComponent()->PostProcessSettings;
    const float Dust = SaskartaDroneLogic::FallLensDust(CineS);
    const bool bTorn = SaskartaDroneLogic::FallSignalTorn(CineS);
    const bool bDust = Dust > 0.f;
    // Dust on the lens: a brown haze, heavy vignette and grain that partly stays on.
    PP.bOverride_SceneColorTint = bDust;
    PP.SceneColorTint = FMath::Lerp(FLinearColor::White, FLinearColor(0.78f, 0.64f, 0.48f), 0.7f * Dust);
    PP.bOverride_VignetteIntensity = bDust;
    PP.VignetteIntensity = 0.4f + 1.2f * Dust;
    PP.bOverride_ColorContrast = bDust;
    PP.ColorContrast = FVector4(1.f - 0.3f * Dust, 1.f - 0.3f * Dust, 1.f - 0.3f * Dust, 1.f);
    PP.bOverride_FilmGrainIntensity = bDust || bTorn;
    PP.FilmGrainIntensity = bTorn ? 1.f : 0.7f * Dust;
    PP.bOverride_SceneFringeIntensity = bDust || bTorn;
    PP.SceneFringeIntensity = bTorn ? 6.f : 1.5f * Dust;
    // Torn signal: alternate crushed and blown frames.
    PP.bOverride_ColorGain = bTorn;
    const float Gain = (FMath::FloorToInt(CineS * 30.f) % 2) ? 1.8f : 0.25f;
    PP.ColorGain = FVector4(Gain, Gain * 0.9f, Gain * 0.8f, 1.f);
}

void USaskartaDroneSequenceSubsystem::RestoreCarrierMesh()
{
    if (FallMesh.IsValid()) FallMesh->SetRelativeTransform(SavedMeshRelative);
    if (ACameraActor* View = FallViewActor.Get())
    {
        if (APlayerController* PC = PlayerController(); PC && PC->GetViewTarget() == View)
        {
            AActor* Target = SavedFallViewTarget.IsValid() ? SavedFallViewTarget.Get() : FallCarrier.Get();
            if (Target) PC->SetViewTarget(Target);
        }
        View->Destroy();
    }
    if (bGroundTimerPaused && GetWorld())
    {
        // EventRunner may have called StartAnimDriver before OnCinematicFinished,
        // replacing the BP GroundTimer. In that case discard the paused old
        // timer instead of reviving a duplicate 30 Hz ground/camera writer.
        bool bReplaced = false;
        if (FallCarrier.IsValid())
        {
            if (const FStructProperty* GroundProperty = FindFProperty<FStructProperty>(
                    FallCarrier->GetClass(), TEXT("GroundTimer")))
            {
                const FTimerHandle* Current = GroundProperty->ContainerPtrToValuePtr<FTimerHandle>(FallCarrier.Get());
                bReplaced = Current && *Current != PausedGroundTimer;
            }
        }
        if (bReplaced) GetWorld()->GetTimerManager().ClearTimer(PausedGroundTimer);
        else GetWorld()->GetTimerManager().UnPauseTimer(PausedGroundTimer);
    }
    PausedGroundTimer.Invalidate();
    bGroundTimerPaused = false;
    FallViewActor.Reset();
    SavedFallViewTarget.Reset();
    FallMesh.Reset();
    FallCarrier.Reset();
    bFallActive = false;
}

void USaskartaDroneSequenceSubsystem::BeginSwarm()
{
    if (!Drones.IsEmpty()) return;
    if (!GetWorld() || !DroneMesh || !SpinClip || !Carrier())
    {
        UE_LOG(LogTemp, Error, TEXT("Drone sequence cannot spawn: world=%d SK_AuxDrone=%d A_AuxDrone_Spin=%d carrier=%d; check cooked /Game/SaskartaGaea/Characters/Drone assets and possession"),
            GetWorld() != nullptr, DroneMesh != nullptr, SpinClip != nullptr, Carrier() != nullptr);
        return;
    }
    ResolveRoadFrame();
    SwarmStartS = -1.f;
    const int32 Count = FMath::Min(DefaultSwarm, HardMaxSwarm);
    for (int32 I = 0; I < Count; ++I)
    {
        FActorSpawnParameters P;
        P.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
        AActor* Drone = I < 2 ? static_cast<AActor*>(GetWorld()->SpawnActor<ACameraActor>(ACameraActor::StaticClass(), FVector::ZeroVector, FRotator::ZeroRotator, P))
                              : GetWorld()->SpawnActor<AActor>(AActor::StaticClass(), FVector::ZeroVector, FRotator::ZeroRotator, P);
        if (!Drone)
        {
            if (I < 2)
            {
                UE_LOG(LogTemp, Error, TEXT("Drone sequence cannot spawn relay camera %d; keeping auxiliary sensors available"), I);
                ClearDrones();
                return;
            }
            continue;
        }
        Drone->SetActorEnableCollision(false);
        USkeletalMeshComponent* Visual = NewObject<USkeletalMeshComponent>(Drone);
        Drone->AddInstanceComponent(Visual);
        if (Drone->GetRootComponent()) Visual->SetupAttachment(Drone->GetRootComponent());
        else Drone->SetRootComponent(Visual);
        Visual->SetSkeletalMesh(DroneMesh);
        Visual->SetCollisionProfileName(TEXT("NoCollision"));
        Visual->SetCastShadow(false);
        Visual->RegisterComponent();
        if (I == 1) Visual->SetRelativeLocation(FVector(0.f, 0.f, 60.f));
        Drone->SetActorLocation(LocalAtCarrier(SaskartaDroneLogic::SwarmOffset(I, 0.f)));
        Visual->PlayAnimation(SpinClip, true);
        if (I < 2)
        {
            if (ACameraActor* Camera = Cast<ACameraActor>(Drone)) Camera->GetCameraComponent()->SetFieldOfView(75.f);
        }
        if (I < 2)
        {
            if (RotorSound)
            {
                UAudioComponent* Loop = UGameplayStatics::SpawnSoundAttached(RotorSound, Visual, NAME_None,
                    FVector::ZeroVector, FRotator::ZeroRotator, EAttachLocation::KeepRelativeOffset,
                    true, 0.9f, I == 0 ? 1.f : 1.06f, 0.f, RotorAttenuation);
                RotorLoops.Add(Loop);
                if (I == 0) RotorLoop = Loop;
            }
            USpotLightComponent* Beam = NewObject<USpotLightComponent>(Drone);
            Drone->AddInstanceComponent(Beam);
            if (Drone->GetRootComponent()) Beam->SetupAttachment(Drone->GetRootComponent());
            Beam->SetIntensityUnits(ELightUnits::Candelas);
            Beam->SetIntensity(0.f);
            Beam->SetAttenuationRadius(4500.f);
            Beam->SetInnerConeAngle(9.f);
            Beam->SetOuterConeAngle(17.f);
            Beam->SetLightColor(FLinearColor(1.f, 0.9f, 0.75f));
            Beam->SetCastShadows(false);
            Beam->SetVisibility(false);
            Beam->RegisterComponent();
            DroneLights.Add(Beam);
            UMaterialInstanceDynamic* DownwashMid = nullptr;
            DownwashFx.Add(MakeDownwash(DownwashMaterial, DownwashPlane, Drone, DownwashMid));
            DownwashMids.Add(DownwashMid);
            Flights[I].Reset(Drone->GetActorLocation());
        }
        Drones.Add(Drone);
    }
    bSwarmActive = !Drones.IsEmpty();
}

void USaskartaDroneSequenceSubsystem::UpdateSwarm(float CineS)
{
    ACharacter* P = Carrier();
    if ((!bSwarmActive && !bDeparting) || CineS < 0.f || !P) return;
    const FVector Feet = P->GetActorLocation() - FVector(0.f, 0.f, P->GetSimpleCollisionHalfHeight());
    const FVector Focus = Feet + FVector(0.f, 0.f, 120.f);
    for (int32 I = bDeparting ? 2 : 0; I < Drones.Num(); ++I)
    {
        AActor* Drone = Drones[I].Get();
        if (!Drone) continue;
        const FVector Want = LocalAtCarrier(SaskartaDroneLogic::SwarmOffset(I, CineS) + SaskartaDroneLogic::HoverDrift(I, CineS));
        if (I < 2)
        {
            Flights[I].Stiffness = 1.f;
            FlyDrone(I, Want, Focus, StepS);
        }
        else Drone->SetActorLocationAndRotation(Want, (Focus - Want).Rotation());
        if (DroneLights.IsValidIndex(I) && DroneLights[I])
        {
            const float Level = bDeparting ? 0.f : SaskartaDroneLogic::ArrivalLight(I, CineS);
            DroneLights[I]->SetVisibility(Level > 0.01f);
            DroneLights[I]->SetIntensity(Level * DroneLightCandela);
            const FVector Aim = LocalAtCarrier(SaskartaDroneLogic::ArrivalLightTarget(I, CineS)) - Drone->GetActorLocation();
            if (!Aim.IsNearlyZero()) DroneLights[I]->SetWorldRotation(Aim.Rotation());
        }
    }
    if (!bDeparting && !bFeedBooted && CineS >= ArrivalBootS && Drones.IsValidIndex(0) && Drones[0].IsValid())
    {
        // The feed boots on the CRT from drone 0, looking down at the carrier.
        bFeedBooted = true;
        AActor* Lead = Drones[0].Get();
        if (USkeletalMeshComponent* Mesh = Lead->FindComponentByClass<USkeletalMeshComponent>()) Mesh->SetVisibility(false);
        ActiveDroneIndex = 0;
        if (APlayerController* PC = PlayerController()) PC->SetViewTarget(Lead);
        StartRelayCut(0, 0.6f);
    }
}

void USaskartaDroneSequenceSubsystem::UpdateDownwash(int32 Index, const FHitResult* Ground, float HeightCm)
{
    if (Index < 0 || Index > 1 || !DownwashFx.IsValidIndex(Index) || !DownwashMids.IsValidIndex(Index)) return;
    UStaticMeshComponent* Fx = DownwashFx[Index];
    UMaterialInstanceDynamic* Mid = DownwashMids[Index];
    if (!IsValid(Fx) || !Mid || !DownwashPlane || !GetWorld()) return;
    if (bHumanEscort)
    {
        PuffStartS[Index] = -1000.f;
        Fx->SetVisibility(false);
        return;
    }
    const float Now = GetWorld()->GetTimeSeconds();
    if (Ground && !Ground->ImpactPoint.ContainsNaN() && !Ground->ImpactNormal.ContainsNaN()
        && SaskartaDroneLogic::CanEmitDownwash(HeightCm, bHumanEscort) && Now >= NextPuffS[Index])
    {
        NextPuffS[Index] = Now + .7f;
        PuffStartS[Index] = Now;
        PuffHeightCm[Index] = HeightCm;
        PuffOrigin[Index] = Ground->ImpactPoint;
        PuffNormal[Index] = Ground->ImpactNormal.GetSafeNormal(UE_SMALL_NUMBER, FVector::UpVector);
        Mid->SetScalarParameterValue(TEXT("CloudVariant"), float((FMath::FloorToInt(Now / .7f) + Index * 3) % 8));
    }
    const SaskartaDroneLogic::FDownwashSample Shape = SaskartaDroneLogic::SampleDownwash(Now - PuffStartS[Index], PuffHeightCm[Index]);
    APlayerController* PC = PlayerController();
    APlayerCameraManager* Camera = PC ? PC->PlayerCameraManager : nullptr;
    if (!Camera || Shape.Opacity <= .001f) { Fx->SetVisibility(false); return; }
    // The puff stays where the rotor first struck the ground; only orientation
    // follows the observer. No camera-centred shell, moving floor, or allocation.
    const FVector Position = PuffOrigin[Index] + PuffNormal[Index] * (12.f + Shape.HeightCm * .45f);
    const FVector ToView = Camera->GetCameraLocation() - Position;
    const float DistanceFade = FMath::Clamp((2500.f - float(ToView.Size())) / 500.f, 0.f, 1.f);
    if (ToView.ContainsNaN() || ToView.IsNearlyZero() || DistanceFade <= 0.f) { Fx->SetVisibility(false); return; }
    const FVector Right = Camera->GetCameraRotation().RotateVector(FVector::RightVector);
    const FQuat Face = FRotationMatrix::MakeFromZX(ToView.GetSafeNormal(), Right).ToQuat();
    const FVector Size = DownwashPlane->GetBoundingBox().GetSize();
    Fx->SetWorldTransform(FTransform(Face, Position, FVector(Shape.WidthCm / Size.X, Shape.HeightCm / Size.Y, 1.f)));
    Mid->SetScalarParameterValue(TEXT("Opacity"), Shape.Opacity * DistanceFade);
    Fx->SetVisibility(true);
}

void USaskartaDroneSequenceSubsystem::FlyDrone(int32 Index, const FVector& WantIn, const FVector& Focus, float Dt)
{
    UWorld* World = GetWorld();
    AActor* Drone = Drones.IsValidIndex(Index) ? Drones[Index].Get() : nullptr;
    if (!World || !Drone || Index < 0 || Index > 1) return;
    FCollisionQueryParams Query(SCENE_QUERY_STAT(SaskartaDroneFlight), false, Carrier());
    for (const TWeakObjectPtr<AActor>& Other : Drones) if (Other.IsValid()) Query.AddIgnoredActor(Other.Get());
    FVector Want = WantIn;
    FHitResult Ground;
    if (World->LineTraceSingleByChannel(Ground, Want + FVector(0.f, 0.f, 500.f), Want - FVector(0.f, 0.f, 3000.f), ECC_Visibility, Query))
    {
        Want.Z = FMath::Max(Want.Z, Ground.ImpactPoint.Z + 150.f);
    }
    SaskartaDroneLogic::FDroneFlight& F = Flights[Index];
    if (Dt <= 0.f) F.Reset(Want);
    else if (!F.bValid) F.Reset(Drone->GetActorLocation());
    const float Heading = (Focus - F.Position).Rotation().Yaw;
    F.Step(Want, Heading, Dt);
    FVector Pos = F.Position;
    const bool bGroundHit = World->LineTraceSingleByChannel(Ground, Pos + FVector(0.f, 0.f, 500.f), Pos - FVector(0.f, 0.f, 600.f), ECC_Visibility, Query);
    if (bGroundHit)
    {
        const float Floor = float(Ground.ImpactPoint.Z) + 120.f;
        if (Pos.Z < Floor)
        {
            Pos.Z = Floor;
            F.Position.Z = Floor;
            F.Velocity.Z = FMath::Max(F.Velocity.Z, 0.0);
        }
    }
    UpdateDownwash(Index, bGroundHit ? &Ground : nullptr, bGroundHit ? float(Pos.Z - Ground.ImpactPoint.Z) : 450.f);
    Drone->SetActorLocationAndRotation(Pos, (Focus - Pos).Rotation());
    if (USkeletalMeshComponent* Visual = Drone->FindComponentByClass<USkeletalMeshComponent>())
    {
        // The camera stays gimballed on the carrier; the body pitches, banks and spins up.
        const FRotator Gust = SaskartaDroneLogic::GustTilt(Index, World->GetTimeSeconds());
        Visual->SetWorldRotation(FRotator(F.PitchDeg + Gust.Pitch, Heading + Gust.Yaw, F.RollDeg + Gust.Roll));
        Visual->SetPlayRate(F.RotorRate);
    }
    if (RotorLoops.IsValidIndex(Index) && RotorLoops[Index])
    {
        const APlayerController* PC = PlayerController();
        const bool bOnCamera = PC && PC->GetViewTarget() == Drone;
        const SaskartaDroneLogic::FRotorMix Mix =
            SaskartaDroneLogic::RotorMix(F.RotorRate, float(F.Velocity.Size()), F.Strain, bOnCamera);
        UAudioComponent* Loop = RotorLoops[Index];
        Loop->SetVolumeMultiplier(Mix.Volume);
        Loop->SetPitchMultiplier(Mix.Pitch * (Index == 0 ? 1.f : 1.06f));
        if (!Loop->IsPlaying()) Loop->Play();
        if (bOnCamera && bDroneFeedActive && WindSound)
        {
            if (!WhooshLoop)
            {
                WhooshLoop = UGameplayStatics::CreateSound2D(this, WindSound, 0.001f, 1.f, 0.f, nullptr, false, false);
                if (WhooshLoop) WhooshLoop->Play();
            }
            if (WhooshLoop)
            {
                const float Speed = float(F.Velocity.Size());
                WhooshLoop->SetVolumeMultiplier(FMath::Max(0.001f, SaskartaDroneLogic::WhooshLevel(Speed, F.Strain)));
                WhooshLoop->SetPitchMultiplier(0.85f + 0.5f * FMath::Clamp(Speed / 1800.f, 0.f, 1.f));
            }
        }
    }
}

void USaskartaDroneSequenceSubsystem::StartRelayCut(int32 FeedIndex, float Duration)
{
    UWorld* World = GetWorld();
    if (!World) return;
    RelayCutFeed = FeedIndex;
    RelayCutStartS = World->GetTimeSeconds();
    RelayCutDurationS = Duration;
    ShowTag(FeedIndex == 0 ? TEXT("FEED 1") : TEXT("FEED 2"), 2.f);
}

void USaskartaDroneSequenceSubsystem::ShowTag(const FString& Text, float Seconds)
{
    UWorld* World = GetWorld();
    if (!World) return;
    TagText = Text;
    TagStartS = World->GetTimeSeconds();
    TagUntilS = TagStartS + Seconds;
    APlayerController* PC = PlayerController();
    if (!TagWidget && PC && PC->IsLocalController())
    {
        TagWidget = CreateWidget<USaskartaFeedTagWidget>(PC, USaskartaFeedTagWidget::StaticClass());
        if (TagWidget) TagWidget->AddToViewport(40);
    }
}

void USaskartaDroneSequenceSubsystem::UpdateRelayCut(double NowS)
{
    if (TagWidget)
    {
        const float Age = float(NowS) - TagStartS;
        const float Remaining = TagUntilS - float(NowS);
        float Opacity = Remaining <= 0.f ? 0.f : FMath::Min(1.f, Remaining / 0.4f);
        if (Age < 0.3f && (FMath::FloorToInt(Age * 20.f) % 2) != 0) Opacity *= 0.35f;
        const float Jitter = (TagText == TEXT("OPTICS FAULT") && Age < 0.5f) ? FMath::Sin(Age * 90.f) * 6.f : 0.f;
        TagWidget->ShowTag(TagText, Opacity, Jitter);
    }
    ACameraActor* Cam = Drones.IsValidIndex(RelayCutFeed) ? Cast<ACameraActor>(Drones[RelayCutFeed].Get()) : nullptr;
    if (!Cam || RelayCutStartS < -100.f) return;
    FPostProcessSettings& PP = Cam->GetCameraComponent()->PostProcessSettings;
    const float Age = float(NowS) - RelayCutStartS;
    if (Age >= RelayCutDurationS)
    {
        PP.bOverride_ColorGain = false;
        PP.bOverride_SceneFringeIntensity = false;
        PP.bOverride_FilmGrainIntensity = false;
        RelayCutStartS = -1000.f;
        return;
    }
    // A CRT relay cut: the new source flickers in, it does not pan.
    const float Gain = SaskartaDroneLogic::RelayFlicker(Age, RelayCutDurationS);
    PP.bOverride_ColorGain = true;
    PP.ColorGain = FVector4(Gain, Gain, Gain, 1.f);
    PP.bOverride_SceneFringeIntensity = true;
    PP.SceneFringeIntensity = 4.f;
    PP.bOverride_FilmGrainIntensity = true;
    PP.FilmGrainIntensity = 0.8f;
}

void USaskartaDroneSequenceSubsystem::SetDroneFeedActive(bool bOn)
{
    if (!bOn) bPendingAuxFallback = false;
    if (bDroneFeedActive == bOn) return;
    bDroneFeedActive = bOn;
    if (bOn)
    {
        if (Drones.IsEmpty()) BeginSwarm();
        if (!Drones.IsValidIndex(1) || !Cast<ACameraActor>(Drones[0].Get()) || !Cast<ACameraActor>(Drones[1].Get()))
        {
            QueueDroneFailure(TEXT("missing one of two relay cameras after swarm spawn"));
            return;
        }
        // The cinematic still owns the player view until its last frame.
        if (!Runner.IsValid() || !Runner->IsCinematicActive()) HandoverToDrone(0.f);
    }
    else
    {
        ClearDrones();
    }
}

void USaskartaDroneSequenceSubsystem::QueueDroneFailure(const TCHAR* Reason)
{
    UE_LOG(LogTemp, Error, TEXT("DroneCam activation failed: %s. Restoring AuxSensors on the next runtime step."), Reason);
    bDroneFeedActive = false;
    ClearDrones();
    // Defer mode mutation: RestoreFromSave broadcasts while iterating ActiveModes.
    bPendingAuxFallback = Runner.IsValid() && Runner->IsPresentationModeActive(DroneMode);
}

void USaskartaDroneSequenceSubsystem::HandoverToDrone(float BlendSeconds)
{
    AActor* Lead = GetDroneViewTarget();
    APlayerController* PC = PlayerController();
    if (!Cast<ACameraActor>(Lead) || !Drones.IsValidIndex(1) || !Cast<ACameraActor>(Drones[1].Get()) || !PC)
    {
        QueueDroneFailure(TEXT("lead camera or player controller unavailable at handback"));
        return;
    }
    if (USkeletalMeshComponent* Mesh = Lead->FindComponentByClass<USkeletalMeshComponent>()) Mesh->SetVisibility(false);
    for (USpotLightComponent* Beam : DroneLights) if (Beam) Beam->SetVisibility(false);
    if (!bFeedBooted)
    {
        // A skipped arrival still boots the feed like a relay.
        bFeedBooted = true;
        ActiveDroneIndex = 0;
        StartRelayCut(0, 0.6f);
    }
    bSwarmActive = false;
    bDeparting = true;
    DepartureStartS = GetWorld() ? GetWorld()->GetTimeSeconds() : -1.f;
    bDroneFeedActive = true;
    UpdateFollow(0.f);
    // A skipped B1 may bypass its earlier Aux-off cue. A valid relay handback
    // must display the clean scene feed, not leave point-cloud ranging on top.
    if (bAuxActive)
    {
        if (Runner.IsValid()) Runner->SetPresentationMode(AuxMode, false);
        else SetAuxActive(false);
    }
    if (PC->GetViewTarget() != Lead)
    {
        if (Runner.IsValid()) Runner->SetCollisionSafeViewTarget(PC, Lead, FMath::Max(0.f, BlendSeconds));
        else PC->SetViewTarget(Lead);
    }
    for (int32 I = 2; I < Drones.Num(); ++I)
    {
        if (AActor* Other = Drones[I].Get()) Other->SetLifeSpan(4.f);
    }
}

bool USaskartaDroneSequenceSubsystem::RestoreHumanEscort(ACharacter* StrandedCarrier)
{
    if (!IsValid(StrandedCarrier) || !GetWorld() || StrandedCarrier->GetWorld() != GetWorld()) return false;
    StopSequence();
    BeginHumanEscort(StrandedCarrier);
    if (bHumanEscort) UpdateHumanEscort(0.f); // place both immediately at their own anchors
    return bHumanEscort;
}

void USaskartaDroneSequenceSubsystem::BeginHumanEscort(ACharacter* CarrierOverride)
{
    ACharacter* Wreck = CarrierOverride ? CarrierOverride : Carrier();
    if (!Wreck)
    {
        StopSequence();
        return;
    }
    const bool bAlreadySpawned = Drones.IsValidIndex(1) && Drones[0].IsValid() && Drones[1].IsValid();
    if (!bAlreadySpawned)
    {
        ClearDrones();
        WreckCarrier = Wreck; // BeginSwarm must not mistake an already-possessed elder for the carrier.
        BeginSwarm();
    }
    bHumanEscort = Drones.IsValidIndex(1) && Drones[0].IsValid() && Drones[1].IsValid();
    bEndingDroneGrounded = false;
    if (bHumanEscort)
    {
        WreckCarrier = Wreck;
        WreckPose = Wreck->GetActorTransform();
    }
    StopRelay(false); // stop the damaged carrier feed; preserve the physical escort pair
    if (!bHumanEscort) return;

    const float Now = GetWorld() ? GetWorld()->GetTimeSeconds() : 0.f;
    for (int32 I = 0; I < 2; ++I)
    {
        AActor* Drone = Drones[I].Get();
        if (USkeletalMeshComponent* Mesh = Drone->FindComponentByClass<USkeletalMeshComponent>())
            Mesh->SetVisibility(true); // the former feed camera must be visible in exterior ending shots
        if (DroneLights.IsValidIndex(I) && DroneLights[I]) DroneLights[I]->SetVisibility(false);
        if (!bAlreadySpawned)
        {
            const FVector At = SaskartaDroneLogic::HumanEscortTarget(I, WreckPose, WreckPose, Now);
            Drone->SetActorLocation(At);
            Flights[I].Reset(At);
        }
    }
    if (APlayerController* PC = PlayerController(); PC &&
        (PC->GetViewTarget() == Drones[0].Get() || PC->GetViewTarget() == Drones[1].Get()))
    {
        PC->SetViewTarget(Wreck); // the sequence camera takes over on its first cut
    }
    UE_LOG(LogTemp, Log, TEXT("CIN_19: preserving two drones for the human walk; one follows Samyor, one stays at the carrier"));
}

void USaskartaDroneSequenceSubsystem::GroundEscortDroneAtRadioPost()
{
    if (!bHumanEscort || !Drones.IsValidIndex(0) || !Drones[0].IsValid() || !GetWorld()) return;
    ACharacter* Human = PlayerController() ? Cast<ACharacter>(PlayerController()->GetPawn()) : nullptr;
    if (!Human) return;

    // This level anchor is also the CIN_24/CIN_25 camera rest point.
    bool bFoundRest = false;
    for (TActorIterator<AActor> It(GetWorld()); It; ++It)
    {
        if (It->ActorHasTag(FName(TEXT("Saskarta.DroneRest"))))
        {
            EndingDroneRest = It->GetActorLocation();
            bFoundRest = true;
            break;
        }
    }
    if (!bFoundRest)
    {
        EndingDroneRest = Human->GetActorLocation() +
            Human->GetActorRotation().RotateVector(FVector(-170.f, 95.f, -40.f));
        FHitResult Ground;
        FCollisionQueryParams Query(SCENE_QUERY_STAT(SaskartaEndingDroneRest), false, Human);
        if (GetWorld()->LineTraceSingleByChannel(Ground, EndingDroneRest + FVector(0, 0, 400),
            EndingDroneRest - FVector(0, 0, 800), ECC_Visibility, Query))
        {
            EndingDroneRest.Z = Ground.ImpactPoint.Z + 32.f;
        }
        UE_LOG(LogTemp, Warning, TEXT("CIN_24: Saskarta.DroneRest anchor missing; using traced fallback"));
    }
    bEndingDroneGrounded = true;
    if (AActor* Drone = Drones[0].Get())
    {
        Drone->SetActorLocation(EndingDroneRest);
        Flights[0].Reset(EndingDroneRest);
        // The sequence camera looks through this drone; its body must not block its own lens.
        if (USkeletalMeshComponent* Mesh = Drone->FindComponentByClass<USkeletalMeshComponent>())
            Mesh->SetVisibility(false);
    }
    if (RotorLoops.IsValidIndex(0) && RotorLoops[0]) RotorLoops[0]->Stop();
}

void USaskartaDroneSequenceSubsystem::UpdateHumanEscort(float Dt)
{
    APlayerController* PC = PlayerController();
    ACharacter* Human = PC ? Cast<ACharacter>(PC->GetPawn()) : nullptr;
    if (!Human || Human == WreckCarrier.Get() || !Drones.IsValidIndex(1) ||
        !Drones[0].IsValid() || !Drones[1].IsValid()) return;
    const float Now = GetWorld() ? GetWorld()->GetTimeSeconds() : 0.f;
    const FTransform HumanPose = Human->GetActorTransform();
    const FVector HumanFocus = HumanPose.GetLocation() + FVector(0.f, 0.f, 40.f);
    FCollisionQueryParams Query(SCENE_QUERY_STAT(SaskartaHumanDroneCamera), false, Human);
    // The parked carrier is a camera obstacle, including while the elder walks beside it.
    for (const TWeakObjectPtr<AActor>& Drone : Drones) if (Drone.IsValid()) Query.AddIgnoredActor(Drone.Get());
    for (int32 I = 0; I < 2; ++I)
    {
        FVector Want = SaskartaDroneLogic::HumanEscortTarget(I, HumanPose, WreckPose, Now);
        const FVector Focus = I == 0 ? HumanFocus : WreckPose.GetLocation() + FVector(0.f, 0.f, 90.f);
        if (I == 0)
        {
            // Look input changes where the drone physically flies, rather than
            // rotating a separate third-person spring arm around the traveller.
            const FRotator Look = PC->GetControlRotation();
            const float Pitch = FMath::Clamp(float(FRotator::NormalizeAxis(Look.Pitch)), -35.f, -7.f);
            Want = Focus + FRotator(0.f, Look.Yaw, 0.f).RotateVector(
                FVector(-420.f, 60.f, -424.f * FMath::Tan(FMath::DegreesToRadians(Pitch))))
                + SaskartaDroneLogic::HoverDrift(0, Now) * 0.25f;
            FHitResult Hit;
            if (GetWorld()->SweepSingleByChannel(Hit, Focus, Want, FQuat::Identity, ECC_Camera,
                FCollisionShape::MakeSphere(24.f), Query))
                Want = Hit.Location + Hit.Normal * 12.f;
        }
        const FVector PreviousEye = Drones[I]->GetActorLocation();
        if (I == 0 && Runner.IsValid()) Want = Runner->ConstrainCarrierCameraPath(PreviousEye, Want);
        Flights[I].Stiffness = I == 0 ? 1.35f : 0.8f;
        FlyDrone(I, Want, Focus, Dt);
        if (I == 0)
        {
            AActor* Eye = Drones[0].Get();
            FHitResult Hit;
            if (GetWorld()->SweepSingleByChannel(Hit, Focus, Eye->GetActorLocation(), FQuat::Identity,
                ECC_Camera, FCollisionShape::MakeSphere(24.f), Query))
            {
                const FVector Safe = Hit.Location + Hit.Normal * 12.f;
                Flights[0].Position = Safe;
                Flights[0].Velocity = FVector::ZeroVector;
                Eye->SetActorLocationAndRotation(Safe, (Focus - Safe).Rotation());
            }
            if (Runner.IsValid())
            {
                const FVector Safe = Runner->ConstrainCarrierCameraPath(PreviousEye, Eye->GetActorLocation());
                if (!Safe.Equals(Eye->GetActorLocation(), 0.01))
                {
                    Flights[0].Position = Safe;
                    Flights[0].Velocity = FVector::ZeroVector;
                    Eye->SetActorLocationAndRotation(Safe, (Focus - Safe).Rotation());
                }
            }
            const bool bViewing = PC->GetViewTarget() == Eye;
            if (USkeletalMeshComponent* Mesh = Eye->FindComponentByClass<USkeletalMeshComponent>())
                Mesh->SetVisibility(!bViewing);
            if (Runner.IsValid() && !Runner->IsCinematicActive() && Runner->GetFlowState() == FName(TEXT("Human"))
                && PC->GetViewTarget() == Human)
                Runner->SetCollisionSafeViewTarget(PC, Eye, 0.6f);
        }
    }
}

void USaskartaDroneSequenceSubsystem::UpdateFollow(float Dt)
{
    ACharacter* P = Carrier();
    UWorld* World = GetWorld();
    if (!Drones.IsValidIndex(1) || !Drones[0].IsValid() || !Drones[1].IsValid() || !P || !World) return;
    DesiredOrbitYawDeg = SaskartaDroneLogic::RecenterYaw(
        DesiredOrbitYawDeg, World->GetTimeSeconds() - LastLookS, Dt);
    // Mouse look moves the active drone along its arc (lagged); each drone owns one 180-degree side.
    OrbitYawDeg = SaskartaDroneLogic::AdvanceLaggedYaw(OrbitYawDeg, DesiredOrbitYawDeg, Dt);
    OrbitPitchDeg = SaskartaDroneLogic::AdvanceLaggedPitch(OrbitPitchDeg, DesiredOrbitPitchDeg, Dt);
    const int32 Feed = SaskartaDroneLogic::AdvanceFeedSwitch(ActiveDroneIndex, OrbitYawDeg, Dt, FeedSwitchWaitS);
    const FVector Feet = P->GetActorLocation() - FVector(0.f, 0.f, P->GetSimpleCollisionHalfHeight());
    const FVector Focus = Feet + FVector(0.f, 0.f, 120.f);
    FCollisionQueryParams Query(SCENE_QUERY_STAT(SaskartaDroneCamera), false, P);
    for (const TWeakObjectPtr<AActor>& Drone : Drones) if (Drone.IsValid()) Query.AddIgnoredActor(Drone.Get());
    const float Now = World->GetTimeSeconds();
    for (int32 I = 0; I < 2; ++I)
    {
        const float StationYaw = SaskartaDroneLogic::StationYawForDrone(I, ActiveDroneIndex, OrbitYawDeg);
        FVector Want = LocalAtCarrier(SaskartaDroneLogic::FollowOffset(StationYaw, OrbitPitchDeg))
            + SaskartaDroneLogic::HoverDrift(I, Now) * (I == ActiveDroneIndex ? 0.7f : 1.f);
        if (RoadSpline.IsValid())
        {
            const FVector Nearest = RoadSpline->FindLocationClosestToWorldLocation(Want, ESplineCoordinateSpace::World);
            const FVector Side(Want.X - Nearest.X, Want.Y - Nearest.Y, 0.f);
            if (Side.SizeSquared() > FMath::Square(MaxRoadLateralCm))
            {
                const FVector Bounded = Side.GetClampedToMaxSize(MaxRoadLateralCm);
                Want.X = Nearest.X + Bounded.X;
                Want.Y = Nearest.Y + Bounded.Y;
            }
        }
        FHitResult Hit;
        if (World->SweepSingleByChannel(Hit, Focus, Want, FQuat::Identity, ECC_Camera,
            FCollisionShape::MakeSphere(30.f), Query))
        {
            Want = Hit.Location + Hit.Normal * 15.f;
        }
        Want = Focus + (Want - Focus).GetClampedToMaxSize(MaxEyeDistanceCm);
        // The feed drone flies tight so the view keeps up with the look; the other holds station softer.
        Flights[I].Stiffness = I == ActiveDroneIndex ? 1.8f : 1.2f;
        FlyDrone(I, Want, Focus, Dt);
        AActor* Drone = Drones[I].Get();
        FVector Flown = Focus + (Drone->GetActorLocation() - Focus).GetClampedToMaxSize(MaxEyeDistanceCm);
        if (World->SweepSingleByChannel(Hit, Focus, Flown, FQuat::Identity, ECC_Camera,
            FCollisionShape::MakeSphere(30.f), Query))
        {
            Flown = Hit.Location + Hit.Normal * 15.f;
        }
        if (!Flown.Equals(Drone->GetActorLocation(), 0.1f))
        {
            Flights[I].Position = Flown;
            Drone->SetActorLocationAndRotation(Flown, (Focus - Flown).Rotation());
        }
    }
    if (Feed != ActiveDroneIndex)
    {
        // The other drone already holds station on that side: a hard relay cut, not a pan.
        AActor* Old = GetDroneViewTarget();
        if (USkeletalMeshComponent* Mesh = Old->FindComponentByClass<USkeletalMeshComponent>()) Mesh->SetVisibility(true);
        ActiveDroneIndex = Feed;
        AActor* New = GetDroneViewTarget();
        if (USkeletalMeshComponent* Mesh = New->FindComponentByClass<USkeletalMeshComponent>()) Mesh->SetVisibility(false);
        if (APlayerController* PC = PlayerController())
        {
            if (PC->GetViewTarget() == Old) PC->SetViewTarget(New);
        }
        StartRelayCut(Feed, 0.22f);
    }
}

void USaskartaDroneSequenceSubsystem::Step()
{
    UWorld* World = GetWorld();
    if (!World || !Runner.IsValid()) return;
    const FName Flow = Runner->GetFlowState();
    if (bPendingAuxFallback)
    {
        bPendingAuxFallback = false;
        if (Flow != FName(TEXT("Title")) && Flow != FName(TEXT("Human")))
        {
            Runner->SetPresentationMode(AuxMode, true);
            Runner->SetPresentationMode(DroneMode, false);
        }
    }
    if (Flow == FName(TEXT("Title")) || (Flow == FName(TEXT("End")) && !bEndingDroneGrounded))
    {
        if (bAuxActive || bDroneFeedActive || bFallActive || bHumanEscort || !Drones.IsEmpty())
        {
            bHumanEscort = false;
            StopSequence();
        }
        return;
    }
    if (bHumanEscort) return; // CIN_19 pauses the pair; Human/Transmit movement runs per frame.
    if (Flow == FName(TEXT("Human")))
    {
        if (bAuxActive || bDroneFeedActive || bFallActive || !Drones.IsEmpty()) StopSequence();
        return;
    }
    if (!Runner->IsCinematicActive() && (bFallActive || bSwarmPending || bSwarmActive))
    {
        RestoreCarrierMesh();
        bSwarmPending = false;
        bSwarmActive = false;
        if (!bDroneFeedActive) ClearDrones();
    }
    if (bAuxActive || bDroneFeedActive || bSwarmActive || bSwarmPending) ResolveRoadFrame();
    if (bFallActive)
    {
        const float T = Runner->GetCinematicPlaybackSeconds();
        if (T >= 0.f) UpdateFall(T);
    }
    bArrivalDriving = Runner->IsCinematicActive() && Runner->GetActiveCinematicId() == SwarmCine &&
        Runner->GetCinematicPlaybackSeconds() >= 0.f && Runner->GetCinematicPlaybackSeconds() < ArrivalEndS;
    if (bSwarmPending && Runner->GetCinematicPlaybackSeconds() >= 0.f)
    {
        bSwarmPending = false;
        BeginSwarm();
    }
    if (bSwarmActive)
    {
        const float T = Runner->GetCinematicPlaybackSeconds();
        if (T >= 0.f) UpdateSwarm(T);
    }
    if (bDeparting && DepartureStartS >= 0.f)
    {
        const float Age = World->GetTimeSeconds() - DepartureStartS;
        if (Age <= SwarmDepartureS) UpdateSwarm(SwarmHandoverS + Age);
        else bDeparting = false;
    }
    if (bDroneFeedActive && !Runner->IsCinematicActive())
    {
        if (!Drones.IsValidIndex(1) || !Drones[0].IsValid() || !Drones[1].IsValid())
        {
            QueueDroneFailure(TEXT("one of the two relay actors was lost during driving"));
            return;
        }
        // Look and follow run per frame in HandlePreActorTick.
    }
    if (bAuxActive)
    {
        if (!AuxMid || !AuxVolume.IsValid()) BindAuxMaterial();
    }
    UpdateAuxMaterial(World->GetTimeSeconds());
    UpdateRelayCut(World->GetTimeSeconds());
}

void USaskartaDroneSequenceSubsystem::ClearDrones()
{
    APlayerController* PC = PlayerController();
    bool bViewingRelay = false;
    if (PC)
    {
        for (int32 I = 0; I < FMath::Min(2, Drones.Num()); ++I)
        {
            bViewingRelay |= Drones[I].Get() == PC->GetViewTarget();
        }
    }
    if (PC && bViewingRelay)
    {
        if (APawn* Pawn = PC->GetPawn()) PC->SetViewTarget(Pawn);
    }
    if (RotorLoop) RotorLoop->Stop();
    RotorLoop = nullptr;
    for (UAudioComponent* Loop : RotorLoops) if (Loop) Loop->Stop();
    RotorLoops.Reset();
    if (WhooshLoop) WhooshLoop->Stop();
    WhooshLoop = nullptr;
    DroneLights.Reset();
    DownwashFx.Reset();
    DownwashMids.Reset();
    for (int32 I = 0; I < 2; ++I) { NextPuffS[I] = 0.f; PuffStartS[I] = -1000.f; }
    for (SaskartaDroneLogic::FDroneFlight& F : Flights) F.bValid = false;
    RelayCutStartS = -1000.f;
    for (TWeakObjectPtr<AActor>& Drone : Drones) if (Drone.IsValid()) Drone->Destroy();
    Drones.Reset();
    bHumanEscort = false;
    bEndingDroneGrounded = false;
    WreckCarrier.Reset();
    WreckPose = FTransform::Identity;
    bSwarmActive = false;
    bSwarmPending = false;
    bDeparting = false;
    ActiveDroneIndex = 0;
    OrbitYawDeg = DesiredOrbitYawDeg = 0.f;
    bLookBaseline = false;
    OrbitPitchDeg = DesiredOrbitPitchDeg = -11.27f;
    FeedSwitchWaitS = 0.f;
}

void USaskartaDroneSequenceSubsystem::StopSequence()
{
    bHumanEscort = false;
    bEndingDroneGrounded = false;
    StopRelay(true);
}

void USaskartaDroneSequenceSubsystem::StopRelay(bool bDestroyDrones)
{
    bPendingAuxFallback = false;
    for (UStaticMeshComponent* Fx : DownwashFx) if (IsValid(Fx)) Fx->SetVisibility(false);
    for (float& Start : PuffStartS) Start = -1000.f;
    UWorld* World = GetWorld();
    if (World)
    {
        World->GetTimerManager().ClearTimer(PingTimer);
        for (FTimerHandle& H : EchoTimers) World->GetTimerManager().ClearTimer(H);
    }
    bAuxActive = false;
    bDroneFeedActive = false;
    bArrivalDriving = false;
    if (TagWidget)
    {
        TagWidget->RemoveFromParent();
        TagWidget = nullptr;
    }
    TagUntilS = -1000.f;
    if (WindLoop) WindLoop->Stop();
    WindLoop = nullptr;
    if (WhooshLoop) WhooshLoop->Stop();
    WhooshLoop = nullptr;
    if (AuxVolume.IsValid() && AuxVolume->Settings.WeightedBlendables.Array.IsValidIndex(AuxBlendIndex))
    {
        AuxVolume->Settings.WeightedBlendables.Array[AuxBlendIndex].Weight = 0.f;
    }
    RestoreCarrierMesh();
    if (bDestroyDrones) ClearDrones();
}
