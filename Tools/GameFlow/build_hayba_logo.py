"""Rasterize the official Hayba vector with its orange cap merged into one path."""
from pathlib import Path
import cairosvg
from PIL import Image

root = Path(__file__).resolve().parents[2]
source = root / 'SourceArt/UI/HaybaLogo.clean.svg'
target = root / 'SourceArt/UI/T_Hayba_Logo_clean.png'
svg = source.read_text(encoding='utf-8')
assert svg.count('fill="#B56A1D"') == 1
cairosvg.svg2png(bytestring=svg.encode('utf-8'), write_to=str(target),
                 output_width=1156, output_height=1400)
image = Image.open(target)
assert image.size == (1156, 1400) and image.mode == 'RGBA'
print(target)
