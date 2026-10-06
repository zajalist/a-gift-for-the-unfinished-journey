"""Extract complete native terrain receipts; never use socket_fitted_frame."""
from pathlib import Path
import json,hashlib,math
ROOT=Path(__file__).resolve().parents[2]
SOURCE=ROOT/'Saved/Verification/live_completion_20261001/CIN19_survey_v14'
OUT=ROOT/'Saved/Verification/ending_focus_20261001/side_exit_actual_v6'

def unwrap(value):
    if isinstance(value,dict):
        if 'stdout' in value and value.get('output_complete') is True:return value
        for v in value.values():
            got=unwrap(v)
            if got:return got
    elif isinstance(value,list):
        for v in value:
            got=unwrap(v)
            if got:return got
    elif isinstance(value,str) and value.lstrip().startswith('{'):
        return unwrap(json.loads(value))

def extract():
    points={}; provenance={};frame=None
    for name in ('centres_explicit_transform.json','heeltoe_a.json','heeltoe_b.json'):
        path=SOURCE/name;data=unwrap(json.loads(path.read_text()));assert data
        provenance[name]=hashlib.sha256(path.read_bytes()).hexdigest()
        for line in data['stdout'].splitlines():
            if line.startswith('CIN19_ACTUAL_FRAMES '):
                frame=json.loads(line.split(' ',1)[1])['sequence'][0]['transform_origin']
            if line.startswith('CIN19_ACTUAL_GROUND '):
                rows=json.loads(line.split(' ',1)[1])['points']
                for row in rows:
                    g=row['ground'];assert g and 'LandscapeStreamingProxy' in g['actor']
                    points[row['name']]=dict(point_cm=g['frame_local'],normal=g['frame_normal'],actor=g['actor'],actual_native_contact=True)
    assert len(points)==20 and frame
    for name,p in points.items():
        if '_heel' in name or '_toe' in name:continue
        if name.startswith('staff'):
            p.update(footprint_reviewed=True,footprint_scope='Point support for measured staff tip; no boot footprint implied')
            continue
        residual=[]
        for suffix in ('heel','toe'):
            q=points[name+'_'+suffix]['point_cm']
            residual.append(abs(sum((q[k]-p['point_cm'][k])*p['normal'][k] for k in range(3))))
        assert max(residual)<.5,(name,residual)
        p.update(footprint_reviewed=True,heel_toe_plane_residual_cm=residual,
                 footprint_scope='Actual centre/heel/toe longitudinal support only; lateral boot corners not surveyed')
    result=dict(frame=frame,supports=points,provenance_sha256=provenance,
                production_accepted=False,scope='Controlled CIN19 preview placement; actual ending placement requires matching support survey')
    OUT.mkdir(exist_ok=True);(OUT/'actual_supports.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(dict(points=len(points),max_heel_toe_residual_cm=max(max(p.get('heel_toe_plane_residual_cm',[0])) for p in points.values()),frame=frame)))
    return result

if __name__=='__main__':extract()
