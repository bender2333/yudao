param(
    [string]$Milestone = '阶段一：单机诚实闭环，三道槽位立缝',
    [string]$Owner = 'bender2333',
    [string]$Repo = 'yudao',
    [string]$Out = '.tmp/discussion-note/overlap.md',
    [string]$Signature = '<署名>'
)

# 只读扫描：拉一个里程碑里的开放工单，按 GitHub 原生 blocked_by 分层，
# 找出「没有先后关系、但共享代码文件」的组合，写成 markdown 报告。
# 不改工单、不改标签、不开 PR。

$ErrorActionPreference = 'Stop'
$root = (& git rev-parse --show-toplevel).Trim()
Push-Location $root
try {
    $raw = gh issue list --state open --milestone $Milestone --limit 200 --json 'number,title,labels,body'
    if (-not $raw) { throw "拉不到里程碑「$Milestone」的工单" }
    $issues = $raw | ConvertFrom-Json

    $ready = @($issues | Where-Object { $_.labels.name -contains 'ready-for-agent' })
    $flying = @($issues | Where-Object { ($_.labels.name -contains 'in-progress') -or ($_.labels.name -contains 'needs-review') })
    if ($ready.Count -eq 0) { throw "里程碑「$Milestone」里没有 ready-for-agent 的工单" }

    function Get-Scope([string]$body) {
        $lines = ($body -replace "`r", '') -split "`n"
        $start = -1
        for ($k = 0; $k -lt $lines.Count; $k++) { if ($lines[$k] -match '^#{1,4}\s*只改') { $start = $k } }
        if ($start -lt 0) { for ($k = 0; $k -lt $lines.Count; $k++) { if ($lines[$k] -match '^只改[：:]') { $start = $k } } }
        if ($start -lt 0) { for ($k = 0; $k -lt $lines.Count; $k++) { if ($lines[$k] -match '只改[：:]') { $start = $k; break } } }
        if ($start -lt 0) { return '' }
        $chunk = @()
        $j = if ($lines[$start] -match '^#{1,4}\s') { $start + 1 } else { $start }
        while ($j -lt $lines.Count) {
            if ($lines[$j] -match '^#{1,4}\s' -and $chunk.Count -gt 0) { break }
            $chunk += $lines[$j]; $j++
        }
        return ($chunk -join ' ').Trim()
    }

    $nodes = @()
    foreach ($i in @($ready) + @($flying)) {
        $scope = Get-Scope ($i.body -replace "`r", '')
        $files = @([regex]::Matches($scope, '[A-Za-z0-9_\-./]+\.(py|ts|tsx|json|toml|md|yml|yaml|js)') |
            ForEach-Object { $_.Value } | Sort-Object -Unique)
        $deps = @()
        try {
            $json = gh api "repos/$Owner/$Repo/issues/$($i.number)/dependencies/blocked_by" 2>$null; if ($LASTEXITCODE -ne 0) { $deps = @() } else { $deps = @(($json | ConvertFrom-Json) | ForEach-Object { [int]$_.number }) }
        }
        catch { $deps = @() }
        $state = if ($i.labels.name -contains 'in-progress') { 'in-progress' }
        elseif ($i.labels.name -contains 'needs-review') { 'needs-review' }
        else { 'ready' }
        $nodes += [pscustomobject]@{
            n = [int]$i.number; title = $i.title; files = $files; deps = @($deps | Sort-Object -Unique)
            scope = $scope; state = $state
        }
    }

    $byN = @{}; foreach ($x in $nodes) { $byN[[int]$x.n] = $x }
    # 只算还没关的依赖：不在本次扫描集合里的编号视为已关闭
    function ActiveDeps([int]$n) {
        if (-not $byN.ContainsKey($n)) { return @() }
        return @($byN[$n].deps | Where-Object { $byN.ContainsKey([int]$_) })
    }

    $level = @{}
    function Get-Level([int]$n) {
        if ($level.ContainsKey($n)) { return $level[$n] }
        $d = @(ActiveDeps $n)
        if ($d.Count -eq 0) { $level[$n] = 0; return 0 }
        $max = 0
        foreach ($x in $d) { $v = Get-Level([int]$x); if ($v + 1 -gt $max) { $max = $v + 1 } }
        $level[$n] = $max
        return $max
    }
    foreach ($x in $nodes) { Get-Level([int]$x.n) | Out-Null }

    $reach = @{}
    foreach ($x in $nodes) {
        $seen = New-Object System.Collections.Generic.HashSet[int]
        $stack = New-Object System.Collections.Generic.Stack[int]
        foreach ($d in (ActiveDeps ([int]$x.n))) { $stack.Push([int]$d) }
        while ($stack.Count -gt 0) {
            $cur = [int]$stack.Pop()
            if (-not $seen.Add($cur)) { continue }
            foreach ($d in (ActiveDeps $cur)) { $stack.Push([int]$d) }
        }
        $reach[[int]$x.n] = $seen
    }
    function Ordered([int]$a, [int]$b) { return ($reach[$a].Contains($b) -or $reach[$b].Contains($a)) }
    function IsCodeFile([string]$p) {
        return ($p -notmatch 'layers\.toml$' -and $p -notmatch '^harness/tests/' -and $p -notmatch '^client/tests/' -and $p -notmatch '^evals/tests/')
    }

    $lines = New-Object System.Collections.Generic.List[string]
    $stamp = Get-Date -Format 'yyyy-MM-dd HH:mm'
    $lines.Add("# 「只改」重叠扫描：$Milestone（$stamp）")
    $lines.Add('')
    $lines.Add("只读扫描，没有改动工单、PR 或代码。范围是里程碑「$Milestone」里 $($ready.Count) 张 ``ready-for-agent``，加 $($flying.Count) 张在飞。依赖取 GitHub 原生 ``blocked_by``。")
    $lines.Add('')
    $lines.Add('## 1. 依赖层与并行宽度')
    $lines.Add('')
    $lines.Add('| 层 | 张数 | 工单 |')
    $lines.Add('| --- | --- | --- |')
    foreach ($lv in ($level.Values | Sort-Object -Unique)) {
        $ns = @($nodes | Where-Object { $level[[int]$_.n] -eq $lv } | ForEach-Object { "#$($_.n)" } | Sort-Object)
        $lines.Add("| $lv | $($ns.Count) | $($ns -join '、') |")
    }
    $zero = @($nodes | Where-Object { $_.state -eq 'ready' -and @(ActiveDeps ([int]$_.n)).Count -eq 0 } | ForEach-Object { "#$($_.n)" })
    $lines.Add('')
    $lines.Add($(if ($zero.Count) { "可以立刻派：$($zero -join '、')" } else { '当前没有可以立刻派的 ready 工单：全部被未关闭的依赖挡着。' }))
    $lines.Add('')

    $pairs = @(); $reg = @()
    for ($a = 0; $a -lt $nodes.Count; $a++) {
        for ($b = $a + 1; $b -lt $nodes.Count; $b++) {
            $x = $nodes[$a]; $y = $nodes[$b]
            $shared = @($x.files | Where-Object { $y.files -contains $_ })
            if ($shared.Count -eq 0) { continue }
            $code = @($shared | Where-Object { IsCodeFile $_ })
            if ($code.Count -gt 0) {
                if (Ordered ([int]$x.n) ([int]$y.n)) { continue }
                $pairs += [pscustomobject]@{
                    a = $x.n; b = $y.n; aLv = $level[[int]$x.n]; bLv = $level[[int]$y.n]
                    shared = ($code -join ' + '); count = $code.Count
                }
            }
            else { $reg += "#$($x.n)×#$($y.n)" }
        }
    }
    $lines.Add('## 2. 没有先后关系、且共享代码文件的组合')
    $lines.Add('')
    if ($pairs.Count -eq 0) { $lines.Add('没有。') }
    else {
        $lines.Add('| A | B | 共享文件 | 怎么处置 |')
        $lines.Add('| --- | --- | --- | --- |')
        foreach ($p in $pairs | Sort-Object count -Descending) {
            $how = if ($p.aLv -eq $p.bLv) { '同层，按规矩重切或合成一张，不能并行' } else { "不同层（L$($p.aLv)/L$($p.bLv)），低层还在跑时会撞" }
            $lines.Add("| #$($p.a) (L$($p.aLv)) | #$($p.b) (L$($p.bLv)) | $($p.shared) | $how |")
        }
    }
    $lines.Add('')
    $lines.Add('## 3. 只共享登记表或测试目录的组合')
    $lines.Add('')
    $lines.Add("$($reg.Count) 组，按规则不算同一块（登记表冲突两边都保留，测试目录各写各的）。" + $(if ($reg.Count) { ' ' + ($reg -join '；') } else { '' }))
    $lines.Add('')
    $noScope = @($nodes | Where-Object { $_.state -eq 'ready' -and $_.files.Count -eq 0 })
    $lines.Add('## 4. 「只改」缺失或读不出来的')
    $lines.Add('')
    if ($noScope.Count -eq 0) { $lines.Add('没有。') }
    else { foreach ($x in $noScope) { $lines.Add("- #$($x.n) $($x.title)") } }
    $lines.Add('')
    $lines.Add('## 5. 每张的层与「只改」摘要')
    $lines.Add('')
    foreach ($x in $nodes | Sort-Object @{ Expression = { $level[[int]$_.n] } }, n) {
        $deps = @(ActiveDeps ([int]$x.n))
        $lines.Add("### #$($x.n)（L$($level[[int]$x.n])，$($x.state)）$($x.title)")
        $lines.Add("- 未关闭依赖：$(if ($deps.Count) { ($deps | ForEach-Object { "#$_" }) -join '、' } else { '无' })")
        $lines.Add("- 只改：$($x.scope.Substring(0, [Math]::Min(300, $x.scope.Length)))")
        $lines.Add('')
    }
    $lines.Add('---')
    $lines.Add('')
    $lines.Add("— $Signature / $stamp / 只读扫描，未改动工单、PR 与代码")

    $outPath = Join-Path $root $Out
    New-Item -ItemType Directory -Force (Split-Path $outPath) | Out-Null
    $lines | Set-Content $outPath -Encoding utf8
    Write-Output "报告：$outPath"
    Write-Output "层宽：$((($level.Values | Sort-Object -Unique) | ForEach-Object { $lv = $_; "L$lv=$(@($nodes | Where-Object { $level[[int]$_.n] -eq $lv }).Count)" }) -join '  ')"
    Write-Output "无先后 + 共享代码文件：$($pairs.Count) 组；只共享登记表：$($reg.Count) 组；缺「只改」：$($noScope.Count) 张"
}
finally { Pop-Location }


