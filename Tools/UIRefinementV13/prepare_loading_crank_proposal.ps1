$ErrorActionPreference = 'Stop'
$projectRoot = 'D:\UnrealEngine\saskartarad'
$proposalRoot = Join-Path $projectRoot 'Tools\UIRefinementV13\loading_crank_native'
New-Item -ItemType Directory -Force -Path $proposalRoot | Out-Null
function Replace-Exact([string]$source, [string]$old, [string]$new) {
    $old = $old.Replace("`r`n", "`n")
    $new = $new.Replace("`r`n", "`n")
    if (-not $source.Contains($old)) { throw "Proposal anchor absent: $($old.Substring(0, [Math]::Min(70, $old.Length)))" }
    return $source.Replace($old, $new)
}
$headerPath = Join-Path $projectRoot 'Plugins\SaskartaCore\Source\SaskartaCore\Public\SaskartaMotorResonance.h'
$sourcePath = Join-Path $projectRoot 'Plugins\SaskartaCore\Source\SaskartaCore\Private\SaskartaMotorDiagram.cpp'
$header = [IO.File]::ReadAllText($headerPath).Replace("`r`n", "`n")
$source = [IO.File]::ReadAllText($sourcePath).Replace("`r`n", "`n")
$header = Replace-Exact $header @'
    void Configure(UObject* Font);
'@ @'
    /** Set before RebuildWidget so loading never flashes gameplay instructions. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Saskarta|Motor")
    bool bLoadingPresentation = false;

    /** Smoothed readiness only; no gameplay clock, input or automatic advancement. */
    UFUNCTION(BlueprintCallable, Category="Saskarta|Loading")
    void PresentLoading(float Readiness);

    void Configure(UObject* Font);
'@
$header = Replace-Exact $header @'
    float ChargePercent = 0.f;
'@ @'
    float LoadingReadiness = 0.f;
    float ChargePercent = 0.f;
'@
$source = Replace-Exact $source @'
        Font = InFont;
        Core = InLogic;
'@ @'
        const bool bWasLoading = bLoading;
        bLoading = false;
        if (bWasLoading) Invalidate(EInvalidateWidgetReason::Layout);
        Font = InFont;
        Core = InLogic;
'@
$source = Replace-Exact $source @'
    virtual FVector2D ComputeDesiredSize(float) const override
    {
        return FVector2D(SaskartaMotorScreen::Width, SaskartaMotorScreen::Height);
    }
'@ @'
    void SetLoading(float InReadiness)
    {
        const float SafeReadiness = FMath::IsFinite(InReadiness) ? FMath::Clamp(InReadiness, 0.f, 1.f) : 0.f;
        if (bLoading && LoadingFraction == SafeReadiness) return;
        const bool bWasLoading = bLoading;
        bLoading = true;
        LoadingFraction = SafeReadiness;
        Invalidate(bWasLoading ? EInvalidateWidgetReason::Paint : EInvalidateWidgetReason::Layout);
    }
    virtual FVector2D ComputeDesiredSize(float) const override
    {
        return FVector2D(SaskartaMotorScreen::Width, bLoading ? 164.f : SaskartaMotorScreen::Height);
    }
'@
$source = Replace-Exact $source @'
        Text(24, 12, Core.IsTuning() ? TEXT("BIOFUEL / CHARGING") : TEXT("BIOFUEL / RESONANCE"), 24);
'@ @'
        // Loading and charging share the exact crank rings, spokes, pin and top mark.
        const auto DrawCrank = [&](FVector2D Wheel, float WheelAngle)
        {
            Arc(Wheel, 67, 0, 2*PI, 0.3f, 2.f);
            Arc(Wheel, 61, 0, 2*PI, 0.56f, 2.f);
            for (int32 I = 0; I < 6; ++I)
            {
                const float Angle = WheelAngle + I * PI / 3.f;
                const FVector2D Direction(FMath::Cos(Angle), FMath::Sin(Angle));
                Line({Wheel+Direction*25.f,Wheel+Direction*54.f}, 0.45f, 2.f);
            }
            const FVector2D Tip = Wheel + FVector2D(FMath::Cos(WheelAngle), FMath::Sin(WheelAngle)) * 61.f;
            Arc(Tip, 5, 0, 2*PI, 1.f, 3.f);
            Line({Wheel+FVector2D(0,-83),Wheel+FVector2D(0,-73)}, 1.f, 3.f);
        };
        if (bLoading)
        {
            // This phase can stop and reverse with readiness; time cannot fill the line.
            const FVector2D Wheel(92.f, 83.f);
            DrawCrank(Wheel, LoadingFraction * 1.75f * 2.f * PI - PI * 0.5f);
            Arc(Wheel, 24, 0, 2*PI, 0.6f, 2.f);
            if (LoadingFraction > 0.f)
                Arc(Wheel, 70, -PI*0.5f, -PI*0.5f + LoadingFraction*2.f*PI, 0.9f, 3.f);
            Box(184, 81, 512, 4, 0.16f);
            Box(184, 81, 512*LoadingFraction, 4, 0.9f);
            return Layer;
        }

        Text(24, 12, Core.IsTuning() ? TEXT("BIOFUEL / CHARGING") : TEXT("BIOFUEL / RESONANCE"), 24);
'@
$source = Replace-Exact $source @'
        Arc(Wheel, 67, 0, 2*PI, 0.3f, 2.f);
        Arc(Wheel, 61, 0, 2*PI, 0.56f, 2.f);
        Arc(Wheel, 70, -PI*.5f-Window, -PI*.5f+Window, Core.BeatWindowOpen() ? 1.f : 0.6f, 5.f);
        for (int32 I = 0; I < 6; ++I)
        {
            const float Angle = WheelAngle + I * PI / 3.f;
            const FVector2D Direction(FMath::Cos(Angle), FMath::Sin(Angle));
            Line({Wheel+Direction*25.f,Wheel+Direction*54.f}, 0.45f, 2.f);
        }
        const FVector2D Tip = Wheel + FVector2D(FMath::Cos(WheelAngle), FMath::Sin(WheelAngle)) * 61.f;
        Arc(Tip, 5, 0, 2*PI, 1.f, 3.f);
        Line({{358,91},{358,101}}, 1.f, 3.f);
'@ @'
        DrawCrank(Wheel, WheelAngle);
        Arc(Wheel, 70, -PI*.5f-Window, -PI*.5f+Window, Core.BeatWindowOpen() ? 1.f : 0.6f, 5.f);
'@
$source = Replace-Exact $source @'
    float Charge = 0.f;
'@ @'
    bool bLoading = false;
    float LoadingFraction = 0.f;
    float Charge = 0.f;
'@
$source = Replace-Exact $source @'
    Frame = Logic;
'@ @'
    bLoadingPresentation = false;
    Frame = Logic;
'@
$source = Replace-Exact $source @'
TSharedRef<SWidget> USaskartaMotorDiagram::RebuildWidget()
'@ @'
void USaskartaMotorDiagram::PresentLoading(float Readiness)
{
    bLoadingPresentation = true;
    LoadingReadiness = FMath::IsFinite(Readiness) ? FMath::Clamp(Readiness, 0.f, 1.f) : 0.f;
    if (Diagram) Diagram->SetLoading(LoadingReadiness);
}

TSharedRef<SWidget> USaskartaMotorDiagram::RebuildWidget()
'@
$source = Replace-Exact $source @'
    Diagram->SetGlyphs(GlyphTextures);
    Diagram->SetFrame(FontObject, Frame, bPad, ChargePercent, DustGapM, bShowCharge);
'@ @'
    Diagram->SetGlyphs(GlyphTextures);
    if (bLoadingPresentation) Diagram->SetLoading(LoadingReadiness);
    else Diagram->SetFrame(FontObject, Frame, bPad, ChargePercent, DustGapM, bShowCharge);
'@
[IO.File]::WriteAllText((Join-Path $proposalRoot 'SaskartaMotorResonance.h.proposed'), $header)
[IO.File]::WriteAllText((Join-Path $proposalRoot 'SaskartaMotorDiagram.cpp.proposed'), $source)
$hashes = [ordered]@{ status='proposed_not_installed'; source_header_sha256=(Get-FileHash -LiteralPath $headerPath -Algorithm SHA256).Hash; source_cpp_sha256=(Get-FileHash -LiteralPath $sourcePath -Algorithm SHA256).Hash }
$hashes | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $proposalRoot 'base_hashes.json') -Encoding utf8
Write-Output 'Prepared native proposal copies only.'
