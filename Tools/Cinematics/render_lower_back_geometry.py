"""Render actual source-skinned surfaces to expose pose-opened waist gaps."""
from pathlib import Path
import json
import math
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.collections import PolyCollection
import traveller_contacts as contacts
import samyor_reveal as rig

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'Saved/Verification/lower_back_audit_20261001'


def read_pose(path):
    line = next(x for x in path.read_text().splitlines() if x.startswith('TRAVELLER_POSE '))
    data = json.loads(line.split(' ', 1)[1])
    return data, {b: (tuple(v[0][:3]), tuple(v[0][3:7]), tuple(v[0][7:])) for b, v in data['bones'].items()}


def draw(ax, points, triangles, angle=30):
    a = math.radians(angle)
    forward = np.array((0, math.cos(a), -math.sin(a)))
    up = np.array((0, math.sin(a), math.cos(a)))
    surface = points[triangles[:, [0, 2, 1]]]
    normals = np.cross(surface[:, 1]-surface[:, 0], surface[:, 2]-surface[:, 0])
    mask = normals @ forward < 0
    surface, normals = surface[mask], normals[mask]
    order = np.argsort((surface.mean(axis=1) @ forward))[::-1]
    surface, normals = surface[order], normals[order]
    xy = np.stack((surface[:, :, 0], surface @ up), axis=2)
    unit = normals / np.maximum(np.linalg.norm(normals, axis=1)[:, None], 1e-9)
    value = .34 + .5 * np.abs(unit @ -forward)
    colors = np.column_stack((value*.82, value*.88, value, np.ones(len(value))))
    ax.add_collection(PolyCollection(xy, facecolors=colors, edgecolors='none', antialiased=False))
    ax.set_facecolor('#db692f')
    ax.set_xlim(-30, 30)
    ax.set_ylim(74, 108)
    ax.set_aspect('equal')
    ax.set_xlabel('component X (cm)')
    ax.set_ylabel('projected height (cm)')


def main():
    _, _, triangles = contacts.source_body()
    samples = [('Reference', rig.REF_LOCAL)]
    for name in ('01_idle_pose.readback.txt', '02_idle_pose.readback.txt'):
        data, pose = read_pose(OUT/name)
        samples.append((data['clip']+' at '+str(round(data['at'], 2))+' s', pose))
    fig, axes = plt.subplots(1, len(samples), figsize=(15, 5), layout='constrained')
    for ax, (name, pose) in zip(axes, samples):
        draw(ax, contacts.skin(pose), triangles)
        ax.set_title(name)
    fig.suptitle('Same source mesh, rear view 30° down; orange = no outward-facing surface\nOpaque solid geometry only, not a rendered game frame')
    target = OUT/'waist-pose-comparison.png'
    fig.savefig(target, dpi=180)
    print(target)


if __name__ == '__main__':
    main()
