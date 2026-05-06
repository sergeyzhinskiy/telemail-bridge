#!/bin/bash
###############################################################################
# TeleMail Bridge - Установщик для Debian 12 (без Docker)
# 
# Устанавливает всё необходимое для работы TeleMail Bridge на чистом Debian 12.
# Минимальные требования:
#   - Debian 12 (Bookworm)
#   - 2 ГБ RAM
#   - 10 ГБ свободного места
#   - Доступ в интернет
#   - Права root
#
# Использование:
#   chmod +x install.sh
#   sudo ./install.sh
#
# Что будет установлено:
#   - PostgreSQL 16
#   - Redis 7
#   - Python 3.12
#   - Nginx + Let's Encrypt (опционально)
#   - TeleMail Bridge (все компоненты)
#   - Systemd-сервисы для автозапуска
###############################################################################

set -e  # Выходим при ошибке
set -u  # Выходим при использовании неопределённой переменной

# ========== ЦВЕТА ДЛЯ ВЫВОДА ==========
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
NC='\033[0m' # No Color

# ========== ПЕРЕМЕННЫЕ ==========
APP_NAME="telemail"
APP_DIR="/opt/telemail-bridge"
VENV_DIR="${APP_DIR}/venv"
LOG_DIR="/var/log/${APP_NAME}"
DATA_DIR="/var/lib/${APP_NAME}"
SESSIONS_DIR="${DATA_DIR}/sessions"
MEDIA_DIR="${DATA_DIR}/media"
TEMP_DIR="${DATA_DIR}/temp"
CONFIG_DIR="/etc/${APP_NAME}"
BACKUP_DIR="${DATA_DIR}/backups"

# Пользователи и группы
APP_USER="telemail"
APP_GROUP="telemail"

# Цветной вывод
info() { echo -e "${BLUE}[INFO]${NC} $1"; }
success() { echo -e "${GREEN}[OK]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }
step() { echo -e "\n${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"; echo -e "${CYAN}[$(date +%H:%M:%S)] $1${NC}"; echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}\n"; }

# ========== ПРОВЕРКИ ==========
check_root() {
    if [ "$(id -u)" -ne 0 ]; then
        error "Скрипт должен запускаться от root. Используйте: sudo ./install.sh"
    fi
}

check_debian() {
    if [ ! -f /etc/debian_version ]; then
        error "Этот скрипт предназначен для Debian 12"
    fi
    
    local version=$(cat /etc/debian_version | cut -d. -f1)
    if [ "$version" != "12" ]; then
        warn "Скрипт протестирован на Debian 12. У вас версия $(cat /etc/debian_version)"
        read -p "Продолжить? (y/n): " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            exit 1
        fi
    fi
}

check_resources() {
    local total_ram=$(free -m | awk '/^Mem:/{print $2}')
    local free_space=$(df -BG /opt | awk 'NR==2{print $4}' | sed 's/G//')
    
    if [ "$total_ram" -lt 1800 ]; then
        warn "Рекомендуется минимум 2 ГБ RAM. У вас: ${total_ram}MB"
    fi
    
    if [ "$free_space" -lt 8 ]; then
        error "Недостаточно места. Требуется ~8 ГБ. У вас: ${free_space}GB"
    fi
    
    info "RAM: ${total_ram}MB, Свободно: ${free_space}GB"
}

# ========== УСТАНОВКА СИСТЕМНЫХ ПАКЕТОВ ==========
install_system_packages() {
    step "1/9 Установка системных пакетов"
    
    info "Обновление списка пакетов..."
    apt-get update -qq
    
    info "Установка необходимых пакетов..."
    apt-get install -y -qq \
        curl wget git \
        build-essential gcc \
        python3 python3-dev python3-pip python3-venv \
        python3-setuptools python3-wheel \
        libpq-dev postgresql-client \
        libssl-dev libffi-dev \
        libjpeg-dev zlib1g-dev \
        libxml2-dev libxslt1-dev \
        ffmpeg mediainfo \
        nginx certbot python3-certbot-nginx \
        supervisor \
        htop iotop iftop net-tools \
        rsync gnupg2 lsb-release ca-certificates \
        2>&1 | grep -v "^$"
    
    success "Системные пакеты установлены"
}

# ========== УСТАНОВКА POSTGRESQL ==========
install_postgresql() {
    step "2/9 Установка PostgreSQL 16"
    
    if command -v psql &>/dev/null; then
        local pg_version=$(psql --version | awk '{print $3}' | cut -d. -f1)
        if [ "$pg_version" -ge 15 ]; then
            success "PostgreSQL уже установлен (версия $pg_version)"
            return
        fi
    fi
    
    info "Добавление репозитория PostgreSQL..."
    curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc | gpg --dearmor -o /usr/share/keyrings/postgresql.gpg
    
    echo "deb [signed-by=/usr/share/keyrings/postgresql.gpg] http://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main" \
        > /etc/apt/sources.list.d/postgresql.list
    
    apt-get update -qq
    apt-get install -y -qq postgresql-16 postgresql-contrib-16
    
    info "Настройка PostgreSQL..."
    systemctl enable postgresql
    systemctl start postgresql
    
    # Генерация пароля для БД
    local db_password=$(openssl rand -base64 24 | tr -d '/+=' | cut -c1-20)
    
    # Создание пользователя и БД
    su - postgres -c "psql -c \"CREATE USER ${APP_USER} WITH PASSWORD '${db_password}';\"" 2>/dev/null || true
    su - postgres -c "psql -c \"CREATE DATABASE ${APP_NAME} OWNER ${APP_USER};\"" 2>/dev/null || true
    su - postgres -c "psql -c \"GRANT ALL PRIVILEGES ON DATABASE ${APP_NAME} TO ${APP_USER};\"" 2>/dev/null || true
    su - postgres -c "psql -c \"ALTER USER ${APP_USER} CREATEDB;\"" 2>/dev/null || true
    
    # Сохраняем пароль в конфиг
    echo "DB_PASSWORD=${db_password}" >> ${CONFIG_DIR}/.env
    echo "DATABASE_URL=postgresql+asyncpg://${APP_USER}:${db_password}@localhost/${APP_NAME}" >> ${CONFIG_DIR}/.env
    
    # Настройка pg_hba.conf для доступа по паролю
    local pg_hba="/etc/postgresql/16/main/pg_hba.conf"
    if ! grep -q "${APP_USER}" "$pg_hba"; then
        sed -i "s|local   all             all                                     peer|local   all             all                                     md5|" "$pg_hba"
    fi
    
    systemctl restart postgresql
    
    success "PostgreSQL 16 установлен и настроен"
}

# ========== УСТАНОВКА REDIS ==========
install_redis() {
    step "3/9 Установка Redis"
    
    if command -v redis-server &>/dev/null; then
        success "Redis уже установлен"
        return
    fi
    
    apt-get install -y -qq redis-server
    
    # Настройка Redis
    local redis_conf="/etc/redis/redis.conf"
    
    # Бэкап конфига
    cp "$redis_conf" "${redis_conf}.backup"
    
    # Настройки для production
    sed -i 's/^bind .*/bind 127.0.0.1/' "$redis_conf"
    sed -i 's/^protected-mode .*/protected-mode yes/' "$redis_conf"
    sed -i 's/^# maxmemory .*/maxmemory 256mb/' "$redis_conf"
    sed -i 's/^# maxmemory-policy .*/maxmemory-policy allkeys-lru/' "$redis_conf"
    
    # Генерация пароля для Redis
    local redis_password=$(openssl rand -base64 16 | tr -d '/+=' | cut -c1-16)
    sed -i "s/^# requirepass .*/requirepass ${redis_password}/" "$redis_conf"
    
    echo "REDIS_PASSWORD=${redis_password}" >> ${CONFIG_DIR}/.env
    echo "REDIS_URL=redis://:${redis_password}@localhost:6379/0" >> ${CONFIG_DIR}/.env
    
    systemctl enable redis-server
    systemctl restart redis-server
    
    # Проверка
    if redis-cli -a "$redis_password" ping | grep -q PONG; then
        success "Redis установлен и работает"
    else
        error "Redis не запустился"
    fi
}

# ========== СОЗДАНИЕ ПОЛЬЗОВАТЕЛЯ И ДИРЕКТОРИЙ ==========
create_user_and_dirs() {
    step "4/9 Создание пользователя и директорий"
    
    # Создаём пользователя если не существует
    if ! id -u ${APP_USER} &>/dev/null; then
        useradd -r -s /bin/bash -d ${APP_DIR} -m ${APP_USER}
        info "Пользователь ${APP_USER} создан"
    else
        info "Пользователь ${APP_USER} уже существует"
    fi
    
    # Создаём необходимые директории
    mkdir -p ${APP_DIR}
    mkdir -p ${LOG_DIR}
    mkdir -p ${DATA_DIR}
    mkdir -p ${SESSIONS_DIR}
    mkdir -p ${MEDIA_DIR}
    mkdir -p ${TEMP_DIR}
    mkdir -p ${CONFIG_DIR}
    mkdir -p ${BACKUP_DIR}
    
    # Устанавливаем права
    chown -R ${APP_USER}:${APP_GROUP} ${APP_DIR}
    chown -R ${APP_USER}:${APP_GROUP} ${LOG_DIR}
    chown -R ${APP_USER}:${APP_GROUP} ${DATA_DIR}
    chown -R ${APP_USER}:${APP_GROUP} ${CONFIG_DIR}
    
    # Права на сессии (только для владельца)
    chmod 700 ${SESSIONS_DIR}
    
    success "Пользователь и директории созданы"
}

# ========== КЛОНИРОВАНИЕ РЕПОЗИТОРИЯ ==========
clone_repository() {
    step "5/9 Клонирование репозитория"
    
    if [ -d "${APP_DIR}/.git" ]; then
        info "Репозиторий уже существует, обновляем..."
        cd ${APP_DIR}
        su - ${APP_USER} -c "cd ${APP_DIR} && git pull"
    else
        # URL репозитория (можно изменить)
        local repo_url="${GITHUB_REPO_URL:-https://github.com/yourusername/telemail-bridge.git}"
        
        su - ${APP_USER} -c "git clone ${repo_url} ${APP_DIR}"
    fi
    
    success "Репозиторий склонирован"
}

# ========== НАСТРОЙКА ВИРТУАЛЬНОГО ОКРУЖЕНИЯ ==========
setup_python_env() {
    step "6/9 Настройка Python окружения"
    
    cd ${APP_DIR}
    
    # Создаём виртуальное окружение
    if [ ! -d "${VENV_DIR}" ]; then
        su - ${APP_USER} -c "python3 -m venv ${VENV_DIR}"
        info "Виртуальное окружение создано"
    fi
    
    # Устанавливаем зависимости
    su - ${APP_USER} -c "
        source ${VENV_DIR}/bin/activate
        pip install --upgrade pip setuptools wheel
        pip install -r ${APP_DIR}/requirements.txt
    "
    
    success "Python зависимости установлены"
}

# ========== НАСТРОЙКА КОНФИГУРАЦИИ ==========
configure_app() {
    step "7/9 Настройка конфигурации приложения"
    
    # Генерация ключей
    local encryption_key=$(openssl rand -hex 16)
    local jwt_secret=$(openssl rand -base64 32 | tr -d '/+=' | cut -c1-32)
    local admin_password=$(openssl rand -base64 12 | tr -d '/+=' | cut -c1-12)
    
    # Интерактивный ввод обязательных параметров
    echo -e "${YELLOW}Введите обязательные параметры:${NC}"
    echo ""
    
    read -p "Telegram Bot Token (от @BotFather): " BOT_TOKEN
    read -p "Telegram API ID (my.telegram.org): " TELEGRAM_API_ID
    read -p "Telegram API Hash: " TELEGRAM_API_HASH
    
    echo ""
    echo -e "${YELLOW}Настройки catch-all почты (для приёма ответов):${NC}"
    echo ""
    
    read -p "Catch-all Email: " CATCH_ALL_EMAIL
    read -p "Catch-all пароль: " CATCH_ALL_PASSWORD
    read -p "Catch-all IMAP хост [imap.gmail.com]: " CATCH_ALL_IMAP_HOST
    CATCH_ALL_IMAP_HOST=${CATCH_ALL_IMAP_HOST:-imap.gmail.com}
    read -p "Catch-all IMAP порт [993]: " CATCH_ALL_IMAP_PORT
    CATCH_ALL_IMAP_PORT=${CATCH_ALL_IMAP_PORT:-993}
    read -p "Домен для Reply-To [telemail.app]: " CATCH_ALL_DOMAIN
    CATCH_ALL_DOMAIN=${CATCH_ALL_DOMAIN:-telemail.app}
    read -p "SMTP From адрес [bot@telemail.app]: " SMTP_FROM_ADDRESS
    SMTP_FROM_ADDRESS=${SMTP_FROM_ADDRESS:-bot@telemail.app}
    
    echo ""
    echo -e "${YELLOW}Настройки админки:${NC}"
    echo ""
    
    read -p "Домен для админки [admin.telemail.app]: " ADMIN_DOMAIN
    ADMIN_DOMAIN=${ADMIN_DOMAIN:-admin.telemail.app}
    read -p "Email администратора: " ADMIN_EMAIL
    
    echo ""
    echo -e "${YELLOW}Настройки платежей (опционально):${NC}"
    echo ""
    
    read -p "ЮKassa Shop ID (оставьте пустым если не нужно): " YOOKASSA_SHOP_ID
    read -p "ЮKassa Secret Key: " YOOKASSA_SECRET_KEY
    read -p "Stripe Secret Key: " STRIPE_SECRET_KEY
    
    # Загружаем пароль БД из временного файла
    source ${CONFIG_DIR}/.env 2>/dev/null || true
    
    # Создаём основной .env файл
    cat > ${APP_DIR}/.env << EOF
# ========== СГЕНЕРИРОВАНО АВТОМАТИЧЕСКИ ==========
# Дата установки: $(date '+%Y-%m-%d %H:%M:%S')

# ========== ОБЯЗАТЕЛЬНЫЕ ==========
BOT_TOKEN=${BOT_TOKEN}
TELEGRAM_API_ID=${TELEGRAM_API_ID}
TELEGRAM_API_HASH=${TELEGRAM_API_HASH}
DATABASE_URL=postgresql+asyncpg://${APP_USER}:${DB_PASSWORD}@localhost/${APP_NAME}
ENCRYPTION_KEY=${encryption_key}

# ========== CATCH-ALL ПОЧТА ==========
CATCH_ALL_EMAIL=${CATCH_ALL_EMAIL}
CATCH_ALL_PASSWORD=${CATCH_ALL_PASSWORD}
CATCH_ALL_IMAP_HOST=${CATCH_ALL_IMAP_HOST}
CATCH_ALL_IMAP_PORT=${CATCH_ALL_IMAP_PORT}
CATCH_ALL_DOMAIN=${CATCH_ALL_DOMAIN}
SMTP_FROM_ADDRESS=${SMTP_FROM_ADDRESS}

# ========== REDIS ==========
REDIS_URL=redis://:${redis_password:-}@localhost:6379/0
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_PASSWORD=${redis_password:-}
REDIS_DB_FSM=0

# ========== АДМИНКА ==========
JWT_SECRET=${jwt_secret}
JWT_EXPIRATION_HOURS=12
BASE_URL=https://${CATCH_ALL_DOMAIN}
ADMIN_BASE_URL=https://${ADMIN_DOMAIN}

# ========== ПЛАТЕЖИ ==========
YOOKASSA_SHOP_ID=${YOOKASSA_SHOP_ID:-}
YOOKASSA_SECRET_KEY=${YOOKASSA_SECRET_KEY:-}
STRIPE_SECRET_KEY=${STRIPE_SECRET_KEY:-}
STRIPE_WEBHOOK_SECRET=

# ========== ЛОГИРОВАНИЕ ==========
LOG_LEVEL=INFO

# ========== ЛИМИТЫ ==========
MAX_ATTACHMENT_SIZE=52428800

# ========== CELERY ==========
CELERY_BROKER_URL=redis://:${redis_password:-}@localhost:6379/0
CELERY_RESULT_BACKEND=redis://:${redis_password:-}@localhost:6379/0
EOF

    # Устанавливаем права
    chown ${APP_USER}:${APP_GROUP} ${APP_DIR}/.env
    chmod 600 ${APP_DIR}/.env
    
    # Сохраняем пароли в защищённый файл
    cat > ${CONFIG_DIR}/credentials.txt << EOF
═══════════════════════════════════════════════════════════════
TeleMail Bridge - Учётные данные
═══════════════════════════════════════════════════════════════
Дата установки: $(date '+%Y-%m-%d %H:%M:%S')

База данных:
  Пользователь: ${APP_USER}
  Пароль: ${DB_PASSWORD}
  База данных: ${APP_NAME}
  URL: ${DATABASE_URL}

Redis:
  Пароль: ${redis_password:-}

Админка:
  URL: https://${ADMIN_DOMAIN}
  Email администратора: ${ADMIN_EMAIL}
  Пароль администратора: ${admin_password}
  JWT Secret: ${jwt_secret}

Шифрование:
  Encryption Key: ${encryption_key}

⚠️ Храните этот файл в безопасном месте!
═══════════════════════════════════════════════════════════════
EOF
    
    chmod 600 ${CONFIG_DIR}/credentials.txt
    
    success "Конфигурация создана"
    echo -e "${GREEN}Учётные данные сохранены в: ${CONFIG_DIR}/credentials.txt${NC}"
    echo -e "${YELLOW}Пароль администратора: ${admin_password}${NC}"
}

# ========== СОЗДАНИЕ SYSTEMD-СЕРВИСОВ ==========
create_systemd_services() {
    step "8/9 Создание systemd-сервисов"
    
    # Сервис Telegram Bot
    cat > /etc/systemd/system/telemail-bot.service << EOF
[Unit]
Description=TeleMail Bridge - Telegram Bot
After=network.target postgresql.service redis-server.service
Wants=postgresql.service redis-server.service

[Service]
Type=simple
User=${APP_USER}
Group=${APP_GROUP}
WorkingDirectory=${APP_DIR}
Environment=PATH=${VENV_DIR}/bin:/usr/local/bin:/usr/bin:/bin
Environment=PYTHONPATH=${APP_DIR}
EnvironmentFile=${APP_DIR}/.env
ExecStart=${VENV_DIR}/bin/python -m bot.main
Restart=always
RestartSec=5
StandardOutput=append:${LOG_DIR}/bot.log
StandardError=append:${LOG_DIR}/bot_error.log

# Защита
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ProtectHome=yes
ReadWritePaths=${LOG_DIR} ${DATA_DIR} ${APP_DIR}/sessions ${APP_DIR}/media /tmp
ReadOnlyPaths=${APP_DIR}/.env

[Install]
WantedBy=multi-user.target
EOF

    # Сервис Email Receiver
    cat > /etc/systemd/system/telemail-receiver.service << EOF
[Unit]
Description=TeleMail Bridge - Email Receiver
After=network.target postgresql.service redis-server.service telemail-bot.service
Wants=postgresql.service redis-server.service

[Service]
Type=simple
User=${APP_USER}
Group=${APP_GROUP}
WorkingDirectory=${APP_DIR}
Environment=PATH=${VENV_DIR}/bin:/usr/local/bin:/usr/bin:/bin
Environment=PYTHONPATH=${APP_DIR}
EnvironmentFile=${APP_DIR}/.env
ExecStart=${VENV_DIR}/bin/python -m core.email_receiver
Restart=always
RestartSec=10
StandardOutput=append:${LOG_DIR}/receiver.log
StandardError=append:${LOG_DIR}/receiver_error.log

[Install]
WantedBy=multi-user.target
EOF

    # Сервис Celery Worker
    cat > /etc/systemd/system/telemail-worker.service << EOF
[Unit]
Description=TeleMail Bridge - Celery Worker
After=network.target redis-server.service
Wants=redis-server.service

[Service]
Type=simple
User=${APP_USER}
Group=${APP_GROUP}
WorkingDirectory=${APP_DIR}
Environment=PATH=${VENV_DIR}/bin:/usr/local/bin:/usr/bin:/bin
Environment=PYTHONPATH=${APP_DIR}
EnvironmentFile=${APP_DIR}/.env
ExecStart=${VENV_DIR}/bin/celery -A core.tasks worker --loglevel=info --concurrency=2
Restart=always
RestartSec=5
StandardOutput=append:${LOG_DIR}/worker.log
StandardError=append:${LOG_DIR}/worker_error.log

[Install]
WantedBy=multi-user.target
EOF

    # Сервис Celery Beat
    cat > /etc/systemd/system/telemail-beat.service << EOF
[Unit]
Description=TeleMail Bridge - Celery Beat
After=network.target redis-server.service
Wants=redis-server.service

[Service]
Type=simple
User=${APP_USER}
Group=${APP_GROUP}
WorkingDirectory=${APP_DIR}
Environment=PATH=${VENV_DIR}/bin:/usr/local/bin:/usr/bin:/bin
Environment=PYTHONPATH=${APP_DIR}
EnvironmentFile=${APP_DIR}/.env
ExecStart=${VENV_DIR}/bin/celery -A core.tasks beat --loglevel=info
Restart=always
RestartSec=5
StandardOutput=append:${LOG_DIR}/beat.log
StandardError=append:${LOG_DIR}/beat_error.log

[Install]
WantedBy=multi-user.target
EOF

    # Сервис админки (через uvicorn)
    cat > /etc/systemd/system/telemail-admin.service << EOF
[Unit]
Description=TeleMail Bridge - Admin Panel
After=network.target postgresql.service
Wants=postgresql.service

[Service]
Type=simple
User=${APP_USER}
Group=${APP_GROUP}
WorkingDirectory=${APP_DIR}
Environment=PATH=${VENV_DIR}/bin:/usr/local/bin:/usr/bin:/bin
Environment=PYTHONPATH=${APP_DIR}
EnvironmentFile=${APP_DIR}/.env
ExecStart=${VENV_DIR}/bin/uvicorn admin.web_app.main:app --host 127.0.0.1 --port 8000 --workers 2
Restart=always
RestartSec=5
StandardOutput=append:${LOG_DIR}/admin.log
StandardError=append:${LOG_DIR}/admin_error.log

[Install]
WantedBy=multi-user.target
EOF

    systemctl daemon-reload
    
    # Включаем сервисы
    systemctl enable telemail-bot
    systemctl enable telemail-receiver
    systemctl enable telemail-worker
    systemctl enable telemail-beat
    systemctl enable telemail-admin
    
    success "Systemd-сервисы созданы"
}

# ========== НАСТРОЙКА NGINX ==========
configure_nginx() {
    step "9/9 Настройка Nginx"
    
    # Загружаем переменные
    source ${APP_DIR}/.env 2>/dev/null || true
    
    # Извлекаем домен админки
    local admin_domain=$(grep ADMIN_BASE_URL ${APP_DIR}/.env | cut -d'=' -f2 | sed 's|https://||')
    local main_domain=$(grep BASE_URL ${APP_DIR}/.env | cut -d'=' -f2 | sed 's|https://||')
    
    # Конфигурация для админки
    cat > /etc/nginx/sites-available/telemail-admin << EOF
server {
    listen 80;
    server_name ${admin_domain};
    
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        
        # Увеличенные таймауты для админки
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
    }
    
    location /static {
        alias ${APP_DIR}/admin/static;
        expires 30d;
        add_header Cache-Control "public, immutable";
    }
    
    # Логи
    access_log ${LOG_DIR}/nginx_admin_access.log;
    error_log ${LOG_DIR}/nginx_admin_error.log;
}
EOF

    # Активируем сайт
    ln -sf /etc/nginx/sites-available/telemail-admin /etc/nginx/sites-enabled/
    
    # Проверяем конфигурацию
    nginx -t
    
    systemctl enable nginx
    systemctl restart nginx
    
    # Настройка SSL через Let's Encrypt (опционально)
    echo ""
    read -p "Настроить SSL через Let's Encrypt? (y/n): " -n 1 -r SETUP_SSL
    echo
    
    if [[ $SETUP_SSL =~ ^[Yy]$ ]]; then
        read -p "Email для Let's Encrypt: " LETSENCRYPT_EMAIL
        
        certbot --nginx \
            -d ${admin_domain} \
            --non-interactive \
            --agree-tos \
            --email ${LETSENCRYPT_EMAIL} \
            --redirect
        
        success "SSL настроен для ${admin_domain}"
    fi
    
    success "Nginx настроен"
}

# ========== ИНИЦИАЛИЗАЦИЯ БД ==========
init_database() {
    info "Инициализация базы данных..."
    
    cd ${APP_DIR}
    
    su - ${APP_USER} -c "
        source ${VENV_DIR}/bin/activate
        cd ${APP_DIR}
        python -c '
import asyncio
from core.db import init_db
asyncio.run(init_db())
print(\"База данных инициализирована успешно\")
'
    "
    
    # Создаём администратора
    read -p "Создать администратора? (y/n): " -n 1 -r CREATE_ADMIN
    echo
    
    if [[ $CREATE_ADMIN =~ ^[Yy]$ ]]; then
        su - ${APP_USER} -c "
            source ${VENV_DIR}/bin/activate
            cd ${APP_DIR}
            python -c '
import asyncio
from core.db import get_db
from database.models import User, UserRole
import bcrypt

async def create_admin():
    admin_password = \"${admin_password}\"
    password_hash = bcrypt.hashpw(admin_password.encode(), bcrypt.gensalt()).decode()
    
    async with get_db() as db:
        # Проверяем, есть ли уже админ с таким email
        from sqlalchemy import select
        result = await db.execute(
            select(User).where(User.email == \"${ADMIN_EMAIL}\")
        )
        existing = result.scalar_one_or_none()
        
        if existing:
            existing.role = UserRole.SUPERADMIN
            existing.admin_password_hash = password_hash
            print(f\"Администратор обновлён: ${ADMIN_EMAIL}\")
        else:
            admin = User(
                telegram_user_id=0,
                email=\"${ADMIN_EMAIL}\",
                role=UserRole.SUPERADMIN,
                admin_password_hash=password_hash,
                is_active=True
            )
            db.add(admin)
            print(f\"Администратор создан: ${ADMIN_EMAIL}\")
        
        await db.commit()

asyncio.run(create_admin())
'
        "
    fi
    
    success "База данных инициализирована"
}

# ========== ЗАПУСК СЕРВИСОВ ==========
start_services() {
    info "Запуск сервисов..."
    
    systemctl start telemail-bot
    sleep 2
    systemctl start telemail-receiver
    sleep 2
    systemctl start telemail-worker
    sleep 2
    systemctl start telemail-beat
    sleep 2
    systemctl start telemail-admin
    
    # Проверка статуса
    sleep 5
    
    local all_ok=true
    
    for service in telemail-bot telemail-receiver telemail-worker telemail-beat telemail-admin; do
        if systemctl is-active --quiet $service; then
            success "$service запущен"
        else
            error "$service не запустился"
            all_ok=false
        fi
    done
    
    if [ "$all_ok" = true ]; then
        success "Все сервисы запущены успешно!"
    else
        warn "Некоторые сервисы не запустились. Проверьте логи:"
        echo "  journalctl -u telemail-bot -f"
        echo "  journalctl -u telemail-receiver -f"
        echo "  ${LOG_DIR}/"
    fi
}

# ========== СОЗДАНИЕ СКРИПТОВ УПРАВЛЕНИЯ ==========
create_management_scripts() {
    # Скрипт для перезапуска всех сервисов
    cat > /usr/local/bin/telemail-restart << 'EOF'
#!/bin/bash
systemctl restart telemail-bot telemail-receiver telemail-worker telemail-beat telemail-admin
echo "Все сервисы перезапущены"
EOF
    chmod +x /usr/local/bin/telemail-restart
    
    # Скрипт для просмотра логов
    cat > /usr/local/bin/telemail-logs << 'EOF'
#!/bin/bash
echo "Выберите лог для просмотра:"
echo "1) Bot"
echo "2) Email Receiver"
echo "3) Celery Worker"
echo "4) Celery Beat"
echo "5) Admin Panel"
echo "6) Все (tail -f)"
read -p "> " choice

case $choice in
    1) journalctl -u telemail-bot -f ;;
    2) journalctl -u telemail-receiver -f ;;
    3) journalctl -u telemail-worker -f ;;
    4) journalctl -u telemail-beat -f ;;
    5) journalctl -u telemail-admin -f ;;
    6) tail -f /var/log/telemail/*.log ;;
    *) echo "Неверный выбор" ;;
esac
EOF
    chmod +x /usr/local/bin/telemail-logs
    
    # Скрипт для бэкапа
    cat > /usr/local/bin/telemail-backup << 'EOF'
#!/bin/bash
BACKUP_DIR="/var/lib/telemail/backups"
DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="${BACKUP_DIR}/telemail_backup_${DATE}.tar.gz"

echo "Создание бэкапа..."
pg_dump -U telemail telemail > "${BACKUP_DIR}/telemail_db_${DATE}.sql"
tar -czf "$BACKUP_FILE" \
    /opt/telemail-bridge/.env \
    /opt/telemail-bridge/sessions \
    "${BACKUP_DIR}/telemail_db_${DATE}.sql" \
    /etc/telemail/

echo "Бэкап создан: $BACKUP_FILE"

# Удаляем бэкапы старше 30 дней
find "$BACKUP_DIR" -name "telemail_backup_*.tar.gz" -mtime +30 -delete
EOF
    chmod +x /usr/local/bin/telemail-backup
    
    # Скрипт для обновления
    cat > /usr/local/bin/telemail-update << 'EOF'
#!/bin/bash
echo "Обновление TeleMail Bridge..."
cd /opt/telemail-bridge

# Останавливаем сервисы
systemctl stop telemail-bot telemail-receiver telemail-worker telemail-beat telemail-admin

# Обновляем код
su - telemail -c "cd /opt/telemail-bridge && git pull"

# Обновляем зависимости
su - telemail -c "
    source /opt/telemail-bridge/venv/bin/activate
    pip install -r /opt/telemail-bridge/requirements.txt
"

# Запускаем сервисы
systemctl start telemail-bot telemail-receiver telemail-worker telemail-beat telemail-admin

echo "Обновление завершено"
EOF
    chmod +x /usr/local/bin/telemail-update
    
    success "Скрипты управления созданы:"
    echo "  telemail-restart  - перезапуск всех сервисов"
    echo "  telemail-logs     - просмотр логов"
    echo "  telemail-backup   - создание бэкапа"
    echo "  telemail-update   - обновление из репозитория"
}

# ========== ЗАВЕРШЕНИЕ ==========
print_summary() {
    source ${APP_DIR}/.env 2>/dev/null || true
    
    echo ""
    echo -e "${GREEN}═══════════════════════════════════════════════════════════════${NC}"
    echo -e "${GREEN}  TeleMail Bridge успешно установлен!${NC}"
    echo -e "${GREEN}═══════════════════════════════════════════════════════════════${NC}"
    echo ""
    echo -e "${BLUE}📊 Статус сервисов:${NC}"
    echo "  systemctl status telemail-bot telemail-receiver telemail-worker telemail-beat telemail-admin"
    echo ""
    echo -e "${BLUE}📝 Логи:${NC}"
    echo "  ${LOG_DIR}/"
    echo ""
    echo -e "${BLUE}🔑 Учётные данные:${NC}"
    echo "  ${CONFIG_DIR}/credentials.txt"
    echo ""
    echo -e "${BLUE}🛠 Управление:${NC}"
    echo "  telemail-restart  - перезапуск всех сервисов"
    echo "  telemail-logs     - просмотр логов"
    echo "  telemail-backup   - создание бэкапа"
    echo "  telemail-update   - обновление из GitHub"
    echo ""
    echo -e "${BLUE}🌐 Доступ:${NC}"
    echo "  Админка: https://$(grep ADMIN_BASE_URL ${APP_DIR}/.env | cut -d'=' -f2 | sed 's|https://||')"
    echo "  Бот: @$(echo ${BOT_TOKEN} | cut -d: -f1)"
    echo ""
    echo -e "${YELLOW}⚠️ Не забудьте:${NC}"
    echo "  1. Сохранить ${CONFIG_DIR}/credentials.txt в безопасном месте"
    echo "  2. Настроить catch-all email (входящие письма должны попадать в ящик)"
    echo "  3. Проверить логи: journalctl -u telemail-bot -f"
    echo ""
    echo -e "${GREEN}═══════════════════════════════════════════════════════════════${NC}"
}

# ========== ОСНОВНАЯ ФУНКЦИЯ ==========
main() {
    echo ""
    echo -e "${MAGENTA}╔══════════════════════════════════════════════════════════╗${NC}"
    echo -e "${MAGENTA}║                                                          ║${NC}"
    echo -e "${MAGENTA}║       🌉 TeleMail Bridge - Установщик для Debian 12       ║${NC}"
    echo -e "${MAGENTA}║                                                          ║${NC}"
    echo -e "${MAGENTA}╚══════════════════════════════════════════════════════════╝${NC}"
    echo ""
    echo -e "Этот скрипт установит TeleMail Bridge на чистый Debian 12."
    echo -e "Будут установлены: PostgreSQL, Redis, Python 3.12, Nginx."
    echo -e "Общий размер установки: ~2 ГБ."
    echo ""
    read -p "Продолжить? (y/n): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 0
    fi
    
    # Выполняем все шаги
    check_root
    check_debian
    check_resources
    install_system_packages
    create_user_and_dirs
    install_postgresql
    install_redis
    clone_repository
    setup_python_env
    configure_app
    create_systemd_services
    init_database
    configure_nginx
    create_management_scripts
    start_services
    print_summary
}

# Запускаем
main "$@"