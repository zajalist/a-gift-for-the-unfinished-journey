#include "SaskartaGameplayHintWidget.h"

#include "Blueprint/WidgetTree.h"
#include "Components/CanvasPanel.h"
#include "Components/CanvasPanelSlot.h"
#include "Components/HorizontalBox.h"
#include "Components/HorizontalBoxSlot.h"
#include "Components/Image.h"
#include "Components/ScaleBox.h"
#include "Components/ScaleBoxSlot.h"
#include "Components/SizeBox.h"
#include "Components/SizeBoxSlot.h"
#include "Components/TextBlock.h"
#include "Engine/AssetManager.h"
#include "Engine/Font.h"
#include "Engine/StreamableManager.h"
#include "Engine/Texture2D.h"
#include "Styling/CoreStyle.h"

DEFINE_LOG_CATEGORY_STATIC(LogSaskartaGameplayHints, Log, All);

namespace SaskartaGameplayHint
{
    constexpr const TCHAR* FontPath = TEXT("/Game/SaskartaGaea/GameFlow/UI/Fonts/F_ArefRuqaa_Caption.F_ArefRuqaa_Caption");
    const TCHAR* const GlyphNames[] = {
        TEXT("Key_W"), TEXT("Key_S"), TEXT("Key_A"), TEXT("Key_D"), TEXT("Mouse_Move"),
        TEXT("Key_Shift"), TEXT("Key_R"), TEXT("Key_Tab"), TEXT("Pad_Y"), TEXT("Pad_LStick"),
        TEXT("Pad_RStick"), TEXT("Pad_RT"), TEXT("Pad_DPad_Up"), TEXT("Pad_View")
    };

    FSoftObjectPath GlyphPath(const TCHAR* Glyph)
    {
        return FSoftObjectPath(FString::Printf(
            TEXT("/Game/SaskartaGaea/UI/Prompts/Light/T_Prompt_%s.T_Prompt_%s"), Glyph, Glyph));
    }
}

void USaskartaGameplayHintWidget::NativeOnInitialized()
{
    Super::NativeOnInitialized();
    SetIsFocusable(false);
    SetVisibility(ESlateVisibility::Collapsed);
    if (!WidgetTree) return;
    if (WidgetTree->RootWidget)
    {
        bAuthoredLayout = true;
        HintRow = Cast<UHorizontalBox>(GetWidgetFromName(TEXT("HintRow")));
        bAuthoredBindingsValid = HintRow != nullptr;
        for (int32 Index = 0; Index < 14; ++Index)
        {
            UImage* Glyph = Cast<UImage>(GetWidgetFromName(FName(*FString::Printf(TEXT("HintGlyph%d"), Index))));
            USizeBox* Bounds = Cast<USizeBox>(GetWidgetFromName(FName(*FString::Printf(TEXT("HintGlyphBox%d"), Index))));
            AuthoredGlyphs.Add(Glyph);
            AuthoredGlyphBounds.Add(Bounds);
            bAuthoredBindingsValid &= Glyph && Bounds;
        }
        for (int32 Index = 0; Index < 7; ++Index)
        {
            UTextBlock* Caption = Cast<UTextBlock>(GetWidgetFromName(FName(*FString::Printf(TEXT("HintCaption%d"), Index))));
            AuthoredCaptions.Add(Caption);
            bAuthoredBindingsValid &= Caption != nullptr;
        }
        if (!bAuthoredBindingsValid)
        {
            UE_LOG(LogSaskartaGameplayHints, Error, TEXT("%s: authored tutorial UMG layout has missing or mistyped named slots. Install Tools/UIRuntime layouts."), *GetClass()->GetPathName());
        }
        else
        {
            LoadPresentationAssets();
        }
        return;
    }

    UCanvasPanel* Root = WidgetTree->ConstructWidget<UCanvasPanel>();
    WidgetTree->RootWidget = Root;
    UScaleBox* Fit = WidgetTree->ConstructWidget<UScaleBox>();
    Fit->SetStretch(EStretch::ScaleToFit);
    Fit->SetStretchDirection(EStretchDirection::DownOnly);
    UCanvasPanelSlot* LayoutSlot = Root->AddChildToCanvas(Fit);
    LayoutSlot->SetAnchors(FAnchors(0.f, 1.f, 1.f, 1.f));
    LayoutSlot->SetOffsets(FMargin(24.f, -122.f, 24.f, 100.f));

    USizeBox* Bounds = WidgetTree->ConstructWidget<USizeBox>();
    Bounds->SetWidthOverride(760.f);
    Bounds->SetHeightOverride(76.f);
    UScaleBoxSlot* FitSlot = Cast<UScaleBoxSlot>(Fit->AddChild(Bounds));
    FitSlot->SetHorizontalAlignment(HAlign_Center);
    FitSlot->SetVerticalAlignment(VAlign_Center);
    HintRow = WidgetTree->ConstructWidget<UHorizontalBox>(UHorizontalBox::StaticClass(), TEXT("HintRow"));
    Bounds->AddChild(HintRow);
    // Centre the content within the fixed, down-scalable canvas; there is no background brush.
    if (UPanelSlot* ContentSlot = HintRow->Slot)
    {
        if (USizeBoxSlot* SizeSlot = Cast<USizeBoxSlot>(ContentSlot))
        {
            SizeSlot->SetHorizontalAlignment(HAlign_Center);
            SizeSlot->SetVerticalAlignment(VAlign_Center);
        }
    }
    SetVisibility(ESlateVisibility::Collapsed);
    LoadPresentationAssets();
}

void USaskartaGameplayHintWidget::LoadPresentationAssets()
{
    if (PresentationLoad.IsValid()) return;
    TArray<FSoftObjectPath> Paths;
    Paths.Add(FSoftObjectPath(SaskartaGameplayHint::FontPath));
    for (const TCHAR* Glyph : SaskartaGameplayHint::GlyphNames)
        Paths.Add(SaskartaGameplayHint::GlyphPath(Glyph));
    PresentationLoad = UAssetManager::GetStreamableManager().RequestAsyncLoad(Paths,
        FStreamableDelegate::CreateWeakLambda(this, [this]()
        {
            CaptionFont = Cast<UFont>(FSoftObjectPath(SaskartaGameplayHint::FontPath).ResolveObject());
            for (const TCHAR* Glyph : SaskartaGameplayHint::GlyphNames)
                if (UTexture2D* Texture = Cast<UTexture2D>(SaskartaGameplayHint::GlyphPath(Glyph).ResolveObject()))
                    GlyphTextures.Add(FName(Glyph), Texture);
            if (bHintRequested) RefreshHint();
        }));
}

void USaskartaGameplayHintWidget::ShowHint(FName Id, const FString& Text, bool bGamepad)
{
    const bool bChanged = CurrentId != Id || CurrentText != Text || bCurrentGamepad != bGamepad;
    CurrentId = Id;
    CurrentText = Text;
    bCurrentGamepad = bGamepad;
    bHintRequested = !Text.IsEmpty();
    LoadPresentationAssets();
    if (bChanged || GetVisibility() == ESlateVisibility::Collapsed) RefreshHint();
}

void USaskartaGameplayHintWidget::HideHint()
{
    bHintRequested = false;
    SetVisibility(ESlateVisibility::Collapsed);
}

void USaskartaGameplayHintWidget::NativeDestruct()
{
    HideHint();
    if (PresentationLoad.IsValid()) PresentationLoad->CancelHandle();
    PresentationLoad.Reset();
    Super::NativeDestruct();
}

void USaskartaGameplayHintWidget::AddCaption(const FString& Text, float LeftPadding, float RightPadding)
{
    if (bAuthoredLayout)
    {
        if (!bAuthoredBindingsValid || !AuthoredCaptions.IsValidIndex(NextCaption)) return;
        UTextBlock* Caption = AuthoredCaptions[NextCaption++];
        NextGlyph = 0;
        Caption->SetText(FText::FromString(Text));
        Caption->SetVisibility(ESlateVisibility::HitTestInvisible);
        if (UHorizontalBoxSlot* LayoutSlot = Cast<UHorizontalBoxSlot>(Caption->Slot))
            LayoutSlot->SetPadding(FMargin(LeftPadding, 0.f, RightPadding, 0.f));
        return;
    }
    UTextBlock* Caption = WidgetTree->ConstructWidget<UTextBlock>();
    Caption->SetText(FText::FromString(Text));
    FSlateFontInfo Font = FCoreStyle::GetDefaultFontStyle(TEXT("Regular"), 21);
    if (CaptionFont) Font = FSlateFontInfo(CaptionFont.Get(), 21);
    Caption->SetFont(Font);
    Caption->SetColorAndOpacity(FSlateColor(FLinearColor(0.94f, 0.91f, 0.81f, 1.f)));
    Caption->SetShadowColorAndOpacity(FLinearColor(0.f, 0.f, 0.f, 0.8f));
    Caption->SetShadowOffset(FVector2D(1.5f, 2.f));
    Caption->SetJustification(ETextJustify::Center);
    Caption->SetWrapTextAt(700.f);
    UHorizontalBoxSlot* LayoutSlot = HintRow->AddChildToHorizontalBox(Caption);
    LayoutSlot->SetVerticalAlignment(VAlign_Center);
    LayoutSlot->SetPadding(FMargin(LeftPadding, 0.f, RightPadding, 0.f));
}

void USaskartaGameplayHintWidget::AddGlyph(FName Glyph, const TCHAR* Fallback, float Width)
{
    TObjectPtr<UTexture2D>* Found = GlyphTextures.Find(Glyph);
    if (!Found || !*Found)
    {
        AddCaption(Fallback, 2.f, 2.f);
        return;
    }
    if (bAuthoredLayout)
    {
        const int32 SlotIndex = NextCaption * 2 + NextGlyph;
        if (!bAuthoredBindingsValid || NextGlyph >= 2 || !AuthoredGlyphs.IsValidIndex(SlotIndex)) return;
        ++NextGlyph;
        UImage* Icon = AuthoredGlyphs[SlotIndex];
        USizeBox* Bounds = AuthoredGlyphBounds[SlotIndex];
        Bounds->SetWidthOverride(Width);
        Bounds->SetVisibility(ESlateVisibility::HitTestInvisible);
        Icon->SetBrushFromTexture(*Found, false);
        return;
    }
    USizeBox* Bounds = WidgetTree->ConstructWidget<USizeBox>();
    Bounds->SetWidthOverride(Width);
    Bounds->SetHeightOverride(38.f);
    UImage* Icon = WidgetTree->ConstructWidget<UImage>();
    Icon->SetBrushFromTexture(*Found, false);
    Bounds->AddChild(Icon);
    UHorizontalBoxSlot* LayoutSlot = HintRow->AddChildToHorizontalBox(Bounds);
    LayoutSlot->SetVerticalAlignment(VAlign_Center);
    LayoutSlot->SetPadding(FMargin(2.f, 0.f));
}

void USaskartaGameplayHintWidget::RefreshHint()
{
    if (!HintRow || (bAuthoredLayout && !bAuthoredBindingsValid)) return;
    NextGlyph = 0;
    NextCaption = 0;
    if (bAuthoredLayout)
    {
        for (USizeBox* Bounds : AuthoredGlyphBounds) Bounds->SetVisibility(ESlateVisibility::Collapsed);
        for (UTextBlock* Caption : AuthoredCaptions) Caption->SetVisibility(ESlateVisibility::Collapsed);
    }
    else HintRow->ClearChildren();
    if (!bHintRequested)
    {
        SetVisibility(ESlateVisibility::Collapsed);
        return;
    }
    if (CurrentId == TEXT("drive"))
    {
        if (bCurrentGamepad)
        {
            AddGlyph(TEXT("Pad_LStick"), TEXT("LS"));
            AddCaption(TEXT("DRIVE / STEER"));
            AddGlyph(TEXT("Pad_RStick"), TEXT("RS"));
        }
        else
        {
            AddGlyph(TEXT("Key_W"), TEXT("W"));
            AddGlyph(TEXT("Key_S"), TEXT("S"));
            AddCaption(TEXT("DRIVE"));
            AddGlyph(TEXT("Key_A"), TEXT("A"));
            AddGlyph(TEXT("Key_D"), TEXT("D"));
            AddCaption(TEXT("STEER"));
            AddGlyph(TEXT("Mouse_Move"), TEXT("MOUSE"));
        }
        AddCaption(TEXT("LOOK"), 8.f, 0.f);
    }
    else if (CurrentId == TEXT("radio"))
    {
        AddGlyph(bCurrentGamepad ? TEXT("Pad_DPad_Up") : TEXT("Key_R"), bCurrentGamepad ? TEXT("D-PAD UP") : TEXT("R"));
        AddCaption(TEXT("RADIO"), 8.f, 0.f);
    }
    else if (CurrentId == TEXT("lamps"))
    {
        // The shipped prompt set has F9, but no F. Keep the real control as unboxed text.
        if (bCurrentGamepad) AddGlyph(TEXT("Pad_RStick"), TEXT("RS"));
        AddCaption(bCurrentGamepad ? TEXT("CLICK . LAMPS") : TEXT("F . LAMPS"), 8.f, 0.f);
    }
    else if (CurrentId == TEXT("boost") || CurrentId == TEXT("turbo"))
    {
        AddGlyph(bCurrentGamepad ? TEXT("Pad_RT") : TEXT("Key_Shift"), bCurrentGamepad ? TEXT("RT") : TEXT("SHIFT"), 50.f);
        AddCaption(CurrentText, 8.f, 0.f);
    }
    else if (CurrentId == TEXT("motor_tuning"))
    {
        AddGlyph(bCurrentGamepad ? TEXT("Pad_View") : TEXT("Key_Tab"), bCurrentGamepad ? TEXT("VIEW") : TEXT("TAB"), 48.f);
        AddCaption(TEXT("TUNE MOTOR"), 8.f, 0.f);
    }
    else if (CurrentId == TEXT("radio_repair"))
    {
        if (bCurrentGamepad) AddGlyph(TEXT("Pad_Y"), TEXT("Y"), 42.f);
        else AddCaption(TEXT("T"), 0.f, 10.f);
        AddCaption(TEXT("ADJUST THE AERIAL"), 8.f, 0.f);
    }
    else AddCaption(CurrentText, 0.f, 0.f);
    SetVisibility(ESlateVisibility::HitTestInvisible);
}
