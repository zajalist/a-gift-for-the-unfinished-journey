// Storm shells gate (task STORM-SHELLS): keeps the moving-dust post-process pass in the frame only while
// there is a storm, and sets its quality tier.
//
// The look (docs/look/STORM_SHELLS.md, Shaders/StormShells.ush): one post-process material at Scene Color
// After DOF (MI_PP_Saskarta_StormShells) on its own unbound PPV (PPV_Saskarta_StormShells, tag
// Saskarta_StormShells). Per pixel it crosses the view ray with 4 virtual cylinders centred on the camera
// (30/55/90/150 m) and composites a world-anchored, wind-driven dust field sampled there. The material reads
// the camera position, time and MPC_Saskarta_Sky.StormIntensity itself. The subsystem feeds the current
// height-fog parameters so the dust follows the look key's colour and transmittance.
//
// This subsystem:
//   - finds the PPV once (tag, name or editor label), swaps the MI for a dynamic instance;
//   - reads StormIntensity from the MPC's world instance each tick (what the material sees; the lighting
//     director writes it per look key), falling back to the director's getter when the MPC is missing;
//   - sets the PPV's BlendWeight to 1 or 0 with hysteresis (on above 0.015, off at or below 0.005), and only
//     when it changes. A volume or blendable of weight 0 is never added to the view, so at storm 0 the pass
//     costs nothing. The weight is NOT an opacity: the material fades with StormIntensity itself;
//   - writes the MID's Tier (x shells drawn, y shells with the wisp octave) from the cvars, on change;
//   - writes Haze, HazeDir, FogA and FogB from the level height fog when its look changes.
//
// CVars (ECVF_Scalability, so DefaultScalability.ini can set them per EffectsQuality level):
//   saskarta.stormshells          1   0 removes the pass
//   saskarta.stormshells.layers   4   shells drawn, nearest first (3 drops the 150 m shell; 0 = off)
//   saskarta.stormshells.detail   2   shells with the wisp octave, nearest first
//
// Game worlds only (PIE and the packaged game); the editor viewport keeps the PPV as saved (weight 1).
#pragma once

#include "CoreMinimal.h"
#include "SaskartaStormShellsLogic.h"
#include "Subsystems/WorldSubsystem.h"
#include "SaskartaStormShells.generated.h"

class APostProcessVolume;
class UMaterialInstanceDynamic;
class UMaterialParameterCollection;

UCLASS()
class SASKARTACORE_API USaskartaStormShellsSubsystem : public UTickableWorldSubsystem
{
    GENERATED_BODY()

public:
    UFUNCTION(BlueprintPure, Category = "Saskarta|Look", meta = (WorldContext = "WorldContextObject"))
    static USaskartaStormShellsSubsystem* GetStormShells(const UObject* WorldContextObject);

    /** True while the shells' pass is in the frame (the PPV's weight is 1). */
    UFUNCTION(BlueprintPure, Category = "Saskarta|Look")
    bool IsPassOn() const { return bPassOn; }

    /** Hide the camera-centred shell pass in this world without changing global scalability or storm ambience. */
    UFUNCTION(BlueprintCallable, Category = "Saskarta|Look")
    void SetSuppressed(bool bInSuppressed);

    UFUNCTION(BlueprintPure, Category = "Saskarta|Look")
    bool IsSuppressed() const { return bSuppressed; }

    /** The StormIntensity the gate read last (MPC_Saskarta_Sky, what the material uses). */
    UFUNCTION(BlueprintPure, Category = "Saskarta|Look")
    float GetStormIntensity() const { return LastStorm; }

    /** True once the PPV and its material instance were found. */
    UFUNCTION(BlueprintPure, Category = "Saskarta|Look")
    bool IsBound() const { return Volume.IsValid() && Mid != nullptr; }

    // UWorldSubsystem / FTickableGameObject
    virtual bool ShouldCreateSubsystem(UObject* Outer) const override;
    virtual void OnWorldBeginPlay(UWorld& InWorld) override;
    virtual void Deinitialize() override;
    virtual void Tick(float DeltaTime) override;
    virtual bool IsTickable() const override;
    virtual TStatId GetStatId() const override;

private:
    bool Bind();
    float ReadStormIntensity() const;
    void Apply(float Weight, const FSaskartaStormShellTier& Tier);
    void UpdateFogParams();

    TWeakObjectPtr<APostProcessVolume> Volume;
    UPROPERTY(Transient)
    TObjectPtr<UMaterialInstanceDynamic> Mid;
    UPROPERTY(Transient)
    TObjectPtr<UMaterialParameterCollection> SkyMPC;

    bool bBegunPlay = false;
    bool bGateOn = false;
    bool bPassOn = false;
    bool bSuppressed = false;
    bool bWarnedUnbound = false;
    float LastStorm = 0.f;
    float AppliedWeight = -1.f;
    FSaskartaStormShellTier AppliedTier{-1, -1};
    FLinearColor AppliedHaze;
    FLinearColor AppliedHazeDir;
    FLinearColor AppliedFogA;
    FLinearColor AppliedFogB;
    bool bFogApplied = false;
    double NextBindTryS = 0.0;
};
