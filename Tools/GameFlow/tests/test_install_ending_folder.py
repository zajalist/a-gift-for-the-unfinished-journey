"""Bounded installer failure/resume checks with an injected editor; no editor calls."""
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'editor'))
import install_ending_folder as install


def test_connection_initializes_log_identity_before_guard(monkeypatch, tmp_path):
    log = tmp_path / 'editor.log'
    log.write_text('healthy editor')
    monkeypatch.setattr(install.editor, 'LOG', log)
    monkeypatch.setattr(install.editor, 'new_faults', lambda _: [])
    guarded = []
    monkeypatch.setattr(install.EditorConnection, 'guard', lambda self: guarded.append(
        (self.log_start, self.log_identity)))
    connection = install.EditorConnection('test-owner')
    assert guarded == [(log.stat().st_size, log.stat().st_ctime_ns)]
    assert connection.rpc == connection._paced_rpc


def test_rpc_rate_is_bounded_without_retrying_mutations(monkeypatch):
    clock = [10.0]
    calls = []
    sleeps = []
    monkeypatch.setattr(install.time, 'monotonic', lambda: clock[0])
    def sleep(seconds):
        sleeps.append(seconds)
        clock[0] += seconds
    monkeypatch.setattr(install.time, 'sleep', sleep)
    connection = object.__new__(install.EditorConnection)
    connection._next_rpc_at = 0.0
    def transport(command):
        calls.append((command, clock[0]))
        if command == 'mutation':
            raise ConnectionResetError('unknown result')
        return command
    connection._transport = transport
    assert connection._paced_rpc('status') == 'status'
    with pytest.raises(ConnectionResetError):
        connection._paced_rpc('mutation')
    assert connection._paced_rpc('status') == 'status'
    assert [name for name, _ in calls] == ['status', 'mutation', 'status']
    assert [stamp for _, stamp in calls] == pytest.approx([10.0, 10.6, 11.2])
    assert sleeps == pytest.approx([0.6, 0.6])


def fixture_plan(tmp_path, clips=1):
    prepared = tmp_path / 'prepared'
    folder = 'hatch_anims'
    directory = prepared / folder
    directory.mkdir(parents=True)
    source = tmp_path / 'Tools/Cinematics/samyor_reveal.py'
    source.parent.mkdir(parents=True)
    source.write_text('# generator\n', encoding='utf-8')
    hashes = {}
    for i in range(clips):
        name = f'A_Samyor_Test{i}'
        package = f'/Game/Anims/{name}'
        for filename, code in [(f'{i}0_create_{name}.py', "print('created')\n"),
                               (f'{i}1_keys_{name}_0.py', "print('keys')\n"),
                               (f'{i}2_save_{name}.py', f"import unreal\nprint('saved', unreal.EditorAssetLibrary.save_asset({package!r}, False))\n")]:
            path = directory / filename
            path.write_text(code, encoding='utf-8')
            hashes[f'{folder}/{filename}'] = install.digest(path)
    audit = prepared / 'preparation-audit.json'
    audit.write_text(json.dumps({'prepared_sha256': hashes,
                                'source_sha256': {'Tools/Cinematics/samyor_reveal.py': install.digest(source)}}), encoding='utf-8')
    (tmp_path / 'Content/Anims').mkdir(parents=True)
    plan = install.make_plan(folder, prepared, tmp_path, audit)
    return plan, prepared, audit


def sender(plan, root, calls, fail=None):
    def send(code, name):
        calls.append(name)
        if name == fail:
            return 'saved False'
        if install.is_save(name):
            group = next(g for g in plan['groups'] if g['id'] == name)
            install.package_file(group['package'], root).write_bytes(name.encode())
            return 'length 7.0 tracks 44 saved True'
        return 'ok'
    return send


def test_preflight_rejects_extra_files_hash_changes_and_changed_generator(tmp_path):
    plan, prepared, audit = fixture_plan(tmp_path)
    folder = prepared / plan['folder']
    extra = folder / 'extra.py'
    extra.write_text('print(1)', encoding='utf-8')
    with pytest.raises(ValueError, match='filenames differ'):
        install.make_plan(plan['folder'], prepared, tmp_path, audit)
    extra.unlink()
    first = folder / plan['groups'][0]['steps'][0]
    original = first.read_bytes()
    first.write_bytes(original + b'# edit\n')
    with pytest.raises(ValueError, match='hash differs'):
        install.make_plan(plan['folder'], prepared, tmp_path, audit)
    first.write_bytes(original)
    (tmp_path / 'Tools/Cinematics/samyor_reveal.py').write_text('# changed', encoding='utf-8')
    with pytest.raises(ValueError, match='Generator changed'):
        install.make_plan(plan['folder'], prepared, tmp_path, audit)


def test_default_runs_one_whole_group_then_resumes_next_group(tmp_path):
    plan, _, _ = fixture_plan(tmp_path, 2)
    journal = tmp_path / 'run.json'
    calls = []
    send = sender(plan, tmp_path, calls)
    assert install.run_plan(plan, journal, send, lambda: None, root=tmp_path) == 1
    assert calls == plan['groups'][0]['steps']
    calls.clear()
    assert install.run_plan(plan, journal, send, lambda: None, root=tmp_path) == 0
    assert calls == plan['groups'][1]['steps']
    calls.clear()
    assert install.run_plan(plan, journal, send, lambda: None, root=tmp_path) == 0
    assert calls == []


def test_failed_save_stops_and_resume_restarts_whole_unsaved_group(tmp_path):
    plan, _, _ = fixture_plan(tmp_path, 2)
    journal = tmp_path / 'run.json'
    calls = []
    with pytest.raises(RuntimeError, match='saved False'):
        install.run_plan(plan, journal, sender(plan, tmp_path, calls, plan['groups'][0]['id']),
                         lambda: None, max_groups=2, root=tmp_path)
    state = json.loads(journal.read_text(encoding='utf-8'))
    assert not state['completed']
    assert state['events'][-1]['output'] == 'saved False'
    assert state['events'][-1]['status'] == 'failed'
    assert calls == plan['groups'][0]['steps']
    calls.clear()
    install.run_plan(plan, journal, sender(plan, tmp_path, calls), lambda: None, root=tmp_path)
    assert calls == plan['groups'][0]['steps']


@pytest.mark.parametrize('output', ['saved false', 'saved', 'ok', 'unsaved True'])
def test_missing_or_false_save_confirmation_fails(output):
    with pytest.raises(RuntimeError):
        install.validate_output('90_save.py', output)


def test_guard_failure_stops_before_next_call_and_records_error(tmp_path):
    plan, _, _ = fixture_plan(tmp_path)
    journal = tmp_path / 'run.json'
    calls, guard_calls = [], []
    def guard():
        guard_calls.append(1)
        if len(guard_calls) == 2:
            raise RuntimeError('Native fault or PIE start')
    with pytest.raises(RuntimeError, match='Native fault'):
        install.run_plan(plan, journal, sender(plan, tmp_path, calls), guard, root=tmp_path)
    assert len(calls) == 1
    assert json.loads(journal.read_text(encoding='utf-8'))['events'][-1]['status'] == 'failed'


def test_resume_refuses_changed_saved_package(tmp_path):
    plan, _, _ = fixture_plan(tmp_path)
    journal = tmp_path / 'run.json'
    calls = []
    send = sender(plan, tmp_path, calls)
    install.run_plan(plan, journal, send, lambda: None, root=tmp_path)
    install.package_file(plan['groups'][0]['package'], tmp_path).write_bytes(b'external edit')
    with pytest.raises(ValueError, match='Previously saved package changed'):
        install.run_plan(plan, journal, send, lambda: None, root=tmp_path)


def test_preflight_refuses_readonly_package_without_changing_attributes(tmp_path, monkeypatch):
    plan, prepared, audit = fixture_plan(tmp_path)
    target = install.package_file(plan['groups'][0]['package'], tmp_path)
    target.touch()
    previous = install.os.access
    monkeypatch.setattr(install.os, 'access', lambda p, mode: False if Path(p) == target else previous(p, mode))
    with pytest.raises(ValueError, match='Read-only save target'):
        install.make_plan(plan['folder'], prepared, tmp_path, audit)


def live_connection(tmp_path, monkeypatch, token='[REDACTED:token]'):
    log = tmp_path / 'editor.log'
    log.write_text('', encoding='utf-8')
    monkeypatch.setattr(install.editor, 'LOG', log)
    monkeypatch.setattr(install.editor, 'log_size', lambda: log.stat().st_size)
    monkeypatch.setenv('HAYBA_LEASE', 'stale-environment-token')
    monkeypatch.setenv('HAYBA_AGENT_ID', 'old-owner')
    connection = object.__new__(install.EditorConnection)
    connection.owner, connection.token = 'root-fixture', None
    connection.log_start, connection.log_identity = 0, log.stat().st_ctime_ns
    connection.pie_running = lambda: False
    mirror = {'mode': 'lease', 'holders': {connection.owner: {
        'token': token, 'expires_at': install.time.time() + 900, 'resources': ['global']}}}
    connection.gate = SimpleNamespace(read_lock=lambda: mirror)
    status = {'caller_owner': connection.owner, 'leases': [{
        'owner': connection.owner, 'mine': True, 'token': token,
        'resources': [{'resource': 'global', 'mode': 'exclusive'}], 'expires_in_s': 899}]}
    calls = []
    def rpc(command, params, owner, lease, timeout):
        calls.append((command, params, owner, lease, timeout))
        return status
    connection.rpc = rpc
    return connection, mirror, status, calls


def test_live_guard_uses_confirmed_owner_for_redacted_token(tmp_path, monkeypatch):
    connection, _, _, calls = live_connection(tmp_path, monkeypatch)
    connection.guard()
    assert connection.token is None
    assert 'HAYBA_LEASE' not in install.os.environ
    assert install.os.environ['HAYBA_AGENT_ID'] == connection.owner
    assert calls == [('lease_status', {}, connection.owner, None, 5)]


def test_live_guard_retains_real_token_and_rejects_wrong_token(tmp_path, monkeypatch):
    connection, _, status, calls = live_connection(tmp_path, monkeypatch, 'real-fixture-token')
    connection.guard()
    assert connection.token == 'real-fixture-token'
    assert calls[-1][3] == 'real-fixture-token'
    status['leases'][0]['token'] = 'another-token'
    with pytest.raises(RuntimeError, match='token does not match'):
        connection.guard()


@pytest.mark.parametrize('defect', ['stale_mirror', 'mirror_scope', 'missing_live', 'wrong_owner',
                                  'wrong_caller', 'not_mine', 'shared', 'scoped', 'expiring',
                                  'nan_live', 'nan_mirror', 'duplicate'])
def test_live_guard_rejects_invalid_ownership_or_resource(tmp_path, monkeypatch, defect):
    connection, mirror, status, _ = live_connection(tmp_path, monkeypatch)
    claim = status['leases'][0]
    if defect == 'stale_mirror':
        mirror['holders'][connection.owner]['expires_at'] = 0
    elif defect == 'mirror_scope':
        mirror['holders'][connection.owner]['resources'] = ['asset:/Game/Test']
    elif defect == 'missing_live':
        status['leases'] = []
    elif defect == 'wrong_owner':
        claim['owner'] = 'different-root'
    elif defect == 'wrong_caller':
        status['caller_owner'] = 'different-root'
    elif defect == 'not_mine':
        claim['mine'] = False
    elif defect == 'shared':
        claim['resources'][0]['mode'] = 'shared'
    elif defect == 'scoped':
        claim['resources'][0]['resource'] = 'asset:/Game/Test'
    elif defect == 'expiring':
        claim['expires_in_s'] = 34.9
    elif defect == 'nan_live':
        claim['expires_in_s'] = float('nan')
    elif defect == 'nan_mirror':
        mirror['holders'][connection.owner]['expires_at'] = float('nan')
    elif defect == 'duplicate':
        status['leases'].append(dict(claim))
    with pytest.raises(RuntimeError):
        connection.guard()


def test_send_retains_editor_warnings_and_stops_on_transport_warning(tmp_path, monkeypatch, capsys):
    connection, _, status, calls = live_connection(tmp_path, monkeypatch)
    def rpc(command, params, owner, lease, timeout):
        calls.append((command, params, owner, lease, timeout))
        if command == 'lease_status':
            return status
        return {'ok': True, 'stdout': 'saved True', 'stderr': 'compiler detail', 'warnings': ['advisory detail']}
    connection.rpc = rpc
    output = connection.send("print('fixture')", 'fixture.py')
    assert 'compiler detail' in output and 'advisory detail' in output
    assert 'ENDING_EDITOR_STDERR' in capsys.readouterr().err
    assert calls[-1][0] == 'python_run' and calls[-1][3] is None
    def refusing_rpc(*args):
        raise RuntimeError('native lease warning: fixture lease expired')
    connection.rpc = refusing_rpc
    with pytest.raises(RuntimeError, match='fixture lease expired'):
        connection.send("print('fixture')", 'fixture.py')


@pytest.mark.parametrize('response', [
    {'ok': False, 'stderr': 'AssertionError: fixture failure'},
    {'stdout': 'saved True'},
    {'ok': True, 'stdout': 'saved True', 'stdout_truncated': True},
    {'ok': True, 'stderr': 'partial detail', 'stderr_truncated': True},
])
def test_send_refuses_nested_python_failure_or_truncated_evidence(tmp_path, monkeypatch, response):
    connection, _, status, _ = live_connection(tmp_path, monkeypatch)
    connection.rpc = lambda command, *args: status if command == 'lease_status' else response
    with pytest.raises(RuntimeError):
        connection.send("print('fixture')", 'fixture.py')
