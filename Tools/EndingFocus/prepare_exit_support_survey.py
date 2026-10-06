"""Generate one bounded read-only runtime socket and eight-support readback."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
folder=ROOT/'Saved/Verification/ending_focus_20261001/side_exit_native_v5'
folder.mkdir(exist_ok=True)
s=(ROOT/'Saved/Verification/ending_focus_20261001/capsule_exit_full_v3/00_runtime_socket_frame.py').read_text()
start=s.index("points=[('rear_tyre_column'")
end=s.index('\nactors=',start)
s=s[:start]+'''points=[('left_initial',(-285.,-118.,0.)),('right_initial',(-255.,-118.,0.)),
        ('left_mid',(-314.,-126.,0.)),('right_mid',(-344.,-94.,0.)),
        ('left_final',(-352.5,-126.,0.)),('right_final',(-359.5,-94.,0.)),
        ('staff_old',(-302.,-138.,.4)),('staff_new',(-278.,-138.,.4))]
# Heel/toe traces accompany each actual ankle column. Initial boots face -Y;
# final boots face +X; the mid step rotates55% toward +X. Do not promote a
# single successful centre hit into a planted-foot certificate.
base_points=list(points)
for name,(x,y,z) in base_points:
    if name.startswith('staff'):continue
    forward=(0.,-1.) if name.endswith('initial') else ((.76,-.65) if name.endswith('mid') else (1.,0.))
    for suffix,length in [('heel',-7.),('toe',13.)]:
        points.append((name+'_'+suffix,(x+forward[0]*length,y+forward[1]*length,z)))'''+s[end:]
s=s.replace("frame_local=xyz(frame.inverse_transform_location(h[5])))", "frame_local=xyz(frame.inverse_transform_location(h[5])),\n            frame_normal=xyz(frame.rotation.inverse().rotate_vector(h[7])))")
(folder/'00_actual_exit_supports.py').write_text(s)
print(folder/'00_actual_exit_supports.py')
