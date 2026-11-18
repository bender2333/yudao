import base64
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

INSTANCE_SCRIPT = Path(__file__).resolve().parents[2] / ".claude" / "skills" / "trial" / "scripts" / "instance.ps1"

pytestmark = pytest.mark.skipif(os.name != "nt", reason="instance.ps1 uses Windows PowerShell process semantics")


def _junction(path: Path, target: Path) -> None:
    subprocess.run(
        ["cmd.exe", "/d", "/c", "mklink", "/J", str(path), str(target)],
        check=True, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW, timeout=15,
    )


_PROBE_SETUP = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$manifestPath = Join-Path (Get-Location).ProviderPath 'manifest.json'
# 点载时执行 Inspect，遇到缺失的 manifest 后退出，已定义的函数保留。
try { . $env:ISSUE_1839_SCRIPT -Action Inspect -Manifest $manifestPath } catch {
  if ($_.Exception.Message -notlike "manifest 不存在：*") { throw }
}
# 这里只检查启动命令的选择，不要求工作目录装有试用 wheel。
function Assert-ServerInputs { }
$serverInputs = [ordered]@{
  python = 'unused.exe'
  working_directory = (Get-Location).ProviderPath
  data_dir = Join-Path (Get-Location).ProviderPath 'data'
  port = 18739
}
"""

_PATH_PROBE = r"""
# 保留启动及点载所需的 PATH，只在查找 pwsh 时使用测试路径。
$env:PATH = [string]$env:ISSUE_1839_PATH
$candidates = @(Get-Command pwsh -CommandType Application -ErrorAction SilentlyContinue | ForEach-Object Source)
$errorMessage = $null
$launch = $null
# 在进程启动边界运行真实解释器，但用无副作用的命令代替服务引导脚本。
function Start-Process {
  [CmdletBinding()]
  param([string]$FilePath, [string]$ArgumentList, [string]$WorkingDirectory, [string]$WindowStyle, [switch]$PassThru)
  $script:launch = @{ file_path = $FilePath; window_style = $WindowStyle }
  $process = Microsoft.PowerShell.Management\Start-Process -FilePath $FilePath `
    -ArgumentList '-NoLogo -NoProfile -NonInteractive -Command exit 0' `
    -WorkingDirectory $WorkingDirectory -WindowStyle $WindowStyle -Wait -PassThru:$PassThru
  $script:launch.exit_code = $process.ExitCode
  throw [OperationCanceledException]::new('probe: process started')
}
try { $null = Start-Server $serverInputs $true } catch [OperationCanceledException] {
  if (-not $launch) { throw }
} catch { $errorMessage = $_.Exception.Message }
@{ matches = $candidates; launch = $launch; error = $errorMessage } | ConvertTo-Json -Compress
"""


def _run_probe(
    pwsh: Path, workdir: Path, probe: str, *, search_path: str | None = None,
) -> dict[str, object]:
    encoded = base64.b64encode((_PROBE_SETUP + probe).encode("utf-16le")).decode("ascii")
    system_keys = ("PSModulePath", "SystemRoot", "WINDIR", "PATHEXT")
    environment = {key: os.environ[key] for key in system_keys if key in os.environ}
    environment.update(
        PATH=os.environ["PATH"], TEMP=str(workdir), TMP=str(workdir),
        ISSUE_1839_SCRIPT=str(INSTANCE_SCRIPT),
    )
    if search_path is not None:
        environment["ISSUE_1839_PATH"] = search_path
    result = subprocess.run(
        [str(pwsh), "-NoLogo", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
        cwd=workdir, env=environment, capture_output=True, text=True, encoding="utf-8", errors="replace",
        creationflags=subprocess.CREATE_NO_WINDOW, timeout=30,
    )
    assert result.returncode == 0, f"pwsh probe failed ({result.returncode}): {result.stderr}"
    output = [line for line in result.stdout.splitlines() if line.strip()]
    assert output, f"pwsh probe returned no result: {result.stderr}"
    return json.loads(output[-1])


# R3：已安装的试用工作台按 PATH 优先顺序启动隐藏的 PowerShell。
@pytest.mark.parametrize("candidate_count", [1, 2], ids=["single-match", "multiple-matches"])
def test_instance_start_uses_first_pwsh_application_in_path(tmp_path: Path, candidate_count: int) -> None:
    pwsh = shutil.which("pwsh")
    assert pwsh, "Windows test runner must have PowerShell 7 on PATH"
    home = Path(pwsh).parent
    links = [tmp_path / f"pwsh-{index}" for index in range(candidate_count)]
    try:
        for link in links:
            _junction(link, home)
        ordered_links = list(reversed(links))
        expected = ordered_links[0] / "pwsh.exe"
        search_path = os.pathsep.join(map(str, ordered_links))
        result = _run_probe(Path(pwsh), tmp_path, _PATH_PROBE, search_path=search_path)
        assert result["matches"] == [str(link / "pwsh.exe") for link in ordered_links]
        assert result["error"] is None, result["error"]
        assert result["launch"] == {"file_path": str(expected), "window_style": "Hidden", "exit_code": 0}
    finally:
        for link in links:
            if link.exists():
                os.rmdir(link)


# R3：无可用 PowerShell 时，试用启动给出可诊断的错误。
def test_instance_start_reports_when_pwsh_is_missing(tmp_path: Path) -> None:
    pwsh = shutil.which("pwsh")
    assert pwsh, "Windows test runner must have PowerShell 7 on PATH"
    probe = r"""
$lookedUpPwsh = $false
$launchAttempted = $false
$errorMessage = $null
# 只替换 pwsh 的候选查询，保留运行机的 PATH，不执行外部启动。
function Get-Command {
  [CmdletBinding()]
  param([string]$Name, [System.Management.Automation.CommandTypes]$CommandType)
  if ($Name -eq 'pwsh' -and $CommandType -eq 'Application') {
    $script:lookedUpPwsh = $true
    return
  }
  Microsoft.PowerShell.Core\Get-Command @PSBoundParameters
}
function Start-Process {
  $script:launchAttempted = $true
  throw '探针：不应尝试启动服务'
}
try { $null = Start-Server $serverInputs $true } catch { $errorMessage = $_.Exception.Message }
@{ looked_up_pwsh = $lookedUpPwsh; launch_attempted = $launchAttempted; error = $errorMessage } | ConvertTo-Json -Compress
"""
    result = _run_probe(Path(pwsh), tmp_path, probe)

    assert result["looked_up_pwsh"] is True, result
    assert result["launch_attempted"] is False, result
    error = result["error"]
    assert isinstance(error, str) and "pwsh.exe" in error and "PATH" in error, result
