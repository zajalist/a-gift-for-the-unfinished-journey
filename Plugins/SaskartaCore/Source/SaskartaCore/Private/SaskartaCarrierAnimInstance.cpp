// USaskartaCarrierAnimInstance and its proxy (task CARRIERANIM). See the headers.
//
// Axis conventions used below (all derived from Tuning.MeshForward F and MeshUp U):
//   R = U x F is the carrier's right (mesh -X for the imported rig).
//   A rotation of +a about U turns the nose right (yaw).
//   A rotation of +a about R turns the nose DOWN and rolls a wheel forward, so a
//   nose-up pitch p is a rotation of -p about R.
//   A rotation of +a about F lifts the right side, so a right-side-down roll r is a
//   rotation of -r about F.
// Rotations of a bone "about its own axis" use that mesh axis expressed in the bone's
// reference frame, applied as Local * Delta, so they follow the bone's parents (a
// wheel keeps spinning about its axle while the steer bone above it turns).

#include "SaskartaCarrierAnimInstance.h"

#include "Animation/AnimSequence.h"
#include "Animation/AnimSequenceBase.h"
#include "Animation/BlendSpace.h"
#include "AnimationRuntime.h"
#include "CollisionQueryParams.h"
#include "Components/SkeletalMeshComponent.h"
#include "Engine/HitResult.h"
#include "Engine/SkeletalMesh.h"
#include "Engine/World.h"
#include "GameFramework/Actor.h"
#include "SaskartaCarrierAnimProxy.h"

// ─── Proxy ───────────────────────────────────────────────────────────────────

FSaskartaCarrierAnimProxy::FSaskartaCarrierAnimProxy(UAnimInstance* InAnimInstance)
    : FAnimInstanceProxy(InAnimInstance)
{
}

uint32 FSaskartaCarrierAnimProxy::BoneKey(const FSaskartaCarrierAnimTuning& T)
{
    uint32 H = 0;
    for (const FName& N : { T.BoneBody, T.BoneMast, T.BoneEyeL, T.BoneEyeR, T.BoneSteerFL, T.BoneSteerFR,
        T.BoneWheelFL, T.BoneWheelFR, T.BoneWheelRL, T.BoneWheelRR, T.BoneCoupler, T.BoneCapsuleRoot,
        T.BoneCapsuleLining, T.BoneCapsuleWheelL, T.BoneCapsuleWheelR })
    {
        H = HashCombine(H, GetTypeHash(N));
    }
    H = HashCombine(H, GetTypeHash(T.MeshForward));
    H = HashCombine(H, GetTypeHash(T.MeshUp));
    return H;
}

void FSaskartaCarrierAnimProxy::PreUpdate(UAnimInstance* InAnimInstance, float DeltaSeconds)
{
    FAnimInstanceProxy::PreUpdate(InAnimInstance, DeltaSeconds);

    const USaskartaCarrierAnimInstance* Instance = Cast<USaskartaCarrierAnimInstance>(InAnimInstance);
    if (!Instance)
    {
        return;
    }
    Inputs = Instance->Inputs;
    Tuning = Instance->Tuning;
    bWheelSpinLocked = Instance->bWheelSpinLocked;
    State = Instance->CurrentState;
    const uint32 Key = BoneKey(Tuning);
    if (Key != CachedBoneKey)
    {
        bBonesCached = false;
    }

    if (Instance->PlaySerial != SeenPlaySerial)
    {
        SeenPlaySerial = Instance->PlaySerial;
        if (CurrentPlayer.Asset && Tuning.StateBlendTime > 0.f)
        {
            PreviousPlayer = MoveTemp(CurrentPlayer);
            BlendElapsed = 0.f;
            BlendDuration = Tuning.StateBlendTime;
        }
        else
        {
            PreviousPlayer = FPlayer();
            BlendElapsed = 0.f;
            BlendDuration = 0.f;
        }
        CurrentPlayer = FPlayer();
        CurrentPlayer.Asset = Instance->CurrentAsset.Get();
        CurrentPlayer.bLoop = Instance->bLoopRequested;
    }
    CurrentPlayer.Rate = Instance->PlayRate;
    CurrentPlayer.BlendPosition = Instance->BlendInput;

    // The hitch: an explicit ResetHitch, then the owner's own motion this frame.
    if (Instance->HitchResetSerial != SeenHitchResetSerial)
    {
        SeenHitchResetSerial = Instance->HitchResetSerial;
        bHitchResetPending = true;
    }
    bOwnerMotionValid = false;
    const AActor* Owner = Instance->GetOwningActor();
    if (Owner && Tuning.bHitchFromOwnerMotion)
    {
        const FVector Location = Owner->GetActorLocation();
        const FVector Forward = Owner->GetActorForwardVector().GetSafeNormal2D();
        const float YawDeg = static_cast<float>(Owner->GetActorRotation().Yaw);
        if (bHaveOwnerPose && DeltaSeconds > UE_KINDA_SMALL_NUMBER)
        {
            const FVector Step = Location - LastOwnerLocation;
            const float Distance = static_cast<float>(Step.Size2D());
            const float YawStepDeg = FRotator::NormalizeAxis(YawDeg - LastOwnerYawDeg);
            if (SaskartaCarrierMath::IsTeleportStep(Distance, FMath::DegreesToRadians(YawStepDeg), DeltaSeconds,
                Tuning.TeleportDistance, Tuning.TeleportSpeed, FMath::DegreesToRadians(Tuning.TeleportYawRateDeg)))
            {
                // A respawn, a checkpoint or a sequence moved the carrier: straight, and no hitch motion this frame.
                bHitchResetPending = true;
                OwnerSpeed = 0.f;
                OwnerYawRateDeg = 0.f;
                bOwnerMotionValid = true;
            }
            else
            {
                OwnerSpeed = static_cast<float>(FVector::DotProduct(Step, Forward)) / DeltaSeconds;
                OwnerYawRateDeg = YawStepDeg / DeltaSeconds;
                bOwnerMotionValid = true;
            }
        }
        if (DeltaSeconds > UE_KINDA_SMALL_NUMBER || !bHaveOwnerPose)
        {
            LastOwnerLocation = Location;
            LastOwnerYawDeg = YawDeg;
            bHaveOwnerPose = true;
        }
    }
    else
    {
        bHaveOwnerPose = false;
    }
}

void FSaskartaCarrierAnimProxy::Update(float DeltaSeconds)
{
    const float Dt = FMath::Clamp(DeltaSeconds, 0.f, SaskartaCarrierMath::MaxFrameS);
    CacheBoneRefs(GetRequiredBones());

    AdvancePlayer(CurrentPlayer, Dt);
    if (PreviousPlayer.Asset)
    {
        AdvancePlayer(PreviousPlayer, Dt);
        BlendElapsed += Dt;
        if (BlendElapsed >= BlendDuration)
        {
            PreviousPlayer = FPlayer();
        }
    }

    if (Dt > 0.f)
    {
        StepDynamics(Dt);
    }
}

bool FSaskartaCarrierAnimProxy::Evaluate(FPoseContext& Output)
{
    // 1. The clip, crossfaded from the previous one.
    if (!EvaluatePlayer(CurrentPlayer, Output))
    {
        Output.ResetToRefPose();
    }
    if (PreviousPlayer.Asset && BlendDuration > 0.f && BlendElapsed < BlendDuration)
    {
        FPoseContext PreviousPose(Output);
        if (EvaluatePlayer(PreviousPlayer, PreviousPose))
        {
            const float Alpha = FMath::Clamp(BlendElapsed / BlendDuration, 0.f, 1.f);
            FAnimationPoseData OutData(Output);
            const FAnimationPoseData PreviousData(PreviousPose);
            FAnimationRuntime::BlendTwoPosesTogetherInPlace(OutData, PreviousData, Alpha);
        }
    }

    // 2. The procedural bones on top.
    if (CacheBoneRefs(Output.Pose.GetBoneContainer()))
    {
        ApplyBones(Output.Pose);
    }
    return true;
}

void FSaskartaCarrierAnimProxy::PostUpdate(UAnimInstance* InAnimInstance) const
{
    FAnimInstanceProxy::PostUpdate(InAnimInstance);

    USaskartaCarrierAnimInstance* Instance = Cast<USaskartaCarrierAnimInstance>(InAnimInstance);
    if (!Instance)
    {
        return;
    }
    // A PlayState since PreUpdate: keep the fresh values it set.
    if (Instance->PlaySerial == SeenPlaySerial)
    {
        Instance->OutClipTime = CurrentPlayer.Time;
        Instance->OutClipLength = CurrentPlayer.Length;
        Instance->bOutClipFinished = CurrentPlayer.bFinished;
    }
    Instance->OutBodyPitchDeg = OutBodyPitchDeg;
    Instance->OutBodyRollDeg = OutBodyRollDeg;
    Instance->OutBodyHeaveCm = OutBounceCm;
    Instance->OutHitchDeg = OutHitchDeg;
    Instance->OutHitchLimitDeg = OutHitchLimitDeg;
}

float FSaskartaCarrierAnimProxy::HitchLimit()
{
    const FSaskartaCarrierAnimTuning& T = Tuning;
    const float UserMax = FMath::DegreesToRadians(FMath::Clamp(T.MaxHitchDeg, 0.f, 89.f));
    const float Clearance = FMath::DegreesToRadians(FMath::Max(0.f, T.HitchClearanceDeg));
    if (UserMax != LimitKeyUserMax || Clearance != LimitKeyClearance || T.bHitchFootprintLimit != bLimitKeyFootprint
        || T.CarrierFootprint != LimitCarrierFootprint || T.TrailerFootprint != LimitTrailerFootprint)
    {
        LimitKeyUserMax = UserMax;
        LimitKeyClearance = Clearance;
        bLimitKeyFootprint = T.bHitchFootprintLimit;
        LimitCarrierFootprint = T.CarrierFootprint;
        LimitTrailerFootprint = T.TrailerFootprint;
        HitchLimitRad = T.bHitchFootprintLimit
            ? SaskartaCarrierMath::SafeHitchAngle(T.CarrierFootprint.GetData(), T.CarrierFootprint.Num(),
                T.TrailerFootprint.GetData(), T.TrailerFootprint.Num(), Clearance, UserMax)
            : UserMax;
    }
    return HitchLimitRad;
}

void FSaskartaCarrierAnimProxy::ResetTrailer()
{
    HitchRad = 0.f;
    Sway = SaskartaCarrierMath::FSpring();
    TrailerPitch = SaskartaCarrierMath::FSpring();
    TrailerRoll = SaskartaCarrierMath::FSpring();
    TrailerBob = SaskartaCarrierMath::FSpring();
    bHaveTrailerMean = false;
    LastBobV = 0.f;
    bHaveWheelMean = false;
}

bool FSaskartaCarrierAnimProxy::IsOff() const
{
    return Tuning.OffStates.Contains(State);
}

bool FSaskartaCarrierAnimProxy::CacheBoneRefs(const FBoneContainer& Container)
{
    if (!Container.IsValid())
    {
        return false;
    }
    const FReferenceSkeleton& Ref = Container.GetReferenceSkeleton();
    if (bBonesCached && CachedSerial == Container.GetSerialNumber() && CachedSkeleton == &Ref)
    {
        return true;
    }

    MeshForward = Tuning.MeshForward.GetSafeNormal();
    if (MeshForward.IsNearlyZero())
    {
        MeshForward = FVector(0.f, 1.f, 0.f);
    }
    MeshUp = Tuning.MeshUp.GetSafeNormal();
    if (MeshUp.IsNearlyZero() || FMath::Abs(FVector::DotProduct(MeshUp, MeshForward)) > 0.99)
    {
        MeshUp = FVector::UpVector;
    }
    MeshRight = FVector::CrossProduct(MeshUp, MeshForward).GetSafeNormal();
    MeshUp = FVector::CrossProduct(MeshForward, MeshRight).GetSafeNormal(); // orthonormal

    const FName Names[BoneCount] = {
        Tuning.BoneBody, Tuning.BoneMast, Tuning.BoneEyeL, Tuning.BoneEyeR, Tuning.BoneSteerFL, Tuning.BoneSteerFR,
        Tuning.BoneWheelFL, Tuning.BoneWheelFR, Tuning.BoneWheelRL, Tuning.BoneWheelRR, Tuning.BoneCoupler,
        Tuning.BoneCapsuleRoot, Tuning.BoneCapsuleLining, Tuning.BoneCapsuleWheelL, Tuning.BoneCapsuleWheelR };
    bool bFound[BoneCount];
    for (int32 I = 0; I < BoneCount; ++I)
    {
        FBone& B = Bones[I];
        B = FBone();
        bFound[I] = false;
        const int32 MeshIndex = Names[I].IsNone() ? INDEX_NONE : Ref.FindBoneIndex(Names[I]);
        if (MeshIndex == INDEX_NONE)
        {
            continue;
        }
        bFound[I] = true;
        B.RefCS = FAnimationRuntime::GetComponentSpaceTransformRefPose(Ref, MeshIndex);
        const int32 ParentIndex = Ref.GetParentIndex(MeshIndex);
        if (ParentIndex != INDEX_NONE)
        {
            B.ParentRefCS = FAnimationRuntime::GetComponentSpaceTransformRefPose(Ref, ParentIndex);
        }
        B.Compact = Container.MakeCompactPoseIndex(FMeshPoseBoneIndex(MeshIndex));
        B.bValid = B.Compact.IsValid();
        const FQuat Q = B.RefCS.GetRotation();
        B.AxisForward = Q.UnrotateVector(MeshForward).GetSafeNormal();
        B.AxisUp = Q.UnrotateVector(MeshUp).GetSafeNormal();
        B.AxisRight = Q.UnrotateVector(MeshRight).GetSafeNormal();
    }

    auto Pos = [this](int32 I) { return Bones[I].RefCS.GetTranslation(); };
    auto Along = [](const FVector& V, const FVector& Axis) { return static_cast<float>(FVector::DotProduct(V, Axis)); };

    // Carrier wheels: each one's side of the centre line, and the wheelbase.
    const int32 Wheels[4] = { WheelFL, WheelFR, WheelRL, WheelRR };
    float MeanLateral = 0.f;
    int32 NumWheels = 0;
    for (int32 W : Wheels)
    {
        if (bFound[W])
        {
            MeanLateral += Along(Pos(W), MeshRight);
            ++NumWheels;
        }
    }
    MeanLateral = NumWheels > 0 ? MeanLateral / NumWheels : 0.f;
    for (int32 I = 0; I < 4; ++I)
    {
        WheelLateral[I] = bFound[Wheels[I]] ? Along(Pos(Wheels[I]), MeshRight) - MeanLateral : 0.f;
    }
    if (bFound[WheelFL] && bFound[WheelFR] && bFound[WheelRL] && bFound[WheelRR])
    {
        const float Base = FMath::Abs(Along(0.5 * (Pos(WheelFL) + Pos(WheelFR)) - 0.5 * (Pos(WheelRL) + Pos(WheelRR)), MeshForward));
        if (Base > 10.f)
        {
            MeasuredWheelbase = Base;
        }
    }

    // The capsule: coupler to axle, and each capsule wheel's side of the coupler.
    if (bFound[Coupler] && bFound[CapsuleWheelL] && bFound[CapsuleWheelR])
    {
        const FVector Mid = 0.5 * (Pos(CapsuleWheelL) + Pos(CapsuleWheelR));
        const float Length = Along(Pos(Coupler) - Mid, MeshForward);
        if (Length > 20.f)
        {
            MeasuredTrailerLength = Length;
        }
        TrailerWheelLateral[0] = Along(Pos(CapsuleWheelL) - Pos(Coupler), MeshRight);
        TrailerWheelLateral[1] = Along(Pos(CapsuleWheelR) - Pos(Coupler), MeshRight);
    }
    // The coupler behind the mesh origin, which sits on the pawn's turning centre.
    MeasuredHitchOffset = bFound[Coupler] ? FMath::Max(0.f, -Along(Pos(Coupler), MeshForward)) : 0.f;

    CachedSerial = Container.GetSerialNumber();
    CachedSkeleton = &Ref;
    CachedBoneKey = BoneKey(Tuning);
    bBonesCached = true;
    return true;
}

void FSaskartaCarrierAnimProxy::AdvancePlayer(FPlayer& Player, float Dt) const
{
    if (!Player.Asset)
    {
        return;
    }
    auto Advance = [&Player](float Delta, float Length)
    {
        // Advances Normalized by Delta / Length, wrapping or holding the end.
        if (Length <= UE_KINDA_SMALL_NUMBER)
        {
            return;
        }
        float N = Player.Normalized + Delta / Length;
        if (Player.bLoop)
        {
            N = FMath::Fmod(N, 1.f);
            if (N < 0.f)
            {
                N += 1.f;
            }
            Player.bFinished = false;
        }
        else
        {
            if ((Delta >= 0.f && N >= 1.f) || (Delta < 0.f && N <= 0.f))
            {
                Player.bFinished = true;
            }
            N = FMath::Clamp(N, 0.f, 1.f);
        }
        Player.Normalized = N;
    };

    if (const UBlendSpace* BlendSpace = Cast<UBlendSpace>(Player.Asset))
    {
        BlendSpace->UpdateBlendSamples(Player.BlendPosition, Dt, Player.Samples, Player.TriangulationIndex);
        // The samples share one normalised time (they are all versions of the same drive cycle).
        float Length = 0.f;
        float Weight = 0.f;
        for (const FBlendSampleData& Sample : Player.Samples)
        {
            if (Sample.SampleDataIndex >= 0 && Sample.SampleDataIndex < BlendSpace->GetBlendSamples().Num())
            {
                if (const UAnimSequence* Anim = BlendSpace->GetBlendSample(Sample.SampleDataIndex).Animation)
                {
                    const float W = Sample.GetClampedWeight();
                    Length += W * Anim->GetPlayLength();
                    Weight += W;
                }
            }
        }
        Player.Length = Weight > UE_KINDA_SMALL_NUMBER ? Length / Weight : 0.f;
        Advance(Dt * Player.Rate, Player.Length);
        for (FBlendSampleData& Sample : Player.Samples)
        {
            float SampleLength = 0.f;
            if (Sample.SampleDataIndex >= 0 && Sample.SampleDataIndex < BlendSpace->GetBlendSamples().Num())
            {
                if (const UAnimSequence* Anim = BlendSpace->GetBlendSample(Sample.SampleDataIndex).Animation)
                {
                    SampleLength = Anim->GetPlayLength();
                }
            }
            Sample.PreviousTime = Sample.Time;
            Sample.Time = Player.Normalized * SampleLength;
        }
        Player.Time = Player.Normalized * Player.Length;
    }
    else if (const UAnimSequenceBase* Sequence = Cast<UAnimSequenceBase>(Player.Asset))
    {
        Player.Length = Sequence->GetPlayLength();
        Advance(Dt * Player.Rate, Player.Length);
        Player.Time = Player.Normalized * Player.Length;
    }
}

bool FSaskartaCarrierAnimProxy::EvaluatePlayer(FPlayer& Player, FPoseContext& Output) const
{
    if (!Player.Asset)
    {
        return false;
    }
    const FAnimExtractContext Extract(static_cast<double>(Player.Time), /*bExtractRootMotion*/ false, FDeltaTimeRecord(), Player.bLoop);
    if (const UBlendSpace* BlendSpace = Cast<UBlendSpace>(Player.Asset))
    {
        if (Player.Samples.Num() == 0)
        {
            return false;
        }
        FAnimationPoseData PoseData(Output);
        BlendSpace->GetAnimationPose(Player.Samples, Extract, PoseData);
        return true;
    }
    if (const UAnimSequenceBase* Sequence = Cast<UAnimSequenceBase>(Player.Asset))
    {
        FAnimationPoseData PoseData(Output);
        Sequence->GetAnimationPose(PoseData, Extract);
        return true;
    }
    return false;
}

void FSaskartaCarrierAnimProxy::StepDynamics(float Dt)
{
    using namespace SaskartaCarrierMath;
    const FSaskartaCarrierAnimTuning& T = Tuning;
    const float V = Inputs.Speed;
    const float W = FMath::DegreesToRadians(Inputs.YawRate);
    const float WheelV = bWheelSpinLocked ? 0.f : V;
    const float WheelW = bWheelSpinLocked ? 0.f : W;
    const bool bOff = IsOff();

    // Wheels: distance / radius, the inner side slower in a turn.
    const float WheelRadius = FMath::Max(1.f, T.WheelRadius);
    for (int32 I = 0; I < 4; ++I)
    {
        const float Lateral = T.bWheelDifferential ? WheelLateral[I] : 0.f;
        WheelSpin[I] = WrapRadians(WheelSpin[I] + (WheelV - WheelW * Lateral) * Dt / WheelRadius);
    }

    // Steer.
    const float MaxSteer = FMath::DegreesToRadians(FMath::Max(0.f, T.MaxSteerDeg));
    const float Wheelbase = T.Wheelbase > 0.f ? T.Wheelbase : MeasuredWheelbase;
    const float SteerTarget = T.bSteerFromYawRate
        ? SteerFromYawRate(W, V, Wheelbase, MaxSteer, T.SteerMinSpeed)
        : FMath::Clamp(Inputs.Steer, -1.f, 1.f) * MaxSteer;
    StepSpring(Steer, SteerTarget, T.SteerStiffness, T.SteerDamping, Dt);
    OutSteerDeg = FMath::RadiansToDegrees(FMath::Clamp(Steer.X, -MaxSteer, MaxSteer));

    // The hitch. Its limit keeps the capsule clear of the carrier (the footprints), the
    // last HitchSoftZoneDeg cushion the stop, and the rate is capped, so it never snaps.
    if (bHitchResetPending)
    {
        ResetTrailer();
        bHitchResetPending = false;
    }
    const float Length = T.TrailerLength > 0.f ? T.TrailerLength : MeasuredTrailerLength;
    const float Offset = T.bMeasureHitchOffset ? MeasuredHitchOffset : T.HitchOffset;
    const float MaxHitch = HitchLimit();
    FHitchLimits Limits;
    Limits.MaxPsiRad = MaxHitch;
    Limits.SoftZoneRad = FMath::DegreesToRadians(FMath::Max(0.f, T.HitchSoftZoneDeg));
    Limits.MaxRateRadS = FMath::DegreesToRadians(FMath::Max(1.f, T.MaxHitchRateDeg));
    // The owner's per-frame motion when there is one (the 10 Hz inputs step, and spike on a teleport).
    const bool bOwnMotion = T.bHitchFromOwnerMotion && bOwnerMotionValid;
    const float HitchV = bWheelSpinLocked ? 0.f : (bOwnMotion ? OwnerSpeed : V);
    const float HitchW = bWheelSpinLocked ? 0.f : (bOwnMotion ? FMath::DegreesToRadians(OwnerYawRateDeg) : W);
    float HitchRate = 0.f;
    if (T.bTrailer)
    {
        const float Before = HitchRad;
        HitchRad = StepHitchAngleLimited(HitchRad, HitchV, HitchW, Length, Offset, Dt, Limits, T.ReverseJackknifeScale);
        HitchRate = (HitchRad - Before) / Dt;
    }
    else
    {
        HitchRad = 0.f;
    }

    // Capsule wheels: the capsule moves along its own heading at v cos(psi).
    const float TrailerRadius = FMath::Max(1.f, T.TrailerWheelRadius);
    const float TrailerSpeed = HitchV * FMath::Cos(HitchRad);
    const float TrailerYawRate = HitchW + HitchRate;
    for (int32 J = 0; J < 2; ++J)
    {
        const float Lateral = T.bWheelDifferential ? TrailerWheelLateral[J] : 0.f;
        TrailerWheelSpin[J] = WrapRadians(TrailerWheelSpin[J] + (TrailerSpeed - TrailerYawRate * Lateral) * Dt / TrailerRadius);
    }

    // Sway: the capsule swings out of a turn, then settles. It rides on the hitch angle,
    // and the sum bends softly into the same limit.
    const float Lat = LateralAccel(HitchV, HitchW);
    StepSpring(Sway, ClampedGain(Lat, T.SwayPerLateralAccel, T.MaxSwayDeg), T.SwayStiffness, T.SwayDamping, Dt);
    const float SwayDeg = FMath::Clamp(Sway.X, -T.MaxSwayDeg, T.MaxSwayDeg);
    const float MaxHitchDeg = FMath::RadiansToDegrees(MaxHitch);
    OutHitchLimitDeg = MaxHitchDeg;
    OutHitchDeg = T.bTrailer ? SoftClampAngle(FMath::RadiansToDegrees(HitchRad) + SwayDeg, MaxHitchDeg, FMath::Min(3.f, MaxHitchDeg)) : 0.f;

    // Capsule pitch and roll from the ground under its own wheels.
    FVector2D Tilt = FVector2D::ZeroVector;
    if (Inputs.bHasTrailerGround)
    {
        Tilt = TrailerPitchRoll(Inputs.TrailerGroundL, TrailerWheelLateral[0], Inputs.TrailerGroundR, TrailerWheelLateral[1], Length);
    }
    const float PitchTarget = FMath::Clamp(FMath::RadiansToDegrees(static_cast<float>(Tilt.X)), -T.MaxTrailerPitchDeg, T.MaxTrailerPitchDeg);
    const float RollTarget = FMath::Clamp(FMath::RadiansToDegrees(static_cast<float>(Tilt.Y)), -T.MaxTrailerRollDeg, T.MaxTrailerRollDeg);
    StepSpring(TrailerPitch, PitchTarget, T.TrailerTiltStiffness, T.TrailerTiltDamping, Dt);
    StepSpring(TrailerRoll, RollTarget, T.TrailerTiltStiffness, T.TrailerTiltDamping, Dt);
    OutTrailerPitchDeg = FMath::Clamp(TrailerPitch.X, -T.MaxTrailerPitchDeg, T.MaxTrailerPitchDeg);
    OutTrailerRollDeg = FMath::Clamp(TrailerRoll.X, -T.MaxTrailerRollDeg, T.MaxTrailerRollDeg);

    // Capsule bob: it lags a step in the ground under it, then springs back.
    if (Inputs.bHasTrailerGround)
    {
        const float Mean = 0.5f * (Inputs.TrailerGroundL + Inputs.TrailerGroundR);
        if (bHaveTrailerMean && FMath::Abs(Mean - LastTrailerMean) < 50.f)
        {
            TrailerBob.X -= (Mean - LastTrailerMean) * T.TrailerBobCoupling;
        }
        LastTrailerMean = Mean;
        bHaveTrailerMean = true;
    }
    StepSpring(TrailerBob, 0.f, T.TrailerBobStiffness, T.TrailerBobDamping, Dt);
    TrailerBob.X = FMath::Clamp(TrailerBob.X, -T.MaxTrailerBobCm, T.MaxTrailerBobCm);
    OutTrailerBobCm = TrailerBob.X;
    const float BobAccel = (TrailerBob.V - LastBobV) / Dt;
    LastBobV = TrailerBob.V;

    // Body: squat / dip and roll through a spring, then clamped.
    const float BodyPitchTarget = ClampedGain(Inputs.Accel, T.BodyPitchPerAccel, T.MaxBodyPitchDeg);
    const float BodyRollTarget = ClampedGain(-Lat, T.BodyRollPerLateralAccel, T.MaxBodyRollDeg);
    StepSpring(BodyPitch, BodyPitchTarget, T.BodyStiffness, T.BodyDamping, Dt);
    StepSpring(BodyRoll, BodyRollTarget, T.BodyStiffness, T.BodyDamping, Dt);
    OutBodyPitchDeg = FMath::Clamp(BodyPitch.X, -T.MaxBodyPitchDeg, T.MaxBodyPitchDeg);
    OutBodyRollDeg = FMath::Clamp(BodyRoll.X, -T.MaxBodyRollDeg, T.MaxBodyRollDeg);

    // Bounce: the body lags a change of the mean wheel ground height, then springs back.
    float GroundStep = 0.f;
    if (Inputs.bHasWheelGround)
    {
        const float Mean = 0.25f * (Inputs.GroundFL + Inputs.GroundFR + Inputs.GroundRL + Inputs.GroundRR);
        if (bHaveWheelMean && FMath::Abs(Mean - LastWheelMean) < 50.f)
        {
            GroundStep = Mean - LastWheelMean;
            Bounce.X -= GroundStep * T.BounceCoupling;
        }
        LastWheelMean = Mean;
        bHaveWheelMean = true;
    }
    StepSpring(Bounce, 0.f, T.BounceStiffness, T.BounceDamping, Dt);
    Bounce.X = FMath::Clamp(Bounce.X, -T.MaxBounceCm, T.MaxBounceCm);
    OutBounceCm = Bounce.X;

    // Mast whip: it lags the body's angular acceleration and the carrier's acceleration.
    const float BodyPitchAccel = (BodyPitch.V - LastBodyPitchV) / Dt;
    const float BodyRollAccel = (BodyRoll.V - LastBodyRollV) / Dt;
    LastBodyPitchV = BodyPitch.V;
    LastBodyRollV = BodyRoll.V;
    const float MastPitchTarget = FMath::Clamp(-Inputs.Slope * T.MastSlopeCompensation, -T.MaxMastDeg, T.MaxMastDeg);
    StepSpring(MastPitch, MastPitchTarget, T.MastStiffness, T.MastDamping, Dt,
        -T.MastInertia * BodyPitchAccel + T.MastAccelGain * Inputs.Accel);
    StepSpring(MastRoll, 0.f, T.MastStiffness, T.MastDamping, Dt,
        -T.MastInertia * BodyRollAccel - T.MastLateralGain * Lat);
    MastPitch.X = FMath::Clamp(MastPitch.X, -T.MaxMastDeg, T.MaxMastDeg);
    MastRoll.X = FMath::Clamp(MastRoll.X, -T.MaxMastDeg, T.MaxMastDeg);
    OutMastPitchDeg = MastPitch.X;
    OutMastRollDeg = MastRoll.X;

    // Lining jiggle: driven by the capsule's vertical acceleration.
    StepSpring(Lining, 0.f, T.LiningStiffness, T.LiningDamping, Dt, -T.LiningGain * BobAccel);
    Lining.X = FMath::Clamp(Lining.X, -T.MaxLiningCm, T.MaxLiningCm);
    OutLiningCm = Lining.X;

    // Drawbar rattle: random kicks growing with speed and with the roughness of the ground.
    if (!bOff && FMath::Abs(V) > 5.f)
    {
        const float SpeedShare = FMath::Min(FMath::Abs(V) / 500.f, 2.f);
        Rattle.V += Rng.FRandRange(-1.f, 1.f) * (T.RattleKick * SpeedShare * FMath::Sqrt(Dt) + FMath::Abs(GroundStep) * T.RattleRoughnessGain);
    }
    StepSpring(Rattle, 0.f, T.RattleStiffness, T.RattleDamping, Dt);
    Rattle.X = FMath::Clamp(Rattle.X, -T.RattleMaxDeg, T.RattleMaxDeg);
    OutRattleDeg = Rattle.X;

    // Idle life: saccades, a glance into the turn, blinks.
    if (T.bIdleLife && !bOff)
    {
        SaccadeTimer -= Dt;
        if (SaccadeTimer <= 0.f)
        {
            SaccadeTarget = FVector2f(Rng.FRandRange(-T.SaccadeYawDeg, T.SaccadeYawDeg), Rng.FRandRange(-T.SaccadePitchDeg, T.SaccadePitchDeg));
            SaccadeTimer = Rng.FRandRange(T.SaccadeIntervalMin, FMath::Max(T.SaccadeIntervalMin, T.SaccadeIntervalMax));
        }
        BlinkTimer -= Dt;
        if (BlinkTimer <= 0.f)
        {
            BlinkElapsed = 0.f;
            BlinkTimer = Rng.FRandRange(T.BlinkIntervalMin, FMath::Max(T.BlinkIntervalMin, T.BlinkIntervalMax));
        }
    }
    else
    {
        SaccadeTarget = FVector2f::ZeroVector;
        BlinkElapsed = -1.f;
    }
    const float Look = MaxSteer > UE_KINDA_SMALL_NUMBER ? T.EyeSteerLookDeg * FMath::Clamp(Steer.X / MaxSteer, -1.f, 1.f) : 0.f;
    const float EyeDamping = CriticalDamping(T.SaccadeStiffness);
    StepSpring(EyeYaw, SaccadeTarget.X + Look, T.SaccadeStiffness, EyeDamping, Dt);
    StepSpring(EyePitch, SaccadeTarget.Y, T.SaccadeStiffness, EyeDamping, Dt);
    OutEyeYawDeg = EyeYaw.X;
    OutEyePitchDeg = EyePitch.X;
    if (BlinkElapsed >= 0.f)
    {
        BlinkElapsed += Dt;
        const float Duration = FMath::Max(0.02f, T.BlinkDuration);
        if (BlinkElapsed >= Duration)
        {
            BlinkElapsed = -1.f;
            BlinkScale = 1.f;
        }
        else
        {
            BlinkScale = FMath::Lerp(1.f, FMath::Clamp(T.BlinkMinScale, 0.f, 1.f), FMath::Sin(UE_PI * BlinkElapsed / Duration));
        }
    }
    else
    {
        BlinkScale = 1.f;
    }
}

FTransform FSaskartaCarrierAnimProxy::ComponentSpace(const FCompactPose& Pose, FCompactPoseBoneIndex Index) const
{
    FTransform Result = Pose[Index];
    FCompactPoseBoneIndex Parent = Pose.GetParentBoneIndex(Index);
    while (Parent.IsValid())
    {
        Result = Result * Pose[Parent];
        Parent = Pose.GetParentBoneIndex(Parent);
    }
    return Result;
}

void FSaskartaCarrierAnimProxy::ApplyBones(FCompactPose& Pose) const
{
    const FBoneContainer& Container = Pose.GetBoneContainer();
    const int32 NumBones = Pose.GetNumBones();
    auto Valid = [this, NumBones](int32 B)
    {
        return Bones[B].bValid && Bones[B].Compact.GetInt() < NumBones;
    };
    // Rotate a bone about one of its own (mesh-derived) axes, on top of its pose.
    auto RotateOwn = [&](int32 B, const FVector& Axis, float Deg)
    {
        if (!Valid(B) || FMath::IsNearlyZero(Deg))
        {
            return;
        }
        FTransform& Local = Pose[Bones[B].Compact];
        Local.SetRotation((Local.GetRotation() * FQuat(Axis, FMath::DegreesToRadians(Deg))).GetNormalized());
    };
    // Drop the clip's rotation (the wheels and steer are fully procedural).
    auto ResetRotation = [&](int32 B)
    {
        if (Valid(B))
        {
            Pose[Bones[B].Compact].SetRotation(Container.GetRefPoseTransform(Bones[B].Compact).GetRotation());
        }
    };
    // Move a bone by a mesh-space offset (through its parent's reference frame).
    auto TranslateMesh = [&](int32 B, const FVector& MeshDelta)
    {
        if (!Valid(B) || MeshDelta.IsNearlyZero())
        {
            return;
        }
        Pose[Bones[B].Compact].AddToTranslation(Bones[B].ParentRefCS.InverseTransformVector(MeshDelta));
    };

    // Body: squat / dip, roll, bounce.
    RotateOwn(Body, Bones[Body].AxisRight, -OutBodyPitchDeg);
    RotateOwn(Body, Bones[Body].AxisForward, -OutBodyRollDeg);
    TranslateMesh(Body, MeshUp * OutBounceCm);

    // Mast whip.
    RotateOwn(Mast, Bones[Mast].AxisRight, -OutMastPitchDeg);
    RotateOwn(Mast, Bones[Mast].AxisForward, -OutMastRollDeg);

    // Eyes: saccades and blinks.
    for (const int32 Eye : { int32(EyeL), int32(EyeR) })
    {
        RotateOwn(Eye, Bones[Eye].AxisUp, OutEyeYawDeg);
        RotateOwn(Eye, Bones[Eye].AxisRight, -OutEyePitchDeg);
        if (Valid(Eye) && BlinkScale < 0.999f)
        {
            // Squash along the bone axis closest to the mesh's up.
            const FVector A = Bones[Eye].AxisUp.GetAbs();
            const int32 Axis = (A.X >= A.Y && A.X >= A.Z) ? 0 : (A.Y >= A.Z ? 1 : 2);
            FTransform& Local = Pose[Bones[Eye].Compact];
            FVector Scale = Local.GetScale3D();
            Scale[Axis] *= BlinkScale;
            Local.SetScale3D(Scale);
        }
    }

    // Steer.
    if (Tuning.bProceduralSteer)
    {
        for (const int32 S : { int32(SteerFL), int32(SteerFR) })
        {
            ResetRotation(S);
            RotateOwn(S, Bones[S].AxisUp, OutSteerDeg);
        }
    }

    // Carrier wheels.
    if (Tuning.bProceduralWheelSpin)
    {
        const int32 Wheels[4] = { WheelFL, WheelFR, WheelRL, WheelRR };
        for (int32 I = 0; I < 4; ++I)
        {
            ResetRotation(Wheels[I]);
            RotateOwn(Wheels[I], Bones[Wheels[I]].AxisRight, FMath::RadiansToDegrees(WheelSpin[I]));
        }
    }

    // Drawbar rattle (a pitch jitter at the coupler).
    RotateOwn(Coupler, Bones[Coupler].AxisRight, -OutRattleDeg);

    // The capsule: yaw from the hitch (plus sway), pitch and roll from its wheels, bob;
    // all about the coupler.
    if (Tuning.bTrailer && Valid(CapsuleRoot))
    {
        const FCompactPoseBoneIndex Index = Bones[CapsuleRoot].Compact;
        const FCompactPoseBoneIndex ParentIndex = Pose.GetParentBoneIndex(Index);
        const FTransform ParentCS = ParentIndex.IsValid() ? ComponentSpace(Pose, ParentIndex) : FTransform::Identity;
        const FTransform BoneCS = Pose[Index] * ParentCS;
        const FVector Pivot = Valid(Coupler) ? ComponentSpace(Pose, Bones[Coupler].Compact).GetTranslation() : BoneCS.GetTranslation();
        const FQuat Yaw(MeshUp, FMath::DegreesToRadians(OutHitchDeg));
        const FQuat Pitch(MeshRight, FMath::DegreesToRadians(-OutTrailerPitchDeg));
        const FQuat Roll(MeshForward, FMath::DegreesToRadians(-OutTrailerRollDeg));
        const FQuat Q = Yaw * Pitch * Roll;
        FTransform NewCS = BoneCS;
        NewCS.SetRotation((Q * BoneCS.GetRotation()).GetNormalized());
        NewCS.SetTranslation(Pivot + Q.RotateVector(BoneCS.GetTranslation() - Pivot) + MeshUp * OutTrailerBobCm);
        FTransform NewLocal = NewCS.GetRelativeTransform(ParentCS);
        NewLocal.NormalizeRotation();
        Pose[Index] = NewLocal;
    }

    // Lining jiggle.
    TranslateMesh(CapsuleLining, MeshUp * OutLiningCm);

    // Capsule wheels.
    if (Tuning.bProceduralWheelSpin)
    {
        const int32 Wheels[2] = { CapsuleWheelL, CapsuleWheelR };
        for (int32 J = 0; J < 2; ++J)
        {
            ResetRotation(Wheels[J]);
            RotateOwn(Wheels[J], Bones[Wheels[J]].AxisRight, FMath::RadiansToDegrees(TrailerWheelSpin[J]));
        }
    }
}

// ─── Instance ────────────────────────────────────────────────────────────────

FAnimInstanceProxy* USaskartaCarrierAnimInstance::CreateAnimInstanceProxy()
{
    return new FSaskartaCarrierAnimProxy(this);
}

void USaskartaCarrierAnimInstance::DestroyAnimInstanceProxy(FAnimInstanceProxy* InProxy)
{
    delete static_cast<FSaskartaCarrierAnimProxy*>(InProxy);
}

USaskartaCarrierAnimInstance* USaskartaCarrierAnimInstance::InstallOn(USkeletalMeshComponent* Mesh)
{
    if (!Mesh)
    {
        return nullptr;
    }
    if (USaskartaCarrierAnimInstance* Existing = Cast<USaskartaCarrierAnimInstance>(Mesh->GetAnimInstance()))
    {
        return Existing;
    }
    Mesh->SetAnimationMode(EAnimationMode::AnimationBlueprint);
    Mesh->SetAnimInstanceClass(USaskartaCarrierAnimInstance::StaticClass());
    return Cast<USaskartaCarrierAnimInstance>(Mesh->GetAnimInstance());
}

void USaskartaCarrierAnimInstance::SetCarrierInputs(const FSaskartaCarrierAnimInputs& NewInputs)
{
    const float OldL = Inputs.TrailerGroundL;
    const float OldR = Inputs.TrailerGroundR;
    const bool bOldTrailer = Inputs.bHasTrailerGround;
    Inputs = NewInputs;
    if (!NewInputs.bHasTrailerGround)
    {
        Inputs.TrailerGroundL = OldL;
        Inputs.TrailerGroundR = OldR;
        Inputs.bHasTrailerGround = bOldTrailer;
    }
}

void USaskartaCarrierAnimInstance::SetMotionInputs(float Speed, float YawRate, float SlopeRiseOverRun)
{
    const UWorld* World = GetWorld();
    const double Now = World ? World->GetTimeSeconds() : 0.0;
    const double Elapsed = Now - LastMotionTime;
    if (LastMotionTime >= 0.0 && Elapsed > 1e-3 && Elapsed < 1.0)
    {
        // Half-way towards the new estimate: the 10 Hz differences are noisy.
        const float Raw = static_cast<float>((Speed - LastMotionSpeed) / Elapsed);
        Inputs.Accel = FMath::Lerp(Inputs.Accel, Raw, 0.5f);
    }
    else
    {
        Inputs.Accel = 0.f;
    }
    LastMotionSpeed = Speed;
    LastMotionTime = Now;
    Inputs.Speed = Speed;
    Inputs.YawRate = YawRate;
    Inputs.Slope = FMath::RadiansToDegrees(FMath::Atan(SlopeRiseOverRun));
}

void USaskartaCarrierAnimInstance::SetWheelSpinLocked(bool bLocked)
{
    bWheelSpinLocked = bLocked;
}

void USaskartaCarrierAnimInstance::SetWheelGround(float GroundFL, float GroundFR, float GroundRL, float GroundRR)
{
    Inputs.GroundFL = GroundFL;
    Inputs.GroundFR = GroundFR;
    Inputs.GroundRL = GroundRL;
    Inputs.GroundRR = GroundRR;
    Inputs.bHasWheelGround = true;
}

void USaskartaCarrierAnimInstance::ResetHitch()
{
    ++HitchResetSerial;
    OutHitchDeg = 0.f;
}

void USaskartaCarrierAnimInstance::SetTuning(const FSaskartaCarrierAnimTuning& NewTuning)
{
    Tuning = NewTuning;
    bTrailerGeometryValid = false;
    TrailerGeometryMesh = nullptr;
}

void USaskartaCarrierAnimInstance::PlayState(FName State, UAnimationAsset* Asset, bool bLoop, float InPlayRate)
{
    if (Asset)
    {
        KeptAssets.AddUnique(Asset);
    }
    CurrentAsset = Asset;
    CurrentState = State;
    bLoopRequested = bLoop;
    PlayRate = InPlayRate;
    ++PlaySerial;
    bOutClipFinished = false;
    OutClipTime = 0.f;
}

void USaskartaCarrierAnimInstance::SetStateAsset(FName State, UAnimationAsset* Asset, bool bLoop)
{
    if (State.IsNone())
    {
        return;
    }
    StateAssets.Add(State, Asset);
    StateLoops.Add(State, bLoop);
    if (Asset)
    {
        KeptAssets.AddUnique(Asset);
    }
}

void USaskartaCarrierAnimInstance::SetDriveState(FName State, float InPlayRate, FVector2D InBlendInput)
{
    PlayRate = InPlayRate;
    BlendInput = FVector(InBlendInput.X, InBlendInput.Y, 0.0);
    if (State.IsNone() || State == CurrentState)
    {
        return;
    }
    if (const TObjectPtr<UAnimationAsset>* Asset = StateAssets.Find(State))
    {
        PlayState(State, Asset->Get(), StateLoops.FindRef(State), InPlayRate);
    }
    else
    {
        CurrentState = State;
    }
}

void USaskartaCarrierAnimInstance::SetPlayRate(float InPlayRate)
{
    PlayRate = InPlayRate;
}

void USaskartaCarrierAnimInstance::SetBlendSpacePosition(FVector InPosition)
{
    BlendInput = InPosition;
}

bool USaskartaCarrierAnimInstance::IsPlaying() const
{
    return CurrentAsset != nullptr && (bLoopRequested || !bOutClipFinished);
}

FRotator USaskartaCarrierAnimInstance::GetCameraBodyDynamics() const
{
    const float Share = FMath::Clamp(Tuning.CameraBodyShare, 0.f, 1.f);
    return FRotator(OutBodyPitchDeg * Share, 0.f, OutBodyRollDeg * Share);
}

void USaskartaCarrierAnimInstance::GetBodyDynamics(float& PitchDeg, float& RollDeg, float& HeaveCm) const
{
    PitchDeg = OutBodyPitchDeg;
    RollDeg = OutBodyRollDeg;
    HeaveCm = OutBodyHeaveCm;
}

bool USaskartaCarrierAnimInstance::CacheTrailerGeometry(const USkeletalMeshComponent* Mesh)
{
    const USkeletalMesh* Asset = Mesh ? Mesh->GetSkeletalMeshAsset() : nullptr;
    if (!Asset)
    {
        return false;
    }
    if (TrailerGeometryMesh.Get() == Asset)
    {
        return bTrailerGeometryValid;
    }
    TrailerGeometryMesh = Asset;
    bTrailerGeometryValid = false;
    const FReferenceSkeleton& Ref = Asset->GetRefSkeleton();
    const int32 CouplerIndex = Ref.FindBoneIndex(Tuning.BoneCoupler);
    const int32 LeftIndex = Ref.FindBoneIndex(Tuning.BoneCapsuleWheelL);
    const int32 RightIndex = Ref.FindBoneIndex(Tuning.BoneCapsuleWheelR);
    if (CouplerIndex == INDEX_NONE || LeftIndex == INDEX_NONE || RightIndex == INDEX_NONE)
    {
        return false;
    }
    RefCoupler = FAnimationRuntime::GetComponentSpaceTransformRefPose(Ref, CouplerIndex).GetTranslation();
    RefTrailerWheelL = FAnimationRuntime::GetComponentSpaceTransformRefPose(Ref, LeftIndex).GetTranslation();
    RefTrailerWheelR = FAnimationRuntime::GetComponentSpaceTransformRefPose(Ref, RightIndex).GetTranslation();
    bTrailerGeometryValid = true;
    return true;
}

void USaskartaCarrierAnimInstance::UpdateTrailerGround()
{
    USkeletalMeshComponent* Mesh = GetSkelMeshComponent();
    UWorld* World = GetWorld();
    if (!Mesh || !World || !CacheTrailerGeometry(Mesh))
    {
        return;
    }
    const FTransform ComponentTM = Mesh->GetComponentTransform();
    FVector Up = Tuning.MeshUp.GetSafeNormal();
    if (Up.IsNearlyZero())
    {
        Up = FVector::UpVector;
    }
    // Where each capsule wheel would sit with the current hitch yaw, rigid in the carrier's
    // (already ground-fitted) plane: the offset of the real ground from there tilts the capsule.
    const FQuat Yaw(Up, FMath::DegreesToRadians(OutHitchDeg));
    FCollisionQueryParams Params(SCENE_QUERY_STAT(SaskartaTrailerGround), /*bTraceComplex*/ false, GetOwningActor());
    const FVector WheelRefs[2] = { RefTrailerWheelL, RefTrailerWheelR };
    float Heights[2] = { 0.f, 0.f };
    const float Radius = FMath::Max(1.f, Tuning.TrailerWheelRadius);
    const float Limit = FMath::Max(0.f, Tuning.MaxTrailerGroundCm);
    for (int32 J = 0; J < 2; ++J)
    {
        const FVector Local = RefCoupler + Yaw.RotateVector(WheelRefs[J] - RefCoupler);
        const FVector Centre = ComponentTM.TransformPosition(Local);
        const double ExpectedGroundZ = Centre.Z - Radius;
        FHitResult Hit;
        const FVector Start = Centre + FVector(0.0, 0.0, Tuning.TrailerTraceUp);
        const FVector End = Centre - FVector(0.0, 0.0, Radius + Tuning.TrailerTraceDown);
        if (World->LineTraceSingleByChannel(Hit, Start, End, ECC_Visibility, Params))
        {
            Heights[J] = FMath::Clamp(static_cast<float>(Hit.ImpactPoint.Z - ExpectedGroundZ), -Limit, Limit);
        }
    }
    Inputs.TrailerGroundL = Heights[0];
    Inputs.TrailerGroundR = Heights[1];
    Inputs.bHasTrailerGround = true;
}
