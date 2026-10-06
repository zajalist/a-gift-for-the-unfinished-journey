#include "SaskartaPauseLogic.h"
#include "Misc/AutomationTest.h"

#if WITH_DEV_AUTOMATION_TESTS
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaPauseFlowTest, "Saskarta.Pause.CollapseAndWalk",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)
bool FSaskartaPauseFlowTest::RunTest(const FString&)
{
    using namespace SaskartaPause;
    for (const FName Flow : { FName(TEXT("Collapsing")), FName(TEXT("Human")),
                              FName(TEXT("Rebooting")), FName(TEXT("Transmit")) })
    {
        TestTrue(TEXT("collapse black, its prompt and the walk can open pause"), IsPausableFlow(Flow));
        TestTrue(TEXT("Escape/Menu opens from this flow"), Decide(Flow, false, false) == EAction::Open);
        TestTrue(TEXT("repeat cannot open twice"), Decide(Flow, false, true) == EAction::Swallow);
    }
    TestTrue(TEXT("Menu backs out or resumes when paused"), Decide(TEXT("Paused"), true, false) == EAction::Toggle);
    TestTrue(TEXT("a missing menu can be recovered"), Decide(TEXT("Paused"), false, false) == EAction::Close);
    TestTrue(TEXT("title remains with its own input"), Decide(TEXT("Title"), false, false) == EAction::Pass);
    return true;
}
#endif
