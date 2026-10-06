// Caption pages: a long spoken line is shown page by page, in step with the voice.
//
// The author (after playing): "the subtitles are often not in sync with my recording". A station take of up to
// 40 s used to show its whole text at once, so the words ran far ahead of the voice. Now every caption is split
// into pages a player can read (a sentence or a clause, at most MaxPageChars, two lines) and each page is shown
// from its start time in the take:
//
//   - authored pages: Tools/Audio/caption_cues.py times them to the take's pauses and writes them to
//     docs/story/station.json (segments[].caption_pages) and docs/story/caption-pages.json (story lines); the
//     importers carry them into DA_Station and DA_Saskarta_Story (FSaskartaStationSegment / FSaskartaLineDef
//     CaptionPages). No runtime file reads.
//   - fallback: a line without pages (or whose text no longer matches them, or a named song pickup) is split by
//     characters over its duration (ProportionalPages). Never the whole long text at once.
//
// USaskartaEventRunner pages story and station subtitles with FSaskartaCaptionPager on its 0.1 s step (world
// time: a paused world freezes the page with the audio; the station's menu pause shifts the station pager).
// Each page goes out through the existing OnSubtitleShow, so the caption widget needs no change.
//
// Pure logic: Saskarta.Captions.* tests; offline smoke Tools/Audio/caption_smoke (cl, no engine).

#pragma once

#include "CoreMinimal.h"
#include "SaskartaCaptionPaging.generated.h"

/** One page of a caption: the words on screen from StartS (seconds into the take) until the next page. */
USTRUCT(BlueprintType)
struct SASKARTACORE_API FSaskartaCaptionPage
{
    GENERATED_BODY()

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Subtitles")
    float StartS = 0.f;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Subtitles")
    FString Text;

    /** The Saskartan original of this page (SKS lines), or empty. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Subtitles")
    FString Saskartan;
};

struct SASKARTACORE_API FSaskartaCaptionPaging
{
    /** Two subtitle lines. */
    static constexpr int32 MaxPageChars = 90;
    /** The ARCHIVE header rides on the pages that start in the line's first seconds only. */
    static constexpr float HeaderHoldS = 4.f;
    /** An authored page that starts later than DurationS - this does not fit the take: the pages are recomputed. */
    static constexpr float MinLastPageS = 0.3f;

    /** Sentences, then clauses (then words) for a sentence longer than a page, packed greedily up to MaxChars. */
    static TArray<FString> SplitPages(const FString& Text, int32 MaxChars = MaxPageChars);

    /** SplitPages timed by each page's share of the characters over DurationS (page 0 at 0). */
    static TArray<FSaskartaCaptionPage> ProportionalPages(const FString& Text, float DurationS, int32 MaxChars = MaxPageChars);

    /** True when the pages, joined, spell Text (whitespace ignored): the authored pages still match the line. */
    static bool PagesSpell(const TArray<FSaskartaCaptionPage>& Pages, const FString& Text);

    /**
     * The pages to show: Authored when they spell Text and fit DurationS, else ProportionalPages. Sorted, page 0
     * at 0. Saskartan (empty = not shown) fills pages that have none by an even split; empty clears them.
     */
    static TArray<FSaskartaCaptionPage> Resolve(const TArray<FSaskartaCaptionPage>& Authored, const FString& Text,
        const FString& Saskartan, float DurationS);

    /** Text split into Count runs of whole words of about equal length (some may be empty). */
    static TArray<FString> SplitIntoN(const FString& Text, int32 Count);

    /** The page on screen ElapsedS into the take (INDEX_NONE for no pages). */
    static int32 PageAt(const TArray<FSaskartaCaptionPage>& Pages, float ElapsedS);

    /** How long page Index stays up: to the next page, or to the end of the take (at least 0.5 s). */
    static float PageDurationS(const TArray<FSaskartaCaptionPage>& Pages, int32 Index, float DurationS);

    static void AddPrefix(TArray<FSaskartaCaptionPage>& Pages, const FString& Prefix);
};

/** One subtitle lane's page clock (story or station). Times are world seconds. */
struct SASKARTACORE_API FSaskartaCaptionPager
{
    TArray<FSaskartaCaptionPage> Pages;
    /** World time of the take's 0 (a resumed part starts OffsetS in). */
    double ZeroS = 0.0;
    double PausedAtS = -1.0;
    float DurationS = 0.f;
    int32 Shown = INDEX_NONE;

    bool IsLive() const { return Pages.Num() > 0; }
    void Start(const TArray<FSaskartaCaptionPage>& InPages, double NowS, float OffsetS, float InDurationS);
    void Reset();
    /** Freezes the clock (a menu pause) and, on release, moves it on by the time paused. */
    void SetPaused(bool bPaused, double NowS);
    float ElapsedS(double NowS) const;
    /** The page due now when it is not the one on screen (then it counts as shown), else INDEX_NONE. */
    int32 TakeDue(double NowS);
    /** The next TakeDue returns the current page again (a story line covered this lane and has ended). */
    void Reshow() { Shown = INDEX_NONE; }
};
