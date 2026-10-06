$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
$taskRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../../..'))
$outputPath = Join-Path $taskRoot 'Saved/Verification/ui_refinement_v13/loading_crank_refinement_v17/crank_preview.png'
$bitmap = [System.Drawing.Bitmap]::new(800, 430)
$drawing = [System.Drawing.Graphics]::FromImage($bitmap)
$drawing.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
$drawing.Clear([System.Drawing.Color]::FromArgb(8, 9, 7))
$pi = [Math]::PI
function Get-Amber([double]$brightness) {
    [System.Drawing.Color]::FromArgb(255, [int](255*$brightness), [int](255*$brightness*0.76), [int](255*$brightness*0.46))
}
function Draw-Segment([double]$x1, [double]$y1, [double]$x2, [double]$y2, [double]$brightness, [double]$width) {
    $pen = [System.Drawing.Pen]::new((Get-Amber $brightness), [single]$width)
    try { $drawing.DrawLine($pen, [single]$x1, [single]$y1, [single]$x2, [single]$y2) } finally { $pen.Dispose() }
}
function Draw-Arc([double]$x, [double]$y, [double]$radius, [double]$start, [double]$end, [double]$brightness, [double]$width) {
    $count = [Math]::Max(2, [Math]::Ceiling([Math]::Abs($end-$start)*9))
    $lastX = $x+[Math]::Cos($start)*$radius
    $lastY = $y+[Math]::Sin($start)*$radius
    for ($i = 1; $i -le $count; $i++) {
        $angle = $start+($end-$start)*$i/$count
        $nextX = $x+[Math]::Cos($angle)*$radius
        $nextY = $y+[Math]::Sin($angle)*$radius
        Draw-Segment $lastX $lastY $nextX $nextY $brightness $width
        $lastX = $nextX; $lastY = $nextY
    }
}
function Draw-Crank([double]$x, [double]$y, [double]$angle, [double]$hubBrightness) {
    Draw-Arc $x $y 67 0 (2*$pi) 0.3 2
    Draw-Arc $x $y 61 0 (2*$pi) 0.56 2
    for ($i = 0; $i -lt 6; $i++) {
        $a = $angle+$i*$pi/3
        $dx = [Math]::Cos($a); $dy = [Math]::Sin($a)
        Draw-Segment ($x+$dx*24) ($y+$dy*24) ($x+$dx*61) ($y+$dy*61) 0.45 2
    }
    Draw-Arc $x $y 24 0 (2*$pi) $hubBrightness 2
    $dx = [Math]::Cos($angle); $dy = [Math]::Sin($angle)
    $tx = -$dy; $ty = $dx
    $px = $x+$dx*51; $py = $y+$dy*51
    Draw-Segment ($x+$dx*24) ($y+$dy*24) $px $py 0.9 3
    Draw-Segment ($px-$tx*8-$dx*4) ($py-$ty*8-$dy*4) ($px+$tx*8-$dx*4) ($py+$ty*8-$dy*4) 1 2
    Draw-Segment ($px-$tx*8+$dx*4) ($py-$ty*8+$dy*4) ($px+$tx*8+$dx*4) ($py+$ty*8+$dy*4) 1 2
    Draw-Arc ($px+$tx*8) ($py+$ty*8) 4 $angle ($angle+$pi) 1 2
    Draw-Arc ($px-$tx*8) ($py-$ty*8) 4 ($angle+$pi) ($angle+2*$pi) 1 2
    Draw-Arc $px $py 2 0 (2*$pi) 1 1.5
    Draw-Segment $x ($y-74) $x ($y-67) 1 3
}
function Draw-Label([string]$value, [double]$x, [double]$y, [double]$size, [double]$brightness) {
    $font = [System.Drawing.Font]::new('Consolas', [single]$size, [System.Drawing.FontStyle]::Regular, [System.Drawing.GraphicsUnit]::Pixel)
    $brush = [System.Drawing.SolidBrush]::new((Get-Amber $brightness))
    try { $drawing.DrawString($value, $font, $brush, [single]$x, [single]$y) } finally { $brush.Dispose(); $font.Dispose() }
}
try {
    Draw-Label 'CONNECTED CRANK / PROPOSED NATIVE GEOMETRY' 24 16 16 0.75
    Draw-Crank 112 122 (-$pi/2) 1
    Draw-Arc 112 122 70 (-$pi/2-0.22) (-$pi/2+0.22) 1 5
    Draw-Label 'E' 104 108 24 1
    Draw-Label 'CHARGING / AT THE EXISTING TOP WINDOW' 204 97 16 0.85
    Draw-Label 'Attached marker, hub and spokes.' 204 127 14 0.56
    Draw-Label 'Radial arm, closed grip and spindle.' 204 151 14 0.56
    Draw-Label 'LOADING / SAME MECHANISM' 24 220 16 0.75
    $readiness = 0.65
    Draw-Crank 112 332 ($readiness*2*2*$pi-$pi/2) 0.6
    Draw-Arc 112 332 5 0 (2*$pi) 0.6 1.5
    Draw-Arc 112 332 70 (-$pi/2) (-$pi/2+$readiness*2*$pi) 0.9 3
    $track = [System.Drawing.SolidBrush]::new((Get-Amber 0.16))
    $fill = [System.Drawing.SolidBrush]::new((Get-Amber 0.9))
    try {
        $drawing.FillRectangle($track, [single]204, [single]330.5, [single]512, [single]3)
        $drawing.FillRectangle($fill, [single]204, [single]330.5, [single](512*$readiness), [single]3)
    } finally { $track.Dispose(); $fill.Dispose() }
    Draw-Label '65% READINESS / TWO TURNS, FINISHING AT THE TOP' 204 292 14 0.7
    Draw-Label 'CPU sketch: no font assets, phosphor or game compositing.' 204 367 12 0.45
    $bitmap.Save($outputPath, [System.Drawing.Imaging.ImageFormat]::Png)
    Write-Output $outputPath
} finally { $drawing.Dispose(); $bitmap.Dispose() }
