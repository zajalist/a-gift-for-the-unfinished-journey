"""Compile actual PIE teardown methods against minimal world/CVar plumbing.

Run with Python on a Windows development machine with Visual Studio 2026.
This checks cleanup ordering without starting Unreal. It does not replace the
engine build or a live stop-during-loading check. Production methods are
extracted verbatim so removing their loading-before-PIE call makes this fail.
"""
from pathlib import Path
import subprocess
import tempfile

ROOT = next(p for p in Path(__file__).resolve().parents if (p / 'saskartarad.uproject').is_file())
SCRATCH = tempfile.TemporaryDirectory(prefix='saskarta-pie-teardown-')
HERE = Path(SCRATCH.name)
PUB = ROOT / 'Plugins/SaskartaCore/Source/SaskartaCore/Public'
PRIV = ROOT / 'Plugins/SaskartaCore/Source/SaskartaCore/Private'

def block(text, signature):
    start = text.index(signature)
    opening = text.index('{', start)
    depth = 1
    end = opening + 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[start:end]

header = (PUB / 'SaskartaPerfGovernor.h').read_text()
source = (PRIV / 'SaskartaPerfGovernor.cpp').read_text()
policy = block(header, 'struct SASKARTACORE_API FSaskartaTransientPIEFpsCap') + ';'
methods = '\n'.join(block(source, sig) for sig in [
    'void RegisterWorld(UWorld* World)',
    'void UnregisterWorld(const UWorld* World)',
    'void RestoreFpsCap()',
])
teardown = block(source, 'void USaskartaPerfGovernor::RestoreTransientPIEFpsCap()')
cpp = r'''
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <set>
#define SASKARTACORE_API
#define TEXT(s) s
#define UE_LOG(...)
using int32 = int;
using uint32 = unsigned int;
using EConsoleVariableFlags = uint32;
constexpr uint32 ECVF_SetByMask = 255, ECVF_SetByScalability = 1;
struct FMath { static bool IsFinite(float f) {return std::isfinite(f);} template<class T> static T Max(T a,T b) {return a>b?a:b;} };
struct IConsoleVariable {float Value=120; float GetFloat() const {return Value;} uint32 GetFlags()const{return 1;} void Set(float v,uint32) {Value=v;} };
struct IConsoleManager {IConsoleVariable Fps; static IConsoleManager& Get(){static IConsoleManager M;return M;} IConsoleVariable* FindConsoleVariable(const char*){return &Fps;} };
enum class EWorldType { PIE };
struct UWorld { EWorldType WorldType=EWorldType::PIE; };
template<class T> struct TSet { std::set<T> Data; bool Contains(T v)const{return Data.count(v)>0;} void Add(T v){Data.insert(v);} int Remove(T v){return (int)Data.erase(v);} int Num()const{return (int)Data.size();} };
struct FWeakWorld {UWorld* P=nullptr; UWorld* Get()const{return P;} void Reset(){P=nullptr;} };
struct USaskartaLoadingBudget {
    bool Active=false; float Saved=0;
    void Begin(){Saved=IConsoleManager::Get().Fps.Value; if(Saved<=0 || Saved>30)IConsoleManager::Get().Fps.Value=30;Active=true;}
    void RestoreForWorldTeardown(){if(Active){if(IConsoleManager::Get().Fps.Value==30)IConsoleManager::Get().Fps.Value=Saved;Active=false;}}
};
struct UGameInstance {USaskartaLoadingBudget* Budget=nullptr;template<class T>T* GetSubsystem(){return Budget;} };
'''
cpp += policy
cpp += r'''
namespace SaskartaPerfGovernorLocal {
constexpr float TransientPIEFpsCap=60;
uint32 CVarWritePriority(const IConsoleVariable&) {return 1;}
struct FSharedPIEFpsCap {
    TSet<const UWorld*> ActiveWorlds;
    FSaskartaTransientPIEFpsCap Policy;
    uint32 SavedPriority=1;
    void ApplyQualityCeiling(){}
    void RestoreQualityCeiling(){}
'''
cpp += methods + r'''
};
FSharedPIEFpsCap& SharedPIEFpsCap(){static FSharedPIEFpsCap Cap;return Cap;}
}
struct USaskartaPerfGovernor {
    FWeakWorld RegisteredPIEWorld;
    UGameInstance* Instance=nullptr;
    UGameInstance* GetGameInstance(){return Instance;}
    void RestoreTransientPIEFpsCap();
};
'''
cpp += teardown
cpp += r'''
int main(){
 int Failures=0, Cases=0;
 for(float Original: {0.f,24.f,120.f}) for(bool LoadingFirst:{false,true}) for(float External:{-1.f,24.f,90.f}) {
   using namespace SaskartaPerfGovernorLocal;
   SharedPIEFpsCap()=FSharedPIEFpsCap();
   IConsoleManager::Get().Fps.Value=Original;
   UWorld World;USaskartaLoadingBudget Budget;UGameInstance GI;GI.Budget=&Budget;
   USaskartaPerfGovernor Governor;Governor.Instance=&GI;Governor.RegisteredPIEWorld.P=&World;
   SharedPIEFpsCap().RegisterWorld(&World);
   Budget.Begin();
   if(External>0)IConsoleManager::Get().Fps.Value=External;
   if(LoadingFirst)Budget.RestoreForWorldTeardown();
   Governor.RestoreTransientPIEFpsCap();
   Budget.RestoreForWorldTeardown();
   Governor.RestoreTransientPIEFpsCap();
   const float Expected=External>0?External:Original;
   ++Cases;
   if(IConsoleManager::Get().Fps.Value!=Expected || Budget.Active || SharedPIEFpsCap().ActiveWorlds.Num()!=0){
     ++Failures; std::printf("FAIL original=%.0f loadingFirst=%d external=%.0f expected=%.0f actual=%.0f\n",Original,LoadingFirst,External,Expected,IConsoleManager::Get().Fps.Value);
   }
 }
 std::printf("PIE/loading teardown: %d cases, %d failures\n",Cases,Failures);
 return Failures?1:0;
}
'''
(HERE / 'teardown_smoke.cpp').write_text(cpp)
cmd = r'''@echo off
call "C:\Program Files\Microsoft Visual Studio\18\Professional\Common7\Tools\VsDevCmd.bat" -no_logo -arch=x64 -host_arch=x64
if errorlevel 1 exit /b 1
cl /nologo /EHsc /std:c++17 /W4 teardown_smoke.cpp /Fo:teardown_smoke.obj /Fe:teardown_smoke.exe
if errorlevel 1 exit /b 1
teardown_smoke.exe
'''
(HERE / 'run.cmd').write_text(cmd)
try:
    result = subprocess.run(['cmd','/c',str(HERE / 'run.cmd')],cwd=HERE)
finally:
    SCRATCH.cleanup()
raise SystemExit(result.returncode)
