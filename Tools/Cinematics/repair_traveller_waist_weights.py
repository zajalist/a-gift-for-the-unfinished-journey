"""Preserve the complete original FBX and alter only three body weight arrays.

The binary writer retains every unmodified property byte, including geometry,
normals, UVs, bind poses, animation and embedded media. Only absolute node end
offsets and the selected body Hips/UpLeg index/weight arrays may differ.
"""
from dataclasses import dataclass
from pathlib import Path
import hashlib
import json
import struct
import sys
import zlib
import numpy as np

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'Tools/ModelReview'))
from fbx_reader import _read_property, read_fbx

SOURCE=ROOT/'SourceArt/Characters/Traveller/traveller01_animated.fbx'
DEST=ROOT/'SourceArt/Characters/Traveller/Repairs/traveller01_waist_weights_20261001.fbx'


@dataclass
class RawNode:
    name:bytes
    properties:list
    values:list
    children:list
    terminator:bytes

    def child(self,name):
        return next(x for x in self.children if x.name==name.encode())


def parse_binary(blob):
    version=struct.unpack_from('<I',blob,23)[0]
    wide=version>=7500
    fmt='<QQQB' if wide else '<IIIB'
    size=struct.calcsize(fmt)

    def read_node(start):
        end,count,prop_size,name_size=struct.unpack_from(fmt,blob,start)
        if not end:
            return None,start+size
        pos=start+size
        name=blob[pos:pos+name_size];pos+=name_size
        props=[];values=[];prop_start=pos
        for _ in range(count):
            before=pos;value,pos=_read_property(blob,pos)
            props.append(blob[before:pos]);values.append(value)
        assert pos-prop_start==prop_size
        children=[];terminator=b''
        while pos<end:
            before=pos;child,pos=read_node(pos)
            if child is None:
                terminator=blob[before:pos];break
            children.append(child)
        assert pos==end,(name,pos,end)
        return RawNode(name,props,values,children,terminator),end

    nodes=[];pos=27
    while True:
        start=pos;node,pos=read_node(pos)
        if node is None:
            return blob[:27],nodes,blob[start:],fmt
        nodes.append(node)


def encode_binary(header,nodes,footer,fmt):
    size=struct.calcsize(fmt)
    def encode_node(node,start):
        props=b''.join(node.properties)
        offset=start+size+len(node.name)+len(props)
        children=[]
        for child in node.children:
            data=encode_node(child,offset);children.append(data);offset+=len(data)
        end=offset+len(node.terminator)
        return (struct.pack(fmt,end,len(node.properties),len(props),len(node.name))+
                node.name+props+b''.join(children)+node.terminator)
    result=bytearray(header)
    for node in nodes:
        result.extend(encode_node(node,len(result)))
    result.extend(footer)
    return bytes(result)


def replace_array(node,values):
    assert len(node.properties)==1
    code=node.properties[0][:1]
    dtype={b'i':'<i4',b'd':'<f8'}[code]
    values=np.asarray(values,dtype=dtype)
    encoding=struct.unpack_from('<I',node.properties[0],5)[0]
    payload=values.tobytes()
    if encoding:
        assert encoding==1
        payload=zlib.compress(payload)
    node.properties=[code+struct.pack('<III',len(values),encoding,len(payload))+payload]
    node.values=[values]


def all_properties(nodes,path=()):
    result={}
    for index,node in enumerate(nodes):
        key=path+(index,node.name.decode())
        for i,raw in enumerate(node.properties):
            result[key+(i,)]=raw
        result.update(all_properties(node.children,key))
    return result


def build():
    original=SOURCE.read_bytes()
    header,nodes,footer,fmt=parse_binary(original)
    assert encode_binary(header,nodes,footer,fmt)==original,'Lossless parser roundtrip required'
    before=all_properties(nodes)
    scene=read_fbx(original)
    body=next(g for g in scene.geometries.values() if g.name=='tripo_mesh_8efd9b8d.001')
    objects=next(n for n in nodes if n.name==b'Objects')
    by_id={n.values[0]:n for n in objects.children if n.values and isinstance(n.values[0],int)}
    skins={c[1] for c in scene.connections if c[2]==body.id and c[1] in by_id and by_id[c[1]].name==b'Deformer'}
    clusters={by_id[c[1]].values[1].split('\x00')[0].removeprefix('mixamorig:'):by_id[c[1]]
              for c in scene.connections if c[2] in skins and c[1] in by_id and by_id[c[1]].name==b'Deformer'}
    points=body.vertices*(100,-100,100)
    alpha=np.clip((points[:,2]-90)/12,0,1)
    alpha*=(np.abs(points[:,0])<22)&(np.abs(points[:,1])<22)
    alpha=alpha*alpha*(3-2*alpha)
    transferred=np.zeros(len(points))
    for name in ('LeftUpLeg','RightUpLeg'):
        cluster=clusters[name]
        idx=cluster.child('Indexes').values[0]
        weights=cluster.child('Weights').values[0]
        amount=weights*alpha[idx]
        transferred[idx]+=amount
        replace_array(cluster.child('Weights'),weights-amount)
    hips=clusters['Hips']
    indices=hips.child('Indexes').values[0]
    weights=hips.child('Weights').values[0]
    extra=np.setdiff1d(np.flatnonzero(transferred>0),indices)
    new_indices=np.concatenate((indices,extra))
    new_weights=np.concatenate((weights+transferred[indices],transferred[extra]))
    replace_array(hips.child('Indexes'),new_indices)
    replace_array(hips.child('Weights'),new_weights)
    after=all_properties(nodes)
    changed=[key for key in before if before[key]!=after[key]]
    allowed={id(clusters[b].child('Weights')) for b in ('Hips','LeftUpLeg','RightUpLeg')}
    allowed.add(id(hips.child('Indexes')))
    allowed_raw=[]
    def find_allowed(children,path=()):
        for index,node in enumerate(children):
            key=path+(index,node.name.decode())
            if id(node) in allowed:allowed_raw.append(key+(0,))
            find_allowed(node.children,key)
    find_allowed(nodes)
    assert set(changed)==set(allowed_raw),(changed,allowed_raw)
    repaired=encode_binary(header,nodes,footer,fmt)
    # Independently parse derivative and verify every source mesh/connection.
    check=read_fbx(repaired)
    assert scene.connections==check.connections
    for key,mesh in scene.geometries.items():
        other=check.geometries[key]
        assert np.array_equal(mesh.vertices,other.vertices)
        assert np.array_equal(mesh.poly_index,other.poly_index)
        assert np.array_equal(mesh.normals,other.normals)
        assert np.array_equal(mesh.material_ids,other.material_ids)
        for a,b in zip(mesh.uv_layers,other.uv_layers):
            assert np.array_equal(a.uv,b.uv) and np.array_equal(a.index,b.index)
    total=np.zeros(len(points))
    for cluster in clusters.values():
        try:idx=cluster.child('Indexes').values[0];w=cluster.child('Weights').values[0]
        except StopIteration:continue
        assert np.all(w>=0)
        total[idx]+=w
    assert np.max(np.abs(total-1))<0.001
    DEST.parent.mkdir(parents=True,exist_ok=True)
    DEST.write_bytes(repaired)
    report=dict(source=str(SOURCE.relative_to(ROOT)),source_sha256=hashlib.sha256(original).hexdigest(),
        derivative=str(DEST.relative_to(ROOT)),derivative_sha256=hashlib.sha256(repaired).hexdigest(),
        source_bytes=len(original),derivative_bytes=len(repaired),changed_body_vertices=int(np.count_nonzero(transferred)),
        added_hip_influences=len(extra),max_transfer=float(transferred.max()),max_weight_sum_error=float(np.abs(total-1).max()),
        changed_raw_property_paths=[list(x) for x in changed],
        preserved='All other raw FBX property bytes, source geometry, topology, normals, UVs, material assignments, skeleton/bind poses, connections, animations and media',
        transfer='Only body thigh influences -> Hips; smoothstep source component Z90..102cm, |X|/|Y|<22cm')
    (DEST.parent/'waist_weights_manifest.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))
    return report


if __name__=='__main__':build()
