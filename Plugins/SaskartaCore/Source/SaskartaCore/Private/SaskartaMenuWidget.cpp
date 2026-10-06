// USaskartaMenuWidget (task MENUINPUT). See the header and SaskartaMenuNav.h.

#include "SaskartaMenuWidget.h"

#include "Components/Button.h"
#include "Components/CheckBox.h"
#include "Components/ComboBoxString.h"
#include "Components/PanelWidget.h"
#include "Components/ScrollBox.h"
#include "Components/Slider.h"
#include "Components/TextBlock.h"
#include "Components/WidgetSwitcher.h"
#include "Engine/GameViewportClient.h"
#include "Engine/World.h"
#include "Framework/Application/SlateApplication.h"
#include "GameFramework/PlayerController.h"
#include "InputCoreTypes.h"
#include "TimerManager.h"
#include "UObject/UnrealType.h"
#include "Widgets/SViewport.h"

DEFINE_LOG_CATEGORY_STATIC(LogSaskartaMenu, Log, All);

namespace SaskartaMenuWidgetImpl
{
    template <typename T>
    static TArray<bool> UsableFlags(const USaskartaMenuWidget* Owner, const TArray<TWeakObjectPtr<T>>& Widgets, TFunctionRef<bool(const UWidget*)> IsUsable)
    {
        TArray<bool> Out;
        Out.Reserve(Widgets.Num());
        for (const TWeakObjectPtr<T>& W : Widgets)
        {
            Out.Add(IsUsable(W.Get()));
        }
        return Out;
    }

    template <typename T>
    static UWidget* At(const TArray<TWeakObjectPtr<T>>& Widgets, int32 Index)
    {
        return Widgets.IsValidIndex(Index) ? Widgets[Index].Get() : nullptr;
    }

    /** Buttons of a tree in depth-first order. */
    static void CollectButtons(UWidget* Widget, TArray<UWidget*>& Out)
    {
        if (!Widget)
        {
            return;
        }
        if (Widget->IsA<UButton>())
        {
            Out.Add(Widget);
            return;
        }
        if (const UPanelWidget* Panel = Cast<UPanelWidget>(Widget))
        {
            for (int32 I = 0; I < Panel->GetChildrenCount(); ++I)
            {
                CollectButtons(Panel->GetChildAt(I), Out);
            }
        }
    }
}

USaskartaMenuWidget::USaskartaMenuWidget(const FObjectInitializer& ObjectInitializer)
    : Super(ObjectInitializer)
{
    ArrowButtonSuffixes = { TEXT("Prev"), TEXT("Next") };
    FooterButtonNames = { TEXT("ApplyButton"), TEXT("RevertButton"), TEXT("BackButton") };
    KeepDialogButtonNames = { TEXT("KeepButton"), TEXT("RevertNowButton") };
    PromptButtonNames = { TEXT("PromptApplyButton"), TEXT("PromptDiscardButton"), TEXT("PromptCancelButton") };
    AppliedText = NSLOCTEXT("SaskartaMenu", "Applied", "Applied");
    RevertedText = NSLOCTEXT("SaskartaMenu", "Reverted", "Reverted");
}

// ─── Registration ────────────────────────────────────────────────────────────

void USaskartaMenuWidget::RegisterMenuItems(const TArray<UWidget*>& Items)
{
    MenuItems.Reset();
    for (UWidget* W : Items)
    {
        if (W)
        {
            MenuItems.Add(W);
        }
    }
    Nav.MenuItem = FMath::Clamp(Nav.MenuItem, 0, FMath::Max(0, MenuItems.Num() - 1));
}

void USaskartaMenuWidget::RegisterTabs(const TArray<UWidget*>& TabButtons, UWidgetSwitcher* Pages)
{
    Tabs.Reset();
    for (UWidget* W : TabButtons)
    {
        if (W)
        {
            Tabs.Add(W);
        }
    }
    TabPages = Pages;
    TabRows.SetNum(FMath::Max(TabRows.Num(), Tabs.Num()));
    Nav.Tab = FMath::Clamp(Nav.Tab, 0, FMath::Max(0, Tabs.Num() - 1));
}

void USaskartaMenuWidget::RegisterRows(int32 TabIndex, const TArray<UWidget*>& Rows, const TArray<ESaskartaMenuRowType>& Types)
{
    if (TabIndex < 0)
    {
        return;
    }
    if (!TabRows.IsValidIndex(TabIndex))
    {
        TabRows.SetNum(TabIndex + 1);
    }
    FTabRows& Tab = TabRows[TabIndex];
    Tab.Rows.Reset();
    Tab.Types.Reset();
    for (int32 I = 0; I < Rows.Num(); ++I)
    {
        UWidget* W = Rows[I];
        if (!W)
        {
            continue;
        }
        Tab.Rows.Add(W);
        Tab.Types.Add(Types.IsValidIndex(I) ? Types[I] : TypeOf(W));
        BindDirtySources(W);
    }
}

void USaskartaMenuWidget::RegisterFooter(const TArray<UWidget*>& Buttons)
{
    FooterButtons.Reset();
    for (UWidget* W : Buttons)
    {
        if (!W)
        {
            continue;
        }
        FooterButtons.Add(W);
        if (UButton* B = Cast<UButton>(W))
        {
            if (W->GetFName() == ApplyButtonName)
            {
                B->OnClicked.AddUniqueDynamic(this, &USaskartaMenuWidget::HandleApplyClicked);
            }
            else if (W->GetFName() == RevertButtonName)
            {
                B->OnClicked.AddUniqueDynamic(this, &USaskartaMenuWidget::HandleRevertClicked);
            }
        }
    }
}

void USaskartaMenuWidget::RegisterDialog(ESaskartaMenuDialog Dialog, UWidget* Root, const TArray<UWidget*>& Buttons, int32 DefaultIndex, int32 CancelIndex)
{
    FDialogInfo* Info = Dialog == ESaskartaMenuDialog::KeepOrRevert ? &KeepDialog
        : (Dialog == ESaskartaMenuDialog::ApplyChanges ? &PromptDialog : nullptr);
    if (!Info)
    {
        return;
    }
    *Info = FDialogInfo();
    Info->Root = Root;
    for (UWidget* W : Buttons)
    {
        if (W)
        {
            Info->Buttons.Add(W);
        }
    }
    const int32 Last = FMath::Max(0, Info->Buttons.Num() - 1);
    Info->DefaultIndex = FMath::Clamp(DefaultIndex, 0, Last);
    Info->CancelIndex = FMath::Clamp(CancelIndex, 0, Last);

    // Mouse clicks on the dialog buttons: the same bookkeeping as Enter.
    for (int32 I = 0; I < Info->Buttons.Num(); ++I)
    {
        UButton* B = Cast<UButton>(Info->Buttons[I].Get());
        if (!B)
        {
            continue;
        }
        if (Dialog == ESaskartaMenuDialog::KeepOrRevert)
        {
            if (I == 0)
            {
                B->OnClicked.AddUniqueDynamic(this, &USaskartaMenuWidget::HandleKeepClicked);
            }
            else
            {
                B->OnClicked.AddUniqueDynamic(this, &USaskartaMenuWidget::HandleRevertNowClicked);
            }
        }
        else if (I == 0)
        {
            B->OnClicked.AddUniqueDynamic(this, &USaskartaMenuWidget::HandlePromptApply);
        }
        else if (I == 1)
        {
            B->OnClicked.AddUniqueDynamic(this, &USaskartaMenuWidget::HandlePromptDiscard);
        }
        else
        {
            B->OnClicked.AddUniqueDynamic(this, &USaskartaMenuWidget::HandlePromptCancel);
        }
    }
}

void USaskartaMenuWidget::AutoRegister()
{
    MenuItems.Reset();
    Tabs.Reset();
    TabPages = nullptr;
    TabRows.Reset();
    FooterButtons.Reset();
    Combos.Reset();
    ArrowButtons.Reset();
    Sliders.Reset();
    SliderValuesAtCapture.Reset();
    KeepDialog = FDialogInfo();
    PromptDialog = FDialogInfo();

    auto Find = [this](FName Name) -> UWidget*
    {
        return Name.IsNone() ? nullptr : GetWidgetFromName(Name);
    };
    auto FindAll = [&Find](const TArray<FName>& Names)
    {
        TArray<UWidget*> Out;
        for (const FName& N : Names)
        {
            if (UWidget* W = Find(N))
            {
                Out.Add(W);
            }
        }
        return Out;
    };

    // Tabs and their pages' rows (the settings page).
    if (const UPanelWidget* Bar = Cast<UPanelWidget>(Find(TabBarName)))
    {
        TArray<UWidget*> TabButtons;
        for (int32 I = 0; I < Bar->GetChildrenCount(); ++I)
        {
            UWidget* Child = Bar->GetChildAt(I);
            if (Child && Child->IsA<UButton>())
            {
                TabButtons.Add(Child);
            }
        }
        UWidgetSwitcher* Switcher = Cast<UWidgetSwitcher>(Find(TabSwitcherName));
        RegisterTabs(TabButtons, Switcher);
        if (Switcher)
        {
            const int32 Pages = FMath::Min(Switcher->GetNumWidgets(), Tabs.Num());
            for (int32 P = 0; P < Pages; ++P)
            {
                TArray<UWidget*> Controls;
                TFunction<void(UWidget*)> Collect = [&](UWidget* W)
                {
                    if (!W)
                    {
                        return;
                    }
                    if (W->IsA<UComboBoxString>() || W->IsA<USlider>() || W->IsA<UCheckBox>())
                    {
                        Controls.Add(W);
                        return;
                    }
                    if (UButton* B = Cast<UButton>(W))
                    {
                        const FString Name = B->GetName();
                        const bool bArrow = ArrowButtonSuffixes.ContainsByPredicate([&Name](const FString& Suffix)
                        {
                            return !Suffix.IsEmpty() && Name.EndsWith(Suffix, ESearchCase::CaseSensitive);
                        });
                        if (bArrow)
                        {
                            B->OnClicked.AddUniqueDynamic(this, &USaskartaMenuWidget::HandleDirtyClick);
                            ArrowButtons.AddUnique(B);
                        }
                        else
                        {
                            Controls.Add(B);
                        }
                        return;
                    }
                    if (const UPanelWidget* Panel = Cast<UPanelWidget>(W))
                    {
                        for (int32 I = 0; I < Panel->GetChildrenCount(); ++I)
                        {
                            Collect(Panel->GetChildAt(I));
                        }
                    }
                };
                Collect(Switcher->GetWidgetAtIndex(P));
                RegisterRows(P, Controls, TArray<ESaskartaMenuRowType>());
            }
        }
    }

    RegisterFooter(FindAll(FooterButtonNames));

    if (UWidget* Root = Find(KeepDialogName))
    {
        RegisterDialog(ESaskartaMenuDialog::KeepOrRevert, Root, FindAll(KeepDialogButtonNames), KeepDialogDefaultIndex, KeepDialogDefaultIndex);
    }
    if (UWidget* Root = Find(PromptDialogName))
    {
        RegisterDialog(ESaskartaMenuDialog::ApplyChanges, Root, FindAll(PromptButtonNames), PromptDefaultIndex, PromptCancelIndex);
    }

    // A flat menu (title, pause).
    if (Tabs.Num() == 0)
    {
        TArray<UWidget*> Items = FindAll(MenuItemNames);
        if (Items.Num() == 0 && MenuItemNames.Num() == 0 && WidgetTree)
        {
            SaskartaMenuWidgetImpl::CollectButtons(GetRootWidget(), Items);
        }
        RegisterMenuItems(Items);
    }

    UE_LOG(LogSaskartaMenu, Verbose, TEXT("%s: %d menu items, %d tabs, %d footer buttons, keep dialog %s, prompt %s"),
        *GetName(), MenuItems.Num(), Tabs.Num(), FooterButtons.Num(),
        KeepDialog.Root.IsValid() ? TEXT("yes") : TEXT("no"), PromptDialog.Root.IsValid() ? TEXT("yes") : TEXT("no"));
}

ESaskartaMenuRowType USaskartaMenuWidget::TypeOf(const UWidget* Control)
{
    if (Control && Control->IsA<UComboBoxString>())
    {
        return ESaskartaMenuRowType::Selector;
    }
    if (Control && Control->IsA<USlider>())
    {
        return ESaskartaMenuRowType::Slider;
    }
    if (Control && Control->IsA<UCheckBox>())
    {
        return ESaskartaMenuRowType::Toggle;
    }
    return ESaskartaMenuRowType::Button;
}

void USaskartaMenuWidget::BindDirtySources(UWidget* Control)
{
    if (UComboBoxString* Combo = Cast<UComboBoxString>(Control))
    {
        Combo->OnSelectionChanged.AddUniqueDynamic(this, &USaskartaMenuWidget::HandleComboChanged);
        Combos.AddUnique(Combo);
    }
    else if (UCheckBox* Check = Cast<UCheckBox>(Control))
    {
        Check->OnCheckStateChanged.AddUniqueDynamic(this, &USaskartaMenuWidget::HandleCheckChanged);
    }
    else if (USlider* Slider = Cast<USlider>(Control))
    {
        Slider->OnMouseCaptureBegin.AddUniqueDynamic(this, &USaskartaMenuWidget::HandleSliderCaptureBegin);
        Slider->OnControllerCaptureBegin.AddUniqueDynamic(this, &USaskartaMenuWidget::HandleSliderCaptureBegin);
        Slider->OnMouseCaptureEnd.AddUniqueDynamic(this, &USaskartaMenuWidget::HandleSliderCaptureEnd);
        Slider->OnControllerCaptureEnd.AddUniqueDynamic(this, &USaskartaMenuWidget::HandleSliderCaptureEnd);
        Sliders.AddUnique(Slider);
    }
}

const USaskartaMenuWidget::FDialogInfo* USaskartaMenuWidget::DialogInfo(ESaskartaMenuDialog Dialog) const
{
    switch (Dialog)
    {
    case ESaskartaMenuDialog::KeepOrRevert: return &KeepDialog;
    case ESaskartaMenuDialog::ApplyChanges: return &PromptDialog;
    default: return nullptr;
    }
}

// ─── Lifecycle and input ─────────────────────────────────────────────────────

void USaskartaMenuWidget::NativeConstruct()
{
    Nav = FSaskartaMenuNavState();
    bDirty = false;
    bApplyPending = false;
    bKept = false;
    bLeaveAfterKeepDialog = false;
    RepeatLevel.Reset(); // a key still held from the menu that opened this one does not repeat here
    if (bAutoRegister)
    {
        AutoRegister();
    }
    Nav.Level = Tabs.Num() > 0 ? ESaskartaMenuLevel::Tabs : ESaskartaMenuLevel::Menu;
    UE_LOG(LogSaskartaMenu, Verbose, TEXT("%s: construct (auto register %d, level %d, poll %.2f s)"), *GetName(), bAutoRegister ? 1 : 0, int32(Nav.Level), PollInterval);

    // The BP's Construct (the settings page's Init focuses the first tab; NativeOnFocusChanging follows it).
    Super::NativeConstruct();

    // The poll only watches the keep-or-revert overlay and the toast; it never moves the focus.
    if (UWorld* World = GetWorld())
    {
        World->GetTimerManager().SetTimer(PollTimer, this, &USaskartaMenuWidget::PollMenuTimer, FMath::Max(0.05f, PollInterval), true);
    }
}

void USaskartaMenuWidget::NativeDestruct()
{
    UE_LOG(LogSaskartaMenu, Verbose, TEXT("%s: destruct"), *GetName());
    if (UWorld* World = GetWorld())
    {
        World->GetTimerManager().ClearTimer(PollTimer);
        World->GetTimerManager().ClearTimer(ToastTimer);
    }
    HideToast();
    Super::NativeDestruct();
}

bool USaskartaMenuWidget::MapMenuKey(const FKey& Key, ESaskartaMenuAction& OutAction)
{
    // Only these keys are the menu's. Everything else (letters, Tab, the mouse buttons and wheel,
    // the right stick, the triggers) goes to the focused widget or the game untouched.
    if (Key == EKeys::Up || Key == EKeys::Gamepad_DPad_Up || Key == EKeys::Gamepad_LeftStick_Up) { OutAction = ESaskartaMenuAction::Up; return true; }
    if (Key == EKeys::Down || Key == EKeys::Gamepad_DPad_Down || Key == EKeys::Gamepad_LeftStick_Down) { OutAction = ESaskartaMenuAction::Down; return true; }
    if (Key == EKeys::Left || Key == EKeys::Gamepad_DPad_Left || Key == EKeys::Gamepad_LeftStick_Left) { OutAction = ESaskartaMenuAction::Left; return true; }
    if (Key == EKeys::Right || Key == EKeys::Gamepad_DPad_Right || Key == EKeys::Gamepad_LeftStick_Right) { OutAction = ESaskartaMenuAction::Right; return true; }
    if (Key == EKeys::Enter || Key == EKeys::Gamepad_FaceButton_Bottom) { OutAction = ESaskartaMenuAction::Accept; return true; }
    if (Key == EKeys::Escape || Key == EKeys::Gamepad_FaceButton_Right) { OutAction = ESaskartaMenuAction::Back; return true; }
    return false;
}

bool USaskartaMenuWidget::HasMenuKeyboardFocus() const
{
    if (HasAnyUserFocus() || HasFocusedDescendants())
    {
        return true;
    }
    // A focused modal button may sit in a separate layer (the combo's pop-up is excluded by IsAnyComboOpen).
    if (FSlateApplication::IsInitialized())
    {
        const TSharedPtr<SWidget> Focused = FSlateApplication::Get().GetKeyboardFocusedWidget();
        const TSharedPtr<SWidget> Mine = GetCachedWidget();
        if (Focused.IsValid() && Mine.IsValid())
        {
            for (TSharedPtr<SWidget> W = Focused; W.IsValid(); W = W->GetParentWidget())
            {
                if (W == Mine)
                {
                    return true;
                }
            }
        }
    }
    return false;
}

bool USaskartaMenuWidget::MayHandleKey(const FKeyEvent& InKeyEvent, ESaskartaMenuAction& OutAction, const TCHAR* Phase) const
{
    const FKey Key = InKeyEvent.GetKey();
    if (Key.IsMouseButton())
    {
        return false; // never the mouse
    }
    if (!MapMenuKey(Key, OutAction))
    {
        UE_LOG(LogSaskartaMenu, VeryVerbose, TEXT("%s: %s key %s: not a menu key, passed on"), *GetName(), Phase, *Key.ToString());
        return false;
    }
    if (!IsMenuShown())
    {
        UE_LOG(LogSaskartaMenu, Verbose, TEXT("%s: %s key %s: menu not shown, passed on"), *GetName(), Phase, *Key.ToString());
        return false;
    }
    if (IsAnyComboOpen())
    {
        UE_LOG(LogSaskartaMenu, Verbose, TEXT("%s: %s key %s: a combo is open, left to it"), *GetName(), Phase, *Key.ToString());
        return false;
    }
    if (!HasMenuKeyboardFocus())
    {
        UE_LOG(LogSaskartaMenu, Verbose, TEXT("%s: %s key %s: the menu does not have the keyboard focus, passed on"), *GetName(), Phase, *Key.ToString());
        return false;
    }
    return true;
}

FReply USaskartaMenuWidget::NativeOnPreviewKeyDown(const FGeometry& InGeometry, const FKeyEvent& InKeyEvent)
{
    // Tunnel phase: the menu sees the arrows and Enter before the focused combo /
    // slider / check box, so they behave the same on every row. Esc is left to the
    // bubble phase (NativeOnKeyDown), after the focused widget.
    ESaskartaMenuAction Action = ESaskartaMenuAction::Up;
    if (MayHandleKey(InKeyEvent, Action, TEXT("preview")) && Action != ESaskartaMenuAction::Back)
    {
        const FKey Key = InKeyEvent.GetKey();
        if (Action == ESaskartaMenuAction::Accept && InKeyEvent.IsRepeat())
        {
            UE_LOG(LogSaskartaMenu, Verbose, TEXT("%s: key %s repeat swallowed"), *GetName(), *Key.ToString());
            return FReply::Handled();
        }
        // A held Left / Right on a selector or a toggle: one step per press. The OS / XInput repeat
        // (~30 a second) stepped the preset through every level, re-applying the scalability groups
        // each time, and flipped a toggle back and forth. A slider keeps the repeat (a held key
        // glides it); its handler previews cheaply, and the foliage ones only once it rests.
        if ((Action == ESaskartaMenuAction::Left || Action == ESaskartaMenuAction::Right) && InKeyEvent.IsRepeat()
            && Nav.Level == ESaskartaMenuLevel::Rows && IsCurrentRowStepped())
        {
            UE_LOG(LogSaskartaMenu, Verbose, TEXT("%s: key %s repeat on a selector / toggle swallowed"), *GetName(), *Key.ToString());
            return FReply::Handled();
        }
        // A held key repeats only while it stays on the level its press acted on. A press that
        // changed the level takes no repeats: Right held on the Audio tab enters the rows once and
        // does not then glide the first row's slider (Master volume); Down held past the last row
        // stops on the footer's Apply.
        if (InKeyEvent.IsRepeat() && !(RepeatLevel.IsSet() && RepeatLevel.GetValue() == Nav.Level))
        {
            UE_LOG(LogSaskartaMenu, Verbose, TEXT("%s: key %s repeat after a level change swallowed"), *GetName(), *Key.ToString());
            return FReply::Handled();
        }
        const ESaskartaMenuLevel LevelBefore = Nav.Level;
        if (!InKeyEvent.IsRepeat())
        {
            RepeatLevel.Reset();
        }
        if (HandleAction(Action))
        {
            if (!InKeyEvent.IsRepeat() && Nav.Level == LevelBefore)
            {
                RepeatLevel = Nav.Level;
            }
            UE_LOG(LogSaskartaMenu, Log, TEXT("%s: key %s -> action %d, handled (level %d tab %d row %d)"), *GetName(), *Key.ToString(), int32(Action), int32(Nav.Level), Nav.Tab, Nav.Row);
            return FReply::Handled();
        }
        UE_LOG(LogSaskartaMenu, Verbose, TEXT("%s: key %s -> action %d, unhandled, passed on"), *GetName(), *Key.ToString(), int32(Action));
    }
    return Super::NativeOnPreviewKeyDown(InGeometry, InKeyEvent);
}

FReply USaskartaMenuWidget::NativeOnKeyDown(const FGeometry& InGeometry, const FKeyEvent& InKeyEvent)
{
    // Bubble phase: Esc / gamepad B, once the focused widget has passed on it.
    ESaskartaMenuAction Action = ESaskartaMenuAction::Up;
    if (MayHandleKey(InKeyEvent, Action, TEXT("bubble")) && Action == ESaskartaMenuAction::Back)
    {
        const FKey Key = InKeyEvent.GetKey();
        if (InKeyEvent.IsRepeat())
        {
            UE_LOG(LogSaskartaMenu, Verbose, TEXT("%s: key %s repeat swallowed"), *GetName(), *Key.ToString());
            return FReply::Handled();
        }
        if (HandleAction(ESaskartaMenuAction::Back))
        {
            UE_LOG(LogSaskartaMenu, Log, TEXT("%s: key %s -> Back, handled (level %d)"), *GetName(), *Key.ToString(), int32(Nav.Level));
            return FReply::Handled();
        }
        UE_LOG(LogSaskartaMenu, Log, TEXT("%s: key %s -> Back, passed to the game"), *GetName(), *Key.ToString());
        // Not used here (the title, the pause menu): let it reach the game (PC_Saskarta's PollPauseKey).
        return FReply::Unhandled();
    }
    return Super::NativeOnKeyDown(InGeometry, InKeyEvent);
}

FNavigationReply USaskartaMenuWidget::NativeOnNavigation(const FGeometry& MyGeometry, const FNavigationEvent& InNavigationEvent, const FNavigationReply& InDefaultReply)
{
    // Navigation that did not come from a key we already took, under the same focus condition.
    if (IsMenuShown() && !IsAnyComboOpen() && HasMenuKeyboardFocus())
    {
        const EUINavigation Type = InNavigationEvent.GetNavigationType();
        const bool bInDialog = Nav.Level == ESaskartaMenuLevel::Dialog;
        TOptional<ESaskartaMenuAction> Action;
        switch (Type)
        {
        case EUINavigation::Up:
            Action = ESaskartaMenuAction::Up;
            break;
        case EUINavigation::Down:
            Action = ESaskartaMenuAction::Down;
            break;
        case EUINavigation::Left:
            Action = ESaskartaMenuAction::Left;
            break;
        case EUINavigation::Right:
            Action = ESaskartaMenuAction::Right;
            break;
        case EUINavigation::Next:
        case EUINavigation::Previous:
            // Tab / Shift+Tab are Slate's elsewhere, but not in a modal: Slate's default walked the
            // focus to the footer behind the overlay, where Space then clicked Back (the old
            // "Apply -> Keep jumps to the title"). In a dialog they move between its buttons.
            if (bInDialog)
            {
                Action = Type == EUINavigation::Next ? ESaskartaMenuAction::Right : ESaskartaMenuAction::Left;
            }
            break;
        default:
            break;
        }
        const bool bDirectional = Type == EUINavigation::Up || Type == EUINavigation::Down || Type == EUINavigation::Left || Type == EUINavigation::Right;
        if (Action.IsSet() && bDirectional && InNavigationEvent.GetNavigationGenesis() == ENavigationGenesis::Controller)
        {
            // The left stick. XInput sends each push twice: as the digital Gamepad_LeftStick_* keys,
            // which NativeOnPreviewKeyDown already took (MapMenuKey), and as the analog axis, which
            // Slate turns into this navigation (SWidget::OnAnalogValueChanged). Acting on both moved
            // two rows or two values per flick, on two repeat clocks. Stop it without acting. (A
            // D-pad key only gets here when the menu passed on it, and then it has no use here either.)
            UE_LOG(LogSaskartaMenu, VeryVerbose, TEXT("%s: controller navigation %d stopped (the stick's key already went through)"), *GetName(), int32(Type));
            return FNavigationReply::Stop();
        }
        if (Action.IsSet() && HandleAction(Action.GetValue()))
        {
            UE_LOG(LogSaskartaMenu, Verbose, TEXT("%s: navigation %d -> action %d, handled"), *GetName(), int32(Type), int32(Action.GetValue()));
            return FNavigationReply::Stop();
        }
        if (bInDialog)
        {
            return FNavigationReply::Stop(); // a modal owns every navigation
        }
    }
    return Super::NativeOnNavigation(MyGeometry, InNavigationEvent, InDefaultReply);
}

void USaskartaMenuWidget::NativeOnFocusChanging(const FWeakWidgetPath& PreviousFocusPath, const FWidgetPath& NewWidgetPath, const FFocusEvent& InFocusEvent)
{
    Super::NativeOnFocusChanging(PreviousFocusPath, NewWidgetPath, InFocusEvent);
    if (bSettingFocus)
    {
        return;
    }

    // Follow focus that moved without us (a mouse click, the BP's SetKeyboardFocus).
    auto Holds = [&NewWidgetPath](const UWidget* W)
    {
        if (!W)
        {
            return false;
        }
        const TSharedPtr<SWidget> Slate = W->GetCachedWidget();
        return Slate.IsValid() && NewWidgetPath.ContainsWidget(Slate.Get());
    };
    auto IndexIn = [&Holds](const TArray<TWeakObjectPtr<UWidget>>& List)
    {
        for (int32 I = 0; I < List.Num(); ++I)
        {
            if (Holds(List[I].Get()))
            {
                return I;
            }
        }
        return int32(INDEX_NONE);
    };

    FSaskartaMenuNavState S = Nav;
    int32 Index = INDEX_NONE;
    if (Nav.Level == ESaskartaMenuLevel::Dialog)
    {
        if (const FDialogInfo* Info = DialogInfo(Nav.Dialog))
        {
            Index = IndexIn(Info->Buttons);
            if (Index != INDEX_NONE)
            {
                S.DialogButton = Index;
            }
        }
    }
    else if ((Index = IndexIn(FooterButtons)) != INDEX_NONE)
    {
        S.Level = ESaskartaMenuLevel::Footer;
        S.Footer = Index;
    }
    else if ((Index = IndexIn(Tabs)) != INDEX_NONE)
    {
        S.Level = ESaskartaMenuLevel::Tabs;
        if (Index != Nav.Tab)
        {
            S.Row = 0; // a new page starts at its first row, as with the keys (a click kept the old tab's row)
        }
        S.Tab = Index;
    }
    else if ((Index = IndexIn(MenuItems)) != INDEX_NONE)
    {
        S.Level = ESaskartaMenuLevel::Menu;
        S.MenuItem = Index;
    }
    else
    {
        for (int32 T = 0; T < TabRows.Num() && Index == INDEX_NONE; ++T)
        {
            Index = IndexIn(TabRows[T].Rows);
            if (Index != INDEX_NONE)
            {
                S.Level = ESaskartaMenuLevel::Rows;
                S.Tab = T;
                S.Row = Index;
            }
        }
        if (Index == INDEX_NONE)
        {
            // A clicked ◀ ▶ arrow takes the focus but is not a row: follow it to its row, so the keys
            // continue from the row that was clicked (they acted on the old row, or switched tabs).
            const int32 Arrow = IndexIn(ArrowButtons);
            int32 ArrowTab = INDEX_NONE;
            int32 ArrowRow = INDEX_NONE;
            if (Arrow != INDEX_NONE && RowOfArrow(ArrowButtons[Arrow].Get(), ArrowTab, ArrowRow))
            {
                S.Level = ESaskartaMenuLevel::Rows;
                S.Tab = ArrowTab;
                S.Row = ArrowRow;
                Index = ArrowRow;
            }
        }
    }
    if (Index != INDEX_NONE && !(S == Nav))
    {
        UE_LOG(LogSaskartaMenu, Verbose, TEXT("%s: focus followed to level %d tab %d index %d (%s)"), *GetName(), int32(S.Level), S.Tab, Index,
            InFocusEvent.GetCause() == EFocusCause::Mouse ? TEXT("mouse") : TEXT("other"));
        Nav = S;
        OnMenuFocusChanged(Nav.Level, Nav.Tab, Index, WidgetFor(Nav));
    }
}

// ─── The reducer glue ────────────────────────────────────────────────────────

FSaskartaMenuNavContext USaskartaMenuWidget::BuildContext()
{
    using namespace SaskartaMenuWidgetImpl;
    auto Usable = [this](const UWidget* W) { return IsUsable(W); };
    FSaskartaMenuNavContext C;
    C.MenuEnabled = UsableFlags(this, MenuItems, Usable);
    C.TabEnabled = UsableFlags(this, Tabs, Usable);
    if (TabRows.IsValidIndex(Nav.Tab))
    {
        C.RowEnabled = UsableFlags(this, TabRows[Nav.Tab].Rows, Usable);
        C.RowTypes = TabRows[Nav.Tab].Types;
    }
    C.FooterEnabled = UsableFlags(this, FooterButtons, Usable);
    if (Nav.Level == ESaskartaMenuLevel::Dialog)
    {
        if (const FDialogInfo* Info = DialogInfo(Nav.Dialog))
        {
            C.DialogEnabled = UsableFlags(this, Info->Buttons, Usable);
            C.DialogCancelIndex = Info->CancelIndex;
        }
    }
    C.bDirty = HasUnappliedChanges();
    return C;
}

bool USaskartaMenuWidget::HandleAction(ESaskartaMenuAction Action)
{
    // The keep-or-revert overlay may have opened or closed since the last poll. If that closed the
    // menu (Apply chosen in "Apply changes?", then Keep), the key is used up: the stale navigation
    // target (the footer's Apply) must not be pressed again on a widget that has left the screen.
    if (PollMenu() || !IsMenuShown())
    {
        return true;
    }

    const FSaskartaMenuNavContext Context = BuildContext();
    FSaskartaMenuNavResult R = SaskartaMenuNav::Reduce(Nav, Context, Action);
    if (!R.bHandled)
    {
        return false;
    }

    if (R.Command == ESaskartaMenuCommand::ShowApplyPrompt)
    {
        if (!ShowApplyPrompt())
        {
            // No prompt in this widget: the old behaviour (Back discards and leaves).
            return OnBack();
        }
        R.State.DialogButton = PromptDialog.DefaultIndex;
    }

    const bool bFocus = R.bFocusChanged && !(R.Command == ESaskartaMenuCommand::DialogConfirm || R.Command == ESaskartaMenuCommand::DialogCancel);
    ApplyNavState(R.State, bFocus);

    switch (R.Command)
    {
    case ESaskartaMenuCommand::Cycle:
        if (UWidget* Row = WidgetFor(Nav))
        {
            const ESaskartaMenuRowType Type = Context.RowTypes.IsValidIndex(Nav.Row) ? Context.RowTypes[Nav.Row] : TypeOf(Row);
            OnCycle(Row, Type, R.Direction);
        }
        return true;

    case ESaskartaMenuCommand::Activate:
        if (UWidget* Target = WidgetFor(Nav))
        {
            const ESaskartaMenuRowType Type = (Nav.Level == ESaskartaMenuLevel::Rows && Context.RowTypes.IsValidIndex(Nav.Row))
                ? Context.RowTypes[Nav.Row] : ESaskartaMenuRowType::Button;
            OnActivate(Target, Type);
            // Now, not at the next poll: the click may have opened the keep-or-revert check (Apply)
            // or the "Apply changes?" prompt (Back with unapplied changes), and the focus goes there.
            PollMenu();
        }
        return true;

    case ESaskartaMenuCommand::Back:
        return OnBack();

    case ESaskartaMenuCommand::DialogConfirm:
    case ESaskartaMenuCommand::DialogCancel:
        if (Nav.Dialog == ESaskartaMenuDialog::ApplyChanges)
        {
            FinishApplyPrompt(Nav.DialogButton);
        }
        else if (Nav.Dialog == ESaskartaMenuDialog::KeepOrRevert)
        {
            // Press Keep or Revert: the BP's bound KeepResolution / RevertResolution
            // runs (and hides the overlay); our own bound handler records which.
            if (UButton* B = Cast<UButton>(SaskartaMenuWidgetImpl::At(KeepDialog.Buttons, Nav.DialogButton)))
            {
                B->OnClicked.Broadcast();
            }
            PollMenu(); // leave the dialog now if the overlay closed
        }
        return true;

    default:
        return true;
    }
}

UWidget* USaskartaMenuWidget::WidgetFor(const FSaskartaMenuNavState& State) const
{
    using SaskartaMenuWidgetImpl::At;
    switch (State.Level)
    {
    case ESaskartaMenuLevel::Menu: return At(MenuItems, State.MenuItem);
    case ESaskartaMenuLevel::Tabs: return At(Tabs, State.Tab);
    case ESaskartaMenuLevel::Rows: return TabRows.IsValidIndex(State.Tab) ? At(TabRows[State.Tab].Rows, State.Row) : nullptr;
    case ESaskartaMenuLevel::Footer: return At(FooterButtons, State.Footer);
    case ESaskartaMenuLevel::Dialog:
        if (const FDialogInfo* Info = DialogInfo(State.Dialog))
        {
            return At(Info->Buttons, State.DialogButton);
        }
        return nullptr;
    default: return nullptr;
    }
}

UWidget* USaskartaMenuWidget::GetCurrentMenuWidget() const
{
    return WidgetFor(Nav);
}

void USaskartaMenuWidget::ApplyNavState(const FSaskartaMenuNavState& NewState, bool bFocus)
{
    const bool bTabChanged = NewState.Tab != Nav.Tab;
    Nav = NewState;
    if (bTabChanged)
    {
        OpenTabPage(Nav.Tab);
    }
    if (bFocus)
    {
        UWidget* Target = WidgetFor(Nav);
        FocusWidget(Target);
        const int32 Index = Nav.Level == ESaskartaMenuLevel::Menu ? Nav.MenuItem
            : Nav.Level == ESaskartaMenuLevel::Tabs ? Nav.Tab
            : Nav.Level == ESaskartaMenuLevel::Rows ? Nav.Row
            : Nav.Level == ESaskartaMenuLevel::Footer ? Nav.Footer
            : Nav.DialogButton;
        OnMenuFocusChanged(Nav.Level, Nav.Tab, Index, Target);
    }
}

void USaskartaMenuWidget::OpenTabPage(int32 TabIndex)
{
    // The page follows the tab at once; the BP's 50 ms focus poll then calls its
    // OpenTab for the tab bar and labels (the tab button now has the focus).
    if (UWidgetSwitcher* Pages = TabPages.Get())
    {
        if (TabIndex >= 0 && TabIndex < Pages->GetNumWidgets())
        {
            Pages->SetActiveWidgetIndex(TabIndex);
        }
    }
}

void USaskartaMenuWidget::FocusWidget(UWidget* Widget)
{
    if (!Widget)
    {
        return;
    }
    TGuardValue<bool> Guard(bSettingFocus, true);
    if (APlayerController* PC = GetOwningPlayer())
    {
        Widget->SetUserFocus(PC);
    }
    else
    {
        Widget->SetKeyboardFocus();
    }
    ScrollIntoView(Widget);
}

void USaskartaMenuWidget::ScrollIntoView(UWidget* Widget)
{
    // A tab page is a ScrollBox whose ScrollWhenFocusChanges is NoScroll (the UMG default), and focus
    // set from code does not scroll it either, so a focused row below the fold (Graphics has 14 rows)
    // stayed off-screen. Scroll the nearest ScrollBox above the widget; instant, with a little air.
    for (UWidget* It = Widget ? Widget->GetParent() : nullptr; It; It = It->GetParent())
    {
        if (UScrollBox* Scroll = Cast<UScrollBox>(It))
        {
            Scroll->ScrollWidgetIntoView(Widget, /*AnimateScroll*/ false, EDescendantScrollDestination::IntoView, /*Padding*/ 24.f);
            return;
        }
    }
}

bool USaskartaMenuWidget::RowOfArrow(const UWidget* Arrow, int32& OutTab, int32& OutRow) const
{
    // The arrows and the combo of one row are the children of the same box (<Id>Selector).
    const UPanelWidget* Box = Arrow ? Arrow->GetParent() : nullptr;
    if (!Box)
    {
        return false;
    }
    for (int32 T = 0; T < TabRows.Num(); ++T)
    {
        for (int32 R = 0; R < TabRows[T].Rows.Num(); ++R)
        {
            const UWidget* Control = TabRows[T].Rows[R].Get();
            if (Control && Control->GetParent() == Box)
            {
                OutTab = T;
                OutRow = R;
                return true;
            }
        }
    }
    return false;
}

bool USaskartaMenuWidget::IsCurrentRowStepped() const
{
    if (!TabRows.IsValidIndex(Nav.Tab))
    {
        return false;
    }
    const FTabRows& Tab = TabRows[Nav.Tab];
    const ESaskartaMenuRowType Type = Tab.Types.IsValidIndex(Nav.Row) ? Tab.Types[Nav.Row]
        : TypeOf(Tab.Rows.IsValidIndex(Nav.Row) ? Tab.Rows[Nav.Row].Get() : nullptr);
    return Type == ESaskartaMenuRowType::Selector || Type == ESaskartaMenuRowType::Toggle;
}

void USaskartaMenuWidget::FocusCurrent()
{
    FocusWidget(WidgetFor(Nav));
}

void USaskartaMenuWidget::SelectTab(int32 TabIndex)
{
    if (!Tabs.IsValidIndex(TabIndex))
    {
        return;
    }
    FSaskartaMenuNavState S = Nav;
    S.Level = ESaskartaMenuLevel::Tabs;
    S.Tab = TabIndex;
    S.Row = 0;
    S.Dialog = ESaskartaMenuDialog::None;
    ApplyNavState(S, true);
}

bool USaskartaMenuWidget::IsUsable(const UWidget* Widget) const
{
    if (!Widget)
    {
        return false;
    }
    for (const UWidget* It = Widget; It; It = It->GetParent())
    {
        const ESlateVisibility V = It->GetVisibility();
        if (V == ESlateVisibility::Collapsed || V == ESlateVisibility::Hidden || !It->GetIsEnabled())
        {
            return false;
        }
    }
    return true;
}

bool USaskartaMenuWidget::IsMenuShown() const
{
    const ESlateVisibility V = GetVisibility();
    return IsInViewport() && V != ESlateVisibility::Collapsed && V != ESlateVisibility::Hidden && GetRenderOpacity() > 0.01f;
}

bool USaskartaMenuWidget::IsAnyComboOpen() const
{
    for (const TWeakObjectPtr<UComboBoxString>& Combo : Combos)
    {
        if (Combo.IsValid() && Combo->IsOpen())
        {
            return true;
        }
    }
    return false;
}

bool USaskartaMenuWidget::CallNoParamFunction(FName FunctionName)
{
    if (FunctionName.IsNone())
    {
        return false;
    }
    UFunction* Function = FindFunction(FunctionName);
    if (!Function || Function->NumParms != 0)
    {
        return false;
    }
    ProcessEvent(Function, nullptr);
    return true;
}

// ─── Dialogs ─────────────────────────────────────────────────────────────────

void USaskartaMenuWidget::EnterDialog(ESaskartaMenuDialog Dialog)
{
    const FDialogInfo* Info = DialogInfo(Dialog);
    if (!Info || Info->Buttons.Num() == 0)
    {
        return;
    }
    FSaskartaMenuNavState S = Nav;
    if (Nav.Level != ESaskartaMenuLevel::Dialog)
    {
        S.LevelBeforeDialog = Nav.Level;
    }
    S.Level = ESaskartaMenuLevel::Dialog;
    S.Dialog = Dialog;
    S.DialogButton = Info->DefaultIndex;
    ApplyNavState(S, true);
}

void USaskartaMenuWidget::LeaveDialog(bool bFocusApply)
{
    FSaskartaMenuNavState S = Nav;
    S.Dialog = ESaskartaMenuDialog::None;
    S.Level = S.LevelBeforeDialog == ESaskartaMenuLevel::Dialog ? ESaskartaMenuLevel::Tabs : S.LevelBeforeDialog;
    if (bFocusApply)
    {
        const int32 Apply = FooterButtons.IndexOfByPredicate([this](const TWeakObjectPtr<UWidget>& W)
        {
            return W.IsValid() && W->GetFName() == ApplyButtonName;
        });
        if (Apply != INDEX_NONE)
        {
            S.Level = ESaskartaMenuLevel::Footer;
            S.Footer = Apply;
        }
    }
    if (Tabs.Num() == 0 && S.Level != ESaskartaMenuLevel::Footer)
    {
        S.Level = ESaskartaMenuLevel::Menu;
    }
    ApplyNavState(S, true);
}

void USaskartaMenuWidget::FinishApplyPrompt(int32 ButtonIndex)
{
    if (UWidget* Root = PromptDialog.Root.Get())
    {
        Root->SetVisibility(ESlateVisibility::Collapsed);
    }
    FSaskartaMenuNavState S = Nav;
    S.Dialog = ESaskartaMenuDialog::None;
    S.Level = ESaskartaMenuLevel::Tabs;

    if (ButtonIndex == 0)
    {
        // Apply, then leave, unless a resolution change opens the keep-or-revert check:
        // then leave once that closes.
        ApplyNavState(S, false);
        const int32 Apply = FooterButtons.IndexOfByPredicate([this](const TWeakObjectPtr<UWidget>& W)
        {
            return W.IsValid() && W->GetFName() == ApplyButtonName;
        });
        if (UButton* B = Cast<UButton>(SaskartaMenuWidgetImpl::At(FooterButtons, Apply)))
        {
            Nav.LevelBeforeDialog = ESaskartaMenuLevel::Tabs;
            B->OnClicked.Broadcast(); // BP ApplyPending (synchronous) + HandleApplyClicked
        }
        bApplyPending = false;
        if (KeepDialog.Root.IsValid() && IsUsable(KeepDialog.Root.Get()))
        {
            bLeaveAfterKeepDialog = true;
            EnterDialog(ESaskartaMenuDialog::KeepOrRevert);
            return;
        }
        ClearDirty();
        OnBack();
    }
    else if (ButtonIndex == 1)
    {
        // Discard: the BP's Back reverts the unapplied changes and leaves.
        ApplyNavState(S, false);
        ClearDirty();
        OnBack();
    }
    else
    {
        // Cancel: stay in Settings, on the tab list.
        ApplyNavState(S, true);
    }
}

void USaskartaMenuWidget::PollMenuTimer()
{
    PollMenu();
}

bool USaskartaMenuWidget::PollMenu()
{
    // The keep-or-revert overlay: trap the focus while it shows, and return to the
    // footer's Apply (staying in Settings) when it closes.
    const bool bKeepShown = KeepDialog.Root.IsValid() && IsUsable(KeepDialog.Root.Get());
    const bool bInKeep = Nav.Level == ESaskartaMenuLevel::Dialog && Nav.Dialog == ESaskartaMenuDialog::KeepOrRevert;
    if (bKeepShown && !bInKeep)
    {
        bApplyPending = false;
        bKept = false;
        if (Nav.Level == ESaskartaMenuLevel::Dialog && Nav.Dialog == ESaskartaMenuDialog::ApplyChanges)
        {
            if (UWidget* Root = PromptDialog.Root.Get())
            {
                Root->SetVisibility(ESlateVisibility::Collapsed);
            }
            Nav.Level = Nav.LevelBeforeDialog;
            Nav.Dialog = ESaskartaMenuDialog::None;
        }
        EnterDialog(ESaskartaMenuDialog::KeepOrRevert);
    }
    else if (!bKeepShown && bInKeep)
    {
        const bool bWasKept = bKept;
        bKept = false;
        LeaveDialog(/*bFocusApply*/ true);
        ShowToast(bWasKept ? AppliedText : RevertedText);
        if (bLeaveAfterKeepDialog)
        {
            bLeaveAfterKeepDialog = false;
            ClearDirty();
            OnBack();
            return true; // the widget may be gone
        }
    }
    else if (Nav.Level == ESaskartaMenuLevel::Dialog && Nav.Dialog == ESaskartaMenuDialog::ApplyChanges
        && !(PromptDialog.Root.IsValid() && IsUsable(PromptDialog.Root.Get())))
    {
        // Something else closed the prompt.
        LeaveDialog(false);
    }
    else if (Nav.Level != ESaskartaMenuLevel::Dialog && PromptDialog.Buttons.Num() > 0
        && PromptDialog.Root.IsValid() && IsUsable(PromptDialog.Root.Get()) && IsMenuShown())
    {
        // The BP opened the prompt: its Back asks first when there are unapplied changes (the footer's
        // Back clicked or pressed, the pause menu's Esc). Trap the focus in it, Apply first.
        UE_LOG(LogSaskartaMenu, Verbose, TEXT("%s: the Apply changes? prompt was opened by the BP; the focus moves into it"), *GetName());
        EnterDialog(ESaskartaMenuDialog::ApplyChanges);
    }

    if (bApplyPending && !bKeepShown)
    {
        bApplyPending = false;
        ShowToast(AppliedText);
    }

    // No focus guard any more (user, 2026-09-28: Settings "glitchy, buttons don't work"): the poll
    // never moves the focus. The focus moves only on a menu key the menu took, on a dialog opening
    // or closing, or by the BP (FocusCurrent). A click elsewhere simply leaves the focus there, and
    // the menu keys then pass on until the focus is back inside the menu.
    // Only the current item vanishing (a collapsed row) moves the navigation state, without focusing.
    if (IsMenuShown() && Nav.Level != ESaskartaMenuLevel::Dialog && !IsUsable(WidgetFor(Nav)) && HasMenuKeyboardFocus())
    {
        const FSaskartaMenuNavContext C = BuildContext();
        FSaskartaMenuNavState S = Nav;
        switch (S.Level)
        {
        case ESaskartaMenuLevel::Menu: S.MenuItem = SaskartaMenuNav::NearestEnabled(S.MenuItem, C.MenuEnabled); break;
        case ESaskartaMenuLevel::Tabs: S.Tab = SaskartaMenuNav::NearestEnabled(S.Tab, C.TabEnabled); break;
        case ESaskartaMenuLevel::Rows: S.Row = SaskartaMenuNav::NearestEnabled(S.Row, C.RowEnabled); break;
        case ESaskartaMenuLevel::Footer: S.Footer = SaskartaMenuNav::NearestEnabled(S.Footer, C.FooterEnabled); break;
        default: break;
        }
        S.MenuItem = FMath::Max(0, S.MenuItem);
        S.Tab = FMath::Max(0, S.Tab);
        S.Row = FMath::Max(0, S.Row);
        S.Footer = FMath::Max(0, S.Footer);
        if (!(S == Nav))
        {
            UE_LOG(LogSaskartaMenu, Verbose, TEXT("%s: current item vanished; navigation moved to level %d tab %d row %d (focus untouched)"),
                *GetName(), int32(S.Level), S.Tab, S.Row);
            ApplyNavState(S, false);
        }
    }
    return false;
}

// ─── Default behaviour (BlueprintNativeEvent implementations) ────────────────

void USaskartaMenuWidget::OnCycle_Implementation(UWidget* Row, ESaskartaMenuRowType Type, int32 Direction)
{
    const int32 Dir = Direction >= 0 ? 1 : -1;
    if (UComboBoxString* Combo = Cast<UComboBoxString>(Row))
    {
        const int32 Count = Combo->GetOptionCount();
        if (Count > 0)
        {
            const int32 Current = FMath::Max(0, Combo->GetSelectedIndex());
            const int32 Next = ((Current + Dir) % Count + Count) % Count;
            Combo->SetSelectedIndex(Next); // fires OnSelectionChanged -> the row's handler
        }
    }
    else if (USlider* Slider = Cast<USlider>(Row))
    {
        const float Min = Slider->GetMinValue();
        const float Max = Slider->GetMaxValue();
        float Step = Slider->GetStepSize();
        if (Step <= UE_KINDA_SMALL_NUMBER)
        {
            Step = (Max - Min) / 20.f;
        }
        float Value = FMath::Clamp(Slider->GetValue() + Dir * Step, Min, Max);
        if (Step > UE_KINDA_SMALL_NUMBER)
        {
            Value = FMath::Clamp(Min + FMath::RoundToFloat((Value - Min) / Step) * Step, Min, Max);
        }
        if (!FMath::IsNearlyEqual(Value, Slider->GetValue()))
        {
            Slider->SetValue(Value);
            Slider->OnValueChanged.Broadcast(Value); // SetValue alone does not notify
        }
    }
    else if (UCheckBox* Check = Cast<UCheckBox>(Row))
    {
        const bool bOn = !Check->IsChecked();
        Check->SetIsChecked(bOn);
        Check->OnCheckStateChanged.Broadcast(bOn); // SetIsChecked alone does not notify
    }
    else
    {
        return;
    }
    MarkDirty();
}

void USaskartaMenuWidget::OnActivate_Implementation(UWidget* Target, ESaskartaMenuRowType Type)
{
    if (UButton* Button = Cast<UButton>(Target))
    {
        Button->OnClicked.Broadcast();
    }
    else if (Target && (Target->IsA<UCheckBox>() || Target->IsA<UComboBoxString>()))
    {
        OnCycle(Target, TypeOf(Target), 1);
    }
}

bool USaskartaMenuWidget::OnBack_Implementation()
{
    return CallNoParamFunction(BackFunctionName);
}

bool USaskartaMenuWidget::HasUnappliedChanges_Implementation()
{
    return bDirty;
}

bool USaskartaMenuWidget::ShowApplyPrompt_Implementation()
{
    UWidget* Root = PromptDialog.Root.Get();
    if (!Root || PromptDialog.Buttons.Num() == 0)
    {
        return false;
    }
    Root->SetVisibility(ESlateVisibility::Visible);
    return true;
}

void USaskartaMenuWidget::OnShowToast_Implementation(const FText& Message)
{
    HideToast();
    bool bFallback = false;
    UTextBlock* Text = ToastWidgetName.IsNone() ? nullptr : Cast<UTextBlock>(GetWidgetFromName(ToastWidgetName));
    if (!Text && !FallbackToastName.IsNone())
    {
        Text = Cast<UTextBlock>(GetWidgetFromName(FallbackToastName));
        bFallback = Text != nullptr;
    }
    if (!Text)
    {
        return;
    }
    ToastPreviousText = bFallback ? Text->GetText() : FText::GetEmpty();
    bToastIsFallback = bFallback;
    Text->SetText(Message);
    if (!bFallback)
    {
        Text->SetVisibility(ESlateVisibility::HitTestInvisible);
    }
    ToastTarget = Text;
    if (UWorld* World = GetWorld())
    {
        World->GetTimerManager().SetTimer(ToastTimer, this, &USaskartaMenuWidget::HideToast, FMath::Max(0.1f, ToastSeconds), false);
    }
}

void USaskartaMenuWidget::HideToast()
{
    if (UTextBlock* Text = Cast<UTextBlock>(ToastTarget.Get()))
    {
        if (bToastIsFallback)
        {
            Text->SetText(ToastPreviousText);
        }
        else
        {
            Text->SetVisibility(ESlateVisibility::Collapsed);
        }
    }
    ToastTarget = nullptr;
}

void USaskartaMenuWidget::ShowToast(const FText& Message)
{
    OnShowToast(Message);
}

void USaskartaMenuWidget::MarkDirty()
{
    bDirty = true;
}

void USaskartaMenuWidget::ClearDirty()
{
    bDirty = false;
}

// ─── Delegate targets ────────────────────────────────────────────────────────

void USaskartaMenuWidget::HandleDirtyClick()
{
    MarkDirty();
}

void USaskartaMenuWidget::HandleComboChanged(FString SelectedItem, ESelectInfo::Type SelectionType)
{
    // Direct = set from code (the BP's refresh, the ◀ ▶ arrows, OnCycle); those mark dirty themselves or are not user edits.
    if (SelectionType != ESelectInfo::Direct)
    {
        MarkDirty();
    }
}

void USaskartaMenuWidget::HandleCheckChanged(bool bIsChecked)
{
    MarkDirty();
}

void USaskartaMenuWidget::HandleSliderCaptureBegin()
{
    // The delegate does not say which slider, so remember them all (a page has at most a dozen).
    SliderValuesAtCapture.Reset(Sliders.Num());
    for (const TWeakObjectPtr<USlider>& Slider : Sliders)
    {
        SliderValuesAtCapture.Add(Slider.IsValid() ? Slider->GetValue() : 0.f);
    }
}

void USaskartaMenuWidget::HandleSliderCaptureEnd()
{
    // Dirty only when a value moved: a click on a knob without a drag used to count as an unapplied
    // change, and the next Esc asked "Apply changes?" for nothing.
    if (SliderValuesAtCapture.Num() != Sliders.Num())
    {
        MarkDirty();
        return;
    }
    for (int32 I = 0; I < Sliders.Num(); ++I)
    {
        const USlider* Slider = Sliders[I].Get();
        if (Slider && !FMath::IsNearlyEqual(Slider->GetValue(), SliderValuesAtCapture[I], FMath::Max(Slider->GetStepSize() * 0.5f, UE_KINDA_SMALL_NUMBER)))
        {
            MarkDirty();
            break;
        }
    }
    SliderValuesAtCapture.Reset();
}

void USaskartaMenuWidget::HandleApplyClicked()
{
    ClearDirty();
    bApplyPending = true; // the next poll shows "Applied", unless the keep-or-revert check opened
}

void USaskartaMenuWidget::HandleRevertClicked()
{
    ClearDirty();
    ShowToast(RevertedText);
}

void USaskartaMenuWidget::HandleKeepClicked()
{
    bKept = true;
}

void USaskartaMenuWidget::HandleRevertNowClicked()
{
    bKept = false;
}

void USaskartaMenuWidget::HandlePromptApply()
{
    FinishApplyPrompt(0);
}

void USaskartaMenuWidget::HandlePromptDiscard()
{
    FinishApplyPrompt(1);
}

void USaskartaMenuWidget::HandlePromptCancel()
{
    FinishApplyPrompt(2);
}
