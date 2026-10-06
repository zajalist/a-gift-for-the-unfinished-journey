#include "SaskartaPackageRescue.h"
#include "Blueprint/WidgetTree.h"
#include "Components/Border.h"
#include "Components/RetainerBox.h"
#include "Components/SizeBox.h"
#include "Components/TextBlock.h"
#include "Components/VerticalBox.h"
#include "Components/VerticalBoxSlot.h"
#include "Engine/Font.h"
#include "Materials/MaterialInterface.h"
#include "Styling/CoreStyle.h"

void USaskartaPackageRescueWidget::NativeOnInitialized()
{
    Super::NativeOnInitialized();
    SetIsFocusable(true);
    if (!WidgetTree || WidgetTree->RootWidget) return;
    UBorder* Backdrop = WidgetTree->ConstructWidget<UBorder>();
    WidgetTree->RootWidget = Backdrop;
    Backdrop->SetBrushColor(FLinearColor(0.003f, 0.004f, 0.002f, 1.f));
    Backdrop->SetHorizontalAlignment(HAlign_Center);
    Backdrop->SetVerticalAlignment(VAlign_Center);
    Backdrop->SetPadding(FMargin(40.f));
    URetainerBox* CRT = WidgetTree->ConstructWidget<URetainerBox>();
    CRT->SetTextureParameter(TEXT("Texture"));
    if (UMaterialInterface* Effect = LoadObject<UMaterialInterface>(nullptr,
        TEXT("/Game/SaskartaGaea/GameFlow/Materials/MI_UI_RadioCRT.MI_UI_RadioCRT"))) CRT->SetEffectMaterial(Effect);
    Backdrop->SetContent(CRT);
    USizeBox* Width = WidgetTree->ConstructWidget<USizeBox>();
    Width->SetWidthOverride(740.f);
    CRT->SetContent(Width);
    UVerticalBox* Column = WidgetTree->ConstructWidget<UVerticalBox>();
    Width->SetContent(Column);
    UFont* Font = LoadObject<UFont>(nullptr, TEXT("/Game/SaskartaGaea/GameFlow/UI/Fonts/Font_Terminal.Font_Terminal"));
    auto AddLine = [&](const TCHAR* Text, int32 Size, float Bottom)
    {
        UTextBlock* Line = WidgetTree->ConstructWidget<UTextBlock>();
        Line->SetText(FText::FromString(Text));
        Line->SetFont(Font ? FSlateFontInfo(Font, Size) : FCoreStyle::GetDefaultFontStyle("Regular", Size));
        Line->SetColorAndOpacity(FSlateColor(FLinearColor(1.f, 0.7f, 0.27f)));
        Line->SetAutoWrapText(true);
        Column->AddChildToVerticalBox(Line)->SetPadding(FMargin(0.f, 0.f, 0.f, Bottom));
        return Line;
    };
    AddLine(TEXT("CARRIER CONNECTION LOST"), 18, 36.f);
    AddLine(TEXT("PACKAGE RESCUE OPERATION"), 32, 20.f);
    Status = AddLine(TEXT("RECOVERING PACKAGE..."), 28, 36.f);
    Detail = AddLine(TEXT("Restoring route connection."), 19, 0.f);
}

void USaskartaPackageRescueWidget::SetSuccessful(bool bFuelRestored)
{
    if (Status) Status->SetText(FText::FromString(TEXT("SUCCESSFUL")));
    if (Detail) Detail->SetText(FText::FromString(bFuelRestored
        ? TEXT("Package secured. Recovery fuel reserve restored. Resuming route.")
        : TEXT("Package secured. Fuel reserve ready. Resuming route.")));
}

void USaskartaPackageRescueWidget::SetRecoveryFailed()
{
    if (Status) Status->SetText(FText::FromString(TEXT("CONNECTION INTERRUPTED")));
    if (Detail) Detail->SetText(FText::FromString(TEXT("Restoring the last saved carrier connection.")));
}
