// Offline check of the carrier hitch math (no engine, no editor): compiles the REAL
// SaskartaCarrierMath.cpp and the REAL automation tests (Saskarta.Carrier.*) against a
// small shim, and runs them. From the repo root, in an x64 Native Tools prompt:
//   cl /nologo /EHsc /std:c++17 /utf-8 /I Tools/Carrier/hitch_smoke/shim /I Plugins/SaskartaCore/Source/SaskartaCore/Public Tools/Carrier/hitch_smoke/hitch_smoke.cpp /Fe:Saved/hitch_smoke.exe
//   Saved\hitch_smoke.exe
#include "../../../Plugins/SaskartaCore/Source/SaskartaCore/Private/SaskartaCarrierMath.cpp"
#include "../../../Plugins/SaskartaCore/Source/SaskartaCore/Private/Tests/SaskartaCarrierMathTest.cpp"

int main()
{
    int Failed = 0;
    for (auto& Make : SmokeRegistry())
    {
        FSmokeTest* T = Make();
        T->RunTest(FString());
        std::printf("%s %s\n", T->Failures ? "FAIL" : "ok  ", T->Name);
        Failed += T->Failures ? 1 : 0;
        delete T;
    }
    std::printf("%d failed\n", Failed);
    return Failed ? 1 : 0;
}
