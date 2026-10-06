// FSaskartaCarrierAnimProxy: USaskartaCarrierAnimInstance's worker-thread half
// (task CARRIERANIM).
//
//   PreUpdate  (game thread)   copies the inputs, the tuning and the requested clip
//   Update     (worker)        advances the clip(s) and integrates every spring
//   Evaluate   (worker)        samples the clip (with the crossfade), then applies the
//                              procedural bones to the local pose
//   PostUpdate (game thread)   hands the camera / hitch / clip outputs back
//
// A plain struct (not a USTRUCT): nothing reflects it. The asset pointers it holds
// are kept alive by the instance's UPROPERTYs (CurrentAsset, KeptAssets).

#pragma once

#include "CoreMinimal.h"
#include "Animation/AnimInstanceProxy.h"
#include "Animation/AnimationAsset.h"
#include "BoneIndices.h"
#include "Math/RandomStream.h"
#include "SaskartaCarrierAnimInstance.h"
#include "SaskartaCarrierMath.h"

struct FSaskartaCarrierAnimProxy : public FAnimInstanceProxy
{
    FSaskartaCarrierAnimProxy() = default;
    explicit FSaskartaCarrierAnimProxy(UAnimInstance* InAnimInstance);

    virtual void PreUpdate(UAnimInstance* InAnimInstance, float DeltaSeconds) override;
    virtual void Update(float DeltaSeconds) override;
    virtual bool Evaluate(FPoseContext& Output) override;
    virtual void PostUpdate(UAnimInstance* InAnimInstance) const override;

private:
    enum EBone : uint8
    {
        Body, Mast, EyeL, EyeR, SteerFL, SteerFR, WheelFL, WheelFR, WheelRL, WheelRR,
        Coupler, CapsuleRoot, CapsuleLining, CapsuleWheelL, CapsuleWheelR,
        BoneCount
    };

    struct FBone
    {
        bool bValid = false;
        FCompactPoseBoneIndex Compact = FCompactPoseBoneIndex(INDEX_NONE);
        /** Reference pose, component space. */
        FTransform RefCS = FTransform::Identity;
        /** The parent's reference pose, component space (identity at the root). */
        FTransform ParentRefCS = FTransform::Identity;
        /** The mesh's forward / up / right, expressed in this bone's own reference frame. */
        FVector AxisForward = FVector::ForwardVector;
        FVector AxisUp = FVector::UpVector;
        FVector AxisRight = FVector::RightVector;
    };

    /** One playing asset: a sequence (Time in seconds) or a blend space (Time = normalised * length). */
    struct FPlayer
    {
        UAnimationAsset* Asset = nullptr;
        bool bLoop = true;
        float Rate = 1.f;
        FVector BlendPosition = FVector::ZeroVector;
        float Time = 0.f;
        float Normalized = 0.f;
        float Length = 0.f;
        bool bFinished = false;
        TArray<FBlendSampleData> Samples;
        int32 TriangulationIndex = INDEX_NONE;
    };

    bool CacheBoneRefs(const FBoneContainer& Container);
    void AdvancePlayer(FPlayer& Player, float Dt) const;
    bool EvaluatePlayer(FPlayer& Player, FPoseContext& Output) const;
    void StepDynamics(float Dt);
    void ApplyBones(FCompactPose& Pose) const;
    FTransform ComponentSpace(const FCompactPose& Pose, FCompactPoseBoneIndex Index) const;
    bool IsOff() const;
    /** The hitch limit (radians) for the current tuning, cached. */
    float HitchLimit();
    /** Straightens the hitch and settles the capsule's springs. */
    void ResetTrailer();
    /** A hash of the tuning's bone names and mesh axes: the bone cache is rebuilt when it changes. */
    static uint32 BoneKey(const FSaskartaCarrierAnimTuning& T);

    // Copied in PreUpdate.
    FSaskartaCarrierAnimInputs Inputs;
    FSaskartaCarrierAnimTuning Tuning;
    bool bWheelSpinLocked = false;
    FName State;
    int32 SeenPlaySerial = -1;
    int32 SeenHitchResetSerial = 0;

    // The owner's own motion, measured in PreUpdate (game thread) for the hitch.
    bool bHaveOwnerPose = false;
    FVector LastOwnerLocation = FVector::ZeroVector;
    float LastOwnerYawDeg = 0.f;
    bool bOwnerMotionValid = false;
    float OwnerSpeed = 0.f;
    float OwnerYawRateDeg = 0.f;
    bool bHitchResetPending = false;
    // The footprint limit, recomputed when the footprints or the caps change.
    TArray<FVector2D> LimitCarrierFootprint;
    TArray<FVector2D> LimitTrailerFootprint;
    float LimitKeyUserMax = -1.f;
    float LimitKeyClearance = -1.f;
    bool bLimitKeyFootprint = false;
    float HitchLimitRad = 0.f;

    FPlayer CurrentPlayer;
    FPlayer PreviousPlayer;
    float BlendElapsed = 0.f;
    float BlendDuration = 0.f;

    // Bone cache (rebuilt when the bone container changes).
    FBone Bones[BoneCount];
    uint16 CachedSerial = 0;
    const FReferenceSkeleton* CachedSkeleton = nullptr;
    bool bBonesCached = false;
    uint32 CachedBoneKey = 0;
    FVector MeshForward = FVector(0.f, 1.f, 0.f);
    FVector MeshUp = FVector::UpVector;
    FVector MeshRight = FVector(-1.f, 0.f, 0.f);
    float WheelLateral[4] = { 0.f, 0.f, 0.f, 0.f };
    float TrailerWheelLateral[2] = { 0.f, 0.f };
    float MeasuredWheelbase = 100.f;
    float MeasuredTrailerLength = 250.f;
    /** The coupler's distance behind the mesh origin (the pawn's turning centre). */
    float MeasuredHitchOffset = 0.f;

    // Dynamics.
    float WheelSpin[4] = { 0.f, 0.f, 0.f, 0.f };
    float TrailerWheelSpin[2] = { 0.f, 0.f };
    SaskartaCarrierMath::FSpring Steer;
    float HitchRad = 0.f;
    SaskartaCarrierMath::FSpring Sway;
    SaskartaCarrierMath::FSpring TrailerPitch;
    SaskartaCarrierMath::FSpring TrailerRoll;
    SaskartaCarrierMath::FSpring TrailerBob;
    float LastTrailerMean = 0.f;
    bool bHaveTrailerMean = false;
    SaskartaCarrierMath::FSpring BodyPitch;
    SaskartaCarrierMath::FSpring BodyRoll;
    SaskartaCarrierMath::FSpring Bounce;
    float LastWheelMean = 0.f;
    bool bHaveWheelMean = false;
    float LastBodyPitchV = 0.f;
    float LastBodyRollV = 0.f;
    SaskartaCarrierMath::FSpring MastPitch;
    SaskartaCarrierMath::FSpring MastRoll;
    SaskartaCarrierMath::FSpring Lining;
    float LastBobV = 0.f;
    SaskartaCarrierMath::FSpring Rattle;
    SaskartaCarrierMath::FSpring EyeYaw;
    SaskartaCarrierMath::FSpring EyePitch;
    FVector2f SaccadeTarget = FVector2f::ZeroVector;
    float SaccadeTimer = 0.f;
    float BlinkTimer = 3.f;
    float BlinkElapsed = -1.f;
    float BlinkScale = 1.f;
    FRandomStream Rng = FRandomStream(0x5A5C);

    // Results for Evaluate / PostUpdate (degrees and cm).
    float OutSteerDeg = 0.f;
    float OutHitchDeg = 0.f;
    float OutHitchLimitDeg = 0.f;
    float OutTrailerPitchDeg = 0.f;
    float OutTrailerRollDeg = 0.f;
    float OutTrailerBobCm = 0.f;
    float OutBodyPitchDeg = 0.f;
    float OutBodyRollDeg = 0.f;
    float OutBounceCm = 0.f;
    float OutMastPitchDeg = 0.f;
    float OutMastRollDeg = 0.f;
    float OutLiningCm = 0.f;
    float OutRattleDeg = 0.f;
    float OutEyeYawDeg = 0.f;
    float OutEyePitchDeg = 0.f;
};
