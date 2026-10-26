param([Parameter(Mandatory=$true)][string]$ConfigPath,[switch]$Open)
$ErrorActionPreference = 'Stop'
$siteConfig = Get-Content -Raw -LiteralPath $ConfigPath | ConvertFrom-Json
$siteOrigin = [uri]$siteConfig.origin
if ($siteOrigin.Scheme -ne 'https' -or $siteOrigin.UserInfo -or $siteOrigin.PathAndQuery -ne '/') { throw 'origin 必须是无路径、无凭据的 HTTPS 域名。' }
if (-not [IO.Path]::IsPathRooted($siteConfig.credential_path)) { throw 'credential_path 必须为显式绝对路径。' }
$siteCredential = Import-Clixml -LiteralPath $siteConfig.credential_path
if ($siteCredential -isnot [pscredential]) { throw '当前 Windows 用户不能读取这份凭据，请重新绑定。' }
$siteAuth = @{username=$siteCredential.UserName; password=$siteCredential.GetNetworkCredential().Password}
$env:FILMPROD_SITE_AUTH = ConvertTo-Json -InputObject $siteAuth -Compress
try {
    $siteArguments = @((Join-Path $PSScriptRoot 'site_browser.cjs'), '--config', $ConfigPath)
    if ($Open) { $siteArguments += '--open' }
    & node @siteArguments
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
} finally { Remove-Item Env:\FILMPROD_SITE_AUTH -ErrorAction SilentlyContinue }
