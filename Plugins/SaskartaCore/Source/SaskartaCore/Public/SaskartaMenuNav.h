// SaskartaMenuNav: the menu navigation rules as a pure function (task MENUINPUT).
//
// USaskartaMenuWidget maps a key or a navigation event to an ESaskartaMenuAction,
// fills a FSaskartaMenuNavContext from its registered widgets, and runs Reduce().
// The result is the new FSaskartaMenuNavState plus one command for the widget to
// carry out (move the focus, cycle a value, click a button, open the prompt, ...).
// Keeping the rules here means they are unit-tested without any widget
// (Private/Tests/SaskartaMenuNavTest.cpp).
//
// Levels:
//   Menu    a flat list (the title's Start / Settings / Quit, the pause menu).
//   Tabs    the settings category list. Up/Down moves between tabs and the page
//           follows live; Enter/Right enters the rows; Esc/B leaves Settings, and
//           asks "Apply changes?" first when there are unapplied changes.
//   Rows    the current tab's rows. Up/Down moves; Down past the last row goes to
//           the footer; Left/Right cycles a selector, steps a slider or flips a
//           toggle; Enter toggles or activates; Esc returns to the tab list.
//   Footer  Apply / Revert / Back. Left/Right moves; Up returns to the last row;
//           Enter clicks; Esc returns to the tab list.
//   Dialog  a modal (the keep-or-revert check, the "Apply changes?" prompt).
//           Left/Right (or Up/Down) moves between its buttons; Enter confirms;
//           Esc picks the dialog's cancel button (Revert / Cancel).

#pragma once

#include "CoreMinimal.h"
#include "SaskartaMenuNav.generated.h"

/** What a settings row's control is, which decides what Left/Right and Enter do. */
UENUM(BlueprintType)
enum class ESaskartaMenuRowType : uint8
{
    /** A ComboBoxString with ◀ ▶: Left/Right and Enter step through the options. */
    Selector,
    /** A Slider: Left/Right step it by its StepSize. */
    Slider,
    /** A CheckBox: Left/Right and Enter flip it. */
    Toggle,
    /** A Button: Enter clicks it; Left/Right do nothing. */
    Button
};

/** Where the menu focus is. */
UENUM(BlueprintType)
enum class ESaskartaMenuLevel : uint8
{
    Menu,
    Tabs,
    Rows,
    Footer,
    Dialog
};

/** Which modal is open. */
UENUM(BlueprintType)
enum class ESaskartaMenuDialog : uint8
{
    None,
    /** The 15 s "Keep these display settings?" check (Keep / Revert). */
    KeepOrRevert,
    /** "Apply changes?" when leaving Settings with unapplied changes (Apply / Discard / Cancel). */
    ApplyChanges
};

/** One navigation input, after key / gamepad / analog mapping. */
enum class ESaskartaMenuAction : uint8
{
    Up,
    Down,
    Left,
    Right,
    Accept,
    Back
};

/** What the widget must do after Reduce(). */
enum class ESaskartaMenuCommand : uint8
{
    /** Nothing beyond focusing the state's widget (if bFocusChanged). */
    None,
    /** Left/Right on a row: cycle / step / flip it by Direction. */
    Cycle,
    /** Enter on a menu item, a row or a footer button. */
    Activate,
    /** Leave this menu (Esc at the top level with nothing unapplied). */
    Back,
    /** Esc at the tab list with unapplied changes: open the "Apply changes?" prompt. */
    ShowApplyPrompt,
    /** Enter in a dialog: press State.DialogButton. */
    DialogConfirm,
    /** Esc in a dialog: press the dialog's cancel button (DialogCancelIndex). */
    DialogCancel
};

struct FSaskartaMenuNavState
{
    ESaskartaMenuLevel Level = ESaskartaMenuLevel::Menu;
    int32 MenuItem = 0;
    int32 Tab = 0;
    int32 Row = 0;
    int32 Footer = 0;
    ESaskartaMenuDialog Dialog = ESaskartaMenuDialog::None;
    int32 DialogButton = 0;
    /** Where Esc / a closed dialog returns to. */
    ESaskartaMenuLevel LevelBeforeDialog = ESaskartaMenuLevel::Tabs;

    bool operator==(const FSaskartaMenuNavState& O) const
    {
        return Level == O.Level && MenuItem == O.MenuItem && Tab == O.Tab && Row == O.Row && Footer == O.Footer
            && Dialog == O.Dialog && DialogButton == O.DialogButton && LevelBeforeDialog == O.LevelBeforeDialog;
    }
};

/** A snapshot of what can take the focus right now. false = hidden, collapsed or disabled. */
struct FSaskartaMenuNavContext
{
    TArray<bool> MenuEnabled;
    TArray<bool> TabEnabled;
    /** The rows of State.Tab only. */
    TArray<bool> RowEnabled;
    TArray<ESaskartaMenuRowType> RowTypes;
    TArray<bool> FooterEnabled;
    /** The open dialog's buttons. */
    TArray<bool> DialogEnabled;
    int32 DialogCancelIndex = 0;
    /** There are unapplied changes (asks "Apply changes?" on Esc from the tab list). */
    bool bDirty = false;
};

struct FSaskartaMenuNavResult
{
    FSaskartaMenuNavState State;
    ESaskartaMenuCommand Command = ESaskartaMenuCommand::None;
    /** -1 / +1 for Cycle. */
    int32 Direction = 0;
    /** The focus moved to another widget (the widget focuses State's target). */
    bool bFocusChanged = false;
    /** The input was used; the widget consumes the key. */
    bool bHandled = false;
};

namespace SaskartaMenuNav
{
    /**
     * The next enabled index from Current in Direction (+1 / -1). Without wrap it
     * returns INDEX_NONE past either end; with wrap it goes round. INDEX_NONE if
     * nothing else is enabled.
     */
    SASKARTACORE_API int32 StepIndex(int32 Current, int32 Direction, const TArray<bool>& Enabled, bool bWrap);

    /** The first / last enabled index, or INDEX_NONE. */
    SASKARTACORE_API int32 FirstEnabled(const TArray<bool>& Enabled);
    SASKARTACORE_API int32 LastEnabled(const TArray<bool>& Enabled);

    /** Index if it is enabled, else the nearest enabled one after it, else before it, else INDEX_NONE. */
    SASKARTACORE_API int32 NearestEnabled(int32 Index, const TArray<bool>& Enabled);

    /** Applies one action. See the level table at the top of this file. */
    SASKARTACORE_API FSaskartaMenuNavResult Reduce(const FSaskartaMenuNavState& State, const FSaskartaMenuNavContext& Context, ESaskartaMenuAction Action);
}
