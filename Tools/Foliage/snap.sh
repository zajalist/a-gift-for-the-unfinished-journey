#!/usr/bin/env bash
# Two-call scene capture: snap.sh NAME SOURCE CAMX CAMY CAMZ LOOKX LOOKY LOOKZ
# Writes Saved/Screenshots/V4/NAME.png (raw, with alpha) and NAME_rgb.png.
set -e
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
node Tools/Foliage/run_foliage.mjs py Tools/Foliage/capture.py "CAM=[$3, $4, $5]" "LOOK=[$6, $7, $8]" "NAME='$1'" "SOURCE='$2'" > /dev/null
node Tools/Foliage/run_foliage.mjs py Tools/Foliage/capture_export.py "NAME='$1'"
python -c "
from PIL import Image; import numpy as np, sys
a = np.asarray(Image.open('Saved/Screenshots/V4/$1.png'))[..., :3]
Image.fromarray(a).save('Saved/Screenshots/V4/$1_rgb.png'); print('max', a.max(), 'mean', round(float(a.mean()), 3))"
