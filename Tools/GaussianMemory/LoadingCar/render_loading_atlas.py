"""CPU pre-render of genuine covariance ellipses derived from an actual car mesh.

This visualization is mesh-derived, NOT trained 3DGS and NOT a memory asset.
Each source surface sample has an oriented 3D anisotropic covariance; perspective
Jacobian projection, depth sorting, Gaussian alpha and transmittance are used.
No billboards, car silhouette drawing, GPU, Unreal or network imports.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path

# Bound native numerical libraries before importing them.
os.environ['OMP_NUM_THREADS'] = '1'
os.environ['OPENBLAS_NUM_THREADS'] = '1'
os.environ['MKL_NUM_THREADS'] = '1'
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[3]
SCOPE = ROOT / 'Saved/Verification/gaussian_memory_20261001/loading_car'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def smooth(a, b, x):
    t = np.clip((x-a)/(b-a), 0., 1.)
    return t*t*(3.-2.*t)


def normalize(v):
    return v / np.maximum(np.linalg.norm(v, axis=-1, keepdims=True), 1.e-12)


def surface_gaussians(source, count, kernel_scale=.38):
    if source.get('representation') != 'actual_mesh_surface_source' or source.get('trained') is not False:
        raise ValueError('An actual root-extracted mesh surface is required')
    if source.get('units') != 'UE_local_centimeters' or not source.get('source_asset', '').startswith('/Game/'):
        raise ValueError('Need actual Unreal source identity and centimeter geometry')
    v = np.asarray(source['vertices'], dtype=np.float64)[:, [0, 2, 1]] / 100.
    faces = np.asarray(source['triangles'], dtype=np.int32)
    if not np.isfinite(v).all() or faces.ndim != 2 or faces.shape[1] != 3 or faces.min() < 0 or faces.max() >= len(v):
        raise ValueError('Invalid source surface')
    t = v[faces]
    cross = np.cross(t[:, 1]-t[:, 0], t[:, 2]-t[:, 0])
    area = np.linalg.norm(cross, axis=1)/2.
    valid = area > 1.e-12
    if not valid.any():
        raise ValueError('No nondegenerate source triangles')
    ids = np.asarray(source['triangle_material_ids'])[valid]
    t, cross, area = t[valid], cross[valid], area[valid]
    material_names = source['materials']
    if ids.min() < 0 or ids.max() >= len(material_names):
        raise ValueError('Source triangle material ID has no material slot')
    # The source reference pose includes capsule interior lining and padding.
    # Retain the exact source export, but present its exterior for a coherent
    # loading silhouette; interior alpha layers muddy the visible shell.
    exterior = np.array([not any(term in json.dumps(material_names[int(i)]).lower()
                       for term in ('lining', 'padding')) for i in ids])
    t, cross, area, ids = t[exterior], cross[exterior], area[exterior], ids[exterior]
    if not len(t):
        raise ValueError('No actual exterior triangles remain')
    rng = np.random.default_rng(3102026)
    # One stratified sample in every equal-area interval, on real triangles.
    weights = np.ones_like(area) if source.get('sampling') == 'deterministic area-stratified source triangle subset' else area
    selected = np.searchsorted(np.cumsum(weights), (np.arange(count)+rng.random(count))*weights.sum()/count)
    r = np.sqrt(rng.random(count))
    s = rng.random(count)
    bary = np.stack([1-r, r*(1-s), r*s], axis=1)
    positions = np.einsum('ni,nij->nj', bary, t[selected])
    normal = normalize(cross[selected])
    tangent = normalize(t[selected, 1]-t[selected, 0])
    bitangent = normalize(np.cross(normal, tangent))
    # Positive tangent-plane ellipsoids with a thin normal axis. These are
    # authored from mesh area/normal, not learned covariance parameters.
    represented_area = area.sum()
    if source.get('sampling') == 'deterministic area-stratified source triangle subset':
        # Sampled triangles can repeat. Estimate source extent-based coverage
        # from the actual bounds, with a restrained tangent radius.
        extent = v.max(axis=0)-v.min(axis=0)
        represented_area = 2.*(extent[0]*extent[1]+extent[1]*extent[2]+extent[0]*extent[2])
    spacing = math.sqrt(represented_area/count)
    basis = np.stack([tangent, bitangent, normal], axis=2)
    sigma = spacing*kernel_scale*np.array([1., .74, .12])
    covariance = np.einsum('nij,j,nkj->nik', basis, sigma*sigma, basis)
    colors = np.zeros((count, 3), dtype=np.float64)
    for i, material_id in enumerate(ids[selected]):
        if not 0 <= material_id < len(material_names):
            raise ValueError('Source triangle material ID has no material slot')
        name = json.dumps(material_names[int(material_id)]).lower()
        # Deliberate loading palette keyed to actual material identity; this is
        # not a claim to capture the source texture/base-color value.
        color = [.91, .84, .70]
        if 'wheel' in name or 'padding' in name:
            color = [.66, .62, .52]
        elif 'metal' in name or 'coupling' in name:
            color = [.96, .77, .47]
        elif 'capsule' in name:
            color = [.98, .93, .80]
        colors[i] = color
    light = normalize(np.array([-.5, 1., -.6]))
    # Emissive presentation keeps rear-facing points legible. The small normal
    # term preserves shape without turning wheel samples into near-black dust.
    shade = .80+.20*np.abs(normal@light)
    colors *= shade[:, None]
    low, high = v.min(axis=0), v.max(axis=0)
    center = (low+high)/2.
    return positions-center, covariance, colors, float(np.max(high-low)), normal


def camera(positions, size, width, height, azimuth, elevation):
    az, el = math.radians(azimuth), math.radians(elevation)
    eye = size*2.2*np.array([math.cos(el)*math.cos(az), math.sin(el), math.cos(el)*math.sin(az)])
    forward = normalize(-eye)
    right = normalize(np.cross(forward, np.array([0., 1., 0.])))
    up = normalize(np.cross(right, forward))
    matrix = np.stack([right, -up, forward])
    p = (positions-eye)@matrix.T
    # Reserve space for the bounded dissolve orbit. Fit source geometry itself.
    focal = min(width*.35/np.max(np.abs(p[:, 0]/p[:, 2])), height*.34/np.max(np.abs(p[:, 1]/p[:, 2])))
    return eye, matrix, focal


def dream(positions, covariance, phase, seeds, size, reduced=False):
    if reduced:
        return positions, covariance, np.ones(len(positions))
    # Start with the actual vehicle fully formed. No startup frame is black;
    # dissolution changes the point positions rather than fading the entire car.
    wave = .5+.5*math.cos(phase*2*math.pi)
    # Per-surface-sample stagger makes actual structure coalesce smoothly.
    formed = smooth(.03+seeds[:, 0]*.15, .69+seeds[:, 0]*.15, wave)
    disperse = 1-formed
    angle = seeds[:, 1]*2*math.pi + phase*2*math.pi
    displacement = np.stack([np.cos(angle), .45*np.sin(angle*2+seeds[:, 2]), np.sin(angle)], axis=1)
    displacement *= (size*.065*disperse)[:, None]
    # At formation, coherent sub-5mm mirage refraction keeps wheel/body detail.
    # Its phase depends on actual surface position, not independent jitter.
    ripple_phase = positions[:, 2]/size*7. + phase*2*math.pi
    ripple = np.stack([np.sin(ripple_phase), .3*np.sin(ripple_phase*1.4),
                       .25*np.cos(ripple_phase)], axis=1)
    displacement += size*.0008*formed[:, None]*ripple
    breathing = 1+.025*math.sin(phase*2*math.pi)
    scale = breathing + disperse*.06
    alpha = .62+.35*formed
    return positions+displacement, covariance*scale[:, None, None]**2, alpha


def render(positions, covariance, colors, opacity, eye, view, focal, width, height, max_sigma_px=.70):
    p = (positions-eye)@view.T
    depth = p[:, 2]
    x, y, z = p.T
    j = np.zeros((len(p), 2, 3), dtype=np.float64)
    j[:, 0, 0], j[:, 0, 2] = focal/z, -focal*x/(z*z)
    j[:, 1, 1], j[:, 1, 2] = focal/z, -focal*y/(z*z)
    cov_view = np.einsum('ij,njk,lk->nil', view, covariance, view)
    projected = np.einsum('nij,njk,nlk->nil', j, cov_view, j)
    # Subpixel low-pass in the projected covariance, not a circular substitute.
    projected[:, 0, 0] += .14
    projected[:, 1, 1] += .14
    # Bound the largest projected principal sigma while preserving anisotropy
    # and ellipse orientation. This presentation limit prevents large source
    # face ellipsoids from hiding neighboring wheel and body detail.
    half_trace = (projected[:, 0, 0]+projected[:, 1, 1])*.5
    largest_variance = half_trace + np.sqrt(((projected[:, 0, 0]-projected[:, 1, 1])*.5)**2
                                           + projected[:, 0, 1]**2)
    footprint_scale = np.minimum(1., max_sigma_px**2/largest_variance)
    projected *= footprint_scale[:, None, None]
    centers = p[:, :2]/z[:, None]*focal + np.array([width/2., height/2.])
    rgb = np.zeros((height, width, 3), dtype=np.float64)
    transmittance = np.ones((height, width), dtype=np.float64)
    for i in np.argsort(depth, kind='stable'):
        if z[i] <= .01 or opacity[i] < .003:
            continue
        cov = projected[i]
        det = np.linalg.det(cov)
        if not math.isfinite(det) or det <= 0:
            raise ValueError('Invalid projected positive covariance')
        # Principal covariance bounds: retain oriented ellipse inside this box.
        radius = 3.*np.sqrt(np.diag(cov))
        if radius.max() > max(width, height)*.25:
            raise ValueError('Pathological projection; reduce source covariance')
        cx, cy = centers[i]
        x0, x1 = max(0, math.floor(cx-radius[0])), min(width, math.ceil(cx+radius[0])+1)
        y0, y1 = max(0, math.floor(cy-radius[1])), min(height, math.ceil(cy+radius[1])+1)
        if x0 >= x1 or y0 >= y1:
            continue
        xx, yy = np.meshgrid(np.arange(x0, x1)+.5-cx, np.arange(y0, y1)+.5-cy)
        inv = np.array([[cov[1, 1], -cov[0, 1]], [-cov[1, 0], cov[0, 0]]])/det
        q = inv[0, 0]*xx*xx+2*inv[0, 1]*xx*yy+inv[1, 1]*yy*yy
        alpha = np.minimum(.98, opacity[i]*np.exp(-.5*q))
        alpha[q > 9.] = 0.
        patch_t = transmittance[y0:y1, x0:x1]
        weight = patch_t*alpha
        rgb[y0:y1, x0:x1] += weight[:, :, None]*colors[i]
        patch_t *= 1.-alpha
    # The compositor works in linear light; PNG color bytes need sRGB encoding.
    # Writing linear bytes directly made low-alpha Gaussian edges much too dim.
    linear = np.clip(rgb, 0., 1.)
    srgb = np.where(linear <= .0031308, linear*12.92,
                    1.055*np.power(linear, 1./2.4)-.055)
    return Image.fromarray(np.asarray(srgb*255.+.5, dtype=np.uint8))


def brightness(image):
    rgb = np.asarray(image, dtype=np.float64)
    luma = rgb @ np.array([.2126, .7152, .0722])
    visible = luma > 12.
    return {'mean_luma_all_pixels_0_255': float(luma.mean()),
            'visible_pixels_above_12': int(visible.sum()),
            'visible_luma_p50_0_255': float(np.percentile(luma[visible], 50)) if visible.any() else 0.,
            'visible_luma_p95_0_255': float(np.percentile(luma[visible], 95)) if visible.any() else 0.,
            'pixels_above_luma_128': int((luma > 128.).sum()),
            'maximum_luma_0_255': float(luma.max())}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mesh', type=Path, default=SCOPE/'carrier_geometry.json')
    parser.add_argument('--out', type=Path, default=SCOPE/'atlas_v1')
    parser.add_argument('--gaussians', type=int, default=5000)
    parser.add_argument('--frames', type=int, default=64)
    parser.add_argument('--width', type=int, default=512)
    parser.add_argument('--height', type=int, default=288)
    parser.add_argument('--azimuth', type=float, default=30.)
    parser.add_argument('--elevation', type=float, default=12.)
    parser.add_argument('--kernel-scale', type=float, default=.26)
    parser.add_argument('--max-sigma-px', type=float, default=.70)
    args = parser.parse_args()
    out = args.out.resolve()
    if not out.is_relative_to(SCOPE.resolve()) or out.exists():
        raise ValueError('Use a new output directory in the scoped loading_car folder')
    if not 2000 <= args.gaussians <= 12000 or args.frames != 64 or not 128 <= args.width <= 512 or not 72 <= args.height <= 288:
        raise ValueError('Bounded offline budget: 2k..12k ellipsoids; 64 frames; <=512x288')
    if not .20 <= args.kernel_scale <= .60 or not .60 <= args.max_sigma_px <= 2.:
        raise ValueError('Bounded presentation covariance scale/support required')
    source = json.loads(args.mesh.read_text(encoding='utf-8'))
    p, cov, color, size, normals = surface_gaussians(source, args.gaussians, args.kernel_scale)
    eye, view, focal = camera(p, size, args.width, args.height, args.azimuth, args.elevation)
    seeds = np.random.default_rng(1843).random((len(p), 3))
    out.mkdir(parents=True)
    atlas = Image.new('RGB', (args.width*8, args.height*8))
    images, frame_metrics = [], []
    for frame in range(args.frames):
        phase = frame/args.frames
        pp, cc, alpha = dream(p, cov, phase, seeds, size)
        # Actual perspective changes produce front/back parallax. Keep the base
        # focal length fixed so source-fitting does not cause scale pumping.
        orbit = math.sin(phase*2*math.pi)
        frame_eye, frame_view, _ = camera(p, size, args.width, args.height,
                                         args.azimuth+orbit*7.,
                                         args.elevation+2.*math.sin(phase*2*math.pi+.4))
        img = render(pp, cc, color, alpha, frame_eye, frame_view, focal, args.width, args.height, args.max_sigma_px)
        atlas.paste(img, ((frame%8)*args.width, (frame//8)*args.height))
        frame_metrics.append({'frame': frame, **brightness(img)})
        if frame in (0, 8, 16, 24, 32, 40, 48, 56):
            images.append(img)
            img.save(out/f'frame_{frame:02d}.png')
        print(f'LOADING_CAR_FRAME {frame+1}/{args.frames}', flush=True)
    target = out/'T_LoadingCarrier_GaussianAtlas.png'
    atlas.save(target, compress_level=6)
    still = render(p, cov, color, np.full(len(p), .92), eye, view, focal, args.width, args.height, args.max_sigma_px)
    still.save(out/'T_LoadingCarrier_GaussianStill.png')
    sheet = Image.new('RGB', (args.width*4, args.height*2))
    for i, img in enumerate(images):
        sheet.paste(img, ((i%4)*args.width, (i//4)*args.height))
    sheet.save(out/'contact_sheet.png')
    np.savez_compressed(out/'mesh_derived_gaussians.npz', position=p, covariance=cov, color=color, normal=normals)
    receipt = {'id': 'loading_car', 'representation': 'mesh_derived_anisotropic_gaussian_surface', 'trained': False,
        'source_asset': source['source_asset'], 'source_mesh_sha256': digest(args.mesh),
        'source_lod': source['source_lod'], 'source_kind': source['source_kind'],
        'renderer': 'CPU perspective Jacobian covariance + sorted Gaussian alpha transmittance',
        'sample_count': len(p), 'source_materials': source['materials'],
        'color': 'authored luminous ivory/warm brass palette keyed to source materials; textures not sampled; linear compositing exported as sRGB',
        'exterior_presentation': 'source retained intact; capsule lining and padding triangles excluded from loading covariance samples',
        'covariance_presentation': {'kernel_scale': args.kernel_scale, 'maximum_projected_sigma_px': args.max_sigma_px,
                                    'maximum_3sigma_support_px': 3.*args.max_sigma_px,
                                    'formed_displacement_max_m': size*.0008},
        'motion': {'starts_fully_formed': True, 'minimum_sample_opacity': .62,
                   'maximum_dissolve_displacement_m': size*.065,
                   'perspective_orbit_amplitude_degrees': 7.,
                   'perspective_elevation_amplitude_degrees': 2.},
        'brightness': {'units': 'sRGB Rec.709 weighted code values, 0..255',
                       'still': brightness(still), 'frames': frame_metrics},
        'atlas': {'file': target.name, 'sha256': digest(target), 'columns': 8, 'rows': 8, 'frames': 64,
                  'frame_size': [args.width, args.height], 'fps': 16, 'loop_seconds': 4, 'background': '#000000'},
        'still': 'T_LoadingCarrier_GaussianStill.png', 'view_azimuth_degrees': args.azimuth,
        'view_elevation_degrees': args.elevation, 'source_units': 'UE centimeters', 'render_units': 'glTF Y-up meters',
        'uses_gpu': False, 'uses_map_render': False, 'suitable_for_actual_gaussian_memories': False,
        'validation': 'Requires root visual review of actual atlas and startup integration'}
    (out/'receipt.json').write_text(json.dumps(receipt, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    print('LOADING_CAR_ATLAS '+json.dumps(receipt['atlas']), flush=True)


if __name__ == '__main__':
    main()
