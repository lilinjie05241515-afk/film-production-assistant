[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][ValidateSet('env','verify','install','stage','status','check-update','switch','rollback','recover','host-plan','deactivate','uninstall','duplicates','migrate-entry','restore-entry')][string]$Action,
    [string]$Python,
    [Parameter(ValueFromRemainingArguments=$true)][string[]]$InstallerArguments
)
$ErrorActionPreference = 'Stop'
$installer = Join-Path $PSScriptRoot 'installer.py'
if (-not (Test-Path -LiteralPath $installer -PathType Leaf)) {
    throw '找不到同目录 installer.py；请完整解压发行包。'
}
$candidate = $null
if ($Python) {
    $candidate = (Resolve-Path -LiteralPath $Python).Path
} else {
    $launcher = Get-Command py -ErrorAction SilentlyContinue
    if ($launcher) {
        $detected = & $launcher.Source -3 -c 'import sys; print(sys.executable)' 2>$null
        if ($LASTEXITCODE -eq 0 -and $detected) { $candidate = [string]$detected[-1] }
        if ($detected -is [string] -and $LASTEXITCODE -eq 0) { $candidate = $detected }
    }
    if (-not $candidate) {
        $command = Get-Command python -ErrorAction SilentlyContinue
        if ($command) { $candidate = $command.Source }
    }
}
if (-not $candidate) {
    throw '需要 Windows Python 3.11 或更新版本（含 sqlite3）。请安装后重新执行；或用 -Python 指定 python.exe。安装器不会自动下载。'
}
& $candidate -B -X utf8 $installer env --python $candidate
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
if ($Action -eq 'env') { exit 0 }
$arguments = @('-B', '-X', 'utf8', $installer, $Action) + $InstallerArguments
if ($Action -in @('install', 'stage')) { $arguments += @('--python', $candidate) }
& $candidate @arguments
exit $LASTEXITCODE
