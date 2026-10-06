"""Offline inventory of the set-dressing packs: every StaticMesh's bounds, triangle count,
Nanite and collision flags, read straight from the .uasset asset-registry tags (no editor).

    python Tools/World/scan_setdress_assets.py            # writes Tools/World/setdress_assets.json
    python Tools/World/scan_setdress_assets.py --print    # also prints a summary per pack

A cooked-or-not StaticMesh package stores its asset-registry tags as FString pairs
(int32 length incl. NUL, bytes). UStaticMesh writes ApproxSize ("XxYxZ", whole cm, the
bounding-box size), Triangles, NaniteEnabled, NaniteTriangles, CollisionPrims,
CollisionComplexity and DefaultCollision. The pivot is NOT in the tags: the editor lane
seats every mesh from its live bounds (place_setdress.py does that), so only the size is
needed offline, for the footprint, the overlap budget and the settle mode.
"""
import argparse
import json
import os
import struct

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CONTENT = os.path.join(ROOT, 'Content')
OUT = os.path.join(ROOT, 'Tools', 'World', 'setdress_assets.json')

PACKS = {
    'AshesOfBazaar': 'AshesOfBazaar',
    'MedievalVillage': 'MedievalVillage',
    'FabMegascans': 'Fab/Megascans',
    'FabTwig': 'Fab/Twig_V4_PBR',
    'LightFoliage': 'Light_Foliage/Meshes',
    'PolyHaven': 'Pallbearer/PolyHaven',
    'Tripo': 'Pallbearer/Tripo',
    'Vefects': 'Vefects',
    'SaskartaGaea': 'SaskartaGaea',
    'EasyAtmos': 'EasyAtmos/EpicContentDemo',
}
KEEP = ('ApproxSize', 'Triangles', 'NaniteEnabled', 'NaniteTriangles', 'CollisionPrims',
        'CollisionComplexity', 'DefaultCollision', 'LODs', 'Materials')


def read_tags(data):
    """Return the asset-registry tag dict of a StaticMesh package, or None."""
    if data.find(b'\x0b\x00\x00\x00ApproxSize\x00') < 0:
        return None
    # Each tag is found by its own length-prefixed key, so the block's order and its
    # other (pack-specific) keys don't matter.
    tags = {}
    for key in KEEP:
        pat = struct.pack('<i', len(key) + 1) + key.encode('latin1') + b'\x00'
        at = data.find(pat)
        if at < 0:
            continue
        j = at + len(pat)
        n = struct.unpack_from('<i', data, j)[0]
        if 0 < n < 4096:
            tags[key] = data[j + 4:j + 3 + n].decode('latin1')
    return tags


def package_path(abs_path):
    rel = os.path.relpath(abs_path, CONTENT).replace('\\', '/')
    return '/Game/' + rel[:-len('.uasset')]


def kind_of(name, tags):
    if tags is not None:
        return 'SM'
    if name.startswith('NS_'):
        return 'NS'
    if name.startswith('BPP_'):
        return 'BPP'
    if name.startswith('BP_'):
        return 'BP'
    return None


def scan():
    assets = {}
    for pack, rel in PACKS.items():
        base = os.path.join(CONTENT, rel)
        for dirpath, _, files in os.walk(base):
            for f in files:
                if not f.endswith('.uasset'):
                    continue
                p = os.path.join(dirpath, f)
                name = f[:-len('.uasset')]
                # Only meshes, Niagara systems and blueprints are placeable.
                unix = p.replace('\\', '/')
                if not (name.startswith(('SM_', 'sm_', 'NS_', 'BP_', 'BPP_')) or '/StaticMeshes/' in unix
                        or (pack == 'EasyAtmos' and '/Meshes/' in unix)):
                    continue
                with open(p, 'rb') as fh:
                    data = fh.read()
                tags = read_tags(data)
                kind = kind_of(name, tags)
                if kind is None:
                    continue
                entry = {'pack': pack, 'kind': kind, 'file_mb': round(len(data) / 1e6, 1)}
                if tags:
                    size = [float(v) for v in tags.get('ApproxSize', '0x0x0').split('x')]
                    entry.update({
                        'size_cm': size,
                        'tris': int(tags.get('Triangles', '0') or 0),
                        'nanite': tags.get('NaniteEnabled') == 'True',
                        'nanite_tris': int(tags.get('NaniteTriangles', '0') or 0),
                        'collision_prims': int(tags.get('CollisionPrims', '0') or 0),
                        'collision': tags.get('CollisionComplexity', ''),
                        'default_collision': tags.get('DefaultCollision', ''),
                    })
                assets[package_path(p)] = entry
    return dict(sorted(assets.items()))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--print', action='store_true')
    args = ap.parse_args()
    assets = scan()
    doc = {'generated_by': 'Tools/World/scan_setdress_assets.py',
           'note': 'size_cm is the ApproxSize tag (bounding-box size, X x Y x Z, whole cm). Pivot unknown offline.',
           'assets': assets}
    with open(OUT, 'w', encoding='utf8') as fh:
        json.dump(doc, fh, indent=1)
    if args.print:
        per = {}
        for a in assets.values():
            per.setdefault((a['pack'], a['kind']), 0)
            per[(a['pack'], a['kind'])] += 1
        for k, v in sorted(per.items()):
            print('%-16s %-4s %d' % (k[0], k[1], v))
    print('wrote %s (%d assets)' % (OUT, len(assets)))


if __name__ == '__main__':
    main()
