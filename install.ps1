<#
.SYNOPSIS
    TeleMail Bridge – Fully Automatic Windows Installer (Python 3.11)
.DESCRIPTION
    Complete one-click installer. No manual steps required.
    Run as Administrator:
      Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
      .\install.ps1
#>

#Requires -RunAsAdministrator

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
chcp 65001 >$null 2>&1
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

# ===== CONFIGURATION =====
$APP_ROOT = "C:\TeleMailBridge"
$VENV_DIR = "$APP_ROOT\venv"
$LOG_DIR  = "$APP_ROOT\logs"
$DATA_DIR = "$APP_ROOT\data"
$CONFIG_DIR = "$APP_ROOT\config"
$GIT_REPO = "https://github.com/yourusername/telemail-bridge.git"

$PG_VERSION = "16"
$PG_PORT    = 5432
$REDIS_PORT = 6379

$SERVICE_BOT      = "TeleMailBot"
$SERVICE_RECEIVER = "TeleMailReceiver"
$SERVICE_WORKER   = "TeleMailWorker"
$SERVICE_BEAT     = "TeleMailBeat"
$SERVICE_ADMIN    = "TeleMailAdmin"

# ===== GLOBAL VARIABLES =====
$script:PythonExe      = $null
$script:PG_PASSWORD    = ""
$script:REDIS_PASSWORD = ""
$script:AdminPassword  = $null
$script:AdminEmail     = $null

# ===== OUTPUT FUNCTIONS =====
function Write-Info    { Write-Host "[$(Get-Date -Format HH:mm:ss)] " -NoNewline -ForegroundColor Blue;   Write-Host $args }
function Write-Success { Write-Host "[$(Get-Date -Format HH:mm:ss)] " -NoNewline -ForegroundColor Green;  Write-Host $args }
function Write-Warning { Write-Host "[$(Get-Date -Format HH:mm:ss)] " -NoNewline -ForegroundColor Yellow; Write-Host $args }
function Write-ErrorMsg { Write-Host "[$(Get-Date -Format HH:mm:ss)] FATAL: " -NoNewline -ForegroundColor Red; Write-Host $args; exit 1 }
function Write-Step {
    Write-Host ""
    Write-Host "================================================================" -ForegroundColor Cyan
    Write-Host "[$(Get-Date -Format HH:mm:ss)] $args" -ForegroundColor Cyan
    Write-Host "================================================================" -ForegroundColor Cyan
    Write-Host ""
}

# ===== HELPER FUNCTIONS =====
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
    $chars = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghjkmnpqrstuvwxyz23456789"
    $password = ""
    $rng = New-Object System.Security.Cryptography.RNGCryptoServiceProvider
    $bytes = New-Object byte[] $Length
    $rng.GetBytes($bytes)
    for ($i = 0; $i -lt $Length; $i++) { $password += $chars[$bytes[$i] % $chars.Length] }
    return $password
}

function Wait-ForPostgreSQL {
    param([string]$PgBin, [int]$MaxRetries = 30)
    $env:PGPASSWORD = $script:PG_PASSWORD
    for ($i = 1; $i -le $MaxRetries; $i++) {
        $result = & "$PgBin\psql.exe" -U postgres -h localhost -p $PG_PORT -c "SELECT 1;" 2>&1
        if ($LASTEXITCODE -eq 0) { Write-Info "PostgreSQL is ready (attempt $i)"; return $true }
        Start-Sleep -Seconds 2
    }
    Write-Warning "PostgreSQL not responding after $MaxRetries attempts, continuing anyway..."
    return $false
}

function Set-PgHbaTrust {
    param([string]$PgDataDir)
    $hbaFile = Join-Path $PgDataDir "pg_hba.conf"
    if (-not (Test-Path $hbaFile)) {
        Write-Warning "pg_hba.conf not found at $hbaFile"
        return
    }
    Copy-Item $hbaFile "$hbaFile.backup" -Force
    $content = Get-Content $hbaFile -Encoding UTF8
    $content = $content -replace 'scram-sha-256', 'trust'
    $content = $content -replace 'md5', 'trust'
    $content | Set-Content $hbaFile -Encoding UTF8
    Write-Info "pg_hba.conf set to trust mode"
}

function Restore-PgHba {
    param([string]$PgDataDir)
    $hbaFile = Join-Path $PgDataDir "pg_hba.conf"
    $backupFile = "$hbaFile.backup"
    if (Test-Path $backupFile) {
        Copy-Item $backupFile $hbaFile -Force
        Remove-Item $backupFile -Force
        Write-Info "pg_hba.conf restored"
    }
}

# ===== STEP 1: INSTALL PYTHON 3.11 =====
function Install-Python311 {
    Write-Step "1/7 Installing Python 3.11"
    
    $searchPaths = @(
        "C:\Program Files\Python311\python.exe",
        "C:\Python311\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe"
    )
    foreach ($p in $searchPaths) { if (Test-Path $p) { $script:PythonExe = $p; break } }
    
    if ($script:PythonExe) {
        Write-Success "Python 3.11 found: $script:PythonExe"
        return
    }
    
    Write-Info "Downloading Python 3.11.9..."
    $installer = "$env:TEMP\python-3.11.9-amd64.exe"
    if (Test-Path $installer) { if ((Get-Item $installer).Length -lt 20MB) { Remove-Item $installer -Force } }
    if (-not (Test-Path $installer)) {
        Invoke-WebRequest -Uri "https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe" -OutFile $installer -TimeoutSec 300
    }
    
    Write-Info "Installing Python 3.11..."
    Start-Process -FilePath $installer -ArgumentList "/quiet InstallAllUsers=1 PrependPath=1 Include_test=0 Include_pip=1" -Wait -NoNewWindow
    Remove-Item $installer -Force
    
    $env:Path = [Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [Environment]::GetEnvironmentVariable("Path","User")
    foreach ($p in $searchPaths) { if (Test-Path $p) { $script:PythonExe = $p; break } }
    
    if (-not $script:PythonExe) { Write-ErrorMsg "Python 3.11 not found after installation" }
    Write-Success "Python 3.11 installed"
}

# ===== STEP 2: INSTALL SYSTEM PACKAGES =====
function Install-SystemPackages {
    Write-Step "2/7 Installing system packages"
    choco install git ffmpeg vcredist140 vcredist2015 -y --limit-output 2>&1 | Out-Null
    Write-Success "System packages installed"
}

# ===== STEP 3: INSTALL POSTGRESQL =====
function Install-PostgreSQL {
    Write-Step "3/7 Installing PostgreSQL 16"
    
    $script:PG_PASSWORD = New-RandomPassword -Length 20
    $pgBin = "C:\Program Files\PostgreSQL\$PG_VERSION\bin"
    $pgDataDir = "C:\Program Files\PostgreSQL\$PG_VERSION\data"
    $pgService = Get-Service "postgresql*" -ErrorAction SilentlyContinue
    
    if (-not $pgService) {
        Write-Info "Downloading PostgreSQL..."
        $pgInstaller = "$env:TEMP\postgresql-16.exe"
        Invoke-WebRequest -Uri "https://get.enterprisedb.com/postgresql/postgresql-16.0-1-windows-x64.exe" -OutFile $pgInstaller
        Write-Info "Installing PostgreSQL..."
        Start-Process -FilePath $pgInstaller -ArgumentList @(
            "--mode", "unattended",
            "--superpassword", $script:PG_PASSWORD,
            "--servicename", "postgresql-$PG_VERSION",
            "--serverport", $PG_PORT,
            "--datadir", "`"$pgDataDir`""
        ) -Wait -NoNewWindow
        Remove-Item $pgInstaller -Force
        Start-Sleep -Seconds 15
    } else {
        Write-Info "PostgreSQL service found, ensuring it's running..."
        if ((Get-Service $pgService.Name).Status -ne "Running") {
            Start-Service $pgService.Name
            Start-Sleep -Seconds 10
        }
    }
    
    $env:Path += ";$pgBin"
    [Environment]::SetEnvironmentVariable("Path", [Environment]::GetEnvironmentVariable("Path","Machine") + ";$pgBin", "Machine")
    
    # Wait for PostgreSQL
    Wait-ForPostgreSQL -PgBin $pgBin
    
    # Set trust auth temporarily
    Set-PgHbaTrust -PgDataDir $pgDataDir
    & "$pgBin\pg_ctl.exe" -D "$pgDataDir" reload 2>$null
    Start-Sleep -Seconds 3
    
    try {
        $env:PGPASSWORD = ""
        Write-Info "Creating database user..."
        & "$pgBin\psql.exe" -U postgres -h localhost -p $PG_PORT -c "CREATE ROLE telemail WITH LOGIN PASSWORD '$script:PG_PASSWORD';" 2>$null
        if ($LASTEXITCODE -ne 0) {
            & "$pgBin\psql.exe" -U postgres -h localhost -p $PG_PORT -c "ALTER USER telemail WITH PASSWORD '$script:PG_PASSWORD';" 2>$null
        }
        & "$pgBin\psql.exe" -U postgres -h localhost -p $PG_PORT -c "CREATE DATABASE telemail OWNER telemail;" 2>$null
        & "$pgBin\psql.exe" -U postgres -h localhost -p $PG_PORT -c "GRANT ALL PRIVILEGES ON DATABASE telemail TO telemail;" 2>$null
        Write-Success "PostgreSQL configured"
    } catch {
        Write-ErrorMsg "Failed to configure PostgreSQL: $_"
    } finally {
        Restore-PgHba -PgDataDir $pgDataDir
        & "$pgBin\pg_ctl.exe" -D "$pgDataDir" reload 2>$null
    }
}

# ===== STEP 4: INSTALL REDIS =====
function Install-Redis {
    Write-Step "4/7 Installing Redis"
    
    $script:REDIS_PASSWORD = New-RandomPassword -Length 16
    
    if (Get-Service "Redis" -ErrorAction SilentlyContinue) {
        Write-Success "Redis already installed"
        return
    }
    
    Write-Info "Downloading Redis..."
    $redisInstaller = "$env:TEMP\Redis-x64.msi"
    try {
        Invoke-WebRequest -Uri "https://github.com/microsoftarchive/redis/releases/download/win-3.2.100/Redis-x64-3.2.100.msi" -OutFile $redisInstaller
        Start-Process msiexec.exe -ArgumentList "/i `"$redisInstaller`" /quiet /norestart" -Wait -NoNewWindow
        Remove-Item $redisInstaller -Force
    } catch {
        Write-Warning "MSI failed, trying Memurai..."
        $memurai = "$env:TEMP\memurai.exe"
        Invoke-WebRequest -Uri "https://www.memurai.com/get/memurai-developer-latest.exe" -OutFile $memurai
        Start-Process $memurai -ArgumentList "/VERYSILENT" -Wait -NoNewWindow
        Remove-Item $memurai -Force
    }
    
    $configPath = "C:\Program Files\Redis\redis.windows.conf"
    if (Test-Path $configPath) {
        $cfg = Get-Content $configPath
        $cfg = $cfg -replace "# requirepass foobared", "requirepass $script:REDIS_PASSWORD"
        $cfg = $cfg -replace "# bind 127.0.0.1", "bind 127.0.0.1"
        $cfg | Set-Content $configPath
    }
    
    Restart-Service Redis -ErrorAction SilentlyContinue
    Start-Service Redis -ErrorAction SilentlyContinue
    Write-Success "Redis installed"
}

# ===== STEP 5: CLONE REPOSITORY =====
function Prepare-Environment {
    Write-Step "5/7 Preparing directories & cloning repository"
    
    $dirs = @($APP_ROOT, $LOG_DIR, $DATA_DIR, $CONFIG_DIR, "$DATA_DIR\sessions", "$DATA_DIR\media", "$DATA_DIR\temp", "$DATA_DIR\backups")
    foreach ($d in $dirs) { if (-not (Test-Path $d)) { New-Item -ItemType Directory -Path $d -Force | Out-Null } }
    
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) { Write-ErrorMsg "Git is not installed" }
    if (Test-Path "$APP_ROOT\src") { Remove-Item "$APP_ROOT\src" -Recurse -Force -ErrorAction Stop }
    
    git clone $GIT_REPO "$APP_ROOT\src"
    if ($LASTEXITCODE -ne 0) { Write-ErrorMsg "Git clone failed" }
    Write-Success "Repository cloned"
}

# ===== STEP 6: SETUP PYTHON VENV =====
function Setup-PythonVenv {
    Write-Step "6/7 Setting up Python virtual environment & dependencies"
    
    if (Test-Path $VENV_DIR) { Remove-Item $VENV_DIR -Recurse -Force }
    & $script:PythonExe -m venv $VENV_DIR
    & "$VENV_DIR\Scripts\Activate.ps1"
    
    python -m pip install --upgrade pip --quiet
    
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
        "yookassa>=3.0,<4.0",
        "cryptography>=42.0,<44.0",
        "celery[redis]>=5.3,<6.0",
        "orjson>=3.10,<4.0",
        "python-dotenv>=1.0,<2.0",
        "python-dateutil>=2.9,<3.0",
        "loguru>=0.7,<1.0"
    )
    
    foreach ($pkg in $pkgs) {
        Write-Info "  Installing $pkg..."
        pip install $pkg --no-cache-dir --quiet
    }
    
    $check = python -c "import aiohttp; print(aiohttp.__version__)" 2>&1
    if ($LASTEXITCODE -ne 0) { Write-ErrorMsg "aiohttp failed to install" }
    Write-Success "Dependencies installed"
}

# ===== STEP 7: CONFIGURE =====
function Configure-App {
    Write-Step "7/7 Configuring application"
    
    $encryptionKey = -join ((1..32) | ForEach-Object { '{0:x}' -f (Get-Random -Max 16) })
    $jwtSecret = New-RandomPassword -Length 32
    $script:AdminPassword = New-RandomPassword -Length 12
    
    Write-Host "--- Telegram Bot Settings ---" -ForegroundColor Yellow
    $BOT_TOKEN = Read-Host "Bot Token (from @BotFather)"
    $API_ID    = Read-Host "API ID (my.telegram.org)"
    $API_HASH  = Read-Host "API Hash"
    
    Write-Host "--- Catch-all Email Settings ---" -ForegroundColor Yellow
    $CATCH_ALL_EMAIL = Read-Host "Email address"
    $CATCH_ALL_PASS  = Read-Host "Password" -AsSecureString
    $CATCH_ALL_PASS_PLAIN = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($CATCH_ALL_PASS))
    $IMAP_HOST = Read-Host "IMAP host [imap.gmail.com]"; if (-not $IMAP_HOST) { $IMAP_HOST = "imap.gmail.com" }
    $IMAP_PORT = Read-Host "IMAP port [993]"; if (-not $IMAP_PORT) { $IMAP_PORT = "993" }
    $DOMAIN = Read-Host "Domain [telemail.app]"; if (-not $DOMAIN) { $DOMAIN = "telemail.app" }
    $SMTP_FROM = Read-Host "SMTP From [bot@telemail.app]"; if (-not $SMTP_FROM) { $SMTP_FROM = "bot@telemail.app" }
    
    Write-Host "--- Admin Settings ---" -ForegroundColor Yellow
    $script:AdminEmail = Read-Host "Admin email"
    
    if (-not (Test-Path "$APP_ROOT\src")) { New-Item -ItemType Directory -Path "$APP_ROOT\src" -Force | Out-Null }
    
    $envContent = @"
BOT_TOKEN=$BOT_TOKEN
TELEGRAM_API_ID=$API_ID
TELEGRAM_API_HASH=$API_HASH
DATABASE_URL=postgresql+asyncpg://telemail:$script:PG_PASSWORD@localhost:$PG_PORT/telemail
ENCRYPTION_KEY=$encryptionKey
CATCH_ALL_EMAIL=$CATCH_ALL_EMAIL
CATCH_ALL_PASSWORD=$CATCH_ALL_PASS_PLAIN
CATCH_ALL_IMAP_HOST=$IMAP_HOST
CATCH_ALL_IMAP_PORT=$IMAP_PORT
CATCH_ALL_DOMAIN=$DOMAIN
SMTP_FROM_ADDRESS=$SMTP_FROM
REDIS_URL=redis://:$script:REDIS_PASSWORD@localhost:$REDIS_PORT/0
REDIS_HOST=localhost
REDIS_PORT=$REDIS_PORT
REDIS_PASSWORD=$script:REDIS_PASSWORD
JWT_SECRET=$jwtSecret
JWT_EXPIRATION_HOURS=12
BASE_URL=http://localhost:8080
ADMIN_BASE_URL=http://localhost:8000
LOG_LEVEL=INFO
MAX_ATTACHMENT_SIZE=52428800
CELERY_BROKER_URL=redis://:$script:REDIS_PASSWORD@localhost:$REDIS_PORT/0
CELERY_RESULT_BACKEND=redis://:$script:REDIS_PASSWORD@localhost:$REDIS_PORT/0
"@
    $envContent | Out-File -FilePath "$APP_ROOT\src\.env" -Encoding UTF8
    
    $credContent = @"
===========================================================
TeleMail Bridge - Credentials (SAVE THIS FILE!)
===========================================================
PostgreSQL: localhost:$PG_PORT, user: telemail, pass: $script:PG_PASSWORD
Redis:      localhost:$REDIS_PORT, pass: $script:REDIS_PASSWORD
Admin:      http://localhost:8000/admin
Admin email: $script:AdminEmail
Admin password: $script:AdminPassword
JWT Secret: $jwtSecret
Encryption Key: $encryptionKey
===========================================================
"@
    $credContent | Out-File -FilePath "$CONFIG_DIR\credentials.txt" -Encoding UTF8
    Write-Success "Configuration saved"
    Write-Host "*** ADMIN PASSWORD: $script:AdminPassword ***" -ForegroundColor Green
}

# ===== INIT DATABASE =====
function Initialize-Database {
    Write-Info "Initializing database..."
    
    Set-Location "$APP_ROOT\src"
    & "$VENV_DIR\Scripts\Activate.ps1"
    
    $email = $script:AdminEmail
    $pass  = $script:AdminPassword
    
    python -c @"
import asyncio
from core.db import init_db, get_db
from database.models import User, UserRole
import bcrypt
from sqlalchemy import select

async def setup():
    await init_db()
    async with get_db() as db:
        result = await db.execute(select(User).where(User.email == '${email}'))
        existing = result.scalar_one_or_none()
        password_hash = bcrypt.hashpw('${pass}'.encode(), bcrypt.gensalt()).decode()
        if existing:
            existing.role = UserRole.SUPERADMIN
            existing.admin_password_hash = password_hash
        else:
            admin = User(
                telegram_user_id=0,
                email='${email}',
                role=UserRole.SUPERADMIN,
                admin_password_hash=password_hash,
                is_active=True
            )
            db.add(admin)
        await db.commit()
    print('Database initialized successfully')

asyncio.run(setup())
"@
    
    if ($LASTEXITCODE -ne 0) { Write-ErrorMsg "Database initialization failed" }
    Write-Success "Database initialized"
}

# ===== CREATE SERVICES =====
function Create-WindowsServicesSafe {
    Write-Step "Creating Windows services"
    
    $pythonExe = "$VENV_DIR\Scripts\python.exe"
    
    function Create-SCService($Name, $Display, $Command, $Args) {
        Write-Info "Creating service: $Name"
        $svc = Get-Service $Name -ErrorAction SilentlyContinue
        if ($svc) { 
            Stop-Service $Name -Force -ErrorAction SilentlyContinue
            sc.exe delete $Name 2>$null
            Start-Sleep 3
        }
        sc.exe create $Name binPath= "`"$Command`" $Args" start= auto DisplayName= "$Display"
        sc.exe description $Name "TeleMail Bridge - $Display"
        sc.exe failure $Name reset= 86400 actions= restart/5000/restart/5000/restart/5000
        Write-Success "$Name created"
    }
    
    Create-SCService $SERVICE_BOT "Telegram Bot" $pythonExe "-m bot.main"
    Create-SCService $SERVICE_RECEIVER "Email Receiver" $pythonExe "-m core.email_receiver"
    
    $celery = "$VENV_DIR\Scripts\celery.exe"
    if (Test-Path $celery) {
        Create-SCService $SERVICE_WORKER "Celery Worker" $celery "-A core.tasks worker --loglevel=info --concurrency=2 --pool=solo"
        Create-SCService $SERVICE_BEAT "Celery Beat" $celery "-A core.tasks beat --loglevel=info"
    } else {
        Write-Warning "Celery not found, skipping worker/beat services"
    }
    
    $uvicorn = "$VENV_DIR\Scripts\uvicorn.exe"
    if (Test-Path $uvicorn) {
        Create-SCService $SERVICE_ADMIN "Admin Panel" $uvicorn "admin.web_app.main:app --host 127.0.0.1 --port 8000"
    } else {
        Create-SCService $SERVICE_ADMIN "Admin Panel" $pythonExe "-m uvicorn admin.web_app.main:app --host 127.0.0.1 --port 8000"
    }
    
    Write-Success "Services created"
}

# ===== BATCH FILES =====
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
start "TeleMailAdmin" python -m uvicorn admin.web_app.main:app --host 127.0.0.1 --port 8000
echo All components started. Admin: http://localhost:8000/admin
pause
"@
    $startBat | Out-File "$APP_ROOT\start.bat" -Encoding UTF8
    
    $stopBat = @"
@echo off
taskkill /f /fi "WINDOWTITLE eq TeleMailBot*" 2>nul
taskkill /f /fi "WINDOWTITLE eq TeleMailReceiver*" 2>nul
taskkill /f /fi "WINDOWTITLE eq TeleMailAdmin*" 2>nul
echo Stopped.
pause
"@
    $stopBat | Out-File "$APP_ROOT\stop.bat" -Encoding ASCII
    
    Write-Success "Batch files created"
}

# ===== START SERVICES =====
function Start-AllServices {
    Write-Step "Starting services"
    $services = @($SERVICE_BOT, $SERVICE_RECEIVER, $SERVICE_WORKER, $SERVICE_BEAT, $SERVICE_ADMIN)
    foreach ($svc in $services) {
        $s = Get-Service $svc -ErrorAction SilentlyContinue
        if ($s) {
            if ($s.Status -ne "Running") {
                Start-Service $svc
                Write-Info "Starting $svc..."
                Start-Sleep 3
            } else {
                Write-Success "$svc is running"
            }
        } else {
            Write-Warning "$svc not found, skipping"
        }
    }
}

# ===== PRINT SUMMARY =====
function Print-Summary {
    Write-Host ""
    Write-Host "================================================================" -ForegroundColor Green
    Write-Host "  TeleMail Bridge installation completed!" -ForegroundColor Green
    Write-Host "================================================================" -ForegroundColor Green
    Write-Host "Credentials : $CONFIG_DIR\credentials.txt"
    Write-Host "Admin panel : http://localhost:8000/admin"
    Write-Host "Admin password: $script:AdminPassword" -ForegroundColor Yellow
    Write-Host "Manual start: $APP_ROOT\start.bat"
    Write-Host "================================================================" -ForegroundColor Green
}

# ===== MAIN =====
function Main {
    Write-Host ""
    Write-Host "================================================================" -ForegroundColor Magenta
    Write-Host "  TeleMail Bridge - Fully Automatic Installer" -ForegroundColor Magenta
    Write-Host "================================================================" -ForegroundColor Magenta
    Write-Host ""
    
    $confirm = Read-Host "Press Enter to start (or Ctrl+C to cancel)"
    
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