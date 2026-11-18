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


def _probe(pwsh: Path, search_path: str, workdir: Path) -> dict[str, object]:
    probe = r"""
$ErrorActionPreference = 'Stop'
# pwsh 进程初始化会把自己的目录加到 PATH 前面，启动后再设置测试顺序。
$env:PATH = $env:ISSUE_1839_PATH
$manifestPath = Join-Path (Get-Location).ProviderPath 'manifest.json'
# 点载脚本只定义函数，Inspect 在独有的临时目录里读不到 manifest 后即停止。
try { . $env:ISSUE_1839_SCRIPT -Action Inspect -Manifest $manifestPath } catch {
  if ($_.Exception.Message -notlike "manifest 不存在：*") { throw }
}
$candidates = @(Get-Command pwsh -CommandType Application -ErrorAction SilentlyContinue | ForEach-Object Source)
$errorMessage = $null
$launch = $null
# 在进程启动边界运行真实解释器，但用无副作用的命令代替服务引导脚本。
function Assert-ServerInputs { }
function Start-Process {
  [CmdletBinding()]
  param([string]$FilePath, [string]$ArgumentList, [string]$WorkingDirectory, [string]$WindowStyle, [switch]$PassThru)
  $process = Microsoft.PowerShell.Management\Start-Process -FilePath $FilePath `
    -ArgumentList '-NoLogo -NoProfile -NonInteractive -Command exit 0' `
    -WorkingDirectory $WorkingDirectory -WindowStyle $WindowStyle -Wait -PassThru:$PassThru
  $script:launch = @{ file_path = $FilePath; window_style = $WindowStyle; exit_code = $process.ExitCode }
  throw [OperationCanceledException]::new('probe: process started')
}
$serverInputs = [ordered]@{
  python = 'unused.exe'
  working_directory = (Get-Location).ProviderPath
  data_dir = Join-Path (Get-Location).ProviderPath 'data'
  port = 18739
}
try { $null = Start-Server $serverInputs $true } catch [OperationCanceledException] {
  if (-not $launch) { throw }
} catch { $errorMessage = $_.Exception.Message }
@{ matches = $candidates; launch = $launch; error = $errorMessage } | ConvertTo-Json -Compress
"""
    encoded = base64.b64encode(probe.encode("utf-16le")).decode("ascii")
    environment = {key: os.environ[key] for key in ("SystemRoot", "WINDIR", "PATHEXT") if key in os.environ}
    environment.update(
        TEMP=str(workdir), TMP=str(workdir), ISSUE_1839_PATH=search_path, ISSUE_1839_SCRIPT=str(INSTANCE_SCRIPT),
    )
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
        result = _probe(Path(pwsh), os.pathsep.join(map(str, ordered_links)), tmp_path)
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
    empty_path = tmp_path / "empty-path"
    empty_path.mkdir()

    result = _probe(Path(pwsh), str(empty_path), tmp_path)

    assert result["matches"] == []
    assert result["launch"] is None
    assert result["error"] and "pwsh.exe" in result["error"] and "PATH" in result["error"]
