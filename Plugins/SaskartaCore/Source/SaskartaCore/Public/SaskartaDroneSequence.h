// A bounded auxiliary-sensor and drone relay sequence. The story runner owns its timing.
#pragma once

#include "CoreMinimal.h"
#include "Blueprint/UserWidget.h"
#include "Engine/EngineBaseTypes.h"
#include "Subsystems/WorldSubsystem.h"
#include "TimerManager.h"
#include "SaskartaDroneSequence.generated.h"

class AActor;
class ACameraActor;
class ACharacter;
class APlayerController;
class APostProcessVolume;
class UAnimSequence;
class UAudioComponent;
class UMaterialInstanceDynamic;
class UMaterialInterface;
class UStaticMesh;
class UStaticMeshComponent;
class USoundAttenuation;
class USkeletalMesh;
class USkeletalMeshComponent;
class USplineComponent;
class USoundBase;
class USaskartaEventRunner;
class USpotLightComponent;
class UTextBlock;
struct FHitResult;

namespace SaskartaDroneLogic
{
    struct FFallPose
    {
        FVector LocalOffset = FVector::ZeroVector;
        FRotator LocalRotation = FRotator::ZeroRotator;
    };

    SASKARTACORE_API FFallPose FallPose(float CinematicSeconds);
    /** The impact ringing through the lens mount (and the fault roll), in the lens's own frame. */
    SASKARTACORE_API FRotator FallMountShake(float CinematicSeconds);
    /** The lens stays rigidly on its mount on the carrier body: only the mount's ring is added. */
    SASKARTACORE_API FTransform MountedFallView(const FTransform& MountRelative, float CinematicSeconds);
    SASKARTACORE_API float FallFaultFovDelta(float CinematicSeconds);
    /** Dust thrown on the lens at impact: 0 clean, 1 full burst; some stays on. */
    SASKARTACORE_API float FallLensDust(float CinematicSeconds);
    /** The two or three frames of torn signal and OPTICS FAULT before black. */
    SASKARTACORE_API bool FallSignalTorn(float CinematicSeconds);
    /** Upward lift (cm) that keeps every traced body point Clearance above the ground under it. */
    SASKARTACORE_API float ContactLift(TConstArrayView<float> PointZ, TConstArrayView<float> GroundZ, float ClearanceCm);
    SASKARTACORE_API FTransform ComposeFallRelative(const FTransform& Base, const FFallPose& Pose);
    SASKARTACORE_API float EchoRoundTripSeconds(float DistanceCm);
    /** Steady sonar cadence. It never speeds up near the edges: danger is carried by the echoes. */
    SASKARTACORE_API float PingPeriodSeconds();
    /** Echo loudness for a reflector DistanceCm away: the nearer road edge answers louder. */
    SASKARTACORE_API float EchoVolume(float DistanceCm);

    /** The last three pings for the point-cloud material, newest first: rgb origin (cm), a emit time (s). */
    struct SASKARTACORE_API FPingHistory
    {
        static constexpr float EmptyTimeS = -10000.f;
        FLinearColor Slots[3];
        FPingHistory() { Clear(); }
        void Clear();
        void Push(const FVector& Origin, float TimeS);
    };
    SASKARTACORE_API FVector SwarmOffset(int32 Index, float CinematicSeconds);
    /** B1 arrival: 0..1 searchlight level for drone Index. */
    SASKARTACORE_API float ArrivalLight(int32 Index, float CinematicSeconds);
    /** B1 arrival: where drone Index aims its light, carrier-local cm (drone 0 sweeps over the carrier). */
    SASKARTACORE_API FVector ArrivalLightTarget(int32 Index, float CinematicSeconds);
    /** Relay cut / feed boot brightness gain: flickers, then 1 once Age >= Duration. */
    SASKARTACORE_API float RelayFlicker(float AgeSeconds, float DurationSeconds);
    /** Relay thresholds: rear to front past 118 degrees, front to rear below 60 degrees. */
    SASKARTACORE_API int32 FeedForYaw(int32 CurrentFeed, float OrbitYawDeg);
    /** Accumulates continuous time beyond a relay threshold and resets when the look retreats. */
    SASKARTACORE_API int32 AdvanceFeedSwitch(int32 CurrentFeed, float OrbitYawDeg, float DeltaSeconds, float& WaitSeconds);
    /** Station bearing: the active drone follows the look; the other holds station inside its own side. */
    SASKARTACORE_API float StationYawForDrone(int32 DroneIndex, int32 ActiveIndex, float OrbitYawDeg);
    /** Slow altitude bob with smaller altitude hunting, cm. */
    SASKARTACORE_API FVector HoverDrift(int32 Index, float Seconds);
    /** A brief tilt and yaw disturbance every few seconds, settling between gusts. */
    SASKARTACORE_API FRotator GustTilt(int32 Index, float Seconds);

    /** Procedural flight: a lightly damped spring (overshoot, then settle) with pitch into motion,
     *  bank on turns and rotor rate following climb. Position is what the drone actor uses. */
    struct SASKARTACORE_API FDroneFlight
    {
        FVector Position = FVector::ZeroVector;
        FVector Velocity = FVector::ZeroVector;
        FVector Accel = FVector::ZeroVector;
        float PitchDeg = 0.f;
        float RollDeg = 0.f;
        float RotorRate = 1.f;
        /** 0..1 smoothed load on the motors (acceleration against the cap): drives the strain in the rotor sound. */
        float Strain = 0.f;
        /** Spring stiffness scale: the drone carrying the feed flies tighter (1.8) so the view does not trail the look. */
        float Stiffness = 1.f;
        bool bValid = false;
        void Reset(const FVector& At);
        void Step(const FVector& Target, float HeadingYawDeg, float DeltaSeconds);
    };
    SASKARTACORE_API FVector FollowOffset(float OrbitYawDeg, float OrbitPitchDeg);
    /** After the human reveal, only drone 0 tracks Samyor; drone 1 remains by the fallen carrier. */
    SASKARTACORE_API FVector HumanEscortTarget(int32 DroneIndex, const FTransform& Human,
        const FTransform& Wreck, float Seconds);
    SASKARTACORE_API float RecenterYaw(float CurrentYawDeg, float IdleSeconds, float DeltaSeconds);
    SASKARTACORE_API int32 CameraIndexForYaw(float OrbitYawDeg);
    SASKARTACORE_API float OrbitYawForDrone(int32 DroneIndex, float OrbitYawDeg);
    SASKARTACORE_API float AdvanceLaggedYaw(float CurrentDeg, float DesiredDeg, float DeltaSeconds);
    SASKARTACORE_API float AdvanceLaggedPitch(float CurrentDeg, float DesiredDeg, float DeltaSeconds);
    /** Look input as the change of the control rotation (yaw, pitch degrees), wrap-safe; a scripted snap reads as none. */
    SASKARTACORE_API FVector2D LookOrbitDelta(const FRotator& Previous, const FRotator& Current);
    /** Look degrees (control-rotation change, already carrying the player's sensitivity and invert) to orbit
     *  degrees: yaw x2.75, pitch x1.6, so a short wrist sweep carries the drone across its 180-degree side. */
    SASKARTACORE_API FVector2D OrbitFromLook(const FVector2D& LookDeg);
    struct FRotorMix { float Volume = 0.f; float Pitch = 1.f; };
    /** Rotor loop level and pitch from rotor rate, speed (cm/s) and strain; bOnCamera is the drone the feed looks through. */
    SASKARTACORE_API FRotorMix RotorMix(float RotorRate, float SpeedCmS, float Strain, bool bOnCamera);
    /** Air rush on the feed (0..~0.9) from the feed drone's speed and strain: the whoosh of a fast swing. */
    SASKARTACORE_API float WhooshLevel(float SpeedCmS, float Strain);
    struct FDownwashSample { float WidthCm = 0.f; float HeightCm = 0.f; float Opacity = 0.f; };
    /** One short, expanding dust puff; only the two carrier relay drones emit below 4.5m. */
    SASKARTACORE_API bool CanEmitDownwash(float HeightCm, bool bHumanEscort);
    SASKARTACORE_API FDownwashSample SampleDownwash(float AgeS, float HeightCm);
}

/** A small amber line in the corner of the feed: OPTICS FAULT, FEED 1, FEED 2. */
UCLASS()
class SASKARTACORE_API USaskartaFeedTagWidget : public UUserWidget
{
    GENERATED_BODY()

public:
    void ShowTag(const FString& Text, float Opacity, float JitterPx);

protected:
    virtual void NativeOnInitialized() override;

private:
    UPROPERTY(Transient)
    TObjectPtr<UTextBlock> Label;
    FString Shown;
};

UCLASS()
class SASKARTACORE_API USaskartaDroneSequenceSubsystem : public UWorldSubsystem
{
    GENERATED_BODY()

public:
    virtual bool ShouldCreateSubsystem(UObject* Outer) const override;
    virtual void OnWorldBeginPlay(UWorld& InWorld) override;
    virtual void Deinitialize() override;

    UFUNCTION(BlueprintPure, Category = "Saskarta|Drone")
    static USaskartaDroneSequenceSubsystem* GetDroneSequence(const UObject* WorldContextObject);

    UFUNCTION(BlueprintPure, Category = "Saskarta|Drone")
    bool IsAuxSensorsActive() const { return bAuxActive; }

    UFUNCTION(BlueprintPure, Category = "Saskarta|Drone")
    bool IsDroneFeedActive() const { return bDroneFeedActive; }

    UFUNCTION(BlueprintPure, Category = "Saskarta|Drone")
    AActor* GetDroneViewTarget() const;

    /** The walking traveller is watched by the physical escort drone. */
    AActor* GetHumanDroneViewTarget() const;
    bool HandoverToHumanDrone(float BlendSeconds = 0.6f);

    /** The road system can provide its exact centre/tangent; otherwise carrier heading is used. */
    UFUNCTION(BlueprintCallable, Category = "Saskarta|Drone")
    void SetRoadFrame(FVector Centre, FVector Forward, float HalfWidthCm = 225.f);

    UFUNCTION(BlueprintCallable, Category = "Saskarta|Drone")
    void AddOrbitInput(float YawDegrees, float PitchDegrees);

    UFUNCTION(BlueprintCallable, Category = "Saskarta|Drone")
    void BeginSwarm();

    UFUNCTION(BlueprintCallable, Category = "Saskarta|Drone")
    void HandoverToDrone(float BlendSeconds = 0.f);

    /** Call on title/load teardown; modes also clear through EventRunner::StopAll. */
    UFUNCTION(BlueprintCallable, Category = "Saskarta|Drone")
    void StopSequence();

    /** Reconstruct CP4's pair without replaying the swarm arrival. */
    bool RestoreHumanEscort(ACharacter* StrandedCarrier);

private:
    UFUNCTION()
    void HandleModeChanged(FName Mode, bool bOn);
    UFUNCTION()
    void HandleCinematicStarted(FName Id);
    UFUNCTION()
    void HandleCinematicFinished(FName Id);

    void Step();
    void Ping();
    void PlayEcho(FVector Location, float Volume);
    void SetAuxActive(bool bOn);
    void SetDroneFeedActive(bool bOn);
    void QueueDroneFailure(const TCHAR* Reason);
    void StopRelay(bool bDestroyDrones);
    void RestoreCarrierMesh();
    void ClearDrones();
    void BindAuxMaterial();
    void UpdateAuxMaterial(double NowS);
    void UpdateFall(float CineS);
    void UpdateFallLens(float CineS);
    void UpdateSwarm(float CineS);
    void FlyDrone(int32 Index, const FVector& Want, const FVector& Focus, float Dt);
    void UpdateDownwash(int32 Index, const FHitResult* Ground, float HeightCm);
    void DriveCarrierDuringArrival();
    void StartRelayCut(int32 FeedIndex, float Duration);
    void UpdateRelayCut(double NowS);
    void ShowTag(const FString& Text, float Seconds);
    void HandlePreActorTick(UWorld* InWorld, ELevelTick TickType, float DeltaSeconds);
    void UpdateFollow(float Dt);
    void BeginHumanEscort(ACharacter* CarrierOverride = nullptr);
    void UpdateHumanEscort(float Dt);
    void GroundEscortDroneAtRadioPost();
    void ResolveRoadFrame();
    void PollOrbitInput(float Dt);
    FVector LocalAtCarrier(const FVector& Local) const;
    ACharacter* Carrier() const;
    APlayerController* PlayerController() const;

    UPROPERTY(Transient)
    TObjectPtr<USkeletalMesh> DroneMesh;
    UPROPERTY(Transient)
    TObjectPtr<UAnimSequence> SpinClip;
    UPROPERTY(Transient)
    TObjectPtr<USoundBase> PingSound;
    UPROPERTY(Transient)
    TObjectPtr<USoundBase> ReturnSound;
    UPROPERTY(Transient)
    TObjectPtr<USoundBase> WindSound;
    UPROPERTY(Transient)
    TObjectPtr<USoundBase> RotorSound;
    UPROPERTY(Transient)
    TObjectPtr<USoundBase> ScrapeSound;
    UPROPERTY(Transient)
    TObjectPtr<USoundBase> ImpactSound;
    UPROPERTY(Transient)
    TObjectPtr<USoundBase> OpticsSound;
    UPROPERTY(Transient)
    TObjectPtr<USoundBase> ShriekSound;
    UPROPERTY(Transient)
    TObjectPtr<UMaterialInterface> DownwashMaterial;
    UPROPERTY(Transient)
    TObjectPtr<UStaticMesh> DownwashPlane;
    UPROPERTY(Transient)
    TObjectPtr<USaskartaFeedTagWidget> TagWidget;
    UPROPERTY(Transient)
    TArray<TObjectPtr<USpotLightComponent>> DroneLights;
    UPROPERTY(Transient)
    TArray<TObjectPtr<UAudioComponent>> RotorLoops;
    UPROPERTY(Transient)
    TArray<TObjectPtr<UStaticMeshComponent>> DownwashFx;
    UPROPERTY(Transient)
    TArray<TObjectPtr<UMaterialInstanceDynamic>> DownwashMids;
    UPROPERTY(Transient)
    TObjectPtr<UMaterialInstanceDynamic> AuxMid;
    UPROPERTY(Transient)
    TObjectPtr<USoundAttenuation> EchoAttenuation;
    UPROPERTY(Transient)
    TObjectPtr<USoundAttenuation> PingAttenuation;
    UPROPERTY(Transient)
    TObjectPtr<USoundAttenuation> RotorAttenuation;
    UPROPERTY(Transient)
    TObjectPtr<UAudioComponent> RotorLoop;
    UPROPERTY(Transient)
    TObjectPtr<UAudioComponent> WindLoop;
    /** The feed's air rush: the wind loop, non-spatial, level and pitch from the feed drone's speed. */
    UPROPERTY(Transient)
    TObjectPtr<UAudioComponent> WhooshLoop;

    TWeakObjectPtr<USaskartaEventRunner> Runner;
    TWeakObjectPtr<ACharacter> FallCarrier;
    TWeakObjectPtr<AActor> WreckCarrier;
    TWeakObjectPtr<USkeletalMeshComponent> FallMesh;
    TWeakObjectPtr<ACameraActor> FallViewActor;
    TWeakObjectPtr<AActor> SavedFallViewTarget;
    /** The sequence's own unbound volume carrying the aux view: nothing to find in a packaged WP world. */
    TWeakObjectPtr<APostProcessVolume> AuxVolume;
    TWeakObjectPtr<USplineComponent> RoadSpline;
    TArray<TWeakObjectPtr<AActor>> Drones;
    FTransform SavedMeshRelative;
    FTransform WreckPose;
    FVector EndingDroneRest = FVector::ZeroVector;
    FTransform SavedFallViewRelative;
    FTimerHandle PausedGroundTimer;
    FVector RoadCentre = FVector::ZeroVector;
    FVector RoadForward = FVector::ForwardVector;
    float RoadHalfWidthCm = 225.f;
    float SavedFallViewFov = 75.f;
    float OrbitYawDeg = 0.f;
    float OrbitPitchDeg = -11.27f;
    float DesiredOrbitYawDeg = 0.f;
    float DesiredOrbitPitchDeg = -11.27f;
    float FeedSwitchWaitS = 0.f;
    float LastLookS = -1000.f;
    FRotator LastControlRot = FRotator::ZeroRotator;
    bool bLookBaseline = false;
    SaskartaDroneLogic::FPingHistory PingHistory;
    float SwarmStartS = -1.f;
    float DepartureStartS = -1.f;
    float LastRoadSearchS = -1000.f;
    int32 AuxBlendIndex = INDEX_NONE;
    int32 ActiveDroneIndex = 0;
    bool bAuxActive = false;
    bool bDroneFeedActive = false;
    bool bHumanEscort = false;
    bool bEndingDroneGrounded = false;
    bool bPendingAuxFallback = false;
    bool bFallActive = false;
    bool bGroundTimerPaused = false;
    bool bSwarmActive = false;
    bool bSwarmPending = false;
    bool bDeparting = false;
    bool bScrapePlayed = false;
    bool bShriekPlayed = false;
    bool bFeedBooted = false;
    bool bArrivalDriving = false;
    FDelegateHandle PreTickHandle;
    SaskartaDroneLogic::FDroneFlight Flights[2];
    float NextPuffS[2] = {0.f, 0.f};
    float PuffStartS[2] = {-1000.f, -1000.f};
    float PuffHeightCm[2] = {450.f, 450.f};
    FVector PuffOrigin[2] = {FVector::ZeroVector, FVector::ZeroVector};
    FVector PuffNormal[2] = {FVector::UpVector, FVector::UpVector};
    float RelayCutStartS = -1000.f;
    float RelayCutDurationS = 0.2f;
    int32 RelayCutFeed = 0;
    float TagUntilS = -1000.f;
    float TagStartS = -1000.f;
    FString TagText;
    bool bImpactPlayed = false;
    bool bOpticsPlayed = false;
    bool bRoadFrameFresh = false;
    FTimerHandle StepTimer;
    FTimerHandle PingTimer;
    TArray<FTimerHandle> EchoTimers;
};
