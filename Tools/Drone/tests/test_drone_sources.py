"""Source and WAV acceptance checks before the editor import lane."""
import sys
import unittest
import wave
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
import import_drone as drone  # noqa: E402


class DroneSources(unittest.TestCase):
    def test_fbx_rig_animation_and_embedded_images(self):
        drone.audit()

    def test_editor_steps_obey_hayba_filter(self):
        for snippet in (drone.MESH, drone.FINALIZE, drone.TEXTURE,
                        drone.MATERIAL, drone.SOUND, drone.VOICE_IMPORT,
                        drone.READ, drone.VERIFY):
            drone.check_banned(snippet)

    def test_voice_take_is_routed_as_a_distinct_source(self):
        path = drone.ROOT / "SourceArt/Audio/Drone" / (drone.VOICE_NAME + ".wav")
        with wave.open(str(path), "rb") as src:
            self.assertEqual((src.getframerate(), src.getnchannels(), src.getsampwidth()), (48000, 1, 2))
            self.assertGreater(src.getnframes() / src.getframerate(), 2.0)
            self.assertLess(src.getnframes() / src.getframerate(), 3.5)
        self.assertIn('reference.get_editor_property(setting)', drone.VOICE_IMPORT)
        self.assertIn('get_component_bounds(component)', drone.VERIFY)
        self.assertNotIn('imported_bounds', drone.VERIFY)

    def test_audio_format_dc_peak_and_loop_join(self):
        folder = drone.ROOT / "SourceArt/Audio/Drone"
        for name in drone.WAVS:
            with self.subTest(name=name), wave.open(str(folder / (name + ".wav")), "rb") as src:
                self.assertEqual((src.getframerate(), src.getnchannels(), src.getsampwidth()),
                                 (48000, 1, 2))
                x = np.frombuffer(src.readframes(src.getnframes()), dtype="<i2").astype(np.float64) / 32767
                self.assertLess(np.max(np.abs(x)), .5)
                self.assertGreater(np.max(np.abs(x)), .1)
                self.assertLess(abs(x.mean()), .002)
                if name.endswith("RotorLoop"):
                    self.assertEqual(src.getnframes(), 96000)
                    self.assertLess(abs(x[0] - x[-1]), 2 / 32767)


if __name__ == "__main__":
    unittest.main()
