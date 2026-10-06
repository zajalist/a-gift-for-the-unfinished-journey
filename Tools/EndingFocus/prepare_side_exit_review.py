"""Two isolated real side-hatch review clips. No Unreal connection."""
from pathlib import Path
import json
import hashlib
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'Tools/Cinematics'),str(ROOT/'Tools/EndingFocus')]
import samyor_reveal as r
import author_side_hatch_candidate as side
import author_capsule_exit_contacts as transform
from prepare_compact_exit_import import SCRIPT
OUT=ROOT/'Saved/Verification/ending_focus_20261001/side_exit_review_v4'
assert not OUT.exists(),'Preserve prior candidate'
OUT.mkdir(parents=True)
tracks=[b for b in r.ORDER if b!='traveller_rig']
for name,start,end in [('A_Samyor_PullUp_SideContactV4_ReviewOnly',13.5,21.5),('A_Samyor_LegOver_SideContactV4_ReviewOnly',21.5,27.5)]:
    pp=[];state={}
    for i in range(round((end-start)*30)+1):
        t=start+i/30.
        road=side.pose(t,state)
        pp.append(transform.transform_pose(road,r.xinv(r.body_xf(t))))
    data=[]
    for b in tracks:
        kk=[p[b] for p in pp]
        data.append([b,[[round(v,6) for v in k[0]] for k in kk],
                     [[round(v,7) for v in k[1]] for k in kk],[round(v,6) for v in kk[0][2]]])
    dst=OUT/(name+'.json')
    dst.write_text(json.dumps(dict(name=name,frames=len(pp)-1,tracks=data),separators=(',',':')))
    (OUT/(name+'_import.py')).write_text(SCRIPT.format(data_path=str(dst),digest=hashlib.sha256(dst.read_bytes()).hexdigest()))
(OUT/'manifest.json').write_text(json.dumps({p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in OUT.iterdir() if p.is_file()},indent=2))
print('SIDE_EXIT_REVIEW_CLIPS',OUT,'68_tracks',len(tracks),'native_import_calls',2)
