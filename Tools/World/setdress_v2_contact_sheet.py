"""One contact sheet of every composed V2 site plot, plus the sites still to compose.

    python Tools/World/setdress_v2_contact_sheet.py        # -> docs/world/setdress_v2/CONTACT_SHEET.png

Reads the merged placement input (place_setdress.load_doc(v2=True)), the per-site plots in docs/world/setdress_v2/
(written by setdress_v2_groups/*.py) and the 61-site list (setdress_sites.json). Each tile is labelled with the
site, its archetype, its counts and the offline strict-judge result re-run here.
"""
import json
import os
import sys

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
import place_setdress as ps  # noqa: E402
import setdress_v2 as V  # noqa: E402

PLOTS = os.path.join(ROOT, 'docs', 'world', 'setdress_v2')
OUT = os.path.join(PLOTS, 'CONTACT_SHEET.png')
COLS, TILE_W, LABEL_H, PAD = 3, 820, 58, 14
BG, INK, DIM, OK, BAD, CARD = (24, 22, 20), (236, 230, 220), (160, 152, 140), (120, 190, 120), (230, 120, 100), (36, 33, 30)


def font(size, bold=False):
    for name in (('arialbd.ttf', 'segoeuib.ttf') if bold else ('arial.ttf', 'segoeui.ttf')):
        p = os.path.join(os.environ.get('WINDIR', 'C:/Windows'), 'Fonts', name)
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def actors(s):
    P = [p for p in s['placements'] if not p.get('optional')]
    return sum(1 for p in P if not p['ism']) + len({(p['group'], p['asset']) for p in P if p['ism']})


def main():
    doc = ps.load_doc(True)
    W = V.B.World()
    all_sites = json.load(open(os.path.join(HERE, 'setdress_sites.json'), encoding='utf8'))['sites']
    composed = {s['id'] for s in doc['sites']}
    tiles = []
    for s in doc['sites']:
        path = os.path.join(PLOTS, s['id'] + '.png')
        if not os.path.exists(path):
            continue
        im = Image.open(path).convert('RGB')
        im = im.resize((TILE_W, round(im.height * TILE_W / im.width)), Image.LANCZOS)
        v, _ = V.offline_check(W, s)
        c = s['counts']
        tiles.append((s, im, len(v), c))
    f_h, f_b, f_s = font(22, True), font(17), font(15)
    rows = [tiles[i:i + COLS] for i in range(0, len(tiles), COLS)]
    row_h = [max(t[1].height for t in r) + LABEL_H for r in rows]
    missing = [r for r in all_sites if r['id'] not in composed]
    story = [r for r in missing if r['id'] in ps.V2_STORY_SITES]
    todo = [r for r in missing if r['id'] not in ps.V2_STORY_SITES]
    head_h, list_line = 92, 24
    list_h = 70 + list_line * ((len(todo) + 2) // 3 + 2 + len(story))
    Wd = COLS * TILE_W + (COLS + 1) * PAD
    H = head_h + sum(row_h) + PAD * (len(rows) + 1) + list_h
    sheet = Image.new('RGB', (Wd, H), BG)
    d = ImageDraw.Draw(sheet)
    n_viol = sum(t[2] for t in tiles)
    d.text((PAD, 14), 'Saskarta set dressing V2: composed site plots (top-down + axonometric)', font=font(30, True),
           fill=INK)
    d.text((PAD, 54), '%d of %d sites composed, %d placements, strict offline contact check: %d violations.  '
                      'Road order; S07 is the prototype the user reviews first.' % (
                          len(tiles), len(all_sites), sum(t[3]['placements'] for t in tiles), n_viol),
           font=f_b, fill=DIM)
    y = head_h
    for r, h in zip(rows, row_h):
        x = PAD
        for s, im, nv, c in r:
            d.rectangle([x, y, x + TILE_W, y + h - 4], fill=CARD)
            d.text((x + 10, y + 6), '%s  (%s, road %d m)' % (s['id'], s.get('archetype'), s['road_m']), font=f_h,
                   fill=INK)
            d.text((x + 10, y + 34), '%d placements, %d actors, %d ISM, %d decals' % (
                c['placements'], actors(s), c['ism_instances'], c['decals']), font=f_s, fill=DIM)
            tag = 'contact OK' if nv == 0 else '%d violations' % nv
            tw = d.textlength(tag, font=f_b)
            d.text((x + TILE_W - tw - 10, y + 34), tag, font=f_b, fill=OK if nv == 0 else BAD)
            sheet.paste(im, (x, y + LABEL_H))
            x += TILE_W + PAD
        y += h + PAD
    d.text((PAD, y + 6), 'Not composed yet (%d): the V1 dressing stays until each is composed and placed' % len(todo),
           font=f_h, fill=BAD)
    y += 44
    colw = (Wd - 2 * PAD) // 3
    for i, r in enumerate(todo):
        cx, cy = PAD + (i % 3) * colw, y + (i // 3) * list_line
        d.text((cx, cy), '%s  %s' % (r['id'], r.get('kind', '')), font=f_s, fill=INK)
    y += list_line * ((len(todo) + 2) // 3) + 14
    d.text((PAD, y), 'Story sets, placed by their own lane (left out here):', font=f_b, fill=DIM)
    for i, r in enumerate(story):
        d.text((PAD + 20, y + list_line * (i + 1)), '%s  %s' % (r['id'], r.get('kind', '')), font=f_s, fill=DIM)
    sheet.save(OUT, optimize=True)
    print('wrote', OUT, sheet.size, 'tiles', len(tiles), 'not composed', len(todo), 'violations', n_viol)


if __name__ == '__main__':
    main()
