# Retro boot terminal

The black screen that opens the game (first boot) and follows every tether breach (reboot) becomes a 1980s computer terminal: a monochrome amber tube, a fixed-pitch pixel font, a ROM banner, a memory count-up, and status lines typed one by one, each with its `[ OK ]` or `[FAIL]` stamped a beat after the line ends.

This document is the contract for the agent that builds it in the editor. Everything here was prepared offline; nothing was built in Unreal.

| Output | Path |
|---|---|
| Fonts and licences | `Saved/Fonts/` (`VT323-Regular.ttf` + `VT323_OFL.txt`; `Glass_TTY_VT220.ttf` + `Glass_TTY_VT220_LICENSE.txt` + `Glass_TTY_VT220_README.md`) |
| Glyph check | `Tools/GameFlow/check_terminal_glyphs.py` |
| Widget graph spec | `Tools/GameFlow/specs/WBP_Saskarta_BootLog.graph.json` (rewritten) |
| Component spec | `Tools/GameFlow/specs/BPC_CarrierVision.json` (boot parts rewritten) |
| CRT shader | `Shaders/CRTTerminalUI.hlsl` |
| Material build script | `Tools/GameFlow/build_terminal_material.py` |
| SFX generator | `Tools/Audio/make_terminal_sfx.py` |
| SFX and manifest | `Saved/GameAudio/Terminal/*.wav`, `Saved/GameAudio/Terminal/manifest.json` |

## 1. Font

**Primary: VT323** (Peter Hull, SIL Open Font License 1.1). **Alternative: Glass TTY VT220** (Viacheslav Slavinsky, public domain / Unlicense).

| | VT323 | Glass TTY VT220 |
|---|---|---|
| Source | `github.com/google/fonts`, `ofl/vt323/VT323-Regular.ttf` | `github.com/svofski/glasstty`, `Glass_TTY_VT220.ttf` |
| Licence | OFL 1.1: may be embedded in a commercial game; ship `VT323_OFL.txt` with the game credits; the font may not be sold on its own | Public domain, no conditions |
| Design | DEC VT320 glyphs drawn on a clean pixel grid: 40 font units per pixel, advance 400/1000 em, cap height 14 pixels | VT220 glyphs with the CRT's **scanline gaps baked into the outlines**: every glyph row is a 50-unit bar with a 50-unit gap |
| Glyphs | 587 | 330 |
| Covers every boot character | yes | yes |
| Full block U+2588 | no | no |

Why VT323 is primary:

1. **The scanlines belong to the material, not the font.** Glass TTY draws its own scanlines at a 100-unit period. Our CRT material also draws scanlines, and two scanline patterns at different periods beat against each other (moire) unless the font size is locked to the material. VT323's solid pixels take the material's scanlines, glow and flicker cleanly at any size.
2. **Integer pixels at 1080p.** At UE size 37.5 (em = 50 px, because Slate renders fonts at 96 DPI: 37.5 x 96 / 72 = 50), one VT323 pixel is exactly 2 x 2 screen pixels, the advance is exactly 20 px, and one font pixel row is one scanline pair of the material (540 scanlines = 2 px each). Nothing is resampled.
3. **80 columns fit.** 20 px x 80 columns = 1600 px, inside 1920 with a 160 px margin each side.
4. **Coverage.** VT323 also has the em dash and degree sign, so the story's later log lines have room, although this spec keeps to uppercase ASCII as required.

When to switch to Glass TTY: if a softer, more "photographed VT220" look is wanted. Then set the font size to 30 (em 40 px, advance 20 px, glyph bars 2 px on / 2 px off) and set the material's `ScanlineDepth` to 0, or `ScanlineCount` to 270, so its baked lines are the only ones.

**Cursor.** Neither font has the full block U+2588, so the cursor is `_` (`CursorString` on the widget). VT323's underscore is a thick 2-font-pixel bar on the baseline, which reads as a proper terminal cursor.

**Glyph check.** `python Tools/GameFlow/check_terminal_glyphs.py` reads every text and string default and every concatenated literal in both specs, adds the counter digits and `K`, checks that all are uppercase ASCII (`->` not an arrow, `-` not a dash, `C` not a degree sign), and checks both fonts. Current result: 17 strings, 44 distinct characters (`' ()-./0123456789>ABCDEFGHIKLMNOPRSTUVWXYZ[]_'`), both fonts `ok`, exit 0. Rerun it after editing any boot line.

**Import (editor agent).** Import `Saved/Fonts/VT323-Regular.ttf` into `/Game/SaskartaGaea/GameFlow/UI/Fonts/` as a Font Face `FF_VT323`, then create a composite Font `Font_Terminal` whose default typeface `Regular` uses it.

- Font Face `Hinting`: **Monochrome**. This renders hard-edged pixels, which is authentic, and the material's glow softens them. If it looks too harsh at 720p, use `Auto Light`.
- Font Face `Loading Policy`: `Inline` (153 KB).
- Keep `VT323_OFL.txt` with the game's third-party notices.

## 2. The screens

### What the player sees

Final state of the first boot. The rows are 64 columns wide inside the 80-column grid, and each status is right-aligned to column 64.

```
HIGHLAND ASSISTIVE CARRIER  UNIT 07  ROM 2.07
(C) HIGHLAND ROUTE AUTHORITY

CORE MEMORY TEST  0640K                                   [ OK ]

CONTACTOR - CLOSING                                       [ OK ]
HANDOVER - CARRIER 06 -> CARRIER 07                       [ OK ]
LOAD - 1 CAPSULE / ARCHIVE / 36.6 C                       [ OK ]
ROUTE LOCK - ÂLAAWB                                       [ OK ]
_
```

Final state of a reboot. It is a warm restart, so there is no memory test and the memory row stays blank. The fault and the shutdown are what already happened, so they are replayed at once from the log: the player sees `[FAIL]` the moment the screen comes on. The last two lines are what is happening now, so they are typed.

```
HIGHLAND ASSISTIVE CARRIER  UNIT 07  ROM 2.07  WARM RESTART
(C) HIGHLAND ROUTE AUTHORITY


FAULT - ROUTE BOUNDARY EXCEEDED                           [FAIL]
EMERGENCY SHUTDOWN - COMPLETE                             [ OK ]
REINITIALIZING - CARRIER CORE                             [ OK ]
ROUTE LOCK - RESTORED                                     [ OK ]
_
```

The first-boot lines are storyline beat B01's handover lines (`docs/story/storyline.md`), converted to ASCII: `—` became `-`, `→` became `->`, `·` became `/` and `°C` became ` C`. The reboot lines are the design spec's reboot table, with `[FAIL]` on the fault.

### Behaviour

- **Header.** The ROM banner and the copyright line appear at once when the terminal starts, as a real ROM prints its banner, with a line-feed clunk.
- **Memory count-up (first boot only).** The count starts 0.2 s after the banner. It counts `0000K` to `0640K` in 16K steps over 0.7 s. The count is time-based, so it is not frame-rate dependent. `[ OK ]` lands 0.14 s after the count ends, together with the one system beep.
- **Typed lines.**
  - The typewriter prints about **55 characters/s**. It is time-based: each 20 ms tick shows `floor((now - TypeClock) x 55)` characters.
  - Small random stalls. On each tick there is an 8 % chance of a 60 ms stall, which moves `TypeClock` forward. The stalls are capped at 0.12 s per line (`StallBudget`), so a line can never overrun its slot.
  - The cursor sits solid at the end of the text while it types.
  - `[ OK ]` or `[FAIL]` lands **0.14 s** after the last character (`StatusDelay`), with a key-stamp click. The cursor then drops to the next row.
- **Cursor.** A blinking `_` on the next free row, toggled every 0.265 s (the classic 530 ms blink period). The blink restarts on every line feed, so the cursor always appears solid first. It does not blink while a line is typing.
- **A line cut short.** If a new line arrives while one is still open (a hitch, or the story director writing on its own timers), `FinishLine` completes the open line at once, with its status, before the new one starts. Nothing is lost or garbled.
- **Colour.** Monochrome amber, #FFB000, set by **one variable**: the `PhosphorColor` parameter of `M_UI_CRTTerminal`. The text blocks are plain white, and the material maps their brightness onto the phosphor colour. For green, set `PhosphorColor` to (0.033, 1.0, 0.033), which is #33FF33. The value is linear: UMG's linear colour of #FFB000 is (1.0, 0.434, 0.0).

## 3. Timing

All durations are variables on `BPC_CarrierVision`. The widget receives the ones that shape the schedule through `ConfigureTerminal` at `Setup`.

| Variable (BPC) | Default | Meaning |
|---|---|---|
| `FadeToBlackTime` | 0.6 | unchanged: title to black |
| `FirstLineDelay` | **1.25** (was 0.2) | first boot: blackout to the first typed line. Covers the banner, the memory test and its `[ OK ]`: 0.2 + 0.7 + 0.14 = 1.04, then a 0.21 s beat |
| `RebootFirstLineDelay` | 0.3 | reboot: blackout to the first typed line (line 3) |
| `CharsPerSecond` | 55 | typewriter speed |
| `StallBudget` | 0.12 | the most random stall time in one line |
| `StatusDelay` | 0.14 | last character to the status stamp |
| `LineGap` | 0.08 | worst-case status to the next line |
| `FinalHold` | 0.35 | worst-case last status to `PowerOn`, while the cursor blinks |
| `MemDelay` / `MemCountTime` | 0.2 / 0.7 | memory count start and length |
| `HumFadeTime` | 0.4 | fan hum fade-out at `PowerOn` |
| `BootBlack`, `OnTime`, `Residual`, `RampTime`, `OffTime` | 0.3, 0.3, 1.0, 0.8, 0.3 | unchanged: the shader's timeline |
| `LineInterval`, `PowerOnDelay` | removed | replaced by the per-line schedule below |

**The schedule.** The component is the conductor, and the widget only animates inside the slot it is given.

- After sending line *k*, `BootLineStep` stores `LineHold = Len(line) / CharsPerSecond + StallBudget + StatusDelay`. That is the latest moment line *k*'s status can land.
- The next line then starts at `LineHold + LineGap`.
- After the last line, `PowerOn` starts at `LineHold + FinalHold`.

This keeps the chain exact and deterministic, whatever the random stalls do. Longer or shorter text moves `PowerOn` with it, and the vision chain follows automatically, because `VisionOnline` and `CleanUp` stay relative to `PowerOn`.

**First boot** (t = 0 is Start pressed; nominal times, with 60 fps worst case in brackets):

| t | Event |
|---|---|
| 0.000 | `FadeToBlack`: the boot log fades in over black, terminal blank (`ClearTerminal`) |
| 0.600 | `BreachBlack` -> `HandleBlackout` -> `PlayBoot(FirstBoot)`. CRT power-on thunk + flyback whine, drive seek, fan hum. Banner printed (line-feed clunk). Cursor blinking on row 0 |
| 0.800 - 1.500 | Memory `0000K` -> `0640K` |
| 1.640 (1.650) | Memory `[ OK ]` + the system beep |
| 1.850 | Line 1 `CONTACTOR - CLOSING` (19 chars) starts, burst 01. Typed by 2.195; status by 2.455 at the latest |
| 2.535 | Line 2 `HANDOVER - CARRIER 06 -> CARRIER 07` (35) starts, burst 02; status by 3.432 |
| 3.512 | Line 3 `LOAD - 1 CAPSULE / ARCHIVE / 36.6 C` (35) starts, burst 03; status by 4.408 |
| 4.488 | Line 4 `ROUTE LOCK - ÂLAAWB` (19) starts, burst 04; status by 5.093 |
| **5.443** (5.477) | `PowerOn`: contactor + power-on hum + terminal CRT-off zap; `ClearTerminal`, boot log collapsed, fan hum fades; MID boot mode starts (its first 0.3 s is black) |
| **6.043** (6.077) | `VisionOnline` -> `HandleVisionOnline`: control (inside the 5.5-6.5 s target) |
| 7.043 (7.077) | `CleanUp` |

**Reboot** (t = 0 is the breach):

| t | Event |
|---|---|
| 0.000 / 0.800 | `PlayBreach` / `BreachPowerDown` (unchanged) |
| 1.100 | `BreachBlack`: terminal cleared, black. `HandleBlackout` -> respawn -> `PlayBoot(Reboot)`. CRT on, seek, hum. Banner `... WARM RESTART`, and the replayed lines `FAULT ... [FAIL]` and `EMERGENCY SHUTDOWN ... [ OK ]` printed at once |
| 1.400 | Line 3 `REINITIALIZING - CARRIER CORE` (29) starts, burst 03; status by 2.187 |
| 2.267 | Line 4 `ROUTE LOCK - RESTORED` (21) starts, burst 04; status by 2.909 |
| **3.259** (3.283) | `PowerOn` |
| **3.859** (3.883) | `VisionOnline`: control (was 3.7; target about 4) |
| 4.859 (4.883) | `CleanUp` |

If `TryRespawn` has to retry, everything from `PlayBoot` onwards shifts by the retry time, exactly as before.

**Checked by simulation.** A frame-quantised simulation of both timer layers ran 400 random seeds each at 60 fps and 30 fps. It used the widget's time-based typing, per-tick stall rolls, looping timers with `bMaxOncePerFrame` and one-shot lateness. In every run, every status landed before the next line started, and the memory `[ OK ]` landed before line 1. The worst control times were 6.150 / 6.200 s (first boot, 60 / 30 fps) and 3.883 / 3.900 s (reboot).

**Shader sync.** Unchanged. The MID's `VisionStart` is still set in the same frame that `PowerOn` collapses the boot log, and the boot mode's first `BootBlack` seconds are black, so there is no flash between the terminal and the vision.

**Voice.** `CV_BOOT` (storyline task 7) still starts at `HandleBlackout` and runs over the terminal into the first view. The terminal no longer advances at a fixed 0.45 s, but the voice was never locked to the log lines.

## 4. Widget layout: `WBP_Saskarta_BootLog`

Build it with Hayba's UI tools (`ui_build_tree`, `ui_set_text_style`, `ui_set_slot_layout`, `ui_set_variable is_variable=true`, `ui_validate`). Keep the widget's Tick Frequency at **Never**, with no property bindings.

### Replaced and restyled

| Old widget | Fate |
|---|---|
| `BootBlack` (Image) | **Kept**, unchanged: full-screen opaque black, the bottom layer. `SetBlackOpacity` still targets it |
| `BootStatus` (TextBlock, Roboto Light 28, bottom-left) | **Deleted**, replaced by the terminal rows |
| `BootDetail` (TextBlock, Roboto 13, bottom-left) | **Deleted**, replaced by the terminal rows |
| `SetLines(Status, Detail)` function | **Deleted** from the widget. Delete it **before** deleting the two TextBlocks, or the widget will not compile. The new spec does not declare it, and bpgraph never removes functions |

### Tree (sizes in px at 1080p; DPI scale 1.0 at 1080 lines, so every value scales with the screen)

```
RootCanvas                  CanvasPanel
├─ BootBlack                Image        anchors (0,0)-(1,1), offsets 0, tint (0,0,0,1), ZOrder 0         [variable]
└─ TermRetainer             RetainerBox  anchors (0,0)-(1,1), offsets 0, ZOrder 1
   │                          Effect Material = M_UI_CRTTerminal, Texture Parameter = Texture,
   │                          Retain Rendering = true, Phase 0, Phase Count 1
   └─ TermCanvas            CanvasPanel
      └─ TermLines          VerticalBox  anchors (0,0), position (160, 100), alignment (0,0), Size To Content = true
         ├─ TermHeader      TextBlock                                                                  [variable]
         ├─ TermSubHeader   TextBlock                                                                  [variable]
         ├─ GapA            Spacer 1 x 50
         ├─ MemRow          SizeBox  Width Override 1280, Height Override 50
         │  └─ MemOverlay   Overlay
         │     ├─ MemLeft   HorizontalBox, slot HAlign Left, VAlign Top
         │     │  ├─ MemLabelText   TextBlock                                                          [variable]
         │     │  ├─ MemGap         Spacer 40 x 1   (two columns)
         │     │  └─ MemCountText   TextBlock                                                          [variable]
         │     └─ MemStatusText     TextBlock, slot HAlign Right, VAlign Top, Justification Right      [variable]
         ├─ GapB            Spacer 1 x 50
         ├─ Row0            SizeBox  Width Override 1280, Height Override 50
         │  └─ Row0Overlay  Overlay
         │     ├─ Row0Text          TextBlock, slot HAlign Left, VAlign Top                            [variable]
         │     └─ Row0Status        TextBlock, slot HAlign Right, VAlign Top, Justification Right      [variable]
         ├─ Row1 ... Row5   same as Row0 (Row1Text/Row1Status ... Row5Text/Row5Status)                 [variables]
```

Rows sit at y = 100 (banner), 150 (copyright), 250 (memory) and 350, 400, ..., 600 (rows 0-5), all x = 160. The block is 1280 x 550. A row's status ends at x = 1440, which is column 64 of the 80-column grid (the grid spans x = 160-1760).

### Text style (every TextBlock)

| Property | Value |
|---|---|
| Font | `Font_Terminal` (VT323), typeface Regular |
| Size | **37.5**, which gives em 50 px, advance 20 px, one font pixel = 2 px. If the field only takes integers, use 38 and accept 20.27 px columns |
| Colour | **white** (1,1,1,1). The phosphor colour comes from the material. Only if the RetainerBox effect is ever disabled should the text be set to #FFB000 directly |
| Letter spacing / line height | 0 / 1.0 |
| Shadow, outline | none (the material does the glow) |
| Auto Wrap | off; Clipping: none |
| Justification | Left; the `*Status` blocks Right |
| Designer preview text | anything (e.g. the mock above). `FadeToBlack`, `BreachBlack` and `BeginTerminal` all call `ClearTerminal` before the widget is seen |

Check the line height with `ui_measure_text` on `TermHeader`. VT323's hhea metrics are ascent 800 and descent 200, so the line should be 50 px, and the SizeBoxes are 50 px to match. If Slate uses the Windows metrics instead (1040 + 240, which gives 64 px), set every Height Override and Gap spacer to 64 so the rows stay on the grid. The layout is 64 x 11 = 704 px tall, which still fits in 1080.

Validate at 1280x720 and 3840x2160 (`ui_validate`, platform pc, strictness standard): at 720p the block is 853 x 367 px, at 4K 2560 x 1100 px.

### Exposed variables the graph needs

`BootBlack`, `TermHeader`, `TermSubHeader`, `MemLabelText`, `MemCountText`, `MemStatusText`, `Row0Text`-`Row5Text`, `Row0Status`-`Row5Status`. `TermRetainer` does not need to be a variable.

## 5. Widget graph (`WBP_Saskarta_BootLog.graph.json`)

The graph has 39 variables, 15 functions, 294 nodes and 333 links. Every animation runs on **widget-owned timers** (`K2_SetTimer` with `Object = self` on the widget). There is no Tick, and the timers exist only while the terminal is on screen.

| Function | Called by | Does |
|---|---|---|
| `SetBlackOpacity(Opacity)` | BPC `Setup` | unchanged |
| `ConfigureTerminal(InCharsPerSecond, InStatusDelay, InStallBudget, InMemDelay, InMemCountTime)` | BPC `Setup` | copies the schedule-shaping timings from the component, so there is one source of numbers |
| `ClearTerminal()` | BPC `FadeToBlack`, `BreachBlack`, `PowerOn`; `BeginTerminal` | clears the 4 timers; blanks all 17 text blocks; `Row = 0`, `bLineOpen = false`, cursor off |
| `BeginTerminal(Header, SubHeader, MemLabel, MemoryKB)` | BPC `PlayBoot` | `ClearTerminal`, prints the banner (`SfxLineFeed`), sets the memory label (blank when `MemoryKB = 0`), starts `MemTimer` (looping `MemTick` 0.03 s) if `MemoryKB > 0`, then the cursor on row 0 and `BlinkTimer` (looping 0.265 s) |
| `TypeLine(Line, Result)` | BPC `BootLineStep` | closes an open line (`FinishLine`), loads the line, `TypeClock = now`, `StallLeft = StallBudget`, then `TypeTimer` (looping `TypeTick` 0.02 s, `bMaxOncePerFrame`) |
| `PrintLine(Line, Result)` | BPC `PlayBoot` (reboot lines 1-2) | the same load, then the whole line and its status at once (`SfxLineFeed`) |
| `TypeStep()` | `TypeTimer` | the stall roll, then `Shown = max(Shown, clamp(trunc((now - TypeClock) x CPS), 0, Len))`, renders `Left(TypeString, Shown) + "_"`. When the line is complete it stops `TypeTimer` and sets `StatusTimer` -> `ShowStatus` after `StatusDelay` |
| `ShowStatus()` | `StatusTimer`, `PrintLine`, `FinishLine` | stamps `[ OK ]`, `[FAIL]` or nothing (`Result` `OK`, `FAIL`, `NONE`) on the row's status block, redraws the row without the cursor, plays `SfxKey<row+1>`, `Row = min(Row + 1, 5)`, cursor on, restarts `BlinkTimer` |
| `FinishLine()` | `TypeLine`, `PrintLine` | stops typing, `Shown = Len`, `ShowStatus` |
| `BlinkCursor()` | `BlinkTimer` | when no line is open, toggles `_` / blank on the current row |
| `CountMemory()` | `MemTimer` | `MemKB = clamp(trunc(elapsed / MemCountTime x Total / Step) x Step, 0, Total)`, shows `Conv_IntToText(MemKB, min 4 digits) + "K"`. At the total it stops, and `StatusTimer` -> `MemoryDone` fires after `StatusDelay` |
| `MemoryDone()` | `StatusTimer` | memory `[ OK ]` + `SfxOkBlip` |
| `SetRow(Content)` | internal | `GetRowText().SetText(Conv_StringToText(Content))` |
| `GetRowText()`, `GetRowStatus()` (pure) | internal | `select` over the six row blocks by `Row` (Hayba cannot author array access) |

Notes for the build:

- **Pure re-evaluation.** Blueprint re-evaluates a pure node for each impure node that reads it. `TypeStep` reads `Shown` through a fresh get after its set, and `BlinkCursor` reads `bCursorOn` after its set. In the component, `BootLineStep` computes `LineHold` into a variable **before** it increments `BootLine`, because the line text it measures is selected by `BootLine`.
- **Literals.** The only string literal is `K` (a `Concat_StrStr` input). Blank text and the empty string come from the variables `BlankText` and `BlankString`, because Hayba refuses empty literals. Status names (`FAIL`, `NONE`) are name literals. The status tokens `[ OK ]` and `[FAIL]` and the cursor `_` are variable defaults on the widget.
- **By-ref inputs.** `Conv_TextToString.InText` is by-ref, and it is always linked (from the function entry, `SelectText` or `Conv_IntToText`), never given a literal.
- **Timers.** Every timer target takes no parameters. Every delay goes through `FClamp(x, 0.01, 60)`. Every handle is cleared before it is set again (`K2_ClearAndInvalidateTimerHandle` fed by a variable get).
- **Six rows.** The terminal has six rows: at most five lines plus the cursor row. `Row` stops at 5, so a sixth line would overwrite row 5. The boot uses four lines, the reboot four, and storyline B18 four.
- **Unconnected on purpose.** `TypeStep.ifDone.else` (still typing), `BlinkCursor.ifOpen.then` (a line is typing, so the cursor stays solid) and `CountMemory.ifFull.else` (still counting).

## 6. Component changes (`BPC_CarrierVision.json`)

The component now has 69 variables, 20 functions, 312 nodes and 369 links. The line text is data: the variables below, never literals in logic.

- **Removed variables:** `Boot1Status`...`Boot4Detail`, `Reboot1Status`...`Reboot4Detail` (16), `LineInterval`, `PowerOnDelay`, `SfxBootTick`, `BlankLine`. If the live asset was already built, delete them in the editor. Stale variables compile, but they mislead.
- **Added data:**

  | Variable | Type | Default |
  |---|---|---|
  | `BootHeader` | text | `HIGHLAND ASSISTIVE CARRIER  UNIT 07  ROM 2.07` |
  | `RebootHeader` | text | `HIGHLAND ASSISTIVE CARRIER  UNIT 07  ROM 2.07  WARM RESTART` |
  | `BootSubHeader` | text | `(C) HIGHLAND ROUTE AUTHORITY` |
  | `MemLabel` | text | `CORE MEMORY TEST` |
  | `BootMemoryKB` / `RebootMemoryKB` | int | 640 / 0 |
  | `Boot1Line`...`Boot4Line` | text | the four B01 lines |
  | `Boot1Result`...`Boot4Result` | name | `OK` |
  | `Reboot1Line`...`Reboot4Line` | text | the four reboot lines |
  | `Reboot1Result` / `Reboot2Result`...`Reboot4Result` | name | `FAIL` / `OK` |

  A result can be `OK`, `FAIL` or `NONE` (no status).
- **Added timings:** the table in section 3.
- **Added sounds:** `SfxTeletype1`-`4`, `SfxDriveSeek`, `SfxCrtOn`, `SfxCrtOff`, `SfxFanHum`.
- **Added state:** `LineHold` (float) and `TermHum` (AudioComponent).
- **New function** `StopHum()`: when `TermHum` is valid, `FadeOut(HumFadeTime, 0)`. `SpawnSound2D` has `bAutoDestroy` on, so the component disposes of itself.
- **`Setup`** also calls `BootLog.ConfigureTerminal(...)` after `SetBlackOpacity(1)`.
- **`FadeToBlack`, `BreachBlack`:** `SetLines(BlankLine, BlankLine)` is replaced by `BootLog.ClearTerminal()`.
- **`PlayBoot(Kind)`:**
  1. Sets `BootKind`, `BootLine = 0`, shows the boot log opaque, and clears `StepTimer` and `LineTimer`.
  2. Sound: `StopHum`, `TermHum = SpawnSound2D(SfxFanHum)`, then plays `SfxCrtOn` and `SfxDriveSeek`.
  3. `BeginTerminal`, with the header chosen by kind and `MemoryKB` 640 or 0.
  4. **Reboot only:** `PrintLine(Reboot1)`, `PrintLine(Reboot2)`, then `BootLine = 2`.
  5. `LineTimer` becomes a **one-shot** -> `BootLineStep` after `FirstLineDelay` or `RebootFirstLineDelay`.
- **`BootLineStep`:**
  1. Selects the line and result by `BootLine` and kind (four `select` nodes plus `SelectText` and `SelectName`).
  2. Calls `BootLog.TypeLine`.
  3. Plays the teletype burst for that index. This is the kept boot-line sound call, now one burst per line instead of a tick.
  4. Sets `LineHold`, then increments `BootLine`.
  5. If there are more lines, re-arms the one-shot `LineTimer` after `LineHold + LineGap`. Otherwise it sets `StepTimer` -> `PowerOn` after `LineHold + FinalHold`.
- **`PowerOn`:** adds `SfxCrtOff` after the contactor and power-on sounds, `BootLog.ClearTerminal` before the collapse, and `StopHum` after it. The MID steps are unchanged.
- **`PlayBoot`'s public signature is unchanged**, so `PC_Saskarta.json` needs no edit.

**Story director note.** The storyline's future `CarrierVision.ShowLogLine(Status, Detail)` (beats B18 and S2) should become `ShowLogLine(Line: text, Result: name)`, a wrapper on `BootLog.TypeLine`. B18 then reads `CARRIER 07 - CRITICAL FAILURE` `[FAIL]`, `HANDOVER - SEARCHING` twice, and `NO CARRIER AVAILABLE` with result `NONE`. `FinishLine` makes voice-timed calls safe even when they come faster than the typing.

## 7. CRT material: `M_UI_CRTTerminal`

`Shaders/CRTTerminalUI.hlsl` is the source of truth. It is the body of the Custom node in a **User Interface** domain material with blend mode **Additive**. It samples the RetainerBox's render target through the texture parameter **`Texture`**, and its output is light added over `BootBlack`. The black and the boot log's opacity fade therefore never depend on the effect, and the effect also multiplies by the widget's vertex alpha.

| Layer | How |
|---|---|
| Phosphor glow | 1 sharp tap + 8 halo taps: four at `GlowRadius` (2.5 px @1080p) on the axes, four on the diagonals at about 1.8 R. The halo is added under the text (`GlowStrength` 0.8) and is not scanlined, so it bleeds across the gaps as on a real tube |
| Scanlines | `ScanlineCount` 540 = one bright and one dark 1080p row per scanline, matched to VT323's 2 px font pixels. Locked to the screen (not the warped image) to avoid moire. Faded out below 1.25 output px per line (sub-720p) |
| Curvature, vignette | Radial barrel bulge `Curvature` 0.045 with an anti-aliased glass edge; `pow(16 u(1-u) v(1-v), Vignette 0.3)` |
| Flicker | 57 Hz sine, depth 0.035, which beats slowly against 60 Hz vsync like mains-fed tubes, plus per-frame hashed noise at half that depth |
| Rolling band | A band 7 % of the screen high, 7 % brighter, rolling down at 0.11 screens/s (one pass every 9 s) |
| Line jitter | 9 decisions per second; 12 % of them slip one 3-scanline band sideways by up to 2 px |
| Tube face | `RasterGlow` 0.012 of the phosphor colour inside the glass, so the rounded screen edge is faintly visible |

Offline compile: the node body, in a mock of UE's Custom-node wrapper (`Texture2DSampleLevel` macro, `TexSampler`), compiles clean under FXC ps_5_0 and DXC ps_6_6 with warnings as errors: about 138 instruction slots and 9 samples. UE's count will differ. The file is ASCII, with no quotes, backslashes or defines, and it does not spell any banned `python_run` names.

### Build the CRT material

Same procedure as `build_vision_material.md`:

1. Substitute the HLSL at the marker. The script has exactly one `__HLSL__`; use a literal replacement:

   ```bash
   node -e "
   const fs = require('fs');
   const py = fs.readFileSync('Tools/GameFlow/build_terminal_material.py', 'utf8');
   const hlsl = fs.readFileSync('Shaders/CRTTerminalUI.hlsl', 'utf8');
   const parts = py.split('__HLSL__');
   if (parts.length !== 2) throw new Error('expected exactly one marker, found ' + (parts.length - 1));
   if (hlsl.includes(\"'''\") || hlsl.includes(String.fromCharCode(92))) throw new Error('HLSL must not contain triple quotes or backslashes');
   fs.writeFileSync('Saved/GameFlow_build_terminal_material.py', parts.join(hlsl));
   "
   ```

   The result is about 17 KB, and it parses as Python (checked offline).
2. Send the file as Hayba `python_run`'s `script`. It creates or rebuilds `/Game/SaskartaGaea/GameFlow/Materials/M_UI_CRTTerminal`:
   - domain UI, blend mode Additive;
   - a Custom node (Float3 output) -> Final Color;
   - inputs `UV` <- TexCoord 0, `Tex` <- TextureObjectParameter `Texture` (default `/Engine/EngineResources/Black`), `Time`, `Fade` <- VertexColor `.A`, `PhosphorColor` <- vector param `.RGB`, and 13 scalar parameters (group `CRTTerminal`).

   It is idempotent and saves only this package.
3. Read the `CRT` lines. You want `nodes=19 (expect 19)`, no `NONE` in `pins`, `failed_links=[]`, `final_is_custom=True`, `phosphor=1.0,0.434,0.0` and `saved=True`.
4. Run Hayba `material_compile` on the asset: `has_errors` false, `saved` true. Record the instruction count.
5. In `WBP_Saskarta_BootLog`, set `TermRetainer`'s Effect Material to it, with Texture Parameter `Texture`.

**If `TexSampler` is rejected** (the name of the generated sampler for a texture-object input can differ by version), replace the nine `TexSampler` uses with `View.MaterialTextureBilinearClampedSampler` and rebuild.

**If Additive UI blending misbehaves**, switch the blend mode to Translucent, add a second Custom output or a `saturate(max(Col.r, Col.g))` path into Opacity, and keep `BootBlack` underneath.

## 8. Sound

`python Tools/Audio/make_terminal_sfx.py` generates everything. It writes 48 kHz mono 16-bit WAVs with fixed seeds, so the files are byte-identical on every run. `--check` re-reads them and checks format, length, peak, DC, edges, the loop seam, the beep frequency and length, the flyback level and fade, and burst density, and re-renders every file to confirm determinism. It has been run: **check passed**. Output: `Saved/GameAudio/Terminal/` plus `manifest.json`, with `ue_folder` = `/Game/SaskartaGaea/Audio/Terminal` and, per sound, `ue_path`, `loop`, `suggested_volume`, `plays` and `sha256`.

There is no instrumental music. Every tone has a physical source: one PC-speaker beep, the CRT's 15.7 kHz flyback, 50 Hz mains and its harmonics, fan blade-pass, and the spindle and stepper buzz.

| Asset | Length | Content | Plays |
|---|---|---|---|
| `SFX_Term_Teletype_Burst_01` | 0.36 | about 55 strikes/s of key and relay chatter with one or two stalls, over a faint print-motor bed | `BPC.BootLineStep`, first-boot line 1 |
| `SFX_Term_Teletype_Burst_02` | 0.60 | same, different seed | `BootLineStep`, first-boot line 2 |
| `SFX_Term_Teletype_Burst_03` | 0.58 | same | `BootLineStep`, line 3 (first boot and reboot) |
| `SFX_Term_Teletype_Burst_04` | 0.42 | same | `BootLineStep`, line 4 (first boot and reboot) |
| `SFX_Term_Key_01`...`06` | 0.12 each | single key: switch tick, shell ring, bottom-out, release | `WBP.ShowStatus`: the status stamp, `Key_<row+1>` |
| `SFX_Term_LineFeed` | 0.35 | platen ratchet (three clicks) + carriage thunk | `WBP.BeginTerminal` (banner) and `WBP.PrintLine` (replayed reboot lines) |
| `SFX_Term_OK_Blip` | 0.12 | the one system beep: 1 kHz square, 0.1 s (measured peak 999.8 Hz) | `WBP.MemoryDone`: memory `[ OK ]`, first boot only |
| `SFX_Term_Drive_Seek` | 1.50 | head-load clack, spindle spin-up whirr, three stepper seeks, single steps, unload clack | `BPC.PlayBoot`, both kinds |
| `SFX_Term_CRT_PowerOn` | 2.20 | relay click, degauss surge (50 Hz + harmonics, coil buzz, shadow-mask ring), static charge, then the quiet 15.734 kHz flyback whine fading out (22 dB under the file RMS; its last 0.3 s is 25 dB under its first second) | `BPC.PlayBoot`, both kinds |
| `SFX_Term_CRT_PowerOff` | 0.50 | snap, flyback dive, zap, low thump, crackle tail | `BPC.PowerOn`: the terminal tube dies as vision takes over |
| `SFX_Term_Fan_Hum_Loop` | 20.0 | circular-filtered fan air, 294 Hz blade-pass hum with periodic wander, 50/100/150/200/300 Hz mains (peak -12 dBFS, seamless) | `BPC.PlayBoot` `SpawnSound2D` -> `TermHum`; `StopHum` fades it at `PowerOn` |

Import (editor agent): `asset_import` each WAV into `/Game/SaskartaGaea/Audio/Terminal/` under its own name.

- Set **Looping** on `SFX_Term_Fan_Hum_Loop`. Even without it, the 20 s file outlasts the longest boot.
- Apply the manifest's `suggested_volume` as each SoundWave's Volume. Everything is peak-normalised, so the beep (0.35) and the keys (0.6) need taming.
- The asset paths are the variable defaults in the two specs, so the sounds must exist before the specs are built. A missing asset only plays nothing.

## 9. Build order (editor agent)

1. Fonts: `FF_VT323` and `Font_Terminal` (section 1).
2. Sounds: run `make_terminal_sfx.py --check`, import, set Looping and volumes (section 8).
3. Material: `M_UI_CRTTerminal` (section 7).
4. Widget `WBP_Saskarta_BootLog`: delete the `SetLines` function, then `BootStatus` and `BootDetail`. Build the tree in section 4, expose the variables, compile, and run `ui_validate` at 720p and 4K.
5. If `BPC_CarrierVision` already exists live, delete the removed variables (section 6).
6. `node Tools/GameFlow/bpgraph.mjs build --reset-graphs` with `PC_Saskarta.json`, `BPC_CarrierVision.json`, `WBP_Saskarta_BootLog.graph.json`, `WBP_Saskarta_Subtitle.graph.json` (and the rest of the set, as README_CarrierVision.md describes). Every asset must compile clean and every link must verify.
7. Playtest (the user presses Play): first boot to control in about 6.1 s; a breach to control in about 3.9 s; `[FAIL]` visible from the first frame of the reboot terminal; no flash between the terminal and the vision.

## 10. Verified offline / not yet verified

- `node Tools/GameFlow/bpgraph.mjs check Tools/GameFlow/specs/*.json`: all nine specs pass.
- A scratch semantic check of both edited specs:
  - every pin name and direction was checked against the UE 5.8 signatures used, and every component-to-widget call against the widget's declared signature;
  - every impure node is reachable, every required input is linked or has a literal, and no node is unused;
  - every variable read or written exists (widget variables included);
  - every timer target is parameterless.

  No errors.
- The timing simulation (section 3) and the glyph check (section 1).
- The HLSL compiles offline (section 7); the material script parses after substitution.
- `make_terminal_sfx.py --check`: passed.
- **Not verified live:**
  - the Hayba build of the graphs;
  - `Conv_IntToText`'s digit pins through Hayba;
  - the RetainerBox + Additive UI material in 5.8;
  - `TexSampler` naming;
  - VT323's line height in Slate;
  - how the terminal looks.

  These belong to the editor build and the playtest.
