"""Mirror the three frozen v2 readbacks with struct value comparison only.

No generator edits, rebuilds, saves or editor calls. UE Python Guid wrappers can
compare by object identity; compare the complete binding ID exported value.
"""
from pathlib import Path
import ast
import hashlib
import json

ROOT=Path(__file__).resolve().parents[2]
PACKET=ROOT/'Saved/Verification/ending_body_fix_20261001_v2'
OUT=ROOT/'Saved/Verification/ending_body_acceptance_20261001_v3'
FOLDERS=('CIN_19_HATCH','CIN_24_TRANSMISSION','CIN_25_END_CARD')
OLD="""    return (actual_id.get_editor_property('guid') == expected_id.get_editor_property('guid')
            and actual_id.get_editor_property('sequence_id') == expected_id.get_editor_property('sequence_id'))"""
NEW="""    return actual_id.export_text() == expected_id.export_text()"""


def prepare():
    manifest=json.loads((PACKET/'manifest.json').read_text())
    rows=[];OUT.mkdir(parents=True,exist_ok=True)
    for folder in FOLDERS:
        original=PACKET/folder/'99_read.py'
        digest=hashlib.sha256(original.read_bytes()).hexdigest()
        assert digest==manifest['script_sha256'][folder+'/99_read.py']
        code=original.read_text();assert code.count(OLD)==1
        updated=code.replace(OLD,NEW)
        compile(updated,folder,'exec')
        tree=ast.parse(updated)
        methods={n.func.attr for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute)}
        assert not methods&{'save_asset','save_loaded_asset','set_editor_property','add_track','add_section','spawn_actor_from_class'}
        target=OUT/(folder+'.py');target.write_text(updated)
        rows.append(dict(source=str(original.relative_to(ROOT)),source_sha256=digest,
            readback=str(target.relative_to(ROOT)),readback_sha256=hashlib.sha256(target.read_bytes()).hexdigest()))
    (OUT/'manifest.json').write_text(json.dumps(dict(scope='Read-only acceptance; only full binding-ID export value equality replaces Python wrapper equality',
        original_manifest_sha256=hashlib.sha256((PACKET/'manifest.json').read_bytes()).hexdigest(),rows=rows),indent=2)+'\n')
    print('BODY_ACCEPTANCE_V3_READY',len(rows),OUT)


if __name__=='__main__':prepare()
