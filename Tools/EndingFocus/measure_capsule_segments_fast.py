"""Exact finite body-edge/Carrier-triangle crossings with spatial broad phase.

Offline source authoring measurement, not installed asset or visual acceptance.
The broad phase cannot omit a triangle intersecting a finite segment: its
centroid is within half the segment length plus its farthest vertex radius.
"""
import os
os.environ['OPENBLAS_NUM_THREADS']='1';os.environ['OMP_NUM_THREADS']='1'
import numpy as np
from scipy.spatial import cKDTree
import measure_capsule_triangles as slow
body=slow.body

class Sweep:
    def __init__(self):
        self.parts=slow.pieces();_,_,f=body.source_body()
        self.edges=np.unique(np.sort(np.concatenate([f[:,[0,1]],f[:,[1,2]],f[:,[2,0]]]),axis=1),axis=0)
        self.cached={}

    def geometry(self,t):
        angle=slow.r.lid_angle(t)
        key=round(angle,8)
        if key not in self.cached:
            mesh,labels=slow.at_time(self.parts,t);tri=mesh.vertices[mesh.faces]
            centre=tri.mean(axis=1);radius=np.linalg.norm(tri-centre[:,None,:],axis=2).max(axis=1)
            groups=[]
            for top in (1.,2.,4.,8.,16.,32.,64.,128.,256.,512.):
                ids=np.where((radius<=top)&(radius>top*.5 if top>1 else radius>=0))[0]
                if len(ids):groups.append((ids,cKDTree(centre[ids]),float(radius[ids].max())))
            assert sum(len(g[0]) for g in groups)==len(tri)
            self.cached[key]=(tri,np.array(labels),groups,tri.min(axis=1),tri.max(axis=1))
        return self.cached[key]

    def measure(self,t,pose):
        v=body.skin(pose);e=self.edges;o=v[e[:,0]];d=v[e[:,1]]-o;length=np.linalg.norm(d,axis=1)
        tri,labels,groups,lo,hi=self.geometry(t)
        pairs_i=[];pairs_j=[]
        for ids,tree,radius in groups:
            candidates=tree.query_ball_point(o+d*.5,length*.5+radius,workers=1)
            counts=np.array([len(x) for x in candidates]);pairs_i.append(np.repeat(np.arange(len(e)),counts))
            pairs_j.append(ids[np.concatenate([np.asarray(x,dtype=np.int32) for x in candidates])])
        ii=np.concatenate(pairs_i);jj=np.concatenate(pairs_j)
        if not len(jj):return dict(t_s=t,intersections=0,by_mesh={},body_edges=len(e),source_triangles=len(tri))
        overlap=np.all(np.minimum(o[ii],o[ii]+d[ii])<=hi[jj],axis=1)&np.all(np.maximum(o[ii],o[ii]+d[ii])>=lo[jj],axis=1)
        ii=ii[overlap];jj=jj[overlap];a=tri[jj,0];b=tri[jj,1]-a;c=tri[jj,2]-a
        h=np.cross(d[ii],c);det=np.einsum('ij,ij->i',b,h);valid=np.abs(det)>1e-9
        ii=ii[valid];jj=jj[valid];a=a[valid];b=b[valid];c=c[valid];h=h[valid];det=det[valid]
        inv=1./det;s=o[ii]-a;u=np.einsum('ij,ij->i',s,h)*inv;q=np.cross(s,b)
        vv=np.einsum('ij,ij->i',d[ii],q)*inv;along=np.einsum('ij,ij->i',c,q)*inv
        hit=(u>=-1e-9)&(vv>=-1e-9)&(u+vv<=1.+1e-9)&(along*length[ii]>.02)&((1.-along)*length[ii]>.02)
        ii=ii[hit];jj=jj[hit];along=along[hit]
        grouped={}
        for name in slow.MODELS:
            sel=labels[jj]==name
            grouped[name]=dict(intersections=int(sel.sum()),unique_body_edges=int(len(np.unique(ii[sel]))),
                samples=[dict(point_cm=(o[i]+d[i]*a).tolist(),body_edge=e[i].tolist(),source_triangle=int(j)) for i,j,a in zip(ii[sel][:6],jj[sel][:6],along[sel][:6])])
        return dict(t_s=t,intersections=len(ii),by_mesh=grouped,body_edges=len(e),source_triangles=len(tri))
