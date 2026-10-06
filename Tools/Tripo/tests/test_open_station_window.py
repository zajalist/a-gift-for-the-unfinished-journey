"""Offline geometry checks; does not claim rendered station acceptance."""
from pathlib import Path
import sys
import numpy as np
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import open_station_window as window
import tripo_ingest as ti


def area(polys):
    return sum(np.linalg.norm(np.cross(t[1,:3]-t[0,:3],t[2,:3]-t[0,:3]))/2
               for poly in polys for t in window.triangulate(poly))


def test_box_subtraction_retains_outside_and_clips_crossing_triangle():
    tri=np.array([[-2.,-2.,0.],[2.,-2.,0.],[0.,2.,0.]])
    assert area(window.subtract_box(tri,[-.5,-.5,-1],[.5,.5,1])) == pytest.approx(7)
    assert area(window.subtract_box(tri,[5,5,5],[6,6,6])) == pytest.approx(8)
    assert window.subtract_box(tri,[-3,-3,-1],[3,3,1]) == []


def test_intersection_interpolates_uv_and_does_not_change_winding():
    tri=np.array([[-2.,-2.,0.,0.,0.],[2.,-2.,0.,1.,0.],[0.,2.,0.,.5,1.]])
    pieces=window.subtract_box(tri,[-.5,-.5,-1],[.5,.5,1])
    for poly in pieces:
        for t in window.triangulate(poly):
            assert np.cross(t[1,:3]-t[0,:3],t[2,:3]-t[0,:3])[2] > 0
            assert np.allclose(t[:,3],(t[:,0]+2)/4)
            assert np.allclose(t[:,4],(t[:,1]+2)/4)


def load_triangles(path):
    g,b=ti.read_glb(path)
    mi,m=ti._mesh_instances(g)[0]
    p=g['meshes'][mi]['primitives'][0]
    v=(ti.read_accessor(g,b,p['attributes']['POSITION'])@m[:3,:3].T+m[:3,3])*100
    indices=ti.read_accessor(g,b,p['indices']).astype(int).reshape(-1,3)
    return v[indices]


def hit_count(tris,x,y):
    # Window ray from existing interior recess toward the outside, glTF -Z.
    origin=np.array([x,y,-80.]);direction=np.array([0.,0.,-1.])
    e1,e2=tris[:,1]-tris[:,0],tris[:,2]-tris[:,0]
    h=np.cross(np.broadcast_to(direction,e2.shape),e2)
    det=np.einsum('ij,ij->i',e1,h)
    valid=abs(det)>1e-8
    inv=np.zeros_like(det);inv[valid]=1/det[valid]
    s=origin-tris[:,0];u=inv*np.einsum('ij,ij->i',s,h)
    q=np.cross(s,e1);v=inv*np.einsum('j,ij->i',direction,q)
    distance=inv*np.einsum('ij,ij->i',e2,q)
    return np.count_nonzero(valid&(u>=0)&(v>=0)&(u+v<=1)&(distance>0)&(distance<150))


@pytest.mark.skipif(not window.OUTPUT.exists(),reason='Generated source asset not staged')
def test_real_window_pane_rays_are_open_and_brass_mullions_remain():
    before,after=load_triangles(window.SOURCE),load_triangles(window.OUTPUT)
    for lo,hi in window.PANES:
        x,y=(lo[0]+hi[0])/2,(lo[1]+hi[1])/2
        assert hit_count(before,x,y)>0
        assert hit_count(after,x,y)==0
    for x,y in [(-7,150),(20,132),(-7,105),(-58,155),(60,100)]:
        assert hit_count(after,x,y)>0,(x,y)
