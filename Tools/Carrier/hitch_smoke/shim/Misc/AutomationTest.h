// Shim for the offline hitch smoke: IMPLEMENT_SIMPLE_AUTOMATION_TEST registers a plain test.
#pragma once
#include "CoreMinimal.h"
#include <functional>

#define WITH_DEV_AUTOMATION_TESTS 1
namespace EAutomationTestFlags { enum { EditorContext = 1, EngineFilter = 2 }; }

struct FSmokeTest
{
    const char* Name = "";
    int Failures = 0;
    void Fail(const FString& What) { ++Failures; std::printf("  FAIL %s: %s\n", Name, *What); }
    void TestTrue(const FString& What, bool b) { if (!b) Fail(What); }
    void TestFalse(const FString& What, bool b) { if (b) Fail(What); }
    void TestEqual(const FString& What, float A, float B, float Tol = 1.e-4f)
    {
        if (!(std::fabs(A - B) <= Tol)) Fail(FString::Printf("%s (%.6f vs %.6f)", *What, A, B));
    }
    virtual bool RunTest(const FString&) = 0;
    virtual ~FSmokeTest() = default;
};

inline std::vector<std::function<FSmokeTest*()>>& SmokeRegistry() { static std::vector<std::function<FSmokeTest*()>> R; return R; }

#define IMPLEMENT_SIMPLE_AUTOMATION_TEST(Class, TestName, Flags) \
    struct Class : FSmokeTest { Class() { Name = TestName; } bool RunTest(const FString&) override; }; \
    static const bool Class##Registered = (SmokeRegistry().push_back([] { return static_cast<FSmokeTest*>(new Class()); }), true);
