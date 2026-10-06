// Stele scan: the pure decisions. See SaskartaSteleScanLogic.h and docs/look/STELE_SCAN.md section 3.

#include "SaskartaSteleScanLogic.h"

void FSaskartaSteleScanCore::SortByRoad()
{
    Steles.Sort([](const FStele& A, const FStele& B) { return A.RoadM < B.RoadM; });
}

int32 FSaskartaSteleScanCore::FindStele(FName Id) const
{
    return Steles.IndexOfByPredicate([Id](const FStele& S) { return S.Id == Id; });
}

void FSaskartaSteleScanCore::ResetReadings()
{
    for (FStele& S : Steles)
    {
        S.bRead = false;
    }
    Numbers.Reset();
    Completed.Reset();
    TextOnlyFullReads.Reset();
    BusyUntilS = 0.0;
}

void FSaskartaSteleScanCore::Candidates(float RoadM, const FSaskartaSteleScanTuning& T, TArray<int32>& Out) const
{
    Out.Reset();
    for (int32 I = 0; I < Steles.Num(); ++I)
    {
        const FStele& S = Steles[I];
        if (!S.bRead && S.RoadM >= RoadM - T.BehindM && S.RoadM <= RoadM + T.AheadM)
        {
            Out.Add(I);
        }
    }
}

bool FSaskartaSteleScanCore::Eligible(const FSaskartaSteleView& V, bool bDock, const FSaskartaSteleScanTuning& T)
{
    const float MaxAngle = bDock ? T.DockViewDeg : T.MaxViewDeg;
    return V.bLineOfSight
        && V.DistanceM >= T.MinRangeM && V.DistanceM <= T.RangeM
        && V.ViewAngleDeg <= MaxAngle
        && V.FaceDot >= T.MinFaceDot;
}

ESaskartaSteleReadKind FSaskartaSteleScanCore::KindFor(const FStele& S, const FSaskartaSteleScanTuning& T) const
{
    if (S.Wear >= T.WornWear || Completed.Contains(S.Inscription)
        || TextOnlyFullReads.FindRef(S.Inscription) >= T.MaxTextOnlyFullReads)
    {
        return ESaskartaSteleReadKind::Match;
    }
    return ESaskartaSteleReadKind::Full;
}

FSaskartaSteleReadDecision FSaskartaSteleScanCore::Decide(double NowS, bool bCanRead, bool bHudBusy, float HudBusyForS,
    const TArray<FSaskartaSteleView>& Views, const FSaskartaSteleScanTuning& T)
{
    FSaskartaSteleReadDecision D;
    if (!bCanRead || NowS < BusyUntilS)
    {
        return D;
    }
    if (bHudBusy && HudBusyForS < T.HudWaitMaxS)
    {
        return D; // a HUD query is up: wait for it, but never longer than HudWaitMaxS
    }
    int32 Best = INDEX_NONE;
    float BestDistance = TNumericLimits<float>::Max();
    for (const FSaskartaSteleView& V : Views)
    {
        if (!Steles.IsValidIndex(V.Index))
        {
            continue;
        }
        const FStele& S = Steles[V.Index];
        if (S.bRead || !Eligible(V, S.bDock, T))
        {
            continue;
        }
        if (V.DistanceM < BestDistance)
        {
            BestDistance = V.DistanceM;
            Best = V.Index;
        }
    }
    return BeginRead(NowS, Best, T);
}

bool FSaskartaSteleScanCore::EligibleForPrompt(const FSaskartaSteleView& V, bool bDock, bool bHold, const FSaskartaSteleScanTuning& T)
{
    const float Cone = (bDock ? FMath::Max(T.PromptViewDeg, T.DockViewDeg) : T.PromptViewDeg) + (bHold ? T.PromptHoldDeg : 0.f);
    const float Range = T.PromptRangeM + (bHold ? T.PromptHoldM : 0.f);
    return V.bLineOfSight
        && V.DistanceM >= T.MinRangeM && V.DistanceM <= Range
        && V.ViewAngleDeg <= Cone
        && V.FaceDot >= T.MinFaceDot;
}

int32 FSaskartaSteleScanCore::PromptTarget(double NowS, bool bCanPrompt, int32 Current,
    const TArray<FSaskartaSteleView>& Views, const FSaskartaSteleScanTuning& T) const
{
    if (!bCanPrompt || NowS < BusyUntilS)
    {
        return INDEX_NONE;
    }
    int32 Best = INDEX_NONE;
    float BestDistance = TNumericLimits<float>::Max();
    for (const FSaskartaSteleView& V : Views)
    {
        // A read stone is offered again: the author wants to scan a pillar as often as they like (2026-09-29).
        if (!Steles.IsValidIndex(V.Index))
        {
            continue;
        }
        const bool bHold = V.Index == Current;
        if (!EligibleForPrompt(V, Steles[V.Index].bDock, bHold, T))
        {
            continue;
        }
        if (bHold)
        {
            return Current;
        }
        if (V.DistanceM < BestDistance)
        {
            BestDistance = V.DistanceM;
            Best = V.Index;
        }
    }
    return Best;
}

FString FSaskartaSteleScanCore::PromptLine(const FString& Label)
{
    return FString(TEXT("E · ")) + (Label.IsEmpty() ? FString(TEXT("SCAN INSCRIPTION")) : Label);
}

FSaskartaSteleReadDecision FSaskartaSteleScanCore::BeginRead(double NowS, int32 Index, const FSaskartaSteleScanTuning& T)
{
    FSaskartaSteleReadDecision D;
    if (!Steles.IsValidIndex(Index) || NowS < BusyUntilS)
    {
        return D;
    }
    const int32 Best = Index;
    FStele& S = Steles[Best];
    // A re-scan (the E prompt on a stone already read) plays the full reading and the voice again; a worn stone
    // stays a match. The number, the log and the map keep the first read.
    D.bRescan = S.bRead;
    S.bRead = true;
    D.Stele = Best;
    D.Kind = (D.bRescan && S.Wear < T.WornWear) ? ESaskartaSteleReadKind::Full : KindFor(S, T);
    D.bTryVoice = D.Kind == ESaskartaSteleReadKind::Full && !S.bNeverVoice && !InSilentRange(S.RoadM, T);
    if (const int32* Existing = Numbers.Find(S.Inscription))
    {
        D.Number = *Existing;
    }
    else
    {
        D.Number = Numbers.Num() + 1;
        Numbers.Add(S.Inscription, D.Number);
    }
    BusyUntilS = NowS + ReadingHoldS(D.Kind, D.bTryVoice, T);
    return D;
}

void FSaskartaSteleScanCore::OnVoiceResult(FName Inscription, bool bAttempted, bool bPlayed)
{
    if (bPlayed || !bAttempted)
    {
        Completed.Add(Inscription);
    }
    else
    {
        ++TextOnlyFullReads.FindOrAdd(Inscription);
    }
}

int32 FSaskartaSteleScanCore::MarkBehind(float RoadM, const FSaskartaSteleScanTuning& T)
{
    int32 Marked = 0;
    for (FStele& S : Steles)
    {
        if (!S.bRead && S.RoadM < RoadM - T.BehindM)
        {
            S.bRead = true;
            ++Marked;
        }
    }
    return Marked;
}

bool FSaskartaSteleScanCore::InSilentRange(float RoadM, const FSaskartaSteleScanTuning& T)
{
    for (const FVector2f& R : T.SilentRoadM)
    {
        if (RoadM >= R.X && RoadM <= R.Y)
        {
            return true;
        }
    }
    return false;
}

float FSaskartaSteleScanCore::ReadingHoldS(ESaskartaSteleReadKind Kind, bool bTryVoice, const FSaskartaSteleScanTuning& T)
{
    switch (Kind)
    {
    case ESaskartaSteleReadKind::Full:
        return bTryVoice
            ? FMath::Max(T.TextAtS + T.TextOnlyHoldS, T.VoiceAtS + T.VoiceWaitMaxS + T.HoldAfterVoiceS)
            : T.TextAtS + T.TextOnlyHoldS;
    case ESaskartaSteleReadKind::Match:
        return T.MatchSweepS + T.MatchHoldS;
    default:
        return 0.f;
    }
}

TArray<FSaskartaSteleCpdWrite> FSaskartaSteleScanCore::StartCpd(ESaskartaSteleReadKind Kind, double NowS, float GlowHoldS)
{
    TArray<FSaskartaSteleCpdWrite> Out;
    if (Kind == ESaskartaSteleReadKind::None)
    {
        return Out;
    }
    FSaskartaSteleCpdWrite W;
    W.Index = SaskartaSteleCpd::ScanStart;
    W.Value = static_cast<float>(NowS);
    Out.Add(W);
    W.Index = SaskartaSteleCpd::ScanMode;
    W.Value = Kind == ESaskartaSteleReadKind::Full ? 1.f : 0.5f;
    Out.Add(W);
    W.Index = SaskartaSteleCpd::GlowHold;
    W.Value = FMath::Max(0.f, GlowHoldS);
    Out.Add(W);
    return Out;
}

float FSaskartaSteleScanCore::GlowHoldForVoice(double ScanStartS, double VoiceStartS, float ClipS)
{
    return static_cast<float>(FMath::Max(0.0, VoiceStartS - ScanStartS)) + FMath::Max(0.f, ClipS) + 0.5f;
}

namespace SaskartaSteleText
{
    struct FFold
    {
        uint32 Lo;
        uint32 Hi;
        TCHAR To;
    };

    // Latin letters with diacritics -> the bare letter; 0 = drop (combining marks).
    static const FFold Folds[] = {
        { 0x00C0, 0x00C5, TEXT('a') }, { 0x00C7, 0x00C7, TEXT('c') }, { 0x00C8, 0x00CB, TEXT('e') },
        { 0x00CC, 0x00CF, TEXT('i') }, { 0x00D1, 0x00D1, TEXT('n') }, { 0x00D2, 0x00D6, TEXT('o') },
        { 0x00D8, 0x00D8, TEXT('o') }, { 0x00D9, 0x00DC, TEXT('u') }, { 0x00DD, 0x00DD, TEXT('y') },
        { 0x00E0, 0x00E5, TEXT('a') }, { 0x00E7, 0x00E7, TEXT('c') }, { 0x00E8, 0x00EB, TEXT('e') },
        { 0x00EC, 0x00EF, TEXT('i') }, { 0x00F1, 0x00F1, TEXT('n') }, { 0x00F2, 0x00F6, TEXT('o') },
        { 0x00F8, 0x00F8, TEXT('o') }, { 0x00F9, 0x00FC, TEXT('u') }, { 0x00FD, 0x00FD, TEXT('y') },
        { 0x00FF, 0x00FF, TEXT('y') }, { 0x0100, 0x0105, TEXT('a') }, { 0x0106, 0x010D, TEXT('c') },
        { 0x010E, 0x0111, TEXT('d') }, { 0x0112, 0x011B, TEXT('e') }, { 0x011C, 0x0123, TEXT('g') },
        { 0x0124, 0x0127, TEXT('h') }, { 0x0128, 0x0131, TEXT('i') }, { 0x0134, 0x0135, TEXT('j') },
        { 0x0136, 0x0137, TEXT('k') }, { 0x0139, 0x0142, TEXT('l') }, { 0x0143, 0x0148, TEXT('n') },
        { 0x014C, 0x0151, TEXT('o') }, { 0x0154, 0x0159, TEXT('r') }, { 0x015A, 0x0161, TEXT('s') },
        { 0x0162, 0x0167, TEXT('t') }, { 0x0168, 0x0173, TEXT('u') }, { 0x0174, 0x0175, TEXT('w') },
        { 0x0176, 0x0178, TEXT('y') }, { 0x0179, 0x017E, TEXT('z') },
        { 0x02BC, 0x02BC, TEXT('\'') }, { 0x02BE, 0x02BF, TEXT('\'') }, { 0x2018, 0x2019, TEXT('\'') },
        { 0x0300, 0x036F, 0 },
        { 0x1E0C, 0x1E0D, TEXT('d') }, { 0x1E24, 0x1E25, TEXT('h') }, { 0x1E62, 0x1E63, TEXT('s') },
        { 0x1E6C, 0x1E6D, TEXT('t') }, { 0x1E92, 0x1E93, TEXT('z') },
    };

    static int32 CountOf(const FString& Text, const TCHAR* Sub)
    {
        int32 N = 0;
        int32 From = 0;
        const int32 Len = FCString::Strlen(Sub);
        while (Len > 0)
        {
            const int32 At = Text.Find(Sub, ESearchCase::CaseSensitive, ESearchDir::FromStart, From);
            if (At == INDEX_NONE)
            {
                break;
            }
            ++N;
            From = At + Len;
        }
        return N;
    }
}

FString FSaskartaSteleScanCore::MachineTranslit(const FString& Saskartan)
{
    FString Out;
    Out.Reserve(Saskartan.Len());
    for (const TCHAR C : Saskartan)
    {
        const uint32 Code = static_cast<uint32>(C);
        if (Code < 128)
        {
            Out.AppendChar(C);
            continue;
        }
        bool bFolded = false;
        for (const SaskartaSteleText::FFold& F : SaskartaSteleText::Folds)
        {
            if (Code >= F.Lo && Code <= F.Hi)
            {
                if (F.To != 0)
                {
                    Out.AppendChar(F.To);
                }
                bFolded = true;
                break;
            }
        }
        if (!bFolded)
        {
            Out.AppendChar(TEXT('?'));
        }
    }
    return Out.ToUpper();
}

int32 FSaskartaSteleScanCore::CountUnresolved(const FString& EnglishApprox)
{
    return SaskartaSteleText::CountOf(EnglishApprox, TEXT("[?]"))
        + SaskartaSteleText::CountOf(EnglishApprox, TEXT("[ERASED]"))
        + SaskartaSteleText::CountOf(EnglishApprox, TEXT("[NAME:"))
        + SaskartaSteleText::CountOf(EnglishApprox, TEXT("~"));
}

FString FSaskartaSteleScanCore::HudSafe(const FString& Text, const FString& ResolvedMark)
{
    if (ResolvedMark.IsEmpty())
    {
        return Text.Replace(TEXT(" ✓"), TEXT(""), ESearchCase::CaseSensitive)
            .Replace(TEXT("✓"), TEXT(""), ESearchCase::CaseSensitive);
    }
    return Text.Replace(TEXT("✓"), *ResolvedMark, ESearchCase::CaseSensitive);
}

FString FSaskartaSteleScanCore::ReadingHeader(int32 Number)
{
    return FString::Printf(TEXT("INSCRIPTION %02d · READING"), Number);
}

FString FSaskartaSteleScanCore::Header(int32 Number, int32 Unresolved)
{
    if (Unresolved <= 0)
    {
        return FString::Printf(TEXT("INSCRIPTION %02d · READ"), Number);
    }
    return FString::Printf(TEXT("INSCRIPTION %02d · PARTIAL · %d ?"), Number, Unresolved);
}

FString FSaskartaSteleScanCore::FullText(int32 Number, const FString& Saskartan, const FString& MachineTranslitOverride,
    const FString& EnglishApprox, const FString& ResolvedMark)
{
    FString Translit = MachineTranslitOverride;
    if (Translit.IsEmpty())
    {
        Translit = (Saskartan.IsEmpty() || Saskartan == TEXT("AUTHOR")) ? FString(TEXT("?")) : MachineTranslit(Saskartan);
    }
    return Header(Number, CountUnresolved(EnglishApprox)) + TEXT("\n ") + Translit + TEXT("\n ~ EN: ")
        + HudSafe(EnglishApprox, ResolvedMark);
}

FString FSaskartaSteleScanCore::MatchLine(int32 Number, const FString& EnglishApprox, float Wear, float WornWear,
    const FString& ResolvedMark)
{
    FString Line = FString::Printf(TEXT("MATCH %02d · "), Number) + HudSafe(EnglishApprox, ResolvedMark);
    if (Wear >= WornWear)
    {
        const int32 Legible = FMath::Clamp(FMath::RoundToInt((1.f - Wear) * 100.f), 0, 100);
        Line += FString::Printf(TEXT(" · %d %% LEGIBLE"), Legible);
    }
    return Line;
}
