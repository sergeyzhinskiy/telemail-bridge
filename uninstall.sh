#!/bin/bash
###############################################################################
# TeleMail Bridge - Скрипт удаления
###############################################################################

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${RED}⚠️ ВНИМАНИЕ: Полное удаление TeleMail Bridge!${NC}"
echo "Будут удалены:"
echo "  - Файлы приложения"
echo "  - База данных"
echo "  - Конфигурация"
echo "  - Логи"
echo "  - Systemd-сервисы"
echo ""
read -p "Вы уверены? Введите DELETE для подтверждения: " CONFIRM

if [ "$CONFIRM" != "DELETE" ]; then
    echo "Отмена."
    exit 0
fi

echo -e "${YELLOW}Удаление...${NC}"

# Остановка сервисов
systemctl stop telemail-bot telemail-receiver telemail-worker telemail-beat telemail-admin 2>/dev/null || true
systemctl disable telemail-bot telemail-receiver telemail-worker telemail-beat telemail-admin 2>/dev/null || true

# Удаление файлов сервисов
rm -f /etc/systemd/system/telemail-bot.service
rm -f /etc/systemd/system/telemail-receiver.service
rm -f /etc/systemd/system/telemail-worker.service
rm -f /etc/systemd/system/telemail-beat.service
rm -f /etc/systemd/system/telemail-admin.service
systemctl daemon-reload

# Удаление Nginx конфига
rm -f /etc/nginx/sites-enabled/telemail-admin
rm -f /etc/nginx/sites-available/telemail-admin
systemctl restart nginx 2>/dev/null || true

# Удаление скриптов управления
rm -f /usr/local/bin/telemail-restart
rm -f /usr/local/bin/telemail-logs
rm -f /usr/local/bin/telemail-backup
rm -f /usr/local/bin/telemail-update

# Удаление БД
su - postgres -c "psql -c \"DROP DATABASE IF EXISTS telemail;\"" 2>/dev/null || true
su - postgres -c "psql -c \"DROP USER IF EXISTS telemail;\"" 2>/dev/null || true

# Удаление файлов
rm -rf /opt/telemail-bridge
rm -rf /var/log/telemail
rm -rf /var/lib/telemail
rm -rf /etc/telemail

# Удаление пользователя
userdel -r telemail 2>/dev/null || true

echo -e "${GREEN}TeleMail Bridge удалён.${NC}"