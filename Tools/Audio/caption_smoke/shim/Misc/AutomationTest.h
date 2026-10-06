// Shim for the offline caption smoke: IMPLEMENT_SIMPLE_AUTOMATION_TEST registers a plain test.
#pragma once
#include "CoreMinimal.h"
#include <functional>

#define WITH_DEV_AUTOMATION_TESTS 1
namespace EAutomationTestFlags { enum { EditorContext = 1, EngineFilter = 2 }; }

struct FSmokeTest
{
    const char* Name = "";
    int Failures = 0;
    void Fail(const TCHAR* What, const std::wstring& Detail = L"") { ++Failures; std::wprintf(L"  FAIL %hs: %ls %ls\n", Name, What, Detail.c_str()); }
    void TestTrue(const TCHAR* What, bool b) { if (!b) Fail(What); }
    void TestFalse(const TCHAR* What, bool b) { if (b) Fail(What); }
    void TestEqual(const TCHAR* What, int32 A, int32 B) { if (A != B) Fail(What, std::to_wstring(A) + L" vs " + std::to_wstring(B)); }
    void TestEqual(const TCHAR* What, float A, float B, float Tol = 1.e-4f) { if (!(std::fabs(A - B) <= Tol)) Fail(What, std::to_wstring(A) + L" vs " + std::to_wstring(B)); }
    void TestEqual(const TCHAR* What, const FString& A, const FString& B) { if (A != B) Fail(What, L"'" + A.S + L"' vs '" + B.S + L"'"); }
    virtual bool RunTest(const FString&) = 0;
    virtual ~FSmokeTest() = default;
};

inline std::vector<std::function<FSmokeTest*()>>& SmokeRegistry() { static std::vector<std::function<FSmokeTest*()>> R; return R; }

#define IMPLEMENT_SIMPLE_AUTOMATION_TEST(Class, TestName, Flags) \
    struct Class : FSmokeTest { Class() { Name = TestName; } bool RunTest(const FString&) override; }; \
    static const bool Class##Registered = (SmokeRegistry().push_back([] { return static_cast<FSmokeTest*>(new Class()); }), true);
