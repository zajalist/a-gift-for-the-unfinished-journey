// Automation tests for the task LOADBUDGET pure logic: save/restore, owner ref counting, the
// Cap/AtLeast/Set ops, "keep a value someone else changed", unknown CVars, the frame window, and
// that every CVar the budget names exists in this build and is not a cheat CVar.
//
// Written offline (fail-first waived, as R33). Run after the build:
//   Automation RunTests Saskarta.LoadBudget

#include "Misc/AutomationTest.h"

#if WITH_DEV_AUTOMATION_TESTS

#include "HAL/IConsoleManager.h"
#include "SaskartaLoadingBudget.h"

namespace SaskartaLoadBudgetTest
{
    /** A CVar store in a map; Writes counts every write. */
    class FFakeCVars final : public ISaskartaCVarAccess
    {
    public:
        TMap<FString, FString> Values;
        int32 Writes = 0;

        virtual bool Read(const FString& Name, FString& OutValue) const override
        {
            const FString* V = Values.Find(Name);
            if (!V)
            {
                return false;
            }
            OutValue = *V;
            return true;
        }

        virtual void Write(const FString& Name, const FString& Value) override
        {
            ++Writes;
            Values.Add(Name, Value);
        }
    };

    using EOp = FSaskartaLoadBudgetCore::EOp;

    static TArray<FSaskartaLoadBudgetCore::FSetting> Settings()
    {
        return {
            { TEXT("t.MaxFPS"), 30.f, EOp::Cap },
            { TEXT("s.AsyncLoadingTimeLimit"), 4.f, EOp::Cap },
            { TEXT("s.PriorityAsyncLoadingExtraTime"), 0.f, EOp::Set },
            { TEXT("gc.TimeBetweenPurgingPendingKillObjects"), 600.f, EOp::AtLeast },
            { TEXT("not.in.this.build"), 1.f, EOp::Set },
        };
    }

    static FFakeCVars Defaults()
    {
        FFakeCVars C;
        C.Values.Add(TEXT("t.MaxFPS"), TEXT("60.000000"));
        C.Values.Add(TEXT("s.AsyncLoadingTimeLimit"), TEXT("5.000000"));
        C.Values.Add(TEXT("s.PriorityAsyncLoadingExtraTime"), TEXT("15.000000"));
        C.Values.Add(TEXT("gc.TimeBetweenPurgingPendingKillObjects"), TEXT("60.000000"));
        return C;
    }
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaLoadBudgetResolveTest, "Saskarta.LoadBudget.Resolve",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)
bool FSaskartaLoadBudgetResolveTest::RunTest(const FString&)
{
    using EOp = FSaskartaLoadBudgetCore::EOp;
    TestEqual("Cap lowers", FSaskartaLoadBudgetCore::Resolve(EOp::Cap, 60.f, 30.f), 30.f);
    TestEqual("Cap never raises", FSaskartaLoadBudgetCore::Resolve(EOp::Cap, 24.f, 30.f), 24.f);
    TestEqual("Cap of unlimited (0)", FSaskartaLoadBudgetCore::Resolve(EOp::Cap, 0.f, 30.f), 30.f);
    TestEqual("Cap value 0 leaves it", FSaskartaLoadBudgetCore::Resolve(EOp::Cap, 60.f, 0.f), 60.f);
    TestEqual("AtLeast raises", FSaskartaLoadBudgetCore::Resolve(EOp::AtLeast, 60.f, 600.f), 600.f);
    TestEqual("AtLeast never lowers", FSaskartaLoadBudgetCore::Resolve(EOp::AtLeast, 900.f, 600.f), 900.f);
    TestEqual("Set", FSaskartaLoadBudgetCore::Resolve(EOp::Set, 15.f, 0.f), 0.f);
    TestTrue("numeric equality", FSaskartaLoadBudgetCore::ValuesEqual(TEXT("30"), TEXT("30.000000")));
    TestFalse("numeric inequality", FSaskartaLoadBudgetCore::ValuesEqual(TEXT("30"), TEXT("60")));
    TestEqual("format int", FSaskartaLoadBudgetCore::FormatValue(30.f), FString(TEXT("30")));
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaLoadBudgetSaveRestoreTest, "Saskarta.LoadBudget.SaveRestore",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)
bool FSaskartaLoadBudgetSaveRestoreTest::RunTest(const FString&)
{
    using namespace SaskartaLoadBudgetTest;
    FFakeCVars C = Defaults();
    const FFakeCVars Before = C;
    FSaskartaLoadBudgetCore Core;

    TestTrue("first Begin applies", Core.Begin(TEXT("Loading"), Settings(), C));
    TestEqual("t.MaxFPS capped", C.Values[TEXT("t.MaxFPS")], FString(TEXT("30")));
    TestEqual("async slice", C.Values[TEXT("s.AsyncLoadingTimeLimit")], FString(TEXT("4")));
    TestEqual("priority extra off", C.Values[TEXT("s.PriorityAsyncLoadingExtraTime")], FString(TEXT("0")));
    TestEqual("gc held back", C.Values[TEXT("gc.TimeBetweenPurgingPendingKillObjects")], FString(TEXT("600")));
    TestFalse("unknown CVar not created", C.Values.Contains(TEXT("not.in.this.build")));
    TestEqual("four saved", Core.GetSaved().Num(), 4);

    TestTrue("last End restores", Core.End(TEXT("Loading"), C));
    for (const TPair<FString, FString>& P : Before.Values)
    {
        TestEqual(*FString::Printf(TEXT("%s restored exactly"), *P.Key), C.Values[P.Key], P.Value);
    }
    TestFalse("inactive", Core.IsActive());
    TestEqual("nothing saved", Core.GetSaved().Num(), 0);

    // Already within budget: no write, and nothing to restore.
    FFakeCVars Low = Defaults();
    Low.Values[TEXT("t.MaxFPS")] = TEXT("24.000000");
    Core.Begin(TEXT("Loading"), Settings(), Low);
    TestEqual("user cap below 30 kept", Low.Values[TEXT("t.MaxFPS")], FString(TEXT("24.000000")));
    TestFalse("not saved", Core.GetSaved().ContainsByPredicate([](const FSaskartaLoadBudgetCore::FSaved& S) { return S.Name == TEXT("t.MaxFPS"); }));
    Core.End(TEXT("Loading"), Low);
    TestEqual("still 24", Low.Values[TEXT("t.MaxFPS")], FString(TEXT("24.000000")));
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaLoadBudgetRefCountTest, "Saskarta.LoadBudget.RefCount",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)
bool FSaskartaLoadBudgetRefCountTest::RunTest(const FString&)
{
    using namespace SaskartaLoadBudgetTest;
    FFakeCVars C = Defaults();
    FSaskartaLoadBudgetCore Core;

    TestTrue("Begin A applies", Core.Begin(TEXT("A"), Settings(), C));
    const int32 WritesAfterA = C.Writes;
    TestFalse("Begin A again is a no-op", Core.Begin(TEXT("A"), Settings(), C));
    TestFalse("Begin B does not re-save", Core.Begin(TEXT("B"), Settings(), C));
    TestEqual("no extra writes", C.Writes, WritesAfterA);
    TestEqual("two owners", Core.NumOwners(), 2);

    TestFalse("End unknown owner", Core.End(TEXT("Z"), C));
    TestFalse("End A keeps it on (B holds)", Core.End(TEXT("A"), C));
    TestEqual("still budgeted", C.Values[TEXT("t.MaxFPS")], FString(TEXT("30")));
    TestFalse("End A twice is a no-op", Core.End(TEXT("A"), C));
    TestTrue("End B restores", Core.End(TEXT("B"), C));
    TestEqual("restored", C.Values[TEXT("t.MaxFPS")], FString(TEXT("60.000000")));
    TestFalse("End after restore is a no-op", Core.End(TEXT("B"), C));

    // Begin again after a full cycle saves the values of that moment.
    C.Values[TEXT("t.MaxFPS")] = TEXT("120.000000");
    TestTrue("re-Begin applies", Core.Begin(TEXT("Loading"), Settings(), C));
    TestTrue("ForceRestore (world teardown)", Core.ForceRestore(C));
    TestEqual("restored to the new value", C.Values[TEXT("t.MaxFPS")], FString(TEXT("120.000000")));
    TestEqual("owners cleared", Core.NumOwners(), 0);
    TestFalse("ForceRestore when idle", Core.ForceRestore(C));
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaLoadBudgetKeepChangedTest, "Saskarta.LoadBudget.KeepChanged",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)
bool FSaskartaLoadBudgetKeepChangedTest::RunTest(const FString&)
{
    using namespace SaskartaLoadBudgetTest;
    FFakeCVars C = Defaults();
    FSaskartaLoadBudgetCore Core;
    Core.Begin(TEXT("Loading"), Settings(), C);
    // The settings menu applies a 144 fps cap during loading: the restore must keep it.
    C.Values[TEXT("t.MaxFPS")] = TEXT("144.000000");
    Core.End(TEXT("Loading"), C);
    TestEqual("newer value kept", C.Values[TEXT("t.MaxFPS")], FString(TEXT("144.000000")));
    TestEqual("reported as kept", Core.GetKeptOnRestore().Num(), 1);
    TestEqual("others restored", C.Values[TEXT("s.AsyncLoadingTimeLimit")], FString(TEXT("5.000000")));
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaLoadBudgetFrameWindowTest, "Saskarta.LoadBudget.FrameWindow",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)
bool FSaskartaLoadBudgetFrameWindowTest::RunTest(const FString&)
{
    FSaskartaFrameWindow W;
    W.AddFrame(33.f);
    W.AddFrame(33.f);
    W.AddFrame(190.f);
    TestEqual("frames", W.NumFrames(), 3);
    TestEqual("max", W.MaxMs(), 190.f);
    TestEqual("hitches", W.NumHitches(), 1);
    TestTrue("mean", FMath::IsNearlyEqual(W.MeanMs(), 256.f / 3.f, 0.01f));
    W.Reset();
    TestEqual("reset", W.NumFrames(), 0);
    TestEqual("reset mean", W.MeanMs(), 0.f);
    return true;
}

// Every CVar the budget names must exist in this engine build and must not be a cheat CVar
// (refused in Shipping). r.ScreenPercentage is only added when saskarta.loadbudget.ScreenPercentage > 0.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaLoadBudgetCVarsExistTest, "Saskarta.LoadBudget.CVarsExist",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)
bool FSaskartaLoadBudgetCVarsExistTest::RunTest(const FString&)
{
    const TArray<FSaskartaLoadBudgetCore::FSetting> S = USaskartaLoadingBudget::BuildSettings();
    TestTrue("has settings", S.Num() >= 15);
    for (const FSaskartaLoadBudgetCore::FSetting& Setting : S)
    {
        const IConsoleVariable* V = IConsoleManager::Get().FindConsoleVariable(*Setting.Name);
        if (!V)
        {
            // PCG CVars live in the PCG module, loaded with the project.
            AddError(FString::Printf(TEXT("%s does not exist"), *Setting.Name));
            continue;
        }
        TestFalse(*FString::Printf(TEXT("%s is not a cheat CVar"), *Setting.Name), (V->GetFlags() & ECVF_Cheat) != 0);
    }
    return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS
