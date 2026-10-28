<#
试用前的环境核对。只读，不改动任何东西；有阻断项时以退出码 1 结束。

用法：
  pwsh -NoProfile -File .claude/skills/trial/scripts/preflight.ps1 `
      -Ticket 994 -TaskSet trial-tasks@3 -Port 8766 -ChromePort 9222 -EdgePort 9223

参数都有默认值；-DataDir 不给时按 -Port 拼一个临时目录。
#>
[CmdletBinding()]
param(
  [int]$Ticket = 0,
  [string]$TaskSet = 'trial-tasks@3',
  [int]$Port = 8766,
  [int]$ChromePort = 9222,
  [int]$EdgePort = 9223,
  [string]$DataDir = ''
)

$ErrorActionPreference = 'Stop'
$repo = (git rev-parse --show-toplevel 2>$null)
if (-not $repo) { $repo = (Get-Location).Path }
if (-not $DataDir) { $DataDir = Join-Path ([System.IO.Path]::GetTempPath()) "yudao-trial-$Port" }

$rows = New-Object System.Collections.Generic.List[object]
function Add-Row([string]$Item, [string]$Value, [string]$Level, [string]$Note = '') {
  $rows.Add([pscustomobject]@{ 项 = $Item; 值 = $Value; 级别 = $Level; 说明 = $Note })
}

function Get-ToolVersion([string]$Exe, [string[]]$Arguments = @('--version')) {
  $command = Get-Command $Exe -ErrorAction SilentlyContinue
  if (-not $command) { return $null }
  try {
    $output = & $command.Source @Arguments 2>&1 | Select-Object -First 1
    return [string]$output
  } catch {
    return $null
  }
}

# 1. 仓库
$branch = (git -C $repo rev-parse --abbrev-ref HEAD 2>$null)
$commit = (git -C $repo rev-parse --short HEAD 2>$null)
$dirty = (git -C $repo status --porcelain 2>$null)
$dirtyText = if ($dirty) { "有 $($dirty.Count) 处未提交改动" } else { '干净' }
Add-Row '仓库' $repo '信息'
Add-Row '分支与提交' "$branch @ $commit" '信息'
Add-Row '工作区' $dirtyText ($(if ($dirty) { '警告' } else { '通过' })) '发布包要求工作区干净；有改动时先提交或另用干净克隆'

# 2. 工具
foreach ($tool in @(
    @{ Name = 'git'; Args = @('--version') },
    @{ Name = 'python'; Args = @('--version') },
    @{ Name = 'uv'; Args = @('--version') },
    @{ Name = 'node'; Args = @('--version') },
    @{ Name = 'npm'; Args = @('--version') },
    @{ Name = 'gh'; Args = @('--version') },
    @{ Name = 'omp'; Args = @('--version') })) {
  $version = Get-ToolVersion $tool.Name $tool.Args
  if ($version) {
    $level = '通过'
    if ($tool.Name -eq 'node' -and $version -match 'v(\d+)\.') {
      if ([int]$Matches[1] -lt 22) { $level = '阻断'; $version = "$version（发布要 22.12 以上）" }
    }
    Add-Row "工具 $($tool.Name)" $version $level
  } else {
    $level = if ($tool.Name -in @('git', 'python', 'uv', 'gh')) { '阻断' } else { '警告' }
    Add-Row "工具 $($tool.Name)" '没有找到' $level
  }
}

# 3. GitHub 账号
$ghUser = (& gh api user --jq .login 2>$null)
if ($ghUser) { Add-Row 'gh 账号' $ghUser '通过' } else { Add-Row 'gh 账号' '没有登录' '阻断' '发帖与发工单要用' }

# 4. 模型与凭据（环境变量）
$baseUrl = $env:YUDAO_EVAL_BASE_URL
$apiKey = $env:YUDAO_EVAL_API_KEY
if ($baseUrl) { Add-Row '评测服务地址' $baseUrl '通过' } else { Add-Row '评测服务地址' 'YUDAO_EVAL_BASE_URL 没设' '阻断' }
if ($apiKey) { Add-Row '凭据' "已设（长度 $($apiKey.Length)）" '通过' } else { Add-Row '凭据' 'YUDAO_EVAL_API_KEY 没设' '阻断' '产品部门与工程部门跑真实模型要用' }
foreach ($name in @('YUDAO_EVAL_MODEL_PRODUCT', 'YUDAO_EVAL_MODEL_ENGINEERING', 'YUDAO_EVAL_MODEL_QUALITY')) {
  $value = [Environment]::GetEnvironmentVariable($name)
  $level = if ($value) { '通过' } else { '警告' }
  Add-Row $name ($(if ($value) { $value } else { '没设，按仓库默认' })) $level
}

# 5. 端口
foreach ($candidate in @(
    @{ Name = '产品服务'; Value = $Port },
    @{ Name = 'Chrome 调试口'; Value = $ChromePort },
    @{ Name = 'Edge 调试口'; Value = $EdgePort })) {
  $inUse = Get-NetTCPConnection -LocalPort $candidate.Value -State Listen -ErrorAction SilentlyContinue
  if ($inUse) {
    $owner = (Get-Process -Id $inUse[0].OwningProcess -ErrorAction SilentlyContinue).ProcessName
    Add-Row "端口 $($candidate.Value)（$($candidate.Name)）" "被占用：$owner" '警告' '先确认是不是上一次试用留下的'
  } else {
    Add-Row "端口 $($candidate.Value)（$($candidate.Name)）" '空闲' '通过'
  }
}

# 6. 浏览器
$browsers = @{
  'Chrome' = @(
    "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
    "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
    "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe")
  'Edge'   = @(
    "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe",
    "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe")
}
foreach ($name in $browsers.Keys) {
  $found = $browsers[$name] | Where-Object { Test-Path $_ } | Select-Object -First 1
  if ($found) { Add-Row "浏览器 $name" $found '通过' } else { Add-Row "浏览器 $name" '没有找到' '警告' '换路复测要第二个浏览器' }
}

# 7. 磁盘
$drive = (Split-Path -Qualifier $DataDir)
$free = (Get-PSDrive -Name $drive.TrimEnd(':') -ErrorAction SilentlyContinue).Free
if ($free) {
  $freeGb = [math]::Round($free / 1GB, 1)
  Add-Row "磁盘余量 $drive" "$freeGb GB" ($(if ($freeGb -lt 5) { '警告' } else { '通过' })) '数据目录、虚拟环境与构建产物'
} else {
  Add-Row "磁盘余量 $drive" '读不到' '警告'
}
Add-Row '数据目录（本次）' $DataDir '信息'

# 8. 工单与任务集
if ($Ticket -gt 0) {
  $issue = (& gh issue view $Ticket --json number,title,state --jq '"\(.number) \(.state) \(.title)"' 2>$null)
  if ($issue) { Add-Row "试用工单 #$Ticket" $issue '通过' } else { Add-Row "试用工单 #$Ticket" '读不到' '阻断' }
} else {
  Add-Row '试用工单' '没有给 -Ticket' '警告' '报告要挂在试用工单下'
}
$tasksFile = Join-Path $repo 'docs/trial/tasks.md'
if (Test-Path $tasksFile) {
  $tasksText = Get-Content $tasksFile -Raw
  $version = if ($tasksText -match '(trial-tasks@\d+)') { $Matches[1] } else { '没有写版本' }
  $level = if ($version -eq $TaskSet) { '通过' } else { '阻断' }
  Add-Row '任务集版本' "$version（要求 $TaskSet）" $level '产品代码、任务集与规格三者版本要一致'
} else {
  Add-Row '任务集文件' "$tasksFile 不存在" '阻断'
}

# 输出
$rows | Format-Table -AutoSize -Wrap | Out-String -Width 200 | Write-Output
$blockers = @($rows | Where-Object { $_.级别 -eq '阻断' }).Count
$warnings = @($rows | Where-Object { $_.级别 -eq '警告' }).Count
Write-Output "阻断 $blockers 项，警告 $warnings 项"
if ($blockers -gt 0) {
  Write-Output '有阻断项，先补齐再开始试用；缺什么由维护者决定怎么补。'
  exit 1
}
Write-Output '可以开始。'
exit 0
