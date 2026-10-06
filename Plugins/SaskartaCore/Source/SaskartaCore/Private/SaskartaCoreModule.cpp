// SaskartaCore module: registers the two custom CVars that ComputeCVars()
// writes to (pcg.Saskarta.DensityScale, r.Saskarta.ReduceFlashing). See
// task-P2-brief.md's "Also:" note under Step 5.

#include "Modules/ModuleManager.h"
#include "HAL/IConsoleManager.h"

static TAutoConsoleVariable<float> CVarSaskartaPCGDensityScale(
    TEXT("pcg.Saskarta.DensityScale"),
    1.0f,
    TEXT("Saskarta: density scale applied to PCG foliage spawners. Driven by ")
    TEXT("USaskartaGameUserSettings::FoliageDensity via ApplySaskartaSettings()."),
    ECVF_Default);

static TAutoConsoleVariable<int32> CVarSaskartaReduceFlashing(
    TEXT("r.Saskarta.ReduceFlashing"),
    0,
    TEXT("Saskarta: 1 reduces flashing/strobing effects. Read by materials via ")
    TEXT("an MPC updated by USaskartaGameUserSettings::ApplySaskartaSettings()."),
    ECVF_Default);

class FSaskartaCoreModule : public IModuleInterface
{
public:
    virtual void StartupModule() override {}
    virtual void ShutdownModule() override {}
};

IMPLEMENT_MODULE(FSaskartaCoreModule, SaskartaCore)
