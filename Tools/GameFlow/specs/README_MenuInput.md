# Menu keyboard / gamepad input (USaskartaMenuWidget)

Task MENUINPUT. The title, settings and pause widgets get a C++ parent class, `USaskartaMenuWidget` (plugin `SaskartaCore`), which does the key handling that bpgraph can't author (an `OnKeyDown` override):

- the two-level Settings navigation (tab list, then rows, then footer);
- Esc handling and the "Apply changes?" prompt;
- the keep-or-revert modal;
- the fix for "Apply -> Keep jumps to the title".

The code lives in:

- `Plugins/SaskartaCore/Source/SaskartaCore/Public/SaskartaMenuWidget.h` and `Private/SaskartaMenuWidget.cpp`: the widget.
- `Public/SaskartaMenuNav.h` and `Private/SaskartaMenuNav.cpp`: the rules, as a pure reducer.
- `Private/Tests/SaskartaMenuNavTest.cpp`: the tests (`Automation RunTests Saskarta.Menu`).

**Rebuilding Settings (2026-09-28): go to section 3.** Section 4 is the two-minute test for the user.

## 0. Build first (editor CLOSED)

The class has been built since 9/27. The source changes again on 2026-09-28 (section 3, step 2), so build once more before the next Settings rebuild. Close the editor, then run:

```
start "" /belownormal /wait /b "C:\Program Files\Epic Games\UE_5.8\Engine\Build\BatchFiles\Build.bat" UnrealEditor Win64 Development -Project="D:\UnrealEngine\saskartarad\saskartarad.uproject" -WaitMutex -NoHotReloadFromIDE
```

Don't use Live Coding for these changes. They add UFUNCTIONs and a virtual override, and Live Coding can't add reflected functions.

If the build fails, the previous `UnrealEditor-SaskartaCore.dll` stays in place and the editor still opens.

After the build, open the editor and run `Automation RunTests Saskarta.Menu`. All 7 tests should pass.

## 1. What the player gets

| Where | Key / button | Result |
|---|---|---|
| Title, pause | Up / Down, D-pad, left stick | Moves between the items, wrapping round. The stick moves one item per push. |
| Title, pause | Enter / A | Clicks the item. |
| Title, pause | Esc / B | Not handled here. The title ignores it. On the pause menu it reaches `PC_Saskarta.PollPauseKey` -> `HandleEscape` -> resume, as before. |
| Settings, tab list | Up / Down | Moves to the previous / next tab. The page switches at once. |
| Settings, tab list | Enter / Right / A | Enters the rows at the first row, or at the row you left last time. |
| Settings, tab list | Esc / B | Leaves Settings (the BP's `Back`). If there are unapplied changes, it first opens **Apply changes?** with Apply / Discard / Cancel. |
| Settings, rows | Up / Down | Moves between rows, skipping collapsed ones such as FrameGen without DLSS. Down past the last row goes to the footer's **Apply**. The page scrolls to keep the row in view. |
| Settings, rows | Left / Right | Steps a selector (it wraps; the row's handler applies the value, like the ◀ ▶ arrows). Steps a slider by its `StepSize`. Flips a toggle. Holding the key repeats on a slider only; a selector or a toggle takes one step per press. |
| Settings, rows | Enter / A | Flips a toggle, clicks a button (RUN BENCHMARK), or steps a selector forward. |
| Settings, rows | Esc / B | Back to the tab list, with the focus on the current tab. |
| Settings, footer | Left / Right | Moves between Apply / Revert / Back. |
| Settings, footer | Up | Goes to the last row. |
| Settings, footer | Enter | Clicks the button. **Back** with unapplied changes asks **Apply changes?** first (so does a mouse click on Back, and Esc from the pause menu). |
| Settings, footer | Esc | Back to the tab list. |
| Keep-or-revert modal | (on open) | Revert has the focus. |
| Keep-or-revert modal | Left / Right, Tab / Shift+Tab | Switches between the buttons. The focus can't leave the modal. |
| Keep-or-revert modal | Enter | Presses the focused button. |
| Keep-or-revert modal | Esc | Revert. |
| Keep-or-revert modal | Any other key | Swallowed. |
| Apply | Enter or click | Shows **Applied** at the bottom right, next to the footer, and stays in Settings. Only a resolution or window-mode change (compared with the last confirmed one) first shows the modal. After Keep: Applied, and the focus goes back to the footer's Apply. After Revert or the 15 s timeout: Reverted. It never returns to the title. |
| Revert | Enter or click | Drops every unapplied change, the quality groups too, and shows **Reverted**. |

**Held keys.** A held arrow or stick repeats only on the level where it was pressed, and only if the press stayed on that level:

- Right held on a tab enters the rows once and does not then drag the first row's slider;
- Down held through the rows stops on the footer's Apply;
- Enter and Esc never repeat.

**Mouse.** Clicks and hovers reach the widgets as before. A click that moves the focus also moves the navigation (`NativeOnFocusChanging`), so the keys continue from where you clicked:

- a click on a ◀ ▶ arrow moves the navigation to that arrow's row;
- a click on a tab starts that page at its first row.

The focused row glows fully and owns the description line. A row that is only hovered glows faintly, and shows its description only while nothing on the page has the focus.

These changes made with the mouse count as unapplied:

- combo picks;
- slider drags that move the value (a click on the knob that does not move it no longer counts);
- check box clicks;
- ◀ ▶ arrow clicks.

**The focus is never taken on a timer.** The old 0.05 s focus guard is gone (user, 2026-09-28: Settings "glitchy, buttons don't work"). The focus moves only in these cases:

- on a menu key that the menu took;
- when a dialog opens or closes;
- when the BP calls `FocusCurrent`.

A click elsewhere leaves the focus there. The menu keys then pass on to the game until the focus is back inside the menu (a click on any row or tab).

**The "Apply -> Keep jumps to the title" bug (likely cause, not reproduced).** The old keep-or-revert overlay never took the focus, so the focus stayed on the footer's Apply button behind it. The arrow keys then walked the hidden footer (Revert, Back) under the modal, and Enter on Keep's position clicked **Back**. Back reverts and returns to the title. Now the modal traps the focus:

- Revert is focused when it opens;
- only Keep and Revert are reachable, with the arrows and with Tab;
- the focus returns to Apply when the modal closes.

## 2. Editor-lane steps (done 9/27; kept for reference)

### 2a. Reparent the three widget blueprints

Done. `WBP_Saskarta_Title`, `WBP_Saskarta_Settings` and `WBP_Saskarta_Pause` are children of `SaskartaMenuWidget`. A `--reset-graphs` build keeps the parent class.

### 2b. Class defaults

The defaults already match the names that `gen_settings_specs.mjs` generates. The Settings spec's `cdo_defaults` also sets `bAutoRegister = true` and `PollInterval = 0.05` explicitly.

| Property | Default | Meaning |
|---|---|---|
| `bAutoRegister` | true | Finds the widgets below by name in `NativeConstruct`, before the BP's `Construct`. |
| `MenuItemNames` | empty | The flat menu. Empty means every Button in tree order, which gives Start/Settings/Quit and Resume/Settings/Quit. |
| `TabBarName` / `TabSwitcherName` | `TabBar` / `TabSwitcher` | The tab buttons (the Button children, in order) and the pages. Each page's rows are found in tree order, and each row's control is its ComboBoxString / Slider / CheckBox / Button. |
| `ArrowButtonSuffixes` | `Prev`, `Next` | The ◀ ▶ arrows. They are not rows. Clicking one marks the menu dirty and moves the navigation to its row. |
| `FooterButtonNames` | `ApplyButton`, `RevertButton`, `BackButton` | |
| `ApplyButtonName` / `RevertButtonName` | `ApplyButton` / `RevertButton` | Their clicks clear the dirty flag. Apply shows the "Applied" toast; Revert shows "Reverted". |
| `KeepDialogName` / `KeepDialogButtonNames` / `KeepDialogDefaultIndex` | `ConfirmOverlay` / `KeepButton`, `RevertNowButton` / 1 | The keep-or-revert modal. Revert gets the focus when it opens, and Esc presses it. |
| `PromptDialogName` / `PromptButtonNames` | `PromptOverlay` / `PromptApplyButton`, `PromptDiscardButton`, `PromptCancelButton` | The "Apply changes?" prompt. The order matters: Apply, Discard, Cancel. |
| `PromptDefaultIndex` / `PromptCancelIndex` | 0 / 2 | Apply gets the focus when the prompt opens; Esc presses Cancel. |
| `BackFunctionName` | `Back` | `OnBack` calls this BP function when the widget has it. That's the settings page's `Back`. The title and the pause menu don't have one, so Esc passes through to the game. |
| `ToastWidgetName` / `FallbackToastName` | `Toast` / None | "Applied" / "Reverted" go into the `Toast` text block for `ToastSeconds` (2 s). There is no fallback: the description line is rewritten every 50 ms, so it can't hold a toast. |
| `PollInterval` | 0.05 | How often the widget watches the keep-or-revert overlay and the prompt. It never moves the focus outside a dialog. |

### 2c. The "Apply changes?" prompt and the toast

Both are in `settingsTree()` in `gen_settings_specs.mjs`:

- **`PromptOverlay`:** the same look as the keep-or-revert box. It has no graph of its own. The C++ shows it, hides it, and handles its three buttons for both Enter and clicks:
  - **Apply:** clicks the footer's Apply, which runs the BP's `ApplyPending`. If that opens the keep-or-revert check, Settings closes after the check. Otherwise it leaves Settings through `Back`, which has nothing left to revert.
  - **Discard:** calls `Back`, which reverts and leaves.
  - **Cancel:** stays in Settings, on the tab list.
- **`Toast`:** a Collapsed, right-aligned gold `TextBlock` on the footer line, just left of the three chips.

The BP's `Back` also opens the prompt (`HasUnappliedChanges` -> `ShowApplyPrompt`), and the C++ then moves the focus into it. The prompt's Discard and Apply clear the dirty flag before they call `Back` again.

### 2d. What the graphs do

- **Focus poll.** The 50 ms `UpdateFocus` poll draws the row glow, the description and the tab bar from the real focus. The C++ moves that real focus.
- **Arrows.** `Cycle` serves the ◀ ▶ arrows.
- **Leaving.** `Back` / `SetReturn` restore the title or pause panel.
- **Preview.** A row edit previews live. Only the engine settings use the full `Preview` (it re-applies every scalability group): VSync, frame cap, the quality groups and the preset. The other rows use `PreviewLight` (the Saskarta CVars, the audio mix, the FOV). The two foliage sliders call `PreviewLight` 0.3 s after the last step, because their CVars recreate the render state.
- **Presets.** A preset pick no longer applies or saves anything by itself. `USaskartaGameUserSettings::SetOverallScalabilityLevel` writes the foliage and cloud rows from the preset table, and the menu's Apply applies and saves.
- **Apply.** `ApplyPending` applies, saves and re-reads every row (`RefreshAll`). Only a real display change starts the countdown.
- **Revert.** `RevertPending` (Revert, Back, Discard) reloads the saved settings, including the saved scalability groups (`USaskartaGameUserSettings::LoadSettings(true)`).
- **Frame cap.** The frame cap row always shows one of 30 / 45 / 60.
- **Pause.** `PC_Saskarta.PollPauseKey` is unchanged. While Settings has the focus, it consumes Esc, so `WBP_Saskarta_Pause.HandleEscape`'s "settings open" branch is a fallback.

## 3. Runbook: rebuild WBP_Saskarta_Settings (2026-09-28)

### Where things stand

- **The asset on disk is HEAD (`ce1b1a67`).** `Content/SaskartaGaea/GameFlow/UI/WBP_Saskarta_Settings.uasset` was restored with `git checkout HEAD --`. It is fully wired, so Settings works, and the key layer is on. It doesn't have:
  - the Sensor filter row;
  - the new frame-cap list (it still lists 30/60/80/120/144/Unlimited, and the C++ clamps those to 60);
  - any of the 2026-09-28 fixes.
- **The half-built asset is set aside.** It was on disk before the restore: a `--reset-graphs` build was killed by Play at 12:16 UTC, the editor autosaved it at 12:29, and "Restore Packages" put it back into Content at 12:34. It is in `Saved/SettingsHalfBuild_2026-09-28/`, with the five old `WBP_Saskarta_Settings_Auto*.uasset` autosaves. **Never restore it.**
- **The specs and the C++ are current and committed.** The specs are `specs/WBP_Saskarta_Settings.graph.json` and `.tree.json`. The C++ is `SaskartaMenuWidget.*` and `SaskartaGameUserSettings.*`. The C++ is not built in the project yet: a copy compiled clean.

The rebuild takes about 25 minutes of editor time, in one lane, and **nobody presses Play** during it. A Play press in the middle of a build is what broke Settings on 9/28.

### A. Editor closed

1. **Free space on D:.** D: had 0 GB free at 16:50 UTC on 9/28 (1.3 GB after this task removed its own build copy). The asset save, the DDC, the logs and the plugin build all need room. The old build copies in `D:\tmp` hold about 37 GB of `Intermediate` folders (`sask-*`, `SaskEvtCheck`, `saskcheck`, `anim-host`, `aphrosia-host`). Delete the ones whose lanes are finished, or free 5 GB or more elsewhere.
2. **Build SaskartaCore** (section 0). Expect `Result: Succeeded`. If it fails, stop and fix it first. The new graphs still work on the old DLL, only degraded:
   - the prompt that the footer's Back opens doesn't take the keyboard focus;
   - a preset pick shows its foliage values only after Apply.
3. **Check the files:**
   - `node Tools/GameFlow/gen_settings_specs.mjs` (no `--pc`), then `git status --short Tools/GameFlow/specs` must show no change to the Settings specs. Without `--pc`, the PC specs are never touched.
   - `ls Saved/Autosaves/Game/SaskartaGaea/GameFlow/UI/ | grep Settings` must show nothing.
   - `attrib Content\SaskartaGaea\GameFlow\UI\WBP_Saskarta_Settings.uasset` must not show `R`. If it does, run `attrib -R` on it. `build_settings_ui.mjs` and `bpgraph.mjs` refuse a read-only package (exit 3), because saving one crashed the editor on 9/27.

### B. Editor open

4. **Launch the editor.** If **Restore Packages** appears, don't restore anything you don't own. `Saved/Autosaves/PackageRestoreData.json` lists `WBP_Saskarta_Radio_Auto3` and 8 `S07_WaitingWater` external objects from other lanes: ask their owner. Never restore `WBP_Saskarta_Settings`.
5. **Tell the user the window:** "Settings rebuild from HH:MM for about 25 minutes. Please don't press Play or save until I say it's done." No Ctrl+S or Save All during the build: a Save All at 12:15 wrote a half-built asset to Content.
6. **Take the lane:** `python Tools/GameFlow/editor_gate.py acquire --owner SETTINGS --lane long`.
7. **Turn autosave off and keep the editor at full speed.** Hayba runs one command per editor frame, and at 3 fps in the background the last build took 25 minutes.
   - **Autosave:** Editor Preferences > General > Loading & Saving > Auto Save > **Enable AutoSave** off. Or in Hayba Python: `unreal.get_default_object(unreal.EditorLoadingSavingSettings).set_editor_property('auto_save_enable', False)`.
   - **Speed:** Hayba `set_cpu_throttle_override` on, or Editor Preferences > General > Performance > **Use Less CPU when in Background** off. Keep the editor in the foreground if you can.
8. **Check that PIE is off:** `python Tools/GameFlow/pie_guard.py python -c "print('no PIE')"` must print `no PIE`. Exit 97 means PIE is running: stop it first.
9. **Tree** (about 2 minutes; adds the Sensor filter row, the 30/45/60 frame cap and the Toast):

   ```
   python Tools/GameFlow/pie_guard.py node Tools/GameFlow/build_settings_ui.mjs Tools/GameFlow/specs/WBP_Saskarta_Settings.tree.json --clear
   ```

   Accept it only on exit 0. It ends with a compile and a save.
10. **Graphs** (about 15 minutes at full frame rate):

    ```
    python Tools/GameFlow/pie_guard.py node Tools/GameFlow/bpgraph.mjs build --reset-graphs Tools/GameFlow/specs/WBP_Saskarta_Settings.graph.json > Saved/SettingsBuild_report.json
    ```

    - Build **only** this spec. Never build `PC_Saskarta*.json` with it.
    - Accept it only when all of these hold:
      - the exit code is 0;
      - stderr ends with `bpgraph: ... commands ... — OK`;
      - the report has `"ok": true`, 71 graphs, 1699 links found of 1699, and no `missing` entries.
    - Pass 3 sets the class defaults (`bAutoRegister`, `PollInterval`, `DesiredFocusWidget`) and compiles and saves.
11. **If the guard kills a step** (exit 98, "PIE started"):
    1. Stop PIE.
    2. **Don't save.** File > Exit, and choose Don't Save for WBP_Saskarta_Settings.
    3. Delete `Saved/Autosaves/Game/SaskartaGaea/GameFlow/UI/WBP_Saskarta_Settings_Auto*.uasset`.
    4. If the Content file's time changed, run `git checkout HEAD -- Content/SaskartaGaea/GameFlow/UI/WBP_Saskarta_Settings.uasset`.
    5. Relaunch, decline Restore Packages for it, and start again at step 8.
12. **Finish the window:**
    - turn autosave back on;
    - turn the CPU throttle override off;
    - `python Tools/GameFlow/editor_gate.py release --owner SETTINGS`;
    - tell the user that Play is safe.

### C. Verify and commit

13. **Check the asset offline:** `node Tools/GameFlow/verify_settings_asset.mjs` must print `155 / 155 spec strings and graph names found` and exit 0. It checks every row description, every ReadSetting name and every function name in the uasset bytes. It catches a half-wired build, which compiles clean and logs nothing. The HEAD asset of 9/28 reports 149 / 155, missing only the new Sensor filter / frame-cap / PreviewLight strings.
14. **Commit by pathspec only** (the editor's Git provider stages new packages by itself):

    ```
    git commit -m "Settings rebuilt from the 2026-09-28 specs" -- Content/SaskartaGaea/GameFlow/UI/WBP_Saskarta_Settings.uasset
    ```

15. **Hand over to the user:** they run the two-minute test (section 4).

## 4. Two-minute test (user, PIE)

Start PIE from the title. Tick each line; anything that fails, note the row and the key.

**Mouse (30 s)**

- [ ] Title > Settings. Click each tab: the page and the gold bar follow.
- [ ] Graphics: click ▶ on Shadows twice. The value steps, and the Shadows row glows.
- [ ] Drag Master volume: the number follows the knob and the sound level changes. Drag Foliage distance: the % follows, and there's no freeze.
- [ ] Click **Apply**. **Applied** appears bottom right for 2 s. You stay in Settings.
- [ ] Change Shadows, then click **Revert**. **Reverted** appears, and Shadows shows its old value (the shadows look as before).
- [ ] Change Subtitle size, then click **Back**. **Apply changes?** opens. Click Cancel: you stay. Click Back again, then Discard: Settings closes. Reopen it: the old size is shown.

**Keyboard (45 s)**

- [ ] Reopen Settings. Up/Down on the tabs switches pages. Right enters the rows, and the first row glows.
- [ ] Graphics: Down to the last row (Clouds). The page scrolls, and the row stays visible.
- [ ] Hold Right on Preset: it moves one step only. Hold Right on a slider (Foliage density): it glides.
- [ ] Display: Right on Window mode, then Down to Apply and Enter. **Keep these display settings?** opens with Revert focused. Tab and Left/Right stay inside the dialog. Left, then Enter on Keep: **Applied**, the focus is on Apply, and you are still in Settings.
- [ ] Change the window mode again and Apply, then press Esc in the dialog: **Reverted**. Once more, and wait 15 s: **Reverted**.
- [ ] Change FOV. Esc (to the tabs), then Esc again: **Apply changes?** opens with Apply focused. Choose Apply: Settings closes with the FOV kept.
- [ ] Apply with no display change: no countdown dialog appears (in PIE too).

**Gamepad (30 s)**

- [ ] The D-pad and the left stick each move exactly one row per push, on the tabs and in the rows.
- [ ] A enters, activates or flips. B goes back one level. On the tab list, B leaves (or asks Apply changes?).
- [ ] Left stick left/right on Master volume: one step per push. Holding it glides.

**Each row (15 s)**

- [ ] Display: 7 rows. Frame rate cap shows only 30 / 45 / 60.
- [ ] Upscaling: 4 rows. Frame generation is hidden without DLSS.
- [ ] Graphics: 14 rows, and RUN BENCHMARK refreshes the Display and Upscaling rows too.
- [ ] Audio: 6 rows.
- [ ] Accessibility: 6 rows, including **Sensor filter** (Off / Low / Medium / High).
- [ ] The description line under the list always describes the keyboard-focused row, even while the mouse rests on another row.

**Pause**

- [ ] In game, Esc opens pause. Settings works as above. Esc from the Settings tab list returns to pause, with Settings focused.
