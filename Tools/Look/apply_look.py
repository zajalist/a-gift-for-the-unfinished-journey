"""Set the Saskarta_WP lighting actors to one look key, through Hayba python_run.

    python Tools/Look/apply_look.py --key Valley         # apply a key from look_keys.json
    python Tools/Look/apply_look.py --read               # print the current lighting state (JSON)
    python Tools/Look/apply_look.py --key Above --dry-run  # print the editor script only
    python Tools/Look/apply_look.py --save               # save the lighting actors + MPC + cloud MI (after an apply)

Spec: docs/superpowers/specs/2026-09-26-saskarta-world-sprint-design.md, section 6.
The keys live in Tools/Look/look_keys.json; LOOK.md explains every value.

What one key sets (the same set USaskartaLightingDirector will blend at runtime):
- the sun (DirectionalLight): pitch, yaw, intensity (lux), temperature (K);
- SkyAtmosphere: Mie scattering scale, Mie anisotropy, Rayleigh scattering scale;
- VolumetricCloud: layer bottom altitude and height (km), and MPC_Saskarta_Sky's
  Coverage, Density, BaseAltitude (km) and StormIntensity, read by M_Saskarta_Cloud;
- ExponentialHeightFog: density, height falloff, inscattering colour, start distance and
  the second fog layer (density, height offset);
- the blend weights of PPV_Saskarta_Grade_Storm and PPV_Saskarta_Grade_Clear.

MPC values are written both to the asset defaults (so the saved level opens in the applied
key) and to the editor world's collection instance (so the viewport updates at once).

The editor script obeys python_run's rules: a 5 s deadline and none of the banned words
(the try keyword, the getattr builtin, the time import, file opening, str replace, new level).
It is sent over Hayba's TCP port (default 127.0.0.1:52342; HB_PORT overrides the port).
Wrap every run in Tools/GameFlow/editor_gate.py acquire/release.
"""
import argparse
import json
import os
import pathlib
import socket
import struct
import sys

HERE = pathlib.Path(__file__).resolve().parent
KEYS_PATH = HERE / "look_keys.json"
MPC_PATH = "/Game/SaskartaGaea/Look/MPC_Saskarta_Sky.MPC_Saskarta_Sky"
CLOUD_MI_PATH = "/Game/SaskartaGaea/Look/MI_Saskarta_Cloud.MI_Saskarta_Cloud"
LOOK_KEYS_DA_PATH = "/Game/SaskartaGaea/Look/DA_Saskarta_LookKeys"  # build_look_keys_asset.py's FOLDER / ASSET
# The sky atmosphere's planet top sits at this world Z (cm), below the lowest road point
# (-414 m, spline point 28), so cloud altitudes in the keys are km above -450 m:
# Valley road ~0.09 km, InCloud (4350 m) 0.51 km, Above (4550 m) 0.56 km, summit 0.65 km.
PLANET_TOP_Z_CM = -45000.0
# Fog inscattering is an absolute luminance. This level's exposure (PPV_Saskarta_Mood: manual,
# bias 10.5) is set for a sun of a few lux, so a palette colour at face value is a white wall.
# The key's fog colour is its hue; this scale sets its brightness against that exposure.
FOG_LUMINANCE_SCALE = 0.08
# Sky light and sky brightness (not in the key schema; the same in every key).
# The storm keys are dark and desaturated (concept board). The sky light recaptures in real time,
# so it follows each key's sky; its intensity and a slight cool tint keep ambient near neutral, and
# the sky luminance factor lifts the open sky between storm clouds to charcoal instead of black.
# LOOK2 (user: "the colors are all washed out"; brief B.4): the ground in shadow sat near black
# (road_200 lower half luma ~0.05), so the ambient carries more of the scene.
# LOOK2 fix round 1 (review 1): 1.3 -> 2.2. At the 8-degree sun a flat surface gets sin(8) = 0.14 of
# the sun, so the flat road core read darker than the rough, sun-facing verge; more of the scene on
# the sky light lets the lighter road albedo show (road_1050 lit road/verge 0.64 -> 0.94 at RoadLift 1.3).
SKYLIGHT_INTENSITY = 3.5  # STORM: the 3,000 K sun and the heavier deck left the road near black at 2.2 (road_200 lower-half luma 0.007 vs LOOK2's 0.021)
SKYLIGHT_TINT = (0.9, 0.95, 1.05)  # LOOK2: cooler, so ground hues are not one orange (was 0.95, 0.96, 1.0)
SKY_LUMINANCE_FACTOR = 3.0  # STORM: lifted from LOOK2's 2.8 so the heavier storm deck (StormIntensity 0.8) is not pure black
# How much the sky light is occluded under the cloud layer (engine default 0.5). At 0.5 the storm
# undersides go near black whenever the camera looks away from the sun; 0.1 keeps them charcoal.
CLOUD_BOTTOM_OCCLUSION = 0.2  # LOOK2 B.2: more cloud light/shadow contrast (was 0.1)
# LOOK2 B.3: the volumetric fog (80 m, unchanged) is the haze inside the near 500 m that the height
# fog's start distance (task SKY) leaves clear; scaling its extinction keeps SKY's valley bands.
VOLUMETRIC_FOG_EXTINCTION = 1.0  # FOG2: 1.0 so the volumetric near fog and the analytic fog beyond it match at the seam (LOOK2 had 0.5); FOG3: the height fog it scales is thin now
# STORM: the volumetric fog carries the animated dust (M_Saskarta_DustVolume on the StormDust_Volume actor,
# a Volume-domain material on a map-sized box) out to 1.5 km, with forward scattering so the low sun
# throws shafts through it. Its grid is r.VolumetricFog.GridPixelSize 16 at Epic/Cinematic
# (Config/DefaultScalability.ini).
# FOG2 (user: "very intense fog / dust storm", "within 20 m the fog can start"): the dense dust wall is
# 80-300 m away on every key, so the volumetric grid only needs to cover the near 120 m (the same froxel
# count over a shorter depth: finer slices, crisper shafts and headlight cones, no extra cost); the
# analytic height fog carries everything beyond. The near 20 m stays clear (start 20 m, fading in over 10 m).
# FOG3 (user: "close to the player, but not dense"): the A/B range is the carrier's own air, 10-60 m (fading in
# over 5 m): the same froxel count over half the depth (finer slices, no extra cost), and beyond 60 m the thin
# analytic fog takes over. The near dust there is M_Saskarta_DustVolume's bubble and near layer (build_storm_fx.py
# VOLUME_PARAMS Gust / Near, thinned for FOG3), a veil of about 10 % over 50 m.
VOLUMETRIC_FOG_DISTANCE_CM = 6000.0
VOLUMETRIC_FOG_START_CM = 1000.0
VOLUMETRIC_FOG_NEAR_FADE_CM = 500.0
VOLUMETRIC_FOG_SCATTERING = 0.6
# FOG2: inside VOLUMETRIC_FOG_DISTANCE the engine drops the analytic fog (its inscattering colour) and the fog
# is lit only by the lights, so the near 20-120 m went dark (smoke, not dust) under the dim storm sky. The sky
# light's and the sun's volumetric scattering are raised so the near dust is as bright as the analytic wall
# behind it; the sky light is real-time captured, so the near dust follows each key's sky.
# FOG2 decision (kept in FOG3): volumetric fog is OFF by default. Inside its range the engine drops the analytic fog, and
# the near dust then depends on the volumetric lighting, which editor captures cannot show (SceneCaptures render
# it unlit/black here). The analytic fog alone gives exactly the look asked for (clear to 20 m, a dense ochre wall
# by 80-300 m; Saved/Screenshots/Look/Fog2) and costs less. Set True for a PIE A/B: the near 20-120 m is then
# volumetric (shafts, headlight cones, the animated M_Saskarta_DustVolume) lit by the values below.
VOLUMETRIC_FOG_ENABLED = False
SKYLIGHT_VOLUMETRIC_SCATTERING = 6.0
SUN_VOLUMETRIC_SCATTERING = 3.0
VOLUMETRIC_FOG_ALBEDO = (0.66, 0.56, 0.34)  # FOG2: ochre toward a sickly yellow (was 0.62, 0.45, 0.30)
# MTNVIEW addendum 2 (user: "like distance fog / dust storm like"): the keys' fog is a dust haze,
# densest on the ground and falling off with height so the summit stands above it; the key's
# optional "luminance" overrides FOG_LUMINANCE_SCALE for that key (the dust must read as lit haze);
# dir_exponent / dir_color turn on directional inscattering (the warm glow toward the low sun, at
# the same FOG_LUMINANCE_SCALE brightness as the fog colour) and volumetric fog (sun shafts).
# LOOK2 B.4: PPV_Saskarta_Mood's manual exposure compensation (EV), written by --grades.
MOOD_EXPOSURE_BIAS = 11.25
# Second fog layer falloff: the default for a key without fog.second_falloff. The director does not blend it,
# so the level's saved value holds in game and every key carries the same one.
# FOG3: the second layer is the ground-hugging dust, anchored per key under the road (fog_model.fit_keys): its
# density halves every 20 m (FOG3 fix round 1; FOG3 had 0.4, 25 m; FOG2 0.08, a thin upper tier halving every 125 m).
# FOG3B: 0.7, halving every 14.3 m, so the doubled near dust stays under the ridges and the summit (fog_model.py FOG3B).
SECOND_FOG_FALLOFF = 0.7
# The fog's maximum opacity (engine default 1.0; the level has used 0.8 since before L1). A key may
# override it with fog.max_opacity; fog.second_falloff likewise overrides SECOND_FOG_FALLOFF.
FOG_MAX_OPACITY = 0.98  # Keep a faint far ridge while the distance veil hides the unbuilt world.
# M_Saskarta_Cloud's noise moves by Layout_WindControls.xyz * (engine time / 3.9 s + WindOffset),
# with WindOffset (MPC_Saskarta_Sky) also added to the direction (task SKY found the product term).
# The parent's default is (1, 1, 0.5, 0.333). Task SKY slows it in MI_Saskarta_Cloud; see LOOK.md.
CLOUD_WIND_CONTROLS = (0.42, 0.42, 0.21, 0.333333)  # STORM: 0.42 x the parent default, a slow roil (task SKY had 0.35; R45: no rush)
# STORM: torn, turbulent storm edges. M_Saskarta_Cloud's Noise_Strength is (shape, detail 1, detail 2,
# erosion power); the parent default is (0.8, 0.08, 0.03, 2.5). Stronger detail noise erodes the
# deck's edges into rags. Storm_AlbedoColor darkens and warms the storm cells (was 0.8, 0.77, 0.74, 0.333).
CLOUD_NOISE_STRENGTH = (0.8, 0.14, 0.06, 2.5)
CLOUD_STORM_ALBEDO = (0.62, 0.52, 0.44, 0.333)
PPV_STORM = "PPV_Saskarta_Grade_Storm"
PPV_CLEAR = "PPV_Saskarta_Grade_Clear"


# ----------------------------------------------------------------------------- transport

EDITOR_LOG = pathlib.Path(__file__).resolve().parents[2] / "Saved" / "Logs" / "saskartarad.log"
PIE_SETTLE_S = 30.0


def pie_running(log=EDITOR_LOG):
    """True while the user's Play-In-Editor session runs, read from the editor log only (an editor
    call to ask would itself hitch their session): the last PIE start after the last PIE shutdown."""
    if not log.exists():
        return False
    text = log.read_text(encoding="utf-8", errors="replace")
    start = max(text.rfind("Creating play world package"), text.rfind("Play in editor total start"))
    stop = text.rfind("Shutting down PIE")
    if start > stop:
        return True
    # LANE4: also hold off for PIE_SETTLE_S after a session ends (the user often presses Play again at once,
    # and the editor is still tearing the play world down). Log lines start [YYYY.MM.DD-HH.MM.SS:mmm] in UTC.
    if stop >= 0:
        import datetime
        line_start = text.rfind(chr(10), 0, stop) + 1
        stamp = text[line_start + 1:line_start + 20]
        try_ok = len(stamp) == 19 and stamp[4] == "." and stamp[10] == "-"
        if try_ok:
            t = datetime.datetime.strptime(stamp, "%Y.%m.%d-%H.%M.%S").replace(tzinfo=datetime.timezone.utc)
            if (datetime.datetime.now(datetime.timezone.utc) - t).total_seconds() < PIE_SETTLE_S:
                return True
    return False


def python_run(script, port=None, timeout_s=120.0):
    """Send one python_run to the Hayba plugin; return (ok, stdout, error).
    Refuses (SystemExit) while PIE runs, checked before every call, so multi-call tools stop as soon
    as the user presses Play (LANE2, 2026-09-27: a profile run kept calling into a PIE session)."""
    if pie_running():
        raise SystemExit("PIE is running: no editor call sent (wait until the session ends)")
    port = int(port or os.environ.get("HB_PORT", 52342))
    envelope = {"cmd": "python_run", "id": f"apply_look_{os.getpid()}", "params": {"script": script}}
    # Hayba leases (editor_gate.py): act as the gate's lease holder, not as a stranger connection.
    if os.environ.get("HAYBA_LEASE"):
        envelope["lease"] = os.environ["HAYBA_LEASE"]
    if os.environ.get("HAYBA_AGENT_ID"):
        envelope["owner"] = os.environ["HAYBA_AGENT_ID"]
    payload = json.dumps(envelope).encode("utf-8")
    with socket.create_connection(("127.0.0.1", port), timeout=timeout_s) as s:
        s.sendall(struct.pack(">I", len(payload)) + payload)
        head = _recv_exact(s, 4)
        body = _recv_exact(s, struct.unpack(">I", head)[0])
    msg = json.loads(body.decode("utf-8"))
    data = msg.get("data") or {}
    out = data.get("stdout", "") if isinstance(data, dict) else str(data)
    err = msg.get("error") or (data.get("stderr") if isinstance(data, dict) else "")
    return bool(msg.get("ok")), out, err


def _recv_exact(s, n):
    buf = b""
    while len(buf) < n:
        chunk = s.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("Hayba closed the connection")
        buf += chunk
    return buf


# ----------------------------------------------------------------------------- keys

def load_keys(path=KEYS_PATH):
    return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))


def find_key(keys, name):
    for k in keys:
        if k["name"].lower() == name.lower():
            return k
    raise SystemExit(f"no key {name!r}; keys: {', '.join(k['name'] for k in keys)}")


def linear_to_hex(lin):
    """linear (r, g, b) -> '#RRGGBB' (sRGB)."""
    out = []
    for c in lin:
        c = min(max(c, 0.0), 1.0)
        s_ = c * 12.92 if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055
        out.append(int(round(s_ * 255)))
    return "#%02X%02X%02X" % tuple(out)


def blend_keys(keys, road_m):
    """FOG2: the look at a road metre, as USaskartaLightingDirector blends it: every number linear between
    the two keys around road_m, colours linear in linear light; names, strings and flags from the lower key.
    (The director also takes the sun yaw along the shortest arc; the keys' yaws are within 30 deg.)"""
    ks = sorted(keys, key=lambda k: float(k["road_m"]))
    if road_m <= ks[0]["road_m"]:
        return json.loads(json.dumps(ks[0]))
    if road_m >= ks[-1]["road_m"]:
        return json.loads(json.dumps(ks[-1]))
    for a, b in zip(ks, ks[1:]):
        if road_m <= b["road_m"]:
            t = (road_m - a["road_m"]) / float(b["road_m"] - a["road_m"])

            def mix(x, y):
                if isinstance(x, dict):
                    return {n: mix(x[n], y.get(n, x[n])) for n in x}
                if isinstance(x, bool) or not isinstance(x, (int, float)):
                    if isinstance(x, str) and x.startswith("#") and isinstance(y, str):
                        la, lb = hex_to_linear(x), hex_to_linear(y)
                        return linear_to_hex([u + (v - u) * t for u, v in zip(la, lb)])
                    return x
                return x + (y - x) * t
            out = mix(a, b)
            out["name"] = f"{a['name']}+{b['name']}@{road_m:g}"
            return out


def hex_to_linear(hex_color):
    """'#RRGGBB' (sRGB) -> linear (r, g, b)."""
    h = hex_color.lstrip("#")
    out = []
    for i in (0, 2, 4):
        c = int(h[i:i + 2], 16) / 255.0
        out.append(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
    return tuple(round(v, 5) for v in out)


# ----------------------------------------------------------------------------- editor scripts

FIND = """
import unreal
eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
acts = eas.get_all_level_actors()
def first(cls):
    for a in acts:
        if a.get_class().get_name() == cls:
            return a
    return None
def labelled(label):
    for a in acts:
        if a.get_actor_label() == label:
            return a
    return None
sun = first('DirectionalLight')
atm = first('SkyAtmosphere')
cloud = first('VolumetricCloud')
fog = first('ExponentialHeightFog')
sky = first('SkyLight')
"""

APPLY = FIND + """
K = __KEY__
FOGLIN = __FOGLIN__
DIRLIN = __DIRLIN__
done = []
atm.set_actor_location(unreal.Vector(0.0, 0.0, __PLANET_TOP_Z__), False, False)
atm.get_component_by_class(unreal.SkyAtmosphereComponent).set_editor_property('transform_mode', unreal.SkyAtmosphereTransformMode.PLANET_TOP_AT_COMPONENT_TRANSFORM)
cmi = unreal.load_asset('__CLOUD_MI__')
if cmi:
    cloud.get_component_by_class(unreal.VolumetricCloudComponent).set_material(cmi)
    wc = __CLOUD_WIND__
    MEL = unreal.MaterialEditingLibrary
    MEL.set_material_instance_vector_parameter_value(cmi, 'Layout_WindControls', unreal.LinearColor(wc[0], wc[1], wc[2], wc[3]))
    ns = __CLOUD_NOISE__
    MEL.set_material_instance_vector_parameter_value(cmi, 'Noise_Strength', unreal.LinearColor(ns[0], ns[1], ns[2], ns[3]))
    sa = __CLOUD_STORM_ALB__
    MEL.set_material_instance_vector_parameter_value(cmi, 'Storm_AlbedoColor', unreal.LinearColor(sa[0], sa[1], sa[2], sa[3]))
    MEL.update_material_instance(cmi)
ac0 = atm.get_component_by_class(unreal.SkyAtmosphereComponent)
ac0.set_sky_luminance_factor(unreal.LinearColor(__SLF__, __SLF__, __SLF__, 1.0))
if sky:
    sk0 = sky.get_component_by_class(unreal.SkyLightComponent)
    sk0.set_editor_property('real_time_capture', True)
    sk0.set_intensity(__SKY_I__)
    sk0.set_light_color(unreal.LinearColor(__SKY_T__[0], __SKY_T__[1], __SKY_T__[2], 1.0))
    sk0.set_editor_property('volumetric_scattering_intensity', __SKY_VS__)
done.append('setup')
s = K['sun']
sun.set_actor_rotation(unreal.Rotator(roll=0.0, pitch=s['pitch'], yaw=s['yaw']), False)
sc = sun.get_component_by_class(unreal.DirectionalLightComponent)
sc.set_intensity(s['intensity_lux'])
sc.set_editor_property('use_temperature', True)
sc.set_editor_property('cast_cloud_shadows', False)
sc.set_temperature(s['temperature_k'])
sc.set_editor_property('volumetric_scattering_intensity', __SUN_VS__)
done.append('sun')
a = K['atmosphere']
ac = atm.get_component_by_class(unreal.SkyAtmosphereComponent)
ac.set_mie_scattering_scale(a['mie_scattering_scale'])
ac.set_mie_anisotropy(a['mie_anisotropy'])
ac.set_rayleigh_scattering_scale(a['rayleigh_scale'])
done.append('atmosphere')
c = K['clouds']
cc = cloud.get_component_by_class(unreal.VolumetricCloudComponent)
cc.set_layer_bottom_altitude(c['base_km'])
cc.set_layer_height(c['top_km'] - c['base_km'])
cc.set_sky_light_cloud_bottom_occlusion(__CLOUD_OCC__)
done.append('cloud layer')
f = K['fog']
fc = fog.get_component_by_class(unreal.ExponentialHeightFogComponent)
fc.set_fog_density(f['density'])
fc.set_fog_height_falloff(f['falloff'])
fc.set_fog_inscattering_color(unreal.LinearColor(FOGLIN[0], FOGLIN[1], FOGLIN[2], 1.0))
fc.set_start_distance(f['start_m'] * 100.0)
sd = fc.get_editor_property('second_fog_data')
sd.set_editor_property('fog_density', f['second_density'])
sd.set_editor_property('fog_height_offset', f['second_height_m'] * 100.0)
sd.set_editor_property('fog_height_falloff', f.get('second_falloff', __SECOND_FALLOFF__))
fc.set_editor_property('second_fog_data', sd)
fc.set_editor_property('fog_max_opacity', f.get('max_opacity', __FOG_MAX_OPACITY__))
fc.set_editor_property('fog_cutoff_distance', f.get('cutoff_m', 0.0) * 100.0)
fc.set_editor_property('volumetric_fog_extinction_scale', __VFOG_EXT__)
fc.set_editor_property('volumetric_fog_distance', __VFOG_DIST__)
fc.set_editor_property('volumetric_fog_start_distance', __VFOG_START__)
fc.set_editor_property('volumetric_fog_near_fade_in_distance', __VFOG_FADE__)
fc.set_editor_property('volumetric_fog_scattering_distribution', __VFOG_G__)
fc.set_editor_property('volumetric_fog_albedo', unreal.Color(r=int(__VFOG_ALB__[0] * 255), g=int(__VFOG_ALB__[1] * 255), b=int(__VFOG_ALB__[2] * 255), a=255))
if 'dir_exponent' in f:
    fc.set_editor_property('directional_inscattering_exponent', f['dir_exponent'])
    fc.set_editor_property('directional_inscattering_luminance', unreal.LinearColor(DIRLIN[0], DIRLIN[1], DIRLIN[2], 1.0))
fc.set_editor_property('enable_volumetric_fog', __VFOG_ON__)
done.append('fog')
g = K['grade']
ps = labelled('__PPV_STORM__')
pc = labelled('__PPV_CLEAR__')
if ps:
    ps.set_editor_property('blend_weight', g['storm_weight'])
    done.append('storm grade')
if pc:
    pc.set_editor_property('blend_weight', g['clear_weight'])
    done.append('clear grade')
mpc = unreal.load_asset('__MPC__')
if mpc:
    vals = {'Coverage': c['coverage'], 'Density': c['density'], 'BaseAltitude': c['base_km'],
            'StormIntensity': K['storm_intensity']}
    params = mpc.get_editor_property('scalar_parameters')
    for p in params:
        n = str(p.get_editor_property('parameter_name'))
        if n in vals:
            p.set_editor_property('default_value', vals[n])
    mpc.set_editor_property('scalar_parameters', params)
    w = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
    for n in vals:
        unreal.MaterialLibrary.set_scalar_parameter_value(w, mpc, n, vals[n])
    done.append('mpc')
if sky:
    skc = sky.get_component_by_class(unreal.SkyLightComponent)
    skc.recapture_sky()
    done.append('skylight recapture')
print('applied ' + K['name'] + ': ' + ', '.join(done))
"""

READ = FIND + """
import json
def rot(a):
    r = a.get_actor_rotation()
    return {'pitch': round(r.pitch, 3), 'yaw': round(r.yaw, 3), 'roll': round(r.roll, 3)}
def col(c):
    return [round(c.r, 5), round(c.g, 5), round(c.b, 5)]
out = {}
if sun:
    sc = sun.get_component_by_class(unreal.DirectionalLightComponent)
    out['sun'] = {'label': sun.get_actor_label(), 'rotation': rot(sun),
        'intensity': sc.get_editor_property('intensity'),
        'use_temperature': sc.get_editor_property('use_temperature'),
        'temperature': sc.get_editor_property('temperature'),
        'light_color': str(sc.get_editor_property('light_color')),
        'atmosphere_sun_light': sc.get_editor_property('atmosphere_sun_light'),
        'cast_cloud_shadows': sc.get_editor_property('cast_cloud_shadows')}
if atm:
    ac = atm.get_component_by_class(unreal.SkyAtmosphereComponent)
    out['atmosphere'] = {'label': atm.get_actor_label(),
        'mie_scattering_scale': ac.get_editor_property('mie_scattering_scale'),
        'mie_anisotropy': ac.get_editor_property('mie_anisotropy'),
        'rayleigh_scattering_scale': ac.get_editor_property('rayleigh_scattering_scale'),
        'multi_scattering_factor': ac.get_editor_property('multi_scattering_factor'),
        'sky_luminance_factor': col(ac.get_editor_property('sky_luminance_factor')),
        'transform_mode': str(ac.get_editor_property('transform_mode')),
        'location_z_cm': atm.get_actor_location().z}
if cloud:
    cc = cloud.get_component_by_class(unreal.VolumetricCloudComponent)
    m = cc.get_editor_property('material')
    out['cloud'] = {'label': cloud.get_actor_label(),
        'layer_bottom_altitude_km': cc.get_editor_property('layer_bottom_altitude'),
        'layer_height_km': cc.get_editor_property('layer_height'),
        'sky_light_cloud_bottom_occlusion': cc.get_editor_property('sky_light_cloud_bottom_occlusion'),
        'material': m.get_path_name() if m else None,
        'wind_controls': str(unreal.MaterialEditingLibrary.get_material_instance_vector_parameter_value(m, 'Layout_WindControls')) if m and m.get_class().get_name() == 'MaterialInstanceConstant' else None}
if fog:
    fc = fog.get_component_by_class(unreal.ExponentialHeightFogComponent)
    sd = fc.get_editor_property('second_fog_data')
    out['fog'] = {'label': fog.get_actor_label(),
        'density': fc.get_editor_property('fog_density'),
        'falloff': fc.get_editor_property('fog_height_falloff'),
        'inscattering_color': col(fc.get_editor_property('fog_inscattering_luminance')),
        'start_distance_cm': fc.get_editor_property('start_distance'),
        'second_density': sd.get_editor_property('fog_density'),
        'second_falloff': sd.get_editor_property('fog_height_falloff'),
        'second_height_offset_cm': sd.get_editor_property('fog_height_offset'),
        'max_opacity': fc.get_editor_property('fog_max_opacity'),
        'cutoff_distance_cm': fc.get_editor_property('fog_cutoff_distance'),
        'volumetric_fog': fc.get_editor_property('enable_volumetric_fog')}
if sky:
    skc = sky.get_component_by_class(unreal.SkyLightComponent)
    out['skylight'] = {'label': sky.get_actor_label(),
        'real_time_capture': skc.get_editor_property('real_time_capture'),
        'intensity': skc.get_editor_property('intensity'),
        'light_color': str(skc.get_editor_property('light_color')),
        'source_type': str(skc.get_editor_property('source_type'))}
pp = {}
for a in acts:
    if a.get_class().get_name() == 'PostProcessVolume':
        pp[a.get_actor_label()] = {'blend_weight': a.get_editor_property('blend_weight'),
            'unbound': a.get_editor_property('unbound'),
            'priority': a.get_editor_property('priority')}
out['post_process_volumes'] = pp
print(json.dumps(out))
"""


# ----------------------------------------------------------------------------- grade volumes
# The two grade volumes carry the concept-board grade (spec section 6). Colour-grading
# vectors are (R, G, B, luminance). The board is DARK and DESATURATED, so the storm grade pulls
# global saturation to 0.22 and only tilts the gains warm; the palette's hue ratios, heavily softened:
#   shadows   #2A2826 -> R:G:B 1.05:1.00:0.95  (warm charcoal)      gain 1.03:1.00:0.96
#   midtones  #3B312B / #6E5F55 -> 1.20:1.00:0.88 / 1.16:1.00:0.89   gain 1.03:1.00:0.95
#   clear highlights #E8B070 -> 1.32:1.00:0.64  (gold)             gain 1.10:1.00:0.82
# The accent #C8703A is not graded in; it belongs to emissive sources only (sun disc, fire, beacon).
# Tuned against Tools/Look/measure_look.py: mean luminance 0.14-0.26, mid-tone saturation <= 0.30.
#
# Ruling R31 / task L1b: raw emissive light sources (the High Voice crown and beam) rendered
# near-white under the storm grade, because the global saturation (0.22) desaturates every
# luminance range, including the brightest pixels where the accent hue should read clearly.
# ColorCorrectionHighlightsMin narrows "highlights" to only the brightest band (roughly the sun
# disc, fire and the beacon; ordinary lit cloud tops sit below it), and a highlight-range
# saturation well above 1 pushes the accent hue back out from under the global desaturation for
# just that band, while color_saturation (global) and the shadow/mid-tone values are untouched,
# so the rest of the frame stays as dark and desaturated as before (Tools/Look/measure_look.py).
GRADES = {
    PPV_STORM: {
        "priority": 2.0,
        # Board: dark, desaturated. Global saturation well below 1; warmth only as a slight gain tilt.
        "color_saturation": (1.0, 1.0, 1.0, 0.6),  # LOOK2 B.1 (user: "more saturation"; board 0.22)
        "color_contrast": (1.0, 1.0, 1.0, 1.15),  # LOOK2 B.3 (was 1.1)
        "color_saturation_shadows": (1.0, 1.0, 1.0, 0.7),
        "color_gain_shadows": (1.07, 1.0, 0.88, 1.0),  # STORM: shadows toward umber (was 1.03, 1.0, 0.96)
        "color_offset_shadows": (0.006, 0.004, 0.002, 0.0),  # STORM (was 0.004, 0.0035, 0.003)
        "color_saturation_midtones": (1.0, 1.0, 1.0, 1.1),  # LOOK2 B.1
        "color_gain_midtones": (1.0, 1.0, 0.98, 1.0),  # LOOK2 B.1: less orange cast, so greens read (was 1.03, 1.0, 0.95)
        # LOOK2 fix round 1 (review 3): white balance. The 8-degree sun reaches the ground red-orange
        # through the atmosphere, so every surface read as one rust tint (Lab cast 0.94-0.97, see
        # measure_look2.py). Balancing for a 5400 K source with a slight green tint pulls the lit
        # ground back toward its own ochre / olive / grey, while the clouds keep warm breaks.
        "white_temp": 5400.0,
        "white_tint": -0.1,
        "color_saturation_highlights": (1.0, 1.0, 1.0, 1.3),  # was 3.0 (L1b); with global saturation raised it blotched sunlit clouds yellow (user 2026-09-27)
        "color_correction_highlights_min": 0.6,
        "color_gain_highlights": (1.1, 0.97, 0.8, 1.0),  # STORM: highlights toward burnt orange (was 1.02, 1.0, 0.96)
        "film_toe": 0.6,
        "vignette_intensity": 0.35,
        "film_grain_intensity": 0.1,
    },
    PPV_CLEAR: {
        "priority": 3.0,
        "color_saturation": (1.0, 1.0, 1.0, 0.85),  # LOOK2 B.1 (board 0.4)
        "color_contrast": (1.0, 1.0, 1.0, 0.92),
        "color_gain_shadows": (1.02, 1.0, 0.97, 1.0),
        "color_gain_midtones": (1.03, 1.0, 0.95, 1.0),
        "color_saturation_highlights": (1.0, 1.0, 1.0, 1.3),  # was 3.0 (L1b); with global saturation raised it blotched sunlit clouds yellow (user 2026-09-27)
        "color_correction_highlights_min": 0.6,
        "color_gain_highlights": (1.1, 1.0, 0.82, 1.02),
        "film_toe": 0.55,
        "vignette_intensity": 0.35,
        "film_grain_intensity": 0.1,
    },
}

GRADES_SCRIPT = """
import unreal
G = __GRADES__
MOOD_ANCHOR = unreal.Vector(389000.0, 408000.0, 0.0)
eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
acts = eas.get_all_level_actors()
have = {}
for a in acts:
    if a.get_class().get_name() == 'PostProcessVolume':
        have[a.get_actor_label()] = a
out = []
for label in sorted(G):
    spec = G[label]
    a = have.get(label)
    if a is None:
        a = eas.spawn_actor_from_class(unreal.PostProcessVolume, MOOD_ANCHOR)
        a.set_actor_label(label)
        out.append('spawned ' + label)
    a.set_editor_property('unbound', True)
    a.set_editor_property('priority', spec['priority'])
    a.set_editor_property('is_spatially_loaded', False)
    s = a.get_editor_property('settings')
    for k in spec:
        if k == 'priority':
            continue
        v = spec[k]
        if isinstance(v, tuple):
            v = unreal.Vector4(v[0], v[1], v[2], v[3])
        s.set_editor_property('override_' + k, True)
        s.set_editor_property(k, v)
    a.set_editor_property('settings', s)
    out.append(label + ' ok')
mood = have.get('PPV_Saskarta_Mood')
if mood:
    s = mood.get_editor_property('settings')
    s.set_editor_property('override_auto_exposure_bias', True)
    s.set_editor_property('auto_exposure_bias', __MOOD_EV__)
    s.set_editor_property('override_color_saturation', False)
    s.set_editor_property('override_vignette_intensity', False)
    mood.set_editor_property('settings', s)
    out.append('mood grading overrides off (exposure kept)')
print('; '.join(out))
"""


# FOG3: save what an apply touched, and nothing else: the lighting actors' external packages, the MPC and the
# cloud MI (only the dirty ones). A separate python_run after the apply (FOG2 ran it from a scratch helper).
# FOG3 fix round 1: the save writes the level-only fog values (second-layer falloff, max opacity) the director
# never sets, and those only fit the densities in look_keys.json. So it refuses unless DA_Saskarta_LookKeys
# already holds look_keys.json's fog (build_look_keys_asset.py build ran first): a level saved under Fog 2's DA
# puts every key on the 0.2 floor by 300 m. The other half (a DA rebuilt but the level not saved) is on the
# editor steps in LOOK.md.
SAVE_DA_FIELDS = {"fog_density": "density", "fog_falloff": "falloff", "fog_start_m": "start_m",
                  "fog_second_density": "second_density", "fog_second_height_m": "second_height_m"}
SAVE_LABELS = ["DirectionalLight", "SkyAtmosphere", "VolumetricCloud", "ExponentialHeightFog", "SkyLight", PPV_STORM, PPV_CLEAR]
SAVE_SCRIPT = """
import unreal
eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
L = __LABELS__
WANT = __DA_FOG__
da = unreal.load_asset('__DA__')
bad = []
if da is None:
    bad.append('no asset')
else:
    have = {}
    for s in da.get_editor_property('keys'):
        have[str(s.get_editor_property('name'))] = s
    for name in WANT:
        s = have.get(name)
        if s is None:
            bad.append(name + ' missing')
            continue
        for field in WANT[name]:
            v = float(s.get_editor_property(field))
            w = WANT[name][field]
            if abs(v - w) > 1e-4 * max(1.0, abs(w)):
                bad.append(name + '.' + field + ' ' + str(round(v, 5)) + ' vs ' + str(w))
if bad:
    print('NOT SAVED: DA_Saskarta_LookKeys does not hold look_keys.json (run build_look_keys_asset.py build first): ' + str(bad[:6]))
else:
    pk = [a.get_package() for a in eas.get_all_level_actors() if a.get_actor_label() in L]
    n_actors = len(pk)
    for path in ['__MPC__', '__CLOUD_MI__']:
        asset = unreal.load_asset(path)
        if asset:
            pk.append(asset.get_package())
    print('actors ' + str(n_actors) + ' of ' + str(len(L)) + ', packages ' + str(len(pk)) + ', saved ' + str(unreal.EditorLoadingAndSavingUtils.save_packages(pk, True)))
"""


def save_script(keys=None):
    """The --save script, with look_keys.json's fog per key: the DA must hold it before anything is saved."""
    want = {k["name"]: {field: float(k["fog"][n]) for field, n in SAVE_DA_FIELDS.items()} for k in (keys or load_keys())}
    return (SAVE_SCRIPT.replace("__LABELS__", repr(SAVE_LABELS)).replace("__MPC__", MPC_PATH)
            .replace("__CLOUD_MI__", CLOUD_MI_PATH).replace("__DA_FOG__", repr(want))
            .replace("__DA__", LOOK_KEYS_DA_PATH))


def grades_script():
    return GRADES_SCRIPT.replace("__GRADES__", repr(GRADES)).replace("__MOOD_EV__", repr(MOOD_EXPOSURE_BIAS))


BANNED = ("try","getattr", "import time", "open(", ".replace(", "new_level(")


def check_banned(script):
    """python_run refuses these words anywhere in the text; fail here, with a clear message."""
    hits = [w for w in BANNED if w in script]
    if hits:
        raise SystemExit(f"editor script contains banned words for python_run: {hits}")
    return script


def apply_script(key):
    return (APPLY
            .replace("__KEY__", repr(key))
            .replace("__FOGLIN__", repr(tuple(round(c * key["fog"].get("luminance", FOG_LUMINANCE_SCALE), 6) for c in hex_to_linear(key["fog"]["color"]))))
            .replace("__DIRLIN__", repr(tuple(round(c * key["fog"].get("luminance", FOG_LUMINANCE_SCALE), 6) for c in hex_to_linear(key["fog"].get("dir_color", "#000000")))))
            .replace("__PPV_STORM__", PPV_STORM)
            .replace("__PPV_CLEAR__", PPV_CLEAR)
            .replace("__MPC__", MPC_PATH)
            .replace("__CLOUD_MI__", CLOUD_MI_PATH)
            .replace("__PLANET_TOP_Z__", repr(PLANET_TOP_Z_CM))
            .replace("__SECOND_FALLOFF__", repr(SECOND_FOG_FALLOFF))
            .replace("__FOG_MAX_OPACITY__", repr(FOG_MAX_OPACITY))
            .replace("__CLOUD_WIND__", repr(CLOUD_WIND_CONTROLS))
            .replace("__CLOUD_NOISE__", repr(CLOUD_NOISE_STRENGTH))
            .replace("__CLOUD_STORM_ALB__", repr(CLOUD_STORM_ALBEDO))
            .replace("__SLF__", repr(SKY_LUMINANCE_FACTOR))
            .replace("__CLOUD_OCC__", repr(CLOUD_BOTTOM_OCCLUSION))
            .replace("__VFOG_EXT__", repr(VOLUMETRIC_FOG_EXTINCTION))
            .replace("__VFOG_DIST__", repr(VOLUMETRIC_FOG_DISTANCE_CM))
            .replace("__VFOG_ON__", repr(VOLUMETRIC_FOG_ENABLED))
            .replace("__VFOG_START__", repr(VOLUMETRIC_FOG_START_CM))
            .replace("__VFOG_FADE__", repr(VOLUMETRIC_FOG_NEAR_FADE_CM))
            .replace("__VFOG_G__", repr(VOLUMETRIC_FOG_SCATTERING))
            .replace("__VFOG_ALB__", repr(VOLUMETRIC_FOG_ALBEDO))
            .replace("__SKY_I__", repr(SKYLIGHT_INTENSITY))
            .replace("__SKY_T__", repr(SKYLIGHT_TINT))
            .replace("__SKY_VS__", repr(SKYLIGHT_VOLUMETRIC_SCATTERING))
            .replace("__SUN_VS__", repr(SUN_VOLUMETRIC_SCATTERING)))


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--key", help="look key name from look_keys.json")
    g.add_argument("--road", type=float, help="FOG2: the look at this road metre, blended between the keys as the director does")
    g.add_argument("--read", action="store_true", help="print the current lighting state")
    g.add_argument("--grades", action="store_true",
                   help="create or update the two grade volumes (idempotent)")
    g.add_argument("--save", action="store_true",
                   help="FOG3: save the lighting actors, MPC_Saskarta_Sky and MI_Saskarta_Cloud (dirty packages only); "
                        "refuses unless DA_Saskarta_LookKeys already holds look_keys.json's fog")
    p.add_argument("--dry-run", action="store_true", help="print the editor script, send nothing")
    p.add_argument("--fog-mult", type=float, default=1.0,
                   help="scale the key's fog densities, as the director's PushFogOverride / a story SetFog does (FOG2 silhouette check)")
    p.add_argument("--keys", default=str(KEYS_PATH), help="look_keys.json path")
    a = p.parse_args(argv)

    if a.read:
        script = READ
    elif a.grades:
        script = grades_script()
    elif a.save:
        script = save_script(load_keys(a.keys))
    else:
        key = blend_keys(load_keys(a.keys), a.road) if a.road is not None else find_key(load_keys(a.keys), a.key)
        key["fog"]["density"] *= a.fog_mult
        key["fog"]["second_density"] *= a.fog_mult
        script = apply_script(key)
    script = check_banned(script)
    if a.dry_run:
        print(script)
        return 0
    ok, out, err = python_run(script)
    if out:
        print(out.rstrip())
    if not ok or err:
        print(f"python_run failed: {err}", file=sys.stderr)
        return 1
    if "NOT SAVED" in (out or ""):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
