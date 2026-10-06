"""Exact project/archive manifests. No Unreal, network, deployment or Git calls.

snapshot before UAT; bind-build after success; prepare only when inputs still match.
The archive-only uproject disables three optional editor tools. Runtime files stay exact.
"""
from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import struct
import zipfile


ROOT = Path(__file__).resolve().parents[2]
UPROJECT = "saskartarad.uproject"
MANIFEST = "PROJECT_ARCHIVE_MANIFEST.json"
DEPENDENCIES = "PROJECT_ARCHIVE_DEPENDENCIES.json"
EXCLUDED = {"intermediate", "deriveddatacache", "__pycache__", ".pytest_cache", ".git"}
OPTIONAL_EDITOR = {"Aura", "AIAssistant", "InEditorDocumentation"}
INPUTS = [UPROJECT, "Build", "Config", "Content", "Plugins", "Shaders", "Source"]
ENTRIES = [UPROJECT, "README.md", "COMRADE_START_HERE.md", ".gitignore", ".gitattributes",
           "Binaries", "Build", "Config", "Content", "Plugins", "Shaders", "SourceArt", "Tools", "docs",
           "Saved/RadioRecordings", "Saved/Screenshots/TripoExtras", "Saved/SetDress", "Saved/Tripo"]
BREATH_DIR = "Saved/Verification/audio_completion_20261001"
BREATH_AUDIT = "Saved/Verification/breath_asset_audit_20261001/audit_with_previews.json"
S26 = ["s26_fence_panel", "s26_gate_open", "s26_radio_station", "s26_transmitter_cabinet"]
STATION = "Content/__ExternalActors__/level/Saskarta_WP/2/5R/1L47KCG69RV15XKPKRWNS6.uasset"
REF = re.compile(rb"/Game/[A-Za-z0-9_./-]+(?=\x00)")
WIDE_REF = re.compile(rb"/\x00G\x00a\x00m\x00e\x00/\x00(?:[A-Za-z0-9_./-]\x00)+\x00\x00")
WORLD_CANDIDATES = "Saved/Verification/world_persistence_audit_20261001/hlod_selection/candidates.json"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def load(path):
    text = Path(path).read_text(encoding="utf-8-sig")
    # UE plugin descriptors permit JSON comments/trailing commas. Preserve string literals.
    strings_or_comments = r'"(?:\\.|[^"\\])*"|//[^\r\n]*|/\*[\s\S]*?\*/'
    text = re.sub(strings_or_comments, lambda m: m[0] if m[0].startswith('"') else " ", text)
    strings_or_trailing = r'"(?:\\.|[^"\\])*"|,(?=\s*[}\]])'
    text = re.sub(strings_or_trailing, lambda m: m[0] if m[0].startswith('"') else "", text)
    return json.loads(text)


def encoded(value):
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")


def write_new(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(encoded(value))


def digest_bytes(data):
    return hashlib.sha256(data).hexdigest()


def digest(path):
    path = Path(path)
    before = path.stat()
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    after = path.stat()
    require((before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns),
            f"File changed while hashing: {path}")
    return h.hexdigest()


def safe_name(name):
    name = str(name).replace("\\", "/")
    p = PurePosixPath(name)
    require(not p.is_absolute() and name and all(x not in ("", ".", "..") for x in name.split("/"))
            and not any(c in name for c in (":", "\n", "\r", "\0")), f"Unsafe archive path: {name!r}")
    return name


def excluded(name, runtime=False):
    parts = PurePosixPath(name).parts
    return (any(p.lower() in EXCLUDED for p in parts) or
            (runtime and any(p.lower() in {"binaries", "saved"} for p in parts)) or
            ".bak" in parts[-1].lower() or parts[-1].lower().endswith(".pyc"))


def files_under(root, entries, runtime=False):
    root = Path(root).resolve()
    result = set()
    for entry in entries:
        entry = safe_name(entry)
        target = root / entry
        if entry == "Source" and not target.exists():
            continue
        require(target.exists(), f"Missing required entry: {entry}")
        pending = [target]
        while pending:
            path = pending.pop()
            rel = path.relative_to(root).as_posix()
            if excluded(rel, runtime):
                continue
            st = path.lstat()
            require(not path.is_symlink() and not (getattr(st, "st_file_attributes", 0) & 0x400),
                    f"Symlink/reparse point is not a portable archive input: {rel}")
            if path.is_dir():
                pending.extend(path.iterdir())
            elif path.is_file():
                result.add(safe_name(rel))
    require(len({p.casefold() for p in result}) == len(result), "Case-colliding Windows paths")
    return sorted(result)


def fingerprint(root, names):
    return {name: {"bytes": (root / name).stat().st_size, "sha256": digest(root / name)} for name in names}


def runtime_state(root):
    names = files_under(root, INPUTS, runtime=True)
    result = fingerprint(root, names)
    require(names == files_under(root, INPUTS, runtime=True), "Runtime file set changed during capture")
    return result


def check_state(root, expected):
    require(runtime_state(root) == expected, "Runtime source/assets differ from the captured build inputs")


def plugin_index(root):
    result = {}
    for path in Path(root).rglob("*.uplugin"):
        if any(x.lower() in EXCLUDED for x in path.parts):
            continue
        require(path.stem not in result, f"Ambiguous plugin descriptor: {path.stem}")
        result[path.stem] = path
    return result


def win_enabled(row):
    return (row.get("Enabled", True) and
            (not row.get("PlatformAllowList") or "Win64" in row["PlatformAllowList"]) and
            "Win64" not in row.get("PlatformDenyList", []))


def dependencies(root, engine):
    """Resolve plugin graph; never copy engine plugins or alter the working uproject."""
    original = load(root / UPROJECT)
    portable = copy.deepcopy(original)
    project_plugins = plugin_index(root / "Plugins")
    engine_plugins = plugin_index(engine / "Plugins")
    disabled = []
    for item in portable.get("Plugins", []):
        if item["Name"] in OPTIONAL_EDITOR and item.get("Enabled"):
            require(item.get("TargetAllowList") == ["Editor"], "Optional plugin gained a runtime target")
            descriptor = engine_plugins.get(item["Name"])
            require(descriptor is not None, f"Cannot verify optional plugin: {item['Name']}")
            require(all(m["Type"] in ("Editor", "EditorNoCommandlet") for m in load(descriptor).get("Modules", [])),
                    f"Optional plugin gained non-editor modules: {item['Name']}")
            item["Enabled"] = False
            disabled.append(item["Name"])
    pending = [r["Name"] for r in portable.get("Plugins", []) if win_enabled(r)]
    resolved = {}
    while pending:
        name = pending.pop()
        if name in resolved:
            continue
        require(name not in OPTIONAL_EDITOR, f"Required plugin depends on disabled editor tool: {name}")
        descriptor = project_plugins.get(name) or engine_plugins.get(name)
        require(descriptor is not None, f"Missing enabled plugin dependency: {name}")
        data = load(descriptor)
        is_project = name in project_plugins
        if is_project:
            for module in data.get("Modules", []):
                require((descriptor.parent / "Source" / module["Name"]).is_dir(),
                        f"Project plugin module source is missing: {name}/{module['Name']}")
        resolved[name] = {"location": "project" if is_project else "engine",
                          "descriptor": descriptor.relative_to(root if is_project else engine).as_posix(),
                          "sha256": digest(descriptor)}
        for dep in data.get("Plugins", []):
            if win_enabled(dep) and not dep.get("Optional", False):
                pending.append(dep["Name"])
    version = load(engine / "Build/Build.version")
    require(version.get("MajorVersion") == 5 and version.get("MinorVersion") == 8, "UE5.8 is required")
    return portable, {"engine_version": version, "plugins": resolved,
                      "archive_only_disabled_editor_plugins": sorted(disabled),
                      "engine_plugins_copied": False,
                      "recipient_requirement": "Verify extraction with this exact UE Build.version and resolved plugin descriptors; then open/build the extracted project."}


def relative_source(root, value):
    value = str(value).replace("\\", "/")
    # Source manifests were authored on Windows; retain the original archive-relative path.
    marker = "/Saved/"
    if marker in value:
        value = "Saved/" + value.split(marker, 1)[1]
    return safe_name(value)


def breath_inputs(root):
    data = load(root / BREATH_DIR / "breath-manifest.json")
    names = [BREATH_DIR + "/breath-manifest.json", BREATH_DIR + "/install.json", BREATH_AUDIT,
             BREATH_DIR + "/prepare_breaths.py", BREATH_DIR + "/offline-validation.json"]
    for row in data["recordings"].values():
        require(row["license_url"] == "https://creativecommons.org/publicdomain/zero/1.0/", "Unreviewed breath license")
        name = relative_source(root, row["source_path"])
        require(digest(root / name) == row["source_sha256"], f"Breath source changed: {name}")
        names.append(name)
    expected = {"BREATH_01", "BREATH_02", "BREATH_03", "BREATH_04A", "BREATH_04B", "BREATH_04C", "BREATH_05", "BREATH_06"}
    require({r["id"] for r in data["waves"]} == expected, "Incomplete eight-breath source packet")
    for row in data["waves"]:
        name = relative_source(root, row["file"])
        require(digest(root / name) == row["file_sha256"], f"Edited breath WAV changed: {name}")
        require((root / "Content/SaskartaGaea/Audio/Breaths" / (row["id"] + ".uasset")).is_file(), "Missing baked breath asset")
        names.append(name)
    completed = load(root / BREATH_DIR / "install.json")["completed"]
    require(expected | {"Traveller_loop_default"} <= set(completed), "Incomplete breath/loop install receipt")
    return names


def references(path):
    result = set()
    tail = b""
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            data = tail + chunk
            strings = [m.decode("ascii") for m in REF.findall(data)]
            strings += [m.decode("utf-16-le").rstrip("\0") for m in WIDE_REF.findall(data)]
            for value in strings:
                result.add(value.split(".", 1)[0].rstrip("/"))
            tail = data[-4096:]
    return result


def hard_imports(path):
    """Read versioned editor package imports, not historical import-source metadata.

    UE5.8 PackageFileSummary.cpp, ObjectResource.cpp:346, UnrealNames.cpp:4457.
    Unknown/unversioned formats reject rather than falling back to string guesses.
    """
    with path.open("rb") as stream:
        size = path.stat().st_size

        def take(n):
            require(0 <= n <= 64 * 1024 * 1024, "Unexpected package field size")
            value = stream.read(n)
            require(len(value) == n, f"Truncated package: {path}")
            return value

        def integer():
            return struct.unpack("<i", take(4))[0]

        def string():
            count = integer()
            require(abs(count) <= 65536, "Unexpected package string size")
            if not count:
                return ""
            value = take(abs(count) * (2 if count < 0 else 1))
            return value.decode("utf-16-le" if count < 0 else "utf-8").rstrip("\0")

        def seek(offset):
            require(0 <= offset <= size, "Invalid package table offset")
            stream.seek(offset)

        require(struct.unpack("<I", take(4))[0] == 0x9E2A83C1, f"Not an editor package: {path}")
        legacy = integer()
        require(legacy in (-9, -8, -7, -6), "Unsupported package legacy version")
        integer()  # legacy UE3
        ue4 = integer()
        ue5 = integer() if legacy <= -8 else 0
        licensee = integer()
        require(504 <= ue4 <= 522 and 0 <= ue5 <= 1018 and not licensee, "Unsupported/unversioned package")
        if ue5 >= 1016:  # PACKAGE_SAVED_HASH: FIoHash20 + TotalHeaderSize
            take(20); integer()
        custom_count = integer()
        require(0 <= custom_count <= 4096, "Unexpected custom-version table")
        take(custom_count * 20)
        if ue5 < 1016:
            integer()  # TotalHeaderSize
        string()  # package/folder name
        flags = struct.unpack("<I", take(4))[0]
        name_count, name_offset = integer(), integer()
        if ue5 >= 1008:
            integer(); integer()  # soft-object-path table, not hard imports
        if ue4 >= 516 and not (flags & 0x80000000):
            string()  # LocalizationId
        integer(); integer()  # gatherable text, present for supported >=504 packages
        integer(); integer()  # exports
        import_count, import_offset = integer(), integer()
        require(0 <= name_count <= 250000 and 0 <= import_count <= 250000, "Unexpected package table count")
        seek(name_offset)
        names = []
        for _ in range(name_count):
            names.append(string()); take(4)  # two uint16 name hashes, UE4 >=504

        def fname():
            index, number = integer(), integer()
            require(0 <= index < len(names) and 0 <= number < 2**30, "Invalid import FName")
            return names[index] + ("_" + str(number - 1) if number else "")

        seek(import_offset)
        packages = set()
        for _ in range(import_count):
            fname(); class_name = fname(); integer(); object_name = fname()
            package_name = fname() if ue4 >= 520 else "None"
            optional = integer() if ue5 >= 1003 else 0
            require(optional in (0, 1), "Invalid optional-import boolean")
            if not optional:
                if class_name == "Package" and object_name.startswith("/Game/"):
                    packages.add(object_name)
                if package_name.startswith("/Game/"):
                    packages.add(package_name)
        return packages


def baked_assets(root):
    """Bounded mandatory /Game hard-import closure; cook/soft/runtime acceptance is separate."""
    old = load(root / "SourceArt/Tripo/manifest.json")
    models = {"SM_T2_" + r["t2"] for r in old["models"] if r["verdict"] == "use"}
    require(len(models) == 24, "Legacy Tripo approved list changed; review archive coverage")
    models.update("SM_T2_" + name for name in S26)
    new_manifest = root / "SourceArt/Tripo/20261001/import_manifest.json"
    require(new_manifest.is_file(), "Missing new S26 source manifest")
    for row in load(new_manifest):
        for key, hash_key in (("source_file", "source_sha256"), ("runtime_file", "runtime_sha256")):
            name = safe_name(row[key])
            require(digest(root / name) == row[hash_key], f"New S26 source/hash mismatch: {name}")
    required = {"/Game/SaskartaGaea/Environment/Tripo02/" + n for n in models}
    required |= {"/Game/SaskartaGaea/Audio/Breaths/" + n for n in
                 ("BREATH_01", "BREATH_02", "BREATH_03", "BREATH_04A", "BREATH_04B", "BREATH_04C", "BREATH_05", "BREATH_06")}
    require("/Game/SaskartaGaea/Environment/Tripo02/SM_T2_s26_radio_station" in hard_imports(root / STATION),
            "Saved station actor does not reference the accepted new station mesh")
    summit = [r for r in load(root / WORLD_CANDIDATES)["candidates"] if r["region"] == "summit"]
    require(len(summit) == 53, "Unexpected saved summit actor inventory")
    saved_refs = set()
    for row in summit:
        saved_refs.update(hard_imports(root / safe_name(row["file"])))
    require({"/Game/SaskartaGaea/Environment/Tripo02/SM_T2_" + n for n in S26} <= saved_refs,
            "New S26 models are not all referenced by the exact saved summit actors")
    pending = list(required)
    checked = set()
    while pending:
        package = pending.pop()
        if package in checked:
            continue
        require(len(checked) < 4096, "Unexpected asset dependency scope; review before archive")
        relative = safe_name("Content/" + package[6:])
        candidates = [root / (relative + ext) for ext in (".uasset", ".umap")]
        path = next((p for p in candidates if p.is_file()), None)
        if path is None and (root / relative).is_dir():
            continue  # Serialized directory metadata, not an asset reference.
        require(path is not None, f"Missing baked /Game dependency: {package}")
        checked.add(package)
        pending.extend(hard_imports(path) - checked)
    return {"required_models": sorted(models), "saved_station_actor": STATION,
            "checked_game_packages": sorted(checked),
            "scope": "28 approved model seeds + eight breaths and mandatory /Game hard imports; soft/dynamic references still require UE cook/load/runtime validation"}


def snapshot(root, output):
    require(not Path(output).exists(), "Snapshot already exists")
    files = runtime_state(root)
    result = {"schema": 1, "kind": "prebuild_runtime_inputs", "project_root": str(root),
              "created_utc": datetime.now(timezone.utc).isoformat(), "files": files}
    write_new(output, result)


def package_state(package):
    require((package / "saskartarad.exe").is_file(), "Package must name the completed Windows directory")
    names = files_under(package, [p.name for p in package.iterdir() if p.name.lower() != "saved"])
    names = [p for p in names if "saved" not in [x.lower() for x in PurePosixPath(p).parts]]
    return fingerprint(package, names)


def bind(root, snapshot_file, build_log, package, output):
    snap = load(snapshot_file)
    require(snap.get("kind") == "prebuild_runtime_inputs", "Expected a pre-build snapshot")
    check_state(root, snap["files"])
    st = build_log.stat()
    started = getattr(st, "st_birthtime", st.st_ctime)
    require(datetime.fromisoformat(snap["created_utc"]).timestamp() <= started,
            "Snapshot must predate the fresh UAT log; cannot retroactively certify a build")
    log = build_log.read_text(encoding="utf-8-sig", errors="replace")
    require("BUILD SUCCESSFUL" in log and re.search(r"ExitCode\s*=\s*0", log), "UAT success is missing")
    require("-cook" in log and "-skipcook" not in log.lower(), "Require a fresh cook")
    require(str(root / UPROJECT).lower().replace("/", "\\") in log.lower().replace("/", "\\"), "UAT log is for a different project")
    destinations = re.findall(r'-archivedirectory=(?:"([^"]+)"|(\S+))', log, flags=re.I)
    require(package.name.lower() == "windows" and any(Path(a or b).resolve() == package.parent for a, b in destinations),
            "UAT archive destination does not match this Windows package")
    result = {"schema": 1, "kind": "successful_build_binding", "runtime_inputs": snap["files"],
              "snapshot_sha256": digest(snapshot_file), "snapshot_created_utc": snap["created_utc"],
              "build_log": str(build_log), "build_log_sha256": digest(build_log),
              "package_root": str(package), "package_files": package_state(package),
              "created_utc": datetime.now(timezone.utc).isoformat()}
    check_state(root, snap["files"])
    write_new(output, result)


def prepare(root, engine, binding_file, work):
    require(not work.exists(), "Archive work directory already exists; preserve prior attempt")
    binding = load(binding_file)
    require(binding.get("kind") == "successful_build_binding", "A successful build binding is required")
    check_state(root, binding["runtime_inputs"])
    for name in ("Content/level/Saskarta_WP.umap", "Content/SaskartaGaea/Audio/Station/DA_Station.uasset"):
        require((root / name).is_file(), f"Missing required baked runtime asset: {name}")
    package = Path(binding["package_root"])
    require(package_state(package) == binding["package_files"], "Accepted Windows package changed")
    require(digest(Path(binding["build_log"])) == binding["build_log_sha256"], "Accepted build log changed")
    portable, deps = dependencies(root, engine)
    baked = baked_assets(root)
    entries = ENTRIES + breath_inputs(root) + [WORLD_CANDIDATES]
    if (root / "Source").exists():
        entries.append("Source")
    names = files_under(root, entries)
    require(set(binding["runtime_inputs"]) <= set(names), "Archive omits captured runtime inputs")
    files = fingerprint(root, names)
    overlay = encoded(portable)
    files[UPROJECT] = {"bytes": len(overlay), "sha256": digest_bytes(overlay)}
    dep_bytes = encoded(deps)
    files[DEPENDENCIES] = {"bytes": len(dep_bytes), "sha256": digest_bytes(dep_bytes)}
    manifest = {"schema": 1, "kind": "portable_project_archive", "build_binding": binding,
                "build_binding_sha256": digest(binding_file), "source_uproject_sha256": digest(root / UPROJECT),
                "files": files, "dependencies": deps, "baked_assets": baked,
                "excluded_directory_names": sorted(EXCLUDED), "runtime_acceptance": "separate; not established by archive integrity"}
    check_state(root, binding["runtime_inputs"])
    work.mkdir(parents=True)
    (work / UPROJECT).write_bytes(overlay)
    (work / DEPENDENCIES).write_bytes(dep_bytes)
    (work / MANIFEST).write_bytes(encoded(manifest))
    (work / "files.nul").write_bytes(b"\0".join(n.encode("utf-8") for n in names if n != UPROJECT) + b"\0")
    return manifest


def verify_zip(archive, expected_manifest):
    expected = load(expected_manifest)
    with zipfile.ZipFile(archive) as z:
        for info in z.infolist():
            safe_name(info.filename.rstrip("/"))
        names = [safe_name(i.filename) for i in z.infolist() if not i.is_dir()]
        require(len(names) == len(set(n.casefold() for n in names)), "Duplicate/case-colliding ZIP entries")
        require(set(names) == set(expected["files"]) | {MANIFEST}, "ZIP file set differs from exact manifest")
        require(z.read(MANIFEST) == Path(expected_manifest).read_bytes(), "Embedded manifest differs")
        for info in z.infolist():
            require(not stat.S_ISLNK(info.external_attr >> 16), "ZIP contains a symlink")
        for name, row in expected["files"].items():
            h = hashlib.sha256()
            count = 0
            with z.open(name) as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    h.update(chunk)
                    count += len(chunk)
            require(count == row["bytes"] and h.hexdigest() == row["sha256"], f"ZIP member mismatch: {name}")
    return {"status": "all_zip_members_crc_and_sha256_verified", "files": len(names), "zip_sha256": digest(archive)}


def verify_extracted(root, engine, expected_manifest):
    expected = load(expected_manifest)
    require((root / MANIFEST).read_bytes() == Path(expected_manifest).read_bytes(), "Extracted manifest differs")
    names = files_under(root, [p.name for p in root.iterdir()])
    require(set(names) == set(expected["files"]) | {MANIFEST}, "Incomplete or changed extraction")
    require(fingerprint(root, sorted(expected["files"])) == expected["files"], "Extracted file hash mismatch")
    deps = expected["dependencies"]
    require(load(engine / "Build/Build.version") == deps["engine_version"], "Unverified recipient engine version")
    for name, row in deps["plugins"].items():
        base = root if row["location"] == "project" else engine
        require((base / row["descriptor"]).is_file() and digest(base / row["descriptor"]) == row["sha256"],
                f"Missing or changed recipient plugin: {name}")
    return {"status": "exact_extraction_and_engine_dependencies_verified", "files": len(names),
            "open_build_launch_acceptance": "still required"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=ROOT)
    commands = parser.add_subparsers(dest="command", required=True)
    s = commands.add_parser("snapshot"); s.add_argument("--output", type=Path, required=True)
    b = commands.add_parser("bind-build")
    for name in ("snapshot", "build-log", "package", "output"):
        b.add_argument("--" + name, type=Path, required=True)
    p = commands.add_parser("prepare")
    for name in ("engine", "binding", "work"):
        p.add_argument("--" + name, type=Path, required=True)
    z = commands.add_parser("verify-zip"); z.add_argument("--archive", type=Path, required=True); z.add_argument("--manifest", type=Path, required=True); z.add_argument("--check-current", action="store_true")
    e = commands.add_parser("verify-extracted"); e.add_argument("--engine", type=Path, required=True); e.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args(); root = args.project.resolve()
    if args.command == "snapshot":
        snapshot(root, args.output)
    elif args.command == "bind-build":
        bind(root, args.snapshot, args.build_log, args.package.resolve(), args.output)
    elif args.command == "prepare":
        result = prepare(root, args.engine.resolve(), args.binding, args.work)
        print(json.dumps({"status": "archive_inputs_prepared", "files": len(result["files"])}))
    elif args.command == "verify-zip":
        print(json.dumps(verify_zip(args.archive, args.manifest)))
        if args.check_current:
            check_state(root, load(args.manifest)["build_binding"]["runtime_inputs"])
    else:
        print(json.dumps(verify_extracted(root, args.engine.resolve(), args.manifest)))


if __name__ == "__main__":
    main()
