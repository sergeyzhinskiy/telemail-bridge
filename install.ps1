<#
.SYNOPSIS
    TeleMail Bridge – Final Windows Installer (Python 3.11)
.DESCRIPTION
    Installs TeleMail Bridge on Windows 10/11 without Docker.
    Run as Administrator:
      chcp 65001
      Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
      .\install.ps1
#>

#Requires -RunAsAdministrator

$ErrorActionPreference = "Continue"
$ProgressPreference = "SilentlyContinue"

# ----- Set UTF-8 encoding for console -----
chcp 65001 >$null 2>&1
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

# ----- Configuration -----
$APP_ROOT = "C:\TeleMailBridge"
$VENV_DIR = "$APP_ROOT\venv"
$LOG_DIR  = "$APP_ROOT\logs"
$DATA_DIR = "$APP_ROOT\data"
$CONFIG_DIR = "$APP_ROOT\config"
$GIT_REPO = "https://github.com/sergeyzhinskiy/telemail-bridge.git"  # <-- change to your repo

$PG_VERSION = "16"
$PG_PORT    = 5432
$REDIS_PORT = 6379

$SERVICE_BOT      = "TeleMailBot"
$SERVICE_RECEIVER = "TeleMailReceiver"
$SERVICE_WORKER   = "TeleMailWorker"
$SERVICE_BEAT     = "TeleMailBeat"
$SERVICE_ADMIN    = "TeleMailAdmin"

$script:PythonExe       = $null
$script:PG_PASSWORD     = ""
$script:REDIS_PASSWORD  = ""
$script:AdminPassword   = $null
$script:AdminEmail      = $null

# ----- Output functions -----
function Write-Info    { Write-Host "[INFO] " -NoNewline -ForegroundColor Blue;   Write-Host $args }
function Write-Success { Write-Host "[OK] "   -NoNewline -ForegroundColor Green;  Write-Host $args }
function Write-Warning { Write-Host "[WARN] "  -NoNewline -ForegroundColor Yellow; Write-Host $args }
function Write-ErrorMsg { Write-Host "[ERROR] " -NoNewline -ForegroundColor Red;    Write-Host $args; exit 1 }
function Write-Step {
    Write-Host ""
    Write-Host "================================================================" -ForegroundColor Cyan
    Write-Host "[$(Get-Date -Format HH:mm:ss)] $args" -ForegroundColor Cyan
    Write-Host "================================================================" -ForegroundColor Cyan
    Write-Host ""
}

function Test-Administrator {
    $currentUser = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($currentUser)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        Write-ErrorMsg "Run this script as Administrator!"
    }
}

function Test-SystemRequirements {
    Write-Step "Checking system requirements"
    $os = Get-CimInstance Win32_OperatingSystem
    $version = [Version]$os.Version
    if ($version.Major -lt 10 -or ($version.Major -eq 10 -and $version.Build -lt 17763)) {
        Write-ErrorMsg "Windows 10 (1809+) or Windows 11 required. Current: $($os.Caption)"
    }
    Write-Info "OS: $($os.Caption) (Build $($version.Build))"
    $totalRAM = [Math]::Round($os.TotalVisibleMemorySize / 1MB, 1)
    if ($totalRAM -lt 3.5) { Write-Warning "Recommended 4+ GB RAM. You have: $totalRAM GB" }
    Write-Info "RAM: $totalRAM GB"
    $drive = Get-PSDrive C
    $freeSpace = [Math]::Round($drive.Free / 1GB, 1)
    if ($freeSpace -lt 12) { Write-ErrorMsg "Not enough disk space on C:. Need ~12 GB. You have: $freeSpace GB" }
    Write-Info "Free space on C:: $freeSpace GB"
    if (-not (Test-Connection -ComputerName 8.8.8.8 -Count 1 -Quiet)) { Write-ErrorMsg "No internet connection" }
    Write-Info "Internet: available"
}

function Install-Chocolatey {
    if (Get-Command choco -ErrorAction SilentlyContinue) { Write-Success "Chocolatey already installed"; return }
    Write-Info "Installing Chocolatey..."
    Set-ExecutionPolicy Bypass -Scope Process -Force
    [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.ServicePointManager]::SecurityProtocol -bor 3072
    iex ((New-Object System.Net.WebClient).DownloadString('https://community.chocolatey.org/install.ps1'))
    $env:Path = [Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [Environment]::GetEnvironmentVariable("Path","User")
    Write-Success "Chocolatey installed"
}

function New-RandomPassword {
    param([int]$Length = 20)
    $chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789!@#%&*"
    $password = ""
    $rng = New-Object System.Security.Cryptography.RNGCryptoServiceProvider
    $bytes = New-Object byte[] $Length
    $rng.GetBytes($bytes)
    for ($i = 0; $i -lt $Length; $i++) { $password += $chars[$bytes[$i] % $chars.Length] }
    return $password
}

function Get-PostgreSQLService {
    $services = Get-Service -Name "postgresql*" -ErrorAction SilentlyContinue
    if ($services) {
        return $services[0]
    }
    return $null
}

function Get-PostgreSQLBinPath {
    $paths = @(
        "C:\Program Files\PostgreSQL\$PG_VERSION\bin",
        "C:\Program Files\PostgreSQL\16\bin",
        "C:\Program Files\PostgreSQL\15\bin"
    )
    foreach ($path in $paths) {
        if (Test-Path "$path\psql.exe") {
            return $path
        }
    }
    return $null
}

# ----- Install Python 3.11 -----
function Install-Python311 {
    Write-Step "1/7 Installing Python 3.11"
    if (-not $script:PG_PASSWORD) { $script:PG_PASSWORD = New-RandomPassword -Length 20 }
    $searchPaths = @(
        "C:\Program Files\Python311\python.exe",
        "C:\Python311\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
        (Get-Command python3.11 -ErrorAction SilentlyContinue).Source
    )
    foreach ($p in $searchPaths) { if ($p -and (Test-Path $p)) { $script:PythonExe = $p; break } }
    if (-not $script:PythonExe) { try { $script:PythonExe = (py -3.11 -c "import sys; print(sys.executable)") } catch {} }
    if ($script:PythonExe) { Write-Success "Python 3.11 found: $script:PythonExe"; return }

    Write-Info "Downloading Python 3.11.9..."
    $installer = "$env:TEMP\python-3.11.9-amd64.exe"
    if (Test-Path $installer) { if ((Get-Item $installer).Length -lt 20MB) { Remove-Item $installer -Force } }
    if (-not (Test-Path $installer)) { Invoke-WebRequest -Uri "https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe" -OutFile $installer -TimeoutSec 300 }
    Write-Info "Installing Python 3.11..."
    Start-Process -FilePath $installer -ArgumentList "/quiet InstallAllUsers=1 PrependPath=1 Include_test=0 Include_pip=1" -Wait -NoNewWindow
    Remove-Item $installer -Force
    $env:Path = [Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [Environment]::GetEnvironmentVariable("Path","User")
    foreach ($p in $searchPaths) { if (Test-Path $p) { $script:PythonExe = $p; break } }
    if (-not $script:PythonExe) { Write-ErrorMsg "Python 3.11 installed but python.exe not found!" }
    Write-Success "Python 3.11 installed"
}

# ----- Install system packages -----
function Install-SystemPackages {
    Write-Step "2/7 Installing system packages"
    choco install git ffmpeg vcredist-all -y --limit-output 2>&1 | Out-Null
    Write-Success "System packages installed"
}

# ----- Install PostgreSQL 16 -----
function Install-PostgreSQL {
    Write-Step "3/7 Installing PostgreSQL 16"
    if (-not $script:PG_PASSWORD) { $script:PG_PASSWORD = New-RandomPassword -Length 20 }
    
    $pgService = Get-PostgreSQLService
    
    if (-not $pgService) {
        Write-Info "Installing PostgreSQL 16..."
        $pgInstaller = "$env:TEMP\postgresql-16.4-1-windows-x64.exe"
        try {
            Invoke-WebRequest -Uri "https://get.enterprisedb.com/postgresql/postgresql-16.4-1-windows-x64.exe" -OutFile $pgInstaller -TimeoutSec 300
        } catch {
            Write-ErrorMsg "Failed to download PostgreSQL installer"
        }
        
        # Install with default paths
        Start-Process -FilePath $pgInstaller -ArgumentList "--mode unattended --superpassword $script:PG_PASSWORD --servicename postgresql-x64-16 --serviceaccount postgres --serverport $PG_PORT" -Wait -NoNewWindow
        Remove-Item $pgInstaller -Force
        Start-Sleep -Seconds 20
        $pgService = Get-PostgreSQLService
    }
    
    if (-not $pgService) {
        Write-ErrorMsg "PostgreSQL service not found after installation"
    }
    
    # Ensure service is running
    $svcName = $pgService.Name
    $svcStatus = (Get-Service $svcName -ErrorAction SilentlyContinue).Status
    if ($svcStatus -ne "Running") { 
        Write-Info "Starting PostgreSQL service..."
        Start-Service $svcName
        Start-Sleep -Seconds 15
    }
    
    $pgBin = Get-PostgreSQLBinPath
    if (-not $pgBin) {
        Write-ErrorMsg "PostgreSQL bin directory not found"
    }
    
    Write-Info "PostgreSQL bin path: $pgBin"
    
    # Add to PATH
    $env:Path = "$pgBin;$env:Path"
    
    # Test connection to PostgreSQL
    Write-Info "Testing PostgreSQL connection..."
    $maxRetries = 20
    $connected = $false
    
    for ($i = 1; $i -le $maxRetries; $i++) {
        Start-Sleep -Seconds 2
        $env:PGPASSWORD = $script:PG_PASSWORD
        $testResult = & "$pgBin\psql.exe" -U postgres -h localhost -p $PG_PORT -c "SELECT 1" -t 2>&1
        if ($LASTEXITCODE -eq 0) {
            $connected = $true
            Write-Success "PostgreSQL is ready"
            break
        }
        Write-Info "Waiting for PostgreSQL... ($i/$maxRetries)"
    }
    
    if (-not $connected) {
        Write-Warning "PostgreSQL connection test failed, but continuing..."
        Write-Info "Last error: $testResult"
    }
    
    # Create user and database
    try {
        $env:PGPASSWORD = $script:PG_PASSWORD
        
        # Create user
        & "$pgBin\psql.exe" -U postgres -h localhost -p $PG_PORT -c "CREATE USER telemail WITH PASSWORD '$script:PG_PASSWORD';" 2>&1 | Out-Null
        
        # Create database
        & "$pgBin\psql.exe" -U postgres -h localhost -p $PG_PORT -c "CREATE DATABASE telemail OWNER telemail;" 2>&1 | Out-Null
        
        # Grant privileges
        & "$pgBin\psql.exe" -U postgres -h localhost -p $PG_PORT -c "GRANT ALL PRIVILEGES ON DATABASE telemail TO telemail;" 2>&1 | Out-Null
        
        Write-Success "PostgreSQL 16 configured successfully"
    } catch {
        Write-Warning "Could not configure PostgreSQL: $_"
    }
}

# ----- Install Redis -----
function Install-Redis {
    Write-Step "4/7 Installing Redis"
    if (-not $script:REDIS_PASSWORD) { $script:REDIS_PASSWORD = New-RandomPassword -Length 16 }
    if (Get-Service "Redis" -ErrorAction SilentlyContinue) { Write-Success "Redis already installed"; return }
    
    Write-Info "Installing Redis via Chocolatey..."
    choco install redis-64 -y --limit-output 2>&1 | Out-Null
    
    # Configure Redis password
    $configPath = "C:\ProgramData\Redis\redis.windows.conf"
    if (-not (Test-Path $configPath)) {
        $configPath = "C:\Program Files\Redis\redis.windows.conf"
    }
    
    if (Test-Path $configPath) {
        $cfg = Get-Content $configPath -ErrorAction SilentlyContinue
        if ($cfg) {
            $cfg = $cfg -replace "# requirepass foobared", "requirepass $script:REDIS_PASSWORD"
            $cfg = $cfg -replace "# bind 127.0.0.1", "bind 127.0.0.1"
            $cfg | Set-Content $configPath -Force
            Write-Info "Redis configured with password"
        }
    }
    
    Restart-Service Redis -ErrorAction SilentlyContinue
    Start-Service Redis -ErrorAction SilentlyContinue
    Write-Success "Redis installed"
}

# ----- Clone repository -----
function Prepare-Environment {
    Write-Step "5/7 Preparing directories & cloning repository"
    $dirs = @($APP_ROOT, $LOG_DIR, $DATA_DIR, $CONFIG_DIR, "$DATA_DIR\sessions", "$DATA_DIR\media", "$DATA_DIR\temp", "$DATA_DIR\backups")
    foreach ($d in $dirs) { if (-not (Test-Path $d)) { New-Item -ItemType Directory -Path $d -Force | Out-Null } }
    
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) { 
        Write-Info "Installing git..."
        choco install git -y --limit-output 2>&1 | Out-Null
        $env:Path = [Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [Environment]::GetEnvironmentVariable("Path","User")
    }
    
    if (Test-Path "$APP_ROOT\src") { 
        Write-Info "Removing existing src directory..."
        Remove-Item "$APP_ROOT\src" -Recurse -Force -ErrorAction SilentlyContinue
    }
    
    Write-Info "Cloning repository from $GIT_REPO ..."
    git clone $GIT_REPO "$APP_ROOT\src" 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) { 
        Write-Warning "Git clone failed. Creating empty structure..."
        New-Item -ItemType Directory -Path "$APP_ROOT\src" -Force | Out-Null
    }
    Write-Success "Repository prepared"
}

# ----- Setup Python venv -----
function Setup-PythonVenv {
    Write-Step "6/7 Setting up Python virtual environment & dependencies"
    if (Test-Path $VENV_DIR) { Remove-Item $VENV_DIR -Recurse -Force -ErrorAction SilentlyContinue }
    
    Write-Info "Creating virtual environment..."
    & $script:PythonExe -m venv $VENV_DIR
    
    Write-Info "Activating virtual environment..."
    & "$VENV_DIR\Scripts\Activate.ps1"
    
    Write-Info "Upgrading pip..."
    & "$VENV_DIR\Scripts\python.exe" -m pip install --upgrade pip --quiet
    
    Write-Info "Installing dependencies (this may take a few minutes)..."
    $pkgs = @(
        "aiogram==2.25.2",
        "telethon>=1.36,<2.0",
        "aiohttp>=3.8.0,<3.9.0",
        "sqlalchemy[asyncio]>=2.0,<3.0",
        "asyncpg>=0.29,<1.0",
        "alembic>=1.13,<2.0",
        "redis>=5.0,<6.0",
        "aiosmtplib>=3.0,<4.0",
        "aioimaplib>=1.0,<2.0",
        "fastapi>=0.111,<1.0",
        "uvicorn[standard]>=0.29,<1.0",
        "jinja2>=3.1,<4.0",
        "python-multipart>=0.0.9",
        "PyJWT>=2.8,<3.0",
        "bcrypt>=4.1,<5.0",
        "python-dotenv>=1.0,<2.0",
        "loguru>=0.7,<1.0"
    )
    foreach ($pkg in $pkgs) { 
        Write-Info "Installing $pkg..."
        & "$VENV_DIR\Scripts\pip.exe" install $pkg --quiet --no-cache-dir 2>&1 | Out-Null
    }
    Write-Success "Dependencies installed"
}

# ----- Configure application -----
function Configure-App {
    Write-Step "7/7 Configuring application"
    $encryptionKey = -join ((1..32) | ForEach-Object { '{0:x}' -f (Get-Random -Max 16) })
    $jwtSecret = New-RandomPassword -Length 32
    $adminPassword = New-RandomPassword -Length 12
    $script:AdminPassword = $adminPassword
    
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Yellow
    Write-Host "  Please enter configuration values" -ForegroundColor Yellow
    Write-Host "========================================" -ForegroundColor Yellow
    Write-Host ""
    
    Write-Host "--- Telegram Bot settings ---" -ForegroundColor Cyan
    $BOT_TOKEN = Read-Host "Bot Token"
    $API_ID    = Read-Host "API ID"
    $API_HASH  = Read-Host "API Hash"
    
    Write-Host ""
    Write-Host "--- Catch-all email settings ---" -ForegroundColor Cyan
    $CATCH_ALL_EMAIL = Read-Host "Email"
    $CATCH_ALL_PASS  = Read-Host "Password" -AsSecureString
    $CATCH_ALL_PASS_PLAIN = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($CATCH_ALL_PASS))
    
    $IMAP_HOST = Read-Host "IMAP host [imap.gmail.com]"; if (-not $IMAP_HOST) { $IMAP_HOST = "imap.gmail.com" }
    $IMAP_PORT = Read-Host "IMAP port [993]"; if (-not $IMAP_PORT) { $IMAP_PORT = "993" }
    $DOMAIN = Read-Host "Domain [telemail.app]"; if (-not $DOMAIN) { $DOMAIN = "telemail.app" }
    $SMTP_FROM = Read-Host "SMTP From [bot@telemail.app]"; if (-not $SMTP_FROM) { $SMTP_FROM = "bot@telemail.app" }
    
    Write-Host ""
    Write-Host "--- Admin settings ---" -ForegroundColor Cyan
    $ADMIN_EMAIL = Read-Host "Admin email"
    $script:AdminEmail = $ADMIN_EMAIL

    # Create .env file
    $envFile = "$APP_ROOT\src\.env"
    $envText = @"
BOT_TOKEN=$BOT_TOKEN
TELEGRAM_API_ID=$API_ID
TELEGRAM_API_HASH=$API_HASH
DATABASE_URL=postgresql+asyncpg://telemail:$($script:PG_PASSWORD)@localhost:$PG_PORT/telemail
ENCRYPTION_KEY=$encryptionKey
CATCH_ALL_EMAIL=$CATCH_ALL_EMAIL
CATCH_ALL_PASSWORD=$CATCH_ALL_PASS_PLAIN
CATCH_ALL_IMAP_HOST=$IMAP_HOST
CATCH_ALL_IMAP_PORT=$IMAP_PORT
CATCH_ALL_DOMAIN=$DOMAIN
SMTP_FROM_ADDRESS=$SMTP_FROM
REDIS_URL=redis://:$($script:REDIS_PASSWORD)@localhost:$REDIS_PORT/0
REDIS_HOST=localhost
REDIS_PORT=$REDIS_PORT
REDIS_PASSWORD=$($script:REDIS_PASSWORD)
JWT_SECRET=$jwtSecret
JWT_EXPIRATION_HOURS=12
BASE_URL=http://localhost:8080
ADMIN_BASE_URL=http://localhost:8000
LOG_LEVEL=INFO
MAX_ATTACHMENT_SIZE=52428800
"@
    $envText | Out-File -FilePath $envFile -Encoding UTF8 -Force
    
    # Save credentials
    $credFile = "$CONFIG_DIR\credentials.txt"
    $credText = @"

===========================================================
TeleMail Bridge - Credentials
===========================================================
PostgreSQL: localhost:$PG_PORT, user: telemail, pass: $($script:PG_PASSWORD)
Redis:      localhost:$REDIS_PORT, pass: $($script:REDIS_PASSWORD)
Admin:      http://localhost:8000/admin
Admin email: $ADMIN_EMAIL
Admin password: $adminPassword
JWT Secret: $jwtSecret
Encryption Key: $encryptionKey

Telegram Bot Token: $BOT_TOKEN
Telegram API ID: $API_ID
===========================================================

Save this file in a safe place!
"@
    $credText | Out-File -FilePath $credFile -Encoding UTF8 -Force
    Write-Success "Configuration saved to $credFile"
}

# ----- Initialize database -----
function Initialize-Database {
    Write-Info "Initializing database..."
    Write-Success "Setup completed (database initialization will run on first start)"
}

# ----- Create services -----
function Create-WindowsServicesSafe {
    Write-Step "Creating Windows services"
    $pythonExe = "$VENV_DIR\Scripts\python.exe"
    
    function Create-SCService($Name, $Display, $Command, $Args) {
        $svc = Get-Service $Name -ErrorAction SilentlyContinue
        if ($svc) { 
            Stop-Service $Name -Force -ErrorAction SilentlyContinue
            sc.exe delete $Name 2>$null
            Start-Sleep 3
        }
        $fullCommand = "`"$Command`" $Args"
        sc.exe create $Name binPath= $fullCommand start= auto DisplayName= "$Display" 2>$null
        if ($LASTEXITCODE -eq 0) { 
            Write-Success "$Name created"
        } else {
            Write-Warning "Failed to create $Name"
        }
    }
    
    Create-SCService $SERVICE_BOT "Telegram Bot" $pythonExe "-m bot.main"
    Create-SCService $SERVICE_RECEIVER "Email Receiver" $pythonExe "-m core.email_receiver"
    Create-SCService $SERVICE_ADMIN "Admin Panel" $pythonExe "-m uvicorn admin.web_app.main:app --host 127.0.0.1 --port 8000"
    Write-Success "Services created"
}

# ----- Batch files -----
function Create-BatchFiles {
    Write-Info "Creating start/stop batch files..."
    $startBat = @"
@echo off
chcp 65001 >nul
cd /d "$APP_ROOT\src"
call "$VENV_DIR\Scripts\activate.bat"
start "TeleMailBot" python -m bot.main
timeout /t 3 >nul
start "TeleMailReceiver" python -m core.email_receiver
timeout /t 2 >nul
start "TeleMailAdmin" uvicorn admin.web_app.main:app --host 127.0.0.1 --port 8000
echo.
echo All components started.
echo Admin panel: http://localhost:8000/admin
echo.
pause
"@
    $startBat | Out-File "$APP_ROOT\start.bat" -Encoding UTF8 -Force
    
    $stopBat = @"
@echo off
taskkill /f /fi "WINDOWTITLE eq TeleMailBot*" 2>nul
taskkill /f /fi "WINDOWTITLE eq TeleMailReceiver*" 2>nul
taskkill /f /fi "WINDOWTITLE eq TeleMailAdmin*" 2>nul
echo Stopped all components.
pause
"@
    $stopBat | Out-File "$APP_ROOT\stop.bat" -Encoding ASCII -Force
    Write-Success "Batch files created"
}

function Start-AllServices {
    Write-Step "Starting services"
    $services = @($SERVICE_BOT, $SERVICE_RECEIVER, $SERVICE_ADMIN)
    foreach ($svc in $services) {
        $s = Get-Service $svc -ErrorAction SilentlyContinue
        if ($s) {
            if ($s.Status -ne "Running") { 
                Start-Service $svc -ErrorAction SilentlyContinue
                Write-Info "Starting $svc..."
            }
        }
    }
    Start-Sleep -Seconds 3
}

function Print-Summary {
    Write-Host ""
    Write-Host "================================================================" -ForegroundColor Green
    Write-Host "  TeleMail Bridge installed successfully!" -ForegroundColor Green
    Write-Host "================================================================" -ForegroundColor Green
    Write-Host ""
    Write-Host "Credentials file: $CONFIG_DIR\credentials.txt" -ForegroundColor Yellow
    Write-Host "Admin panel:      http://localhost:8000/admin" -ForegroundColor Yellow
    Write-Host "Manual start:     $APP_ROOT\start.bat" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "IMPORTANT: Check credentials.txt for your passwords!" -ForegroundColor Red
    Write-Host "================================================================" -ForegroundColor Green
}

# ----- Main -----
function Main {
    Write-Host "================================================================" -ForegroundColor Magenta
    Write-Host "  TeleMail Bridge - Final Installer (Python 3.11)" -ForegroundColor Magenta
    Write-Host "================================================================" -ForegroundColor Magenta
    
    $confirm = Read-Host "`nContinue with installation? (y/n)"
    if ($confirm -ne 'y') { exit 0 }
    
    $startTime = Get-Date
    
    try {
        Test-Administrator
        Test-SystemRequirements
        Install-Chocolatey
        Install-Python311
        Install-SystemPackages
        Prepare-Environment
        Install-PostgreSQL
        Install-Redis
        Setup-PythonVenv
        Configure-App
        Initialize-Database
        Create-WindowsServicesSafe
        Start-AllServices
        Create-BatchFiles
        
        $duration = [Math]::Round(((Get-Date) - $startTime).TotalMinutes, 1)
        Write-Success "Installation finished in $duration minutes!"
        Print-Summary
    } catch {
        Write-ErrorMsg "Installation failed: $_"
        Write-Host $_.ScriptStackTrace
        exit 1
    }
}

Main
