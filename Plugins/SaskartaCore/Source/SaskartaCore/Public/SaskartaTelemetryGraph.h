#pragma once

#include "CoreMinimal.h"
#include "Components/Widget.h"
#include "SaskartaTelemetryGraph.generated.h"

class SSaskartaTelemetryGraph;

/** A cheap instrument trace. Samples are normalized [0,1] in time/value; labels belong to the caller. */
UCLASS()
class SASKARTACORE_API USaskartaTelemetryGraph : public UWidget
{
    GENERATED_BODY()
public:
    void SetSamples(const TArray<FVector2D>& InSamples);
protected:
    virtual TSharedRef<SWidget> RebuildWidget() override;
    virtual void ReleaseSlateResources(bool bReleaseChildren) override;
private:
    TArray<FVector2D> Samples;
    TSharedPtr<SSaskartaTelemetryGraph> Graph;
};
