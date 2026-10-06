// USaskartaEventRunner, part: a story prompt the player can always see and answer, and the ending's
// data layer resolved through its asset. The rules are FSaskartaPromptLogic (SaskartaPromptLogic.h).
//
// Packaged playtest, 2026-09-29: after CIN_18 the collapse's boot-log black (BPC_CarrierVision's
// BootLogWidget, UMG ZOrder 100, opacity 1) stays up by design until CIN_19 clears it, and B18's
// "Release the inner latch." went only to the caption widget (ZOrder 40) underneath it: an invisible
// prompt on a dead screen. Now:
//   - while that black is up, the prompt is typed onto the CRT as one more log line (its ShowLogLine);
//   - an unanswered prompt is re-shown after FirstRemindS and every RemindEveryS (the caption again, the CRT
//     line again, and the runner's own line above every HUD widget), and the game viewport gets focus back;
//   - E / Enter / gamepad A are read from the PlayerInput and, on Windows while the game has focus, from the
//     keyboard itself, so a widget holding keyboard focus cannot swallow the answer.

#include "SaskartaEventRunner.h"
#include "SaskartaPromptLogic.h"

#include "AssetRegistry/AssetData.h"
#include "AssetRegistry/IAssetRegistry.h"
#include "Blueprint/UserWidget.h"
#include "Components/ActorComponent.h"
#include "Engine/GameViewportClient.h"
#include "Engine/World.h"
#include "Framework/Application/SlateApplication.h"
#include "GameFramework/PlayerController.h"
#include "InputCoreTypes.h"
#include "Misc/App.h"
#include "Styling/CoreStyle.h"
#include "UObject/UnrealType.h"
#include "Widgets/Layout/SBox.h"
#include "Widgets/Layout/SBorder.h"
#include "Widgets/SBoxPanel.h"
#include "HAL/PlatformTime.h"
#include "Widgets/Text/STextBlock.h"
#include "WorldPartition/DataLayer/DataLayerAsset.h"
#include "WorldPartition/DataLayer/DataLayerInstance.h"
#include "WorldPartition/DataLayer/DataLayerManager.h"

#if PLATFORM_WINDOWS
#include "Windows/WindowsHWrapper.h"
#endif

DEFINE_LOG_CATEGORY_STATIC(LogSaskartaPrompt, Log, All);

namespace SaskartaPrompt
{
    static const FName NameShowLogLine(TEXT("ShowLogLine"));
    static const FName NameBootLogWidget(TEXT("BootLogWidget"));
    static const FName NameLine(TEXT("Line"));
    static const FName NameResult(TEXT("Result"));
    /** WBP_Saskarta_BootLog.ShowStatus prints no [ OK ] / [FAIL] for NONE. */
    static const FName NameNoStatus(TEXT("NONE"));
    static const TCHAR* TerminalFontPath = TEXT("/Game/SaskartaGaea/GameFlow/UI/Fonts/Font_Terminal.Font_Terminal");
}

void USaskartaEventRunner::NotePromptShown(const FText& Text)
{
    PromptText = Text;
    PromptShownS = Now();
    PromptLastRemindS = -1.0;
    PromptReminds = 0;
    RemovePromptOverlay();

    bool bBlackUp = false;
    UActorComponent* Terminal = FindCrtTerminal(bBlackUp);
    if (bBlackUp && TypeCrtLine(Terminal, FSaskartaPromptLogic::CrtLine(Text.ToString())))
    {
        UE_LOG(LogSaskartaPrompt, Log, TEXT("prompt typed on the CRT (the boot-log black is up)"));
    }
    // 2026-10-05 (the author): over the black the prompt stays on screen until answered, with a pulsing E.
    if (bBlackUp)
    {
        ShowPromptOverlay(Text.ToString());
    }
}

void USaskartaEventRunner::TickPromptReminder()
{
    if (!bPromptActive)
    {
        return;
    }
    const double T = Now();
    if (!FSaskartaPromptLogic::ShouldRemind(T - PromptShownS, PromptLastRemindS < 0.0 ? -1.0 : T - PromptLastRemindS))
    {
        return;
    }
    PromptLastRemindS = T;
    ++PromptReminds;
    const FString Plain = PromptText.ToString();
    OnPromptShow.Broadcast(PromptText);
    bool bBlackUp = false;
    UActorComponent* Terminal = FindCrtTerminal(bBlackUp);
    if (bBlackUp)
    {
        TypeCrtLine(Terminal, FSaskartaPromptLogic::CrtLine(Plain));
    }
    ShowPromptOverlay(Plain);

    // A widget holding keyboard focus (no menu is up: the cursor is hidden and the game runs) gives it back.
    APlayerController* PC = GetPC();
    const UWorld* World = GetWorld();
    if (PC && !PC->bShowMouseCursor && World && !World->IsPaused() && FSlateApplication::IsInitialized())
    {
        FSlateApplication::Get().SetAllUserFocusToGameViewport();
    }
    UE_LOG(LogSaskartaPrompt, Log, TEXT("prompt reminder %d: '%s' unanswered for %.0f s (next beat %s)"),
        PromptReminds, *Plain, T - PromptShownS, *PromptNextBeat.ToString());
}

void USaskartaEventRunner::ReadPromptKeys(bool& bOutKeyboardDown, bool& bOutGamepadDown) const
{
    bOutKeyboardDown = false;
    bOutGamepadDown = false;
    if (const APlayerController* PC = GetPC())
    {
        bOutKeyboardDown = PC->IsInputKeyDown(EKeys::E) || PC->IsInputKeyDown(EKeys::Enter);
        bOutGamepadDown = PC->IsInputKeyDown(EKeys::Gamepad_FaceButton_Bottom);
    }
#if PLATFORM_WINDOWS
    // The PlayerInput only sees keys the game viewport receives. With the game window in front, read the
    // keyboard too, so a focused widget or an input-mode change cannot eat the answer (packaged 2026-09-29).
    if (!bOutKeyboardDown && FApp::HasFocus())
    {
        bOutKeyboardDown = (::GetAsyncKeyState('E') & 0x8000) != 0 || (::GetAsyncKeyState(VK_RETURN) & 0x8000) != 0;
    }
#endif
}

UActorComponent* USaskartaEventRunner::FindCrtTerminal(bool& bOutBlackUp) const
{
    bOutBlackUp = false;
    const APlayerController* PC = GetPC();
    if (!PC)
    {
        return nullptr;
    }
    // BPC_CarrierVision on the PC: found by what it has (ShowLogLine and BootLogWidget), not by a name.
    for (UActorComponent* Comp : PC->GetComponents())
    {
        if (!Comp || !Comp->FindFunction(SaskartaPrompt::NameShowLogLine))
        {
            continue;
        }
        if (const FObjectPropertyBase* Prop = FindFProperty<FObjectPropertyBase>(Comp->GetClass(), SaskartaPrompt::NameBootLogWidget))
        {
            if (const UUserWidget* W = Cast<UUserWidget>(Prop->GetObjectPropertyValue_InContainer(Comp)))
            {
                const ESlateVisibility V = W->GetVisibility();
                bOutBlackUp = W->IsInViewport() && V != ESlateVisibility::Collapsed && V != ESlateVisibility::Hidden
                    && W->GetRenderOpacity() > 0.5f;
            }
        }
        return Comp;
    }
    return nullptr;
}

bool USaskartaEventRunner::TypeCrtLine(UActorComponent* Terminal, const FString& Line) const
{
    UFunction* Func = Terminal ? Terminal->FindFunction(SaskartaPrompt::NameShowLogLine) : nullptr;
    if (!Func || Func->ParmsSize <= 0)
    {
        return false;
    }
    FTextProperty* LineProp = FindFProperty<FTextProperty>(Func, SaskartaPrompt::NameLine);
    FNameProperty* ResultProp = FindFProperty<FNameProperty>(Func, SaskartaPrompt::NameResult);
    if (!LineProp || !ResultProp)
    {
        return false;
    }
    uint8* Params = static_cast<uint8*>(FMemory_Alloca(Func->ParmsSize));
    FMemory::Memzero(Params, Func->ParmsSize);
    for (TFieldIterator<FProperty> It(Func); It && It->HasAnyPropertyFlags(CPF_Parm); ++It)
    {
        It->InitializeValue_InContainer(Params);
    }
    LineProp->SetPropertyValue_InContainer(Params, FText::FromString(Line));
    ResultProp->SetPropertyValue_InContainer(Params, SaskartaPrompt::NameNoStatus);
    Terminal->ProcessEvent(Func, Params);
    for (TFieldIterator<FProperty> It(Func); It && It->HasAnyPropertyFlags(CPF_Parm); ++It)
    {
        It->DestroyValue_InContainer(Params);
    }
    return true;
}

void USaskartaEventRunner::ShowPromptOverlay(const FString& Line)
{
    RemovePromptOverlay();
    UWorld* World = GetWorld();
    UGameViewportClient* Viewport = World ? World->GetGameViewport() : nullptr;
    if (!Viewport)
    {
        return;
    }
    if (!PromptFont)
    {
        PromptFont = LoadObject<UObject>(nullptr, SaskartaPrompt::TerminalFontPath, nullptr, LOAD_NoWarn | LOAD_Quiet);
    }
    const FSlateFontInfo Font = PromptFont ? FSlateFontInfo(PromptFont, 34.f) : FCoreStyle::GetDefaultFontStyle("Regular", 28);
    const FSlateFontInfo KeyFont = PromptFont ? FSlateFontInfo(PromptFont, 40.f) : FCoreStyle::GetDefaultFontStyle("Bold", 32);
    FString Body = Line.TrimStartAndEnd();
    const double T0 = FPlatformTime::Seconds();
    TSharedRef<SWidget> Widget = SNew(SBox)
        .Visibility(EVisibility::HitTestInvisible)
        .HAlign(HAlign_Center)
        .VAlign(VAlign_Bottom)
        .Padding(FMargin(16.f, 0.f, 16.f, 150.f))
        [
            SNew(SHorizontalBox)
            + SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center).Padding(0.f, 0.f, 22.f, 0.f)
            [
                SNew(SBorder)
                .BorderImage(FCoreStyle::Get().GetBrush("WhiteBrush"))
                .BorderBackgroundColor_Lambda([T0]()
                {
                    const float A = 0.5f + 0.5f * FMath::Sin(float(FPlatformTime::Seconds() - T0) * 5.f);
                    return FSlateColor(FLinearColor(1.f, 0.62f, 0.15f, 0.35f + 0.65f * A));
                })
                .Padding(FMargin(14.f, 2.f))
                .RenderTransformPivot(FVector2D(0.5f, 0.5f))
                .RenderTransform_Lambda([T0]()
                {
                    const float A = 0.5f + 0.5f * FMath::Sin(float(FPlatformTime::Seconds() - T0) * 5.f);
                    return TOptional<FSlateRenderTransform>(FSlateRenderTransform(1.f + 0.12f * A));
                })
                [
                    SNew(STextBlock)
                    .Text(FText::FromString(TEXT("E")))
                    .Font(KeyFont)
                    .ColorAndOpacity(FSlateColor(FLinearColor(0.02f, 0.02f, 0.02f, 1.f)))
                ]
            ]
            + SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center)
            [
                SNew(STextBlock)
                .Text(FText::FromString(Body))
                .Font(Font)
                .ColorAndOpacity(FSlateColor(FLinearColor(1.f, 0.72f, 0.25f, 1.f)))
                .ShadowOffset(FVector2D(2.f, 2.f))
                .ShadowColorAndOpacity(FLinearColor(0.f, 0.f, 0.f, 0.9f))
            ]
        ];
    Viewport->AddViewportWidgetContent(Widget, FSaskartaPromptLogic::OverlayZOrder);
    PromptOverlay = Widget;
    PromptOverlayViewport = Viewport;
}

void USaskartaEventRunner::RemovePromptOverlay()
{
    if (PromptOverlay.IsValid())
    {
        if (UGameViewportClient* Viewport = PromptOverlayViewport.Get())
        {
            Viewport->RemoveViewportWidgetContent(PromptOverlay.ToSharedRef());
        }
    }
    PromptOverlay.Reset();
    PromptOverlayViewport.Reset();
}

void USaskartaEventRunner::HandlePromptHidden()
{
    RemovePromptOverlay();
}

bool USaskartaEventRunner::ActivateDataLayer(const FString& Ref)
{
    UWorld* World = GetWorld();
    if (!World || Ref.IsEmpty())
    {
        return false;
    }
    // By its UDataLayerAsset (name or path): a cooked World Partition game keeps the asset, not an editor label.
    if (UDataLayerManager* Manager = UDataLayerManager::GetDataLayerManager(World))
    {
        for (UDataLayerInstance* Instance : Manager->GetDataLayerInstances())
        {
            const UDataLayerAsset* Asset = Instance ? Instance->GetAsset() : nullptr;
            if (!Asset || !FSaskartaPromptLogic::DataLayerAssetMatches(Ref, Asset->GetName(), Asset->GetPathName()))
            {
                continue;
            }
            if (!Instance->IsRuntime())
            {
                UE_LOG(LogSaskartaPrompt, Warning, TEXT("data layer %s (%s) is an editor data layer: a cooked game has none. Make it a Runtime layer."),
                    *Ref, *Asset->GetPathName());
                return false;
            }
            Manager->SetDataLayerInstanceRuntimeState(Instance, EDataLayerRuntimeState::Activated);
            UE_LOG(LogSaskartaPrompt, Log, TEXT("data layer %s activated (%s)"), *Ref, *Asset->GetPathName());
            return true;
        }
    }
    const FName Once(*(TEXT("DL:") + Ref));
    if (WarnedMissing.Contains(Once))
    {
        return false;
    }
    WarnedMissing.Add(Once);
    FString FoundPath;
    if (IAssetRegistry* AR = IAssetRegistry::Get())
    {
        TArray<FAssetData> Assets;
        AR->GetAssetsByClass(UDataLayerAsset::StaticClass()->GetClassPathName(), Assets, true);
        for (const FAssetData& A : Assets)
        {
            if (FSaskartaPromptLogic::DataLayerAssetMatches(Ref, A.AssetName.ToString(), A.GetObjectPathString()))
            {
                FoundPath = A.GetObjectPathString();
                break;
            }
        }
    }
    if (!FoundPath.IsEmpty())
    {
        UE_LOG(LogSaskartaPrompt, Warning, TEXT("data layer %s: the asset %s exists but this world has no instance of it (add it to the level as a Runtime layer)"),
            *Ref, *FoundPath);
    }
    else
    {
        UE_LOG(LogSaskartaPrompt, Display, TEXT("data layer %s: no UDataLayerAsset of that name in this build. The ending set is not in a data layer: it is always loaded or streams with the world, so there is nothing to activate."),
            *Ref);
    }
    return false;
}
