// Capture guard, the pure part (task CAPTURE-CPP). See SaskartaCaptureGuard.h for the subsystem.
//
// Engine-free and deterministic (time is passed in), so the automation tests drive it directly:
//   - Classify: which role a scene capture has, from its owner's name / editor label, its tags,
//     its owner's class chain and its render target's name.
//   - FSaskartaLoadingPhaseTracker: Startup -> Loading -> Linger -> Play -> Loading ... from one
//     "is the loading screen up" bool per poll.
//   - Decide: what the guard does with a capture of a role in a phase (leave / on / off).
//   - ShouldAudit: whether an unmanaged capture earns the one-time "captures every frame" warning.
//
// Roles:
//   LoadingOnly  the Keeper point cloud's offstage capture (KeeperPointCloud_Capture, drawing into
//                RT_Saskarta_LoadingTraveller), or anything tagged Saskarta.LoadingCapture.
//                Every frame while the loading screen is up; off (bCaptureEveryFrame false,
//                component deactivated) from LingerS after it goes away until the next loading.
//   Stray        editor leftovers: Look_TempCapture*, HaybaMCPCaptureActor (class, tag or name),
//                anything tagged Saskarta.StrayCapture, plus the saskarta.captureguard.ExtraStrays
//                prefixes. Off for the whole game.
//   Unmanaged    everything else: never touched; audited (one warning each) when it captures every
//                frame.
// Name rules are case-insensitive prefixes, so Look_TempCapture_0 / _1 match Look_TempCapture. The
// label only exists in editor builds (PIE); a cooked game still matches the Keeper capture by its
// render target's name, and by tags.
//
// Phases:
//   Startup  from world BeginPlay until the first loading signal (captures left as authored). With
//            no loading signal for StartGraceS (a debug start that skips the intro), Play.
//   Loading  the loading screen is up: LoadingOnly captures on.
//   Linger   LingerS after the loading signal drops (the loading widget's own fade covers most of
//            it; this is the margin). A new loading signal goes straight back to Loading.
//   Play     LoadingOnly captures off.

#pragma once

#include "CoreMinimal.h"

/** What the guard does with one scene capture. */
enum class ESaskartaCaptureRole : uint8
{
    /** Not the guard's: left alone; audited when it captures every frame. */
    Unmanaged,
    /** Feeds a loading screen (the Keeper point cloud): every frame while loading, off in play. */
    LoadingOnly,
    /** An editor leftover (Look_TempCapture*, HaybaMCPCaptureActor): off for the whole game. */
    Stray,
};

/** Where the game is relative to the loading screen. */
enum class ESaskartaCapturePhase : uint8
{
    Startup,
    Loading,
    Linger,
    Play,
};

/** What to do with a capture now. */
enum class ESaskartaCaptureCommand : uint8
{
    /** Leave it as it is. */
    Leave,
    /** Capture every frame, component active. */
    On,
    /** No every-frame or on-movement capture, component deactivated. */
    Off,
};

/** One scene capture as the classifier sees it (the subsystem fills it from the component). */
struct SASKARTACORE_API FSaskartaCaptureIdentity
{
    /** The owner actor's object name (SceneCapture2D_UAID_..., HaybaMCPCaptureActor_UAID_...). */
    FString ActorName;
    /** The owner's editor label (KeeperPointCloud_Capture, Look_TempCapture_0); empty in a cooked game. */
    FString ActorLabel;
    /** The owner actor's tags and the component's tags. */
    TArray<FName> Tags;
    /** The owner's class and its super classes, most derived first (HaybaMCPCaptureActor, Actor, Object). */
    TArray<FString> ClassNames;
    /** The render target's object name (RT_Saskarta_LoadingTraveller); empty without one. */
    FString TextureTargetName;
};

struct SASKARTACORE_API FSaskartaCaptureGuardLogic
{
    /** Tag an actor or capture component with this to make it LoadingOnly. */
    static const FName LoadingTag;
    /** Tag an actor or capture component with this to make it a Stray (off for the whole game). */
    static const FName StrayTag;

    /** Names (actor name, label or tag prefixes) that make a capture LoadingOnly. */
    static const TArray<FString>& LoadingNames();
    /** Render target names that make a capture LoadingOnly. */
    static const TArray<FString>& LoadingTargets();
    /** Names (actor name, label, tag or class-name prefixes) that make a capture a Stray. */
    static const TArray<FString>& StrayNames();

    /**
     * The capture's role. LoadingOnly wins over Stray (a tagged loading capture is never switched
     * off during loading). ExtraStrayPrefixes are added to StrayNames (the CVar list).
     */
    static ESaskartaCaptureRole Classify(const FSaskartaCaptureIdentity& Id, const TArray<FString>& ExtraStrayPrefixes);

    /** What to do with a capture of Role in Phase. */
    static ESaskartaCaptureCommand Decide(ESaskartaCaptureRole Role, ESaskartaCapturePhase Phase,
        bool bHasVisibleConsumer = true);

    /** True when an unmanaged, active capture renders every frame and has not been reported yet. */
    static bool ShouldAudit(ESaskartaCaptureRole Role, bool bCaptureEveryFrame, bool bComponentActive, bool bAlreadyWarned);

    /** "a, b,,c " -> {a, b, c}. */
    static TArray<FString> ParseList(const FString& Csv);

    static const TCHAR* RoleName(ESaskartaCaptureRole Role);
    static const TCHAR* PhaseName(ESaskartaCapturePhase Phase);
    static const TCHAR* CommandName(ESaskartaCaptureCommand Command);

private:
    static bool MatchesAnyPrefix(const FString& Value, const TArray<FString>& Prefixes);
    static bool MatchesAny(const FSaskartaCaptureIdentity& Id, const TArray<FString>& Prefixes, bool bIncludeClasses);
};

/** The loading-screen phase from one bool per poll (see the header comment). */
struct SASKARTACORE_API FSaskartaLoadingPhaseTracker
{
    /** Startup -> Play when no loading signal comes this long after BeginPlay. */
    double StartGraceS = 8.0;
    /** Loading -> Play this long after the loading signal drops. */
    double LingerS = 1.5;

    /** World BeginPlay: Startup from NowS. */
    void Start(double NowS);

    /** One poll. Returns true when the phase changed (GetPhase is the new one). No-op before Start. */
    bool Update(double NowS, bool bLoading);

    ESaskartaCapturePhase GetPhase() const { return Phase; }
    bool HasStarted() const { return bStarted; }
    /** How many loading windows began since Start. */
    int32 GetLoadingCount() const { return LoadingCount; }
    /** When the current phase began. */
    double GetPhaseSinceS() const { return PhaseSinceS; }

private:
    void Enter(ESaskartaCapturePhase NewPhase, double NowS);

    ESaskartaCapturePhase Phase = ESaskartaCapturePhase::Startup;
    double PhaseSinceS = 0.0;
    int32 LoadingCount = 0;
    bool bStarted = false;
};
