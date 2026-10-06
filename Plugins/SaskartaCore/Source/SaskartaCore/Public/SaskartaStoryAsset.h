// DA_Saskarta_Story: the story data the event runner executes (EVENTS.md section 6).
//
// Packaging: docs/ is not staged, so the data lives in a DataAsset under /Game, which
// cooks like any other asset. It is filled in the editor lane by
//   unreal.SaskartaStoryImport.import_story_from_files(asset, project_dir)
// (C++ parsing, so no Python struct plumbing), then saved. In editor builds only, when the
// asset is missing, the runner imports a transient copy straight from docs/story/ so PIE
// works before the asset exists (see USaskartaStoryImport::LoadStoryOrImportTransient).

#pragma once

#include "CoreMinimal.h"
#include "Engine/DataAsset.h"
#include "SaskartaEventTypes.h"
#include "SaskartaCollapseStageLogic.h"
#include "SaskartaStoryAsset.generated.h"

UCLASS(BlueprintType)
class SASKARTACORE_API USaskartaStoryAsset : public UPrimaryDataAsset
{
    GENERATED_BODY()

public:
    /** beats[] + optional_beats[] (bOptional) + system_beats[] (bSystem). */
    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Saskarta|Story")
    TArray<FSaskartaBeatDef> Beats;

    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Saskarta|Story")
    TArray<FSaskartaLineDef> Lines;

    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Saskarta|Story")
    TArray<FSaskartaCinematicDef> Cinematics;

    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Saskarta|Story")
    TArray<FSaskartaGlanceDef> Glances;

    /** (road m, UE m) pairs from road-profile.json samples, sorted by road m. */
    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Saskarta|Story")
    TArray<FVector2f> RoadMToUeM;

    /** Optional content feature tags: PromiseCine, MarkCine, Exchange, AuxSensors, Drone, S7. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Story")
    TArray<FName> EnabledTags;

    /** Silence after each story line before Voice is free again (the old pre-mix gap). */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Story")
    float GapS = 0.8f;

    /**
     * When true the runner forwards road m to USaskartaLightingDirector::SetRoadProgress.
     * Leave false while the tether already calls it (EVENTS.md section 2).
     */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Story")
    bool bDriveLightingRoadProgress = false;

    /** story-events.json "collapse_stage": where the carrier stands for B18 / CIN_18 (USaskartaCollapseStageSubsystem). */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Story")
    FSaskartaCollapseStageDef CollapseStage;

    const FSaskartaBeatDef* FindBeat(FName Id) const;
    const FSaskartaLineDef* FindLine(FName Id) const;
    const FSaskartaCinematicDef* FindCinematic(FName Id) const;
    const FSaskartaGlanceDef* FindGlance(FName Id) const;
};
