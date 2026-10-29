# 术语与编号核对：以 CONTEXT.md 为唯一术语来源。
# 1 从 CONTEXT.md 抽出每个条目指定的 _Avoid_ 词，在全仓活动文档里找它们的用法（命中即「用了不该用的词」）。
# 2 数总图外环九个状态词的出现次数，确认状态词没有被改名。
# 3 数 Stage N、M0/M1、工作包编号（3.2B 这类）的分布，找出路线图改名没跟到底的文件。
# 在仓库根目录运行（或显式给 -Root）。
param(
    [string]$Root = (Get-Location).Path,
    [string[]]$Exclude = @('.venv/', 'node_modules/', '.tmp/', '.claude/worktrees/', 'docs/archive/', '.ralph/', '.yudao/'),
    [string]$Out = '',
    [string]$ContextFile = 'CONTEXT.md',
    [int]$MaxWords = 40
)

$stateWords = @('等待工作', '一轮工作中', '核验中', '接纳', '询问中', '等用户', '排空中', '返工', '停止')

$docs = Get-ChildItem -LiteralPath $Root -Recurse -File -Include *.md, *.html -ErrorAction SilentlyContinue |
    Where-Object {
        $rel = $_.FullName.Substring($Root.Length).Replace('\', '/')
        -not ($Exclude | Where-Object { $rel.Contains($_) })
    }

# 1 抽 _Avoid_（CONTEXT.md 的写法：条目行在前，下一行以「_Avoid_: 词, 词」列出不该用的词）
$avoid = @{}
$ctxPath = Join-Path $Root $ContextFile
if (Test-Path -LiteralPath $ctxPath) {
    $current = ''
    foreach ($line in Get-Content -LiteralPath $ctxPath -Encoding UTF8) {
        if ($line -match '^\s*_Avoid_[:：]\s*(.+)$') {
            $words = ($Matches[1] -split '[、,，;；]') | ForEach-Object { $_.Trim().Trim('。', '.', ' ', '`') } | Where-Object { $_ -and $_.Length -ge 2 }
            foreach ($w in $words) { if (-not $avoid.ContainsKey($w)) { $avoid[$w] = $current } }
            continue
        }
        if ($line -match '^\s*[-*#]*\s*\*\*(.+?)\*\*') { $current = $Matches[1].Trim() }
        elseif ($line -match '^\s*[-*#]*\s*`([^`]+)`\s*[:：]') { $current = $Matches[1].Trim() }
    }
}
"术语表读到 $($avoid.Count) 个 _Avoid_ 词"

$sb = New-Object System.Text.StringBuilder
[void]$sb.AppendLine("# 术语与编号核对")
[void]$sb.AppendLine("")
[void]$sb.AppendLine("扫描 $($docs.Count) 份 md/html，排除 $($Exclude -join ' ')。")
[void]$sb.AppendLine("")

# 一遍扫描，同时收 1、2、3 三组数据
$avoidHits = @{}
$stateCount = @{}
foreach ($w in $stateWords) { $stateCount[$w] = 0 }
$numberRows = New-Object System.Collections.Generic.List[object]

foreach ($f in $docs) {
    $rel = $f.FullName.Substring($Root.Length).Replace('\', '/')
    $text = Get-Content -LiteralPath $f.FullName -Raw -Encoding UTF8
    if (-not $text) { continue }
    $lines = $text -split "`r?`n"

    for ($i = 0; $i -lt $lines.Count; $i++) {
        $line = $lines[$i]
        if ($line -match '_Avoid_' -or $line -match '禁|不该用|不用') { continue }
        foreach ($w in $avoid.Keys) {
            if ($line.Contains($w)) {
                if (-not $avoidHits.ContainsKey($w)) { $avoidHits[$w] = New-Object System.Collections.Generic.List[string] }
                $avoidHits[$w].Add("${rel}:$($i + 1)")
            }
        }
    }

    foreach ($sw in $stateWords) { $stateCount[$sw] += ([regex]::Matches($text, [regex]::Escape($sw))).Count }

    $stage = ([regex]::Matches($text, 'Stage\s*\d+')).Count
    $mile = ([regex]::Matches($text, '\bM\d(\.\d+)?\b')).Count
    $pack = ([regex]::Matches($text, '\b\d\.\d[A-Z]?\b')).Count
    if ($stage + $mile + $pack -gt 0) {
        $numberRows.Add([pscustomobject]@{ File = $rel; Stage = $stage; M = $mile; Pack = $pack; Sum = $stage + $mile + $pack })
    }
}

[void]$sb.AppendLine("## 1 用了 _Avoid_ 词的地方（按命中数排序，取前 $MaxWords 个词）")
[void]$sb.AppendLine("")
[void]$sb.AppendLine("通用词（材料、场景、窗口这类）命中自然会多，先看命中少的：少而集中的才是真的用错了词。")
[void]$sb.AppendLine("")
[void]$sb.AppendLine("| 词 | 该用 | 命中 | 位置 |")
[void]$sb.AppendLine("| --- | --- | --- | --- |")
foreach ($item in ($avoidHits.GetEnumerator() | Sort-Object { $_.Value.Count } | Select-Object -First $MaxWords)) {
    $w = $item.Key
    $hits = $item.Value
    $shown = ($hits | Select-Object -First 6) -join ' '
    if ($hits.Count -gt 6) { $shown += " …共 $($hits.Count) 处" }
    [void]$sb.AppendLine("| $w | $($avoid[$w]) | $($hits.Count) | $shown |")
}

[void]$sb.AppendLine("")
[void]$sb.AppendLine("## 2 外环九个状态词的出现次数")
[void]$sb.AppendLine("")
[void]$sb.AppendLine("| 状态词 | 次数 |")
[void]$sb.AppendLine("| --- | --- |")
foreach ($sw in $stateWords) { [void]$sb.AppendLine("| $sw | $($stateCount[$sw]) |") }

[void]$sb.AppendLine("")
[void]$sb.AppendLine("## 3 旧编号分布（Stage N / M 里程碑 / 工作包号），按文件取前 40")
[void]$sb.AppendLine("")
[void]$sb.AppendLine("| 文件 | Stage | M 里程碑 | 工作包号 | 合计 |")
[void]$sb.AppendLine("| --- | --- | --- | --- | --- |")
foreach ($r in ($numberRows | Sort-Object Sum -Descending | Select-Object -First 40)) {
    [void]$sb.AppendLine("| $($r.File) | $($r.Stage) | $($r.M) | $($r.Pack) | $($r.Sum) |")
}

$text = $sb.ToString()
if ($Out) { Set-Content -LiteralPath $Out -Value $text -Encoding UTF8; "写盘 $Out" } else { $text }
