import ctypes, ctypes.wintypes as wt, re, sys

EXE = r"D:\UnrealEngine\saskartarad\Binaries\Win64\saskartarad.exe"
SYMPATH = r"D:\UnrealEngine\saskartarad\Binaries\Win64"
XML = sys.argv[1]

dbg = ctypes.WinDLL("dbghelp.dll")
k32 = ctypes.WinDLL("kernel32.dll")
h = k32.GetCurrentProcess()
dbg.SymSetOptions(0x2 | 0x10 | 0x40)  # UNDNAME | LOAD_LINES | LOAD_ANYTHING
dbg.SymInitializeW.argtypes = [wt.HANDLE, wt.LPCWSTR, wt.BOOL]
dbg.SymInitializeW(h, SYMPATH, False)
dbg.SymLoadModuleExW.restype = ctypes.c_uint64
dbg.SymLoadModuleExW.argtypes = [wt.HANDLE, wt.HANDLE, wt.LPCWSTR, wt.LPCWSTR, ctypes.c_uint64, wt.DWORD, ctypes.c_void_p, wt.DWORD]
BASE = 0x140000000
base = dbg.SymLoadModuleExW(h, None, EXE, None, BASE, 0, None, 0)
print("loaded base", hex(base), "err", k32.GetLastError())


class SYMBOL_INFOW(ctypes.Structure):
    _fields_ = [("SizeOfStruct", wt.ULONG), ("TypeIndex", wt.ULONG), ("Reserved", ctypes.c_uint64 * 2),
                ("Index", wt.ULONG), ("Size", wt.ULONG), ("ModBase", ctypes.c_uint64), ("Flags", wt.ULONG),
                ("Value", ctypes.c_uint64), ("Address", ctypes.c_uint64), ("Register", wt.ULONG),
                ("Scope", wt.ULONG), ("Tag", wt.ULONG), ("NameLen", wt.ULONG), ("MaxNameLen", wt.ULONG),
                ("Name", wt.WCHAR * 1024)]


class IMAGEHLP_LINEW64(ctypes.Structure):
    _fields_ = [("SizeOfStruct", wt.DWORD), ("Key", ctypes.c_void_p), ("LineNumber", wt.DWORD),
                ("FileName", wt.LPWSTR), ("Address", ctypes.c_uint64)]


dbg.SymFromAddrW.argtypes = [wt.HANDLE, ctypes.c_uint64, ctypes.POINTER(ctypes.c_uint64), ctypes.POINTER(SYMBOL_INFOW)]
dbg.SymGetLineFromAddrW64.argtypes = [wt.HANDLE, ctypes.c_uint64, ctypes.POINTER(wt.DWORD), ctypes.POINTER(IMAGEHLP_LINEW64)]

text = open(XML, encoding="utf-8", errors="replace").read()
block = text.split("<PCallStack>")[1].split("</PCallStack>")[0]
for m in re.finditer(r"saskartarad 0x[0-9a-fA-F]+ \+ ([0-9a-fA-F]+)", block):
    addr = base + int(m.group(1), 16)
    si = SYMBOL_INFOW(); si.SizeOfStruct = ctypes.sizeof(SYMBOL_INFOW) - 1024 * 2; si.MaxNameLen = 1024
    disp = ctypes.c_uint64(0)
    name = si.Name if dbg.SymFromAddrW(h, addr, ctypes.byref(disp), ctypes.byref(si)) else "?"
    ln = IMAGEHLP_LINEW64(); ln.SizeOfStruct = ctypes.sizeof(IMAGEHLP_LINEW64)
    d32 = wt.DWORD(0)
    where = ""
    if dbg.SymGetLineFromAddrW64(h, addr, ctypes.byref(d32), ctypes.byref(ln)):
        where = f"{ln.FileName.split(chr(92))[-1]}:{ln.LineNumber}"
    print(f"+{m.group(1):>8}  {name}  {where}")
