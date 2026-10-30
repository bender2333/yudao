<#
试用实例的启动、核对、停止与重启。服务只从指定的解释器与 wheel 起，身份记在 manifest 里；
任何一步不符就地报错，不换成源码运行。

用法：
  pwsh -NoProfile -File .claude/skills/trial/scripts/instance.ps1 -Action Start `
      -Manifest <manifest.json> -Python <解释器> -Wheel <wheel> -Commit <提交> `
      -DataDir <空目录> -Port <端口> -MaterialVersion <材料版本> -SkillCommit <技能提交> `
      [-TaskSet trial-tasks@4] [-WorkingDirectory <仓库外目录>] [-ModelsFile <models.json>]
  pwsh -NoProfile -File .claude/skills/trial/scripts/instance.ps1 -Action Inspect -Manifest <manifest.json> [-ModelsFile <models.json>]
  pwsh -NoProfile -File .claude/skills/trial/scripts/instance.ps1 -Action Restart -Manifest <manifest.json>
  pwsh -NoProfile -File .claude/skills/trial/scripts/instance.ps1 -Action Stop -Manifest <manifest.json>

Inspect 与 Restart 的身份都从 manifest 读。-ModelsFile 是 JSON 数组（或带 models 键的对象），
每项必须有 department、model、protocol、context_window、max_output_tokens；可另记推理档位与输入方式。
Inspect 加 -NoWrite 时不改 manifest，加 -PassThru 时把结果对象交给调用者（preflight 用）。
退出码：0 通过，1 有未通过的检查或报错。
#>
[CmdletBinding()]
param(
  [Parameter(Mandatory)][ValidateSet('Start', 'Inspect', 'Stop', 'Restart')][string]$Action,
  [Parameter(Mandatory)][string]$Manifest,
  [string]$Python = '',
  [string]$Wheel = '',
  [string]$Commit = '',
  [string]$DataDir = '',
  [int]$Port = 0,
  [string]$TaskSet = 'trial-tasks@4',
  [string]$MaterialVersion = '',
  [string]$SkillCommit = '',
  [string]$WorkingDirectory = '',
  [string]$ModelsFile = '',
  [ValidateRange(1, 600)][int]$ReadyTimeoutSec = 90,
  [switch]$NoWrite,
  [switch]$PassThru
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Net.Http

function Get-FullPath([string]$Path) {
  [System.IO.Path]::GetFullPath([System.IO.Path]::Combine((Get-Location).ProviderPath, $Path))
}

$ManifestPath = Get-FullPath $Manifest
$ManifestDir = Split-Path -Parent $ManifestPath

function Format-Utc([datetime]$Time) { $Time.ToUniversalTime().ToString('o') }

function ConvertTo-UtcTime($Value) {
  # ConvertFrom-Json 会把 ISO 时间串转成本地时间的 datetime，两种形式都收成 UTC
  if ($Value -is [datetime]) { return $Value.ToUniversalTime() }
  return [datetime]::Parse([string]$Value, [System.Globalization.CultureInfo]::InvariantCulture, [System.Globalization.DateTimeStyles]::RoundtripKind).ToUniversalTime()
}

function ConvertTo-Plain($Value) {
  # JSON 读出的对象收成有序字典，时间一律写回 UTC 字符串
  if ($null -eq $Value) { return $null }
  if ($Value -is [datetime]) { return (Format-Utc $Value) }
  if ($Value -is [System.Management.Automation.PSCustomObject]) {
    $result = [ordered]@{}
    foreach ($property in $Value.PSObject.Properties) { $result[$property.Name] = ConvertTo-Plain $property.Value }
    return $result
  }
  if ($Value -is [System.Collections.IEnumerable] -and $Value -isnot [string]) {
    return , @(foreach ($item in $Value) { ConvertTo-Plain $item })
  }
  return $Value
}

function Read-Manifest {
  if (-not (Test-Path -LiteralPath $ManifestPath)) { throw "manifest 不存在：$ManifestPath" }
  $plain = ConvertTo-Plain (Get-Content -LiteralPath $ManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json)
  if ($plain['schema_version'] -ne 1) { throw "manifest 的 schema_version 不是 1：$ManifestPath" }
  return $plain
}

function Write-Manifest($Data) {
  New-Item -ItemType Directory -Force -Path $ManifestDir | Out-Null
  $json = ConvertTo-Json -InputObject $Data -Depth 8
  [System.IO.File]::WriteAllText($ManifestPath, $json + "`n", (New-Object System.Text.UTF8Encoding($false)))
}

function Save-ToolIdentity($Data) {
  $hashes = [ordered]@{}
  $files = @(Get-ChildItem -LiteralPath $PSScriptRoot -File | Where-Object { $_.Extension -in '.ps1', '.mjs' })
  $skillRoot = Split-Path -Parent $PSScriptRoot
  $entry = Join-Path $skillRoot 'SKILL.md'
  if (Test-Path -LiteralPath $entry) {
    $files += Get-Item -LiteralPath $entry
    $methods = Join-Path $skillRoot 'method'
    if (Test-Path -LiteralPath $methods) { $files += Get-ChildItem -LiteralPath $methods -File -Filter '*.md' }
  }
  foreach ($file in $files) { $hashes[$file.Name] = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant() }
  $Data['tool_sha256'] = $hashes
  $Data['skill_worktree_dirty'] = $null
  if (Get-Command git -ErrorAction SilentlyContinue) {
    $repoRoot = (& git -C $PSScriptRoot rev-parse --show-toplevel 2>$null)
    if ($repoRoot) { $Data['skill_worktree_dirty'] = [bool](& git -C $repoRoot status --porcelain -- .claude/skills/trial) }
  }
}

function Resolve-ManifestPath([string]$Path) {
  # manifest 里的路径可以写相对路径，相对 manifest 所在目录
  [System.IO.Path]::GetFullPath([System.IO.Path]::Combine($ManifestDir, $Path))
}

function Read-Models([string]$File) {
  $parsed = Get-Content -LiteralPath (Get-FullPath $File) -Raw -Encoding UTF8 | ConvertFrom-Json
  $items = if ($parsed.PSObject.Properties['models']) { $parsed.models } else { $parsed }
  $result = New-Object System.Collections.Generic.List[object]
  foreach ($item in @($items)) {
    $entry = [ordered]@{}
    # 配置只取明确列出的字段，凭据等其他键不进入 manifest
    foreach ($key in 'department', 'model', 'protocol', 'context_window', 'max_output_tokens') {
      $property = $item.PSObject.Properties[$key]
      if (-not $property -or $null -eq $property.Value -or "$($property.Value)" -eq '') { throw "ModelsFile 里有一项缺少 $key" }
      $entry[$key] = $property.Value
    }
    foreach ($key in 'requested_tier', 'reasoning_mode', 'default_reasoning_level', 'input_modalities') {
      if ($item.PSObject.Properties[$key]) { $entry[$key] = $item.$key }
    }
    $result.Add($entry)
  }
  return , $result.ToArray()
}

# ---- 进程 ----

function Get-ProcessInfo([int]$ProcessId) {
  $process = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
  if (-not $process) { return $null }
  $startedAt = $null
  try { $startedAt = Format-Utc $process.StartTime } catch { throw "读不到进程 $ProcessId 的创建时间：$($_.Exception.Message)" }
  $cim = Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId" -ErrorAction SilentlyContinue
  [pscustomobject]@{
    Id = $ProcessId
    StartedAt = $startedAt
    ParentId = if ($cim) { [int]$cim.ParentProcessId } else { 0 }
    CommandLine = if ($cim) { [string]$cim.CommandLine } else { '' }
  }
}

function Test-SameStart([string]$Recorded, [string]$Actual) {
  [math]::Abs(((ConvertTo-UtcTime $Recorded) - (ConvertTo-UtcTime $Actual)).TotalMilliseconds) -lt 5
}

function Get-DescendantIds([int]$RootId, [string]$RootStartedAt = '', [string]$RootStoppedAt = '') {
  # 某进程当前的全部后代；父进程号链条上要求父进程比子进程先创建，避免进程号被复用后误连
  $all = @(Get-CimInstance Win32_Process)
  $found = New-Object System.Collections.Generic.List[int]
  $queue = New-Object System.Collections.Generic.Queue[object]
  $root = $all | Where-Object { $_.ProcessId -eq $RootId }
  if ($RootStartedAt) {
    if ($root -and -not (Test-SameStart $RootStartedAt (Format-Utc $root.CreationDate))) { return @() }
    if (-not $root) { $root = [pscustomobject]@{ ProcessId = $RootId; CreationDate = (ConvertTo-UtcTime $RootStartedAt).ToLocalTime() } }
  }
  if (-not $root) { return @() }
  $rootEnded = if ($RootStoppedAt) { (ConvertTo-UtcTime $RootStoppedAt).ToLocalTime() } else { $null }
  $queue.Enqueue($root)
  while ($queue.Count -gt 0) {
    $parent = $queue.Dequeue()
    foreach ($child in ($all | Where-Object { $_.ParentProcessId -eq $parent.ProcessId -and $_.ProcessId -ne $parent.ProcessId })) {
      if ($child.CreationDate -lt $parent.CreationDate) { continue }
      if ($parent.ProcessId -eq $RootId -and $rootEnded -and $child.CreationDate -gt $rootEnded) { continue }
      if ($found.Contains([int]$child.ProcessId)) { continue }
      $found.Add([int]$child.ProcessId)
      $queue.Enqueue($child)
    }
  }
  return $found.ToArray()
}

function Get-Listener([int]$PortNumber) {
  $listener = @(Get-NetTCPConnection -LocalPort $PortNumber -State Listen -ErrorAction SilentlyContinue)
  if ($listener.Count -eq 0) { return $null }
  return [int]$listener[0].OwningProcess
}

function Get-RecordedProcess([int]$ProcessId, [string]$StartedAt, [string]$Label) {
  $info = Get-ProcessInfo $ProcessId
  if (-not $info) { return $null }
  if (-not (Test-SameStart $StartedAt $info.StartedAt)) {
    throw "$Label $ProcessId 的创建时间是 $($info.StartedAt)，与 manifest 记录的 $StartedAt 不符，不停止"
  }
  return $info
}

function Stop-Recorded([int]$ProcessId, [string]$StartedAt, [string]$Label) {
  # 只停 manifest 记录且创建时间一致的进程
  $info = Get-RecordedProcess $ProcessId $StartedAt $Label
  if (-not $info) { return "$Label $ProcessId 已不存在" }
  # 服务进程结束时启动进程可能同时退出，此时进程已不在不算错误，结束后再确认
  Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
  Wait-Process -Id $ProcessId -Timeout 20 -ErrorAction SilentlyContinue
  if (Get-Process -Id $ProcessId -ErrorAction SilentlyContinue) { throw "$Label $ProcessId 停止后仍在运行" }
  return "$Label $ProcessId 已停止"
}

# ---- 网络 ----

function Get-HttpStatus([string]$Url) {
  # 本机地址不走系统代理；连接失败返回空
  $handler = New-Object System.Net.Http.HttpClientHandler
  $handler.UseProxy = $false
  $client = New-Object System.Net.Http.HttpClient($handler)
  $client.Timeout = [TimeSpan]::FromSeconds(5)
  try {
    $response = $client.GetAsync($Url).GetAwaiter().GetResult()
    $type = if ($response.Content.Headers.ContentType) { [string]$response.Content.Headers.ContentType.MediaType } else { '' }
    return [pscustomobject]@{ Status = [int]$response.StatusCode; ContentType = $type }
  } catch {
    return $null
  } finally {
    $client.Dispose()
  }
}

# ---- 包身份 ----

$IdentityScript = @'
import hashlib
import importlib.metadata as metadata
import json
import sys
import sysconfig
import zipfile
from email.parser import BytesParser
from pathlib import Path

wheel = Path(sys.argv[1])
problems = []
result = {"executable": sys.executable, "prefix": sys.prefix, "python_version": sys.version.split()[0], "problems": problems}
if sys.version_info < (3, 11):
    problems.append("解释器低于 Python 3.11")

# 实际导入 harness，位置必须在这个解释器的 site-packages 里
import harness

package = Path(harness.__file__).resolve().parent
site_dirs = {Path(sysconfig.get_paths()[key]).resolve() for key in ("purelib", "platlib")}
result["package_path"] = str(package)
result["site_packages"] = sorted(str(item) for item in site_dirs)
site = package.parent
if site not in site_dirs:
    problems.append("harness 的导入位置不在该解释器的 site-packages 内：" + str(package))

# 已安装的发行版：不能是 editable（direct_url.json、editable 的 .pth 与 egg-link 三处都查）
for directory in site_dirs:
    for pattern in ("__editable__*yudao*", "yudao*.egg-link"):
        for item in directory.glob(pattern):
            problems.append("site-packages 里有 editable 安装的痕迹：" + item.name)
dist = metadata.distribution("yudao-harness")
result["installed_version"] = dist.version
direct_url = dist.read_text("direct_url.json")
if direct_url and json.loads(direct_url).get("dir_info", {}).get("editable"):
    problems.append("已安装的 yudao-harness 是 editable 安装")

# wheel 里的文件与安装内容逐个比对
with zipfile.ZipFile(wheel) as archive:
    names = [name for name in archive.namelist() if not name.endswith("/")]
    info_prefix = [name for name in names if name.endswith(".dist-info/METADATA")]
    wheel_meta = BytesParser().parsebytes(archive.read(info_prefix[0]))
    result["wheel_version"] = wheel_meta["Version"]
    if wheel_meta["Name"].lower().replace("_", "-") != "yudao-harness" or wheel_meta["Version"] != dist.version:
        problems.append("wheel 的名称或版本与已安装的发行版不同")
    mismatched, missing = [], []
    for name in names:
        if name.endswith((".dist-info/RECORD", ".dist-info/WHEEL")):
            continue
        installed = site / name
        if not installed.is_file():
            missing.append(name)
        elif hashlib.sha256(installed.read_bytes()).digest() != hashlib.sha256(archive.read(name)).digest():
            mismatched.append(name)
    expected = set(names)
    extra = sorted(
        item.relative_to(site).as_posix()
        for item in package.rglob("*")
        if item.is_file() and "__pycache__" not in item.parts and item.suffix != ".pyc"
        and item.relative_to(site).as_posix() not in expected)
result["wheel_files_checked"] = len(names)
for label, items in (("缺少", missing), ("内容不同", mismatched), ("多出", extra)):
    if items:
        problems.append("安装目录与 wheel 比较：" + label + " " + str(len(items)) + " 个，例如 " + ", ".join(items[:5]))
result["ok"] = not problems
print(json.dumps(result))
'@

function Test-PackageIdentity([string]$PythonPath, [string]$WheelPath, [string]$WorkDir) {
  # 检查与服务使用同样的解释器参数（-I -X utf8）和同样的工作目录：PYTHONPATH 与当前目录都不参与导入，
  # 检查里导入的 harness 就是服务实际导入的那一份
  $errFile = [System.IO.Path]::GetTempFileName()
  $previous = $OutputEncoding
  $OutputEncoding = New-Object System.Text.UTF8Encoding($false)
  Push-Location $WorkDir
  try {
    $output = $IdentityScript | & $PythonPath -I -X utf8 - $WheelPath 2>$errFile
    $exit = $LASTEXITCODE
  } finally {
    Pop-Location
    $OutputEncoding = $previous
  }
  $errText = (Get-Content -LiteralPath $errFile -Raw -Encoding UTF8)
  Remove-Item -LiteralPath $errFile -Force
  if ($exit -ne 0) {
    $tail = (($errText -split "`r?`n" | Where-Object { $_ } | Select-Object -Last 3) -join ' | ')
    return [pscustomobject]@{ ok = $false; problems = @("身份检查脚本退出码 ${exit}：$tail") }
  }
  return ($output -join "`n") | ConvertFrom-Json
}

function Assert-OutsideRepository([string]$Directory) {
  # 仓库内运行会导入仓库里的 harness 包
  $top = $null
  if (Get-Command git -ErrorAction SilentlyContinue) { $top = (& git -C $Directory rev-parse --show-toplevel 2>$null) }
  if ($top) { throw "工作目录在 git 仓库内（$top）：$Directory" }
  if ((Test-Path -LiteralPath (Join-Path $Directory 'harness')) -or (Test-Path -LiteralPath (Join-Path $Directory 'pyproject.toml'))) {
    throw "工作目录里有 harness 或 pyproject.toml：$Directory"
  }
}

# ---- 启动 ----

function Assert-ServerInputs($M, [bool]$FreshData, [int]$AllowedListenerId = 0) {
  $python = $M['python']; $wheelPath = $M['wheel']['path']
  $workDir = $M['working_directory']; $dataDir = $M['data_dir']; $portNumber = [int]$M['port']
  if ($portNumber -lt 1024 -or $portNumber -gt 65535) { throw '实例端口需要在 1024–65535 之间' }
  if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw "解释器不存在：$python" }
  if (-not (Test-Path -LiteralPath $wheelPath -PathType Leaf)) { throw "wheel 不存在：$wheelPath" }
  if (-not (Test-Path -LiteralPath $workDir -PathType Container)) { throw "工作目录不存在：$workDir" }
  Assert-OutsideRepository $workDir
  $hash = (Get-FileHash -LiteralPath $wheelPath -Algorithm SHA256).Hash.ToLowerInvariant()
  if ($M['wheel']['sha256'] -and $M['wheel']['sha256'] -ne $hash) { throw "wheel 的 SHA-256 是 $hash，与 manifest 记录的 $($M['wheel']['sha256']) 不符" }
  $M['wheel']['sha256'] = $hash
  if ($FreshData) {
    if ((Test-Path -LiteralPath $dataDir) -and @(Get-ChildItem -LiteralPath $dataDir -Force).Count -gt 0) { throw "数据目录不为空：$dataDir（继续使用已有数据请用 Restart）" }
  } elseif (-not (Test-Path -LiteralPath $dataDir -PathType Container)) {
    throw "数据目录不存在：$dataDir"
  }
  $listenerId = Get-Listener $portNumber
  if ($listenerId -and $listenerId -ne $AllowedListenerId) { throw "端口 $portNumber 已被占用" }

  $identity = Test-PackageIdentity $python $wheelPath $workDir
  if (-not $identity.ok) { throw ("包身份核对未通过：" + (@($identity.problems) -join '；')) }
  return $identity
}

function Start-Server($M, [bool]$FreshData) {
  $identity = Assert-ServerInputs $M $FreshData
  $python = $M['python']; $workDir = $M['working_directory']
  $dataDir = $M['data_dir']; $portNumber = [int]$M['port']

  New-Item -ItemType Directory -Force -Path $dataDir | Out-Null
  New-Item -ItemType Directory -Force -Path $ManifestDir | Out-Null
  $stem = [System.IO.Path]::GetFileNameWithoutExtension($ManifestPath)
  $stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
  $outFile = Join-Path $ManifestDir "$stem.$stamp.stdout.log"
  $errFile = Join-Path $ManifestDir "$stem.$stamp.stderr.log"
  # 独立隐藏窗口负责服务输出；外层不重定向句柄，避免调用者等后台服务关闭输出管道才返回。
  $bootPath = Join-Path $ManifestDir "$stem.boot.ps1"
  $bootConfigPath = Join-Path $ManifestDir "$stem.boot.json"
  $bootScript = @'
param([Parameter(Mandatory)][string]$Config)
$ErrorActionPreference = 'Stop'
$settings = Get-Content -LiteralPath $Config -Raw -Encoding UTF8 | ConvertFrom-Json
$OutputEncoding = [Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
& $settings.python -I -X utf8 -m harness api --data-dir $settings.data_dir --host 127.0.0.1 --port $settings.port --no-browser 1> $settings.stdout 2> $settings.stderr
exit $LASTEXITCODE
'@
  [IO.File]::WriteAllText($bootPath, $bootScript, [Text.UTF8Encoding]::new($false))
  $bootConfig = [ordered]@{ python = $python; data_dir = $dataDir; port = $portNumber; stdout = $outFile; stderr = $errFile }
  [IO.File]::WriteAllText($bootConfigPath, (ConvertTo-Json $bootConfig), [Text.UTF8Encoding]::new($false))
  $shell = (Get-Command pwsh -CommandType Application -ErrorAction Stop).Source
  $argumentLine = "-NoProfile -File `"$bootPath`" -Config `"$bootConfigPath`""
  $launcher = Start-Process -FilePath $shell -ArgumentList $argumentLine -WorkingDirectory $workDir -WindowStyle Hidden -PassThru
  $null = $launcher.Handle
  $launcherStart = Format-Utc $launcher.StartTime
  $serverId = 0
  $serverStart = $null
  try {
    $deadline = (Get-Date).AddSeconds($ReadyTimeoutSec)
    while ($true) {
      if ($launcher.HasExited) {
        $tail = ((Get-Content -LiteralPath $errFile -Tail 8 -ErrorAction SilentlyContinue) -join ' | ')
        throw "服务进程已退出（退出码 $($launcher.ExitCode)）：$tail"
      }
      $listenerId = Get-Listener $portNumber
      if ($listenerId) {
        if ($listenerId -ne $launcher.Id -and $listenerId -notin (Get-DescendantIds $launcher.Id)) {
          throw "端口 $portNumber 的监听进程 $listenerId 不是本次启动的进程"
        }
        $serverId = $listenerId
        $serverStart = (Get-ProcessInfo $listenerId).StartedAt
        $capabilities = Get-HttpStatus "http://127.0.0.1:$portNumber/api/capabilities"
        if ($capabilities -and $capabilities.Status -eq 200) { break }
        if ($capabilities -and $capabilities.Status -ne 503) { throw "/api/capabilities 返回 $($capabilities.Status)" }
      }
      if ((Get-Date) -gt $deadline) { throw "$ReadyTimeoutSec 秒内 /api/capabilities 没有返回 200" }
      Start-Sleep -Milliseconds 500
    }
    $page = Get-HttpStatus "http://127.0.0.1:$portNumber/"
    if (-not $page -or $page.Status -ne 200 -or $page.ContentType -ne 'text/html') { throw '页面 / 没有返回 HTTP 200 text/html，wheel 里的页面文件没有生效' }
    $server = Get-ProcessInfo $serverId
    if (-not $server) { throw "监听进程 $serverId 在就绪后消失" }
  } catch {
    # 失败时只清理本次自己创建的进程，日志留在原处供查看
    $startupError = $_.Exception.Message
    # 先停止启动进程，再读取后代，防止读取期间仍有新的服务进程被创建
    $launcherInfo = Get-ProcessInfo $launcher.Id
    if ($launcherInfo -and (Test-SameStart $launcherStart $launcherInfo.StartedAt)) {
      $null = Stop-Recorded $launcher.Id $launcherStart '启动进程'
    }
    $launcherStopped = Format-Utc (Get-Date)
    $owned = @(Get-DescendantIds $launcher.Id $launcherStart $launcherStopped | ForEach-Object { Get-ProcessInfo $_ } | Where-Object { $_ })
    if ($serverId -and $serverStart) { $owned += [pscustomobject]@{ Id = $serverId; StartedAt = $serverStart } }
    $owned += [pscustomobject]@{ Id = $launcher.Id; StartedAt = $launcherStart }
    foreach ($recorded in $owned) {
      $info = Get-ProcessInfo $recorded.Id
      if ($info -and (Test-SameStart $recorded.StartedAt $info.StartedAt)) { $null = Stop-Recorded $recorded.Id $recorded.StartedAt '本次启动进程' }
    }
    throw "启动失败：$startupError（stdout $outFile，stderr $errFile）"
  }

  $history = @()
  if ($M['process_history']) { $history = @($M['process_history']) }
  if ([int]$M['pid'] -gt 0 -and $M['process_started_at']) {
    $history += [ordered]@{ pid = [int]$M['pid']; process_started_at = $M['process_started_at']; package_path = $M['package_path']; wheel_sha256 = $M['wheel']['sha256'] }
  }
  $M['process_history'] = $history
  $M['python_version'] = $identity.python_version
  $M['python_prefix'] = $identity.prefix
  $M['package_path'] = $identity.package_path
  $M['site_packages'] = @($identity.site_packages)
  $M['package_version'] = $identity.installed_version
  $M['wheel_files_checked'] = [int]$identity.wheel_files_checked
  $M['host'] = '127.0.0.1'
  $M['pid'] = $serverId
  $M['process_started_at'] = $server.StartedAt
  $M['launcher_pid'] = $launcher.Id
  $M['launcher_started_at'] = $launcherStart
  $M['started_at'] = Format-Utc (Get-Date)
  $M['stdout_path'] = $outFile
  $M['stderr_path'] = $errFile
  $M['identity_checked_at'] = Format-Utc (Get-Date)
  $M['api_ready'] = [ordered]@{ capabilities_status = 200; page_status = 200; page_content_type = $page.ContentType; checked_at = Format-Utc (Get-Date) }
  $M['status'] = 'running'
  $M.Remove('stopped_at')
  Save-ToolIdentity $M
  Write-Manifest $M
  return $M
}

function Format-Summary($M) {
  Write-Output "manifest：$ManifestPath"
  Write-Output "状态：$($M['status'])  端口：$($M['port'])  PID：$($M['pid'])（创建 $($M['process_started_at'])）"
  Write-Output "提交：$($M['commit'])  wheel SHA-256：$($M['wheel']['sha256'])"
  Write-Output "包路径：$($M['package_path'])"
  Write-Output "数据目录：$($M['data_dir'])"
  Write-Output "stdout：$($M['stdout_path'])"
  Write-Output "stderr：$($M['stderr_path'])"
  if (@($M['models']).Count -eq 0) { Write-Output '部门模型：manifest 里还没有配置；在页面绑定好以后用 -ModelsFile 再运行 Inspect 更新' }
}

# ---- 核对 ----

function Invoke-Inspect($M) {
  $checks = New-Object System.Collections.Generic.List[object]
  function Add-Check([string]$Name, [bool]$Ok, [string]$Detail) { $checks.Add([pscustomobject]@{ 检查 = $Name; 结果 = $(if ($Ok) { '通过' } else { '未通过' }); 说明 = $Detail }) }

  $wheelPath = Resolve-ManifestPath $M['wheel']['path']
  $python = Resolve-ManifestPath $M['python']
  $workDir = Resolve-ManifestPath $M['working_directory']
  $portNumber = [int]$M['port']

  $wheelOk = $false
  if (Test-Path -LiteralPath $wheelPath -PathType Leaf) {
    $hash = (Get-FileHash -LiteralPath $wheelPath -Algorithm SHA256).Hash.ToLowerInvariant()
    $wheelOk = $hash -eq $M['wheel']['sha256']
    Add-Check 'wheel SHA-256' $wheelOk $(if ($wheelOk) { $hash } else { "文件是 $hash，manifest 记录 $($M['wheel']['sha256'])" })
  } else {
    Add-Check 'wheel SHA-256' $false "wheel 不存在：$wheelPath"
  }

  if ($wheelOk -and (Test-Path -LiteralPath $python -PathType Leaf) -and (Test-Path -LiteralPath $workDir -PathType Container)) {
    $identity = Test-PackageIdentity $python $wheelPath $workDir
    Add-Check '包身份（导入位置、非 editable、与 wheel 逐文件一致）' ([bool]$identity.ok) $(if ($identity.ok) { "$($identity.package_path)；比对 $($identity.wheel_files_checked) 个文件" } else { @($identity.problems) -join '；' })
    if ($identity.ok) {
      Add-Check '包路径与 manifest 一致' ($identity.package_path -eq (Resolve-ManifestPath $M['package_path'])) "实际 $($identity.package_path)；记录 $($M['package_path'])"
    }
  } else {
    Add-Check '包身份（导入位置、非 editable、与 wheel 逐文件一致）' $false '解释器、工作目录或 wheel 不可用，未能检查'
  }

  $info = Get-ProcessInfo ([int]$M['pid'])
  $alive = $false
  if (-not $info) {
    Add-Check '服务进程' $false "PID $($M['pid']) 不存在"
  } elseif (-not (Test-SameStart $M['process_started_at'] $info.StartedAt)) {
    Add-Check '服务进程' $false "PID $($M['pid']) 的创建时间是 $($info.StartedAt)，记录为 $($M['process_started_at'])"
  } else {
    $alive = $true
    $portArgument = "--port $portNumber"
    $commandOk = $info.CommandLine -match '\s-I\s' -and $info.CommandLine -match '-m\s+harness\s+api' -and $info.CommandLine.Contains($portArgument) -and $info.CommandLine.Contains([string]$M['data_dir'])
    Add-Check '服务进程' $commandOk $(if ($commandOk) { "PID $($info.Id)，创建 $($info.StartedAt)，命令行含 -I、harness api、端口与数据目录" } else { "命令行与记录不符：$($info.CommandLine)" })
  }

  $listenerId = Get-Listener $portNumber
  Add-Check "端口 $portNumber 的监听进程" ($listenerId -eq [int]$M['pid']) $(if ($listenerId) { "监听进程 $listenerId，记录 $($M['pid'])" } else { '没有进程监听' })

  $capabilities = Get-HttpStatus "http://127.0.0.1:$portNumber/api/capabilities"
  Add-Check '/api/capabilities' ($capabilities -and $capabilities.Status -eq 200) $(if ($capabilities) { "HTTP $($capabilities.Status)" } else { '连接失败' })
  $page = Get-HttpStatus "http://127.0.0.1:$portNumber/"
  Add-Check '页面 /' ($page -and $page.Status -eq 200 -and $page.ContentType -eq 'text/html') $(if ($page) { "HTTP $($page.Status) $($page.ContentType)" } else { '连接失败' })

  $ok = -not @($checks | Where-Object { $_.结果 -ne '通过' }).Count
  $status = if ($ok) { 'running' } elseif ($M['status'] -eq 'stopped' -and -not $alive) { 'stopped' } elseif ($alive) { 'unhealthy' } else { 'exited' }
  return [pscustomobject]@{ ok = $ok; status = $status; checks = $checks.ToArray() }
}

function Complete-Inspect($M, $Result) {
  if ($ModelsFile) { $M['models'] = Read-Models $ModelsFile }
  if (-not $NoWrite) {
    $M['status'] = $Result.status
    $M['identity_checked_at'] = Format-Utc (Get-Date)
    $M['checks'] = @($Result.checks | ForEach-Object { [ordered]@{ name = $_.检查; result = $_.结果; detail = $_.说明 } })
    Save-ToolIdentity $M
    Write-Manifest $M
  }
}

# ---- 入口 ----

switch ($Action) {
  'Start' {
    foreach ($required in 'Python', 'Wheel', 'Commit', 'DataDir', 'MaterialVersion', 'SkillCommit') {
      if (-not (Get-Variable $required -ValueOnly)) { throw "Start 需要 -$required" }
    }
    if ($Port -lt 1024 -or $Port -gt 65535) { throw 'Start 需要 -Port（1024–65535）' }
    if ($Commit -notmatch '^[0-9a-f]{7,40}$') { throw "-Commit 要写十六进制提交号：$Commit" }
    if (Test-Path -LiteralPath $ManifestPath) { throw "manifest 已存在：$ManifestPath（重启用 Restart，新一轮用新的 manifest 路径）" }
    if (-not $WorkingDirectory) { $WorkingDirectory = [System.IO.Path]::GetTempPath() }
    $m = [ordered]@{
      schema_version = 1
      commit = $Commit
      wheel = [ordered]@{ path = (Get-FullPath $Wheel); sha256 = '' }
      python = (Get-FullPath $Python)
      package_path = ''
      working_directory = (Get-FullPath $WorkingDirectory).TrimEnd('\')
      data_dir = (Get-FullPath $DataDir).TrimEnd('\')
      port = $Port
      pid = 0
      process_started_at = ''
      identity_checked_at = ''
      status = 'starting'
      task_set = $TaskSet
      material_version = $MaterialVersion
      skill_commit = $SkillCommit
      models = $(if ($ModelsFile) { Read-Models $ModelsFile } else { , @() })
      restart_count = 0
    }
    $m = Start-Server $m $true
    Format-Summary $m
  }
  'Inspect' {
    $m = Read-Manifest
    $result = Invoke-Inspect $m
    Complete-Inspect $m $result
    if ($PassThru) { return $result }
    $result.checks | Format-Table -AutoSize -Wrap | Out-String -Width 200 | Write-Output
    Format-Summary (Read-Manifest)
    if (-not $result.ok) { Write-Output "核对未通过，状态 $($result.status)"; exit 1 }
    Write-Output '核对通过。'
  }
  'Stop' {
    $m = Read-Manifest
    $port = [int]$m['port']
    $descendants = @()
    $info = Get-RecordedProcess ([int]$m['pid']) $m['process_started_at'] '服务进程'
    if ($m['launcher_pid'] -and [int]$m['launcher_pid'] -ne [int]$m['pid']) {
      $null = Get-RecordedProcess ([int]$m['launcher_pid']) $m['launcher_started_at'] '启动进程'
    }
    if ($info) {
      $descendants = @(Get-DescendantIds ([int]$m['pid']) | ForEach-Object { Get-ProcessInfo $_ } | Where-Object { $_ })
    }
    Write-Output (Stop-Recorded ([int]$m['pid']) $m['process_started_at'] '服务进程')
    if ($m['launcher_pid'] -and [int]$m['launcher_pid'] -ne [int]$m['pid']) {
      Write-Output (Stop-Recorded ([int]$m['launcher_pid']) $m['launcher_started_at'] '启动进程')
    }
    $deadline = (Get-Date).AddSeconds(15)
    while (Get-Listener $port) {
      if ((Get-Date) -gt $deadline) { throw "端口 $port 在停止后仍有进程监听" }
      Start-Sleep -Milliseconds 300
    }
    foreach ($child in $descendants) {
      $still = Get-ProcessInfo $child.Id
      if ($still -and (Test-SameStart $child.StartedAt $still.StartedAt)) { Write-Warning "后代进程 $($child.Id) 仍在运行，不在 manifest 内，未处理" }
    }
    $m['status'] = 'stopped'
    $m['stopped_at'] = Format-Utc (Get-Date)
    Write-Manifest $m
    Write-Output "实例已停止，数据目录保留：$($m['data_dir'])"
  }
  'Restart' {
    $m = Read-Manifest
    $m['wheel']['path'] = Resolve-ManifestPath $m['wheel']['path']
    $m['python'] = Resolve-ManifestPath $m['python']
    $m['working_directory'] = Resolve-ManifestPath $m['working_directory']
    $m['data_dir'] = Resolve-ManifestPath $m['data_dir']
    if ($ModelsFile) { $m['models'] = Read-Models $ModelsFile }
    if (-not (Test-Path -LiteralPath $m['wheel']['path'] -PathType Leaf)) { throw '重启需要原来的 wheel，当前文件不存在' }
    $wheelHash = (Get-FileHash -LiteralPath $m['wheel']['path'] -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($wheelHash -ne $m['wheel']['sha256']) { throw '重启的 wheel 摘要与原实例不同，保留当前进程' }
    $info = Get-RecordedProcess ([int]$m['pid']) $m['process_started_at'] '服务进程'
    if ($m['launcher_pid'] -and [int]$m['launcher_pid'] -ne [int]$m['pid']) {
      $null = Get-RecordedProcess ([int]$m['launcher_pid']) $m['launcher_started_at'] '启动进程'
    }
    # 全部输入与进程身份通过以后再停止原服务，当前端口只允许由记录的服务占用
    $allowedListener = if ($info) { [int]$info.Id } else { 0 }
    $null = Assert-ServerInputs $m $false $allowedListener
    # 重启前同一份 manifest 里的进程先停掉；进程已不在时只记录
    if ($info) {
      Write-Output (Stop-Recorded ([int]$m['pid']) $m['process_started_at'] '服务进程')
    }
    if ($m['launcher_pid'] -and [int]$m['launcher_pid'] -ne [int]$m['pid']) {
      Write-Output (Stop-Recorded ([int]$m['launcher_pid']) $m['launcher_started_at'] '启动进程')
    }
    $deadline = (Get-Date).AddSeconds(15)
    while (Get-Listener ([int]$m['port'])) {
      if ((Get-Date) -gt $deadline) { throw "端口 $($m['port']) 在停止后仍有进程监听" }
      Start-Sleep -Milliseconds 300
    }
    $m['restart_count'] = [int]$m['restart_count'] + 1
    $m['last_restart_at'] = Format-Utc (Get-Date)
    $m = Start-Server $m $false
    Format-Summary $m
  }
}
