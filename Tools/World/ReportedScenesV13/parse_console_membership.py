"""Parse a complete synchronous, exact-OUTER UE GETALL log slice offline."""
from __future__ import annotations
import argparse
import json
import re
from pathlib import Path
import prepare


def inner(value):
    for _ in range(10):
        assert isinstance(value,dict) and not value.get('isError') and value.get('ok',True)
        assert not value.get('_truncated')
        if 'executed' in value:return value
        if 'result' in value:value=value['result'];continue
        assert len(value['content'])==1
        value=json.loads(value['content'][0]['text'])
    raise AssertionError('Unexpected command response')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--log-slice',type=Path,required=True);parser.add_argument('--command-receipt',type=Path,required=True);parser.add_argument('--source',required=True);parser.add_argument('--out',type=Path,required=True);args=parser.parse_args()
    response=inner(json.loads(args.command_receipt.read_bytes()))
    assert response['executed'] is True
    outer=args.source.rsplit('.',1)[0]
    expected=f'GETALL WorldPartitionHLODSourceActorsFromCell Actors OUTER={outer} NAME=WorldPartitionHLODSourceActorsFromCell_0'
    assert response['command']==expected,'Exact bounded native command required'
    text=args.log_slice.read_text(encoding='utf-8-sig')
    assert len(text)<100000 and not any(word in text for word in ('Failed to find outer','Unrecognized class','Unrecognized property','[TRUNCATED]'))
    lines=text.splitlines();header=f'WorldPartitionHLODSourceActorsFromCell {args.source}.Actors ='
    starts=[i for i,line in enumerate(lines) if header in line];assert len(starts)==1
    rows=[]
    for line in lines[starts[0]+1:]:
        match=re.search(r'\t(\d+): (\(.*\))$',line)
        if not match:continue
        index=int(match.group(1));assert index==len(rows),'Missing/duplicate array entry'
        exported=match.group(2);assert '...' not in exported
        fields={}
        for key in ('Package','Path','NativeClass'):
            got=re.search(r'(?:^\(|,)'+key+r'="([^"]*)"',exported);assert got, f'Missing {key}'
            fields[key]=got.group(1)
        guid=re.search(r'(?:^\(|,)ActorInstanceGuid=([0-9A-F]{32})(?:,|\))',exported);assert guid
        rows.append({'index':index,'guid':guid.group(1),'package':fields['Package'],'actor':fields['Path'],'native_class':fields['NativeClass'],'complete_export':exported})
    assert 1<=len(rows)<=64,'Unexpected source list; explicit review required'
    prepare.write(args.out,{'source_object':args.source,'rows':rows,'mapping_count':len(rows),'complete_log_slice_required':True,'command_receipt':str(args.command_receipt.resolve()),'command_receipt_sha256':prepare.sha(args.command_receipt),'log_slice':str(args.log_slice.resolve()),'log_slice_sha256':prepare.sha(args.log_slice),'read_only':True,'mutations':0})
    print(json.dumps({'out':str(args.out),'source':args.source,'mapping_count':len(rows),'guids':[row['guid'] for row in rows]}))


if __name__=='__main__':main()
