"""Offline source/asset contracts; runtime mixing still needs the real UE build/listen."""
from pathlib import Path
import re
import unittest
import wave


ROOT = Path(__file__).resolve().parents[2]
CPP = ROOT / "Plugins/SaskartaCore/Source/SaskartaCore/Private/SaskartaMotorResonanceAudio.cpp"
HEADER = ROOT / "Plugins/SaskartaCore/Source/SaskartaCore/Public/SaskartaMotorResonanceAudio.h"


class MotorAudioContract(unittest.TestCase):
    def setUp(self):
        self.code = CPP.read_text(encoding="utf-8")

    def test_every_audio_path_is_an_existing_local_asset(self):
        paths = re.findall(r'FSoftObjectPath\(TEXT\("(/Game/[^\"]+)"\)\)', self.code)
        self.assertEqual(len(paths), 5)
        for path in paths:
            file = ROOT / "Content" / (path.removeprefix("/Game/").split(".")[0] + ".uasset")
            self.assertTrue(file.is_file(), path)

    def test_only_async_prefetch_and_resident_resolution(self):
        self.assertIn("RequestAsyncLoad(Requested, FStreamableDelegate())", self.code)
        self.assertIn("HasLoadCompleted()", self.code)
        self.assertIn("ResolveObject()", self.code)
        for forbidden in ("LoadObject<", "LoadSynchronous", "TryLoad", "BindLambda", "CreateLambda"):
            self.assertNotIn(forbidden, self.code)
        self.assertIn("LoadHandle->CancelHandle()", self.code)

    def test_authored_mix_and_radio_are_untouched(self):
        for forbidden in ("NotifyPaused", "SetSoundMix", "SetBaseSoundMix", "SetSoundClass",
                          "SetSubmix", "SetVolumeMultiplier(0.f)", "PlayNamedSfx"):
            self.assertNotIn(forbidden, self.code)
        self.assertNotIn("ServoUp", self.code)  # Old2.4s feedback stacked on1s beats.

    def test_source_has_bounded_owned_voices(self):
        header = HEADER.read_text(encoding="utf-8")
        self.assertEqual(len(re.findall(r"TObjectPtr<UAudioComponent>", header)), 4)
        for voice in ("WarningVoice", "ResultVoice", "FlywheelVoice"):
            self.assertIn(f"StopVoice({voice});", self.code)
        self.assertIn("StopVoice(Voice);", self.code)
        self.assertIn("Voice->DestroyComponent();", self.code)

    def test_pause_consumes_current_cues_and_feedback(self):
        blocked = self.code.split("if (!bAudible)", 1)[1].split("// Balance warnings", 1)[0]
        for required in ("Silence();", "WarnedBeat = Core.CompletedBeats", "WarnedBalance = Core.BalanceIndex",
                         "LastFeedbackUntil = Core.FeedbackUntilS", "return;"):
            self.assertIn(required, blocked)
        self.assertIn("Core.bSuppressed", self.code)
        self.assertIn("!World || World->IsPaused()", self.code)

    def test_anticipation_is_before_the_scoring_window(self):
        self.assertIn("BeatLeadS = 0.35", self.code)
        self.assertIn("BalanceLeadS = 0.7", self.code)
        self.assertIn("UntilBeat > FSaskartaMotorResonanceLogic::GoodWindowS", self.code)
        self.assertIn("UntilBalance > FSaskartaMotorResonanceLogic::BalanceWindowS", self.code)
        self.assertIn("Core.WantsLeft() ? ESound::LeftValve : ESound::RightValve", self.code)

    def test_same_feedback_is_not_replayed_by_key_then_tick(self):
        self.assertIn("Core.FeedbackUntilS == LastFeedbackUntil && Core.Feedback == LastFeedback", self.code)
        self.assertIn("PlayFeedback(Core);", self.code)
        self.assertIn("case E::Miss:", self.code)
        self.assertIn("case E::WrongSide:", self.code)

    def test_flywheel_gain_is_applied_once(self):
        self.assertIn("const float Volume = 0.025f + 0.03f * Effort", self.code)
        self.assertIn("FlywheelVoice->FadeIn(0.12f, 1.f)", self.code)
        self.assertNotIn("FadeIn(0.12f, Volume)", self.code)

    def test_selected_oneshots_are_short(self):
        files = [ROOT / "Saved/GameFlowAudio/SFX_Carrier_Contactor.wav"]
        files += [ROOT / "Saved/GameAudio/CarrierVehicle" / ("SFX_Carrier_" + name + ".wav")
                  for name in ("Mast_Tick_01", "Steer_Servo_L_01", "Steer_Servo_R_01")]
        if not all(path.is_file() for path in files):
            self.skipTest("Optional authored WAV source cache is absent")
        for path in files:
            with wave.open(str(path)) as sample:
                self.assertLessEqual(sample.getnframes() / sample.getframerate(), .321, path.name)


if __name__ == "__main__":
    unittest.main()
