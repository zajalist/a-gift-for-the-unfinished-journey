// Automation tests for SaskartaMenuNav::Reduce (task MENUINPUT): the settings
// two-level navigation, the footer, the modal dialogs and the flat menu, without widgets.
//
//   Automation RunTests Saskarta.Menu
//
// Written offline with the implementation (the editor was open); the closed-editor build
// session runs them first.

#include "Misc/AutomationTest.h"

#if WITH_DEV_AUTOMATION_TESTS

#include "SaskartaMenuNav.h"
#include "SaskartaMenuWidget.h"
#include "InputCoreTypes.h"

namespace SaskartaMenuNavTest
{
    /** Five tabs; the current tab has four rows (Selector, Toggle, Slider, Button), the third collapsed when bHideRow2. */
    static FSaskartaMenuNavContext Settings(bool bDirty = false, bool bHideRow2 = false)
    {
        FSaskartaMenuNavContext C;
        C.TabEnabled = { true, true, true, true, true };
        C.RowEnabled = { true, true, !bHideRow2, true };
        C.RowTypes = { ESaskartaMenuRowType::Selector, ESaskartaMenuRowType::Toggle, ESaskartaMenuRowType::Slider, ESaskartaMenuRowType::Button };
        C.FooterEnabled = { true, true, true };
        C.bDirty = bDirty;
        return C;
    }

    static FSaskartaMenuNavState At(ESaskartaMenuLevel Level, int32 Tab = 0, int32 Row = 0, int32 Footer = 0)
    {
        FSaskartaMenuNavState S;
        S.Level = Level;
        S.Tab = Tab;
        S.Row = Row;
        S.Footer = Footer;
        return S;
    }
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaMenuStepIndexTest, "Saskarta.Menu.StepIndex",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)
bool FSaskartaMenuStepIndexTest::RunTest(const FString&)
{
    using namespace SaskartaMenuNav;
    const TArray<bool> E = { true, false, true, true };
    TestEqual(TEXT("skips a disabled entry"), StepIndex(0, 1, E, false), 2);
    TestEqual(TEXT("stops at the end without wrap"), StepIndex(3, 1, E, false), int32(INDEX_NONE));
    TestEqual(TEXT("wraps"), StepIndex(3, 1, E, true), 0);
    TestEqual(TEXT("wraps backwards over a disabled entry"), StepIndex(2, -1, E, true), 0);
    TestEqual(TEXT("nothing else enabled"), StepIndex(0, 1, TArray<bool>{ true, false }, true), int32(INDEX_NONE));
    TestEqual(TEXT("empty"), StepIndex(0, 1, TArray<bool>(), true), int32(INDEX_NONE));
    TestEqual(TEXT("nearest keeps an enabled index"), NearestEnabled(2, E), 2);
    TestEqual(TEXT("nearest moves forward from a disabled one"), NearestEnabled(1, E), 2);
    TestEqual(TEXT("nearest falls back to earlier"), NearestEnabled(3, TArray<bool>{ true, true, false, false }), 1);
    TestEqual(TEXT("first / last"), FirstEnabled(E) * 10 + LastEnabled(E), 3);
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaMenuTabsTest, "Saskarta.Menu.Tabs",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)
bool FSaskartaMenuTabsTest::RunTest(const FString&)
{
    using namespace SaskartaMenuNavTest;
    const FSaskartaMenuNavContext C = Settings();

    // Down moves to the next tab (the page follows: the widget opens State.Tab).
    FSaskartaMenuNavResult R = SaskartaMenuNav::Reduce(At(ESaskartaMenuLevel::Tabs, 1), C, ESaskartaMenuAction::Down);
    TestTrue(TEXT("down: handled and focus moves"), R.bHandled && R.bFocusChanged);
    TestEqual(TEXT("down: next tab"), R.State.Tab, 2);
    TestTrue(TEXT("down: still on the tab list"), R.State.Level == ESaskartaMenuLevel::Tabs);
    // Up at the first tab stays (consumed).
    R = SaskartaMenuNav::Reduce(At(ESaskartaMenuLevel::Tabs, 0), C, ESaskartaMenuAction::Up);
    TestTrue(TEXT("up at the top: consumed, no move"), R.bHandled && !R.bFocusChanged && R.State.Tab == 0);

    // Enter and Right both enter the rows at the first row.
    for (const ESaskartaMenuAction A : { ESaskartaMenuAction::Accept, ESaskartaMenuAction::Right })
    {
        R = SaskartaMenuNav::Reduce(At(ESaskartaMenuLevel::Tabs, 2), C, A);
        TestTrue(TEXT("enter/right: into the rows"), R.State.Level == ESaskartaMenuLevel::Rows && R.State.Row == 0 && R.State.Tab == 2 && R.bFocusChanged);
    }

    // Esc with nothing unapplied: leave Settings.
    R = SaskartaMenuNav::Reduce(At(ESaskartaMenuLevel::Tabs, 2), C, ESaskartaMenuAction::Back);
    TestTrue(TEXT("esc clean: Back"), R.Command == ESaskartaMenuCommand::Back);

    // Esc with unapplied changes: the "Apply changes?" prompt, Apply focused.
    R = SaskartaMenuNav::Reduce(At(ESaskartaMenuLevel::Tabs, 2), Settings(/*bDirty*/ true), ESaskartaMenuAction::Back);
    TestTrue(TEXT("esc dirty: prompt"), R.Command == ESaskartaMenuCommand::ShowApplyPrompt);
    TestTrue(TEXT("esc dirty: dialog level"), R.State.Level == ESaskartaMenuLevel::Dialog && R.State.Dialog == ESaskartaMenuDialog::ApplyChanges);
    TestTrue(TEXT("esc dirty: returns to the tab list"), R.State.LevelBeforeDialog == ESaskartaMenuLevel::Tabs);
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaMenuRowsTest, "Saskarta.Menu.Rows",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)
bool FSaskartaMenuRowsTest::RunTest(const FString&)
{
    using namespace SaskartaMenuNavTest;
    const FSaskartaMenuNavContext C = Settings();

    // Left/Right cycle a selector / toggle / slider; not a button.
    FSaskartaMenuNavResult R = SaskartaMenuNav::Reduce(At(ESaskartaMenuLevel::Rows, 0, 0), C, ESaskartaMenuAction::Left);
    TestTrue(TEXT("left on a selector: cycle -1"), R.Command == ESaskartaMenuCommand::Cycle && R.Direction == -1 && !R.bFocusChanged);
    R = SaskartaMenuNav::Reduce(At(ESaskartaMenuLevel::Rows, 0, 2), C, ESaskartaMenuAction::Right);
    TestTrue(TEXT("right on a slider: cycle +1"), R.Command == ESaskartaMenuCommand::Cycle && R.Direction == 1);
    R = SaskartaMenuNav::Reduce(At(ESaskartaMenuLevel::Rows, 0, 3), C, ESaskartaMenuAction::Right);
    TestTrue(TEXT("right on a button: consumed, nothing"), R.bHandled && R.Command == ESaskartaMenuCommand::None);

    // Enter toggles / activates; not on a slider.
    R = SaskartaMenuNav::Reduce(At(ESaskartaMenuLevel::Rows, 0, 1), C, ESaskartaMenuAction::Accept);
    TestTrue(TEXT("enter on a toggle: activate"), R.Command == ESaskartaMenuCommand::Activate);
    R = SaskartaMenuNav::Reduce(At(ESaskartaMenuLevel::Rows, 0, 3), C, ESaskartaMenuAction::Accept);
    TestTrue(TEXT("enter on a button: activate"), R.Command == ESaskartaMenuCommand::Activate);
    R = SaskartaMenuNav::Reduce(At(ESaskartaMenuLevel::Rows, 0, 2), C, ESaskartaMenuAction::Accept);
    TestTrue(TEXT("enter on a slider: nothing"), R.Command == ESaskartaMenuCommand::None);

    // Down skips a collapsed row; Down past the last row goes to the footer's first button.
    R = SaskartaMenuNav::Reduce(At(ESaskartaMenuLevel::Rows, 0, 1), Settings(false, /*bHideRow2*/ true), ESaskartaMenuAction::Down);
    TestEqual(TEXT("down skips the collapsed row"), R.State.Row, 3);
    R = SaskartaMenuNav::Reduce(At(ESaskartaMenuLevel::Rows, 0, 3), C, ESaskartaMenuAction::Down);
    TestTrue(TEXT("down past the last row: footer Apply"), R.State.Level == ESaskartaMenuLevel::Footer && R.State.Footer == 0 && R.bFocusChanged);
    // Up at the first row stays.
    R = SaskartaMenuNav::Reduce(At(ESaskartaMenuLevel::Rows, 0, 0), C, ESaskartaMenuAction::Up);
    TestTrue(TEXT("up at the first row: stays"), R.State.Level == ESaskartaMenuLevel::Rows && R.State.Row == 0 && !R.bFocusChanged);

    // Esc returns to the tab list on the same tab (the widget focuses that tab).
    R = SaskartaMenuNav::Reduce(At(ESaskartaMenuLevel::Rows, 3, 2), C, ESaskartaMenuAction::Back);
    TestTrue(TEXT("esc in rows: tab list, current tab"), R.State.Level == ESaskartaMenuLevel::Tabs && R.State.Tab == 3 && R.bFocusChanged);
    TestTrue(TEXT("esc in rows: does not leave"), R.Command == ESaskartaMenuCommand::None);
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaMenuFooterTest, "Saskarta.Menu.Footer",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)
bool FSaskartaMenuFooterTest::RunTest(const FString&)
{
    using namespace SaskartaMenuNavTest;
    const FSaskartaMenuNavContext C = Settings();
    FSaskartaMenuNavResult R = SaskartaMenuNav::Reduce(At(ESaskartaMenuLevel::Footer, 0, 0, 0), C, ESaskartaMenuAction::Right);
    TestEqual(TEXT("right: Revert"), R.State.Footer, 1);
    R = SaskartaMenuNav::Reduce(At(ESaskartaMenuLevel::Footer, 0, 0, 2), C, ESaskartaMenuAction::Right);
    TestTrue(TEXT("right at Back: stays"), R.State.Footer == 2 && !R.bFocusChanged);
    R = SaskartaMenuNav::Reduce(At(ESaskartaMenuLevel::Footer, 0, 0, 1), C, ESaskartaMenuAction::Up);
    TestTrue(TEXT("up: the last row"), R.State.Level == ESaskartaMenuLevel::Rows && R.State.Row == 3);
    R = SaskartaMenuNav::Reduce(At(ESaskartaMenuLevel::Footer, 0, 0, 0), C, ESaskartaMenuAction::Accept);
    TestTrue(TEXT("enter: activate"), R.Command == ESaskartaMenuCommand::Activate);
    R = SaskartaMenuNav::Reduce(At(ESaskartaMenuLevel::Footer, 4, 0, 0), C, ESaskartaMenuAction::Back);
    TestTrue(TEXT("esc: tab list"), R.State.Level == ESaskartaMenuLevel::Tabs && R.State.Tab == 4);
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaMenuDialogTest, "Saskarta.Menu.Dialog",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)
bool FSaskartaMenuDialogTest::RunTest(const FString&)
{
    using namespace SaskartaMenuNavTest;
    // The keep-or-revert check: Keep (0), Revert (1); opened on Revert.
    FSaskartaMenuNavContext C = Settings();
    C.DialogEnabled = { true, true };
    C.DialogCancelIndex = 1;
    FSaskartaMenuNavState S = At(ESaskartaMenuLevel::Dialog);
    S.Dialog = ESaskartaMenuDialog::KeepOrRevert;
    S.DialogButton = 1;
    S.LevelBeforeDialog = ESaskartaMenuLevel::Footer;

    FSaskartaMenuNavResult R = SaskartaMenuNav::Reduce(S, C, ESaskartaMenuAction::Left);
    TestEqual(TEXT("left: Keep"), R.State.DialogButton, 0);
    R = SaskartaMenuNav::Reduce(R.State, C, ESaskartaMenuAction::Right);
    TestEqual(TEXT("right: Revert"), R.State.DialogButton, 1);
    R = SaskartaMenuNav::Reduce(S, C, ESaskartaMenuAction::Accept);
    TestTrue(TEXT("enter: confirm the focused button"), R.Command == ESaskartaMenuCommand::DialogConfirm && R.State.DialogButton == 1);
    FSaskartaMenuNavState OnKeep = S;
    OnKeep.DialogButton = 0;
    R = SaskartaMenuNav::Reduce(OnKeep, C, ESaskartaMenuAction::Back);
    TestTrue(TEXT("esc: Revert (the cancel button)"), R.Command == ESaskartaMenuCommand::DialogCancel && R.State.DialogButton == 1);
    // Everything else is swallowed by the modal.
    R = SaskartaMenuNav::Reduce(S, C, ESaskartaMenuAction::Down);
    TestTrue(TEXT("down: stays in the dialog"), R.bHandled && R.State.Level == ESaskartaMenuLevel::Dialog);

    // The "Apply changes?" prompt: Apply (0), Discard (1), Cancel (2); Esc = Cancel.
    C.DialogEnabled = { true, true, true };
    C.DialogCancelIndex = 2;
    S.Dialog = ESaskartaMenuDialog::ApplyChanges;
    S.DialogButton = 0;
    R = SaskartaMenuNav::Reduce(S, C, ESaskartaMenuAction::Back);
    TestTrue(TEXT("prompt esc: Cancel"), R.Command == ESaskartaMenuCommand::DialogCancel && R.State.DialogButton == 2);
    R = SaskartaMenuNav::Reduce(S, C, ESaskartaMenuAction::Left);
    TestEqual(TEXT("prompt left from Apply wraps to Cancel"), R.State.DialogButton, 2);
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaMenuFlatTest, "Saskarta.Menu.Flat",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)
bool FSaskartaMenuFlatTest::RunTest(const FString&)
{
    // The title / pause menu: Up/Down wrap, Enter clicks, Esc asks the widget, Left/Right pass on.
    FSaskartaMenuNavContext C;
    C.MenuEnabled = { true, true, true };
    FSaskartaMenuNavState S;
    S.Level = ESaskartaMenuLevel::Menu;
    S.MenuItem = 2;
    FSaskartaMenuNavResult R = SaskartaMenuNav::Reduce(S, C, ESaskartaMenuAction::Down);
    TestEqual(TEXT("down wraps to the first item"), R.State.MenuItem, 0);
    R = SaskartaMenuNav::Reduce(S, C, ESaskartaMenuAction::Accept);
    TestTrue(TEXT("enter: activate"), R.Command == ESaskartaMenuCommand::Activate);
    R = SaskartaMenuNav::Reduce(S, C, ESaskartaMenuAction::Back);
    TestTrue(TEXT("esc: Back command"), R.Command == ESaskartaMenuCommand::Back);
    R = SaskartaMenuNav::Reduce(S, C, ESaskartaMenuAction::Left);
    TestFalse(TEXT("left: not handled"), R.bHandled);
    return true;
}

// ---------------------------------------------------------------------------- CPPBATCH: the menu's keys

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaMenuKeyMapTest, "Saskarta.Menu.KeyMap",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)
bool FSaskartaMenuKeyMapTest::RunTest(const FString&)
{
    auto Maps = [](const FKey& Key, ESaskartaMenuAction Want)
    {
        ESaskartaMenuAction A = ESaskartaMenuAction::Up;
        return USaskartaMenuWidget::MapMenuKey(Key, A) && A == Want;
    };
    auto Ignored = [](const FKey& Key)
    {
        ESaskartaMenuAction A = ESaskartaMenuAction::Up;
        return !USaskartaMenuWidget::MapMenuKey(Key, A);
    };
    TestTrue("Up", Maps(EKeys::Up, ESaskartaMenuAction::Up));
    TestTrue("Down", Maps(EKeys::Down, ESaskartaMenuAction::Down));
    TestTrue("Left", Maps(EKeys::Left, ESaskartaMenuAction::Left));
    TestTrue("Right", Maps(EKeys::Right, ESaskartaMenuAction::Right));
    TestTrue("D-pad up", Maps(EKeys::Gamepad_DPad_Up, ESaskartaMenuAction::Up));
    TestTrue("left stick right", Maps(EKeys::Gamepad_LeftStick_Right, ESaskartaMenuAction::Right));
    TestTrue("Enter accepts", Maps(EKeys::Enter, ESaskartaMenuAction::Accept));
    TestTrue("A accepts", Maps(EKeys::Gamepad_FaceButton_Bottom, ESaskartaMenuAction::Accept));
    TestTrue("Esc backs", Maps(EKeys::Escape, ESaskartaMenuAction::Back));
    TestTrue("B backs", Maps(EKeys::Gamepad_FaceButton_Right, ESaskartaMenuAction::Back));

    // Never the mouse, never keys that belong to the widgets or the game.
    TestTrue("left mouse", Ignored(EKeys::LeftMouseButton));
    TestTrue("right mouse", Ignored(EKeys::RightMouseButton));
    TestTrue("wheel", Ignored(EKeys::MouseScrollUp));
    TestTrue("Tab", Ignored(EKeys::Tab));
    TestTrue("Space (the focused button's own)", Ignored(EKeys::SpaceBar));
    TestTrue("W", Ignored(EKeys::W));
    TestTrue("R (the radio)", Ignored(EKeys::R));
    TestTrue("right stick", Ignored(EKeys::Gamepad_RightStick_Up));
    TestTrue("F9 (debug)", Ignored(EKeys::F9));
    return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS
