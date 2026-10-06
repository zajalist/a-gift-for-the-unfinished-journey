// Minimal engine shim for the offline hitch smoke (no engine). Only what
// SaskartaCarrierMath.cpp and SaskartaCarrierMathTest.cpp use.
#pragma once
#include <algorithm>
#include <cmath>
#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <initializer_list>
#include <string>
#include <vector>

#define SASKARTACORE_API
#define TEXT(x) x
#define UE_PI 3.14159265358979323846f
#define UE_HALF_PI 1.57079632679489661923f
#define UE_KINDA_SMALL_NUMBER 1.e-4f
using int32 = std::int32_t;

struct FVector2D
{
    double X = 0.0, Y = 0.0;
    FVector2D() = default;
    FVector2D(double InX, double InY) : X(InX), Y(InY) {}
    FVector2D operator-(const FVector2D& O) const { return FVector2D(X - O.X, Y - O.Y); }
    bool operator==(const FVector2D& O) const { return X == O.X && Y == O.Y; }
};

template <typename T>
struct TArray
{
    std::vector<T> V;
    TArray() = default;
    TArray(std::initializer_list<T> L) : V(L) {}
    const T* GetData() const { return V.data(); }
    int32 Num() const { return static_cast<int32>(V.size()); }
    bool operator!=(const TArray& O) const { return V != O.V; }
};

struct FMath
{
    template <typename T> static T Abs(T A) { return A < T(0) ? -A : A; }
    template <typename T> static T Max(T A, T B) { return A > B ? A : B; }
    template <typename T> static T Min(T A, T B) { return A < B ? A : B; }
    template <typename T> static T Clamp(T X, T Lo, T Hi) { return X < Lo ? Lo : (X > Hi ? Hi : X); }
    static bool IsFinite(float A) { return std::isfinite(A); }
    static int32 CeilToInt(float A) { return static_cast<int32>(std::ceil(A)); }
    static int32 RoundToInt(float A) { return static_cast<int32>(std::floor(A + 0.5f)); }
    static float Sin(float A) { return std::sin(A); }
    static float Cos(float A) { return std::cos(A); }
    static double Sin(double A) { return std::sin(A); }
    static double Cos(double A) { return std::cos(A); }
    static float Asin(float A) { return std::asin(A); }
    static float Atan(float A) { return std::atan(A); }
    static float Atan2(float Y, float X) { return std::atan2(Y, X); }
    static float Sqrt(float A) { return std::sqrt(A); }
    static float Exp(float A) { return std::exp(A); }
    static float Fmod(float A, float B) { return std::fmod(A, B); }
    static float DegreesToRadians(float D) { return D * (UE_PI / 180.f); }
    static float RadiansToDegrees(float R) { return R * (180.f / UE_PI); }
};

struct FString
{
    std::string S;
    FString() = default;
    FString(const char* In) : S(In) {}
    static FString Printf(const char* Fmt, ...)
    {
        char Buf[512];
        va_list Args;
        va_start(Args, Fmt);
        std::vsnprintf(Buf, sizeof(Buf), Fmt, Args);
        va_end(Args);
        return FString(Buf);
    }
    const char* operator*() const { return S.c_str(); }
};
