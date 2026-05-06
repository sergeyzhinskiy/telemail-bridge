<#
.SYNOPSIS
    Удаление TeleMail Bridge с Windows
#>

#Requires -RunAsAdministrator

$ErrorActionPreference = "Stop"

Write-Host "⚠️ ВНИМАНИЕ: Полное удаление TeleMail Bridge!" -ForegroundColor Red
Write-Host "Будут удалены: все файлы, база данных, службы."
Write-Host ""

$confirm = Read-Host "Введите DELETE для подтверждения"
if ($confirm -ne "DELETE") {
    Write-Host "Отмена."
    exit 0
}

Write-Host "Удаление..." -ForegroundColor Yellow

# Остановка служб
$services = @("TeleMailBot", "TeleMailReceiver", "TeleMailWorker", "TeleMailBeat", "TeleMailAdmin", "TeleMailNginx")
foreach ($svc in $services) {
    Stop-Service $svc -ErrorAction SilentlyContinue
    & "C:\Windows\System32\nssm.exe" remove $svc confirm 2>$null
}

# Удаление файлов
$paths = @(
    "C:\TeleMailBridge",
    "C:\Program Files\PostgreSQL\16\data",
    "C:\Program Files\Redis"
)

foreach ($path in $paths) {
    if (Test-Path $path) {
        Remove-Item $path -Recurse -Force -ErrorAction SilentlyContinue
        Write-Host "Удалено: $path"
    }
}

# Удаление ярлыков
$desktop = [Environment]::GetFolderPath("Desktop")
Remove-Item "$desktop\TeleMail Admin.url" -ErrorAction SilentlyContinue
Remove-Item "$desktop\TeleMail Управление.lnk" -ErrorAction SilentlyContinue

# Удаление из PATH
$currentPath = [Environment]::GetEnvironmentVariable("Path", "Machine")
$currentPath = $currentPath -replace [regex]::Escape(";C:\Program Files\PostgreSQL\16\bin"), ""
[Environment]::SetEnvironmentVariable("Path", $currentPath, "Machine")

Write-Host "✅ TeleMail Bridge удалён." -ForegroundColor Green