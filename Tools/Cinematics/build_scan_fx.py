"""The carrier's sensor scan wave (LANE5, user 2026-09-28): MPC_Saskarta_Scan + M_PP_SensorScan.

    python Tools/Cinematics/build_scan_fx.py OUT_DIR      # writes the two python_run chunks (10_mpc.py, 20_material.py)

The effect is its own post-process blendable (independent of LANE4's CRT sensor filter): from the world
position of each pixel, an expanding ring sweeps out from ScanOrigin (the carrier) across the terrain:
- a thin bright leading edge (with a slight red/blue fringe: the chromatic shimmer) and a fading trail;
- inside the trail: topographic contour lines every 2 m of height, a faint 10 m world grid, and edge
  highlights from the surface normal's screen-space change (rocks, trees, ruins);
- a "focus" disc (FocusPos / FocusRadius / FocusColor / FocusAmount) recolours the contours there: the red
  rejected candidate, the green detected summit;
- a screen-space reticle (RetAlpha / RetSize / RetColor): the scan bracket, and later the subtle waypoint.
Sky pixels (depth > 20 km) are never touched. With Intensity 0 and RetAlpha 0 the pass is a copy.

Parameters (MPC_Saskarta_Scan), animated by the cinematic's MPC track or by BP:
  scalars: ScanRadius (cm), ScanWidth (trail length, cm), Intensity, FocusRadius (cm), FocusAmount,
           RetAlpha, RetSize (fraction of the screen height)
  vectors: ScanOrigin (xyz cm), Tint, FocusPos (xyz cm), FocusColor, RetColor
Blendable location: after tonemapping (LDR colours, crisp reticle). Cost: one full-screen pass, a few ALU
lines and no texture taps beyond the scene colour/depth: well under 0.3 ms at 1080p. It is only bound where
it is used: the cinematic's cameras (their post-process blendables) and, if added, the gameplay pulse.
"""
from __future__ import annotations

import sys
from pathlib import Path

FOLDER = "/Game/SaskartaGaea/Look/Scan"
MPC = "MPC_Saskarta_Scan"
MAT = "M_PP_SensorScan"
CYAN = (0.55, 0.95, 1.0)
SCALARS = [("ScanRadius", 0.0), ("ScanWidth", 30000.0), ("Intensity", 0.0), ("FocusRadius", 15000.0),
           ("FocusAmount", 0.0), ("RetAlpha", 0.0), ("RetSize", 0.08)]
VECTORS = [("ScanOrigin", (0.0, 0.0, 0.0)), ("Tint", CYAN), ("FocusPos", (0.0, 0.0, 0.0)),
           ("FocusColor", (1.0, 0.25, 0.2)), ("RetColor", (0.95, 0.75, 0.4))]

HLSL = r'''float3 col = SceneColor.rgb;
float3 wp = WP.xyz;
float dep = Depth.x;
float sky = dep > 2000000.0 ? 0.0 : 1.0;
float d = length(wp.xy - Origin.xy);
float behind = Radius.x - d;
float lead = saturate(1.0 - abs(behind) / min(Width.x * 0.01 + 1.0, 300.0));
float trail = behind > 0.0 ? exp(-behind / max(Width.x, 1.0)) : 0.0;
float cz = frac(wp.z / 200.0);
float fz = fwidth(wp.z / 200.0) + 0.0001;
float lz = (1.0 - smoothstep(0.0, fz * 1.5, min(cz, 1.0 - cz))) * saturate(1.0 - fz * 3.0);
float2 gg = frac(wp.xy / 1000.0);
float2 fg = fwidth(wp.xy / 1000.0) + 0.0001;
float2 lg = (1.0 - smoothstep(float2(0.0, 0.0), fg * 1.2, min(gg, 1.0 - gg))) * saturate(1.0 - fg * 4.0);
float grid = max(lg.x, lg.y);
float3 nrm = normalize(cross(ddx(wp), ddy(wp)));
float edge = saturate(length(fwidth(nrm)) * 1.5);
float focus = saturate(1.0 - length(wp.xy - FocusPos.xy) / max(FocusRadius.x, 1.0)) * FocusAmount.x * sky;
float3 tint = lerp(Tint.rgb, FocusColor.rgb, saturate(focus * 3.0));
float k = sky * Intensity.x;
col += tint * (lead * 1.3 + trail * (lz * 1.1 + grid * 0.1 + edge * 0.6)) * k;
col = lerp(col, FocusColor.rgb * 0.9, saturate(focus * 0.4));
col += FocusColor.rgb * focus * (lz * 1.2 + edge * 1.4);
col.r += lead * k * 0.18;
col.b += lead * k * 0.3;
float2 p = (UV.xy - 0.5) * float2(Aspect.x / max(Aspect.y, 1.0), 1.0);
float rr = length(p);
float ring = 1.0 - smoothstep(0.0012, 0.0026, abs(rr - RetSize.x));
float arms = (abs(p.x) < 0.0012 || abs(p.y) < 0.0012) ? 1.0 : 0.0;
arms *= step(RetSize.x * 1.12, rr) * step(rr, RetSize.x * 1.5);
float dotc = 1.0 - smoothstep(0.0015, 0.003, rr);
col = lerp(col, RetColor.rgb, saturate((ring + arms + dotc) * RetAlpha.x));
return col;'''

PINS = ["SceneColor", "Depth", "WP", "UV", "Aspect", "Origin", "Radius", "Width", "Intensity", "Tint",
        "FocusPos", "FocusRadius", "FocusColor", "FocusAmount", "RetAlpha", "RetSize", "RetColor"]

MPC_CHUNK = f'''import unreal
eal = unreal.EditorAssetLibrary
path = '{FOLDER}/{MPC}'
if eal.does_asset_exist(path):
    mpc = eal.load_asset(path)
else:
    mpc = unreal.AssetToolsHelpers.get_asset_tools().create_asset('{MPC}', '{FOLDER}', unreal.MaterialParameterCollection, unreal.MaterialParameterCollectionFactoryNew())
sc = []
for n, v in {SCALARS!r}:
    p = unreal.CollectionScalarParameter()
    p.set_editor_property('parameter_name', n)
    p.set_editor_property('default_value', v)
    sc.append(p)
vc = []
for n, v in {VECTORS!r}:
    p = unreal.CollectionVectorParameter()
    p.set_editor_property('parameter_name', n)
    p.set_editor_property('default_value', unreal.LinearColor(v[0], v[1], v[2], 1.0))
    vc.append(p)
mpc.set_editor_property('scalar_parameters', sc)
mpc.set_editor_property('vector_parameters', vc)
print('MPC', len(mpc.get_editor_property('scalar_parameters')), len(mpc.get_editor_property('vector_parameters')), 'saved', eal.save_asset(path, False))
'''

MAT_CHUNK = f'''import unreal
mel = unreal.MaterialEditingLibrary
eal = unreal.EditorAssetLibrary
Q = unreal.PropertyAccessChangeNotifyMode.NEVER
path = '{FOLDER}/{MAT}'
if eal.does_asset_exist(path):
    mat = eal.load_asset(path)
else:
    mat = unreal.AssetToolsHelpers.get_asset_tools().create_asset('{MAT}', '{FOLDER}', unreal.Material, unreal.MaterialFactoryNew())
mat.set_editor_property('material_domain', unreal.MaterialDomain.MD_POST_PROCESS)
mat.set_editor_property('blendable_location', unreal.BlendableLocation.BL_SCENE_COLOR_AFTER_TONEMAPPING)
for old in mel.get_material_expressions(mat):
    mel.delete_material_expression(mat, old)
mpc = eal.load_asset('{FOLDER}/{MPC}')
cu = mel.create_material_expression(mat, unreal.MaterialExpressionCustom, -300, 0)
cu.set_editor_property('description', 'SensorScan', Q)
cu.set_editor_property('output_type', unreal.CustomMaterialOutputType.CMOT_FLOAT3, Q)
cu.set_editor_property('code', {HLSL!r}, Q)
pins = []
for n in {PINS!r}:
    ci = unreal.CustomInput()
    ci.set_editor_property('input_name', n)
    pins.append(ci)
cu.set_editor_property('inputs', pins, Q)
y = [-600]
def node(cls):
    y[0] += 70
    return mel.create_material_expression(mat, cls, -900, y[0])
ok = []
col = node(unreal.MaterialExpressionSceneTexture)
col.set_editor_property('scene_texture_id', unreal.SceneTextureId.PPI_POST_PROCESS_INPUT0, Q)
ok.append(mel.connect_material_expressions(col, 'Color', cu, 'SceneColor'))
dep = node(unreal.MaterialExpressionSceneTexture)
dep.set_editor_property('scene_texture_id', unreal.SceneTextureId.PPI_SCENE_DEPTH, Q)
ok.append(mel.connect_material_expressions(dep, 'Color', cu, 'Depth'))
wp = node(unreal.MaterialExpressionWorldPosition)
ok.append(mel.connect_material_expressions(wp, '', cu, 'WP'))
sp = node(unreal.MaterialExpressionScreenPosition)
ok.append(mel.connect_material_expressions(sp, 'ViewportUV', cu, 'UV'))
vs = node(unreal.MaterialExpressionViewSize)
ok.append(mel.connect_material_expressions(vs, '', cu, 'Aspect'))  # ViewSize (w, h): the HLSL divides

print('MAT nodes', mel.get_num_material_expressions(mat), 'links', sum(1 for x in ok if x), '/', len(ok))
'''

MAT2_CHUNK = f'''import unreal
mel = unreal.MaterialEditingLibrary
eal = unreal.EditorAssetLibrary
path = '{FOLDER}/{MAT}'
mat = eal.load_asset(path)
mpc = eal.load_asset('{FOLDER}/{MPC}')
cu = [e for e in mel.get_material_expressions(mat) if e.get_class().get_name() == 'MaterialExpressionCustom'][0]
ok = []
y = [300]
for pin, pname, rgb in (('Origin', 'ScanOrigin', True), ('Radius', 'ScanRadius', False), ('Width', 'ScanWidth', False),
                        ('Intensity', 'Intensity', False), ('Tint', 'Tint', True), ('FocusPos', 'FocusPos', True),
                        ('FocusRadius', 'FocusRadius', False), ('FocusColor', 'FocusColor', True), ('FocusAmount', 'FocusAmount', False),
                        ('RetAlpha', 'RetAlpha', False), ('RetSize', 'RetSize', False), ('RetColor', 'RetColor', True)):
    y[0] += 70
    c = mel.create_material_expression(mat, unreal.MaterialExpressionCollectionParameter, -900, y[0])
    c.set_editor_property('collection', mpc)  # notified: the node resolves its parameter id from the name
    c.set_editor_property('parameter_name', pname)
    ok.append(mel.connect_material_expressions(c, '', cu, pin))
ok.append(mel.connect_material_property(cu, '', unreal.MaterialProperty.MP_EMISSIVE_COLOR))
errs = mel.recompile_material(mat)
print('MAT links', sum(1 for x in ok if x), '/', len(ok), 'errors', len(errs), 'nodes', mel.get_num_material_expressions(mat))
print('MAT saved', eal.save_asset(path, False))
'''


def main(out: Path):
    out.mkdir(parents=True, exist_ok=True)
    (out / "10_mpc.py").write_text(MPC_CHUNK, encoding="utf-8")
    (out / "20_material.py").write_text(MAT_CHUNK, encoding="utf-8")
    (out / "21_material_params.py").write_text(MAT2_CHUNK, encoding="utf-8")
    print("wrote", out / "10_mpc.py", out / "20_material.py")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else Path("Saved/Cinematics/scan_fx"))
