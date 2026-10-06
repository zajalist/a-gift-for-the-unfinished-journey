#pragma once

#include "CoreMinimal.h"

namespace SaskartaPause
{
    enum class EAction : uint8 { Pass, Open, Toggle, Close, Swallow };

    inline bool IsPausableFlow(FName Flow)
    {
        static const FName Names[] = {
            TEXT("Playing"), TEXT("Carrier"), TEXT("Human"), TEXT("Collapsing"),
            TEXT("Rebooting"), TEXT("Booting"), TEXT("Transmit"), TEXT("End") };
        for (const FName Name : Names) if (Flow == Name) return true;
        return false;
    }

    inline EAction Decide(FName Flow, bool bMenuShown, bool bRepeat)
    {
        if (Flow == FName(TEXT("Paused")))
            return bRepeat ? EAction::Swallow : (bMenuShown ? EAction::Toggle : EAction::Close);
        if (!IsPausableFlow(Flow)) return EAction::Pass;
        return bRepeat || bMenuShown ? EAction::Swallow : EAction::Open;
    }
}
