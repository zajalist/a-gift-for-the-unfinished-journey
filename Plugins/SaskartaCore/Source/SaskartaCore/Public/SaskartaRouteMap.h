// USaskartaRouteMap: the carrier's top-down route map on the CRT (M / D-pad down). A world subsystem, a thin shell
// over FSaskartaRouteMapCore (SaskartaRouteMapLogic.h), which builds every line and string.
//
//   - Road: BP_Saskarta_Road's spline (USaskartaEventRunner::GetRoadSpline), sampled every 20 road m once,
//     road m <-> UE m through DA_Saskarta_Story's RoadMToUeM (the same mapping the road beats use).
//   - Nodes: the steles SCANNED this run (USaskartaSteleScanner::OnSteleRead; text from DescribeStele),
//     the HUD queries and wrecks whose beats have fired (their ShowHudQuery actions and the cues of the
//     cinematics they play), labelled by the BOARD (a name or a number, never a ?), and the mast.
//     The scanned list is saved in the run checkpoint (USaskartaSaveGame::RouteLogSteles).
//   - Keys (polled at 50 Hz because bindings did not fire in the package):
//     M / D-pad down toggle; Left / Right, D-pad left / right and the mouse wheel step the
//     selection while the map is open. The mouse keeps driving the look: there is no cursor on the CRT.
//   - Pauses nothing. Opens only in Playing / Carrier, outside cinematics and input holds;
//     closes itself when any of that changes (the ending's flow states are never Playing).
//   - Cheap: no scene capture. One SLeafWidget paints lines and text into the same retainer +
//     MI_UI_RadioCRT as the power line, on a world-space plane in front of the active camera. 10 Hz while
//     open; closed, the plane is hidden and only a 0.1 s state check runs.
//
// Console: Saskarta.RouteMap.Toggle, Saskarta.RouteMap.Dump. CVar saskarta.RouteMap.Enable.
// C++ built only while the editor is closed (never leave an unbuilt plugin enabled).

#pragma once

#include "CoreMinimal.h"
#include "InputCoreTypes.h"
#include "Blueprint/UserWidget.h"
#include "Components/Widget.h"
#include "Subsystems/WorldSubsystem.h"
#include "TimerManager.h"
#include "SaskartaRouteMapLogic.h"
#include "SaskartaSteleScanner.h"
#include "SaskartaRouteMap.generated.h"

class APlayerController;
class SSaskartaRouteMapPlot;
class UCameraComponent;
class UInputComponent;
class URetainerBox;
class USaskartaEventRunner;
class USaskartaSaveGame;
class UWidgetComponent;

/** Paints one FSaskartaRouteFrame (phosphor lines and Font_Terminal text). */
UCLASS()
class SASKARTACORE_API USaskartaRouteMapPlot : public UWidget
{
    GENERATED_BODY()

public:
    void SetFrame(const FSaskartaRouteFrame& Frame);
    void Configure(UObject* InFont, const FVector2D& InSize);

protected:
    virtual TSharedRef<SWidget> RebuildWidget() override;
    virtual void ReleaseSlateResources(bool bReleaseChildren) override;

private:
    TSharedPtr<SSaskartaRouteMapPlot> Plot;
    UPROPERTY(Transient)
    TObjectPtr<UObject> FontObject;
    FSaskartaRouteFrame Pending;
    FVector2D DrawSize = FVector2D(640.f, 440.f);
};

UCLASS()
class SASKARTACORE_API USaskartaRouteMapWidget : public UUserWidget
{
    GENERATED_BODY()

public:
    void ShowFrame(bool bShow, const FSaskartaRouteFrame* Frame);

protected:
    virtual void NativeOnInitialized() override;

private:
    UPROPERTY(Transient)
    TObjectPtr<URetainerBox> Retainer;
    UPROPERTY(Transient)
    TObjectPtr<USaskartaRouteMapPlot> Plot;
};

UCLASS()
class SASKARTACORE_API USaskartaRouteMap : public UWorldSubsystem
{
    GENERATED_BODY()

public:
    UFUNCTION(BlueprintPure, Category = "Saskarta|RouteMap", meta = (WorldContext = "WorldContextObject"))
    static USaskartaRouteMap* GetRouteMap(const UObject* WorldContextObject);

    virtual bool ShouldCreateSubsystem(UObject* Outer) const override;
    virtual void Initialize(FSubsystemCollectionBase& Collection) override;
    virtual void OnWorldBeginPlay(UWorld& InWorld) override;
    virtual void Deinitialize() override;

    UFUNCTION(BlueprintCallable, Category = "Saskarta|RouteMap")
    void SetOpen(bool bInOpen);

    UFUNCTION(BlueprintPure, Category = "Saskarta|RouteMap")
    bool IsOpen() const { return bOpen; }

    /** Playing / Carrier, no cinematic, no input hold. */
    UFUNCTION(BlueprintPure, Category = "Saskarta|RouteMap")
    bool CanOpen() const;
    static FKey MapPadKey() { return EKeys::Gamepad_DPad_Down; }

    /** Steles scanned this run (the onboarding's M hint waits for the first). */
    UFUNCTION(BlueprintPure, Category = "Saskarta|RouteMap")
    int32 NumScanned() const { return ScannedSteles.Num(); }

    /** How many times the map was opened this session (the onboarding's "map_opened"). */
    int32 GetOpenCount() const { return OpenCount; }

    const FSaskartaRouteMapCore& GetCore() const { return Core; }

    /** The ROUTE LOG (SaskartaRouteLog.h) borrows this CRT surface: a frame shows it instead of the map (the map
     *  closes and M / View do not reopen it meanwhile); nullptr hands the surface back. */
    void ShowExternalFrame(const FSaskartaRouteFrame* Frame);
    bool IsShowingExternal() const { return bExternal; }

    FString DumpState() const;

private:
    void Poll();
    void BindInput(APlayerController* PC);
    void UnbindInput();
    void OnToggleKey();
    void OnPrevKey();
    void OnNextKey();
    /** 50 Hz key edges: the input bindings never fired M in the packaged game. */
    void PollKeys();
    void ToggleFromKey(bool bViewButton);
    bool EnsureRoad();
    void RefreshNodes();
    void UpdateCarrier(APlayerController* PC);
    void UpdateWidget(APlayerController* PC, bool bShow, const FSaskartaRouteFrame* Override = nullptr);
    void AttachDisplayToView(APlayerController* PC);
    void HandleWritingRun(UWorld* World, USaskartaSaveGame* Save);
    void HandleRestoredRun(UWorld* World, USaskartaSaveGame* Save);
    USaskartaEventRunner* Runner() const;

    UFUNCTION()
    void HandleSteleRead(const FSaskartaSteleReadout& Readout);

    FSaskartaRouteMapCore Core;
    /** Scan order (saved). */
    TArray<FName> ScannedSteles;
    /** Last known face location per scanned stele (the stone may have streamed out since). */
    TMap<FName, FVector2D> StelePositions;
    bool bOpen = false;
    bool bExternal = false;
    bool bNodesDirty = true;
    bool bMastPlaced = false;
    int32 OpenCount = 0;
    double LastNodesS = -1.0;
    double LastFrameS = -1.0;

    TWeakObjectPtr<UInputComponent> BoundInput;
    TWeakObjectPtr<APlayerController> BoundController;
    TWeakObjectPtr<USaskartaSteleScanner> BoundScanner;
    UPROPERTY(Transient)
    TObjectPtr<USaskartaRouteMapWidget> Widget;
    UPROPERTY(Transient)
    TObjectPtr<UWidgetComponent> WidgetPlane;
    TWeakObjectPtr<UCameraComponent> DisplayCamera;
    FDelegateHandle WritingRunHandle;
    FDelegateHandle RestoredRunHandle;
    FTimerHandle Timer;
    FTimerHandle KeyTimer;
    bool bMWasDown = false;
    bool bViewWasDown = false;
    bool bLeftWasDown = false;
    bool bRightWasDown = false;
};
