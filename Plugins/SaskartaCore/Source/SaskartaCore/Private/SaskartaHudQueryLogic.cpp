#include "SaskartaHudQueryLogic.h"

const FName FSaskartaHudLane::ColumnTarget(TEXT("HudColumn"));
const FName FSaskartaHudLane::StatusTarget(TEXT("HudStatus"));
const FName FSaskartaHudLane::PriorityTarget(TEXT("HudPriority"));

namespace
{
    void Emit(TArray<FSaskartaHudOutput>& Out, ESaskartaHudOut Kind, const FString& Text = FString(), float DurationS = 0.f)
    {
        FSaskartaHudOutput O;
        O.Kind = Kind;
        O.Text = Text;
        O.DurationS = DurationS;
        Out.Add(MoveTemp(O));
    }
}

void FSaskartaHudLane::Push(FSaskartaHudItem Item, double NowS, bool bHeld, TArray<FSaskartaHudOutput>& Out)
{
    Item.QueuedAtS = NowS;
    if (Item.bImmediate)
    {
        if (bActive && !Active.bImmediate && !bInResult)
        {
            Active.QueuedAtS = NowS;
            Pending.Insert(Active, 0);
        }
        else if (bActive)
        {
            Finish(false, Out);
        }
        bActive = false;
        Start(MoveTemp(Item), NowS, Out);
        return;
    }
    if (Item.bPriority)
    {
        const int32 At = Pending.IndexOfByPredicate([](const FSaskartaHudItem& P) { return !P.bPriority; });
        Pending.Insert(MoveTemp(Item), At == INDEX_NONE ? Pending.Num() : At);
    }
    else
    {
        Pending.Add(MoveTemp(Item));
    }
    Advance(NowS, bHeld, Out);
}

void FSaskartaHudLane::NoteExternalLine(double NowS, float DurationS, TArray<FSaskartaHudOutput>& Out)
{
    // +0.15 s: the caption's own hide timer fires before a query takes the line.
    ExternalBusyUntilS = FMath::Max(ExternalBusyUntilS, NowS + FMath::Max(DurationS, 0.5f) + 0.15);
    if (!bActive)
    {
        return;
    }
    // The POI line now owns HudLine. A query still asking goes back to the front; one already showing
    // its result is done (the line is not hidden under the POI's).
    if (!bInResult && !Active.bImmediate)
    {
        Active.QueuedAtS = NowS;
        Pending.Insert(Active, 0);
        bActive = false;
    }
    else
    {
        Finish(false, Out);
    }
}

void FSaskartaHudLane::Advance(double NowS, bool bHeld, TArray<FSaskartaHudOutput>& Out)
{
    if (bActive && NowS >= PhaseEndS)
    {
        if (!bInResult && !Active.Result.IsEmpty())
        {
            bInResult = true;
            PhaseEndS = NowS + Active.ResultS;
            Emit(Out, ESaskartaHudOut::ShowLine, Active.Result, Active.ResultS);
        }
        else
        {
            Finish(true, Out);
        }
    }
    if (bActive)
    {
        return;
    }
    if (bHeld)
    {
        for (FSaskartaHudItem& P : Pending)
        {
            P.QueuedAtS = NowS;
        }
        return;
    }
    Pending.RemoveAll([NowS](const FSaskartaHudItem& P) { return !P.bPriority && NowS - P.QueuedAtS > MaxWaitS; });
    if (Pending.Num() > 0 && NowS >= ExternalBusyUntilS)
    {
        FSaskartaHudItem Next = Pending[0];
        Pending.RemoveAt(0);
        Start(MoveTemp(Next), NowS, Out);
    }
}

void FSaskartaHudLane::Start(FSaskartaHudItem Item, double NowS, TArray<FSaskartaHudOutput>& Out)
{
    Active = MoveTemp(Item);
    bActive = true;
    bInResult = false;
    PhaseEndS = NowS + Active.QueryS;
    Emit(Out, ESaskartaHudOut::Tick);
    Emit(Out, ESaskartaHudOut::ShowLine, Active.Query, Active.QueryS);
}

void FSaskartaHudLane::Finish(bool bHide, TArray<FSaskartaHudOutput>& Out)
{
    if (bHide)
    {
        Emit(Out, ESaskartaHudOut::HideLine);
    }
    bActive = false;
    bInResult = false;
}

void FSaskartaHudLane::SetColumnVisible(bool bVisible, TArray<FSaskartaHudOutput>& Out)
{
    bColumnVisible = bVisible;
    if (bVisible && !Column.IsEmpty())
    {
        Emit(Out, ESaskartaHudOut::ShowColumn, Column);
    }
    else if (!bVisible)
    {
        Emit(Out, ESaskartaHudOut::HideColumn);
    }
}

void FSaskartaHudLane::SetStatus(const FString& Status, TArray<FSaskartaHudOutput>& Out)
{
    if (Status == Column)
    {
        return;
    }
    Column = Status;
    if (!bColumnVisible)
    {
        return;
    }
    Emit(Out, Column.IsEmpty() ? ESaskartaHudOut::HideColumn : ESaskartaHudOut::ShowColumn, Column);
}

void FSaskartaHudLane::Reset(TArray<FSaskartaHudOutput>& Out)
{
    if (bActive)
    {
        Emit(Out, ESaskartaHudOut::HideLine);
    }
    Pending.Reset();
    bActive = false;
    bInResult = false;
    ExternalBusyUntilS = -1.0;
}

bool FSaskartaHudLane::ItemFromAction(const FSaskartaEventAction& A, FSaskartaHudItem& Out)
{
    if (A.Type != ESaskartaActionType::ShowHudQuery || A.TargetTag == ColumnTarget || A.TargetTag == StatusTarget || A.Text.IsEmpty())
    {
        return false;
    }
    Out = FSaskartaHudItem();
    Out.Id = A.Id;
    Out.Query = A.Text.ToString();
    Out.Result = A.ResultText.ToString();
    Out.QueryS = A.DurationS > 0.f ? A.DurationS : DefaultQueryS;
    Out.ResultS = A.Value > 0.f ? A.Value : DefaultResultS;
    Out.bPriority = A.TargetTag == PriorityTarget;
    return true;
}

bool FSaskartaHudLane::IsHudOnlyBeat(const FSaskartaBeatDef& Beat)
{
    if (Beat.Actions.Num() == 0)
    {
        return false;
    }
    for (const FSaskartaEventAction& A : Beat.Actions)
    {
        if (A.Type != ESaskartaActionType::ShowHudQuery)
        {
            return false;
        }
    }
    return true;
}
