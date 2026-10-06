"""Gently sharpen real albedo detail without painting noise or baked illumination."""
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2] / 'SourceArt' / 'Tripo' / '20261003' / 'S26_VictorianRadioStation' / 'extracted'
SOURCE = ROOT / 'tower_basecolor_S26_RelayTower_ReUV_Fine_8k.png'
DEST = ROOT / 'tower_basecolor_S26_RelayTower_ReUV_Fine_8k_refined.png'

image = cv2.imread(str(SOURCE), cv2.IMREAD_COLOR)
if image is None or image.shape[:2] != (8192, 8192):
    raise ValueError(f'Expected 8K source: {SOURCE}')
result = np.empty_like(image)
tile = 1024
pad = 24
for y in range(0, image.shape[0], tile):
    for x in range(0, image.shape[1], tile):
        y0, y1 = max(0, y - pad), min(image.shape[0], y + tile + pad)
        x0, x1 = max(0, x - pad), min(image.shape[1], x + tile + pad)
        patch = image[y0:y1, x0:x1]
        lab = cv2.cvtColor(patch, cv2.COLOR_BGR2LAB)
        light = lab[:, :, 0].astype(np.float32)
        near = cv2.GaussianBlur(light, (0, 0), 1.35)
        mid = cv2.GaussianBlur(light, (0, 0), 6.0)
        high = light - near
        medium = light - mid
        # Keep island edges and the black atlas background untouched.
        valid = (np.max(patch, axis=2) > 12).astype(np.uint8)
        valid = cv2.erode(valid, np.ones((5, 5), np.uint8), iterations=1)
        change = np.where(np.abs(high) > 1.2, 0.58 * high, 0.0) + 0.08 * medium
        sharpened = np.clip(light + change * valid, 0, 255).astype(np.uint8)
        lab[:, :, 0] = sharpened
        polished = cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)
        sy, sx = y - y0, x - x0
        ey, ex = min(tile, image.shape[0] - y), min(tile, image.shape[1] - x)
        result[y:y + ey, x:x + ex] = polished[sy:sy + ey, sx:sx + ex]
    print(f'refined row {y // tile + 1}/8', flush=True)
if not cv2.imwrite(str(DEST), result, [cv2.IMWRITE_PNG_COMPRESSION, 3]):
    raise OSError(DEST)
print(DEST)
