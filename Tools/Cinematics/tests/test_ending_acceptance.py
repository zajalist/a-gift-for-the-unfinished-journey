"""Only exercise offline preparation; no Unreal/editor connection is made."""
import ast
import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location('prepare_ending_acceptance', ROOT / 'Tools/Cinematics/prepare_ending_acceptance.py')
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class EndingAcceptancePreparation(unittest.TestCase):
    def test_packet_read_only_and_all_probes_bounded_metadata(self):
        audit = MODULE.PACKET / 'preparation-audit.json'
        before = hashlib.sha256(audit.read_bytes()).hexdigest()
        with tempfile.TemporaryDirectory() as temp, patch.object(MODULE, 'OUT', Path(temp)), contextlib.redirect_stdout(io.StringIO()):
            MODULE.prepare()
            manifest = json.loads((Path(temp) / 'acceptance-manifest.json').read_text())
            self.assertEqual(len(manifest['scripts']), 6)
            self.assertEqual(manifest['original_audit_sha256'], before)
            for name, digest in manifest['scripts'].items():
                path = Path(temp) / name
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest)
                source = path.read_text()
                tree = ast.parse(source)
                compile(tree, name, 'exec')
                attrs = {n.func.attr for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
                self.assertFalse(any(a.startswith(('set_', 'add_', 'remove_', 'save_', 'spawn_', 'play', 'import_', 'compile')) for a in attrs), (name, attrs))
                self.assertIn('ENDING_ACCEPTANCE_FAIL', source)
                self.assertIn('ACCEPTANCE_OK', source)
            for relative, digest in manifest['inputs'].items():
                self.assertEqual(hashlib.sha256((MODULE.PACKET / relative).read_bytes()).hexdigest(), digest)
        self.assertEqual(hashlib.sha256(audit.read_bytes()).hexdigest(), before)

    def test_hatch_source_metadata_and_head_regression(self):
        self.assertIn("get_editor_property('data_model_interface')", MODULE.HATCH)
        self.assertIn('len(tracks) == 42', MODULE.HATCH)
        self.assertIn("['Neck', 'Head']", MODULE.HATCH)
        self.assertNotIn('AnimationLibrary.get_num_frames', MODULE.HATCH)
        self.assertIn('str(n).casefold()', MODULE.HATCH)

    def test_sequence_camera_anchor_and_complete_body_checks(self):
        self.assertIn('cut.get_camera_binding_id()', MODULE.CINEMATIC)
        self.assertIn('attach.get_constraint_binding_id()', MODULE.CINEMATIC)
        self.assertIn('get_start_frame_seconds()', MODULE.CINEMATIC)
        self.assertIn('sequence animation full head scale', MODULE.CINEMATIC)
        self.assertIn("'animation section timing'", MODULE.CINEMATIC)
        self.assertIn("'body anchor stays uncut'", MODULE.CINEMATIC)

    def test_audio_and_camera_probes_do_not_invoke_runtime(self):
        self.assertIn('sound_class_object', MODULE.SFX)
        self.assertIn("looping == item['looping']", MODULE.SFX)
        self.assertIn('PRIME_ON_LOAD', MODULE.SFX)
        self.assertIn('get_all_actors_of_class', MODULE.TRAVELLER)
        self.assertNotIn('ConfigureCamera(', MODULE.TRAVELLER)
        self.assertNotIn('get_editor_property(\'controller\')', MODULE.CINEMATIC)


if __name__ == '__main__':
    unittest.main()
