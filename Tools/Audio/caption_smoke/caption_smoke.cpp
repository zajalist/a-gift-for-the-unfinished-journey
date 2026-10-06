// Offline check of the caption pages (no engine, no editor): compiles the REAL SaskartaCaptionPaging.cpp and the
// REAL automation tests (Saskarta.Captions.*) against a small shim, and runs them. From the repo root, in an x64
// Native Tools prompt:
//   cl /nologo /EHsc /std:c++17 /utf-8 /I Tools/Audio/caption_smoke/shim /I Plugins/SaskartaCore/Source/SaskartaCore/Public Tools/Audio/caption_smoke/caption_smoke.cpp /Fo:Saved/ /Fe:Saved/caption_smoke.exe
//   Saved\caption_smoke.exe
#include "../../../Plugins/SaskartaCore/Source/SaskartaCore/Private/SaskartaCaptionPaging.cpp"
#include "../../../Plugins/SaskartaCore/Source/SaskartaCore/Private/Tests/SaskartaCaptionPagingTest.cpp"

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
