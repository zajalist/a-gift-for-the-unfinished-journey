import json
from pathlib import Path
from types import SimpleNamespace
import sys
import pytest

sys.path.insert(0,str(Path(__file__).parents[1]))
import run_fence_group as runner

def packet(tmp_path,monkeypatch):
    base=tmp_path/'Saved/plinths';base.mkdir(parents=True)
    monkeypatch.setattr(runner,'ROOT',tmp_path);monkeypatch.setattr(runner,'BASE',base)
    rows=[]
    for name in ['FenceRear00','FenceRear01','FenceRear02']:
        calls=[]
        for phase in ['apply','verify']:
            path=base/phase/(name+'.py');path.parent.mkdir(exist_ok=True);path.write_text('pass\n')
            calls.append(dict(phase=phase,path=str(path.relative_to(tmp_path)),sha256=runner.digest(path)))
        rows.append(dict(id=name,group=0,calls=calls))
    (base/'fence_execution_manifest.json').write_text(json.dumps(dict(groups=rows)))
    return SimpleNamespace(gate=False,group=0,only_id=None,receipts=None,owner='root-test'),base

class Connection:
    def __init__(self,owner,fail=False):self.calls=[];self.fail=fail
    def guard(self):pass
    def send(self,code,name):
        self.calls.append(name);prop,phase=name.rsplit('_',1)
        row=dict(id=prop,applied=phase=='apply',saved=False,pads=[{}],changed=[{},{}],verified_transforms=True,surface_contact_pass=not self.fail)
        return 'S26_LEVEL_PLINTH '+json.dumps(row)

def test_distinct_phase_receipts_and_all_calls(tmp_path,monkeypatch):
    args,base=packet(tmp_path,monkeypatch);c=Connection('x')
    runner.run(args,lambda owner:c)
    assert len(c.calls)==6
    paths=list((base/'fence_receipts').glob('*/*.readback.json'))
    assert len(paths)==6
    assert all(json.loads(p.read_text())['acceptance_passed'] for p in paths)

def test_failed_contact_stops_before_next_prop_and_preserves_output(tmp_path,monkeypatch):
    args,base=packet(tmp_path,monkeypatch);c=Connection('x',True)
    with pytest.raises(RuntimeError,match='verification failed'):runner.run(args,lambda owner:c)
    assert c.calls==['FenceRear00_apply','FenceRear00_verify']
    record=json.loads((base/'fence_receipts/FenceRear00/verify.readback.json').read_text())
    assert record['status']=='ok' and not record['acceptance_passed'] and 'surface_contact_pass' in record['output']

def test_existing_phase_refuses_before_connection(tmp_path,monkeypatch):
    args,base=packet(tmp_path,monkeypatch)
    path=base/'fence_receipts/FenceRear00/apply.readback.json';path.parent.mkdir(parents=True);path.write_text('{}')
    with pytest.raises(AssertionError,match='Existing phase receipt'):runner.run(args,lambda owner:pytest.fail('Must not contact editor'))

def test_changed_script_refuses_before_connection(tmp_path,monkeypatch):
    args,base=packet(tmp_path,monkeypatch);(base/'apply/FenceRear01.py').write_text('x=1\n')
    with pytest.raises(AssertionError,match='hash changed'):runner.run(args,lambda owner:pytest.fail('Must not contact editor'))
