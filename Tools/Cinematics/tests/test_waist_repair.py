from pathlib import Path
import sys
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import repair_traveller_waist_weights as repair
import validate_waist_repair as validation
import traveller_contacts as contacts
import samyor_reveal as rig
from audit_lower_back_geometry import coverage


def test_binary_roundtrip_and_only_four_weight_properties_change():
    original=repair.SOURCE.read_bytes()
    header,nodes,footer,fmt=repair.parse_binary(original)
    assert repair.encode_binary(header,nodes,footer,fmt)==original
    before=repair.all_properties(nodes)
    _,after_nodes,_,_=repair.parse_binary(repair.DEST.read_bytes())
    after=repair.all_properties(after_nodes)
    changed=[key for key in before if before[key]!=after[key]]
    assert len(changed)==4
    assert [k[-2] for k in changed].count('Indexes')==1
    assert [k[-2] for k in changed].count('Weights')==3


def test_derivative_preserves_reference_surface_and_weight_normalization():
    entries=validation.derivative_entries()
    weights=np.zeros(20588)
    for _,ids,w,_ in entries:
        assert np.all(w>=0)
        weights[ids]+=w
    assert np.max(np.abs(weights-1))<2e-7
    assert np.max(np.abs(validation.skin(rig.REF_LOCAL,entries)-contacts.skin(rig.REF_LOCAL)))<1e-10


def test_actual_walk_pose_exposes_original_gap_and_repaired_coverage_is_complete():
    pose=validation.samples()['A_Traveller_SlowWalk@1.0']
    _,_,triangles=contacts.source_body()
    assert coverage(contacts.skin(pose),triangles,40)['missing_front_facing']>=40
    assert coverage(validation.skin(pose,validation.derivative_entries()),triangles,40)['missing_front_facing']==0
