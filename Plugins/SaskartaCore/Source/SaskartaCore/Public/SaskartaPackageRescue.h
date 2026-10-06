#pragma once
#include "CoreMinimal.h"
#include "Blueprint/UserWidget.h"
#include "SaskartaPackageRescue.generated.h"

class UTextBlock;

/** Automatic CRT transfer between the lost carrier and its recovered package. */
UCLASS()
class SASKARTACORE_API USaskartaPackageRescueWidget : public UUserWidget
{
    GENERATED_BODY()
public:
    void SetSuccessful(bool bFuelRestored);
    void SetRecoveryFailed();
protected:
    virtual void NativeOnInitialized() override;
    virtual FReply NativeOnPreviewKeyDown(const FGeometry&, const FKeyEvent&) override { return FReply::Handled(); }
private:
    UPROPERTY(Transient) TObjectPtr<UTextBlock> Status;
    UPROPERTY(Transient) TObjectPtr<UTextBlock> Detail;
};
