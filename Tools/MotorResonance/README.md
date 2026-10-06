# Shared motor timing

`USaskartaMotorResonanceSubsystem` implements the same motor interaction for a
stationary recharge lesson and the automatic dust pursuit. It owns the HUD and
key events. EarlyStorm owns road following, dust distance, rewind and wrecks.

## Runtime contract

- `BeginTuning()` requires the possessed carrier to be stationary, power to report
  rest, and Playing/Carrier flow without pause, map, prompt, cinematic or input
  hold. The lesson owns one movement lock and enables passive rest charging.
- `EndTuning()` and normal lesson completion release exactly that movement lock.
  Tab/View is the existing RouteLog bridge entry/exit. Camera input stays free.
- `BeginPursuit()` starts a fresh sequence, including a fresh retry. `EndPursuit()`
  clears it. No movement lock is taken by motor pursuit; EarlyStorm owns that.
- `GetDriveMultiplier()` is bounded 0.65–1.5, neutral 1 while blocked/inactive.
  `SetPursuitGap(float)` updates the visible distance. `IsActive()` and `IsTuning()`
  report mode. `CanAcceptInput()` is the shared live suppression gate: EarlyStorm
  must freeze **both carrier and dust** while it returns false, with no catch-up.
- Ordinary uphill MotorAssist yields while resonance is active. The pursuit hook
  in `UpdateCarrier` returns before ordinary pulse and limp/turbo limits.

## Input and timing

E / gamepad bottom face button pulses every 1 second in pursuit, 1.2 seconds in
the lesson. A/D / D-pad left/right provide one alternating correction halfway
between every fourth pair of beats. Both controls use key-down/up edges; held
keys, OS repeats and multiple attempts cannot earn repeated rewards. Release
events continue to PlayerInput so pre-existing steering cannot remain stuck.

The lane's green region shows the ±220 ms accepted beat interval, with its mark
at exact beat time. Perfect timing is ±85 ms. Balance accepts ±250 ms, with a
700 ms preparation cue. A just-late tap does not consume or penalize the next cue.
Visible feedback distinguishes perfect, good, early, late, missed and wrong-side
inputs. Existing local BootTick, ServoUp and steering servo sounds supply cues.

The lesson ends after 12 beats, about 14.7 seconds. Each perfect/good beat adds
2.5/1.5 percentage points and each balance adds 1, at most 33 points. Rewards call
`USaskartaPowerSubsystem::SetCharge(GetCharge() + reward)` capped at 100; the HUD
reports the amount actually delivered. Normal passive charging continues.

Pause, cinematics, prompts, map, non-playable flow and loss of game-viewport focus
suppress scoring and hide the HUD. The timing clock freezes; menu-held keys must
be released before scoring resumes. A single render delta above half a second
also freezes timing instead of generating catch-up misses.

## Verification

```powershell
python Tools/MotorResonance/run_smoke.py
python -m unittest discover -s Tools/MotorResonance -p test_pursuit_contract.py
```

This compiles the actual engine-free timing header using the installed MSVC and
replays timing boundaries, repeat/release behavior, suppression, balance windows,
reward draining, lesson completion, multiplier bounds and frame-rate equivalence.
It starts no editor and writes compilation outputs only to a temporary directory.
The separate source contract suite checks the shared motor/movement/dust gate,
input-release forwarding, power API, pursuit hook ordering and movement-setting
restoration. These are wiring checks, not simulated gameplay or native input tests.

The integrated Unreal build and live checks remain required: title-to-game flow,
stationary entry/exit and delivered charge; keyboard/gamepad beat response;
pause/cinematic/prompt/map/focus suppression; synchronized pursuit freeze/resume;
automatic rewind resetting the sequence; readable 1080p HUD and unchanged uphill
assist after exit. Standalone logic tests do not establish native UI/input success.
