// SaskartaMenuNav: the pure navigation rules. See the header for the level table.

#include "SaskartaMenuNav.h"

namespace SaskartaMenuNav
{
    int32 StepIndex(int32 Current, int32 Direction, const TArray<bool>& Enabled, bool bWrap)
    {
        const int32 Num = Enabled.Num();
        if (Num == 0 || Direction == 0)
        {
            return INDEX_NONE;
        }
        const int32 Step = Direction > 0 ? 1 : -1;
        int32 Index = Current;
        for (int32 Tries = 0; Tries < Num; ++Tries)
        {
            Index += Step;
            if (Index < 0 || Index >= Num)
            {
                if (!bWrap)
                {
                    return INDEX_NONE;
                }
                Index = (Index + Num) % Num;
            }
            if (Index == Current)
            {
                return INDEX_NONE; // went all the way round
            }
            if (Enabled[Index])
            {
                return Index;
            }
        }
        return INDEX_NONE;
    }

    int32 FirstEnabled(const TArray<bool>& Enabled)
    {
        return Enabled.IndexOfByKey(true);
    }

    int32 LastEnabled(const TArray<bool>& Enabled)
    {
        return Enabled.FindLast(true);
    }

    int32 NearestEnabled(int32 Index, const TArray<bool>& Enabled)
    {
        if (Enabled.IsValidIndex(Index) && Enabled[Index])
        {
            return Index;
        }
        const int32 Clamped = FMath::Clamp(Index, 0, FMath::Max(0, Enabled.Num() - 1));
        for (int32 I = Clamped; I < Enabled.Num(); ++I)
        {
            if (Enabled[I])
            {
                return I;
            }
        }
        for (int32 I = FMath::Min(Clamped, Enabled.Num() - 1); I >= 0; --I)
        {
            if (Enabled[I])
            {
                return I;
            }
        }
        return INDEX_NONE;
    }

    static int32 Vertical(ESaskartaMenuAction A)
    {
        return A == ESaskartaMenuAction::Up ? -1 : (A == ESaskartaMenuAction::Down ? 1 : 0);
    }

    static int32 Horizontal(ESaskartaMenuAction A)
    {
        return A == ESaskartaMenuAction::Left ? -1 : (A == ESaskartaMenuAction::Right ? 1 : 0);
    }

    /** Enter the rows of the current tab (the remembered row if it is still enabled), or the footer if the tab has none. */
    static void EnterRows(FSaskartaMenuNavResult& R, const FSaskartaMenuNavContext& C)
    {
        const int32 Row = NearestEnabled(R.State.Row, C.RowEnabled);
        if (Row != INDEX_NONE)
        {
            R.State.Level = ESaskartaMenuLevel::Rows;
            R.State.Row = Row;
            R.bFocusChanged = true;
            return;
        }
        const int32 Foot = NearestEnabled(R.State.Footer, C.FooterEnabled);
        if (Foot != INDEX_NONE)
        {
            R.State.Level = ESaskartaMenuLevel::Footer;
            R.State.Footer = Foot;
            R.bFocusChanged = true;
        }
    }

    static void ToTabs(FSaskartaMenuNavResult& R)
    {
        R.State.Level = ESaskartaMenuLevel::Tabs;
        R.bFocusChanged = true;
    }

    FSaskartaMenuNavResult Reduce(const FSaskartaMenuNavState& State, const FSaskartaMenuNavContext& C, ESaskartaMenuAction Action)
    {
        FSaskartaMenuNavResult R;
        R.State = State;
        const int32 V = Vertical(Action);
        const int32 H = Horizontal(Action);

        switch (State.Level)
        {
        case ESaskartaMenuLevel::Menu:
        {
            if (V != 0)
            {
                R.bHandled = true;
                const int32 Next = StepIndex(State.MenuItem, V, C.MenuEnabled, /*bWrap*/ true);
                if (Next != INDEX_NONE)
                {
                    R.State.MenuItem = Next;
                    R.bFocusChanged = true;
                }
            }
            else if (Action == ESaskartaMenuAction::Accept)
            {
                R.bHandled = C.MenuEnabled.IsValidIndex(State.MenuItem) && C.MenuEnabled[State.MenuItem];
                R.Command = R.bHandled ? ESaskartaMenuCommand::Activate : ESaskartaMenuCommand::None;
            }
            else if (Action == ESaskartaMenuAction::Back)
            {
                // The widget decides whether Back is used (OnBack); the title ignores it.
                R.Command = ESaskartaMenuCommand::Back;
                R.bHandled = true;
            }
            // Left/Right: not used by a flat menu (left to Slate / the game).
            break;
        }

        case ESaskartaMenuLevel::Tabs:
        {
            R.bHandled = true;
            if (V != 0)
            {
                const int32 Next = StepIndex(State.Tab, V, C.TabEnabled, /*bWrap*/ false);
                if (Next != INDEX_NONE)
                {
                    R.State.Tab = Next;
                    R.State.Row = 0; // a new page starts at its first row
                    R.bFocusChanged = true;
                }
            }
            else if (Action == ESaskartaMenuAction::Accept || Action == ESaskartaMenuAction::Right)
            {
                EnterRows(R, C);
            }
            else if (Action == ESaskartaMenuAction::Back)
            {
                if (C.bDirty)
                {
                    R.State.Level = ESaskartaMenuLevel::Dialog;
                    R.State.Dialog = ESaskartaMenuDialog::ApplyChanges;
                    R.State.DialogButton = 0;
                    R.State.LevelBeforeDialog = ESaskartaMenuLevel::Tabs;
                    R.Command = ESaskartaMenuCommand::ShowApplyPrompt;
                    R.bFocusChanged = true;
                }
                else
                {
                    R.Command = ESaskartaMenuCommand::Back;
                }
            }
            // Left: nothing to the left of the tab list; consumed so Slate does not wander.
            break;
        }

        case ESaskartaMenuLevel::Rows:
        {
            R.bHandled = true;
            const bool bValidRow = C.RowEnabled.IsValidIndex(State.Row);
            const ESaskartaMenuRowType Type = C.RowTypes.IsValidIndex(State.Row) ? C.RowTypes[State.Row] : ESaskartaMenuRowType::Button;
            if (V < 0)
            {
                const int32 Prev = StepIndex(State.Row, -1, C.RowEnabled, /*bWrap*/ false);
                if (Prev != INDEX_NONE)
                {
                    R.State.Row = Prev;
                    R.bFocusChanged = true;
                }
            }
            else if (V > 0)
            {
                const int32 Next = StepIndex(State.Row, 1, C.RowEnabled, /*bWrap*/ false);
                if (Next != INDEX_NONE)
                {
                    R.State.Row = Next;
                    R.bFocusChanged = true;
                }
                else
                {
                    const int32 Foot = FirstEnabled(C.FooterEnabled);
                    if (Foot != INDEX_NONE)
                    {
                        R.State.Level = ESaskartaMenuLevel::Footer;
                        R.State.Footer = Foot;
                        R.bFocusChanged = true;
                    }
                }
            }
            else if (H != 0)
            {
                if (bValidRow && Type != ESaskartaMenuRowType::Button)
                {
                    R.Command = ESaskartaMenuCommand::Cycle;
                    R.Direction = H;
                }
            }
            else if (Action == ESaskartaMenuAction::Accept)
            {
                if (bValidRow && Type != ESaskartaMenuRowType::Slider)
                {
                    R.Command = ESaskartaMenuCommand::Activate;
                }
            }
            else if (Action == ESaskartaMenuAction::Back)
            {
                ToTabs(R);
            }
            break;
        }

        case ESaskartaMenuLevel::Footer:
        {
            R.bHandled = true;
            if (H != 0)
            {
                const int32 Next = StepIndex(State.Footer, H, C.FooterEnabled, /*bWrap*/ false);
                if (Next != INDEX_NONE)
                {
                    R.State.Footer = Next;
                    R.bFocusChanged = true;
                }
            }
            else if (V < 0)
            {
                const int32 Row = LastEnabled(C.RowEnabled);
                if (Row != INDEX_NONE)
                {
                    R.State.Level = ESaskartaMenuLevel::Rows;
                    R.State.Row = Row;
                    R.bFocusChanged = true;
                }
                else
                {
                    ToTabs(R);
                }
            }
            else if (Action == ESaskartaMenuAction::Accept)
            {
                if (C.FooterEnabled.IsValidIndex(State.Footer) && C.FooterEnabled[State.Footer])
                {
                    R.Command = ESaskartaMenuCommand::Activate;
                }
            }
            else if (Action == ESaskartaMenuAction::Back)
            {
                ToTabs(R);
            }
            break;
        }

        case ESaskartaMenuLevel::Dialog:
        {
            R.bHandled = true; // a modal eats every navigation input
            const int32 Move = H != 0 ? H : V;
            if (Move != 0)
            {
                const int32 Next = StepIndex(State.DialogButton, Move, C.DialogEnabled, /*bWrap*/ true);
                if (Next != INDEX_NONE)
                {
                    R.State.DialogButton = Next;
                    R.bFocusChanged = true;
                }
            }
            else if (Action == ESaskartaMenuAction::Accept)
            {
                R.Command = ESaskartaMenuCommand::DialogConfirm;
            }
            else if (Action == ESaskartaMenuAction::Back)
            {
                R.State.DialogButton = C.DialogCancelIndex;
                R.Command = ESaskartaMenuCommand::DialogCancel;
            }
            break;
        }
        }
        return R;
    }
}
