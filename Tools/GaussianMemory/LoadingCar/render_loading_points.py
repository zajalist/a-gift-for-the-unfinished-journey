"""Render the real carrier surface as discrete, circular screen-space points.

The previous loading atlas used overlapping anisotropic Gaussians. This renderer
keeps its source mesh, camera and formation motion, but each sample is a compact
round point with no ellipse or brush-shaped footprint.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np
from PIL import Image
import trimesh

from render_loading_atlas import SCOPE, camera, dream
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'ModelReview'))
from fbx_reader import read_fbx  # noqa: E402
from review_models import Mesh  # noqa: E402


def sample_full_carrier(fbx_path, count):
    """Use all actual source triangles, rather than the old 1200-triangle preview."""
    scene = read_fbx(str(fbx_path))
    triangles = []
    areas = []
    palettes = []
    wheel_ids = []
    wheel_centers = {}
    for geometry in scene.geometries.values():
        name = geometry.name.lower()
        if 'padding' in name:
            continue
        mesh = Mesh(scene, geometry)
        xyz = mesh.verts.copy()
        xyz[:, 1] *= -1.0  # Match the imported UE skeletal mesh's Y convention.
        xyz = xyz[:, [0, 2, 1]] / 100.0
        wheel_id = len(wheel_centers) + 1 if 'wheel' in name else 0
        if wheel_id:
            wheel_centers[wheel_id] = (xyz.min(0) + xyz.max(0)) / 2
        tri = xyz[mesh.tri_vid]
        area = np.linalg.norm(np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]), axis=1) / 2
        valid = area > 1e-12
        tri, area = tri[valid], area[valid]
        triangles.append(tri)
        areas.append(area)
        palette = [.91, .84, .70]
        if 'wheel' in name:
            palette = [.66, .62, .52]
        elif 'tripo' in name:
            palette = [.98, .93, .80]
        palettes.append(np.tile(palette, (len(tri), 1)))
        wheel_ids.append(np.full(len(tri), wheel_id, dtype=np.int16))
    triangles = np.concatenate(triangles)
    areas = np.concatenate(areas)
    palettes = np.concatenate(palettes)
    wheel_ids = np.concatenate(wheel_ids)
    rng = np.random.default_rng(3102026)
    chosen = np.searchsorted(np.cumsum(areas), (np.arange(count) + rng.random(count)) * areas.sum() / count)
    r = np.sqrt(rng.random(count))
    s = rng.random(count)
    bary = np.stack([1 - r, r * (1 - s), r * s], axis=1)
    points = np.einsum('ni,nij->nj', bary, triangles[chosen])
    colors = palettes[chosen]
    point_wheels = wheel_ids[chosen]
    low, high = triangles.reshape(-1, 3).min(0), triangles.reshape(-1, 3).max(0)
    center = (low + high) / 2
    points -= center
    wheel_centers = {key: value - center for key, value in wheel_centers.items()}
    size = float(np.max(high - low))
    covariance = np.tile(np.eye(3), (count, 1, 1))
    return points, covariance, colors, size, len(triangles), point_wheels, wheel_centers


def sample_road_object(path, count, seed, color):
    scene = trimesh.load(path, force='scene')
    mesh = scene.to_geometry()
    triangles = np.asarray(mesh.vertices, dtype=np.float64)[np.asarray(mesh.faces, dtype=np.int64)]
    area = np.linalg.norm(np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0]), axis=1) / 2
    valid = area > 1e-12
    triangles, area = triangles[valid], area[valid]
    rng = np.random.default_rng(seed)
    chosen = np.searchsorted(np.cumsum(area), (np.arange(count) + rng.random(count)) * area.sum() / count)
    r, s = np.sqrt(rng.random(count)), rng.random(count)
    bary = np.stack([1 - r, r * (1 - s), r * s], axis=1)
    points = np.einsum('ni,nij->nj', bary, triangles[chosen])
    points -= (points.min(0) + points.max(0)) / 2
    points *= .95 / max(np.ptp(points, axis=0))
    return points, np.tile(color, (count, 1))


def point_frame(positions, colors, alpha, eye, view, focal, width, height):
    projected = (positions - eye) @ view.T
    depth = projected[:, 2]
    good = depth > 0.01
    xy = projected[good, :2] / depth[good, None] * focal
    xy += np.array([width / 2, height / 2])
    colors = colors[good]
    alpha = alpha[good]
    depth = depth[good]
    # Draw back to front so one point remains one dot even at silhouette overlap.
    order = np.argsort(depth)[::-1]
    xy, colors, alpha = xy[order], colors[order], alpha[order]
    canvas = np.zeros((height, width, 3), dtype=np.float32)
    # A 1.25 px diameter is intentionally smaller than the old Gaussian support.
    # Four coverage samples antialias each circular point without elongation.
    for (x, y), color, opacity in zip(xy, colors, alpha):
        if x < 1 or x >= width - 1 or y < 1 or y >= height - 1:
            continue
        ix, iy = int(math.floor(x)), int(math.floor(y))
        for py in (iy, iy + 1):
            for px in (ix, ix + 1):
                coverage = max(0.0, 1.0 - math.hypot(px + 0.5 - x, py + 0.5 - y) / 0.85)
                if coverage > 0:
                    canvas[py, px] = np.maximum(canvas[py, px], color * opacity * coverage)
    linear = np.clip(canvas, 0.0, 1.0)
    srgb = np.where(linear <= .0031308, linear * 12.92,
                    1.055 * np.power(linear, 1.0 / 2.4) - .055)
    return Image.fromarray(np.uint8(np.clip(srgb * 255 + .5, 0, 255)), 'RGB')


def main():
    root = Path(__file__).resolve().parents[3]
    p = argparse.ArgumentParser()
    p.add_argument('--mesh', type=Path, default=Path('SourceArt/Characters/Carrier/carrier01_full.fbx'))
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--points', type=int, default=8000)
    p.add_argument('--frames', type=int, default=64)
    p.add_argument('--azimuth', type=float, default=30)
    p.add_argument('--elevation', type=float, default=12)
    a = p.parse_args()
    out = a.out.resolve()
    if not out.is_relative_to(SCOPE.resolve()) or out.exists():
        raise ValueError('Output must be a new directory under the loading car scope')
    if not 3000 <= a.points <= 12000 or a.frames not in (1, 64):
        raise ValueError('Expected 3000..12000 points and 1 or 64 frames')
    positions, covariance, colors, size, triangle_count, point_wheels, wheel_centers = sample_full_carrier(a.mesh, a.points)
    eye, view, focal = camera(positions, size, 512, 288, a.azimuth, a.elevation)
    seeds = np.random.default_rng(1843).random((len(positions), 3))
    road_objects = [
        (*sample_road_object(root / 'SourceArt/Tripo/milestone/milestone.glb', 700, 401, [.91, .67, .35]), -2.75, .50, 0.0),
        (*sample_road_object(root / 'SourceArt/Tripo/signal_mirror/signal_mirror.glb', 800, 402, [.83, .73, .52]), 2.75, .40, 1.8),
        (*sample_road_object(root / 'SourceArt/Tripo/stone_terrace/stone_terrace.glb', 600, 403, [.72, .60, .43]), -1.9, -1.00, 3.2),
    ]
    out.mkdir(parents=True)
    atlas = Image.new('RGB', (4096, 2304)) if a.frames == 64 else None
    shown = []
    for frame in range(a.frames):
        phase = frame / 64
        moved, _cov, alpha = dream(positions, covariance, phase, seeds, size)
        moved = moved.copy()
        wheel_angle = 4 * math.pi * phase
        wheel_turn = np.array([[1, 0, 0], [0, math.cos(wheel_angle), -math.sin(wheel_angle)],
                               [0, math.sin(wheel_angle), math.cos(wheel_angle)]])
        for wheel_id, center in wheel_centers.items():
            mask = point_wheels == wheel_id
            moved[mask] = (moved[mask] - center) @ wheel_turn.T + center
        moved[:, 1] += .025 * math.sin(phase * 4 * math.pi)
        orbit = math.sin(phase * 2 * math.pi)
        frame_eye, frame_view, _ = camera(positions, size, 512, 288,
                                          a.azimuth + orbit * 7,
                                          a.elevation + 2 * math.sin(phase * 2 * math.pi + .4))
        all_positions, all_colors, all_alpha = [moved], [colors], [alpha]
        for object_points, object_colors, screen_x, screen_y, beat in road_objects:
            angle = .22 * math.sin(phase * 2 * math.pi + beat)
            rotation = np.array([[math.cos(angle), 0, -math.sin(angle)],
                                 [0, 1, 0],
                                 [math.sin(angle), 0, math.cos(angle)]])
            bob = .12 * math.sin(phase * 2 * math.pi + beat)
            offset = view[0] * screen_x + view[1] * (screen_y + bob)
            all_positions.append(object_points @ rotation.T + offset)
            all_colors.append(object_colors)
            all_alpha.append(np.full(len(object_points), .75))
        image = point_frame(np.concatenate(all_positions), np.concatenate(all_colors),
                            np.concatenate(all_alpha), frame_eye, frame_view, focal, 512, 288)
        if atlas:
            atlas.paste(image, ((frame % 8) * 512, (frame // 8) * 288))
        if frame in (0, 8, 16, 24, 32, 40, 48, 56):
            shown.append(image)
            image.save(out / f'frame_{frame:02d}.png')
        print(f'POINT_FRAME {frame + 1}/{a.frames}', flush=True)
    still_positions = [positions]
    still_colors = [colors]
    still_alpha = [np.full(a.points, .95)]
    for object_points, object_colors, screen_x, screen_y, _beat in road_objects:
        still_positions.append(object_points + view[0] * screen_x + view[1] * screen_y)
        still_colors.append(object_colors)
        still_alpha.append(np.full(len(object_points), .75))
    still = point_frame(np.concatenate(still_positions), np.concatenate(still_colors),
                        np.concatenate(still_alpha), eye, view, focal, 512, 288)
    still.save(out / 'T_LoadingCarrier_PointStill.png')
    if atlas:
        atlas.save(out / 'T_LoadingCarrier_PointAtlas.png', compress_level=6)
        sheet = Image.new('RGB', (2048, 576))
        for i, image in enumerate(shown):
            sheet.paste(image, ((i % 4) * 512, (i // 4) * 288))
        sheet.save(out / 'contact_sheet.png')
    receipt = {'representation': 'mesh_surface_isotropic_screen_points',
               'source_asset': '/Game/SaskartaGaea/Characters/Carrier/Full/SK_CarrierFull',
               'source_fbx': str(a.mesh), 'source_sha256': hashlib.sha256(a.mesh.read_bytes()).hexdigest(),
               'source_triangles': triangle_count,
               'road_objects': ['milestone', 'signal_mirror', 'stone_terrace'],
               'carrier_motion': 'spinning source wheels, chassis bob, point formation, camera orbit',
               'point_count': a.points, 'frames': a.frames, 'point_diameter_px': 1.25,
               'anisotropic_covariance': False, 'source_geometry_changed': False}
    (out / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
