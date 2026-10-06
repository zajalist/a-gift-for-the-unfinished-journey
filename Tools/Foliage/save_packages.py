# Save an explicit list of packages (Task V4). Sent through
# Tools/Foliage/run_foliage.mjs py, which rewrites the PATHS and PACKAGES lines.
# PATHS are asset paths; PACKAGES are raw package names such as a World
# Partition actor's /Game/__ExternalActors__/... package. Saves only what is
# listed; never the level, never "save all".
import unreal

PATHS = []
PACKAGES = []

eal = unreal.EditorAssetLibrary
for p in PATHS:
    ok = eal.save_asset(p, False)
    print('SAVE ' + p + ' ok=' + str(ok))
if len(PACKAGES) > 0:
    pkgs = [unreal.load_package(n) for n in PACKAGES]
    ok = unreal.EditorLoadingAndSavingUtils.save_packages(pkgs, False)
    print('SAVE packages ' + str(PACKAGES) + ' ok=' + str(ok))
