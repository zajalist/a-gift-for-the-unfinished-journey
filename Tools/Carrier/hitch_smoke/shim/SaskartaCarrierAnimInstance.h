// Shim for the offline hitch smoke: FSaskartaCarrierAnimTuning's two footprints, read
// from the REAL header at start-up so the smoke checks the shipped numbers.
#pragma once
#define _CRT_SECURE_NO_WARNINGS
#include "CoreMinimal.h"
#include <fstream>
#include <sstream>

#ifndef SASKARTA_ANIM_HEADER
#define SASKARTA_ANIM_HEADER "Plugins/SaskartaCore/Source/SaskartaCore/Public/SaskartaCarrierAnimInstance.h"
#endif

inline TArray<FVector2D> SmokeReadFootprint(const char* Field)
{
    std::ifstream In(SASKARTA_ANIM_HEADER);
    std::stringstream Ss;
    Ss << In.rdbuf();
    const std::string Text = Ss.str();
    TArray<FVector2D> Out;
    const std::string Key = std::string(Field) + " = {";
    const size_t Start = Text.find(Key);
    if (Start == std::string::npos) { std::printf("  cannot find %s in %s\n", Field, SASKARTA_ANIM_HEADER); return Out; }
    const size_t End = Text.find("};", Start);
    size_t P = Start;
    while ((P = Text.find("FVector2D(", P)) != std::string::npos && P < End)
    {
        double X = 0, Y = 0;
        std::sscanf(Text.c_str() + P, "FVector2D(%lf, %lf)", &X, &Y);
        Out.V.push_back(FVector2D(X, Y));
        P += 10;
    }
    return Out;
}

struct FSaskartaCarrierAnimTuning
{
    TArray<FVector2D> CarrierFootprint = SmokeReadFootprint("CarrierFootprint");
    TArray<FVector2D> TrailerFootprint = SmokeReadFootprint("TrailerFootprint");
};
