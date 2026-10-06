// USaskartaMenuWidget: keyboard / gamepad navigation for the title, settings and
// pause menus (task MENUINPUT). WBP_Saskarta_Title, WBP_Saskarta_Settings and
// WBP_Saskarta_Pause are reparented to it in the editor lane; see
// Tools/GameFlow/specs/README_MenuInput.md for the exact steps.
//
// The rules live in SaskartaMenuNav.h (a pure, unit-tested reducer). This class:
//  - maps keys (arrows, Enter, Esc, gamepad D-pad / A / B, the left stick's
//    navigation events) to actions in NativeOnPreviewKeyDown, so the rows' own
//    Slate widgets (combo, slider, check box) never see the arrows;
//  - finds its widgets by name (the names Tools/GameFlow/gen_settings_specs.mjs
//    generates), or takes them from RegisterMenuItems / RegisterTabs /
//    RegisterRows / RegisterFooter / RegisterDialog;
//  - carries out the reducer's command: focus a widget, cycle a row (OnCycle),
//    click it (OnActivate), leave the menu (OnBack), or open the
//    "Apply changes?" prompt (ShowApplyPrompt);
//  - watches the keep-or-revert overlay (the BP shows it from
//    StartResolutionCountdown): while it is visible the focus is trapped in it,
//    with Revert focused first; when it closes, the focus returns to the footer's
//    Apply button with an "Applied" or "Reverted" toast, and the menu stays in
//    Settings;
//  - never grabs the focus on a timer (the old 50 ms focus guard made Settings
//    "glitchy, buttons don't work", user 2026-09-28): the focus moves only on a menu
//    key the menu took, when a dialog opens or closes, or by FocusCurrent;
//  - takes a key only when it is one of the menu's (MapMenuKey: arrows, Enter, Esc,
//    D-pad, left stick, gamepad A / B), the menu is shown, no combo is open and the
//    keyboard focus is inside the menu; everything else passes on untouched;
//  - (2026-09-28, "the buttons and controls in Settings are a bit broken") takes the left
//    stick once: its digital Gamepad_LeftStick_* keys go through MapMenuKey, and the analog
//    navigation XInput sends for the same push is stopped (it moved a second row); takes a
//    held Left / Right once per press on a selector or a toggle (a held key stepped the preset
//    or flipped a toggle ~30 times a second); keeps Tab / Shift+Tab inside an open dialog;
//    scrolls the page to the row it focuses; follows a click on a ◀ ▶ arrow to that arrow's
//    row; starts a page at its first row after a tab click; marks a slider dirty only when
//    its value changed; enters the "Apply changes?" prompt when the BP's Back opened it (the
//    footer's Back with unapplied changes); and stops handling a key once the menu has left.
//
// Mouse input is never handled here: clicks and hovers go to the widgets as before, and
// a click that moves the focus also moves the navigation state (NativeOnFocusChanging).
// LogSaskartaMenu: Log = every key taken or passed to the game; Verbose = every key
// passed on and why, focus follows, construct / destruct; VeryVerbose = non-menu keys.

#pragma once

#include "CoreMinimal.h"
#include "Blueprint/UserWidget.h"
#include "Types/SlateEnums.h"
#include "SaskartaMenuNav.h"
#include "SaskartaMenuWidget.generated.h"

class UButton;
class UComboBoxString;
class USlider;
class UWidgetSwitcher;

UCLASS(Abstract, Blueprintable)
class SASKARTACORE_API USaskartaMenuWidget : public UUserWidget
{
    GENERATED_BODY()

public:
    USaskartaMenuWidget(const FObjectInitializer& ObjectInitializer);

    // ─── Registration (by name in NativeConstruct when bAutoRegister, or from BP) ───

    /** A flat menu (title, pause): Up/Down wrap, Enter clicks, Esc calls OnBack. Replaces any earlier list. */
    UFUNCTION(BlueprintCallable, Category = "Saskarta|Menu")
    void RegisterMenuItems(const TArray<UWidget*>& Items);

    /** The settings tab buttons, top to bottom, and the switcher whose page i belongs to tab i (optional). */
    UFUNCTION(BlueprintCallable, Category = "Saskarta|Menu")
    void RegisterTabs(const TArray<UWidget*>& TabButtons, UWidgetSwitcher* Pages);

    /**
     * The focusable controls of one tab's rows, top to bottom (the combo, slider,
     * check box or button of each row). Types may be empty: each row's type is then
     * taken from its class (ComboBoxString = Selector, Slider, CheckBox = Toggle,
     * anything else = Button).
     */
    UFUNCTION(BlueprintCallable, Category = "Saskarta|Menu", meta = (AutoCreateRefTerm = "Types"))
    void RegisterRows(int32 TabIndex, const TArray<UWidget*>& Rows, const TArray<ESaskartaMenuRowType>& Types);

    /** The footer buttons, left to right (Apply, Revert, Back). */
    UFUNCTION(BlueprintCallable, Category = "Saskarta|Menu")
    void RegisterFooter(const TArray<UWidget*>& Buttons);

    /**
     * A modal: its root (watched for visibility for KeepOrRevert; shown and hidden
     * by the widget for ApplyChanges), its buttons left to right, the button that
     * gets the focus when it opens, and the one Esc presses.
     */
    UFUNCTION(BlueprintCallable, Category = "Saskarta|Menu")
    void RegisterDialog(ESaskartaMenuDialog Dialog, UWidget* Root, const TArray<UWidget*>& Buttons, int32 DefaultIndex, int32 CancelIndex);

    /** Finds every widget by the names below (called by NativeConstruct when bAutoRegister). */
    UFUNCTION(BlueprintCallable, Category = "Saskarta|Menu")
    void AutoRegister();

    // ─── Overridable behaviour (BlueprintNativeEvent: override and Call Parent as needed) ───

    /**
     * Left/Right on a row. The default steps a ComboBoxString (wrapping; it fires
     * OnSelectionChanged, so the row's own handler applies it, like the ◀ ▶ arrows),
     * steps a Slider by its StepSize and broadcasts OnValueChanged, or flips a
     * CheckBox and broadcasts OnCheckStateChanged. Marks the menu dirty.
     */
    UFUNCTION(BlueprintNativeEvent, Category = "Saskarta|Menu")
    void OnCycle(UWidget* Row, ESaskartaMenuRowType Type, int32 Direction);

    /** Enter on a menu item, row or footer button. The default clicks a Button (broadcasts OnClicked), flips a Toggle, steps a Selector forward. */
    UFUNCTION(BlueprintNativeEvent, Category = "Saskarta|Menu")
    void OnActivate(UWidget* Target, ESaskartaMenuRowType Type);

    /**
     * Esc at the top level. The default calls this widget's BP function named
     * BackFunctionName (the settings page's "Back") if it has one and returns true;
     * otherwise returns false and the key goes on to the game (the pause menu's
     * Esc then reaches PC_Saskarta's PollPauseKey as before).
     */
    UFUNCTION(BlueprintNativeEvent, Category = "Saskarta|Menu")
    bool OnBack();

    /** True when leaving would lose changes. The default returns the dirty flag (MarkDirty / ClearDirty). */
    UFUNCTION(BlueprintNativeEvent, BlueprintPure = false, Category = "Saskarta|Menu")
    bool HasUnappliedChanges();

    /**
     * Opens the "Apply changes?" prompt. The default shows the registered
     * ApplyChanges dialog root (PromptOverlay) and returns true; with no prompt
     * registered it returns false and Esc falls back to OnBack (discard and leave).
     */
    UFUNCTION(BlueprintNativeEvent, BlueprintCallable, Category = "Saskarta|Menu")
    bool ShowApplyPrompt();

    /** Shows a short message ("Applied", "Reverted"). The default writes it into the ToastWidgetName text block, else into FallbackToastName, for ToastSeconds. */
    UFUNCTION(BlueprintNativeEvent, Category = "Saskarta|Menu")
    void OnShowToast(const FText& Message);

    /** Fired whenever the navigation focus moves (keys, gamepad or a mouse click). Index is the menu item, row, footer or dialog button. */
    UFUNCTION(BlueprintImplementableEvent, Category = "Saskarta|Menu")
    void OnMenuFocusChanged(ESaskartaMenuLevel Level, int32 TabIndex, int32 Index, UWidget* Focused);

    // ─── Small API ───

    UFUNCTION(BlueprintCallable, Category = "Saskarta|Menu")
    void MarkDirty();

    UFUNCTION(BlueprintCallable, Category = "Saskarta|Menu")
    void ClearDirty();

    UFUNCTION(BlueprintCallable, Category = "Saskarta|Menu")
    void ShowToast(const FText& Message);

    /** Gives the keyboard / gamepad focus back to the current item (after a BP moved it elsewhere). */
    UFUNCTION(BlueprintCallable, Category = "Saskarta|Menu")
    void FocusCurrent();

    /** Moves the navigation to a tab (and its page) and focuses the tab button. */
    UFUNCTION(BlueprintCallable, Category = "Saskarta|Menu")
    void SelectTab(int32 TabIndex);

    UFUNCTION(BlueprintPure, Category = "Saskarta|Menu")
    ESaskartaMenuLevel GetMenuLevel() const { return Nav.Level; }

    UFUNCTION(BlueprintPure, Category = "Saskarta|Menu")
    int32 GetMenuTabIndex() const { return Nav.Tab; }

    UFUNCTION(BlueprintPure, Category = "Saskarta|Menu")
    int32 GetMenuRowIndex() const { return Nav.Row; }

    UFUNCTION(BlueprintPure, Category = "Saskarta|Menu")
    ESaskartaMenuDialog GetOpenDialog() const { return Nav.Level == ESaskartaMenuLevel::Dialog ? Nav.Dialog : ESaskartaMenuDialog::None; }

    /** The widget that should have the focus now. */
    UFUNCTION(BlueprintPure, Category = "Saskarta|Menu")
    UWidget* GetCurrentMenuWidget() const;

    /** The menu's keys and what they do; false for every other key (and every mouse button). Pure; tested. */
    static bool MapMenuKey(const FKey& Key, ESaskartaMenuAction& OutAction);

    // ─── Configuration (class defaults of the reparented widget blueprints) ───

    /** Find the widgets by the names below in NativeConstruct (before the BP's Construct runs). */
    UPROPERTY(EditDefaultsOnly, BlueprintReadOnly, Category = "Saskarta|Menu")
    bool bAutoRegister = true;

    /** Flat menu items in order. Empty: every Button in the tree, in tree order (when there is no tab bar). */
    UPROPERTY(EditDefaultsOnly, BlueprintReadOnly, Category = "Saskarta|Menu")
    TArray<FName> MenuItemNames;

    /** The panel holding the tab buttons (its Button children, in order). */
    UPROPERTY(EditDefaultsOnly, BlueprintReadOnly, Category = "Saskarta|Menu")
    FName TabBarName = TEXT("TabBar");

    /** The WidgetSwitcher of the tab pages; each page's rows are found in tree order. */
    UPROPERTY(EditDefaultsOnly, BlueprintReadOnly, Category = "Saskarta|Menu")
    FName TabSwitcherName = TEXT("TabSwitcher");

    /** Buttons inside a row whose name ends with one of these are not rows (the ◀ ▶ arrows). They mark the menu dirty when clicked. */
    UPROPERTY(EditDefaultsOnly, BlueprintReadOnly, Category = "Saskarta|Menu")
    TArray<FString> ArrowButtonSuffixes;

    /** Footer buttons, left to right. */
    UPROPERTY(EditDefaultsOnly, BlueprintReadOnly, Category = "Saskarta|Menu")
    TArray<FName> FooterButtonNames;

    /** Which footer button applies (its click clears the dirty flag and shows the "Applied" toast unless a keep-or-revert check opens). */
    UPROPERTY(EditDefaultsOnly, BlueprintReadOnly, Category = "Saskarta|Menu")
    FName ApplyButtonName = TEXT("ApplyButton");

    /** Which footer button reverts (its click clears the dirty flag). */
    UPROPERTY(EditDefaultsOnly, BlueprintReadOnly, Category = "Saskarta|Menu")
    FName RevertButtonName = TEXT("RevertButton");

    /** The keep-or-revert overlay (made visible by the BP's StartResolutionCountdown). */
    UPROPERTY(EditDefaultsOnly, BlueprintReadOnly, Category = "Saskarta|Menu")
    FName KeepDialogName = TEXT("ConfirmOverlay");

    /** Its buttons, left to right: Keep, Revert. */
    UPROPERTY(EditDefaultsOnly, BlueprintReadOnly, Category = "Saskarta|Menu")
    TArray<FName> KeepDialogButtonNames;

    /** The keep-or-revert button that is focused when it opens and that Esc presses (Revert). */
    UPROPERTY(EditDefaultsOnly, BlueprintReadOnly, Category = "Saskarta|Menu")
    int32 KeepDialogDefaultIndex = 1;

    /** The "Apply changes?" overlay (added by the editor lane; optional). */
    UPROPERTY(EditDefaultsOnly, BlueprintReadOnly, Category = "Saskarta|Menu")
    FName PromptDialogName = TEXT("PromptOverlay");

    /** Its buttons, left to right: Apply, Discard, Cancel. */
    UPROPERTY(EditDefaultsOnly, BlueprintReadOnly, Category = "Saskarta|Menu")
    TArray<FName> PromptButtonNames;

    /** The prompt button focused when it opens (Apply). */
    UPROPERTY(EditDefaultsOnly, BlueprintReadOnly, Category = "Saskarta|Menu")
    int32 PromptDefaultIndex = 0;

    /** The prompt button Esc presses (Cancel). */
    UPROPERTY(EditDefaultsOnly, BlueprintReadOnly, Category = "Saskarta|Menu")
    int32 PromptCancelIndex = 2;

    /** OnBack's default calls this BP function (no parameters) when the widget has it. */
    UPROPERTY(EditDefaultsOnly, BlueprintReadOnly, Category = "Saskarta|Menu")
    FName BackFunctionName = TEXT("Back");

    /** A TextBlock for toasts (optional). */
    UPROPERTY(EditDefaultsOnly, BlueprintReadOnly, Category = "Saskarta|Menu")
    FName ToastWidgetName = TEXT("Toast");

    /** Used for toasts when there is no ToastWidgetName. None: the settings page's description line is rewritten every 50 ms, so it cannot hold a toast. */
    UPROPERTY(EditDefaultsOnly, BlueprintReadOnly, Category = "Saskarta|Menu")
    FName FallbackToastName = NAME_None;

    UPROPERTY(EditDefaultsOnly, BlueprintReadOnly, Category = "Saskarta|Menu")
    float ToastSeconds = 2.0f;

    UPROPERTY(EditDefaultsOnly, BlueprintReadOnly, Category = "Saskarta|Menu")
    FText AppliedText;

    UPROPERTY(EditDefaultsOnly, BlueprintReadOnly, Category = "Saskarta|Menu")
    FText RevertedText;

    /** Keep-or-revert overlay watch period, seconds (min 0.05). It never moves the focus. */
    UPROPERTY(EditDefaultsOnly, BlueprintReadOnly, Category = "Saskarta|Menu")
    float PollInterval = 0.05f;

protected:
    virtual void NativeConstruct() override;
    virtual void NativeDestruct() override;
    virtual FReply NativeOnPreviewKeyDown(const FGeometry& InGeometry, const FKeyEvent& InKeyEvent) override;
    virtual FReply NativeOnKeyDown(const FGeometry& InGeometry, const FKeyEvent& InKeyEvent) override;
    using Super::NativeOnNavigation;
    virtual FNavigationReply NativeOnNavigation(const FGeometry& MyGeometry, const FNavigationEvent& InNavigationEvent, const FNavigationReply& InDefaultReply) override;
    virtual void NativeOnFocusChanging(const FWeakWidgetPath& PreviousFocusPath, const FWidgetPath& NewWidgetPath, const FFocusEvent& InFocusEvent) override;

    virtual void OnCycle_Implementation(UWidget* Row, ESaskartaMenuRowType Type, int32 Direction);
    virtual void OnActivate_Implementation(UWidget* Target, ESaskartaMenuRowType Type);
    virtual bool OnBack_Implementation();
    virtual bool HasUnappliedChanges_Implementation();
    virtual bool ShowApplyPrompt_Implementation();
    virtual void OnShowToast_Implementation(const FText& Message);

private:
    struct FTabRows
    {
        TArray<TWeakObjectPtr<UWidget>> Rows;
        TArray<ESaskartaMenuRowType> Types;
    };

    struct FDialogInfo
    {
        TWeakObjectPtr<UWidget> Root;
        TArray<TWeakObjectPtr<UWidget>> Buttons;
        int32 DefaultIndex = 0;
        int32 CancelIndex = 0;
    };

    /** Runs one action; returns true when it was used. */
    bool HandleAction(ESaskartaMenuAction Action);
    FSaskartaMenuNavContext BuildContext();
    UWidget* WidgetFor(const FSaskartaMenuNavState& State) const;
    void FocusWidget(UWidget* Widget);
    void ApplyNavState(const FSaskartaMenuNavState& NewState, bool bFocus);
    void OpenTabPage(int32 TabIndex);
    bool IsUsable(const UWidget* Widget) const;
    bool IsMenuShown() const;
    bool IsAnyComboOpen() const;
    /** The keyboard focus is on this widget or inside it. */
    bool HasMenuKeyboardFocus() const;
    /** A key event the menu may take: a menu key (OutAction), not the mouse, menu shown, no combo open, focus inside. Logs why not. */
    bool MayHandleKey(const FKeyEvent& InKeyEvent, ESaskartaMenuAction& OutAction, const TCHAR* Phase) const;
    bool CallNoParamFunction(FName FunctionName);
    void BindDirtySources(UWidget* Control);
    /** The row (tab, index) whose control shares a parent with this ◀ ▶ arrow. */
    bool RowOfArrow(const UWidget* Arrow, int32& OutTab, int32& OutRow) const;
    /** Scrolls the nearest ScrollBox above Widget so that it is in view (a tab page's rows). */
    void ScrollIntoView(UWidget* Widget);
    /** The current row is a selector or a toggle (one step per key press, no repeat). */
    bool IsCurrentRowStepped() const;
    void EnterDialog(ESaskartaMenuDialog Dialog);
    void LeaveDialog(bool bFocusApply);
    void FinishApplyPrompt(int32 ButtonIndex);
    void HideToast();

    /**
     * The keep-or-revert watch and the prompt watch (never moves the focus outside a dialog).
     * Returns true when it left the menu (OnBack after the keep-or-revert check), so the caller
     * must not touch the widget's state any more.
     */
    bool PollMenu();
    /** Timer target for PollMenu. */
    void PollMenuTimer();

    // Delegate targets (dynamic, so UFUNCTION).
    UFUNCTION()
    void HandleDirtyClick();
    UFUNCTION()
    void HandleComboChanged(FString SelectedItem, ESelectInfo::Type SelectionType);
    UFUNCTION()
    void HandleCheckChanged(bool bIsChecked);
    UFUNCTION()
    void HandleSliderCaptureBegin();
    UFUNCTION()
    void HandleSliderCaptureEnd();
    UFUNCTION()
    void HandleApplyClicked();
    UFUNCTION()
    void HandleRevertClicked();
    UFUNCTION()
    void HandleKeepClicked();
    UFUNCTION()
    void HandleRevertNowClicked();
    UFUNCTION()
    void HandlePromptApply();
    UFUNCTION()
    void HandlePromptDiscard();
    UFUNCTION()
    void HandlePromptCancel();

    static ESaskartaMenuRowType TypeOf(const UWidget* Control);
    const FDialogInfo* DialogInfo(ESaskartaMenuDialog Dialog) const;

    FSaskartaMenuNavState Nav;

    TArray<TWeakObjectPtr<UWidget>> MenuItems;
    TArray<TWeakObjectPtr<UWidget>> Tabs;
    TWeakObjectPtr<UWidgetSwitcher> TabPages;
    TArray<FTabRows> TabRows;
    TArray<TWeakObjectPtr<UWidget>> FooterButtons;
    FDialogInfo KeepDialog;
    FDialogInfo PromptDialog;
    TArray<TWeakObjectPtr<UComboBoxString>> Combos;
    /** The ◀ ▶ arrows (not rows; a click focuses one, and the navigation follows it to its row). */
    TArray<TWeakObjectPtr<UWidget>> ArrowButtons;
    /** The rows' sliders, and their values when a mouse / controller capture began. */
    TArray<TWeakObjectPtr<USlider>> Sliders;
    TArray<float> SliderValuesAtCapture;

    bool bDirty = false;
    /** An Apply click is waiting to see whether the keep-or-revert check opens. */
    bool bApplyPending = false;
    /** The keep-or-revert check was closed by Keep (true) or Revert / timeout (false). */
    bool bKept = false;
    /** Leave Settings once the keep-or-revert check closes (Apply chosen in the "Apply changes?" prompt). */
    bool bLeaveAfterKeepDialog = false;
    /** Set while this class moves the focus itself, so NativeOnFocusChanging does not re-derive the state. */
    bool bSettingFocus = false;
    /** The level the last pressed (non-repeat) menu key acted on without leaving it; its repeats act only there. Unset: no repeats. */
    TOptional<ESaskartaMenuLevel> RepeatLevel;

    FTimerHandle PollTimer;
    FTimerHandle ToastTimer;
    TWeakObjectPtr<UWidget> ToastTarget;
    bool bToastIsFallback = false;
    FText ToastPreviousText;
};
