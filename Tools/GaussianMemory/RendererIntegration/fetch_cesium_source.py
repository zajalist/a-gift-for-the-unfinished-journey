"""Stage the official UE 5.8 Cesium source release; never enable or load it."""
import hashlib
import json
import pathlib
import urllib.request
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[3]
EVIDENCE = ROOT / "Saved/Verification/gaussian_memory_20261001/renderer_integration"
DEST = ROOT / "Plugins/CesiumForUnreal"
NAME = "CesiumForUnreal-58-SourceOnly-v2.29.1.zip"
EXPECTED = "19d103edb08cd6abe0d729386ec4d085d07d415e1b8922133807de7c3240ab0e"
URL = "https://github.com/CesiumGS/cesium-unreal/releases/download/v2.29.1/" + NAME

EVIDENCE.mkdir(parents=True, exist_ok=True)
archive = EVIDENCE / NAME
if not archive.exists():
    print("Downloading official source-only release", flush=True)
    urllib.request.urlretrieve(URL, archive)
digest = hashlib.file_digest(archive.open("rb"), "sha256").hexdigest()
if digest != EXPECTED:
    raise RuntimeError("Official archive SHA256 mismatch: " + digest)
print("Archive digest verified", flush=True)
with zipfile.ZipFile(archive) as z:
    names = z.namelist()
    descriptor = next(n for n in names if n.endswith("/CesiumForUnreal.uplugin") or n == "CesiumForUnreal.uplugin")
    prefix = descriptor[: -len("CesiumForUnreal.uplugin")]
    for entry in z.infolist():
        if not entry.filename.startswith(prefix) or entry.is_dir():
            continue
        rel = pathlib.PurePosixPath(entry.filename[len(prefix):])
        if rel.is_absolute() or ".." in rel.parts:
            raise RuntimeError("Unsafe archive entry: " + entry.filename)
        # Source-only release has native libraries and assets, never live UE DLLs.
        target = DEST.joinpath(*rel.parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            raise RuntimeError("Refusing to overwrite staged file: " + str(target))
        target.write_bytes(z.read(entry))
(EVIDENCE / "install_source_release.json").write_text(json.dumps({
    "release": "v2.29.1", "engine_archive": "UE5.8 source only", "url": URL,
    "archive_sha256": digest, "destination": str(DEST),
    "state": "staged_source_only_not_enabled_not_built_not_rendered",
    "archive_entries": len(names),
}, indent=2))
print("Staged source plugin: " + str(DEST), flush=True)
