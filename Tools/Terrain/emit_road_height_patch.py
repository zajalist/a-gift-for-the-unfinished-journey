#!/usr/bin/env python3
"""Package a guarded regional height edit from the review-only candidate.

    python Tools/Terrain/emit_road_height_patch.py

Produces little-endian uint16 source/target rectangles and a manifest under
Saved/TerrainRegrade/Local42Patch. No editor, Landscape or source map writes.
The editor helper must compare *every* baseline sample before applying any
target sample, and must refuse an unexpected edit-layer or component layout.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SOURCE = ROOT / "Saved/TerrainRebuild/Current_u16.png"
DEFAULT_CANDIDATE = ROOT / "Saved/TerrainRegrade/local42_review_u16.png"
DEFAULT_OUT = ROOT / "Saved/TerrainRegrade/Local42Patch"
ORIGIN_CM = (-18920.4, 50.0)
XY_CM_PER_PIXEL = 100.0
Z_CM_PER_U16 = 1.5625
EXPECTED_SHAPE = (8161, 8161)


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def emit(source: Path, candidate: Path, output_dir: Path) -> dict:
    Image.MAX_IMAGE_PIXELS = None
    with Image.open(source) as image:
        old = np.asarray(image)
    with Image.open(candidate) as image:
        new = np.asarray(image)
    if (old.dtype != np.uint16 or new.dtype != np.uint16 or
            old.shape != EXPECTED_SHAPE or new.shape != EXPECTED_SHAPE):
        raise ValueError("source and candidate must be aligned 8161x8161 uint16 heightmaps")
    changed = old != new
    if not np.any(changed):
        raise ValueError("heightmaps are identical")
    yy, xx = np.nonzero(changed)
    # Two unchanged vertex samples around the edit make the bounded readback
    # and edge-normal inspection possible without touching adjacent regions.
    col0 = max(0, int(xx.min()) - 2)
    row0 = max(0, int(yy.min()) - 2)
    col1 = min(old.shape[1] - 1, int(xx.max()) + 2)
    row1 = min(old.shape[0] - 1, int(yy.max()) + 2)
    source_roi = old[row0:row1 + 1, col0:col1 + 1].astype("<u2", copy=False)
    target_roi = new[row0:row1 + 1, col0:col1 + 1].astype("<u2", copy=False)
    source_bytes, target_bytes = source_roi.tobytes(order="C"), target_roi.tobytes(order="C")
    output_dir.mkdir(parents=True, exist_ok=True)
    source_path = output_dir / "source_roi.r16"
    target_path = output_dir / "target_roi.r16"
    source_path.write_bytes(source_bytes)
    target_path.write_bytes(target_bytes)
    manifest = {
        "review_only": True,
        "editor_apply_authorized": False,
        "source_image": str(source),
        "candidate_image": str(candidate),
        "image_pixels": [old.shape[1], old.shape[0]],
        "pixel_bounds_inclusive": [col0, row0, col1, row1],
        "roi_pixels": [source_roi.shape[1], source_roi.shape[0]],
        "world_origin_cm": list(ORIGIN_CM),
        "xy_cm_per_pixel": XY_CM_PER_PIXEL,
        "z_cm_per_u16_step": Z_CM_PER_U16,
        "world_bounds_cm_inclusive": [
            ORIGIN_CM[0] + col0 * XY_CM_PER_PIXEL,
            ORIGIN_CM[1] + row0 * XY_CM_PER_PIXEL,
            ORIGIN_CM[0] + col1 * XY_CM_PER_PIXEL,
            ORIGIN_CM[1] + row1 * XY_CM_PER_PIXEL,
        ],
        "changed_pixels": int(changed.sum()),
        "source_roi": str(source_path),
        "target_roi": str(target_path),
        "source_roi_sha256": _hash(source_bytes),
        "target_roi_sha256": _hash(target_bytes),
        "format": "row-major little-endian uint16, no header, inclusive XY bounds",
        "required_preflight": [
            "loaded Landscape extent and XY/Z transform exactly match manifest",
            "all overlapping World Partition Landscape components loaded and writable",
            "selected edit layer and composed-height relationship explicitly verified",
            "every live uint16 height in rectangle equals source_roi before any write",
            "scoped backup of affected Landscape component packages exists",
        ],
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    if source_path.read_bytes() != source_bytes or target_path.read_bytes() != target_bytes:
        raise RuntimeError("regional patch file readback mismatch")
    return manifest


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    ap.add_argument("--candidate", type=Path, default=DEFAULT_CANDIDATE)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()
    manifest = emit(args.source, args.candidate, args.out)
    print(f"REVIEW ONLY: {manifest['changed_pixels']} changed pixels in "
          f"{manifest['roi_pixels']} ROI, manifest={args.out / 'manifest.json'}")


if __name__ == "__main__":
    main()
