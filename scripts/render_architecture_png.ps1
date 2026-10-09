<#
Render reviewed synthetic diagram layouts on Windows without opening a window.
Run render_architecture_atlas.py first. PNGs contain no session or machine data.
Inspect every image and pin its exact hash in privacy_scan.py after approval.
#>
param()
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
$repoRoot = Split-Path $PSScriptRoot -Parent
$layouts = Get-Content -Raw (Join-Path $repoRoot 'docs/architecture/diagram-layouts.json') | ConvertFrom-Json
$ink = [System.Drawing.SolidBrush]::new([System.Drawing.ColorTranslator]::FromHtml('#172b46'))
$muted = [System.Drawing.SolidBrush]::new([System.Drawing.ColorTranslator]::FromHtml('#42556b'))
$titleFont = [System.Drawing.Font]::new('Arial', 25, [System.Drawing.FontStyle]::Bold, [System.Drawing.GraphicsUnit]::Pixel)
$labelFont = [System.Drawing.Font]::new('Arial', 23, [System.Drawing.FontStyle]::Regular, [System.Drawing.GraphicsUnit]::Pixel)
$smallFont = [System.Drawing.Font]::new('Arial', 16, [System.Drawing.FontStyle]::Regular, [System.Drawing.GraphicsUnit]::Pixel)
$tinyFont = [System.Drawing.Font]::new('Arial', 12, [System.Drawing.FontStyle]::Regular, [System.Drawing.GraphicsUnit]::Pixel)
try {
    foreach ($layout in $layouts) {
        if ($layout.slug -notmatch '^architecture-[a-z]+$') { throw 'diagram_name_invalid' }
        if ($layout.width -gt 4096 -or $layout.height -gt 4096) { throw 'diagram_dimension_limit' }
        $bitmap = [System.Drawing.Bitmap]::new([int]$layout.width,[int]$layout.height)
        $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
        try {
            $graphics.Clear([System.Drawing.ColorTranslator]::FromHtml('#f7f9fc'))
            $graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
            $graphics.TextRenderingHint = [System.Drawing.Text.TextRenderingHint]::AntiAliasGridFit
            $graphics.DrawString($layout.title,$titleFont,$ink,70,20)
            $graphics.DrawString('2026-10-08 | Development observation + published baseline | Evidence in catalog',$smallFont,$muted,70,60)
            $legend = @(@('READY (bounded)','#d4efdf'),@('PARTIAL','#fff0b3'),@('NOT IMPLEMENTED','#ffd8d8'),@('MOCK / DEMO','#e1e5ea'))
            for ($j=0; $j -lt $legend.Count; $j++) {
                $brush=[System.Drawing.SolidBrush]::new([System.Drawing.ColorTranslator]::FromHtml($legend[$j][1]))
                try { $graphics.FillRectangle($brush,70+$j*410,103,22,22) } finally { $brush.Dispose() }
                $graphics.DrawString($legend[$j][0],$smallFont,$ink,102+$j*410,104)
            }
            foreach ($edge in $layout.edges) {
                $pen=[System.Drawing.Pen]::new([System.Drawing.ColorTranslator]::FromHtml('#8493a5'),2)
                $cap=[System.Drawing.Drawing2D.AdjustableArrowCap]::new(4,5)
                try {
                    $pen.CustomEndCap=$cap
                    if ($edge.dashed) { $pen.DashStyle=[System.Drawing.Drawing2D.DashStyle]::Dash }
                    $points=[System.Drawing.PointF[]]@($edge.points | ForEach-Object { [System.Drawing.PointF]::new([single]$_[0],[single]$_[1]) })
                    $graphics.DrawLines($pen,$points)
                } finally { $pen.Dispose(); $cap.Dispose() }
            }
            foreach ($card in $layout.cards) {
                $brush=[System.Drawing.SolidBrush]::new([System.Drawing.ColorTranslator]::FromHtml($card.color))
                $pen=[System.Drawing.Pen]::new([System.Drawing.ColorTranslator]::FromHtml('#748398'),1)
                try {
                    $graphics.FillRectangle($brush,$card.x,$card.y,$card.w,$card.h)
                    $graphics.DrawRectangle($pen,$card.x,$card.y,$card.w,$card.h)
                } finally { $brush.Dispose(); $pen.Dispose() }
                for ($j=0; $j -lt $card.lines.Count; $j++) {
                    $font=if ($j -eq 0) { $smallFont } else { $labelFont }
                    $graphics.DrawString($card.lines[$j],$font,$ink,$card.x+18,$card.y+10+$j*29)
                }
                $graphics.DrawString($card.footer,$tinyFont,$muted,$card.x+18,$card.y+132)
            }
            $graphics.DrawString('Arrows = dependencies / data flow. Dashed = planned. Cross-page IDs in catalog. Colors do not certify beta.',$smallFont,$muted,70,$layout.height-43)
            $encoded=[System.IO.MemoryStream]::new()
            $clean=[System.IO.MemoryStream]::new()
            try {
                $bitmap.Save($encoded,[System.Drawing.Imaging.ImageFormat]::Png)
                $payload=$encoded.ToArray()
                $clean.Write($payload,0,8)
                $offset=8
                while ($offset -lt $payload.Length) {
                    $length=[int]$payload[$offset]*16777216+[int]$payload[$offset+1]*65536+[int]$payload[$offset+2]*256+[int]$payload[$offset+3]
                    $kind=[System.Text.Encoding]::ASCII.GetString($payload,$offset+4,4)
                    if ($kind -in @('IHDR','IDAT','IEND')) { $clean.Write($payload,$offset,$length+12) }
                    $offset+=$length+12
                }
                [System.IO.File]::WriteAllBytes((Join-Path $repoRoot ('docs/images/'+$layout.slug+'.png')),$clean.ToArray())
            } finally { $encoded.Dispose(); $clean.Dispose() }
        } finally { $graphics.Dispose(); $bitmap.Dispose() }
    }
} finally {
    $ink.Dispose(); $muted.Dispose(); $titleFont.Dispose(); $labelFont.Dispose(); $smallFont.Dispose(); $tinyFont.Dispose()
}
Write-Output ('Rendered '+$layouts.Count+' synthetic architecture diagrams.')
