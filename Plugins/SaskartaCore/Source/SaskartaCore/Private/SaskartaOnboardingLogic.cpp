#include "SaskartaOnboardingLogic.h"

#include "Dom/JsonObject.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"

namespace SaskartaOnboardingLogic
{
    static const FName Done(TEXT("done"));
    static const FName Timeout(TEXT("timeout"));
    static const FName Blocked(TEXT("blocked"));

    static TArray<FName> Names(const TSharedPtr<FJsonObject>& O, const TCHAR* Field)
    {
        TArray<FName> Out;
        const TArray<TSharedPtr<FJsonValue>>* Arr = nullptr;
        if (O->TryGetArrayField(Field, Arr))
        {
            for (const TSharedPtr<FJsonValue>& V : *Arr)
            {
                FString S;
                if (V.IsValid() && V->TryGetString(S) && !S.IsEmpty())
                {
                    Out.Add(FName(*S));
                }
            }
        }
        return Out;
    }
}

int32 FSaskartaOnboardingCore::FindHint(FName Id) const
{
    return Hints.IndexOfByPredicate([Id](const FSaskartaHintDef& H) { return H.Id == Id; });
}

bool FSaskartaOnboardingCore::TokenHolds(FName Token, const FSaskartaHintFacts& Facts)
{
    const FString S = Token.ToString();
    if (S.StartsWith(TEXT("!")))
    {
        return !Facts.Conditions.Contains(FName(*S.Mid(1)));
    }
    return Facts.Conditions.Contains(Token) || Facts.Actions.Contains(Token);
}

bool FSaskartaOnboardingCore::TriggerHolds(const FSaskartaHintDef& Hint, const FSaskartaHintFacts& Facts)
{
    for (const FName& C : Hint.When)
    {
        if (!TokenHolds(C, Facts))
        {
            return false;
        }
    }
    if (Hint.FromRoadM >= 0.f || Hint.ToRoadM >= 0.f)
    {
        if (Facts.RoadM < 0.f)
        {
            return false;
        }
        if (Hint.FromRoadM >= 0.f && Facts.RoadM < Hint.FromRoadM)
        {
            return false;
        }
        if (Hint.ToRoadM >= 0.f && Facts.RoadM > Hint.ToRoadM)
        {
            return false;
        }
    }
    return true;
}

bool FSaskartaOnboardingCore::IsDone(const FSaskartaHintDef& Hint, const FSaskartaHintFacts& Facts)
{
    for (const FName& T : Hint.DoneWhen)
    {
        if (TokenHolds(T, Facts))
        {
            return true;
        }
    }
    return false;
}

FString FSaskartaOnboardingCore::TextFor(const FSaskartaHintDef& Hint, bool bGamepad)
{
    return bGamepad && !Hint.PadText.IsEmpty() ? Hint.PadText : Hint.Text;
}

FSaskartaHintStep FSaskartaOnboardingCore::Step(const FSaskartaHintFacts& F)
{
    using namespace SaskartaOnboardingLogic;
    if (!F.bBlocked)
    {
        Known.Append(F.Actions);
        Known.Append(F.Conditions);
    }

    // Trigger clocks for the hints that can still show.
    for (const FSaskartaHintDef& H : Hints)
    {
        if (F.bBlocked || Seen.Contains(H.Id) || !TriggerHolds(H, F))
        {
            TrueSinceS.Remove(H.Id);
        }
        else if (!TrueSinceS.Contains(H.Id))
        {
            TrueSinceS.Add(H.Id, F.NowS);
        }
    }

    FSaskartaHintStep Out;
    if (Hints.IsValidIndex(Active))
    {
        const FSaskartaHintDef& H = Hints[Active];
        FName Reason;
        if (F.bBlocked)
        {
            Reason = Blocked;
            if (F.NowS - ActiveSinceS < MinReadS)
            {
                Seen.Remove(H.Id); // barely seen: it may come back
            }
        }
        else if (IsDone(H, F))
        {
            Reason = Done;
        }
        else if (F.NowS - ActiveSinceS >= H.HoldS)
        {
            Reason = Timeout;
        }
        if (!Reason.IsNone())
        {
            Out.Event = ESaskartaHintEvent::Hide;
            Out.Hint = Active;
            Out.Reason = Reason;
            Active = INDEX_NONE;
            LastHideS = F.NowS;
        }
        return Out;
    }
    Active = INDEX_NONE;
    if (F.bBlocked || F.NowS - LastHideS < GapS)
    {
        return Out;
    }

    int32 Best = INDEX_NONE;
    for (int32 I = 0; I < Hints.Num(); ++I)
    {
        const FSaskartaHintDef& H = Hints[I];
        const double* Since = TrueSinceS.Find(H.Id);
        if (Seen.Contains(H.Id) || !Since || F.NowS - *Since < H.DelayS)
        {
            continue;
        }
        bool bAfterOk = true;
        for (const FName& A : H.After)
        {
            bAfterOk &= Seen.Contains(A);
        }
        if (!bAfterOk)
        {
            continue;
        }
        if (H.bSkipIfKnown)
        {
            bool bKnown = false;
            for (const FName& T : H.DoneWhen)
            {
                bKnown |= !T.ToString().StartsWith(TEXT("!")) && Known.Contains(T);
            }
            if (bKnown)
            {
                Seen.Add(H.Id); // the player already does it: never teach it
                TrueSinceS.Remove(H.Id);
                continue;
            }
        }
        if (IsDone(H, F))
        {
            continue;
        }
        if (Best == INDEX_NONE || H.Priority > Hints[Best].Priority)
        {
            Best = I;
        }
    }
    if (Best != INDEX_NONE)
    {
        Active = Best;
        ActiveSinceS = F.NowS;
        Seen.Add(Hints[Best].Id);
        Out.Event = ESaskartaHintEvent::Show;
        Out.Hint = Best;
    }
    return Out;
}

bool FSaskartaOnboardingCore::ParseJson(const FString& Json, FString& OutError)
{
    using namespace SaskartaOnboardingLogic;
    TSharedPtr<FJsonObject> Root;
    const TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(Json);
    if (!FJsonSerializer::Deserialize(Reader, Root) || !Root.IsValid())
    {
        OutError = TEXT("onboarding.json: not valid JSON");
        return false;
    }
    double Number = 0.0;
    if (Root->TryGetNumberField(TEXT("gap_s"), Number))
    {
        GapS = static_cast<float>(Number);
    }
    float DefaultHold = 8.f;
    if (Root->TryGetNumberField(TEXT("hold_s"), Number))
    {
        DefaultHold = static_cast<float>(Number);
    }
    const TArray<TSharedPtr<FJsonValue>>* List = nullptr;
    if (!Root->TryGetArrayField(TEXT("hints"), List))
    {
        OutError = TEXT("onboarding.json: no \"hints\" array");
        return false;
    }
    TArray<FSaskartaHintDef> Parsed;
    for (const TSharedPtr<FJsonValue>& V : *List)
    {
        const TSharedPtr<FJsonObject>* O = nullptr;
        if (!V.IsValid() || !V->TryGetObject(O) || !O || !O->IsValid())
        {
            continue;
        }
        const TSharedPtr<FJsonObject>& H = *O;
        FSaskartaHintDef D;
        FString S;
        if (!H->TryGetStringField(TEXT("id"), S) || S.IsEmpty())
        {
            OutError = TEXT("onboarding.json: a hint without an id");
            return false;
        }
        D.Id = FName(*S);
        H->TryGetStringField(TEXT("text"), D.Text);
        H->TryGetStringField(TEXT("pad_text"), D.PadText);
        if (D.Text.IsEmpty())
        {
            OutError = FString::Printf(TEXT("onboarding.json: hint %s has no text"), *D.Id.ToString());
            return false;
        }
        D.When = Names(H, TEXT("when"));
        D.After = Names(H, TEXT("after"));
        D.DoneWhen = Names(H, TEXT("done_when"));
        const TArray<TSharedPtr<FJsonValue>>* Road = nullptr;
        if (H->TryGetArrayField(TEXT("road_m"), Road) && Road->Num() == 2)
        {
            D.FromRoadM = static_cast<float>((*Road)[0]->AsNumber());
            D.ToRoadM = static_cast<float>((*Road)[1]->AsNumber());
        }
        D.DelayS = H->TryGetNumberField(TEXT("delay_s"), Number) ? static_cast<float>(Number) : 0.f;
        D.HoldS = H->TryGetNumberField(TEXT("hold_s"), Number) ? static_cast<float>(Number) : DefaultHold;
        D.Priority = H->TryGetNumberField(TEXT("priority"), Number) ? static_cast<int32>(Number) : 0;
        bool bFlag = false;
        D.bSkipIfKnown = H->TryGetBoolField(TEXT("skip_if_known"), bFlag) && bFlag;
        Parsed.Add(MoveTemp(D));
    }
    Hints = MoveTemp(Parsed);
    return true;
}
