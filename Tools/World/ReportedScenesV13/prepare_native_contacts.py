"""Convert one actual native catalog into compact contact scripts, offline."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from types import SimpleNamespace
import prepare
import compact_contacts
from unwrap_receipt import unwrap


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--raw',type=Path,required=True)
    parser.add_argument('--catalog-script',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    output=unwrap(json.loads(args.raw.read_bytes()))
    envelope={'status':'ok','script':str(args.catalog_script.resolve()),
              'sha256':prepare.sha(args.catalog_script),'output':output,
              'raw_receipt':str(args.raw.resolve()),'raw_receipt_sha256':prepare.sha(args.raw)}
    catalog=args.out/'native_catalog.json';prepare.write(catalog,envelope)
    data=prepare.receipt(catalog,'REPORTED_CATALOG')
    assert len(data['rows'])==1 and data['all_component_instances_pinned']
    prepare.measure(SimpleNamespace(receipt=catalog,out=args.out/'full_contacts'))
    manifest=json.loads((args.out/'full_contacts/manifest.json').read_bytes())
    compact=[]
    for i,item in enumerate(manifest['scripts']):
        folder=args.out/f'compact_{i:02d}'
        compact_contacts.generate(SimpleNamespace(script=Path(item['script']),out=folder))
        compact.append(json.loads((folder/'manifest.json').read_bytes())['script'])
    prepare.write(args.out/'contact_batch.json',{'status':'prepared_not_executed',
      'host':data['rows'][0]['host'],'scripts':compact,'unresolved':manifest['unresolved'],
      'root_only':True,'execute_separately':True,'editor_calls':0,
      'cart_warning':'Measure every mesh/component first. Never lower cart bags or rails independently; root chooses actual wheels and one shared actor shift.'})
    print(json.dumps({'host':data['rows'][0]['host']['label'],'compact_scripts':compact,'unresolved':manifest['unresolved']}))


if __name__=='__main__':main()
