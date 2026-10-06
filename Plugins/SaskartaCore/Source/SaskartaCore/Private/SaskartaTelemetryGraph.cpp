#include "SaskartaTelemetryGraph.h"

#include "Rendering/DrawElements.h"
#include "Widgets/DeclarativeSyntaxSupport.h"
#include "Widgets/SLeafWidget.h"

class SSaskartaTelemetryGraph : public SLeafWidget
{
public:
    SLATE_BEGIN_ARGS(SSaskartaTelemetryGraph) {}
    SLATE_END_ARGS()
    void Construct(const FArguments&) {}
    void SetSamples(const TArray<FVector2D>& In)
    {
        Samples = In;
        Invalidate(EInvalidateWidgetReason::Paint);
    }
    virtual FVector2D ComputeDesiredSize(float) const override { return FVector2D(288.f, 76.f); }
    virtual int32 OnPaint(const FPaintArgs&, const FGeometry& Geometry, const FSlateRect&,
        FSlateWindowElementList& Elements, int32 Layer, const FWidgetStyle& Style, bool) const override
    {
        const FVector2D Size = Geometry.GetLocalSize();
        const float Alpha = Style.GetColorAndOpacityTint().A;
        for (int32 I = 0; I <= 4; ++I)
        {
            const float Fraction = I * 0.25f;
            TArray<FVector2D> Horizontal{FVector2D(0.f, Fraction * Size.Y), FVector2D(Size.X, Fraction * Size.Y)};
            TArray<FVector2D> Vertical{FVector2D(Fraction * Size.X, 0.f), FVector2D(Fraction * Size.X, Size.Y)};
            const FLinearColor Tint(1.f, 1.f, 1.f, Alpha * (I == 0 || I == 4 ? 0.35f : 0.12f));
            FSlateDrawElement::MakeLines(Elements, Layer, Geometry.ToPaintGeometry(), Horizontal,
                ESlateDrawEffect::None, Tint, false, 1.f);
            FSlateDrawElement::MakeLines(Elements, Layer, Geometry.ToPaintGeometry(), Vertical,
                ESlateDrawEffect::None, Tint, false, 1.f);
        }
        if (Samples.Num() >= 2)
        {
            TArray<FVector2D> Points;
            Points.Reserve(Samples.Num());
            for (const FVector2D& Sample : Samples)
                Points.Emplace(FMath::Clamp(Sample.X, 0.0, 1.0) * Size.X,
                    (1.0 - FMath::Clamp(Sample.Y, 0.0, 1.0)) * Size.Y);
            FSlateDrawElement::MakeLines(Elements, Layer + 1, Geometry.ToPaintGeometry(), Points,
                ESlateDrawEffect::None, FLinearColor(1.f, 1.f, 1.f, Alpha), true, 2.f);
        }
        return Layer + 1;
    }
private:
    TArray<FVector2D> Samples;
};

void USaskartaTelemetryGraph::SetSamples(const TArray<FVector2D>& InSamples)
{
    Samples.Reset(FMath::Min(InSamples.Num(), 120));
    for (int32 I = FMath::Max(0, InSamples.Num() - 120); I < InSamples.Num(); ++I)
        if (FMath::IsFinite(InSamples[I].X) && FMath::IsFinite(InSamples[I].Y)) Samples.Add(InSamples[I]);
    if (Graph.IsValid()) Graph->SetSamples(Samples);
}

TSharedRef<SWidget> USaskartaTelemetryGraph::RebuildWidget()
{
    Graph = SNew(SSaskartaTelemetryGraph);
    Graph->SetSamples(Samples);
    return Graph.ToSharedRef();
}

void USaskartaTelemetryGraph::ReleaseSlateResources(bool bReleaseChildren)
{
    Super::ReleaseSlateResources(bReleaseChildren);
    Graph.Reset();
}
