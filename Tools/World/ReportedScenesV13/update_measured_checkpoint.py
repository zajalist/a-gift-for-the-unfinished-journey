"""Summarize current complete world contacts and saved ending review evidence."""
import json
from pathlib import Path
import prepare
from unwrap_receipt import unwrap


rows=[]
for folder in ('R03_contacts_001_actual_v14','R03_contacts_002_compact_v1','R03_contacts_003_compact_v1','R03_contacts_004_actual_v14','R03_contacts_005_actual_v14','R03_cart000_actual_v14'):
    receipt=prepare.OUT/folder/'native_contacts.json'
    data=prepare.receipt(receipt,'REPORTED_CONTACT')
    gaps=[s['ground']['landscape']['gap_cm'] for s in data['samples']]
    rows.append({'label':data['host']['label'],'guid':data['host']['guid'],'samples':len(gaps),'min_gap_cm':min(gaps),'max_gap_cm':max(gaps),'keep_source_z':min(gaps)<=5,'receipt':str(receipt),'receipt_sha256':prepare.sha(receipt),'whole_cart_rigid_review_required':data['host']['label'].endswith('_000')})
ending=[]
for relative in ('legover_saved.json','A_Samyor_PullUp_SideContactV4_ReviewOnly_InlineV5/90_save.py.json'):
    raw=prepare.ROOT/'Saved/Verification/live_completion_20261001/exit_inline_v5'/relative
    stdout=unwrap(json.loads(raw.read_bytes()))
    lines=[line[len('EXIT_SAVED '):] for line in stdout.splitlines() if line.startswith('EXIT_SAVED ')]
    assert len(lines)==1
    native=json.loads(lines[0]);assert len(native['tracks'])==68 and native['production_accepted'] is False
    asset_file=prepare.ROOT/'Content'/(native['asset'][6:]+'.uasset');assert asset_file.is_file()
    ending.append({'asset':native['asset'],'length_seconds':native['length'],'tracks':len(native['tracks']),'frames':native['frames'],'receipt':str(raw),'receipt_sha256':prepare.sha(raw),'disk_sha256':prepare.sha(asset_file),'production_accepted':False,'main_sequence_changed':False})
prepare.write(prepare.OUT/'R03_complete_contact_audit_v14/summary.json',{'world':rows,'ending_review_clips':ending,'scope':'Complete source contacts and two saved review assets only; no gameplay/render acceptance or world mutation.'})
print(json.dumps({'world':rows,'ending_review_clips':ending}))
