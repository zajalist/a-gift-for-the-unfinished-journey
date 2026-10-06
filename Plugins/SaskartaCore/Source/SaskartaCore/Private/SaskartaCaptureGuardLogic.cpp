// Capture guard, the pure part (task CAPTURE-CPP). See SaskartaCaptureGuardLogic.h.

#include "SaskartaCaptureGuardLogic.h"

const FName FSaskartaCaptureGuardLogic::LoadingTag(TEXT("Saskarta.LoadingCapture"));
const FName FSaskartaCaptureGuardLogic::StrayTag(TEXT("Saskarta.StrayCapture"));

const TArray<FString>& FSaskartaCaptureGuardLogic::LoadingNames()
{
    // Tools/Look/build_keeper_pointcloud.py stages the capture as "KeeperPointCloud_Capture".
    static const TArray<FString> Names = { TEXT("KeeperPointCloud_Capture") };
    return Names;
}

const TArray<FString>& FSaskartaCaptureGuardLogic::LoadingTargets()
{
    // The point cloud's render target: the one name that survives cooking (labels do not).
    static const TArray<FString> Targets = { TEXT("RT_Saskarta_LoadingTraveller") };
    return Targets;
}

const TArray<FString>& FSaskartaCaptureGuardLogic::StrayNames()
{
    // Look_TempCapture / _0 / _1: LOOK and LANE4 viewport captures left in the level.
    // HaybaMCPCaptureActor: the Hayba MCP screenshot helper (class, tag and label all use it).
    static const TArray<FString> Names = { TEXT("Look_TempCapture"), TEXT("HaybaMCPCaptureActor") };
    return Names;
}

bool FSaskartaCaptureGuardLogic::MatchesAnyPrefix(const FString& Value, const TArray<FString>& Prefixes)
{
    if (Value.IsEmpty())
    {
        return false;
    }
    for (const FString& P : Prefixes)
    {
        if (!P.IsEmpty() && Value.StartsWith(P, ESearchCase::IgnoreCase))
        {
            return true;
        }
    }
    return false;
}

bool FSaskartaCaptureGuardLogic::MatchesAny(const FSaskartaCaptureIdentity& Id, const TArray<FString>& Prefixes, bool bIncludeClasses)
{
    if (MatchesAnyPrefix(Id.ActorLabel, Prefixes) || MatchesAnyPrefix(Id.ActorName, Prefixes))
    {
        return true;
    }
    for (const FName& Tag : Id.Tags)
    {
        if (MatchesAnyPrefix(Tag.ToString(), Prefixes))
        {
            return true;
        }
    }
    if (bIncludeClasses)
    {
        for (const FString& C : Id.ClassNames)
        {
            if (MatchesAnyPrefix(C, Prefixes))
            {
                return true;
            }
        }
    }
    return false;
}

ESaskartaCaptureRole FSaskartaCaptureGuardLogic::Classify(const FSaskartaCaptureIdentity& Id, const TArray<FString>& ExtraStrayPrefixes)
{
    // LoadingOnly first: a loading capture is never switched off while the loading screen is up.
    if (Id.Tags.Contains(LoadingTag)
        || MatchesAny(Id, LoadingNames(), false)
        || (!Id.TextureTargetName.IsEmpty() && LoadingTargets().ContainsByPredicate(
               [&Id](const FString& T) { return T.Equals(Id.TextureTargetName, ESearchCase::IgnoreCase); })))
    {
        return ESaskartaCaptureRole::LoadingOnly;
    }
    if (Id.Tags.Contains(StrayTag)
        || MatchesAny(Id, StrayNames(), true)
        || MatchesAny(Id, ExtraStrayPrefixes, true))
    {
        return ESaskartaCaptureRole::Stray;
    }
    return ESaskartaCaptureRole::Unmanaged;
}

ESaskartaCaptureCommand FSaskartaCaptureGuardLogic::Decide(ESaskartaCaptureRole Role, ESaskartaCapturePhase Phase,
    bool bHasVisibleConsumer)
{
    if (Role == ESaskartaCaptureRole::Stray)
    {
        return ESaskartaCaptureCommand::Off;
    }
    if (Role != ESaskartaCaptureRole::LoadingOnly)
    {
        return ESaskartaCaptureCommand::Leave;
    }
    // Preloading the world does not imply that any UI consumes this expensive scene render.
    if (!bHasVisibleConsumer)
    {
        return ESaskartaCaptureCommand::Off;
    }
    if (Phase == ESaskartaCapturePhase::Loading)
    {
        return ESaskartaCaptureCommand::On;
    }
    if (Phase == ESaskartaCapturePhase::Play)
    {
        return ESaskartaCaptureCommand::Off;
    }
    // Startup: as authored (on) until the loading screen shows or the grace runs out.
    // Linger: still on from Loading, until the loading widget has faded away.
    return ESaskartaCaptureCommand::Leave;
}

bool FSaskartaCaptureGuardLogic::ShouldAudit(ESaskartaCaptureRole Role, bool bCaptureEveryFrame, bool bComponentActive, bool bAlreadyWarned)
{
    return Role == ESaskartaCaptureRole::Unmanaged && bCaptureEveryFrame && bComponentActive && !bAlreadyWarned;
}

TArray<FString> FSaskartaCaptureGuardLogic::ParseList(const FString& Csv)
{
    TArray<FString> Parts;
    Csv.ParseIntoArray(Parts, TEXT(","), true);
    TArray<FString> Out;
    for (FString& P : Parts)
    {
        P.TrimStartAndEndInline();
        if (!P.IsEmpty())
        {
            Out.Add(MoveTemp(P));
        }
    }
    return Out;
}

const TCHAR* FSaskartaCaptureGuardLogic::RoleName(ESaskartaCaptureRole Role)
{
    switch (Role)
    {
    case ESaskartaCaptureRole::LoadingOnly: return TEXT("loading-only");
    case ESaskartaCaptureRole::Stray: return TEXT("stray");
    case ESaskartaCaptureRole::Unmanaged:
    default: return TEXT("unmanaged");
    }
}

const TCHAR* FSaskartaCaptureGuardLogic::PhaseName(ESaskartaCapturePhase Phase)
{
    switch (Phase)
    {
    case ESaskartaCapturePhase::Loading: return TEXT("Loading");
    case ESaskartaCapturePhase::Linger: return TEXT("Linger");
    case ESaskartaCapturePhase::Play: return TEXT("Play");
    case ESaskartaCapturePhase::Startup:
    default: return TEXT("Startup");
    }
}

const TCHAR* FSaskartaCaptureGuardLogic::CommandName(ESaskartaCaptureCommand Command)
{
    switch (Command)
    {
    case ESaskartaCaptureCommand::On: return TEXT("on");
    case ESaskartaCaptureCommand::Off: return TEXT("off");
    case ESaskartaCaptureCommand::Leave:
    default: return TEXT("leave");
    }
}

// ============================================================================ phase tracker

void FSaskartaLoadingPhaseTracker::Start(double NowS)
{
    bStarted = true;
    LoadingCount = 0;
    Phase = ESaskartaCapturePhase::Startup;
    PhaseSinceS = NowS;
}

void FSaskartaLoadingPhaseTracker::Enter(ESaskartaCapturePhase NewPhase, double NowS)
{
    if (NewPhase == ESaskartaCapturePhase::Loading)
    {
        ++LoadingCount;
    }
    Phase = NewPhase;
    PhaseSinceS = NowS;
}

bool FSaskartaLoadingPhaseTracker::Update(double NowS, bool bLoading)
{
    if (!bStarted)
    {
        return false;
    }
    const ESaskartaCapturePhase Before = Phase;
    // At most two steps per poll (Loading -> Linger -> Play when LingerS is 0).
    for (int32 Step = 0; Step < 2; ++Step)
    {
        const double InPhaseS = NowS - PhaseSinceS;
        switch (Phase)
        {
        case ESaskartaCapturePhase::Startup:
            if (bLoading)
            {
                Enter(ESaskartaCapturePhase::Loading, NowS);
            }
            else if (InPhaseS >= StartGraceS)
            {
                Enter(ESaskartaCapturePhase::Play, NowS);
            }
            break;
        case ESaskartaCapturePhase::Loading:
            if (!bLoading)
            {
                Enter(ESaskartaCapturePhase::Linger, NowS);
                continue;
            }
            break;
        case ESaskartaCapturePhase::Linger:
            if (bLoading)
            {
                // Back to loading within the margin: the captures are still on, no off/on churn.
                // Not a new loading window.
                Phase = ESaskartaCapturePhase::Loading;
                PhaseSinceS = NowS;
            }
            else if (InPhaseS >= LingerS)
            {
                Enter(ESaskartaCapturePhase::Play, NowS);
            }
            break;
        case ESaskartaCapturePhase::Play:
            if (bLoading)
            {
                Enter(ESaskartaCapturePhase::Loading, NowS);
            }
            break;
        }
        break;
    }
    return Phase != Before;
}
