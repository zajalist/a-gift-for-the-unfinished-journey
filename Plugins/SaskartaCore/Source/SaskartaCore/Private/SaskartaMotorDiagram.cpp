#include "SaskartaMotorResonance.h"
#include "SaskartaPower.h"

#include "Blueprint/WidgetTree.h"
#include "Components/Border.h"
#include "Components/CanvasPanel.h"
#include "Components/CanvasPanelSlot.h"
#include "Components/RetainerBox.h"
#include "Engine/AssetManager.h"
#include "Engine/Font.h"
#include "Engine/StreamableManager.h"
#include "Engine/Texture2D.h"
#include "Materials/MaterialInstanceDynamic.h"
#include "Rendering/DrawElements.h"
#include "Styling/CoreStyle.h"
#include "Styling/SlateBrush.h"
#include "Widgets/DeclarativeSyntaxSupport.h"
#include "Widgets/SLeafWidget.h"

namespace SaskartaMotorScreen
{
    constexpr float Width = 720.f;
    constexpr float Height = 384.f;
    using FLogic = FSaskartaMotorResonanceLogic;
    const TCHAR* const GlyphNames[] = {
        TEXT("Key_E"), TEXT("Key_A"), TEXT("Key_D"),
        TEXT("Pad_A"), TEXT("Pad_DPad_Left"), TEXT("Pad_DPad_Right")
    };

    FSoftObjectPath GlyphPath(const TCHAR* Name)
    {
        return FSoftObjectPath(FString::Printf(
            TEXT("/Game/SaskartaGaea/UI/Prompts/Light/T_Prompt_%s.T_Prompt_%s"), Name, Name));
    }
}

/** One inexpensive phosphor drawing, with no scene capture or per-part widgets.
 *  The crank, pistons and valve advance all use the same clock that judges input. */
class SSaskartaMotorDiagram : public SLeafWidget
{
public:
    SLATE_BEGIN_ARGS(SSaskartaMotorDiagram) {}
    SLATE_END_ARGS()
    void Construct(const FArguments&) {}
    void SetGlyphs(const TMap<FName, TObjectPtr<UTexture2D>>& Textures)
    {
        // Brushes live with the Slate leaf; the UWidget retains their textures for GC.
        GlyphBrushes.Reset();
        for (const auto& Pair : Textures)
        {
            if (!Pair.Value) continue;
            FSlateBrush& Brush = GlyphBrushes.Add(Pair.Key);
            Brush.SetResourceObject(Pair.Value.Get());
            Brush.DrawAs = ESlateBrushDrawType::Image;
            Brush.SetImageSize(FVector2f(static_cast<float>(Pair.Value->GetSizeX()), static_cast<float>(Pair.Value->GetSizeY())));
        }
        Invalidate(EInvalidateWidgetReason::Paint);
    }
    void SetFrame(UObject* InFont, const FSaskartaMotorResonanceLogic& InLogic, bool bInPad, float InCharge, float InGap, bool bInspectingBattery)
    {
        const bool bWasLoading = bLoading;
        bLoading = false;
        if (bWasLoading) Invalidate(EInvalidateWidgetReason::Layout);
        Font = InFont;
        Core = InLogic;
        bPad = bInPad;
        Charge = InCharge;
        Gap = InGap;
        bShowCharge = bInspectingBattery;
        Invalidate(EInvalidateWidgetReason::Paint);
    }
    void SetLoading(float InReadiness)
    {
        const float SafeReadiness = FMath::IsFinite(InReadiness) ? FMath::Clamp(InReadiness, 0.f, 1.f) : 0.f;
        if (bLoading && LoadingFraction == SafeReadiness) return;
        const bool bWasLoading = bLoading;
        bLoading = true;
        LoadingFraction = SafeReadiness;
        Invalidate(bWasLoading ? EInvalidateWidgetReason::Paint : EInvalidateWidgetReason::Layout);
    }
    virtual FVector2D ComputeDesiredSize(float) const override
    {
        return FVector2D(SaskartaMotorScreen::Width, bLoading ? 164.f : SaskartaMotorScreen::Height);
    }
    virtual int32 OnPaint(const FPaintArgs&, const FGeometry& G, const FSlateRect&,
        FSlateWindowElementList& Elements, int32 Layer, const FWidgetStyle& Style, bool) const override
    {
        using FLogic = FSaskartaMotorResonanceLogic;
        const float Alpha = Style.GetColorAndOpacityTint().A;
        const FSlateBrush* White = FCoreStyle::Get().GetBrush("WhiteBrush");
        const auto Color = [Alpha](float Bright) {
            return FLinearColor(Bright, Bright * 0.76f, Bright * 0.46f, Alpha);
        };
        const auto Line = [&](const TArray<FVector2D>& Points, float Bright = 0.55f, float Thickness = 1.5f)
        {
            FSlateDrawElement::MakeLines(Elements, Layer, G.ToPaintGeometry(), Points,
                ESlateDrawEffect::None, Color(Bright), true, Thickness);
        };
        const auto Box = [&](float X, float Y, float W, float H, float Bright)
        {
            FSlateDrawElement::MakeBox(Elements, Layer, G.ToPaintGeometry(FVector2f(W, H),
                FSlateLayoutTransform(FVector2f(X, Y))), White, ESlateDrawEffect::None, Color(Bright));
        };
        const auto Outline = [&](float X, float Y, float W, float H, float Bright = 0.5f)
        {
            Line({{X,Y},{X+W,Y},{X+W,Y+H},{X,Y+H},{X,Y}}, Bright);
        };
        const auto Text = [&](float X, float Y, const FString& Value, int32 Size = 24, float Bright = 0.85f)
        {
            if (!Font.IsValid()) return;
            // A small dark text edge keeps the transparent instrument legible
            // over the road without covering the landscape with a black panel.
            FSlateDrawElement::MakeText(Elements, Layer + 1,
                G.ToPaintGeometry(FVector2f(G.GetLocalSize()), FSlateLayoutTransform(FVector2f(X+1.5f,Y+1.5f))),
                Value, FSlateFontInfo(Font.Get(), Size), ESlateDrawEffect::None,
                FLinearColor(0.015f, 0.012f, 0.008f, Alpha * 0.9f));
            FSlateDrawElement::MakeText(Elements, Layer + 2,
                G.ToPaintGeometry(FVector2f(G.GetLocalSize()), FSlateLayoutTransform(FVector2f(X,Y))),
                Value, FSlateFontInfo(Font.Get(), Size), ESlateDrawEffect::None, Color(Bright));
        };
        const auto Glyph = [&](float CenterX, float CenterY, FName Name, const FString& Fallback, float Size, float Bright)
        {
            if (const FSlateBrush* Brush = GlyphBrushes.Find(Name))
            {
                const float Aspect = static_cast<float>(Brush->ImageSize.X / FMath::Max(1.0, static_cast<double>(Brush->ImageSize.Y)));
                const FVector2f Extent(Size * Aspect, Size);
                FSlateDrawElement::MakeBox(Elements, Layer + 1,
                    G.ToPaintGeometry(Extent, FSlateLayoutTransform(FVector2f(CenterX - Extent.X * 0.5f, CenterY - Size * 0.5f))),
                    Brush, ESlateDrawEffect::None, Color(Bright));
            }
            else Text(CenterX - Fallback.Len() * Size * 0.18f, CenterY - Size * 0.42f,
                Fallback, FMath::RoundToInt(Size * 0.7f), Bright);
        };
        const auto Arc = [&](FVector2D Center, float Radius, float Start, float End, float Bright, float Thickness = 1.5f)
        {
            TArray<FVector2D> Points;
            const int32 Count = FMath::Max(2, FMath::CeilToInt(FMath::Abs(End - Start) * 9.f));
            Points.Reserve(Count + 1);
            for (int32 I = 0; I <= Count; ++I)
            {
                const float Angle = FMath::Lerp(Start, End, static_cast<float>(I) / Count);
                Points.Add(Center + FVector2D(FMath::Cos(Angle), FMath::Sin(Angle)) * Radius);
            }
            Line(Points, Bright, Thickness);
        };

        // One connected mechanism in both presentations. The arm and grip rotate
        // with the wheel; the attached top index stays fixed for the accepted beat.
        const auto DrawCrank = [&](FVector2D Wheel, float WheelAngle, float HubBright)
        {
            Arc(Wheel, 67, 0, 2*PI, 0.3f, 2.f);
            Arc(Wheel, 61, 0, 2*PI, 0.56f, 2.f);
            for (int32 I = 0; I < 6; ++I)
            {
                const float Angle = WheelAngle + I * PI / 3.f;
                const FVector2D Direction(FMath::Cos(Angle), FMath::Sin(Angle));
                Line({Wheel+Direction*24.f,Wheel+Direction*61.f}, 0.45f, 2.f);
            }
            Arc(Wheel, 24, 0, 2*PI, HubBright, 2.f);

            const FVector2D Direction(FMath::Cos(WheelAngle), FMath::Sin(WheelAngle));
            const FVector2D Tangent(-Direction.Y, Direction.X);
            const FVector2D Pin = Wheel + Direction * 51.f;
            Line({Wheel+Direction*24.f,Pin}, 0.9f, 3.f);
            // A closed grip and its spindle make the handle read as a crank,
            // while leaving the center clear for the existing input glyph.
            Line({Pin-Tangent*8.f-Direction*4.f,Pin+Tangent*8.f-Direction*4.f}, 1.f, 2.f);
            Line({Pin-Tangent*8.f+Direction*4.f,Pin+Tangent*8.f+Direction*4.f}, 1.f, 2.f);
            Arc(Pin+Tangent*8.f, 4, WheelAngle, WheelAngle+PI, 1.f, 2.f);
            Arc(Pin-Tangent*8.f, 4, WheelAngle+PI, WheelAngle+2*PI, 1.f, 2.f);
            Arc(Pin, 2, 0, 2*PI, 1.f, 1.5f);
            Line({Wheel+FVector2D(0,-74),Wheel+FVector2D(0,-67)}, 1.f, 3.f);
        };
        if (bLoading)
        {
            // Readiness supplies exactly two turns and finishes at the top mark.
            // A stalled or regressing readiness stalls or reverses the mechanism.
            const FVector2D Wheel(92.f, 83.f);
            DrawCrank(Wheel, LoadingFraction * 2.f * 2.f * PI - PI * 0.5f, 0.6f);
            Arc(Wheel, 5, 0, 2*PI, 0.6f, 1.5f);
            if (LoadingFraction > 0.f)
                Arc(Wheel, 70, -PI*0.5f, -PI*0.5f + LoadingFraction*2.f*PI, 0.9f, 3.f);
            Box(184, 81.5f, 512, 3, 0.16f);
            Box(184, 81.5f, 512*LoadingFraction, 3, 0.9f);
            return Layer;
        }

        Text(24, 12, Core.IsTuning() ? TEXT("BIOFUEL / CHARGING") : TEXT("BIOFUEL / RESONANCE"), 24);
        Text(500, 14, Core.IsTuning() ? TEXT("SERVICE MODE") :
            (Core.bRecoveringCell ? TEXT("MOTOR STOPPED") : TEXT("AUTO DRIVE")), 21, 0.65f);
        Line({{24,46},{696,46}}, 0.35f);
        Line({{478,66},{478,264}}, 0.25f);

        const float Phase = static_cast<float>((Core.ElapsedS - Core.NextBeatS) / Core.PeriodS * 2.0 * PI);
        const bool bEngaged = Core.Feedback == FLogic::EFeedback::Good || Core.Feedback == FLogic::EFeedback::Perfect;
        const float Contact = bEngaged ? 1.f : 0.42f;
        const bool bBalancing = Core.BalanceVisible();
        const bool bBalanceNow = bBalancing && FMath::Abs(Core.NextBalanceS - Core.ElapsedS) <= FLogic::BalanceWindowS;

        // Paired cylinders, connecting rods and crankshaft. Their opposing
        // strokes explain the side-to-side valve correction visually.
        for (int32 I = 0; I < 2; ++I)
        {
            const float X = 55.f + I * 108.f;
            const float Angle = Phase + I * PI;
            const float PistonY = 139.f + FMath::Cos(Angle) * 15.f;
            const FVector2D Crank(X + 33.f, 230.f);
            const FVector2D Pin = Crank + FVector2D(FMath::Sin(Angle), FMath::Cos(Angle)) * 18.f;
            const bool bRequested = bBalancing && (Core.WantsLeft() == (I == 0));
            Glyph(X+33, 73, bPad ? (I == 0 ? TEXT("Pad_DPad_Left") : TEXT("Pad_DPad_Right"))
                : (I == 0 ? TEXT("Key_A") : TEXT("Key_D")),
                bPad ? (I == 0 ? TEXT("DP LEFT") : TEXT("DP RIGHT")) : (I == 0 ? TEXT("A") : TEXT("D")),
                32.f, bRequested ? 1.f : 0.38f);
            Outline(X+16, 92, 34, 12, bRequested ? 1.f : 0.4f);
            if (bRequested)
            {
                const float Lead = FMath::Clamp(1.f - static_cast<float>((Core.NextBalanceS - Core.ElapsedS) / 0.7), 0.f, 1.f);
                Box(X+18, 95, 30.f * Lead, 6, bBalanceNow ? 1.f : 0.65f);
                Line({{X+8,92},{X+2,98},{X+8,104}}, 0.9f, 2.f);
                Line({{X+58,92},{X+64,98},{X+58,104}}, 0.9f, 2.f);
            }
            Line({{X+33,104},{X+33,114}}, 0.7f);
            Outline(X, 114, 66, 74, 0.62f);
            for (int32 Fin = 0; Fin < 5; ++Fin)
                Line({{X-5,120.f+Fin*13},{X,120.f+Fin*13}}, 0.4f);
            Box(X+8, PistonY, 50, 12, Contact);
            Line({{X+8,PistonY-4},{X+58,PistonY-4}}, 0.9f, 2.f);
            Line({{X+33,PistonY+12},Pin}, 0.85f, 3.f);
            Arc(Crank, 22, 0, 2*PI, 0.45f);
            Arc(Pin, 3, 0, 2*PI, 1.f, 2.f);
            Arc(Crank, 3, 0, 2*PI, 0.8f, 2.f);
            Line({Crank,Pin}, 0.7f, 3.f);
        }
        Line({{66,254},{225,254}}, 0.4f);
        Line({{110,230},{175,230}}, 0.45f, 4.f);

        // One revolution per gameplay beat. The broad illuminated arc is the
        // actual accepted window, rather than an unrelated decorative pulse.
        const FVector2D Wheel(358,174);
        const float WheelAngle = Phase - PI * 0.5f;
        const float Window = static_cast<float>(FLogic::GoodWindowS / Core.PeriodS * 2.0 * PI);
        DrawCrank(Wheel, WheelAngle, Core.BeatWindowOpen() ? 1.f : 0.38f);
        Arc(Wheel, 70, -PI*.5f-Window, -PI*.5f+Window, Core.BeatWindowOpen() ? 1.f : 0.6f, 5.f);
        Text(312, 53, TEXT("CRANK"), 24, 0.8f);
        Glyph(358, 174, bPad ? TEXT("Pad_A") : TEXT("Key_E"), bPad ? TEXT("A") : TEXT("E"),
            32.f, Core.BeatWindowOpen() ? 1.f : 0.72f);
        Line({{213,213},{299,164}}, 0.4f, 2.f);
        Line({{213,247},{333,230}}, 0.4f, 2.f);
        Text(290, 248, Core.BeatWindowOpen() ? TEXT("ENGAGE NOW") : TEXT("WATCH THE MARK"), 22,
            Core.BeatWindowOpen() ? 1.f : 0.62f);

        // The gaze-driven battery HUD owns cell readings. This instrument only
        // shows the charge earned or the approaching dust, avoiding duplicates.
        Text(500, 66, Core.IsTuning() ? TEXT("CHARGE GAIN") : TEXT("DUST FRONT"), 21, 0.65f);
        Text(500, 98, Core.IsTuning() ? FString::Printf(TEXT("+%.0f%%"), Core.EarnedCharge)
            : FString::Printf(TEXT("%.0f M"), FMath::Max(0.f, Gap)), 42, 1.f);
        if (!Core.IsTuning())
        {
            const float Safety = FMath::Clamp(Gap / 65.f, 0.f, 1.f);
            Box(500, 159, 182, 5, 0.16f);
            Box(500, 159, 182*Safety, 5, 0.9f);
        }
        Text(500, 190, Core.IsTuning() ? TEXT("GENERATOR") : TEXT("DRIVE TORQUE"), 21, 0.65f);
        Text(500, 224, Core.IsTuning() ? FString::Printf(TEXT("%02d / %02d"),
            FMath::Min(Core.CompletedBeats+1, FLogic::LessonBeats), FLogic::LessonBeats)
            : FString::Printf(TEXT("%.0f%%"), Core.Drive*100.f), 32, 0.9f);

        Line({{24,309},{696,309}}, 0.35f);
        FString Instruction = bPad ? TEXT("A / CROSS  CRANK AT THE TOP MARK") : TEXT("E  CRANK AT THE TOP MARK");
        if (bBalancing)
            Instruction = FString(bPad ? (Core.WantsLeft() ? TEXT("D-PAD LEFT") : TEXT("D-PAD RIGHT"))
                : (Core.WantsLeft() ? TEXT("A") : TEXT("D"))) + (bBalanceNow ? TEXT("  OPEN VALVE NOW") : TEXT("  GET READY TO BALANCE"));
        else if (Core.Feedback == FLogic::EFeedback::Perfect || Core.Feedback == FLogic::EFeedback::Good)
            Instruction = Core.IsTuning() ? TEXT("IN RESONANCE / CELL TAKING CHARGE") : TEXT("IN RESONANCE / ACCELERATING");
        else if (Core.Feedback == FLogic::EFeedback::Balanced) Instruction = TEXT("VALVES BALANCED / KEEP CRANKING");
        else if (Core.Feedback == FLogic::EFeedback::Early) Instruction = TEXT("TOO EARLY / LET THE CRANK REACH THE MARK");
        else if (Core.Feedback == FLogic::EFeedback::Late || Core.Feedback == FLogic::EFeedback::Miss)
            Instruction = TEXT("MOMENTUM LOST / CATCH THE NEXT TURN");
        else if (Core.Feedback == FLogic::EFeedback::WrongSide) Instruction = TEXT("VALVE CLOSED / WATCH THE NEXT SIDE");
        Text(24, 318, Instruction, 24, 0.95f);
        Text(24, 353, Core.IsTuning() ? (bPad ? TEXT("VIEW  CLOSE / PASSIVE CHARGE CONTINUES") : TEXT("TAB  CLOSE / PASSIVE CHARGE CONTINUES"))
            : (Core.bRecoveringCell ? TEXT("CRANK TO RECHARGE / DUST IS STILL CLOSING") :
                TEXT("CRANK ON THE BEAT / BALANCE THE LIT VALVE")), 20, 0.65f);
        return Layer + 2;
    }
private:
    TWeakObjectPtr<UObject> Font;
    TMap<FName, FSlateBrush> GlyphBrushes;
    FSaskartaMotorResonanceLogic Core;
    bool bLoading = false;
    float LoadingFraction = 0.f;
    float Charge = 0.f;
    float Gap = 0.f;
    bool bPad = false;
    bool bShowCharge = false;
};

void USaskartaMotorDiagram::Configure(UObject* Font)
{
    FontObject = Font;
    LoadGlyphs();
}

void USaskartaMotorDiagram::LoadGlyphs()
{
    if (bGlyphLoadRequested) return;
    bGlyphLoadRequested = true;
    if (!UAssetManager::IsInitialized()) return;
    TArray<FSoftObjectPath> Paths;
    for (const TCHAR* Name : SaskartaMotorScreen::GlyphNames)
        Paths.Add(SaskartaMotorScreen::GlyphPath(Name));
    GlyphLoad = UAssetManager::GetStreamableManager().RequestAsyncLoad(Paths,
        FStreamableDelegate::CreateWeakLambda(this, [this]()
        {
            for (const TCHAR* Name : SaskartaMotorScreen::GlyphNames)
                if (UTexture2D* Texture = Cast<UTexture2D>(SaskartaMotorScreen::GlyphPath(Name).ResolveObject()))
                    GlyphTextures.Add(FName(Name), Texture);
            if (Diagram) Diagram->SetGlyphs(GlyphTextures);
        }));
}

void USaskartaMotorDiagram::BeginDestroy()
{
    if (GlyphLoad.IsValid()) GlyphLoad->CancelHandle();
    GlyphLoad.Reset();
    // A retained Slate reference must not keep a brush pointing at a collected texture.
    if (Diagram) Diagram->SetGlyphs({});
    Super::BeginDestroy();
}

void USaskartaMotorDiagram::Present(const FSaskartaMotorResonanceLogic& Logic, bool bGamepad, float Charge, float GapM, bool bInspectingBattery)
{
    bLoadingPresentation = false;
    Frame = Logic;
    bPad = bGamepad;
    ChargePercent = Charge;
    DustGapM = GapM;
    bShowCharge = bInspectingBattery;
    if (Diagram) Diagram->SetFrame(FontObject, Frame, bPad, ChargePercent, DustGapM, bShowCharge);
}

void USaskartaMotorDiagram::PresentLoading(float Readiness)
{
    bLoadingPresentation = true;
    LoadingReadiness = FMath::IsFinite(Readiness) ? FMath::Clamp(Readiness, 0.f, 1.f) : 0.f;
    if (Diagram) Diagram->SetLoading(LoadingReadiness);
}

TSharedRef<SWidget> USaskartaMotorDiagram::RebuildWidget()
{
    SAssignNew(Diagram, SSaskartaMotorDiagram);
    Diagram->SetGlyphs(GlyphTextures);
    if (bLoadingPresentation) Diagram->SetLoading(LoadingReadiness);
    else Diagram->SetFrame(FontObject, Frame, bPad, ChargePercent, DustGapM, bShowCharge);
    return Diagram.ToSharedRef();
}

void USaskartaMotorDiagram::ReleaseSlateResources(bool bReleaseChildren)
{
    Super::ReleaseSlateResources(bReleaseChildren);
    Diagram.Reset();
}

USaskartaMotorRetainer::USaskartaMotorRetainer(const FObjectInitializer& ObjectInitializer)
    : Super(ObjectInitializer)
{
    InitRenderOnPhase(false);
    InitRenderOnInvalidation(false);
}

void USaskartaMotorResonanceWidget::NativeOnInitialized()
{
    Super::NativeOnInitialized();
    SetIsFocusable(false);
    SetVisibility(ESlateVisibility::Collapsed);
    if (!WidgetTree) return;
    if (WidgetTree->RootWidget)
    {
        Diagram = Cast<USaskartaMotorDiagram>(GetWidgetFromName(TEXT("MotorMechanism")));
        Retainer = Cast<URetainerBox>(GetWidgetFromName(TEXT("MotorPhosphor")));
        if (!Diagram || !Retainer)
        {
            UE_LOG(LogTemp, Error, TEXT("%s: authored motor UMG layout requires MotorMechanism and MotorPhosphor. Install Tools/UIRuntime layouts."), *GetClass()->GetPathName());
            return;
        }
        Retainer->SetRetainRendering(false);
        Diagram->Configure(LoadObject<UFont>(nullptr, TEXT("/Game/SaskartaGaea/GameFlow/UI/Fonts/Font_Terminal.Font_Terminal")));
        return;
    }
    UCanvasPanel* Root = WidgetTree->ConstructWidget<UCanvasPanel>(UCanvasPanel::StaticClass(), TEXT("MotorRoot"));
    WidgetTree->RootWidget = Root;
    UCanvasPanel* Screen = WidgetTree->ConstructWidget<UCanvasPanel>(UCanvasPanel::StaticClass(), TEXT("MotorScreen"));
    UCanvasPanelSlot* ScreenSlot = Root->AddChildToCanvas(Screen);
    ScreenSlot->SetAnchors(FAnchors(0.f, 1.f));
    ScreenSlot->SetAlignment(FVector2D(0.f, 1.f));
    ScreenSlot->SetPosition(FVector2D(28.f, -156.f));
    ScreenSlot->SetSize(FVector2D(SaskartaMotorScreen::Width, SaskartaMotorScreen::Height));
    Screen->SetRenderTransformPivot(FVector2D(0.f, 1.f));
    Screen->SetRenderScale(FVector2D(0.82f, 0.82f));

    // Transparent instruments leave the pursuit and landscape visible. Captions
    // keep their own clear space below; there is no opaque instrument panel.
    UBorder* Glass = WidgetTree->ConstructWidget<UBorder>(UBorder::StaticClass(), TEXT("MotorGlass"));
    Glass->SetBrushColor(FLinearColor(0.009f, 0.007f, 0.004f, 0.f));
    UCanvasPanelSlot* GlassSlot = Screen->AddChildToCanvas(Glass);
    GlassSlot->SetSize(FVector2D(SaskartaMotorScreen::Width, SaskartaMotorScreen::Height));
    Retainer = WidgetTree->ConstructWidget<USaskartaMotorRetainer>(USaskartaMotorRetainer::StaticClass(), TEXT("MotorPhosphor"));
    // Direct Slate preserves alpha and the text edge. The former additive CRT
    // retainer discarded dark edges and required a large opaque backdrop.
    Retainer->SetRetainRendering(false);
    UCanvasPanelSlot* PhosphorSlot = Screen->AddChildToCanvas(Retainer);
    PhosphorSlot->SetSize(FVector2D(SaskartaMotorScreen::Width, SaskartaMotorScreen::Height));
    Diagram = WidgetTree->ConstructWidget<USaskartaMotorDiagram>(USaskartaMotorDiagram::StaticClass(), TEXT("MotorMechanism"));
    Diagram->Configure(LoadObject<UFont>(nullptr, TEXT("/Game/SaskartaGaea/GameFlow/UI/Fonts/Font_Terminal.Font_Terminal")));
    Retainer->AddChild(Diagram);
    SetVisibility(ESlateVisibility::Collapsed);
}

void USaskartaMotorResonanceWidget::Present(const FSaskartaMotorResonanceLogic& Logic, bool bShow,
    bool bGamepad, float Charge, float GapM, bool bInspectingBattery)
{
    const bool bWasShown = GetVisibility() != ESlateVisibility::Collapsed;
    SetVisibility(bShow ? ESlateVisibility::HitTestInvisible : ESlateVisibility::Collapsed);
    if (!bShow || !Diagram) return;
    // Refresh at 30 Hz, plus immediate scored input. No per-frame text widgets,
    // property bindings or timers; suppressed gameplay leaves the clock frozen.
    if (bWasShown && LastPaintS >= 0.0 && Logic.ElapsedS >= LastPaintS &&
        Logic.ElapsedS - LastPaintS < 1.0 / 30.0 && LastFeedback == Logic.Feedback && bLastInspectingBattery == bInspectingBattery) return;
    LastPaintS = Logic.ElapsedS;
    LastFeedback = Logic.Feedback;
    bLastInspectingBattery = bInspectingBattery;
    Diagram->Present(Logic, bGamepad, Charge, GapM, bInspectingBattery);
    if (Retainer) Retainer->RequestRender();
}
