#include "Misc/AutomationTest.h"

#if WITH_DEV_AUTOMATION_TESTS

#include "SaskartaMotorAssistLogic.h"

#define MOTOR_TEST_FLAGS (EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaMotorHillAssistTest, "Saskarta.Motor.AutomaticHillAssist",
    MOTOR_TEST_FLAGS)
bool FSaskartaMotorHillAssistTest::RunTest(const FString&)
{
    using F = FSaskartaMotorAssistLogic;
    constexpr float Dt = 1.f / 30.f;
    constexpr float FortyDegreeGrade = 0.8391f;
    F Assist;
    TestTrue(TEXT("walkable hill immediately owns the anti-stuck guard"),
        Assist.Step(0.f, true, true, 1.f, false, false, FortyDegreeGrade));
    TestEqual(TEXT("no press or immediate speed kick"), Assist.Amount, 0.f);
    for (int32 I = 0; I < 18; ++I) Assist.Step(Dt, true, true, 1.f, false, false, FortyDegreeGrade);
    const F::FLimits Limits = Assist.Apply(35.f, 225.f);
    TestTrue(TEXT("torque ramps fully in six tenths of a second"), FMath::IsNearlyEqual(Assist.Amount, 1.f));
    TestTrue(TEXT("acceleration bounded to base plus 180"), FMath::IsNearlyEqual(Limits.MaxAcceleration, 215.f));
    TestTrue(TEXT("useful climb speed ceiling"), FMath::IsNearlyEqual(Limits.MaxWalkSpeed, 380.f));
    TestEqual(TEXT("faster ordinary speed cap retained"), Assist.Apply(190.f, 520.f).MaxWalkSpeed, 520.f);
    TestFalse(TEXT("airborne has no assist"), F::CanAssist(true, false, 1.f, false, false, FortyDegreeGrade));
    TestFalse(TEXT("UI and cinematic locks have no assist"), F::CanAssist(false, true, 1.f, false, false, FortyDegreeGrade));
    TestFalse(TEXT("reverse has no assist"), F::CanAssist(true, true, 1.f, true, false, FortyDegreeGrade));
    TestFalse(TEXT("braking has no assist"), F::CanAssist(true, true, 1.f, false, true, FortyDegreeGrade));
    TestFalse(TEXT("flat has no assist"), F::CanAssist(true, true, 1.f, false, false, 0.f));
    TestFalse(TEXT("release throttle cancels immediately"), Assist.Step(Dt, true, true, 0.f, false, false, FortyDegreeGrade));
    TestEqual(TEXT("no residual torque"), Assist.Amount, 0.f);
    TestEqual(TEXT("normal cap restored by next base update"), Assist.Apply(35.f, 225.f).MaxWalkSpeed, 225.f);
    return true;
}

#endif
