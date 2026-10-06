import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = ROOT / "Tools" / "GameFlow" / "patch_cin01_skip.py"
SPEC = importlib.util.spec_from_file_location("patch_cin01_skip", MODULE_PATH)
PATCHER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PATCHER)


class Cin01SkipPatchTests(unittest.TestCase):
    def test_generated_chunks_only_target_cin01_skip_rule_and_keep_one_second_hold(self):
        policy = PATCHER.load_policy()
        self.assertEqual(policy, {
            "asset": "/Game/SaskartaGaea/Story/DA_Saskarta_Story",
            "cinematic": "CIN_01_DIRECTIVE",
            "skip_min_s": 1.0,
        })
        chunks = PATCHER.chunks(policy)
        self.assertEqual(set(chunks), {"10_apply.py", "20_verify.py", "90_save.py"})
        self.assertIn("unreal.SaskartaSkipRule.HOLD_ALWAYS", chunks["10_apply.py"])
        self.assertIn("before_unowned", chunks["10_apply.py"])
        self.assertIn("keep_fields", chunks["10_apply.py"])
        self.assertIn("save_loaded_asset(story, False)", chunks["90_save.py"])
        for name, source in chunks.items():
            compile(source, name, "exec")


if __name__ == "__main__":
    unittest.main()
