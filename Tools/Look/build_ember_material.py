"""Build M_UI_EmberFire (Task L5): the RetainerBox effect material of the studio intro.

    python Tools/Look/build_ember_material.py check     # offline: HLSL hygiene + editor script + FXC stats
    python Tools/Look/build_ember_material.py build     # create/rebuild the material in the live editor
    python Tools/Look/build_ember_material.py stats     # Hayba material_compile: errors + instruction stats
    python Tools/Look/build_ember_material.py fonts     # import Cinzel / Cormorant if missing (L4's names)
    python Tools/Look/build_ember_material.py defaults IGNITE BURN  # material default Ignite/Burn (renders)

Spec: docs/superpowers/specs/2026-09-26-saskarta-world-sprint-design.md, section 6 ("Studio intro,
credits and the loading hold"). Shaders/EmberFire.hlsl is the source of truth (our own code,
ruling R17); this tool embeds it as the Custom node's code, in the style of
Tools/GameFlow/build_vision_material.py and build_terminal_material.py.

Result: /Game/SaskartaGaea/GameFlow/UI/M_UI_EmberFire
  User Interface domain, blend mode Translucent.
  Custom node "EmberFire" (Float4) -> mask RGB -> Final Color, mask A -> Opacity.
  Custom inputs, in this exact order:
    UV         <- TextureCoordinate 0
    Tex        <- TextureObjectParameter "Texture" (RetainerBox.TextureParameter default)
    Time       <- scalar "Time" (0) + engine Time x scalar "TimeScale" (1)
    Ignite     <- scalar "Ignite" (0)
    Burn       <- scalar "Burn" (0)
    EmberColor <- vector "EmberColor" .RGB, #C8703A = linear (0.578, 0.162, 0.042)
    Fade       <- VertexColor .A (widget opacity)

Editor calls go through Hayba python_run (5 s, banned words checked before sending). Wrap every
editor call in Tools/GameFlow/editor_gate.py acquire/release. `build` saves only this material;
`fonts` saves only the four font packages it creates; `defaults` saves only this material.
"""
import argparse
import json
import os
import pathlib
import re
import shutil
import socket
import struct
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))

from apply_look import python_run, check_banned  # noqa: E402

HLSL_PATH = ROOT / "Shaders" / "EmberFire.hlsl"
PACKAGE_DIR = "/Game/SaskartaGaea/GameFlow/UI"
ASSET_NAME = "M_UI_EmberFire"
ASSET_PATH = f"{PACKAGE_DIR}/{ASSET_NAME}"
TEXTURE_PARAM = "Texture"  # RetainerBox.TextureParameter default; keep them equal
DEFAULT_TEXTURE = "/Engine/EngineResources/Black.Black"
CUSTOM_PINS = ["UV", "Tex", "Time", "Ignite", "Burn", "EmberColor", "Fade"]
SCALARS = [("Ignite", 0.0), ("Burn", 0.0), ("Time", 0.0), ("TimeScale", 1.0)]
EMBER_HEX = "#C8703A"
PARAM_GROUP = "EmberFire"
FONT_DIR = "/Game/SaskartaGaea/GameFlow/UI/Fonts"
# (source ttf under Saved/Fonts, FontFace asset name, composite Font asset name) - L4's planned names.
FONTS = [("Cinzel-VariableFont_wght.ttf", "FF_Cinzel", "F_Cinzel"),
         ("CormorantGaramond-VariableFont_wght.ttf", "FF_Cormorant", "F_Cormorant")]
# Budget stand-in: 0.5 ms at 1440p for the L5 card (323 PS instructions, 2026-09-27); the 2026-09-28
# burn-away rework is allowed 2 ms for the whole card (round 2: FXC 882 slots), so the cap is 1100.
MAX_INSTRUCTIONS = 1100
MAX_SAMPLES = 8


def srgb_to_linear(hex_color):
    h = hex_color.lstrip("#")
    out = []
    for i in (0, 2, 4):
        c = int(h[i:i + 2], 16) / 255.0
        out.append(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
    return tuple(out)


EMBER_LINEAR = srgb_to_linear(EMBER_HEX)


# --------------------------------------------------------------------------- HLSL hygiene

# The policy scanner lowercases the script and drops whitespace before matching, so the HLSL is
# checked in that compact form too. "try" is refused by the project's own apply_look guard.
COMPACT_BANNED = ("try", "getattr", "open(", ".replace(", "new_level(", "importtime", "exec(",
                  "eval(", "compile(", "exit(", "quit(", "vars(", "locals(", "globals(",
                  "setattr(", "delattr(", "__import__", "importlib", "ctypes", "kill",
                  "settrace(", "setprofile(")


def hlsl_problems(text):
    """Every reason the HLSL cannot travel inside the python_run raw string. Empty = fine."""
    problems = []
    if any(ord(c) > 127 for c in text):
        problems.append("non-ASCII character")
    for ch, name in (("\\", "backslash"), ("'", "single quote"), ('"', "double quote")):
        if ch in text:
            problems.append(name)
    if "#" in re.sub(r"//[^\n]*", "", text):
        problems.append("preprocessor directive (the node body cannot hold one)")
    compact = re.sub(r"\s+", "", text).lower()
    problems += [f"banned text {w!r}" for w in COMPACT_BANNED if w in compact]
    for pin in CUSTOM_PINS:
        if not re.search(r"\b" + pin + r"\b", re.sub(r"//[^\n]*", "", text)):
            problems.append(f"pin {pin} is never used in code")
    if "TexSampler" not in text:
        problems.append("TexSampler missing")
    return problems


def texture_sample_count(text):
    """Static texture fetches: calls outside loops count 1, a `for (... k <= N ...)` loop body N."""
    code = re.sub(r"//[^\n]*", "", text)
    total = 0
    loop = re.search(r"for\s*\(\s*int\s+\w+\s*=\s*(\d+)\s*;\s*\w+\s*<=\s*(\d+)[^)]*\)\s*\{(.*?)\}", code, re.S)
    if loop:
        n = int(loop.group(2)) - int(loop.group(1)) + 1
        total += n * loop.group(3).count("Texture2DSample(")
        code = code[:loop.start()] + code[loop.end():]
    return total + code.count("Texture2DSample(")


# --------------------------------------------------------------------------- editor script

EDITOR_SCRIPT = r'''
import unreal

HLSL_SOURCE = r"""__HLSL__"""
ASSET_PATH = "__ASSET_PATH__"
PACKAGE_DIR = "__PACKAGE_DIR__"
ASSET_NAME = "__ASSET_NAME__"
TEXTURE_PARAM = "__TEXTURE_PARAM__"
DEFAULT_TEXTURE = "__DEFAULT_TEXTURE__"
CUSTOM_PINS = __CUSTOM_PINS__
SCALARS = __SCALARS__
EMBER = __EMBER__
GROUP = "__GROUP__"

mel = unreal.MaterialEditingLibrary
eal = unreal.EditorAssetLibrary
QUIET = unreal.PropertyAccessChangeNotifyMode.NEVER

if len(HLSL_SOURCE) < 2000 or "FEmber" not in HLSL_SOURCE or "TexSampler" not in HLSL_SOURCE:
    raise RuntimeError("HLSL_SOURCE holds " + str(len(HLSL_SOURCE)) + " chars: substitution missing")

created = False
if eal.does_asset_exist(ASSET_PATH):
    mat = eal.load_asset(ASSET_PATH)
else:
    tools = unreal.AssetToolsHelpers.get_asset_tools()
    mat = tools.create_asset(ASSET_NAME, PACKAGE_DIR, unreal.Material, unreal.MaterialFactoryNew())
    created = True
if not isinstance(mat, unreal.Material):
    raise RuntimeError("expected a Material at " + ASSET_PATH + ", found " + str(mat))

mat.set_editor_property("material_domain", unreal.MaterialDomain.MD_UI)
mat.set_editor_property("blend_mode", unreal.BlendMode.BLEND_TRANSLUCENT)

removed = 0
for old in mel.get_material_expressions(mat):
    mel.delete_material_expression(mat, old)
    removed += 1


def add(cls, x, y):
    return mel.create_material_expression(mat, cls, x, y)


custom = add(unreal.MaterialExpressionCustom, -350, 0)
custom.set_editor_property("description", "EmberFire", QUIET)
custom.set_editor_property("output_type", unreal.CustomMaterialOutputType.CMOT_FLOAT4, QUIET)
custom.set_editor_property("code", HLSL_SOURCE, QUIET)
pins = []
for pin_name in CUSTOM_PINS:
    pin = unreal.CustomInput()
    pin.set_editor_property("input_name", pin_name)
    pins.append(pin)
custom.set_editor_property("inputs", pins, QUIET)

texcoord = add(unreal.MaterialExpressionTextureCoordinate, -900, -420)
texcoord.set_editor_property("coordinate_index", 0, QUIET)
tex = add(unreal.MaterialExpressionTextureObjectParameter, -900, -340)
tex.set_editor_property("parameter_name", TEXTURE_PARAM, QUIET)
tex.set_editor_property("texture", unreal.load_asset(DEFAULT_TEXTURE), QUIET)
tex.set_editor_property("group", GROUP, QUIET)

params = {}
row = 0
for param_name, default in SCALARS:
    node = add(unreal.MaterialExpressionScalarParameter, -1100, -200 + 80 * row)
    node.set_editor_property("parameter_name", param_name, QUIET)
    node.set_editor_property("default_value", default, QUIET)
    node.set_editor_property("group", GROUP, QUIET)
    node.set_editor_property("sort_priority", row, QUIET)
    params[param_name] = node
    row += 1

time_node = add(unreal.MaterialExpressionTime, -1100, 160)
scaled = add(unreal.MaterialExpressionMultiply, -900, 120)
clock = add(unreal.MaterialExpressionAdd, -700, 60)
ember = add(unreal.MaterialExpressionVectorParameter, -900, 260)
ember.set_editor_property("parameter_name", "EmberColor", QUIET)
ember.set_editor_property("default_value", unreal.LinearColor(EMBER[0], EMBER[1], EMBER[2], 1.0), QUIET)
ember.set_editor_property("group", GROUP, QUIET)
ember.set_editor_property("sort_priority", row, QUIET)
vcolor = add(unreal.MaterialExpressionVertexColor, -900, 360)
rgb = add(unreal.MaterialExpressionComponentMask, -100, -40)
for ch, on in (("r", True), ("g", True), ("b", True), ("a", False)):
    rgb.set_editor_property(ch, on, QUIET)
alpha = add(unreal.MaterialExpressionComponentMask, -100, 80)
for ch, on in (("r", False), ("g", False), ("b", False), ("a", True)):
    alpha.set_editor_property(ch, on, QUIET)

links = [(texcoord, "", custom, "UV"), (tex, "", custom, "Tex"),
         (time_node, "", scaled, "A"), (params["TimeScale"], "", scaled, "B"),
         (params["Time"], "", clock, "A"), (scaled, "", clock, "B"), (clock, "", custom, "Time"),
         (params["Ignite"], "", custom, "Ignite"), (params["Burn"], "", custom, "Burn"),
         (ember, "RGB", custom, "EmberColor"), (vcolor, "A", custom, "Fade"),
         (custom, "", rgb, ""), (custom, "", alpha, "")]
failed_links = []
for src, src_out, dst, dst_pin in links:
    if not mel.connect_material_expressions(src, src_out, dst, dst_pin):
        failed_links.append(dst_pin or dst.get_class().get_name())
final_ok = mel.connect_material_property(rgb, "", unreal.MaterialProperty.MP_EMISSIVE_COLOR)
opacity_ok = mel.connect_material_property(alpha, "", unreal.MaterialProperty.MP_OPACITY)

errors = mel.recompile_material(mat)
saved = eal.save_loaded_asset(mat, False)

connected = mel.get_inputs_for_material_expression(mat, custom)
pin_names = mel.get_material_expression_input_names(custom)
wiring = []
for index in range(len(pin_names)):
    src = connected[index] if index < len(connected) else None
    wiring.append(str(pin_names[index]) + "<-" + ("NONE" if src is None else str(src.get_class().get_name())))
scalar_back = []
for param_name, default in SCALARS:
    scalar_back.append(param_name + "=" + str(mel.get_material_default_scalar_parameter_value(mat, param_name)))
eb = mel.get_material_default_vector_parameter_value(mat, "EmberColor")
print("EF asset=" + ASSET_PATH + " created=" + str(created) + " removed_nodes=" + str(removed))
print("EF domain=" + str(mat.get_editor_property("material_domain")) + " blend=" + str(mat.get_editor_property("blend_mode")))
print("EF nodes=" + str(mel.get_num_material_expressions(mat)) + " (expect 14)")
print("EF custom output=" + str(custom.get_editor_property("output_type")) +
      " code_chars=" + str(len(custom.get_editor_property("code"))) + "/" + str(len(HLSL_SOURCE)))
print("EF pins=" + ",".join(wiring))
print("EF failed_links=" + str(failed_links) + " final=" + str(final_ok) + " opacity=" + str(opacity_ok))
print("EF scalars=" + ",".join(scalar_back))
print("EF ember=" + str(round(eb.r, 3)) + "," + str(round(eb.g, 3)) + "," + str(round(eb.b, 3)))
print("EF recompile_errors=" + str(len(errors)) + " " + " | ".join([str(e) for e in errors]))
print("EF saved=" + str(saved))
'''

FONTS_SCRIPT = r'''
import unreal
DEST = "__FONT_DIR__"
FONTS = __FONTS__
eal = unreal.EditorAssetLibrary
if not eal.does_directory_exist(DEST):
    eal.make_directory(DEST)
for src, face_name, font_name in FONTS:
    if eal.does_asset_exist(DEST + "/" + font_name):
        print("FONT have " + font_name)
        continue
    fac = unreal.FontFileImportFactory()
    fac.set_editor_property("batch_create_font_asset", unreal.BatchCreateFontAsset.YES)
    task = unreal.AssetImportTask()
    task.set_editor_property("filename", src)
    task.set_editor_property("destination_path", DEST)
    task.set_editor_property("destination_name", face_name)
    task.set_editor_property("automated", True)
    task.set_editor_property("replace_existing", False)
    task.set_editor_property("save", False)
    task.set_editor_property("factory", fac)
    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
    print("FONT imported " + " | ".join([str(p) for p in task.get_editor_property("imported_object_paths")]))
    if eal.does_asset_exist(DEST + "/" + face_name + "_Font"):
        print("FONT rename " + str(eal.rename_asset(DEST + "/" + face_name + "_Font", DEST + "/" + font_name)))
    saved = []
    for name in (face_name, font_name):
        if eal.does_asset_exist(DEST + "/" + name):
            saved.append(name + "=" + str(eal.save_asset(DEST + "/" + name, False)))
    print("FONT saved " + " ".join(saved))
print("FONT list " + " | ".join([str(p) for p in eal.list_assets(DEST, False, False)]))
'''

STATS_SCRIPT = r'''
import unreal
mat = unreal.EditorAssetLibrary.load_asset("__ASSET_PATH__")
s = unreal.MaterialEditingLibrary.get_statistics(mat)
print("EFS ps_instructions=" + str(s.get_editor_property("num_pixel_shader_instructions")) +
      " vs_instructions=" + str(s.get_editor_property("num_vertex_shader_instructions")) +
      " samplers=" + str(s.get_editor_property("num_samplers")))
'''

DEFAULTS_SCRIPT = r'''
import unreal
mel = unreal.MaterialEditingLibrary
eal = unreal.EditorAssetLibrary
mat = eal.load_asset("__ASSET_PATH__")
wanted = {"Ignite": __IGNITE__, "Burn": __BURN__}
for node in mel.get_material_expressions(mat):
    if isinstance(node, unreal.MaterialExpressionScalarParameter):
        name = str(node.get_editor_property("parameter_name"))
        if name in wanted:
            node.set_editor_property("default_value", wanted[name])
mel.recompile_material(mat)
print("EFD saved=" + str(eal.save_loaded_asset(mat, False)) + " Ignite=" +
      str(mel.get_material_default_scalar_parameter_value(mat, "Ignite")) + " Burn=" +
      str(mel.get_material_default_scalar_parameter_value(mat, "Burn")))
'''


def fill(template, **kw):
    out = template
    for k, v in kw.items():
        out = out.replace(f"__{k}__", v)
    return out


def editor_script(hlsl=None):
    hlsl = HLSL_PATH.read_text(encoding="utf-8") if hlsl is None else hlsl
    problems = hlsl_problems(hlsl)
    if problems:
        raise SystemExit(f"{HLSL_PATH.name}: {problems}")
    head = fill(EDITOR_SCRIPT, ASSET_PATH=ASSET_PATH, PACKAGE_DIR=PACKAGE_DIR, ASSET_NAME=ASSET_NAME,
                TEXTURE_PARAM=TEXTURE_PARAM, DEFAULT_TEXTURE=DEFAULT_TEXTURE,
                CUSTOM_PINS=repr(CUSTOM_PINS), SCALARS=repr(SCALARS),
                EMBER=repr(tuple(round(c, 4) for c in EMBER_LINEAR)), GROUP=PARAM_GROUP)
    parts = head.split("__HLSL__")
    assert len(parts) == 2, "expected exactly one HLSL marker"
    return check_banned(parts[0] + hlsl + parts[1])


def fonts_script():
    src = [(str((ROOT / "Saved" / "Fonts" / f).as_posix()), face, font) for f, face, font in FONTS]
    return check_banned(fill(FONTS_SCRIPT, FONT_DIR=FONT_DIR, FONTS=repr(src)))


def defaults_script(ignite, burn):
    return check_banned(fill(DEFAULTS_SCRIPT, ASSET_PATH=ASSET_PATH, IGNITE=repr(float(ignite)),
                             BURN=repr(float(burn))))


# --------------------------------------------------------------------------- offline FXC

MOCK_HEAD = """#define Texture2DSample(T,S,U) T.Sample(S,U)
struct FMaterialPixelParameters { float4 SvPosition; };
float4 CustomExpression0(FMaterialPixelParameters Parameters, float2 UV, Texture2D Tex, SamplerState TexSampler, float Time, float Ignite, float Burn, float3 EmberColor, float Fade)
{
"""
MOCK_TAIL = """
}
Texture2D RT; SamplerState RTS;
cbuffer P { float Tm; float Ig; float Bu; float3 Em; float Fd; };
float4 main(float4 pos:SV_Position, float2 uv:TEXCOORD0):SV_Target
{
  FMaterialPixelParameters p; p.SvPosition = pos;
  return CustomExpression0(p, uv, RT, RTS, Tm, Ig, Bu, Em, Fd);
}
"""


def find_fxc():
    found = shutil.which("fxc")
    if found:
        return found
    kits = pathlib.Path("C:/Program Files (x86)/Windows Kits/10/bin")
    for exe in sorted(kits.glob("*/x64/fxc.exe"), reverse=True):
        return str(exe)
    return None


def fxc_stats(hlsl):
    """Compile the node body in a mock of UE's Custom-node wrapper; return (ok, slots, log)."""
    fxc = find_fxc()
    if not fxc:
        return None, None, "fxc not found"
    with tempfile.TemporaryDirectory() as tmp:
        src = pathlib.Path(tmp) / "mock_ember.hlsl"
        asm = pathlib.Path(tmp) / "mock_ember.asm"
        src.write_text(MOCK_HEAD + hlsl + MOCK_TAIL, encoding="ascii")
        r = subprocess.run([fxc, "-nologo", "-T", "ps_5_0", "-E", "main", "-O3", "-WX", str(src), "-Fc", str(asm)],
                           capture_output=True, text=True)
        text = asm.read_text(errors="replace") if asm.exists() else ""
    m = re.search(r"Approximately (\d+) instruction slots", text)
    return r.returncode == 0, int(m.group(1)) if m else None, (r.stdout + r.stderr).strip()


# --------------------------------------------------------------------------- Hayba

def hayba(cmd, params, port=None, timeout_s=300.0):
    """One raw Hayba TCP command; returns the reply dict {ok, data, error}."""
    port = int(port or os.environ.get("HB_PORT", 52342))
    payload = json.dumps({"cmd": cmd, "id": f"ember_{os.getpid()}", "params": params}).encode("utf-8")
    with socket.create_connection(("127.0.0.1", port), timeout=timeout_s) as s:
        s.sendall(struct.pack(">I", len(payload)) + payload)
        head = b""
        while len(head) < 4:
            head += s.recv(4 - len(head))
        n = struct.unpack(">I", head)[0]
        body = b""
        while len(body) < n:
            chunk = s.recv(n - len(body))
            if not chunk:
                raise ConnectionError("Hayba closed the connection")
            body += chunk
    return json.loads(body.decode("utf-8"))


def run_editor(script):
    ok, out, err = python_run(script)
    print(out.rstrip())
    if err:
        print("STDERR", err)
    return ok


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("command", choices=["check", "build", "stats", "fonts", "defaults"])
    p.add_argument("values", nargs="*", type=float)
    a = p.parse_args(argv)
    if a.command == "check":
        hlsl = HLSL_PATH.read_text(encoding="utf-8")
        script = editor_script(hlsl)
        samples = texture_sample_count(hlsl)
        ok, slots, log = fxc_stats(hlsl)
        print(f"check hlsl_chars={len(hlsl)} script_chars={len(script)} samples={samples}/{MAX_SAMPLES} "
              f"fxc_ok={ok} fxc_slots={slots} ember_linear={tuple(round(c, 3) for c in EMBER_LINEAR)}")
        if ok is False:
            print(log)
        return 0 if samples <= MAX_SAMPLES and ok is not False else 1
    if a.command == "build":
        return 0 if run_editor(editor_script()) else 1
    if a.command == "fonts":
        return 0 if run_editor(fonts_script()) else 1
    if a.command == "defaults":
        ignite, burn = (a.values + [0.0, 0.0])[:2]
        return 0 if run_editor(defaults_script(ignite, burn)) else 1
    # material_compile reports errors; its instruction counts come back "n/a" for the UI
    # shader on this platform, so the counts are read with MaterialEditingLibrary.get_statistics.
    # The Custom node's Texture2DSample calls are not in UE's sample estimate: `check` counts them.
    r = hayba("material_compile", {"material_path": ASSET_PATH})
    data = r.get("data") or {}
    print(f"compile ok={r.get('ok')} has_errors={data.get('has_errors')} errors={data.get('errors')} saved={data.get('saved')}")
    ok = run_editor(check_banned(fill(STATS_SCRIPT, ASSET_PATH=ASSET_PATH)))
    return 0 if r.get("ok") and ok and not data.get("has_errors") else 1


if __name__ == "__main__":
    sys.exit(main())
