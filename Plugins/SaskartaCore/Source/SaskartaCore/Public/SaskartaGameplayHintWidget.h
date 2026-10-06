#pragma once

#include "CoreMinimal.h"
#include "Blueprint/UserWidget.h"
#include "SaskartaGameplayHintWidget.generated.h"

class UFont;
class UHorizontalBox;
class UImage;
class USizeBox;
class UTextBlock;
class UTexture2D;
struct FStreamableHandle;

/** A small, non-interactive gameplay caption using the existing Light control glyphs. */
UCLASS()
class SASKARTACORE_API USaskartaGameplayHintWidget : public UUserWidget
{
    GENERATED_BODY()

public:
    void ShowHint(FName Id, const FString& Text, bool bGamepad);
    void HideHint();

protected:
    virtual void NativeOnInitialized() override;
    virtual void NativeDestruct() override;

private:
    void LoadPresentationAssets();
    void RefreshHint();
    void AddGlyph(FName Glyph, const TCHAR* Fallback, float Width = 38.f);
    void AddCaption(const FString& Text, float LeftPadding = 8.f, float RightPadding = 22.f);

    UPROPERTY(Transient)
    TObjectPtr<UHorizontalBox> HintRow;

    UPROPERTY(Transient) TArray<TObjectPtr<UImage>> AuthoredGlyphs;
    UPROPERTY(Transient) TArray<TObjectPtr<USizeBox>> AuthoredGlyphBounds;
    UPROPERTY(Transient) TArray<TObjectPtr<UTextBlock>> AuthoredCaptions;
    bool bAuthoredLayout = false;
    bool bAuthoredBindingsValid = false;
    int32 NextGlyph = 0;
    int32 NextCaption = 0;

    UPROPERTY(Transient)
    TObjectPtr<UFont> CaptionFont;

    UPROPERTY(Transient)
    TMap<FName, TObjectPtr<UTexture2D>> GlyphTextures;

    TSharedPtr<FStreamableHandle> PresentationLoad;
    FName CurrentId;
    FString CurrentText;
    bool bCurrentGamepad = false;
    bool bHintRequested = false;
};
