"""Prepare bounded SourceActors-object reads from exact native property receipts."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import prepare


READ = '''
source=unreal.find_object(None,SOURCE_PATH)
assert unreal.SystemLibrary.is_valid(source),'Exact SourceActors object is not resident; root must revalidate native property first'
assert source.get_class().get_name()=='WorldPartitionHLODSourceActorsFromCell'
mappings=list(source.get_editor_property('actors'))
assert len(mappings)<=64,'Use explicit pages for larger source lists'
rows=[]
for mapping in mappings:
 assert not expired(),'Membership read exceeded 3.5 second bound'
 rows.append({'guid':mapping.get_editor_property('actor_instance_guid').export_text(),'package':str(mapping.get_editor_property('package')),'actor':str(mapping.get_editor_property('path')),'native_class':str(mapping.get_editor_property('native_class')),'container_transform':mapping.get_editor_property('container_transform').export_text()})
payload={'source_object':SOURCE_PATH,'source_class':source.get_class().get_name(),'mapping_count':len(mappings),'complete':True,'rows':rows,'read_only':True,'loaded':False,'saved':False,'provenance':PROVENANCE}
encoded=json.dumps(payload,separators=(',',':'))
assert len(encoded)<7600,'Transport bound: explicit source-list pages required, do not truncate'
print('REPORTED_DIRECT_SOURCE_MEMBERSHIP '+encoded)
'''


def inner(value):
    for _ in range(10):
        assert isinstance(value,dict) and not value.get('isError') and value.get('ok',True)
        if 'properties' in value:return value
        if 'result' in value:value=value['result'];continue
        assert len(value['content'])==1 and value['content'][0]['type']=='text'
        value=json.loads(value['content'][0]['text'])
    raise AssertionError('Unexpected native property envelope')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--raw',type=Path,action='append',required=True);parser.add_argument('--out',type=Path,required=True);args=parser.parse_args()
    scripts=[]
    for i,raw in enumerate(args.raw):
        data=inner(json.loads(raw.read_bytes()))
        assert data['class']=='WorldPartitionHLODSourceActorsFromCell'
        # The path/class are complete facts from a dedicated typed native read.
        # Its clipped Actors value cannot authorize a membership conclusion.
        path=data['path'];assert path.endswith('.WorldPartitionHLODSourceActorsFromCell_0')
        provenance={'native_receipt':str(raw.resolve()),'sha256':prepare.sha(raw),'native_actors_export_truncated':bool(data.get('_truncated'))}
        scripts.append(prepare.write(args.out/f'10_direct_source_{i:02d}.py',prepare.HEAD+'SOURCE_PATH='+repr(path)+'\nPROVENANCE='+repr(provenance)+'\n'+READ))
    prepare.write(args.out/'manifest.json',{'status':'prepared_not_executed','scripts':scripts,'editor_calls':0,'no_policy_bypass':True,'if_reflection_fails':'Preserve failure; dedicated object_get_property Actors has fixed 512-character output cap and no array pagination. Requires typed bounded HLOD membership API; do not retry with unsafe flags or blanket rebuild.'})
    print(json.dumps({'scripts':scripts}))


if __name__=='__main__':main()
