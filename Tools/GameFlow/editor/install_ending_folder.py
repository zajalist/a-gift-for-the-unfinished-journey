"""Install one audited ending folder under the root writer's existing lease.

    python Tools/GameFlow/editor/install_ending_folder.py check hatch_anims
    python Tools/GameFlow/editor/install_ending_folder.py run hatch_anims --owner codex-saskarta-goal

Default: one complete save group per invocation (one animation, one cinematic,
or one SFX). Rerun the same command to continue. Unfinished groups restart from
their resetting create/setup/import step. No prepared files are regenerated.
"""
from __future__ import annotations

import argparse
import ast
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PREPARED = ROOT / 'Saved/Verification/ending_voice_20260930'
AUDIT = PREPARED / 'preparation-audit.json'
FOLDERS = ('hatch_anims', 'final_anims', 'CIN_19_HATCH', 'CIN_24_TRANSMISSION', 'CIN_25_END_CARD', 'sfx')
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / 'Tools/GameFlow'))
import ending_editor as editor


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def package_file(package, root):
    if not package.startswith('/Game/') or '..' in package.split('/'):
        raise ValueError('Unexpected package path: ' + package)
    return root / 'Content' / (package[6:] + '.uasset')


def require_writable(path):
    """Only inspect filesystem metadata; do not clear attributes or write a probe."""
    check = path
    while not check.exists():
        check = check.parent
    info = check.stat()
    readonly = bool(getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_READONLY)
    if (check.is_file() and readonly) or not os.access(check, os.W_OK):
        raise ValueError('Read-only save target or parent: ' + str(check))


def target_of_save(code):
    calls = [n for n in ast.walk(ast.parse(code)) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Attribute) and n.args]
    paths = [n.args[0].value for n in calls if n.func.attr == 'save_asset'
             and isinstance(n.args[0], ast.Constant)]
    if not paths:  # SFX uses save_loaded_asset on its one explicitly loaded wave.
        paths = [n.args[0].value for n in calls if n.func.attr == 'load_asset'
                 and isinstance(n.args[0], ast.Constant)]
    if len(set(paths)) != 1 or not isinstance(paths[0], str):
        raise ValueError('Could not identify exactly one save target')
    return paths[0]


def is_save(name):
    return name == '90_save.py' or '_save_' in name or name.endswith('_save.py')


def make_plan(folder, prepared=PREPARED, root=ROOT, audit_path=AUDIT):
    if folder not in FOLDERS:
        raise ValueError('Choose one audited folder: ' + ', '.join(FOLDERS))
    audit = json.loads(audit_path.read_text(encoding='utf-8'))
    expected = {Path(n).name: h for n, h in audit['prepared_sha256'].items()
                if Path(n).parent.as_posix() == folder and n.endswith('.py')}
    directory = prepared / folder
    actual = {p.name for p in directory.glob('*.py')}
    if not expected or actual != set(expected):
        raise ValueError(f'Folder filenames differ from audit: missing={sorted(set(expected)-actual)}, extra={sorted(actual-set(expected))}')
    codes = {}
    inputs = {}
    for name in sorted(expected):
        path = directory / name
        if digest(path) != expected[name]:
            raise ValueError('Prepared hash differs from audit: ' + name)
        code = path.read_text(encoding='utf-8')
        compile(code, name, 'exec')
        if editor.banned(code):
            raise ValueError('Forbidden python_run operation: ' + name)
        codes[name] = code
        if folder == 'sfx' and name.endswith('_import.py'):
            for node in ast.walk(ast.parse(code)):
                if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value.endswith('.wav'):
                    wave = Path(node.value).resolve()
                    if not wave.is_relative_to(prepared.resolve()) or not wave.is_file():
                        raise ValueError('Missing or unexpected SFX source: ' + str(wave))
                    inputs[str(wave)] = digest(wave)
    sources = ['Tools/Cinematics/samyor_reveal.py'] if folder == 'hatch_anims' else []
    if folder == 'final_anims':
        sources = ['Tools/Cinematics/samyor_final.py', 'Tools/Cinematics/samyor_reveal.py',
                   'Tools/Cinematics/build_cinematics.py', 'Tools/Cinematics/traveller_ref_pose.json',
                   'Tools/Cinematics/probe_ending.json']
    if folder.startswith('CIN_'):
        sources = ['Tools/Cinematics/build_cinematics.py', 'Tools/Cinematics/samyor_reveal.py']
    for name in sources:
        if digest(root / name) != audit['source_sha256'][name]:
            raise ValueError('Generator changed since preparation audit: ' + name)
    groups, pending = [], []
    for name in sorted(codes):
        pending.append(name)
        if is_save(name):
            groups.append({'id': name, 'steps': pending, 'package': target_of_save(codes[name])})
            pending = []
    if pending:
        if pending != ['99_read.py'] or not groups:
            raise ValueError('Unexpected unsaved trailing steps: ' + str(pending))
        groups[-1]['steps'] += pending
    if not groups:
        raise ValueError('No save groups found')
    for group in groups:
        path = package_file(group['package'], root)
        for suffix in ('.uasset', '.uexp', '.ubulk'):
            target = path.with_suffix(suffix)
            if suffix == '.uasset' or target.exists():
                require_writable(target)
    identity = {'folder': folder, 'prepared': str(prepared.resolve()), 'audit_sha256': digest(audit_path),
                'script_sha256': expected, 'input_sha256': inputs, 'groups': groups}
    identity['plan_sha256'] = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    return identity


def validate_output(name, output):
    if re.search(r'\bsaved\s+False\b', output, re.IGNORECASE):
        raise RuntimeError('Editor reported saved False: ' + name)
    if is_save(name):
        if name.startswith('90_') or '_save_A_Samyor_' in name:
            if not re.search(r'\bsaved\s+True\b', output):
                raise RuntimeError('Missing saved True: ' + name)
        elif name.endswith('_save.py'):
            sound = name.split('_', 1)[1].removesuffix('_save.py')
            if 'ENDING_SFX_SAVED ' + sound not in output:
                raise RuntimeError('Missing SFX save confirmation: ' + name)
    if name.endswith('_import.py'):
        sound = name.split('_', 1)[1].removesuffix('_import.py')
        if 'ENDING_SFX_IMPORTED ' + sound not in output:
            raise RuntimeError('Missing SFX import confirmation: ' + name)


def save_state(path, state):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    with temporary.open('w', encoding='utf-8') as handle:
        json.dump(state, handle, indent=2)
        handle.write('\n')
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def saved_files(group, root):
    target = package_file(group['package'], root)
    if not target.is_file():
        raise RuntimeError('Save claimed success but package is absent: ' + str(target))
    return {str(p): digest(p) for ext in ('.uasset', '.uexp', '.ubulk')
            if (p := target.with_suffix(ext)).is_file()}


def run_plan(plan, journal, send, guard, *, max_groups=1, root=ROOT):
    """Injected editor adapter permits offline coverage without an editor connection."""
    if max_groups < 1:
        raise ValueError('max_groups must be positive')
    state = json.loads(journal.read_text(encoding='utf-8')) if journal.exists() else {
        'plan': plan, 'completed': {}, 'events': []}
    if state['plan'] != plan:
        raise ValueError('Journal plan differs; inspect the new plan and use a new journal')
    ran = 0
    for group in plan['groups']:
        if group['id'] in state['completed']:
            if saved_files(group, root) != state['completed'][group['id']]:
                raise ValueError('Previously saved package changed: ' + group['package'])
            continue
        if ran >= max_groups:
            break
        for name in group['steps']:
            event = {'step': name, 'group': group['id'], 'utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                     'status': 'started'}
            state['events'].append(event)
            save_state(journal, state)
            try:
                guard()
                path = Path(plan['prepared']) / plan['folder'] / name
                if digest(path) != plan['script_sha256'][name]:
                    raise ValueError('Prepared script changed during run: ' + name)
                for path_string, sha in plan['input_sha256'].items():
                    if digest(Path(path_string)) != sha:
                        raise ValueError('SFX input changed during run: ' + path_string)
                require_writable(package_file(group['package'], root))
                output = send(path.read_text(encoding='utf-8'), name)
                event['output'] = output
                guard()
                validate_output(name, output)
                event['status'] = 'ok'
            except BaseException as error:
                event.update(status='failed', error=str(error))
                save_state(journal, state)
                raise
            save_state(journal, state)
            print('ENDING_STEP_OK', plan['folder'], name, flush=True)
        state['completed'][group['id']] = saved_files(group, root)
        save_state(journal, state)
        ran += 1
    remaining = len(plan['groups']) - len(state['completed'])
    print('ENDING_FOLDER_PROGRESS', plan['folder'], 'saved_groups', len(state['completed']), 'remaining', remaining)
    return remaining


class EditorConnection:
    def __init__(self, owner):
        import editor_gate
        from apply_look import pie_running
        sys.path.insert(0, str(ROOT / 'Tools/Perf'))
        from bounded_pie_profile import hayba_deadline
        self.gate, self.pie_running, self.owner = editor_gate, pie_running, owner
        # This transport enforces one socket deadline and rejects top-level
        # lease_warning responses instead of losing them while unpacking data.
        self._transport = hayba_deadline
        self._next_rpc_at = 0.0
        self.rpc = self._paced_rpc
        self.token = None
        self.log_start = editor.log_size()
        self.log_identity = editor.LOG.stat().st_ctime_ns
        if editor.new_faults(0):
            raise RuntimeError('Current editor log contains native faults; restart editor before installing')
        self.guard()

    def _paced_rpc(self, *args, **kwargs):
        # The native bridge retains a closed client's writer for up to five
        # seconds. Four guarded RPCs per animation chunk can otherwise exhaust
        # its 16 client slots. Bound this installer's rate while retaining every
        # before/after lease and PIE check; never retry an ambiguous mutation.
        delay = self._next_rpc_at - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        self._next_rpc_at = time.monotonic() + 0.6
        return self._transport(*args, **kwargs)

    def guard(self):
        if not editor.LOG.exists() or editor.LOG.stat().st_ctime_ns != self.log_identity or editor.log_size() < self.log_start:
            raise RuntimeError('Editor log restarted/rotated; stop and re-establish the editor lease')
        if self.pie_running():
            raise RuntimeError('PIE is running or within its teardown cooldown')
        with editor.LOG.open('rb') as handle:
            handle.seek(self.log_start)
            text = handle.read().decode('utf-8', errors='replace')
        if any(mark in text for mark in editor.FAULTS + editor.PIE_START):
            raise RuntimeError('Native fault or PIE start appeared during this installation')
        lock = self.gate.read_lock() or {}
        holder = lock.get('holders', {}).get(self.owner, {})
        if lock.get('mode') != 'lease' or not holder.get('token') or not holder.get('expires_at', 0) >= time.time() + 35:
            raise RuntimeError('Root must acquire/renew its lease (at least 35 seconds remaining)')
        if 'global' not in holder.get('resources', []):
            raise RuntimeError('Ending folder install requires the root global lease')
        # Native acquisition explicitly permits the same owner without a token.
        # Native response redaction can replace the token with this marker; it
        # is not a usable credential and must never enter an RPC envelope.
        token = holder['token']
        if token == '[REDACTED:token]':
            token = None
        self.token = None
        os.environ.pop('HAYBA_LEASE', None)
        status = self.rpc('lease_status', {}, self.owner, token, 5)
        if not isinstance(status, dict) or status.get('caller_owner') != self.owner:
            raise RuntimeError('Live lease status does not identify the requested root owner')
        matches = [claim for claim in status.get('leases', [])
                   if claim.get('owner') == self.owner and claim.get('mine') is True]
        if len(matches) != 1 or not matches[0].get('expires_in_s', 0) >= 35 or not any(
                resource.get('resource') == 'global' and resource.get('mode') == 'exclusive'
                for resource in matches[0].get('resources', [])):
            raise RuntimeError('Mirror is not a live exclusive global lease with at least 35 seconds remaining')
        # Hayba's lease status now names the credential lease_id; accept the
        # previous token field for older editor builds.
        live_token = matches[0].get('lease_id', matches[0].get('token'))
        if token and live_token != '[REDACTED:token]' and live_token != token:
            raise RuntimeError('Live lease token does not match the root mirror')
        self.token = token
        if token:
            os.environ['HAYBA_LEASE'] = token
        os.environ['HAYBA_AGENT_ID'] = self.owner

    def send(self, script, name):
        self.guard()
        if editor.banned(script):
            raise ValueError('Forbidden python_run operation: ' + name)
        # Unlike apply_look.python_run, this preserves lease refusal/warnings.
        # The editor retains its 5-second Python limit; all I/O shares 30 seconds.
        data = self.rpc('python_run', {'script': script}, self.owner, self.token, 30)
        if not isinstance(data, dict):
            raise RuntimeError('Unexpected python_run response: ' + name)
        output = data.get('stdout', '')
        for field in ('stderr', 'warning', 'warnings'):
            if data.get(field):
                detail = str(data[field])
                print(f'ENDING_EDITOR_{field.upper()} {name}: {detail}', file=sys.stderr, flush=True)
                output += f'\n{field}: {detail}'
        # The native handler envelope can be ok while user Python failed;
        # HaybaMCPPythonHandler publishes that result separately in data.ok.
        if data.get('ok') is not True:
            raise RuntimeError(f'{name}: Python execution was not confirmed successful; output: {output}')
        if data.get('stdout_truncated') or data.get('stderr_truncated'):
            raise RuntimeError(f'{name}: Python capture was truncated; output: {output}')
        if 'STOP:' in output:
            raise RuntimeError(f'{name}: editor rejected chunk; output: {output}')
        return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('check', 'run'))
    parser.add_argument('folder', choices=FOLDERS)
    parser.add_argument('--owner')
    parser.add_argument('--max-groups', type=int, default=1)
    parser.add_argument('--journal', type=Path)
    args = parser.parse_args()
    audit = PREPARED / 'final-animation-audit.json' if args.folder == 'final_anims' else AUDIT
    plan = make_plan(args.folder, audit_path=audit)
    if args.mode == 'check':
        print(json.dumps(plan, indent=2))
        return
    if not args.owner:
        parser.error('run requires --owner for the root writer\'s already-held global lease')
    connection = EditorConnection(args.owner)
    journal = args.journal or PREPARED / 'install_logs' / (args.folder + '.json')
    run_plan(plan, journal, connection.send, connection.guard, max_groups=args.max_groups)


if __name__ == '__main__':
    main()
