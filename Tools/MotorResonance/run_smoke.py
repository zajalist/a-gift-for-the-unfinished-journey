"""Compile and replay the real engine-free motor timing header; never starts Unreal."""
from pathlib import Path
import subprocess
import tempfile

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "saskartarad.uproject").is_file())
PUBLIC = ROOT / "Plugins/SaskartaCore/Source/SaskartaCore/Public"
SOURCE = Path(__file__).with_name("motor_resonance_smoke.cpp")
with tempfile.TemporaryDirectory(prefix="saskarta-resonance-") as scratch:
    here = Path(scratch)
    script = here / "run.cmd"
    script.write_text(f'''@echo off
call "C:\\Program Files\\Microsoft Visual Studio\\18\\Professional\\Common7\\Tools\\VsDevCmd.bat" -no_logo -arch=x64 -host_arch=x64
if errorlevel 1 exit /b 1
cl /nologo /EHsc /std:c++17 /W4 /I"{PUBLIC}" "{SOURCE}" /Fo:resonance.obj /Fe:resonance.exe
if errorlevel 1 exit /b 1
resonance.exe
''')
    result = subprocess.run(["cmd", "/c", str(script)], cwd=here, timeout=60)
raise SystemExit(result.returncode)
