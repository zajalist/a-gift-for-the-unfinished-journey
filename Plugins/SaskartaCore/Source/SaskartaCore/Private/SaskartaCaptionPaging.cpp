// Caption pages: see SaskartaCaptionPaging.h.

#include "SaskartaCaptionPaging.h"

namespace SaskartaCaptionPagingPrivate
{
    static bool IsSentenceEnd(TCHAR C)
    {
        return C == TEXT('.') || C == TEXT('?') || C == TEXT('!') || C == TCHAR(0x2026);
    }

    static bool IsCloser(TCHAR C)
    {
        return C == TEXT('"') || C == TEXT('\'') || C == TEXT(')') || C == TCHAR(0x201D) || C == TCHAR(0x2019);
    }

    static bool IsClauseMark(TCHAR C)
    {
        return C == TEXT(',') || C == TEXT(';') || C == TEXT(':') || C == TCHAR(0x2014) || C == TCHAR(0x2013);
    }

    static int32 Weight(const FString& S)
    {
        int32 N = 0;
        for (int32 i = 0; i < S.Len(); ++i)
        {
            N += FChar::IsWhitespace(S[i]) ? 0 : 1;
        }
        return N;
    }

    static FString Squash(const FString& S)
    {
        FString Out;
        Out.Reserve(S.Len());
        for (int32 i = 0; i < S.Len(); ++i)
        {
            if (!FChar::IsWhitespace(S[i]))
            {
                Out.AppendChar(S[i]);
            }
        }
        return Out;
    }

    /** A sentence ends at . ? ! or an ellipsis (and any closing quotes) followed by whitespace. */
    static void SplitSentences(const FString& Text, TArray<FString>& Out)
    {
        const int32 N = Text.Len();
        int32 Start = 0;
        for (int32 i = 0; i < N; ++i)
        {
            if (!IsSentenceEnd(Text[i]))
            {
                continue;
            }
            int32 j = i + 1;
            while (j < N && IsCloser(Text[j]))
            {
                ++j;
            }
            if (j < N && FChar::IsWhitespace(Text[j]))
            {
                const FString Piece = Text.Mid(Start, j - Start).TrimStartAndEnd();
                if (!Piece.IsEmpty())
                {
                    Out.Add(Piece);
                }
                Start = j;
                i = j;
            }
        }
        const FString Tail = Text.Mid(Start, N - Start).TrimStartAndEnd();
        if (!Tail.IsEmpty())
        {
            Out.Add(Tail);
        }
    }

    /** A sentence longer than a page: cut at the clause mark nearest its middle, else at the space nearest it. */
    static void SplitLong(const FString& Piece, int32 MaxChars, TArray<FString>& Out, int32 Depth)
    {
        const int32 N = Piece.Len();
        if (N <= MaxChars || Depth > 16)
        {
            Out.Add(Piece);
            return;
        }
        const float Mid = N * 0.5f;
        int32 Best = INDEX_NONE;
        for (int32 i = 0; i + 1 < N; ++i)
        {
            const int32 Cut = i + 1;
            if (IsClauseMark(Piece[i]) && FChar::IsWhitespace(Piece[Cut]) && Cut >= 12 && Cut <= N - 12
                && (Best == INDEX_NONE || FMath::Abs(Cut - Mid) < FMath::Abs(Best - Mid)))
            {
                Best = Cut;
            }
        }
        if (Best == INDEX_NONE)
        {
            for (int32 i = 1; i < N; ++i)
            {
                if (FChar::IsWhitespace(Piece[i]) && (Best == INDEX_NONE || FMath::Abs(i - Mid) < FMath::Abs(Best - Mid)))
                {
                    Best = i;
                }
            }
        }
        if (Best == INDEX_NONE)
        {
            Out.Add(Piece);
            return;
        }
        SplitLong(Piece.Mid(0, Best).TrimStartAndEnd(), MaxChars, Out, Depth + 1);
        SplitLong(Piece.Mid(Best, N - Best).TrimStartAndEnd(), MaxChars, Out, Depth + 1);
    }
}

TArray<FString> FSaskartaCaptionPaging::SplitPages(const FString& Text, int32 MaxChars)
{
    using namespace SaskartaCaptionPagingPrivate;
    MaxChars = FMath::Max(MaxChars, 16);
    TArray<FString> Sentences;
    SplitSentences(Text, Sentences);
    TArray<FString> Pieces;
    for (const FString& S : Sentences)
    {
        SplitLong(S, MaxChars, Pieces, 0);
    }
    TArray<FString> Pages;
    for (const FString& P : Pieces)
    {
        if (Pages.Num() > 0 && Pages[Pages.Num() - 1].Len() + 1 + P.Len() <= MaxChars)
        {
            Pages[Pages.Num() - 1] += TEXT(" ");
            Pages[Pages.Num() - 1] += P;
        }
        else
        {
            Pages.Add(P);
        }
    }
    return Pages;
}

TArray<FSaskartaCaptionPage> FSaskartaCaptionPaging::ProportionalPages(const FString& Text, float DurationS, int32 MaxChars)
{
    using namespace SaskartaCaptionPagingPrivate;
    TArray<FSaskartaCaptionPage> Out;
    const TArray<FString> Pages = SplitPages(Text, MaxChars);
    int32 Total = 0;
    for (const FString& P : Pages)
    {
        Total += Weight(P);
    }
    int32 Before = 0;
    for (const FString& P : Pages)
    {
        FSaskartaCaptionPage Page;
        Page.Text = P;
        Page.StartS = (Total > 0 && DurationS > 0.f) ? DurationS * static_cast<float>(Before) / static_cast<float>(Total) : 0.f;
        Before += Weight(P);
        Out.Add(Page);
    }
    if (Out.Num() == 0 && !Text.TrimStartAndEnd().IsEmpty())
    {
        FSaskartaCaptionPage Page;
        Page.Text = Text.TrimStartAndEnd();
        Out.Add(Page);
    }
    return Out;
}

bool FSaskartaCaptionPaging::PagesSpell(const TArray<FSaskartaCaptionPage>& Pages, const FString& Text)
{
    using namespace SaskartaCaptionPagingPrivate;
    FString Joined;
    for (const FSaskartaCaptionPage& P : Pages)
    {
        Joined += P.Text;
    }
    return Pages.Num() > 0 && Squash(Joined) == Squash(Text);
}

TArray<FString> FSaskartaCaptionPaging::SplitIntoN(const FString& Text, int32 Count)
{
    using namespace SaskartaCaptionPagingPrivate;
    TArray<FString> Out;
    Count = FMath::Max(1, Count);
    for (int32 k = 0; k < Count; ++k)
    {
        Out.Add(FString());
    }
    const int32 Total = Weight(Text);
    if (Total == 0)
    {
        return Out;
    }
    // Each word goes to the run its middle character falls in.
    int32 Before = 0;
    int32 i = 0;
    const int32 N = Text.Len();
    while (i < N)
    {
        while (i < N && FChar::IsWhitespace(Text[i]))
        {
            ++i;
        }
        const int32 WordStart = i;
        while (i < N && !FChar::IsWhitespace(Text[i]))
        {
            ++i;
        }
        const int32 Len = i - WordStart;
        if (Len <= 0)
        {
            break;
        }
        const float MidChar = Before + Len * 0.5f;
        const int32 K = FMath::Clamp(static_cast<int32>(MidChar * Count / Total), 0, Count - 1);
        if (!Out[K].IsEmpty())
        {
            Out[K] += TEXT(" ");
        }
        Out[K] += Text.Mid(WordStart, Len);
        Before += Len;
    }
    return Out;
}

TArray<FSaskartaCaptionPage> FSaskartaCaptionPaging::Resolve(const TArray<FSaskartaCaptionPage>& Authored, const FString& Text,
    const FString& Saskartan, float DurationS)
{
    TArray<FSaskartaCaptionPage> Out = Authored;
    Out.Sort([](const FSaskartaCaptionPage& A, const FSaskartaCaptionPage& B) { return A.StartS < B.StartS; });
    if (!PagesSpell(Out, Text))
    {
        Out.Reset();
    }
    if (Out.Num() > 0)
    {
        Out[0].StartS = 0.f;
        if (DurationS > 0.f && Out[Out.Num() - 1].StartS > DurationS - MinLastPageS)
        {
            // Timed for another take (or a shorter fallback length): recompute.
            Out.Reset();
        }
    }
    if (Out.Num() == 0)
    {
        if (DurationS > 0.f)
        {
            Out = ProportionalPages(Text, DurationS);
        }
        else
        {
            FSaskartaCaptionPage Page;
            Page.Text = Text;
            Out.Add(Page);
        }
    }
    if (Saskartan.IsEmpty())
    {
        for (FSaskartaCaptionPage& P : Out)
        {
            P.Saskartan = FString();
        }
        return Out;
    }
    bool bMissing = false;
    for (const FSaskartaCaptionPage& P : Out)
    {
        bMissing |= P.Saskartan.IsEmpty();
    }
    if (Out.Num() == 1)
    {
        Out[0].Saskartan = Saskartan;
    }
    else if (bMissing)
    {
        const TArray<FString> Parts = SplitIntoN(Saskartan, Out.Num());
        for (int32 k = 0; k < Out.Num(); ++k)
        {
            Out[k].Saskartan = Parts[k];
        }
    }
    return Out;
}

int32 FSaskartaCaptionPaging::PageAt(const TArray<FSaskartaCaptionPage>& Pages, float ElapsedS)
{
    if (Pages.Num() == 0)
    {
        return INDEX_NONE;
    }
    int32 Index = 0;
    for (int32 k = 1; k < Pages.Num(); ++k)
    {
        if (Pages[k].StartS <= ElapsedS + 1.e-4f)
        {
            Index = k;
        }
    }
    return Index;
}

float FSaskartaCaptionPaging::PageDurationS(const TArray<FSaskartaCaptionPage>& Pages, int32 Index, float DurationS)
{
    if (!Pages.IsValidIndex(Index))
    {
        return 0.5f;
    }
    const float End = Pages.IsValidIndex(Index + 1) ? Pages[Index + 1].StartS : DurationS;
    return FMath::Max(0.5f, End - Pages[Index].StartS);
}

void FSaskartaCaptionPaging::AddPrefix(TArray<FSaskartaCaptionPage>& Pages, const FString& Prefix)
{
    if (Prefix.IsEmpty())
    {
        return;
    }
    for (FSaskartaCaptionPage& P : Pages)
    {
        P.Text = Prefix + P.Text;
    }
}

// ============================================================================ pager

void FSaskartaCaptionPager::Start(const TArray<FSaskartaCaptionPage>& InPages, double NowS, float OffsetS, float InDurationS)
{
    Pages = InPages;
    ZeroS = NowS - FMath::Max(0.f, OffsetS);
    PausedAtS = -1.0;
    DurationS = InDurationS;
    Shown = INDEX_NONE;
}

void FSaskartaCaptionPager::Reset()
{
    Pages.Reset();
    PausedAtS = -1.0;
    Shown = INDEX_NONE;
}

void FSaskartaCaptionPager::SetPaused(bool bPaused, double NowS)
{
    if (bPaused && PausedAtS < 0.0)
    {
        PausedAtS = NowS;
    }
    else if (!bPaused && PausedAtS >= 0.0)
    {
        ZeroS += FMath::Max(0.0, NowS - PausedAtS);
        PausedAtS = -1.0;
    }
}

float FSaskartaCaptionPager::ElapsedS(double NowS) const
{
    return static_cast<float>((PausedAtS >= 0.0 ? PausedAtS : NowS) - ZeroS);
}

int32 FSaskartaCaptionPager::TakeDue(double NowS)
{
    if (!IsLive())
    {
        return INDEX_NONE;
    }
    const int32 Index = FSaskartaCaptionPaging::PageAt(Pages, ElapsedS(NowS));
    if (Index == Shown)
    {
        return INDEX_NONE;
    }
    Shown = Index;
    return Index;
}
