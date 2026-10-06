"""Source wiring checks only; these do not prove Unreal runtime behavior."""
from pathlib import Path
import json
import re
import unittest

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "saskartarad.uproject").is_file())
PRIVATE = ROOT / "Plugins/SaskartaCore/Source/SaskartaCore/Private"


def body(source, signature):
    start = source.index(signature)
    opening = source.index("{", start)
    depth, cursor = 1, opening + 1
    while depth:
        depth += (source[cursor] == "{") - (source[cursor] == "}")
        cursor += 1
    return source[opening:cursor]


class PursuitSourceContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.storm = (PRIVATE / "SaskartaEarlyStorm.cpp").read_text(encoding="utf-8")
        cls.motor = (PRIVATE / "SaskartaMotorResonance.cpp").read_text(encoding="utf-8")
        cls.assist = (PRIVATE / "SaskartaMotorAssist.cpp").read_text(encoding="utf-8")

    def test_movement_and_front_share_live_input_gate(self):
        for method, action in [
            ("bool USaskartaEarlyStormSubsystem::UpdateCarrierForPursuit", "Move->MaxWalkSpeed ="),
            ("void USaskartaEarlyStormSubsystem::Tick", "Carrier->AddMovementInput"),
            ("void USaskartaEarlyStormSubsystem::Poll", "FrontRoadM +="),
        ]:
            with self.subTest(method=method):
                function = body(self.storm, method)
                gate = function.index("!Motor->CanAcceptInput()")
                self.assertLess(gate, function.index(action))
                blocked = body(function[gate:], "")
                self.assertIn("ConsumeMovementInputVector", blocked)
                self.assertIn("StopMovementImmediately", blocked)
                self.assertIn("return", blocked)
                if "UpdateCarrier" not in method:
                    self.assertIn("LastPollS = World->GetTimeSeconds()", blocked)

    def test_gate_covers_menus_prompts_cinematic_and_viewport_focus(self):
        gate = body(self.motor, "bool USaskartaMotorResonanceSubsystem::ControlsAvailable")
        for signal in ["World->IsPaused()", "DriveFlow", "IsCinematicActive()", "IsHoldingInput()",
                       "IsPromptActive()", "Map->IsOpen()", "HasViewportFocus()", "SessionPawn.Get()"]:
            self.assertIn(signal, gate)
        focus = body(self.motor, "bool USaskartaMotorResonanceSubsystem::HasViewportFocus")
        self.assertIn("FSlateApplication::Get().IsActive()", focus)
        tick = body(self.motor, "void USaskartaMotorResonanceSubsystem::Tick")
        self.assertIn("bOwnsMoveLock", tick)
        self.assertIn("!PC->IsMoveInputIgnored()", tick)
        self.assertIn("PC->SetIgnoreMoveInput(true)", tick)

    def test_pursuit_hook_precedes_automatic_hill_assist_and_power_limits(self):
        update = body(self.assist, "bool USaskartaMotorAssistSubsystem::UpdateCarrier")
        self.assertLess(update.index("Storm->UpdateCarrierForPursuit"), update.index("Motor->StepCarrier"))
        # Latest playtest rule: empty fuel stops even an automatically driven
        # pursuit. The normal positive-fuel caps still follow the storm hook.
        empty = update.split("Power && Power->IsLimp()", 1)[1].split("// The pursuit", 1)[0]
        self.assertIn("Carrier->ConsumeMovementInputVector()", empty)
        self.assertIn("ApplyDriveLimits(Carrier, 0.f, false)", empty)
        self.assertIn("Motor->Logic.Reset()", empty)
        self.assertIn("return true;", empty)  # Blocks the Blueprint anti-stuck launch.
        self.assertLess(update.index("Power && Power->IsLimp()"), update.index("Storm->UpdateCarrierForPursuit"))
        self.assertLess(update.index("Storm->UpdateCarrierForPursuit"), update.rindex("ApplyDriveLimits"))
        branch = body(update, "if (Storm->UpdateCarrierForPursuit")
        self.assertIn("return true", branch)
        self.assertIn("Motor->Logic.Reset()", branch)
        ordinary = body(self.assist, "bool USaskartaMotorAssistSubsystem::StepCarrier")
        self.assertIn("Resonance->IsActive()", ordinary)
        for removed in ["BindKey", "PlaySound2D", "CreateWidget", "Move->Velocity +=", "LaunchCharacter"]:
            self.assertNotIn(removed, self.assist)

    def test_vehicle_audio_allows_only_exact_unsuppressed_pursuit(self):
        gate = body(self.assist, "bool USaskartaMotorAssistSubsystem::ShouldPlayDriveAudio")
        for signal in ["World->IsPaused()", "PC->GetPawn() != Carrier", "DriveFlow", "IsCinematicActive()",
                       "IsHoldingInput()", "IsPromptActive()", "OwnsPursuitCarrier(Carrier)", "Motor->CanAcceptInput()"]:
            self.assertIn(signal, gate)
        self.assertIn("!PC->IsMoveInputIgnored() && !(Motor && Motor->IsActive())", gate)
        header = (PRIVATE.parent / "Public/SaskartaEarlyStorm.h").read_text(encoding="utf-8")
        owner = body(header, "bool OwnsPursuitCarrier")
        for guard in ["bChasing", "!bFailed", "bOwnsMoveLock", "DriveCarrier.Get() == Carrier"]:
            self.assertIn(guard, owner)
        spec = json.loads((ROOT / "Tools/GameFlow/specs/BP_Saskarta_Carrier.json").read_text(encoding="utf-8"))
        audio = next(graph for graph in spec["graphs"] if graph["graph"] == "CarrierAudioStep")
        calls = {node.get("call", "") for node in audio["nodes"].values()}
        self.assertIn("ShouldPlayDriveAudio", calls)
        self.assertNotIn("IsMoveInputIgnored", calls)

    def test_tether_reboot_preserves_only_same_pawn_pursuit_and_stays_suppressed(self):
        tick = body(self.motor, "void USaskartaMotorResonanceSubsystem::Tick")
        self.assertIn('Logic.Mode == FSaskartaMotorResonanceLogic::EMode::Pursuit && Flow == TEXT("Rebooting")', tick)
        self.assertIn("!bRecoveringPursuit", tick)
        self.assertIn("PC->GetPawn() != SessionPawn.Get()", tick)
        self.assertIn("Logic.Advance(DeltaTime, !bAllowed)", tick)
        gate = body(self.motor, "bool USaskartaMotorResonanceSubsystem::ControlsAvailable")
        self.assertIn("SaskartaResonance::DriveFlow(Runner->GetFlowState())", gate)
        self.assertNotIn("Rebooting", gate)
        # This recovery exemption relies on the authored reboot keeping the pawn.
        spec = json.loads((ROOT / "Tools/GameFlow/specs/PC_Saskarta.json").read_text(encoding="utf-8"))
        graphs = {graph["graph"]: graph for graph in spec["graphs"]}
        for name in ["HandleBreach", "HandleBlackout", "TryRespawn", "HandleVisionOnline", "TryGround"]:
            calls = {node.get("call", "") for node in graphs[name]["nodes"].values()}
            self.assertFalse(calls & {"Possess", "UnPossess", "DestroyActor", "K2_DestroyActor", "SpawnActor"}, name)
        self.assertIn(["pawn.ReturnValue", "teleport.self"], graphs["TryRespawn"]["links"])
        self.assertEqual(graphs["TryGround"]["defaults"]["toPlaying.FlowState"], "Playing")

    def test_releases_pass_through_and_rewards_use_existing_power(self):
        handler = body(self.motor, "bool USaskartaMotorResonanceSubsystem::HandleKey")
        self.assertLess(handler.index("if (bRepeat)"), handler.index("Logic.Input"))
        self.assertIn("return bAllowed && bDown", handler)
        reward = body(self.motor, "void USaskartaMotorResonanceSubsystem::ApplyReward")
        self.assertIn("Logic.TakeChargeReward()", reward)
        self.assertIn("Power->GetCharge()", reward)
        self.assertIn("Power->SetCharge(FMath::Min(100.f, Before + Reward))", reward)

    def test_tuning_lock_and_pursuit_attempt_are_owned_and_reset(self):
        begin = body(self.motor, "void USaskartaMotorResonanceSubsystem::BeginTuning")
        end = body(self.motor, "void USaskartaMotorResonanceSubsystem::End()")
        for entry in ["Power->CanRest()", "IsMoveInputIgnored()", "SetIgnoreMoveInput(true)",
                      "bOwnsMoveLock = true", "SetRestActivityOpen(true)"]:
            self.assertIn(entry, begin)
        for cleanup in ["if (bOwnsMoveLock)", "SetIgnoreMoveInput(false)", "SetRestActivityOpen(false)",
                        "bOwnsMoveLock = false", "Logic.End()"]:
            self.assertIn(cleanup, end)
        retry = body(self.motor, "void USaskartaMotorResonanceSubsystem::BeginPursuit")
        self.assertLess(retry.index("End();"), retry.index("Begin("))

    def test_chase_restores_character_movement_configuration(self):
        begin = body(self.storm, "void USaskartaEarlyStormSubsystem::BeginChase")
        end = body(self.storm, "void USaskartaEarlyStormSubsystem::ReleaseDrive")
        for saved in ["PreviousMaxSpeed", "PreviousAcceleration", "PreviousBraking", "bPreviousOrientToMovement"]:
            self.assertIn(saved, begin)
            self.assertIn(saved, end)

    def test_recovered_pursuit_restores_fuel_before_movement_or_success(self):
        refill = body(self.storm, "bool USaskartaEarlyStormSubsystem::RestoreRecoveryFuel")
        for guard in ["PursuitCheckpoint->CheckpointId != SaskartaEarlyStorm::PursuitCheckpointId",
                      "Power->GetCore().Tuning.LimpExitPercent", "FMath::Max(Before, Minimum)",
                      "Power->SetCharge", "!Power->IsLimp()", "Power->GetCharge() >= Minimum"]:
            self.assertIn(guard, refill)
        self.assertNotIn("SaveGameToSlot", refill)  # original checkpoint remains intact
        begin = body(self.storm, "void USaskartaEarlyStormSubsystem::BeginChase")
        self.assertIn("if (bRetry && !RestoreRecoveryFuel(bRefueled)) return;", begin)
        self.assertLess(begin.index("RestoreRecoveryFuel"), begin.index("Motor->BeginPursuit()"))
        self.assertLess(begin.index("RestoreRecoveryFuel"), begin.index("SetIgnoreMoveInput(true)"))
        rescue = body(self.storm, "void USaskartaEarlyStormSubsystem::CompleteRescue")
        self.assertLess(rescue.index("RestoreCheckpointSnapshot"), rescue.index("RestoreRecoveryFuel"))
        self.assertLess(rescue.index("RestoreRecoveryFuel"), rescue.index("bRescueRestored = true"))
        self.assertIn("SetSuccessful(bRefueled)", rescue)
        widget = (PRIVATE / "SaskartaPackageRescue.cpp").read_text(encoding="utf-8")
        self.assertIn("Recovery fuel reserve restored", widget)

    def test_normal_zero_fuel_stays_stopped_and_is_never_refilled(self):
        self.assertEqual(self.storm.count("RestoreRecoveryFuel(bRefueled)"), 2)
        tick = body(self.storm, "void USaskartaEarlyStormSubsystem::Tick")
        empty = body(tick, "Power && Power->IsLimp())")
        self.assertIn("DriveSpeedCmS = 0.f", empty)
        self.assertIn("return;", empty)
        self.assertNotIn("SetCharge", empty)
        begin = body(self.storm, "void USaskartaEarlyStormSubsystem::BeginChase")
        fresh = body(begin, "if (!bRetry)")
        self.assertNotIn("RestoreRecoveryFuel", fresh)
        self.assertNotIn("SetCharge", fresh)

    def test_proximity_rattle_is_async_retained_and_once_per_chase(self):
        begin = body(self.storm, "void USaskartaEarlyStormSubsystem::BeginChase")
        play = body(self.storm, "void USaskartaEarlyStormSubsystem::TryPlayProximityRattle")
        clear = body(self.storm, "void USaskartaEarlyStormSubsystem::ClearProximityRattle")
        self.assertIn("RequestAsyncLoad(SaskartaEarlyStorm::ProximityRattlePath", begin)
        self.assertIn("ClearProximityRattle();", begin)
        for guard in ["!Motor->CanAcceptInput()", "bProximityRattleFired", "FrontGapM <= 0.f",
                      "ProximityRattleGapM", "HasLoadCompleted()", "GetLoadedAsset()"]:
            self.assertIn(guard, play)
        self.assertLess(play.index("if (!ProximityRattleSound) return"), play.index("bProximityRattleFired = true"))
        self.assertLess(play.index("bProximityRattleFired = true"), play.index("CreateSound2D"))
        for call in ["LoadSynchronous(", "TryLoad(", "LoadObject<", "PlayNamedSfx("]:
            self.assertNotIn(call, play)
        self.assertIn("bIsUISound = false", play)
        self.assertNotIn("SoundClassOverride", play)
        self.assertIn("CancelHandle()", clear)
        self.assertIn("ProximityRattleLoad.Reset()", clear)
        self.assertIn("ProximityRattleSound = nullptr", clear)
        self.assertIn("bProximityRattleFired = false", clear)

    def test_proximity_rattle_stops_on_pause_suppression_and_end(self):
        tick = body(self.storm, "void USaskartaEarlyStormSubsystem::Tick")
        paused = body(tick, "if (!bChasing || World->IsPaused())")
        suppressed = body(tick, "if (!Motor || !Motor->CanAcceptInput())")
        self.assertIn("StopProximityRattle();", paused)
        self.assertIn("StopProximityRattle();", suppressed)
        end = body(self.storm, "void USaskartaEarlyStormSubsystem::EndChase")
        self.assertIn("ClearProximityRattle();", end)
        stop = body(self.storm, "void USaskartaEarlyStormSubsystem::StopProximityRattle")
        self.assertIn("ProximityRattleAudio->Stop()", stop)
        self.assertNotIn("bProximityRattleFired = false", stop)  # resume cannot replay the cue

    def test_wreck_restore_uses_resident_carrier_independent_of_possession(self):
        rebuild = body(self.storm, "void USaskartaEarlyStormSubsystem::RebuildWrecks")
        self.assertIn("FindObject<UClass>", rebuild)
        self.assertIn("BP_Saskarta_Carrier.BP_Saskarta_Carrier_C", rebuild)
        self.assertIn("GetActorOfClass(World, CarrierClass)", rebuild)
        self.assertNotIn("GetPawn()", rebuild)
        self.assertNotIn("LoadClass", rebuild)
        self.assertNotIn("LoadObject", rebuild)
        self.assertLess(rebuild.index("WreckActors.Reset()"), rebuild.index("if (!Carrier) return"))

    def test_intro_uses_actual_playback_clock_and_visual_only_work(self):
        intro = body(self.storm, "void USaskartaEarlyStormSubsystem::UpdateIntroFront")
        self.assertIn("GetActiveCinematicId() != SaskartaEarlyStorm::StormCine", intro)
        self.assertLess(intro.index("World->IsPaused()"), intro.index("GetCinematicPlaybackSeconds()"))
        self.assertIn("!FMath::IsFinite(PlaybackS) || PlaybackS < 0.f", intro)
        self.assertIn("if (IntroCarrierRoadM < 0.f) IntroCarrierRoadM = RoadM", intro)
        self.assertIn("FrontRoadM = IntroCarrierRoadM - StagedGapM", intro)
        self.assertIn("ApplyWeather(FrontGapM)", intro)
        for forbidden in ["BeginPursuit", "SetPursuitGap", "FailPursuit", "AddMovementInput", "UpdateStormPanic", "RequestedAtS"]:
            self.assertNotIn(forbidden, intro)
        runner = (PRIVATE / "SaskartaEventRunner.cpp").read_text(encoding="utf-8")
        clock = body(runner, "float USaskartaEventRunner::GetCinematicPlaybackSeconds")
        self.assertIn("CinePhase == ESaskartaCinePhase::Playing ? GetCinematicTimeS() : -1.f", clock)

    def test_intro_ease_has_authored_duration_and_same_handoff_gap(self):
        def constant(name):
            return float(re.search(r"constexpr float " + name + r" = ([\d.]+)f;", self.storm)[1])
        duration, start, end = (constant(name) for name in ["IntroDurationS", "IntroGapM", "InitialGapM"])
        story = json.loads((ROOT / "docs/story/story-events.json").read_text(encoding="utf-8"))
        self.assertEqual(duration, story["cinematics"]["CIN_04_DUST_FRONT"]["duration_s"])
        self.assertEqual((start, end), (70., 65.))
        intro = body(self.storm, "void USaskartaEarlyStormSubsystem::UpdateIntroFront")
        self.assertIn("FMath::Clamp(PlaybackS / SaskartaEarlyStorm::IntroDurationS, 0.f, 1.f)", intro)
        self.assertIn("Alpha * Alpha * (3.f - 2.f * Alpha)", intro)
        self.assertIn("FMath::Lerp(SaskartaEarlyStorm::IntroGapM, SaskartaEarlyStorm::InitialGapM, Ease)", intro)
        def gap(seconds):
            alpha = min(1., max(0., seconds / duration))
            ease = alpha * alpha * (3. - 2. * alpha)
            return start + (end - start) * ease
        samples = [gap(i / 100.) for i in range(0, 701)]
        self.assertEqual((gap(0), gap(3), gap(6), gap(60)), (70., 67.5, 65., 65.))
        self.assertTrue(all(65. <= value <= 70. for value in samples))
        self.assertTrue(all(a >= b for a, b in zip(samples, samples[1:])))
        begin = body(self.storm, "void USaskartaEarlyStormSubsystem::BeginChase")
        self.assertIn("FrontGapM = SaskartaEarlyStorm::InitialGapM", begin)

    def test_intro_cleanup_and_handback_are_separate_from_playable_pursuit(self):
        tick = body(self.storm, "void USaskartaEarlyStormSubsystem::Tick")
        self.assertLess(tick.index("if (bIntroActive)"), tick.index("if (!bChasing || World->IsPaused())"))
        intro_tick = body(tick, "if (bIntroActive)")
        self.assertIn("UpdateStormPanic(0.f, false, false)", intro_tick)
        self.assertIn("UpdateIntroFront();", intro_tick)
        self.assertIn("return;", intro_tick)
        finished = body(self.storm, "void USaskartaEarlyStormSubsystem::OnCinematicFinished")
        self.assertLess(finished.index("bIntroActive = false"), finished.index("BeginChase()"))
        self.assertIn("if (!bChasing) EndChase()", finished)
        end = body(self.storm, "void USaskartaEarlyStormSubsystem::EndChase")
        self.assertIn("bIntroActive = false", end)
        self.assertIn("IntroCarrierRoadM = -1.f", end)
        self.assertIn("FrontActor->Destroy()", end)
        intro = body(self.storm, "void USaskartaEarlyStormSubsystem::UpdateIntroFront")
        for stop in ['TEXT("Title")', 'TEXT("Loading")', 'TEXT("Human")', "EndChase()"]:
            self.assertIn(stop, intro)

    def test_panic_defers_to_input_and_story_without_cutting_programme(self):
        poll = body(self.storm, "void USaskartaEarlyStormSubsystem::Poll")
        playing = "Runner->UpdateStormPanic(FrontGapM, true, Motor->IsInputWarningActive())"
        self.assertIn(playing, poll)
        self.assertLess(poll.index("!Motor->CanAcceptInput()"), poll.index(playing))
        runner = (PRIVATE / "SaskartaEventRunner.cpp").read_text(encoding="utf-8")
        panic = body(runner, "void USaskartaEventRunner::UpdateStormPanic")
        for signal in ["World->IsPaused()", "IsCinematicActive()", "IsHoldingInput()", "bPromptActive",
                       "bInputWarningActive", "LastStormPanicEndS + IntervalS", "Candidate == LastStormPanicLine",
                       "TryPlayAuxCarrierLine", "ShowLineSubtitle"]:
            self.assertIn(signal, panic)
        auxiliary = body(runner, "bool USaskartaEventRunner::TryPlayAuxCarrierLine")
        self.assertIn("bHasRunning || Queue.Num() > 0 || PendingKeepLines.Num() > 0", auxiliary)
        self.assertIn("FSaskartaEventLogic::CanStartAuxLine", auxiliary)
        self.assertLess(auxiliary.index("OnStoryLine.Broadcast"), auxiliary.index("BroadcastBusy(true"))
        self.assertIn("OnStoryLine.Broadcast(LineId, NAME_None, true", auxiliary)
        motor_header = (PRIVATE.parent / "Public/SaskartaMotorResonance.h").read_text(encoding="utf-8")
        warning = body(motor_header, "bool IsInputWarningActive")
        self.assertIn("Logic.BalanceVisible()", warning)
        self.assertIn("Logic.NextBeatS - Logic.ElapsedS <= 0.35", warning)
        own_stop = body(runner, "void USaskartaEventRunner::StopStormPanicLine")
        self.assertLess(own_stop.index('StartsWith(TEXT("CV_STORM_PANIC_"))'), own_stop.index("VoiceComp->Stop()"))
        station = (PRIVATE / "SaskartaRadioStation.cpp").read_text(encoding="utf-8")
        busy = body(station, "void USaskartaRadioStation::HandleStoryBusy")
        continuity = body(busy, "if (const USaskartaEventRunner* R = Runner.Get(); R && R->ShouldKeepStationPlaying())")
        self.assertIn("break;", continuity)
        self.assertNotIn("InterruptSlot", continuity)
        fx = (PRIVATE / "SaskartaRadioFX.cpp").read_text(encoding="utf-8")
        carrier = fx.split("case ESaskartaRadioLineKind::Carrier:", 1)[1].split("case ESaskartaRadioLineKind::Archive:", 1)[0]
        self.assertIn("Step.bDuck = true", carrier)
        self.assertNotIn("Step.bInterrupt = true", carrier)
        self.assertNotIn("Step.bForcedOn = true", carrier)
        self.assertTrue(json.loads((ROOT / "docs/story/story-events.json").read_text(encoding="utf-8"))
                        ["cinematics"]["CIN_04_DUST_FRONT"]["keep_station_playing"])


if __name__ == "__main__":
    unittest.main()
