// Minimal engine shim for the offline caption smoke (no engine). Only what SaskartaCaptionPaging.cpp and
// SaskartaCaptionPagingTest.cpp use: a wide FString, a vector TArray, FMath and FChar.
#pragma once
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cwctype>
#include <string>
#include <vector>

#define SASKARTACORE_API
#define TEXT(x) L##x
#define USTRUCT(...)
#define UPROPERTY(...)
#define GENERATED_BODY()
#define INDEX_NONE (-1)
using int32 = std::int32_t;
using TCHAR = wchar_t;

struct FChar
{
    static bool IsWhitespace(TCHAR C) { return std::iswspace(static_cast<wint_t>(C)) != 0; }
};

struct FMath
{
    template <typename T> static T Abs(T A) { return A < T(0) ? -A : A; }
    template <typename T> static T Max(T A, T B) { return A > B ? A : B; }
    template <typename T> static T Min(T A, T B) { return A < B ? A : B; }
    template <typename T> static T Clamp(T X, T Lo, T Hi) { return X < Lo ? Lo : (X > Hi ? Hi : X); }
};

struct FString
{
    std::wstring S;
    FString() = default;
    FString(const TCHAR* In) : S(In ? In : L"") {}
    int32 Len() const { return static_cast<int32>(S.size()); }
    bool IsEmpty() const { return S.empty(); }
    TCHAR operator[](int32 I) const { return S[static_cast<size_t>(I)]; }
    const TCHAR* operator*() const { return S.c_str(); }
    void Reserve(int32 N) { S.reserve(static_cast<size_t>(N)); }
    void Reset() { S.clear(); }
    void AppendChar(TCHAR C) { S.push_back(C); }
    FString Mid(int32 Start, int32 Count) const
    {
        if (Start < 0) Start = 0;
        if (Start >= Len() || Count <= 0) return FString();
        FString O; O.S = S.substr(static_cast<size_t>(Start), static_cast<size_t>(Count)); return O;
    }
    FString TrimStartAndEnd() const
    {
        size_t A = 0, B = S.size();
        while (A < B && std::iswspace(S[A])) ++A;
        while (B > A && std::iswspace(S[B - 1])) --B;
        FString O; O.S = S.substr(A, B - A); return O;
    }
    bool Contains(const TCHAR* Sub) const { return S.find(Sub) != std::wstring::npos; }
    FString& operator+=(const FString& O) { S += O.S; return *this; }
    FString& operator+=(const TCHAR* O) { S += O; return *this; }
    friend FString operator+(const FString& A, const FString& B) { FString O; O.S = A.S + B.S; return O; }
    friend FString operator+(const FString& A, const TCHAR* B) { FString O; O.S = A.S + B; return O; }
    friend FString operator+(const TCHAR* A, const FString& B) { FString O; O.S = A + B.S; return O; }
    bool operator==(const FString& O) const { return S == O.S; }
    bool operator!=(const FString& O) const { return S != O.S; }
};

template <typename T>
struct TArray
{
    std::vector<T> V;
    int32 Add(const T& X) { V.push_back(X); return static_cast<int32>(V.size()) - 1; }
    int32 Num() const { return static_cast<int32>(V.size()); }
    bool IsValidIndex(int32 I) const { return I >= 0 && I < Num(); }
    void Reset() { V.clear(); }
    T& operator[](int32 I) { return V[static_cast<size_t>(I)]; }
    const T& operator[](int32 I) const { return V[static_cast<size_t>(I)]; }
    template <typename P> void Sort(P Pred) { std::stable_sort(V.begin(), V.end(), Pred); }
    typename std::vector<T>::iterator begin() { return V.begin(); }
    typename std::vector<T>::iterator end() { return V.end(); }
    typename std::vector<T>::const_iterator begin() const { return V.begin(); }
    typename std::vector<T>::const_iterator end() const { return V.end(); }
};
