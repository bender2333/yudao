# 把各组审查员写下的 JSON 合并成报告用的明细表。
# 每组一个 JSON：<Dir>/<组号>.json，内容为数组，每项
# { "file": "docs/design/x.md", "line": 12, "kind": "冲突|不一致|失效引用|含糊",
#   "counterpart": "对照的正本位置", "why": "一句话矛盾点", "fix": "改法",
#   "quote": "原文片段", "confidence": "高|中|低" }
# 组号取文件名（g11.json → g11）。字段名大小写不敏感，G 缺失时用文件名。
# 有 <Dir>/titles.json（{"g11":"需求一", ...}）时用它做分组标题。
param(
    [string]$Dir = (Join-Path (Get-Location).Path '.tmp\doc-scan'),
    [string]$Out = '',
    [string]$Csv = ''
)

function Get-Field($obj, [string]$name) {
    $p = $obj.PSObject.Properties | Where-Object { $_.Name -eq $name } | Select-Object -First 1
    if ($p) { return [string]$p.Value }
    return ''
}

$titles = @{}
$titlesPath = Join-Path $Dir 'titles.json'
if (Test-Path -LiteralPath $titlesPath) {
    $o = Get-Content -LiteralPath $titlesPath -Raw -Encoding UTF8 | ConvertFrom-Json
    foreach ($p in $o.PSObject.Properties) { $titles[$p.Name] = [string]$p.Value }
}

$all = New-Object System.Collections.Generic.List[object]
$problems = New-Object System.Collections.Generic.List[string]

foreach ($f in (Get-ChildItem -LiteralPath $Dir -File -Filter *.json | Where-Object { $_.BaseName -ne 'titles' } | Sort-Object Name)) {
    $raw = Get-Content -LiteralPath $f.FullName -Raw -Encoding UTF8
    try { $data = $raw | ConvertFrom-Json } catch { $problems.Add("$($f.Name)：不是合法 JSON"); continue }
    if ($data.PSObject.Properties.Name -contains 'findings') { $data = $data.findings }
    $n = 0
    foreach ($r in @($data)) {
        $n++
        $file = Get-Field $r 'file'
        $why = Get-Field $r 'why'
        if (-not $file -or -not $why) { $problems.Add("$($f.Name) 第 $n 条缺 file 或 why"); continue }
        $g = Get-Field $r 'g'
        if (-not $g) { $g = $f.BaseName }
        $all.Add([pscustomobject]@{
                G           = $g
                Kind        = Get-Field $r 'kind'
                Conf        = Get-Field $r 'confidence'
                File        = $file
                Line        = Get-Field $r 'line'
                Counterpart = Get-Field $r 'counterpart'
                Why         = $why
                Fix         = Get-Field $r 'fix'
                Quote       = Get-Field $r 'quote'
            })
    }
}

"合并 $($all.Count) 条"
if ($problems.Count) { "有问题的条目 $($problems.Count) 条："; $problems | Select-Object -First 20 | ForEach-Object { "  $_" } }

$byKind = $all | Group-Object Kind | Sort-Object Count -Descending
"类别：" + (($byKind | ForEach-Object { "$($_.Name) $($_.Count)" }) -join '，')

if ($Csv) { $all | Export-Csv -LiteralPath $Csv -NoTypeInformation -Encoding UTF8; "写盘 $Csv" }

if ($Out) {
    $sb = New-Object System.Text.StringBuilder
    [void]$sb.AppendLine("共 $($all.Count) 条。类别：" + (($byKind | ForEach-Object { "$($_.Name) $($_.Count)" }) -join '，') + "。")
    foreach ($g in ($all | Group-Object G | Sort-Object Name)) {
        $title = if ($titles.ContainsKey($g.Name)) { $titles[$g.Name] } else { '' }
        [void]$sb.AppendLine("")
        [void]$sb.AppendLine("### 组 $($g.Name) $title（$($g.Count) 条）")
        [void]$sb.AppendLine("")
        [void]$sb.AppendLine("| 位置 | 类别 | 矛盾点 | 改法 |")
        [void]$sb.AppendLine("| --- | --- | --- | --- |")
        foreach ($r in $g.Group) {
            $loc = if ($r.Line) { "$($r.File):$($r.Line)" } else { $r.File }
            $cp = if ($r.Counterpart) { "（对照 $($r.Counterpart)）" } else { '' }
            $why = ($r.Why + $cp) -replace '\|', '\|'
            $fix = $r.Fix -replace '\|', '\|'
            [void]$sb.AppendLine("| $loc | $($r.Kind) | $why | $fix |")
        }
    }
    Set-Content -LiteralPath $Out -Value $sb.ToString() -Encoding UTF8
    "写盘 $Out"
}
