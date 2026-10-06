"""Block Blueprint saves while a second Unreal process may own loaded files.

Windows' exclusive-open test cannot be used here: the editor itself holds its
loaded .uassets open. The 2026-09-28 Settings crash occurred when a separate
UnrealEditor.exe -game process had those assets open. A second editor for the
same project is unsafe for the same reason. This conservative process check
is run before any mutations are sent to Hayba.
"""

import json
import pathlib
import subprocess
import sys


def project_processes(project):
    query = (
        'Get-CimInstance Win32_Process -Filter '
        '"Name = \'UnrealEditor.exe\' OR Name = \'UnrealEditor-Cmd.exe\'" | '
        'Select-Object Name,ProcessId,CommandLine | ConvertTo-Json -Compress'
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", query],
        capture_output=True, text=True, check=True,
    )
    data = json.loads(result.stdout) if result.stdout.strip() else []
    if isinstance(data, dict):
        data = [data]
    project_path = str(pathlib.Path(project).resolve()).replace("\\", "/").lower()
    return [p for p in data if project_path in str(p.get("CommandLine", "")).replace("\\", "/").lower()]


def blocked_processes(processes):
    if len(processes) > 1:
        return processes
    return [p for p in processes if p.get("Name") == "UnrealEditor-Cmd.exe"
            or "-game" in str(p.get("CommandLine", "")).lower().split()]


def main(project, paths):
    processes = blocked_processes(project_processes(project))
    reason = ", ".join(f"{p['Name']} PID {p['ProcessId']}" for p in processes)
    print(json.dumps([{"file": path, "reason": reason} for path in paths] if processes else []))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2:])
