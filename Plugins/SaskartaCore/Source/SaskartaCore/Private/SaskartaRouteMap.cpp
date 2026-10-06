#include "SaskartaRouteMap.h"

#include "Blueprint/WidgetTree.h"
#include "Camera/CameraComponent.h"
#include "Components/CanvasPanel.h"
#include "Components/CanvasPanelSlot.h"
#include "Components/InputComponent.h"
#include "Components/RetainerBox.h"
#include "Components/SplineComponent.h"
#include "Components/WidgetComponent.h"
#include "Engine/Engine.h"
#include "Engine/Font.h"
#include "Engine/World.h"
#include "EngineUtils.h"
#include "Fonts/SlateFontInfo.h"
#include "GameFramework/Pawn.h"
#include "GameFramework/PlayerController.h"
#include "HAL/IConsoleManager.h"
#include "InputCoreTypes.h"
#include "Materials/MaterialInterface.h"
#include "Rendering/DrawElements.h"
#include "SaskartaEventLogic.h"
#include "SaskartaEventRunner.h"
#include "SaskartaHudQueryLogic.h"
#include "SaskartaOnboarding.h"
#include "SaskartaSaveGame.h"
#include "SaskartaSteleScanLogic.h"
#include "SaskartaStoryAsset.h"
#include "TimerManager.h"
#include "Widgets/DeclarativeSyntaxSupport.h"
#include "Widgets/SLeafWidget.h"

DEFINE_LOG_CATEGORY_STATIC(LogSaskartaRouteMap, Log, All);

namespace SaskartaRouteMap
{
    static const FName Playing(TEXT("Playing"));
    static const FName Carrier(TEXT("Carrier"));
    static const FName MastTag(TEXT("Saskarta.Mast"));
    static const FName MastId(TEXT("MAST"));
    static constexpr TCHAR FontPath[] = TEXT("/Game/SaskartaGaea/GameFlow/UI/Fonts/Font_Terminal.Font_Terminal");
    static constexpr TCHAR CrtPath[] = TEXT("/Game/SaskartaGaea/GameFlow/Materials/MI_UI_RadioCRT.MI_UI_RadioCRT");
    /** road-profile.json summit (the mast stands on it) when no actor is tagged Saskarta.Mast. */
    static const FVector2D MastFallbackCm(288080.0, 443650.0);
    static constexpr float RoadStepM = 20.f;
    static constexpr float FrameIntervalS = 0.1f;
    static constexpr float NodesIntervalS = 1.f;
    /** Several queries on one beat are spread along the road so their marks do not sit on each other. */
    static constexpr float SameBeatSpreadM = 12.f;

    static TAutoConsoleVariable<int32> CVarEnable(TEXT("saskarta.RouteMap.Enable"), 1,
        TEXT("1: M / View opens the CRT route map. 0: the keys do nothing."));

    static FString TerminalSafe(const FString& In)
    {
        FString Out = FSaskartaSteleScanCore::HudSafe(In, TEXT("OK"));
        Out.ReplaceInline(TEXT("—"), TEXT("-"));
        Out.ReplaceInline(TEXT("–"), TEXT("-"));
        return Out;
    }
}

// ============================================================================================ the plot
class SSaskartaRouteMapPlot : public SLeafWidget
{
public:
    SLATE_BEGIN_ARGS(SSaskartaRouteMapPlot) {}
    SLATE_END_ARGS()

    void Construct(const FArguments&) {}

    void SetFrame(const FSaskartaRouteFrame& In)
    {
        Current = In;
        Invalidate(EInvalidateWidgetReason::Paint);
    }

    void Configure(UObject* InFont, const FVector2D& InSize)
    {
        FontRef = InFont;
        PlotSize = InSize;
        Invalidate(EInvalidateWidgetReason::Layout);
    }

    virtual FVector2D ComputeDesiredSize(float) const override { return PlotSize; }

    virtual int32 OnPaint(const FPaintArgs& Args, const FGeometry& Geometry, const FSlateRect& CullingRect,
        FSlateWindowElementList& OutDrawElements, int32 LayerId, const FWidgetStyle& InWidgetStyle, bool bParentEnabled) const override
    {
        // White like the power line: MI_UI_RadioCRT turns luminance into the amber phosphor.
        const float Tint = InWidgetStyle.GetColorAndOpacityTint().A;
        for (const FSaskartaRoutePolyline& L : Current.Lines)
        {
            if (L.Points.Num() >= 2)
            {
                FSlateDrawElement::MakeLines(OutDrawElements, LayerId, Geometry.ToPaintGeometry(), L.Points,
                    ESlateDrawEffect::None, FLinearColor(1.f, 1.f, 1.f, L.Alpha * Tint), true, L.Thickness);
            }
        }
        if (UObject* F = FontRef.Get())
        {
            const FVector2f Local(Geometry.GetLocalSize());
            for (const FSaskartaRouteText& T : Current.Texts)
            {
                FSlateDrawElement::MakeText(OutDrawElements, LayerId + 1,
                    Geometry.ToPaintGeometry(Local, FSlateLayoutTransform(T.Pos)), T.Text, FSlateFontInfo(F, T.Size),
                    ESlateDrawEffect::None, FLinearColor(1.f, 1.f, 1.f, T.Alpha * Tint));
            }
        }
        return LayerId + 1;
    }

private:
    FSaskartaRouteFrame Current;
    TWeakObjectPtr<UObject> FontRef;
    FVector2D PlotSize = FVector2D(640.f, 440.f);
};

void USaskartaRouteMapPlot::SetFrame(const FSaskartaRouteFrame& Frame)
{
    Pending = Frame;
    if (Plot.IsValid())
    {
        Plot->SetFrame(Pending);
    }
}

void USaskartaRouteMapPlot::Configure(UObject* InFont, const FVector2D& InSize)
{
    FontObject = InFont;
    DrawSize = InSize;
    if (Plot.IsValid())
    {
        Plot->Configure(FontObject, DrawSize);
    }
}

TSharedRef<SWidget> USaskartaRouteMapPlot::RebuildWidget()
{
    Plot = SNew(SSaskartaRouteMapPlot);
    Plot->Configure(FontObject, DrawSize);
    Plot->SetFrame(Pending);
    return Plot.ToSharedRef();
}

void USaskartaRouteMapPlot::ReleaseSlateResources(bool bReleaseChildren)
{
    Super::ReleaseSlateResources(bReleaseChildren);
    Plot.Reset();
}

// ============================================================================================ the widget
void USaskartaRouteMapWidget::NativeOnInitialized()
{
    Super::NativeOnInitialized();
    if (!WidgetTree || WidgetTree->RootWidget)
    {
        return;
    }
    const FSaskartaRouteMapTuning Defaults;
    UCanvasPanel* Canvas = WidgetTree->ConstructWidget<UCanvasPanel>(UCanvasPanel::StaticClass(), TEXT("RouteCanvas"));
    WidgetTree->RootWidget = Canvas;
    Canvas->SetVisibility(ESlateVisibility::HitTestInvisible);

    Retainer = WidgetTree->ConstructWidget<URetainerBox>(URetainerBox::StaticClass(), TEXT("RouteCRT"));
    Retainer->SetRetainRendering(true);
    Retainer->SetRenderingPhase(0, 2);
    Retainer->SetTextureParameter(TEXT("Texture"));
    if (UMaterialInterface* Effect = LoadObject<UMaterialInterface>(nullptr, SaskartaRouteMap::CrtPath))
    {
        Retainer->SetEffectMaterial(Effect);
    }
    UCanvasPanelSlot* CrtSlot = Canvas->AddChildToCanvas(Retainer);
    CrtSlot->SetAnchors(FAnchors(0.f, 0.f));
    CrtSlot->SetAlignment(FVector2D(0.f, 0.f));
    CrtSlot->SetPosition(FVector2D(0.f, 0.f));
    CrtSlot->SetSize(Defaults.Size);

    Plot = WidgetTree->ConstructWidget<USaskartaRouteMapPlot>(USaskartaRouteMapPlot::StaticClass(), TEXT("RoutePlot"));
    Plot->Configure(LoadObject<UFont>(nullptr, SaskartaRouteMap::FontPath), Defaults.Size);
    Retainer->AddChild(Plot);
    SetVisibility(ESlateVisibility::Collapsed);
}

void USaskartaRouteMapWidget::ShowFrame(bool bShow, const FSaskartaRouteFrame* Frame)
{
    const ESlateVisibility Desired = bShow ? ESlateVisibility::HitTestInvisible : ESlateVisibility::Collapsed;
    if (GetVisibility() != Desired)
    {
        SetVisibility(Desired);
    }
    if (bShow && Frame && Plot)
    {
        Plot->SetFrame(*Frame);
        if (Retainer)
        {
            Retainer->RequestRender();
        }
    }
}

// ============================================================================================ the subsystem
USaskartaRouteMap* USaskartaRouteMap::GetRouteMap(const UObject* WorldContextObject)
{
    const UWorld* World = GEngine ? GEngine->GetWorldFromContextObject(WorldContextObject, EGetWorldErrorMode::ReturnNull) : nullptr;
    return World ? World->GetSubsystem<USaskartaRouteMap>() : nullptr;
}

bool USaskartaRouteMap::ShouldCreateSubsystem(UObject* Outer) const
{
    const UWorld* World = Cast<UWorld>(Outer);
    return World && World->IsGameWorld();
}

void USaskartaRouteMap::Initialize(FSubsystemCollectionBase& Collection)
{
    Super::Initialize(Collection);
    WritingRunHandle = USaskartaSaveGame::OnWritingRun.AddUObject(this, &USaskartaRouteMap::HandleWritingRun);
    RestoredRunHandle = USaskartaSaveGame::OnRestoredRun.AddUObject(this, &USaskartaRouteMap::HandleRestoredRun);
}

void USaskartaRouteMap::OnWorldBeginPlay(UWorld& InWorld)
{
    Super::OnWorldBeginPlay(InWorld);
    if (USaskartaSteleScanner* Scanner = InWorld.GetSubsystem<USaskartaSteleScanner>())
    {
        Scanner->OnSteleRead.AddUniqueDynamic(this, &USaskartaRouteMap::HandleSteleRead);
        BoundScanner = Scanner;
    }
    InWorld.GetTimerManager().SetTimer(Timer, this, &USaskartaRouteMap::Poll, SaskartaRouteMap::FrameIntervalS, true);
    InWorld.GetTimerManager().SetTimer(KeyTimer, this, &USaskartaRouteMap::PollKeys, 0.02f, true);
}

void USaskartaRouteMap::Deinitialize()
{
    if (UWorld* World = GetWorld())
    {
        World->GetTimerManager().ClearTimer(Timer);
        World->GetTimerManager().ClearTimer(KeyTimer);
    }
    if (USaskartaSteleScanner* Scanner = BoundScanner.Get())
    {
        Scanner->OnSteleRead.RemoveDynamic(this, &USaskartaRouteMap::HandleSteleRead);
    }
    USaskartaSaveGame::OnWritingRun.Remove(WritingRunHandle);
    USaskartaSaveGame::OnRestoredRun.Remove(RestoredRunHandle);
    UnbindInput();
    if (WidgetPlane)
    {
        WidgetPlane->DestroyComponent();
        WidgetPlane = nullptr;
    }
    if (Widget)
    {
        Widget->RemoveFromParent();
        Widget = nullptr;
    }
    Super::Deinitialize();
}

USaskartaEventRunner* USaskartaRouteMap::Runner() const
{
    UWorld* World = GetWorld();
    return World ? World->GetSubsystem<USaskartaEventRunner>() : nullptr;
}

bool USaskartaRouteMap::CanOpen() const
{
    const UWorld* World = GetWorld();
    const USaskartaEventRunner* R = Runner();
    const APlayerController* PC = World ? World->GetFirstPlayerController() : nullptr;
    if (!R || !PC || SaskartaRouteMap::CVarEnable.GetValueOnGameThread() == 0)
    {
        return false;
    }
    const FName Flow = R->GetFlowState();
    if (Flow != SaskartaRouteMap::Playing && Flow != SaskartaRouteMap::Carrier)
    {
        return false; // the title, the boot, and the ending (Collapsing, Human, Transmit, End)
    }
    return !(R->IsCinematicActive() || R->IsHoldingInput() || PC->IsMoveInputIgnored());
}

void USaskartaRouteMap::SetOpen(bool bInOpen)
{
    if (bInOpen && (!CanOpen() || bExternal))
    {
        return;
    }
    if (bInOpen == bOpen)
    {
        return;
    }
    bOpen = bInOpen;
    if (bOpen)
    {
        ++OpenCount;
        bNodesDirty = true;
        Core.SelectedId = NAME_None; // opens on the latest node
        LastFrameS = -1.0;
        Poll();
    }
    else
    {
        UpdateWidget(BoundController.Get(), false);
    }
}

// ------------------------------------------------------------------------------------------ input
void USaskartaRouteMap::UnbindInput()
{
    if (UInputComponent* Input = BoundInput.Get())
    {
        Input->KeyBindings.RemoveAll([this](const FInputKeyBinding& Binding)
        {
            return Binding.KeyDelegate.IsBoundToObject(this);
        });
    }
    BoundInput.Reset();
    BoundController.Reset();
}

void USaskartaRouteMap::BindInput(APlayerController* PC)
{
    UInputComponent* Input = PC ? PC->InputComponent : nullptr;
    if (BoundController.Get() == PC && BoundInput.Get() == Input && Input)
    {
        return;
    }
    UnbindInput();
    if (!PC || !Input)
    {
        return;
    }
    auto Bind = [Input, this](const FKey& Key, void (USaskartaRouteMap::*Fn)())
    {
        FInputKeyBinding& Binding = Input->BindKey(Key, IE_Pressed, this, Fn);
        Binding.bConsumeInput = false;
        Binding.bExecuteWhenPaused = false;
    };
    // M / View toggle (R / D-pad up radio, F / D-pad down lamps, E / A prompts stay theirs).
    // M / View and the arrows / D-pad are polled in PollKeys (these bindings never fired in the packaged game);
    // only the mouse wheel, which has no held state to poll, stays a binding.
    Bind(EKeys::MouseScrollDown, &USaskartaRouteMap::OnPrevKey);
    Bind(EKeys::MouseScrollUp, &USaskartaRouteMap::OnNextKey);
    BoundController = PC;
    BoundInput = Input;
}

void USaskartaRouteMap::OnToggleKey()
{
    if (bExternal)
    {
        return;
    }
    SetOpen(!bOpen);
}

void USaskartaRouteMap::ToggleFromKey(bool /*bPadKey*/)
{
    // ROUTE_BOARD_V3.md: M / D-pad down opens the map; Tab / View opens the BOARD.
    if (bExternal)
    {
        return;
    }
    SetOpen(!bOpen);
}

void USaskartaRouteMap::PollKeys()
{
    const UWorld* World = GetWorld();
    const APlayerController* PC = World ? World->GetFirstPlayerController() : nullptr;
    const bool bM = PC && PC->IsInputKeyDown(EKeys::M);
    const bool bView = PC && PC->IsInputKeyDown(MapPadKey());
    const bool bLeft = PC && (PC->IsInputKeyDown(EKeys::Left) || PC->IsInputKeyDown(EKeys::Gamepad_DPad_Left));
    const bool bRight = PC && (PC->IsInputKeyDown(EKeys::Right) || PC->IsInputKeyDown(EKeys::Gamepad_DPad_Right));
    const bool bMPressed = bM && !bMWasDown;
    const bool bViewPressed = bView && !bViewWasDown;
    const bool bLeftPressed = bLeft && !bLeftWasDown;
    const bool bRightPressed = bRight && !bRightWasDown;
    bMWasDown = bM;
    bViewWasDown = bView;
    bLeftWasDown = bLeft;
    bRightWasDown = bRight;
    if (bMPressed)
    {
        ToggleFromKey(false);
    }
    if (bViewPressed)
    {
        ToggleFromKey(true);
    }
    if (bOpen && bLeftPressed)
    {
        OnPrevKey();
    }
    if (bOpen && bRightPressed)
    {
        OnNextKey();
    }
}

void USaskartaRouteMap::ShowExternalFrame(const FSaskartaRouteFrame* Frame)
{
    const UWorld* World = GetWorld();
    APlayerController* PC = World ? World->GetFirstPlayerController() : nullptr;
    if (Frame)
    {
        if (bOpen)
        {
            bOpen = false;
        }
        bExternal = true;
        UpdateWidget(PC, true, Frame);
    }
    else if (bExternal)
    {
        bExternal = false;
        UpdateWidget(PC, false);
    }
}

void USaskartaRouteMap::OnPrevKey()
{
    if (bOpen)
    {
        Core.Step(-1);
        LastFrameS = -1.0;
        Poll();
    }
}

void USaskartaRouteMap::OnNextKey()
{
    if (bOpen)
    {
        Core.Step(1);
        LastFrameS = -1.0;
        Poll();
    }
}

// ------------------------------------------------------------------------------------------ data
bool USaskartaRouteMap::EnsureRoad()
{
    if (Core.Road.Num() >= 2)
    {
        return true;
    }
    USaskartaEventRunner* R = Runner();
    const USaskartaStoryAsset* Story = R ? R->GetStory() : nullptr;
    USplineComponent* Spline = R ? R->GetRoadSpline() : nullptr;
    if (!Story || !Spline || Story->RoadMToUeM.Num() < 2)
    {
        return false;
    }
    const float StartM = Story->RoadMToUeM[0].X;
    const float EndM = Story->RoadMToUeM.Last().X;
    TArray<FSaskartaRoutePoint> Points;
    Points.Reserve(FMath::CeilToInt((EndM - StartM) / SaskartaRouteMap::RoadStepM) + 2);
    for (float M = StartM;; M += SaskartaRouteMap::RoadStepM)
    {
        const float Clamped = FMath::Min(M, EndM);
        const float UeM = FSaskartaEventLogic::UeMFromRoadM(Story->RoadMToUeM, Clamped);
        if (UeM >= 0.f)
        {
            const FVector Loc = Spline->GetLocationAtDistanceAlongSpline(UeM * 100.f, ESplineCoordinateSpace::World);
            Points.Add({Clamped, FVector2D(Loc.X, Loc.Y)});
        }
        if (Clamped >= EndM)
        {
            break;
        }
    }
    Core.SetRoad(MoveTemp(Points));
    UE_LOG(LogSaskartaRouteMap, Log, TEXT("route map: %d road points, %.0f..%.0f m"), Core.Road.Num(), StartM, EndM);
    return Core.Road.Num() >= 2;
}

void USaskartaRouteMap::RefreshNodes()
{
    using namespace SaskartaRouteMap;
    UWorld* World = GetWorld();
    USaskartaEventRunner* R = Runner();
    const USaskartaStoryAsset* Story = R ? R->GetStory() : nullptr;

    // --- the mast (always drawn: the goal).
    if (!bMastPlaced && World && Core.Road.Num() >= 2)
    {
        FSaskartaRouteNode Mast;
        Mast.Id = MastId;
        Mast.Kind = ESaskartaRouteNodeKind::Mast;
        Mast.RoadM = Core.Road.Last().RoadM;
        Mast.bAlwaysShown = true;
        Mast.bHasWorld = true;
        Mast.WorldCm = MastFallbackCm;
        Mast.Label = TEXT("MAST");
        Mast.Title = TEXT("MAST");
        for (TActorIterator<AActor> It(World); It; ++It)
        {
            if (It->ActorHasTag(MastTag))
            {
                Mast.WorldCm = FVector2D(It->GetActorLocation().X, It->GetActorLocation().Y);
                break;
            }
        }
        Core.UpsertNode(Mast);
        bMastPlaced = true;
    }
    if (FSaskartaRouteNode* Mast = Core.Nodes.FindByPredicate([](const FSaskartaRouteNode& N) { return N.Id == MastId; }))
    {
        Mast->Lines.Reset();
        if (Core.bHasCarrier)
        {
            const double Km = FVector2D::Distance(Core.CarrierCm, Mast->WorldCm) / 100000.0;
            Mast->Lines.Add(FString::Printf(TEXT("RELAY . RANGE %.1f KM"), Km));
        }
    }

    // --- the steles scanned this run, numbered as the machine numbers texts (first-read order).
    if (const USaskartaSteleScanner* Scanner = BoundScanner.Get())
    {
        TMap<FName, int32> TextNumbers;
        for (const FName& Id : ScannedSteles)
        {
            FSaskartaSteleLogEntry E;
            if (!Scanner->DescribeStele(Id, E))
            {
                continue;
            }
            const int32* Known = TextNumbers.Find(E.InscriptionId);
            const int32 Number = Known ? *Known : TextNumbers.Add(E.InscriptionId, TextNumbers.Num() + 1);
            if (E.bHasLocation)
            {
                StelePositions.Add(Id, FVector2D(E.Location.X, E.Location.Y));
            }
            FSaskartaRouteNode N;
            N.Id = Id;
            N.Kind = ESaskartaRouteNodeKind::Stele;
            N.RoadM = E.RoadM;
            if (const FVector2D* Pos = StelePositions.Find(Id))
            {
                N.WorldCm = *Pos;
                N.bHasWorld = true;
            }
            N.Label = FString::Printf(TEXT("%02d"), Number);
            N.Title = FString::Printf(TEXT("INSCRIPTION %02d . %s M"), Number, *FSaskartaRouteMapCore::GroupedMetres(E.RoadM));
            N.Lines = {E.Translit, E.EnglishLine};
            Core.UpsertNode(N);
        }
    }

    // --- the HUD queries and wrecks already passed (fired beats and the cues of the cinematics they play).
    if (Story && R)
    {
        for (const FSaskartaBeatDef& B : Story->Beats)
        {
            if (!R->HasBeatFired(B.Id))
            {
                continue;
            }
            float BeatRoadM = B.Trigger.RoadM;
            if (BeatRoadM < 0.f && B.Trigger.UeDistanceM >= 0.f)
            {
                BeatRoadM = FSaskartaEventLogic::RoadMFromUeM(Story->RoadMToUeM, B.Trigger.UeDistanceM);
            }
            if (BeatRoadM < 0.f)
            {
                continue; // not a road beat: nowhere to put it
            }
            TArray<const FSaskartaEventAction*> Queries;
            for (const FSaskartaEventAction& A : B.Actions)
            {
                if (A.Type == ESaskartaActionType::PlayCinematic)
                {
                    if (const FSaskartaCinematicDef* C = Story->FindCinematic(A.Id))
                    {
                        for (const FSaskartaEventAction& Cue : C->Cues)
                        {
                            Queries.Add(&Cue);
                        }
                    }
                }
                Queries.Add(&A);
            }
            int32 K = 0;
            for (const FSaskartaEventAction* A : Queries)
            {
                FSaskartaHudItem Item;
                if (!FSaskartaHudLane::ItemFromAction(*A, Item))
                {
                    continue;
                }
                const bool bWreck = Item.bPriority || Item.Id.ToString().StartsWith(TEXT("WRECK"));
                FSaskartaRouteNode N;
                N.Id = Item.Id.IsNone() ? FName(*FString::Printf(TEXT("%s_%d"), *B.Id.ToString(), K)) : Item.Id;
                N.Kind = bWreck ? ESaskartaRouteNodeKind::Wreck : ESaskartaRouteNodeKind::Query;
                N.RoadM = BeatRoadM + K * SameBeatSpreadM;
                // The machine's result line as the HUD printed it (the design's rule: not the query word).
                const FString ResultLine = !bWreck && !Item.Result.IsEmpty() ? Item.Result : Item.Query;
                N.Mark = bWreck ? ESaskartaRouteMark::None : FSaskartaRouteMapCore::MarkForQuery(ResultLine);
                N.Title = TerminalSafe(ResultLine);
                N.Lines.Add(FString::Printf(TEXT("%s M"), *FSaskartaRouteMapCore::GroupedMetres(BeatRoadM)));
                Core.UpsertNode(N);
                ++K;
            }
        }
    }
    bNodesDirty = false;
}

void USaskartaRouteMap::UpdateCarrier(APlayerController* PC)
{
    const USaskartaEventRunner* R = Runner();
    const APawn* Pawn = PC ? PC->GetPawn() : nullptr;
    Core.bHasCarrier = Pawn != nullptr;
    if (Pawn)
    {
        const FVector Loc = Pawn->GetActorLocation();
        Core.CarrierCm = FVector2D(Loc.X, Loc.Y);
        Core.CarrierYawDeg = static_cast<float>(Pawn->GetActorRotation().Yaw);
    }
    const float RoadM = R ? R->GetRoadM() : -1.f;
    Core.CarrierRoadM = FMath::Max(RoadM, 0.f);
    const USaskartaStoryAsset* Story = R ? R->GetStory() : nullptr;
    const float HwUe = R ? R->GetHighWaterUeM() : TNumericLimits<float>::Max();
    const float HwRoad = (Story && HwUe != TNumericLimits<float>::Max())
        ? FSaskartaEventLogic::RoadMFromUeM(Story->RoadMToUeM, HwUe) : -1.f;
    Core.HighWaterRoadM = FMath::Max(HwRoad, Core.CarrierRoadM);
}

void USaskartaRouteMap::HandleSteleRead(const FSaskartaSteleReadout& Readout)
{
    if (!Readout.SteleId.IsNone() && !ScannedSteles.Contains(Readout.SteleId))
    {
        ScannedSteles.Add(Readout.SteleId);
        bNodesDirty = true;
    }
}

void USaskartaRouteMap::HandleWritingRun(UWorld* World, USaskartaSaveGame* Save)
{
    if (Save && World == GetWorld())
    {
        Save->RouteLogSteles = ScannedSteles;
    }
}

void USaskartaRouteMap::HandleRestoredRun(UWorld* World, USaskartaSaveGame* Save)
{
    if (Save && World == GetWorld())
    {
        ScannedSteles = Save->RouteLogSteles;
        Core.Nodes.RemoveAll([](const FSaskartaRouteNode& N) { return N.Kind != ESaskartaRouteNodeKind::Mast; });
        bNodesDirty = true;
    }
}

// ------------------------------------------------------------------------------------------ the loop
void USaskartaRouteMap::Poll()
{
    UWorld* World = GetWorld();
    if (!World)
    {
        return;
    }
    APlayerController* PC = World->GetFirstPlayerController();
    BindInput(PC);
    if (bOpen && !CanOpen())
    {
        SetOpen(false);
    }
    if (!bOpen)
    {
        return;
    }
    const double NowS = World->GetTimeSeconds();
    if (LastFrameS >= 0.0 && NowS - LastFrameS < SaskartaRouteMap::FrameIntervalS * 0.5)
    {
        return;
    }
    LastFrameS = NowS;
    EnsureRoad();
    UpdateCarrier(PC);
    if (bNodesDirty || LastNodesS < 0.0 || NowS - LastNodesS >= SaskartaRouteMap::NodesIntervalS)
    {
        RefreshNodes();
        LastNodesS = NowS;
    }
    Core.Tuning.bGamepad = FSaskartaInputDevice::IsGamepad();
    Core.EnsureSelection();
    UpdateWidget(PC, true);
}

void USaskartaRouteMap::UpdateWidget(APlayerController* PC, bool bShow, const FSaskartaRouteFrame* Override)
{
    if (Widget && Widget->GetOwningPlayer() != PC)
    {
        if (WidgetPlane)
        {
            WidgetPlane->DestroyComponent();
            WidgetPlane = nullptr;
        }
        DisplayCamera.Reset();
        Widget = nullptr;
    }
    if (!Widget && bShow && PC && PC->IsLocalController())
    {
        Widget = CreateWidget<USaskartaRouteMapWidget>(PC, USaskartaRouteMapWidget::StaticClass());
    }
    if (!Widget)
    {
        return;
    }
    if (bShow)
    {
        AttachDisplayToView(PC);
        if (Override)
        {
            Widget->ShowFrame(true, Override);
        }
        else
        {
            const FSaskartaRouteFrame Frame = Core.BuildFrame();
            Widget->ShowFrame(true, &Frame);
        }
    }
    else
    {
        Widget->ShowFrame(false, nullptr);
    }
    if (WidgetPlane && WidgetPlane->IsVisible() != bShow)
    {
        // Hidden, the plane's render target is not drawn at all.
        WidgetPlane->SetVisibility(bShow);
    }
}

void USaskartaRouteMap::AttachDisplayToView(APlayerController* PC)
{
    if (!Widget || !PC || !PC->IsLocalController())
    {
        return;
    }
    AActor* Target = PC->GetViewTarget();
    UCameraComponent* Camera = Target ? Target->FindComponentByClass<UCameraComponent>() : nullptr;
    if (Target)
    {
        TArray<UCameraComponent*> Cameras;
        Target->GetComponents(Cameras);
        for (UCameraComponent* Candidate : Cameras)
        {
            if (Candidate && Candidate->IsActive())
            {
                Camera = Candidate;
                break;
            }
        }
    }
    AActor* DisplayOwner = Camera ? Camera->GetOwner() : nullptr;
    if (!DisplayOwner || DisplayOwner->IsHidden())
    {
        return;
    }
    if (WidgetPlane && (!IsValid(WidgetPlane) || WidgetPlane->GetOwner() != DisplayOwner))
    {
        if (IsValid(WidgetPlane)) WidgetPlane->DestroyComponent();
        WidgetPlane = nullptr;
        DisplayCamera.Reset();
    }
    if (WidgetPlane && DisplayCamera.Get() == Camera)
    {
        return;
    }
    if (!WidgetPlane)
    {
        // Keep the map on the visible camera actor; the controller is hidden in game.
        WidgetPlane = NewObject<UWidgetComponent>(DisplayOwner, NAME_None, RF_Transient);
        DisplayOwner->AddInstanceComponent(WidgetPlane);
        WidgetPlane->SetWidgetSpace(EWidgetSpace::World);
        WidgetPlane->SetDrawSize(Core.Tuning.Size);
        WidgetPlane->SetPivot(FVector2D(0.5f, 0.5f));
        WidgetPlane->SetTwoSided(true);
        WidgetPlane->SetCollisionEnabled(ECollisionEnabled::NoCollision);
        WidgetPlane->SetWidget(Widget);
        WidgetPlane->RegisterComponent();
    }
    WidgetPlane->AttachToComponent(Camera, FAttachmentTransformRules::KeepRelativeTransform);
    // Centre of the view, a hair behind the power line and the motor display (same scale), so the sensor's
    // CRT post-process covers it too and the road stays visible through the lines. Tune after a standalone look.
    WidgetPlane->SetRelativeTransform(FTransform(FRotator(0.f, 180.f, 0.f), FVector(25.f, 0.f, 0.5f), FVector(0.028f)));
    DisplayCamera = Camera;
}

FString USaskartaRouteMap::DumpState() const
{
    FString Out = FString::Printf(TEXT("RouteMap open=%d can=%d opens=%d road=%d nodes=%d scanned=%d hw=%.0f m carrier=%.0f m sel=%s\n"),
        bOpen ? 1 : 0, CanOpen() ? 1 : 0, OpenCount, Core.Road.Num(), Core.Nodes.Num(), ScannedSteles.Num(),
        Core.HighWaterRoadM, Core.CarrierRoadM, *Core.SelectedId.ToString());
    for (const FSaskartaRouteNode& N : Core.Nodes)
    {
        Out += FString::Printf(TEXT("  %-18s kind=%d road=%6.0f shown=%d mark=%d  %s\n"), *N.Id.ToString(),
            static_cast<int32>(N.Kind), N.RoadM, Core.IsNodeShown(N) ? 1 : 0, static_cast<int32>(N.Mark), *N.Title);
    }
    return Out;
}

namespace SaskartaRouteMap
{
    static FAutoConsoleCommandWithWorldAndArgs CmdToggle(TEXT("Saskarta.RouteMap.Toggle"),
        TEXT("Opens or closes the CRT route map (as M / View)."),
        FConsoleCommandWithWorldAndArgsDelegate::CreateLambda([](const TArray<FString>&, UWorld* World)
        {
            if (USaskartaRouteMap* Map = World ? World->GetSubsystem<USaskartaRouteMap>() : nullptr)
            {
                Map->SetOpen(!Map->IsOpen());
            }
        }));

    static FAutoConsoleCommandWithWorldAndArgs CmdDump(TEXT("Saskarta.RouteMap.Dump"),
        TEXT("Logs the route map's state and nodes."),
        FConsoleCommandWithWorldAndArgsDelegate::CreateLambda([](const TArray<FString>&, UWorld* World)
        {
            if (const USaskartaRouteMap* Map = World ? World->GetSubsystem<USaskartaRouteMap>() : nullptr)
            {
                UE_LOG(LogSaskartaRouteMap, Display, TEXT("%s"), *Map->DumpState());
            }
        }));
}
