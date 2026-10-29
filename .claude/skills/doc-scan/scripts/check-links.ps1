# 全仓链接可解析性核对。
# 逐个解析 md 的 [文字](目标) 与 html 的 href/src，跳过 http、mailto、页内锚点，
# 其余按「相对当前文件」解析后 Test-Path。输出 Markdown 表：文件:行、链接目标、是否越界到 archive。
param(
    [string]$Root = (Get-Location).Path,
    [string[]]$Exclude = @('.venv/', 'node_modules/', '.tmp/', '.claude/worktrees/', 'docs/archive/', '.ralph/', '.yudao/'),
    [string]$Out = '',
    [int]$MaxPerFile = 40
)

$files = Get-ChildItem -LiteralPath $Root -Recurse -File -Include *.md, *.html -ErrorAction SilentlyContinue |
    Where-Object {
        $rel = $_.FullName.Substring($Root.Length).Replace('\', '/')
        -not ($Exclude | Where-Object { $rel.Contains($_) })
    }

$rows = New-Object System.Collections.Generic.List[object]
foreach ($f in $files) {
    $text = Get-Content -LiteralPath $f.FullName -Raw -Encoding UTF8
    if (-not $text) { continue }
    $lines = $text -split "`r?`n"
    $hits = 0
    for ($i = 0; $i -lt $lines.Count; $i++) {
        $line = $lines[$i]
        $targets = @()
        foreach ($m in [regex]::Matches($line, '\[[^\]]*\]\(([^)\s]+)')) { $targets += $m.Groups[1].Value }
        foreach ($m in [regex]::Matches($line, '(?:href|src)="([^"]+)"')) { $targets += $m.Groups[1].Value }
        foreach ($t in $targets) {
            $t = $t.Trim()
            if ($t -match '^(https?:|mailto:|#|data:|javascript:)') { continue }
            if ($t -match '[{}$<>]') { continue }
            $clean = ($t -split '#')[0]
            if (-not $clean) { continue }
            $clean = [uri]::UnescapeDataString($clean)
            $full = if ($clean.StartsWith('/')) { Join-Path $Root $clean.TrimStart('/') } else { Join-Path (Split-Path $f.FullName) $clean }
            if (Test-Path -LiteralPath $full) { continue }
            $hits++
            if ($hits -gt $MaxPerFile) { break }
            $rows.Add([pscustomobject]@{
                    File   = $f.FullName.Substring($Root.Length).Replace('\', '/')
                    Line   = $i + 1
                    Target = $clean
                    ArchivedRef = if ($clean -match 'archive|current-baseline|user-session-log|stage-3-plan') { 'yes' } else { '' }
                })
        }
    }
}

"文件数 $($files.Count)，失效链接 $($rows.Count)"

if ($Out) {
    $md = New-Object System.Text.StringBuilder
    [void]$md.AppendLine("| 位置 | 目标 | 疑似归档引用 |")
    [void]$md.AppendLine("| --- | --- | --- |")
    foreach ($r in $rows) { [void]$md.AppendLine("| $($r.File):$($r.Line) | ``$($r.Target)`` | $($r.ArchivedRef) |") }
    Set-Content -LiteralPath $Out -Value $md.ToString() -Encoding UTF8
    "写盘 $Out"
}
else {
    $rows | Group-Object File | Sort-Object Count -Descending | Select-Object -First 20 |
        ForEach-Object { "$($_.Count) 处  $($_.Name)" }
}
