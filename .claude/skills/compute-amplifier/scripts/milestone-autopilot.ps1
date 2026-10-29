param([Parameter(Mandatory)][string]$Config)
$ErrorActionPreference = 'Stop'
& node (Join-Path $PSScriptRoot 'run.mjs') ([System.IO.Path]::GetFullPath($Config))
exit $LASTEXITCODE
