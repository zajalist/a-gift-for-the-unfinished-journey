"""Prepare only: isolated six-way texture/material prototype for root's editor owner.

    python Tools/Look/six_way/prepare_smoke_material.py prepare
    python Tools/Look/six_way/prepare_smoke_material.py check

No network, Unreal calls, asset writes, scene placement or native changes here.
The emitted editor chunks create new prototype assets; existing assets are never rebuilt.
"""
from __future__ import annotations
import argparse
import ast
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
OUT = ROOT / 'Saved/Verification/six_way_smoke_20261001/material_v3'
FOLDER = '/Game/SaskartaGaea/Look/Storm/SixWayPrototypeV1'
MATERIAL = FOLDER + '/M_DustSixWay'
SOURCE = ROOT / 'Saved/SourceAssets/UnitySixWay'
MAPS = {
    'P': ('FE6029C70B181D6D5A7F35518622FE35909B016F10C53F1E0E0E067EB48056D1', 'T_DustSixWay_Positive'),
    'N': ('8AA0F750189E69A0BAC7FD17918A025BAA2B9AEB6A08F5655551613AF91D8E36', 'T_DustSixWay_Negative'),
}

def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

MATERIAL_CODE = r'''
import unreal
eal=unreal.EditorAssetLibrary
mel=unreal.MaterialEditingLibrary
folder=__FOLDER__
name='M_DustSixWay'
assert not eal.does_asset_exist(folder+'/'+name), 'Prototype already exists; preserve it and inspect before retrying'
textures=[unreal.load_asset(folder+'/'+n) for n in ('T_DustSixWay_Positive','T_DustSixWay_Negative')]
assert all(textures)
for texture in textures:
    assert texture.get_editor_property('srgb') is False
    assert texture.get_editor_property('compression_settings') == unreal.TextureCompressionSettings.TC_BC7
mat=unreal.AssetToolsHelpers.get_asset_tools().create_asset(name,folder,unreal.Material,unreal.MaterialFactoryNew())
assert mat is not None
mat.set_editor_property('material_domain',unreal.MaterialDomain.MD_SURFACE)
mat.set_editor_property('blend_mode',unreal.BlendMode.BLEND_TRANSLUCENT)
mat.set_editor_property('shading_model',unreal.MaterialShadingModel.MSM_UNLIT)
mat.set_editor_property('two_sided',True)
mel.set_base_material_usage(mat,unreal.MaterialUsage.MATUSAGE_NIAGARA_SPRITES,True)
def node(cls,x,y):
    value=mel.create_material_expression(mat,cls,x,y)
    assert value is not None
    return value
def link(source,output,destination,pin):
    assert mel.connect_material_expressions(source,output,destination,pin),str((output,pin))
def scalar(name,value,x,y):
    result=node(unreal.MaterialExpressionScalarParameter,x,y)
    result.set_editor_property('parameter_name',name)
    result.set_editor_property('default_value',value)
    return result
def custom(code,pins,output,x,y):
    result=node(unreal.MaterialExpressionCustom,x,y)
    result.set_editor_property('code',code)
    result.set_editor_property('output_type',output)
    inputs=[]
    for name in pins:
        item=unreal.CustomInput()
        item.set_editor_property('input_name',name)
        inputs.append(item)
    result.set_editor_property('inputs',inputs)
    return result
uv=node(unreal.MaterialExpressionTextureCoordinate,-1200,-400)
frame=scalar('CloudVariant',0.0,-1200,-260)
# Eight static shapes, not a verified flipbook. Half-texel tile inset avoids neighbour bleed.
tile=custom('float f=clamp(floor(Frame),0,7); float2 cell=float2(fmod(f,2),floor(f/2)); return (cell+lerp(float2(0.0005,0.001),float2(0.9995,0.999),saturate(UV)))/float2(2,4);',
            ['UV','Frame'],unreal.CustomMaterialOutputType.CMOT_FLOAT2,-900,-400)
link(uv,'',tile,'UV'); link(frame,'',tile,'Frame')
samples=[]
for i,texture in enumerate(textures):
    sample=node(unreal.MaterialExpressionTextureSampleParameter2D,-650,-400+i*240)
    sample.set_editor_property('parameter_name','Positive' if i==0 else 'Negative')
    sample.set_editor_property('texture',texture)
    sample.set_editor_property('sampler_type',unreal.MaterialSamplerType.SAMPLERTYPE_LINEAR_COLOR)
    link(tile,'',sample,'UVs')
    samples.append(sample)
sun=node(unreal.MaterialExpressionSkyAtmosphereLightDirection,-900,230)
basis=node(unreal.MaterialExpressionTransform,-650,230)
basis.set_editor_property('transform_source_type',unreal.MaterialVectorCoordTransformSource.TRANSFORMSOURCE_WORLD)
basis.set_editor_property('transform_type',unreal.MaterialVectorCoordTransform.TRANSFORM_TANGENT)
# UE5.8 exposes this sole unnamed Transform input as FName None; use the empty pin.
link(sun,'',basis,'')
tint=node(unreal.MaterialExpressionVectorParameter,-650,520)
tint.set_editor_property('parameter_name','DustTint')
tint.set_editor_property('default_value',unreal.LinearColor(0.20,0.115,0.047,1.0))
ambient=scalar('Ambient',0.22,-650,660)
strength=scalar('SunStrength',0.85,-650,770)
# UE tangent axes are UV-right, UV-down, outward normal. Packed P is right/top/back.
# The six-cardinal-light acceptance confirms the sign before any live deployment.
shade=custom('float3 q=normalize(float3(Sun.x,-Sun.y,-Sun.z)+float3(0,0,0.000001)); float3 p=max(q,0); float3 n=max(-q,0); float s=dot(P,p*p)+dot(N,n*n); return Tint*(max(Ambient,0)+max(Strength,0)*s);',
             ['P','N','Sun','Tint','Ambient','Strength'],unreal.CustomMaterialOutputType.CMOT_FLOAT3,-250,80)
for source,output,pin in [(samples[0],'RGB','P'),(samples[1],'RGB','N'),(basis,'','Sun'),
                          (tint,'RGB','Tint'),(ambient,'','Ambient'),(strength,'','Strength')]:
    link(source,output,shade,pin)
particles=node(unreal.MaterialExpressionParticleColor,-650,930)
density=scalar('Opacity',0.6,-650,1050)
opacity=custom('return saturate(Alpha)*saturate(Life)*saturate(Density);',['Alpha','Life','Density'],
               unreal.CustomMaterialOutputType.CMOT_FLOAT1,-250,480)
link(samples[0],'A',opacity,'Alpha'); link(particles,'A',opacity,'Life'); link(density,'',opacity,'Density')
fade=node(unreal.MaterialExpressionDepthFade,30,480)
fade.set_editor_property('fade_distance_default',200.0)
link(opacity,'',fade,'Opacity')
assert mel.connect_material_property(shade,'',unreal.MaterialProperty.MP_EMISSIVE_COLOR)
assert mel.connect_material_property(fade,'',unreal.MaterialProperty.MP_OPACITY)
errors=list(mel.recompile_material(mat))
assert not errors,str(errors)
print('SIX_WAY_MATERIAL_CREATED compile_errors0 nodes'+str(mel.get_num_material_expressions(mat)))
'''

def scripts():
    output={}
    for index,(direction,(wanted,name)) in enumerate(MAPS.items()):
        source=SOURCE / f'TX_Pyro_Clouds_A_2x4_{direction}_Straight.tga'
        assert digest(source).upper()==wanted,source
        asset=FOLDER+'/'+name
        output[f'{10+index}_import_{direction}.py']=f'''import unreal
eal=unreal.EditorAssetLibrary
assert not eal.does_asset_exist({asset!r}), 'Prototype texture already exists; preserve before retry'
task=unreal.AssetImportTask()
task.set_editor_property('filename',{str(source)!r})
task.set_editor_property('destination_path',{FOLDER!r})
task.set_editor_property('destination_name',{name!r})
task.set_editor_property('replace_existing',False)
task.set_editor_property('automated',True)
task.set_editor_property('save',False)
task.set_editor_property('factory',unreal.TextureFactory())
unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
texture=unreal.load_asset({asset!r})
assert isinstance(texture,unreal.Texture2D)
texture.set_editor_property('srgb',False)
texture.set_editor_property('compression_settings',unreal.TextureCompressionSettings.TC_BC7)
texture.set_editor_property('max_texture_size',2048)
texture.set_editor_property('compression_no_alpha',False)
print('SIX_WAY_TEXTURE_{direction}_IMPORTED linear RGBA BC7 max2048')
'''
    output['20_material.py']=MATERIAL_CODE.replace('__FOLDER__',repr(FOLDER))
    assets=[FOLDER+'/'+name for _,name in MAPS.values()]+[MATERIAL]
    for i,asset in enumerate(assets):
        output[f'9{i}_save.py']=f'''import unreal
asset=unreal.load_asset({asset!r})
assert asset is not None
assert unreal.EditorAssetLibrary.save_loaded_asset(asset,False) is True
print('SIX_WAY_SAVED_{i} saved True')
'''
    output['99_read.py']=f'''import unreal
folder={FOLDER!r}
for name in ('T_DustSixWay_Positive','T_DustSixWay_Negative'):
    texture=unreal.load_asset(folder+'/'+name)
    assert isinstance(texture,unreal.Texture2D)
    assert texture.get_editor_property('srgb') is False
    assert texture.get_editor_property('compression_settings')==unreal.TextureCompressionSettings.TC_BC7
    assert texture.get_editor_property('max_texture_size')==2048
    assert texture.get_editor_property('compression_no_alpha') is False
material=unreal.load_asset(folder+'/M_DustSixWay')
assert isinstance(material,unreal.Material)
assert material.get_editor_property('blend_mode')==unreal.BlendMode.BLEND_TRANSLUCENT
assert material.get_editor_property('shading_model')==unreal.MaterialShadingModel.MSM_UNLIT
assert material.get_editor_property('two_sided') is True
assert unreal.MaterialEditingLibrary.get_num_material_expressions(material)==15
print('SIX_WAY_MATERIAL_METADATA_OK two linear maps and two-sample unlit prototype; visual acceptance pending')
'''
    return output

def prepare():
    assert not OUT.exists(), 'Preserve every prepared revision; choose a new OUT to supersede it'
    chunks=scripts()
    OUT.mkdir(parents=True)
    for name,code in chunks.items():
        ast.parse(code,filename=name)
        (OUT/name).write_text(code,encoding='utf-8')
    inputs=[Path(__file__).resolve(),HERE/'read_niagara_inventory.py',SOURCE/'PROVENANCE.md']
    inputs += [SOURCE/f'TX_Pyro_Clouds_A_2x4_{direction}_Straight.tga' for direction in MAPS]
    manifest={'status':'prepared_not_installed','destination':FOLDER,
              'source_sha256':{str(p):digest(p) for p in inputs},
              'script_sha256':{name:digest(OUT/name) for name in chunks},
              'order':list(chunks),'runtime_integration':False,
              'acceptance_pending':['alpha sense','2x4 atlas orientation','six cardinal lights',
                                    'sprite tangent basis under rotation','Niagara template inventory','GPU/overdraw']}
    (OUT/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    check()

def check():
    manifest=json.loads((OUT/'manifest.json').read_text())
    for name,wanted in manifest['source_sha256'].items():
        assert digest(name)==wanted,'stale source '+name
    assert {p.name for p in OUT.glob('*.py')}==set(manifest['script_sha256'])
    for name,wanted in manifest['script_sha256'].items():
        assert digest(OUT/name)==wanted,'stale script '+name
        ast.parse((OUT/name).read_text(),filename=name)
    print('SIX_WAY_PREPARED_PACKET_OK',len(manifest['script_sha256']),digest(OUT/'manifest.json'))

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['prepare','check'])
    command=parser.parse_args().command
    prepare() if command=='prepare' else check()
