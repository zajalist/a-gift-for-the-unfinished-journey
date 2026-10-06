// Automation tests for the caption pages (SaskartaCaptionPaging.h): the fallback split, the authored pages'
// checks, the Saskartan split and the pager clock (pause, resume offset, re-show). Pure, no world.
//   Automation RunTests Saskarta.Captions
// Offline (no engine): Tools/Audio/caption_smoke/caption_smoke.cpp compiles and runs these with cl.

#include "Misc/AutomationTest.h"

#if WITH_DEV_AUTOMATION_TESTS

#include "SaskartaCaptionPaging.h"
#include "SaskartaStoryImport.h"

#define SASKARTA_CAPTION_TEST_FLAGS (EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)

namespace SaskartaCaptionPagingTest
{
    static const TCHAR* LongLine = TEXT("For the tape: this is Ilaawb, the back room of the post office, on the last night. ")
        TEXT("The year is eighteen-forty. The works, the mining company, sent us a letter today, and I have read it four ")
        TEXT("times over, very slowly, by the lamp, twice with my glasses and twice without them. That's what bothers me.");

    static FSaskartaCaptionPage Page(float StartS, const TCHAR* Text, const TCHAR* Sks = TEXT(""))
    {
        FSaskartaCaptionPage P;
        P.StartS = StartS;
        P.Text = Text;
        P.Saskartan = Sks;
        return P;
    }
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaCaptionsSplitTest, "Saskarta.Captions.Split", SASKARTA_CAPTION_TEST_FLAGS)
bool FSaskartaCaptionsSplitTest::RunTest(const FString&)
{
    using namespace SaskartaCaptionPagingTest;
    const TArray<FString> Pages = FSaskartaCaptionPaging::SplitPages(LongLine);
    TestTrue(TEXT("a long line makes several pages"), Pages.Num() >= 3);
    bool bFit = true;
    FString Joined;
    for (const FString& P : Pages)
    {
        bFit &= P.Len() <= FSaskartaCaptionPaging::MaxPageChars;
        Joined += P;
        Joined += TEXT(" ");
    }
    TestTrue(TEXT("every page fits two lines"), bFit);
    TArray<FSaskartaCaptionPage> AsPages;
    for (const FString& P : Pages)
    {
        AsPages.Add(Page(0.f, *P));
    }
    TestTrue(TEXT("the pages spell the line"), FSaskartaCaptionPaging::PagesSpell(AsPages, LongLine));

    const TArray<FString> Short = FSaskartaCaptionPaging::SplitPages(TEXT("There it is. The storm. Seven cups now."));
    TestEqual(TEXT("a short line is one page"), Short.Num(), 1);

    // One very long sentence with no clause marks still splits (at a space).
    const TArray<FString> Words = FSaskartaCaptionPaging::SplitPages(
        TEXT("Tashen Samyar Imriz Tmaz Rsish Ilsis Eb Ehb Dilan Iblil Irlah Ithebiy Asekine Ibzaenes and Iy-la'har-dzehiy the goat and the donkey"));
    TestTrue(TEXT("a list splits at a space"), Words.Num() >= 2 && Words[0].Len() <= FSaskartaCaptionPaging::MaxPageChars);
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaCaptionsProportionalTest, "Saskarta.Captions.Proportional", SASKARTA_CAPTION_TEST_FLAGS)
bool FSaskartaCaptionsProportionalTest::RunTest(const FString&)
{
    using namespace SaskartaCaptionPagingTest;
    const TArray<FSaskartaCaptionPage> P = FSaskartaCaptionPaging::ProportionalPages(LongLine, 30.f);
    TestTrue(TEXT("pages"), P.Num() >= 3);
    TestEqual(TEXT("page 0 at 0"), P[0].StartS, 0.f);
    bool bRising = true;
    for (int32 k = 1; k < P.Num(); ++k)
    {
        bRising &= P[k].StartS > P[k - 1].StartS && P[k].StartS < 30.f;
    }
    TestTrue(TEXT("start times rise inside the take"), bRising);
    TestEqual(TEXT("the first page is not up for the whole take"), FSaskartaCaptionPaging::PageAt(P, 29.f), P.Num() - 1);
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaCaptionsResolveTest, "Saskarta.Captions.Resolve", SASKARTA_CAPTION_TEST_FLAGS)
bool FSaskartaCaptionsResolveTest::RunTest(const FString&)
{
    using namespace SaskartaCaptionPagingTest;
    const FString Text = TEXT("There it is. The storm. Seven cups now, and the kettle is still on the stove where I left it an hour ago.");
    TArray<FSaskartaCaptionPage> Authored;
    Authored.Add(Page(3.1f, TEXT("Seven cups now, and the kettle is still on the stove where I left it an hour ago.")));
    Authored.Add(Page(0.2f, TEXT("There it is. The storm.")));

    TArray<FSaskartaCaptionPage> R = FSaskartaCaptionPaging::Resolve(Authored, Text, FString(), 9.f);
    TestEqual(TEXT("authored pages kept"), R.Num(), 2);
    TestEqual(TEXT("sorted, page 0 at 0"), R[0].StartS, 0.f);
    TestEqual(TEXT("authored time kept"), R[1].StartS, 3.1f);

    // The script changed after the take was analysed: the stale pages are not used.
    R = FSaskartaCaptionPaging::Resolve(Authored, Text + TEXT(" Right."), FString(), 9.f);
    TestTrue(TEXT("text changed: recomputed"), R.Num() >= 1 && R[R.Num() - 1].Text.Contains(TEXT("Right.")));

    // A take shorter than the authored times (subtitle-only fallback length): recomputed inside it.
    R = FSaskartaCaptionPaging::Resolve(Authored, Text, FString(), 3.f);
    TestTrue(TEXT("short take: every page starts inside it"), R[R.Num() - 1].StartS < 3.f);

    // Saskartan: an even split when the pages carry none; cleared when it is not shown.
    const FString Sks = TEXT("eirkirek ara rkheda ye ndasef ibubremat azdaw ta'hajjit im qam-eidheqane nisbibar kilsekat");
    R = FSaskartaCaptionPaging::Resolve(Authored, Text, Sks, 9.f);
    TestTrue(TEXT("each page has its Saskartan"), !R[0].Saskartan.IsEmpty() && !R[1].Saskartan.IsEmpty());
    TArray<FSaskartaCaptionPage> WithSks = Authored;
    WithSks[0].Saskartan = TEXT("B");
    WithSks[1].Saskartan = TEXT("A");
    R = FSaskartaCaptionPaging::Resolve(WithSks, Text, Sks, 9.f);
    TestEqual(TEXT("authored Saskartan kept"), R[0].Saskartan, FString(TEXT("A")));
    R = FSaskartaCaptionPaging::Resolve(WithSks, Text, FString(), 9.f);
    TestTrue(TEXT("Saskartan hidden"), R[0].Saskartan.IsEmpty() && R[1].Saskartan.IsEmpty());

    const TArray<FString> Parts = FSaskartaCaptionPaging::SplitIntoN(TEXT("aa bb cc dd"), 2);
    TestEqual(TEXT("split in two, first"), Parts[0], FString(TEXT("aa bb")));
    TestEqual(TEXT("split in two, second"), Parts[1], FString(TEXT("cc dd")));

    TArray<FSaskartaCaptionPage> Prefixed = R;
    FSaskartaCaptionPaging::AddPrefix(Prefixed, TEXT("CARRIER: "));
    TestEqual(TEXT("prefix on every page"), Prefixed[1].Text, FString(TEXT("CARRIER: ")) + R[1].Text);
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaCaptionsPagerTest, "Saskarta.Captions.Pager", SASKARTA_CAPTION_TEST_FLAGS)
bool FSaskartaCaptionsPagerTest::RunTest(const FString&)
{
    using namespace SaskartaCaptionPagingTest;
    TArray<FSaskartaCaptionPage> P;
    P.Add(Page(0.f, TEXT("One.")));
    P.Add(Page(4.f, TEXT("Two.")));
    P.Add(Page(9.f, TEXT("Three.")));

    FSaskartaCaptionPager G;
    TestEqual(TEXT("idle: nothing due"), G.TakeDue(0.0), INDEX_NONE);
    G.Start(P, 100.0, 0.f, 12.f);
    TestEqual(TEXT("page 0 at once"), G.TakeDue(100.0), 0);
    TestEqual(TEXT("not again"), G.TakeDue(101.0), INDEX_NONE);
    TestEqual(TEXT("page 1 at 4 s"), G.TakeDue(104.05), 1);
    TestEqual(TEXT("page 1 lasts 5 s"), FSaskartaCaptionPaging::PageDurationS(P, 1, 12.f), 5.f);
    TestEqual(TEXT("the last page lasts to the end"), FSaskartaCaptionPaging::PageDurationS(P, 2, 12.f), 3.f);

    // Menu pause at 105 for 20 s: the page holds, then continues where it was.
    G.SetPaused(true, 105.0);
    TestEqual(TEXT("frozen"), G.TakeDue(115.0), INDEX_NONE);
    TestEqual(TEXT("elapsed frozen"), G.ElapsedS(124.0), 5.f);
    G.SetPaused(false, 125.0);
    TestEqual(TEXT("still page 1 after the pause"), G.TakeDue(126.0), INDEX_NONE);
    TestEqual(TEXT("page 2 at 9 s of take time"), G.TakeDue(129.1), 2);

    // A story line covered the lane: Reshow puts the current page back up.
    G.Reshow();
    TestEqual(TEXT("re-shown"), G.TakeDue(130.0), 2);

    // A resumed part starts 6 s in: page 1 first.
    G.Start(P, 200.0, 6.f, 12.f);
    TestEqual(TEXT("resumed part starts on page 1"), G.TakeDue(200.0), 1);
    G.Reset();
    TestFalse(TEXT("reset"), G.IsLive());
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaCaptionsStoryImportTest, "Saskarta.Captions.StoryImport", SASKARTA_CAPTION_TEST_FLAGS)
bool FSaskartaCaptionsStoryImportTest::RunTest(const FString&)
{
    FSaskartaLineDef Line;
    Line.Id = TEXT("RADIO_B02_01");
    Line.English = TEXT("Archive of the upper valley. For whoever carries this road.");
    TArray<FSaskartaLineDef> Lines;
    Lines.Add(Line);
    const FString Captions = FString(R"json({"lines":{"RADIO_B02_01":[{"t":0,"text":"Archive of the upper valley.","sks":"Imrigheyilef-de zdaw."},{"t":3.2,"text":"For whoever carries this road."}]}})json");
    TestTrue(TEXT("caption pages parse"), USaskartaStoryImport::ApplyCaptionPagesJson(Captions, Lines));
    if (TestEqual(TEXT("story pages attached"), Lines[0].CaptionPages.Num(), 2))
    {
        TestEqual(TEXT("story page start"), Lines[0].CaptionPages[1].StartS, 3.2f);
        TestEqual(TEXT("Saskartan page carried"), Lines[0].CaptionPages[0].Saskartan, FString(TEXT("Imrigheyilef-de zdaw.")));
        TestTrue(TEXT("pages match subtitle"), FSaskartaCaptionPaging::PagesSpell(Lines[0].CaptionPages, Lines[0].English));
    }
    return true;
}

#endif
