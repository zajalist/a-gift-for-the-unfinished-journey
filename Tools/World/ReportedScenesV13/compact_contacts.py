"""Lossless bounded contact transport; offline preparation/expansion only."""
from __future__ import annotations
import argparse
import ast
import hashlib
import json
from pathlib import Path
import prepare
from unwrap_receipt import unwrap


def spec_from(code):
    assigns = [n for n in ast.parse(code).body if isinstance(n, ast.Assign)
               and any(isinstance(t, ast.Name) and t.id == 'SPEC' for t in n.targets)]
    assert len(assigns) == 1
    return ast.literal_eval(assigns[0].value)


def spec_digest(spec):
    return hashlib.sha256(json.dumps(spec, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


COMPACT = '''
metadata=[];metadata_ids={}
def compact_hit(hit,world_point):
 meta={k:v for k,v in hit.items() if k not in ('point','normal','gap_cm')}
 key=json.dumps(meta,sort_keys=True,separators=(',',':'))
 if key not in metadata_ids:
  metadata_ids[key]=len(metadata);metadata.append(meta)
 assert hit['gap_cm']==world_point[2]-hit['point'][2],'No derived-gap approximation permitted'
 point=[hit['point'][2]] if hit['point'][:2]==world_point[:2] else hit['point']
 return [metadata_ids[key],point,hit['normal']]
compact_samples=[]
for sample in samples:
 g=sample['ground'];w=sample['world']
 landscape=compact_hit(g['landscape'],w)
 support=compact_hit(g['first_real_support'],w)
 support=None if support==landscape else support
 compact_samples.append([sample['bin'],sample['vertex_index'],sample['local'],w,[landscape,support,[compact_hit(hit,w) for hit in g['occluders']]]])
packed={'version':1,'spec_sha256':SPEC_DIGEST,'metadata':metadata,'samples':compact_samples,'complete':len(samples)==len(bins),'rays':trace_count,'geometry':'RENDER_DATA_LOD0 world-space lower vertex per 3x3 footprint bin','wpo_not_in_base_vertices':True,'read_only':True,'saved':False}
encoded=json.dumps(packed,separators=(',',':'))
assert len(encoded)<7800,'Lossless contact packet exceeds transport bound; split rays into multiple calls without dropping samples'
print('REPORTED_CONTACT_COMPACT '+encoded)
'''


def generate(args):
    original = args.script.read_text(encoding='utf-8')
    spec = spec_from(original)
    marker = "print('REPORTED_CONTACT "
    assert original.count(marker) == 1
    code = original[:original.index(marker)] + '\nSPEC_DIGEST='+repr(spec_digest(spec))+'\n'+COMPACT
    result = prepare.write(args.out/'30_contact_compact.py', code)
    prepare.write(args.out/'manifest.json', {'status':'prepared_not_executed',
      'original_script':str(args.script.resolve()), 'original_sha256':prepare.sha(args.script),
      'spec_sha256':spec_digest(spec), 'script':result,
      'lossless':'All basal samples, support/landscape/occluder facts; only exact repeated metadata and derived gap interned.',
      'editor_calls':0})
    print(json.dumps(result))


def expand(args):
    output = unwrap(json.loads(args.raw.read_bytes()))
    lines = [line[len('REPORTED_CONTACT_COMPACT '):] for line in output.splitlines()
             if line.startswith('REPORTED_CONTACT_COMPACT ')]
    assert len(lines) == 1 and len(lines[0]) < 7800
    packed = json.loads(lines[0]); assert packed['version'] == 1
    spec = spec_from(args.script.read_text(encoding='utf-8'))
    assert packed['spec_sha256'] == spec_digest(spec)
    assert packed['complete'] and packed['read_only'] and not packed['saved']
    metadata = packed['metadata']
    def hit(value, world):
        index, point, normal = value
        assert isinstance(index,int) and 0<=index<len(metadata)
        assert len(point) in (1,3) and len(normal)==3
        point = world[:2]+point if len(point)==1 else point
        return dict(metadata[index],point=point,normal=normal,gap_cm=world[2]-point[2])
    samples=[]
    for bin_id,vertex,local,world,ground in packed['samples']:
        landscape=hit(ground[0],world)
        support=dict(landscape) if ground[1] is None else hit(ground[1],world)
        samples.append({'bin':bin_id,'vertex_index':vertex,'local':local,'world':world,
          'ground':{'landscape':landscape,'first_real_support':support,
                    'occluders':[hit(v,world) for v in ground[2]]}})
    assert 3<=len(samples)<=9 and len({tuple(s['bin']) for s in samples})==len(samples)
    full={k:v for k,v in packed.items() if k not in ('version','spec_sha256','metadata','samples')}
    full.update(host=spec['host'],component=spec['component'],pin=spec['pin'],samples=samples)
    envelope={'status':'ok','script':str(args.script.resolve()),'sha256':prepare.sha(args.script),
      'output':'REPORTED_CONTACT '+json.dumps(full,separators=(',',':'))+'\n',
      'native_compact_stdout':output,'raw_receipt':str(args.raw.resolve()),
      'raw_receipt_sha256':prepare.sha(args.raw),'lossless_expansion':True,
      'spec_sha256':packed['spec_sha256']}
    prepare.write(args.out,envelope)
    gaps=[s['ground']['landscape']['gap_cm'] for s in samples]
    print(json.dumps({'out':str(args.out),'host':spec['host']['label'],'samples':len(samples),
      'min_gap_cm':min(gaps),'max_gap_cm':max(gaps),
      'all_first_support_landscape':all(s['ground']['first_real_support']['kind']=='landscape' for s in samples),
      'hlod_occluders':sorted({h['host']['guid'] for s in samples for h in s['ground']['occluders'] if h['kind']=='hlod'})}))


if __name__=='__main__':
    parser=argparse.ArgumentParser();sub=parser.add_subparsers(dest='mode',required=True)
    make=sub.add_parser('generate');make.add_argument('--script',type=Path,required=True);make.add_argument('--out',type=Path,required=True)
    unpack=sub.add_parser('expand');unpack.add_argument('--script',type=Path,required=True);unpack.add_argument('--raw',type=Path,required=True);unpack.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();globals()[args.mode](args)
