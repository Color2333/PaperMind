# pm CLI 一键安装（Windows，PowerShell）
#
# 用法：
#   irm https://raw.githubusercontent.com/Color2333/PaperMind/main/scripts/install-pm.ps1 | iex
#
# 从 GitHub Releases 下载 pm-windows-x86_64.exe 到 %LOCALAPPDATA%\Programs\pm
$ErrorActionPreference = "Stop"

$Repo = "Color2333/PaperMind"
$InstallDir = "$env:LOCALAPPDATA\Programs\pm"
$Asset = "pm-windows-x86_64.exe"
$Url = "https://github.com/$Repo/releases/latest/download/$Asset"

Write-Host "下载 $Url"
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
$Dest = Join-Path $InstallDir "pm.exe"
Invoke-WebRequest -Uri $Url -OutFile $Dest

Write-Host ""
Write-Host "✓ 安装到 $Dest"
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
if ($userPath -notlike "*$InstallDir*") {
    [Environment]::SetEnvironmentVariable("Path", "$userPath;$InstallDir", "User")
    Write-Host "✓ 已加入用户 PATH（新开终端生效）"
}

& $Dest --version
Write-Host ""
Write-Host "接下来: pm login --server https://你的-papermind-地址"
