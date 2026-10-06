// FSaskartaPromptLogic. See the header.

#include "SaskartaPromptLogic.h"

#include "SaskartaEventTypes.h"

bool FSaskartaPromptLogic::ShouldRemind(double ShownS, double SinceRemindS)
{
    if (ShownS < FirstRemindS)
    {
        return false;
    }
    return SinceRemindS < 0.0 || SinceRemindS >= RemindEveryS;
}

FString FSaskartaPromptLogic::CrtLine(const FString& PromptText)
{
    FString S = PromptText.TrimStartAndEnd();
    while (S.EndsWith(TEXT(".")))
    {
        S.LeftChopInline(1);
    }
    S = S.TrimEnd().ToUpper();
    return S.IsEmpty() ? FString(TEXT("PRESS E / A")) : S + TEXT("  -  PRESS E / A");
}

FString FSaskartaPromptLogic::OverlayLine(const FString& PromptText)
{
    const FString S = PromptText.TrimStartAndEnd();
    return S.IsEmpty() ? FString(TEXT("[E] / (A)")) : S + TEXT("     [E] / (A)");
}

bool FSaskartaPromptLogic::ParseDataLayerRef(const FString& RevealId, FString& OutRef)
{
    OutRef.Reset();
    if (!RevealId.StartsWith(TEXT("DL:"), ESearchCase::CaseSensitive))
    {
        return false;
    }
    OutRef = RevealId.Mid(3).TrimStartAndEnd();
    return !OutRef.IsEmpty();
}

bool FSaskartaPromptLogic::DataLayerAssetMatches(const FString& Ref, const FString& AssetName, const FString& AssetObjectPath)
{
    if (Ref.IsEmpty())
    {
        return false;
    }
    if (Ref.StartsWith(TEXT("/")))
    {
        if (Ref.Equals(AssetObjectPath, ESearchCase::IgnoreCase))
        {
            return true;
        }
        FString Package = AssetObjectPath;
        int32 Dot = INDEX_NONE;
        if (Package.FindLastChar(TEXT('.'), Dot))
        {
            Package.LeftInline(Dot);
        }
        return Ref.Equals(Package, ESearchCase::IgnoreCase);
    }
    return Ref.Equals(AssetName, ESearchCase::IgnoreCase);
}

bool FSaskartaPromptLogic::RunsWithoutSequence(const FSaskartaEventAction& Cue)
{
    switch (Cue.Type)
    {
    case ESaskartaActionType::SetFlowState:
        return true;
    case ESaskartaActionType::CallHook:
        return Cue.Id == FName(TEXT("Cine_ClearBlack"));
    default:
        return false;
    }
}
