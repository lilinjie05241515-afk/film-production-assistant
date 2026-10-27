param(
    [Parameter(Mandatory=$true)][string]$ConfigPath,
    [Parameter(Mandatory=$true)][string]$UserName
)
$ErrorActionPreference = 'Stop'
$siteConfig = Get-Content -Raw -LiteralPath $ConfigPath | ConvertFrom-Json
$siteOrigin = [uri]$siteConfig.origin
if ($siteOrigin.Scheme -ne 'https' -or $siteOrigin.UserInfo -or $siteOrigin.PathAndQuery -ne '/') { throw 'origin 必须是无路径、无凭据的 HTTPS 域名。' }
if (-not [IO.Path]::IsPathRooted($siteConfig.credential_path)) { throw 'credential_path 必须是用户选定配置目录内的绝对路径。' }
$siteCredentialPath = [IO.Path]::GetFullPath($siteConfig.credential_path)
if (Test-Path -LiteralPath $siteCredentialPath) { throw '凭据文件已存在；保留旧文件并为轮换指定新文件名。' }
$sitePassword = Read-Host ('Password for ' + $siteOrigin.GetLeftPart([UriPartial]::Authority)) -AsSecureString
if ($sitePassword.Length -eq 0) { throw 'No password was entered; credential was not saved.' }
New-Item -ItemType Directory -Path ([IO.Path]::GetDirectoryName($siteCredentialPath)) -Force | Out-Null
$siteCredential = [pscredential]::new($UserName, $sitePassword)
$siteCredential | Export-Clixml -LiteralPath $siteCredentialPath
$siteSaved = Import-Clixml -LiteralPath $siteCredentialPath
if ($siteSaved.UserName -ne $UserName) { throw 'Credential verification failed.' }
Write-Output '凭据已由当前 Windows 用户保护；新设备需重新绑定。'
