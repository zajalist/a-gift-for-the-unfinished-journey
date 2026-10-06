"""Retain v3 checks and compare Sequencer key readback to float32 values.

All126 observed CIN24/25 keys equal the frozen authored values rounded to
float32 exactly. This adds every-key checks; it does not widen world tolerance.
"""
import ast
import hashlib
import json
from pathlib import Path
import prepare_transform_diagnostic as diagnostic

ROOT=Path(__file__).resolve().parents[2]
V3=ROOT/'Saved/Verification/ending_body_acceptance_20261001_v3'
OUT=ROOT/'Saved/Verification/ending_body_acceptance_20261001_v4'
HELPER='''def key_near(actual, authored):
    rounded = struct.unpack('<f', struct.pack('<f', float(authored)))[0]
    return abs(float(actual) - rounded) <= 0.000001
'''


def prepare():
    OUT.mkdir(parents=True,exist_ok=True)
    records=[]
    for folder in ('CIN_24_TRANSMISSION','CIN_25_END_CARD'):
        evidence=ROOT/'Saved/Verification/playtest_feedback_20261001'/(folder+'_transform_diagnostic.readback.txt')
        channels=[json.loads(line.split(' ',1)[1]) for line in evidence.read_text().splitlines()
                  if line.startswith('ENDING_TRANSFORM_CHANNEL ')]
        assert len(channels)==18
        assert all(c['actual_count']==c['expected_count'] for c in channels)
        values=[v for c in channels for v in c['values']]
        assert values and all(v['float32_delta']==0 for v in values)
        transforms=dict(row for p in (diagnostic.PACKET/folder).glob('*.py')
                        if (row:=diagnostic.transform_rows(p)) is not None)
        source=V3/(folder+'.py')
        code=source.read_text().replace('import json\n','import json\nimport struct\n',1)
        code=code.replace('EXPECTED = ',HELPER+'ALL_TRANSFORMS = '+repr(transforms)+'\nEXPECTED = ',1)
        old="near(first, wanted['first'][index], 0.01) and near(last, wanted['last'][index], 0.01)"
        assert code.count(old)==1
        code=code.replace(old,"key_near(first, wanted['first'][index]) and key_near(last, wanted['last'][index])")
        before="        first, last = keys[0].get_value(), keys[-1].get_value()"
        code=code.replace(before,"""        for key_index, key in enumerate(keys):
            authored = ALL_TRANSFORMS[name][key_index][1][index]
            require(key_near(key.get_value(), authored), name + ' exact observable transform key',
                    [index, key_index, key.get_value(), authored])
"""+before)
        compile(code,folder,'exec')
        tree=ast.parse(code)
        methods={n.func.attr for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute)}
        assert not methods&{'save_asset','save_loaded_asset','set_editor_property','add_track','add_section','spawn_actor_from_class'}
        target=OUT/(folder+'.py');target.write_text(code)
        records.append(dict(script=str(target.relative_to(ROOT)),sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
            source_v3_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),evidence_sha256=hashlib.sha256(evidence.read_bytes()).hexdigest(),
            observed_keys=len(values),max_absolute_rounding=max(abs(v['delta']) for v in values)))
    (OUT/'manifest.json').write_text(json.dumps(dict(scope='Read-only final acceptance; full binding values and every transform key at observed float32 precision',records=records),indent=2)+'\n')
    print('BODY_ACCEPTANCE_V4_READY',OUT)


if __name__=='__main__':prepare()
