import pathlib
import sys

# The audio tools are plain scripts, not a package: import them from Tools/Audio.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
