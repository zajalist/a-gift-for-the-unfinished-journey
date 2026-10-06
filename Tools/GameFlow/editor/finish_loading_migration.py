"""Finalize one observed pre-reset Loading type migration; never rebuild graphs.

Original installer, journal and graph reports stay byte-for-byte intact. The
only historical exception is the exact observed ProgressFill Image -> Border
skeleton warning. Current independent compiles and saves must still be clean.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path

import install_loading_presentation as original
from install_ending_folder import EditorConnection, ROOT, digest, package_file, require_writable, save_state

EXPECTED_PLAN = '83bc84b6838617a6f5353c80ae67e6a0f65e6659951b06dfddedc65b1c689bf0'
WARNING = ("skeleton compile failed (graphs will be reset): Progress Fill  of type Image Object Reference "
           "doesn't match the property ProgressFill of type Border Object Reference")
REPORT = original.JOURNAL.with_name('install-v1-graphs.json')
STDERR = REPORT.with_suffix(REPORT.suffix + '.err')
RECOVERY = original.JOURNAL.with_name('finalization-v2.json')


def validate_observed_report(report):
    """Remove the one historical warning in memory, then use the strict validator."""
    checked = copy.deepcopy(report)
    loading = [a for a in checked.get('assets', []) if a.get('asset') == original.ASSET]
    if len(loading) != 1 or loading[0].get('warnings') != [WARNING]:
        raise ValueError('Report does not contain exactly the observed Loading migration warning')
    loading[0]['warnings'] = []
    original.validate_graph_report(checked)


def recovery_plan():
    pinned, spec = original.plan()
    before = json.loads(original.JOURNAL.read_text(encoding='utf-8'))
    if pinned['plan_sha256'] != EXPECTED_PLAN or before.get('plan') != pinned:
        raise ValueError('Original reviewed packet changed')
    if before.get('phase') != 'graphs-started':
        raise ValueError('Recovery requires the observed graphs-started journal')
    expected_command = ['node', 'Tools/GameFlow/bpgraph.mjs', 'build', '--reset-graphs',
                        str(original.GRAPH.relative_to(ROOT)), str(original.PC_GRAPH.relative_to(ROOT))]
    inputs = {str(p.relative_to(ROOT)): digest(p) for p in (original.GRAPH, original.PC_GRAPH)}
    if before.get('build_command') != expected_command or before.get('build_inputs') != inputs:
        raise ValueError('Original build command or inputs differ')
    if Path(before.get('graph_report', '')).resolve() != REPORT.resolve():
        raise ValueError('Original build report path differs')
    if before.get('before', {}).get('ProgressFill', {}).get('class') != 'Image':
        raise ValueError('Original tree does not prove the old Image type')
    current = {n['name']: n['class'] for n in original.walk(spec['tree'])}
    if current.get('ProgressFill') != 'Border':
        raise ValueError('New tree does not declare the observed Border migration')
    validate_observed_report(json.loads(REPORT.read_text(encoding='utf-8')))
    evidence = {
        'original_plan_sha256': EXPECTED_PLAN,
        'historical_warning': WARNING,
        'sha256': {str(p.relative_to(ROOT)): digest(p)
                   for p in (original.JOURNAL, REPORT, STDERR, Path(__file__).resolve())},
        'operations': ['read exact Loading tree', 'compile Loading', 'compile PC', 'save Loading', 'save PC'],
    }
    evidence['recovery_sha256'] = hashlib.sha256(json.dumps(evidence, sort_keys=True).encode()).hexdigest()
    return evidence, pinned, spec, before


class RecoveryInstaller(original.Installer):
    def __init__(self, connection, state, evidence):
        super().__init__(connection, RECOVERY, state)
        self.evidence = evidence

    def call(self, command, params):
        if recovery_plan()[0] != self.evidence:
            raise ValueError('Original evidence or recovery source changed during finalization')
        return super().call(command, params)

    def finish_migration(self, spec):
        rows = self.read()
        expected = {n['name']: n['class'] for n in original.walk(spec['tree'])}
        if set(rows) != set(expected) | {self.state['root']}:
            raise ValueError('Loading inventory changed since the staged tree')
        for name, kind in expected.items():
            actual = rows[name]['class']
            expected_class = kind.rsplit('/', 1)[-1].split('.')[-1]
            if actual != expected_class and actual != expected_class + '_C':
                raise ValueError('Loading widget class differs: ' + name)
        compiled = self.call('ui_compile_widget', {'widget_blueprint_path': original.ASSET, 'save_on_success': False})
        if compiled.get('success') is not True or compiled.get('compiled_clean') is not True:
            raise ValueError('Current Loading compile is not clean')
        pc = self.call('blueprint_compile', {'path': original.PC, 'save': False})
        if pc.get('ok') is not True:
            raise ValueError('Current PC compile is not clean')
        for asset in (original.ASSET, original.PC):
            require_writable(package_file(asset, ROOT))
            result = self.call('python_run', {'script': 'import unreal\nbp=unreal.load_asset(' + repr(asset) +
                ")\nassert bp is not None\nsaved=unreal.EditorAssetLibrary.save_loaded_asset(bp,False)\nassert saved is True\nprint('STARTUP_RECOVERY_SAVED_TRUE')"})
            if result.get('ok') is not True or 'STARTUP_RECOVERY_SAVED_TRUE' not in result.get('stdout', ''):
                raise ValueError('Strict save True was not confirmed')
        self.state.update(phase='saved', saved_sha256={a: digest(package_file(a, ROOT))
                          for a in (original.ASSET, original.PC)})
        save_state(self.journal, self.state)
        print('STARTUP_MIGRATION_FINALIZATION_COMPILED_SAVED_OK')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('check', 'run'))
    parser.add_argument('--owner')
    parser.add_argument('--recovery-sha256')
    args = parser.parse_args()
    evidence, pinned, spec, before = recovery_plan()
    if args.mode == 'check':
        print(json.dumps(evidence, indent=2))
        return
    if not args.owner or args.recovery_sha256 != evidence['recovery_sha256']:
        parser.error('Run requires root owner and exact reviewed recovery hash')
    if RECOVERY.exists():
        raise ValueError('Finalization journal already exists; inspect it, never auto-replay')
    for asset in (original.ASSET, original.PC):
        require_writable(package_file(asset, ROOT))
    state = {'plan': pinned, 'recovery': evidence, 'phase': 'finalization-started',
             'root': before['root'], 'events': []}
    connection = EditorConnection(args.owner)
    save_state(RECOVERY, state)
    RecoveryInstaller(connection, state, evidence).finish_migration(spec)


if __name__ == '__main__':
    main()
