<#
.SYNOPSIS
    TeleMail Bridge – Fully Automatic Clean Installer
.DESCRIPTION
    Removes any previous installation, then installs from scratch.
    Generates all passwords, configures PostgreSQL and Redis,
    writes all configs correctly. Run as Administrator:
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
$GIT_REPO = "https://github.com/sergeyzhinskiy/telemail-bridge.git"  # <-- change to your repo

$PG_VERSION = "16"
$PG_PORT    = 5432
$REDIS_PORT = 6379

$SERVICE_BOT      = "TeleMailBot"
$SERVICE_RECEIVER = "TeleMailReceiver"
$SERVICE_WORKER   = "TeleMailWorker"
$SERVICE_BEAT     = "TeleMailBeat"
$SERVICE_ADMIN    = "TeleMailAdmin"

# ===== GLOBAL VARIABLES (filled during installation) =====
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

# ===== HELPER: Generate password =====
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

# ===== STEP 0: CLEAN PREVIOUS INSTALLATION =====
function Invoke-CleanSystem {
    Write-Step "0/7 Cleaning previous installation"

    # Stop and remove all TeleMail services
    $services = @($SERVICE_BOT, $SERVICE_RECEIVER, $SERVICE_WORKER, $SERVICE_BEAT, $SERVICE_ADMIN)
    foreach ($svc in $services) {
        $s = Get-Service $svc -ErrorAction SilentlyContinue
        if ($s) {
            Stop-Service $svc -Force -ErrorAction SilentlyContinue
            sc.exe delete $svc 2>$null
            Write-Info "Removed service: $svc"
        }
    }

    # Stop and remove PostgreSQL service
    $pgService = Get-Service "postgresql*" -ErrorAction SilentlyContinue
    if ($pgService) {
        Stop-Service $pgService.Name -Force -ErrorAction SilentlyContinue
        sc.exe delete $pgService.Name 2>$null
        Write-Info "Removed PostgreSQL service"
    }

    # Kill any remaining postgres processes
    Get-Process -Name "postgres" -ErrorAction SilentlyContinue | Stop-Process -Force

    # Remove PostgreSQL data directory
    $dataDirs = @(
        "C:\TeleMailBridge\PostgreSQL\data",
        "C:\Program Files\PostgreSQL\$PG_VERSION\data"
    )
    foreach ($dir in $dataDirs) {
        if (Test-Path $dir) {
            Remove-Item $dir -Recurse -Force -ErrorAction SilentlyContinue
            Write-Info "Removed data directory: $dir"
        }
    }

    # Stop and remove Redis service
    $redisService = Get-Service "Redis" -ErrorAction SilentlyContinue
    if ($redisService) {
        Stop-Service "Redis" -Force -ErrorAction SilentlyContinue
        sc.exe delete "Redis" 2>$null
        Write-Info "Removed Redis service"
    }

    # Remove old application files
    if (Test-Path $APP_ROOT) {
        Remove-Item $APP_ROOT -Recurse -Force -ErrorAction SilentlyContinue
        Write-Info "Removed $APP_ROOT"
    }

    Write-Success "System cleaned"
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
    Invoke-WebRequest -Uri "https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe" -OutFile $installer
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
    if (-not (Get-Command choco -ErrorAction SilentlyContinue)) {
        Set-ExecutionPolicy Bypass -Scope Process -Force
        [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.ServicePointManager]::SecurityProtocol -bor 3072
        iex ((New-Object System.Net.WebClient).DownloadString('https://community.chocolatey.org/install.ps1'))
        $env:Path = [Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [Environment]::GetEnvironmentVariable("Path","User")
    }
    choco install git ffmpeg -y --limit-output 2>&1 | Out-Null
    Write-Success "System packages installed"
}

# ===== STEP 3: INSTALL POSTGRESQL (FRESH) =====
function Install-PostgreSQL {
    Write-Step "3/7 Installing PostgreSQL 16"

    # Generate password
    $script:PG_PASSWORD = New-RandomPassword -Length 20
    $pgBaseDir = "C:\Program Files\PostgreSQL\$PG_VERSION"
    $pgDataDir = "$pgBaseDir\data"
    $pgBin = "$pgBaseDir\bin"

    Write-Info "Installing PostgreSQL..."
    $pgInstaller = "$env:TEMP\postgresql-16.exe"
    Invoke-WebRequest -Uri "https://get.enterprisedb.com/postgresql/postgresql-16.0-1-windows-x64.exe" -OutFile $pgInstaller

    Start-Process -FilePath $pgInstaller -ArgumentList @(
        "--mode", "unattended",
        "--superpassword", $script:PG_PASSWORD,
        "--servicename", "postgresql-$PG_VERSION",
        "--serverport", $PG_PORT,
        "--datadir", "`"$pgDataDir`""
    ) -Wait -NoNewWindow
    Remove-Item $pgInstaller -Force

    # Wait for service to start
    Start-Sleep -Seconds 15
    $pgService = Get-Service "postgresql*"
    if ($pgService.Status -ne "Running") {
        Start-Service $pgService.Name
        Start-Sleep -Seconds 5
    }

    # Create telemail user and database
    $env:PGPASSWORD = $script:PG_PASSWORD
    & "$pgBin\psql.exe" -U postgres -h localhost -c "CREATE ROLE telemail WITH LOGIN PASSWORD '$script:PG_PASSWORD';" 2>$null
    if ($LASTEXITCODE -ne 0) {
        & "$pgBin\psql.exe" -U postgres -h localhost -c "ALTER USER telemail WITH PASSWORD '$script:PG_PASSWORD';" 2>$null
    }
    & "$pgBin\psql.exe" -U postgres -h localhost -c "CREATE DATABASE telemail OWNER telemail;" 2>$null
    & "$pgBin\psql.exe" -U postgres -h localhost -c "GRANT ALL PRIVILEGES ON DATABASE telemail TO telemail;" 2>$null

    # Add to PATH
    $env:Path += ";$pgBin"
    [Environment]::SetEnvironmentVariable("Path", [Environment]::GetEnvironmentVariable("Path","Machine") + ";$pgBin", "Machine")

    Write-Success "PostgreSQL installed"
}

# ===== STEP 4: INSTALL REDIS =====
function Install-Redis {
    Write-Step "4/7 Installing Redis"

    $script:REDIS_PASSWORD = New-RandomPassword -Length 16

    Write-Info "Installing Redis..."
    $redisInstaller = "$env:TEMP\Redis-x64.msi"
    Invoke-WebRequest -Uri "https://github.com/microsoftarchive/redis/releases/download/win-3.2.100/Redis-x64-3.2.100.msi" -OutFile $redisInstaller
    Start-Process msiexec.exe -ArgumentList "/i `"$redisInstaller`" /quiet /norestart" -Wait -NoNewWindow
    Remove-Item $redisInstaller -Force

    # Configure password
    $redisConfig = "C:\Program Files\Redis\redis.windows.conf"
    if (Test-Path $redisConfig) {
        $cfg = Get-Content $redisConfig
        $cfg = $cfg -replace "# requirepass foobared", "requirepass $script:REDIS_PASSWORD"
        $cfg = $cfg -replace "# bind 127.0.0.1", "bind 127.0.0.1"
        [System.IO.File]::WriteAllText($redisConfig, ($cfg -join "`r`n"), [System.Text.Encoding]::ASCII)
    }

    Restart-Service Redis
    Write-Success "Redis installed"
}

# ===== STEP 5: CLONE REPOSITORY =====
function Prepare-Environment {
    Write-Step "5/7 Cloning repository"

    # Create directories
    $dirs = @($APP_ROOT, $LOG_DIR, $DATA_DIR, $CONFIG_DIR, "$DATA_DIR\sessions", "$DATA_DIR\media", "$DATA_DIR\temp", "$DATA_DIR\backups")
    foreach ($d in $dirs) { if (-not (Test-Path $d)) { New-Item -ItemType Directory -Path $d -Force | Out-Null } }

    if (Test-Path "$APP_ROOT\src") { Remove-Item "$APP_ROOT\src" -Recurse -Force }
    git clone $GIT_REPO "$APP_ROOT\src"
    if ($LASTEXITCODE -ne 0) { Write-ErrorMsg "Git clone failed" }
    Write-Success "Repository cloned"
}

# ===== STEP 6: SETUP PYTHON VENV =====
function Setup-PythonVenv {
    Write-Step "6/7 Setting up Python virtual environment"

    if (Test-Path $VENV_DIR) { Remove-Item $VENV_DIR -Recurse -Force }
    & $script:PythonExe -m venv $VENV_DIR
    & "$VENV_DIR\Scripts\Activate.ps1"

    python -m pip install --upgrade pip --quiet

    $pkgs = @(
        "aiogram==2.25.2", "telethon", "aiohttp>=3.8.0,<3.9.0",
        "sqlalchemy[asyncio]", "asyncpg", "alembic", "redis",
        "aiosmtplib", "aioimaplib", "fastapi", "uvicorn[standard]",
        "jinja2", "python-multipart", "PyJWT", "bcrypt",
        "cryptography", "celery[redis]", "orjson",
        "python-dotenv", "python-dateutil", "loguru"
    )

    foreach ($pkg in $pkgs) {
        pip install $pkg --no-cache-dir --quiet
    }

    $check = python -c "import aiohttp" 2>&1
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
    $BOT_TOKEN = Read-Host "Bot Token (@BotFather)"
    $API_ID    = Read-Host "API ID (my.telegram.org)"
    $API_HASH  = Read-Host "API Hash"

    Write-Host "--- Catch-all Email Settings ---" -ForegroundColor Yellow
    $CATCH_ALL_EMAIL = Read-Host "Email"
    $CATCH_ALL_PASS  = Read-Host "Password" -AsSecureString
    $CATCH_ALL_PASS_PLAIN = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($CATCH_ALL_PASS))
    $IMAP_HOST = Read-Host "IMAP host [imap.gmail.com]"
    if (-not $IMAP_HOST) { $IMAP_HOST = "imap.gmail.com" }
    $IMAP_PORT = Read-Host "IMAP port [993]"
    if (-not $IMAP_PORT) { $IMAP_PORT = "993" }
    $DOMAIN = Read-Host "Domain [telemail.app]"
    if (-not $DOMAIN) { $DOMAIN = "telemail.app" }
    $SMTP_FROM = Read-Host "SMTP From [bot@telemail.app]"
    if (-not $SMTP_FROM) { $SMTP_FROM = "bot@telemail.app" }

    Write-Host "--- Admin Settings ---" -ForegroundColor Yellow
    $script:AdminEmail = Read-Host "Admin email"

    # Write .env with UTF8 (no BOM)
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
    [System.IO.File]::WriteAllText("$APP_ROOT\src\.env", $envContent, [System.Text.Encoding]::ASCII)

    # Write credentials
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
    [System.IO.File]::WriteAllText("$CONFIG_DIR\credentials.txt", $credContent, [System.Text.Encoding]::ASCII)

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
function Create-WindowsServices {
    Write-Step "Creating Windows services"

    $pythonExe = "$VENV_DIR\Scripts\python.exe"

    function Create-SCService($Name, $Display, $Command, $Args) {
        $svc = Get-Service $Name -ErrorAction SilentlyContinue
        if ($svc) {
            Stop-Service $Name -Force -ErrorAction SilentlyContinue
            sc.exe delete $Name 2>$null
            Start-Sleep 2
        }
        sc.exe create $Name binPath= "`"$Command`" $Args" start= auto DisplayName= "$Display"
        sc.exe description $Name "TeleMail Bridge - $Display"
        sc.exe failure $Name reset= 86400 actions= restart/5000/restart/5000/restart/5000
    }

    Create-SCService $SERVICE_BOT      "Telegram Bot"    $pythonExe "-m bot.main"
    Create-SCService $SERVICE_RECEIVER "Email Receiver"  $pythonExe "-m core.email_receiver"
    Create-SCService $SERVICE_ADMIN    "Admin Panel"     $pythonExe "-m uvicorn admin.web_app.main:app --host 127.0.0.1 --port 8000"

    Write-Success "Windows services created"
}

# ===== CREATE BATCH FILES =====
function Create-BatchFiles {
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
    [System.IO.File]::WriteAllText("$APP_ROOT\start.bat", $startBat, [System.Text.Encoding]::ASCII)

    $stopBat = @"
@echo off
taskkill /f /fi "WINDOWTITLE eq TeleMailBot*" 2>nul
taskkill /f /fi "WINDOWTITLE eq TeleMailReceiver*" 2>nul
taskkill /f /fi "WINDOWTITLE eq TeleMailAdmin*" 2>nul
echo Stopped.
pause
"@
    [System.IO.File]::WriteAllText("$APP_ROOT\stop.bat", $stopBat, [System.Text.Encoding]::ASCII)
}

# ===== MAIN =====
function Main {
    Write-Host "================================================================" -ForegroundColor Magenta
    Write-Host "  TeleMail Bridge - Clean Installer" -ForegroundColor Magenta
    Write-Host "================================================================"
    Write-Host "WARNING: This will REMOVE any previous installation." -ForegroundColor Yellow
    $confirm = Read-Host "Type YES to continue"
    if ($confirm -ne "YES") { exit 0 }

    try {
        Invoke-CleanSystem
        Install-Python311
        Install-SystemPackages
        Install-PostgreSQL
        Install-Redis
        Prepare-Environment
        Setup-PythonVenv
        Configure-App
        Initialize-Database
        Create-WindowsServices
        Create-BatchFiles

        Write-Host ""
        Write-Host "================================================================" -ForegroundColor Green
        Write-Host "  INSTALLATION COMPLETE!" -ForegroundColor Green
        Write-Host "================================================================" -ForegroundColor Green
        Write-Host "Admin panel: http://localhost:8000/admin"
        Write-Host "Admin password: $script:AdminPassword" -ForegroundColor Yellow
        Write-Host "Credentials: $CONFIG_DIR\credentials.txt"
        Write-Host "================================================================" -ForegroundColor Green
    } catch {
        Write-ErrorMsg "Installation failed: $_"
        Write-Host $_.ScriptStackTrace
        exit 1
    }
}

Main
