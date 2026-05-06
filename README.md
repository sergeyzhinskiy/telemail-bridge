# telemail-bridge
# 🌉 TeleMail Bridge

**Email-шлюз для Telegram на случай блокировки.** (в процессе разработки)

[![Python](https://img.shields.io/badge/Python-3.12-blue.svg)](https://python.org)
[![License](https://img.shields.io/badge/License-GPT3-green.svg)](LICENSE)
[![Docker](https://img.shields.io/badge/Docker-ready-brightgreen.svg)](docker-compose.yml)
[![Telegram](https://img.shields.io/badge/Telegram-Bot-blue.svg)](https://t.me/telemail_bot)

<p align="center">
  <img src="assets/logo.png" alt="TeleMail Bridge Logo" width="200"/>
</p>

## 📌 Проблема

В 2026 году Telegram заблокирован на территории РФ. Миллионы пользователей потеряли доступ к своему основному средству коммуникации. VPN работает нестабильно, прокси отваливаются, а люди остаются без связи с близкими, коллегами и клиентами.

## 💡 Решение

**TeleMail Bridge** превращает обычную электронную почту в полноценный мост в Telegram. Вы продолжаете общаться со своими контактами в Telegram, но вместо приложения используете привычный email-клиент на телефоне или компьютере.

Email невозможно заблокировать — это базовая инфраструктура интернета. Ваши сообщения всегда дойдут, потому что они идут по протоколам, которые используются всем миром уже 50 лет.

## 🚀 Как это работает

### Пошагово:

1. **Один раз** регистрируетесь в боте через VPN/прокси
2. Указываете свою почту (Gmail, Mail.ru, Яндекс — любую)
3. Авторизуете Telegram-сессию через SMS
4. **Всё!** Дальше общаетесь только через почту:
   - Получаете сообщения из Telegram как email-письма
   - Отвечаете на письма — бот отправляет ответ в Telegram
   - Поддерживаются: текст, фото, видео, голосовые, документы

## ✨ Возможности

- 📧 **Полная интеграция с email** — используйте любой почтовый клиент
- 🔄 **Двусторонняя синхронизация** — входящие и исходящие сообщения
- 📎 **Все типы сообщений** — текст, фото, видео, голосовые, документы
- 🎤 **Голосовые сообщения** — слушайте прямо из почтового клиента
- 📹 **Видео и фото** — приходят как вложения в письмах
- ⭐ **Избранные контакты** — быстрый доступ к важным чатам
- 🔐 **Шифрование** — доступы к почте и сессии хранятся зашифрованными
- 📊 **Статистика** — отслеживайте количество сообщений
- 💎 **Тарифы** — от бесплатного до Enterprise

## 🛠 Технологический стек

| Компонент | Технология |
|-----------|-----------|
| **Telegram User API** | Telethon 1.36 |
| **Telegram Bot API** | Aiogram 2.25 |
| **Email SMTP** | aiosmtplib 3.0 |
| **Email IMAP** | aioimaplib 1.0 |
| **База данных** | PostgreSQL 16 + SQLAlchemy 2.0 |
| **Кэш/Очереди** | Redis 7 + Celery 5.4 |
| **Админ-панель** | FastAPI + Jinja2 + Bootstrap 5 |
| **Платежи** | ЮKassa / Telegram Stars / Stripe |
| **Деплой** | Docker + Docker Compose + Nginx |
| **Мониторинг** | Логирование + Healthcheck |

## 📦 Быстрый старт

### Предварительные требования

- VPS сервер за пределами РФ (Германия, Нидерланды, Финляндия — оптимально)
- Docker и Docker Compose
- Домен (для админки и catch-all почты)
- Telegram API ID и Hash ([my.telegram.org](https://my.telegram.org/apps))
- Бот-токен ([@BotFather](https://t.me/BotFather))

### Установка

```bash
# 1. Клонируем репозиторий
git clone https://github.com/yourusername/telemail-bridge.git
cd telemail-bridge

# 2. Настраиваем переменные окружения
cp .env.example .env
nano .env  # Заполняем все поля

# 3. Запускаем
docker-compose up -d

# 4. Проверяем логи
docker-compose logs -f bot
```
Переменные окружения (.env)
```env
# === ОБЯЗАТЕЛЬНЫЕ ===
BOT_TOKEN=123456:ABC-DEF1234ghikl-zyx57W2v1u123ew11
TELEGRAM_API_ID=123456
TELEGRAM_API_HASH=0123456789abcdef0123456789abcdef
DATABASE_URL=postgresql+asyncpg://telemail:strongpassword@postgres/telemail
ENCRYPTION_KEY=your-32-byte-encryption-key-here!

# === CATCH-ALL ПОЧТА (для приёма ответов пользователей) ===
CATCH_ALL_EMAIL=incoming@yourdomain.com
CATCH_ALL_PASSWORD=app-password-here
CATCH_ALL_IMAP_HOST=imap.gmail.com
CATCH_ALL_IMAP_PORT=993
CATCH_ALL_DOMAIN=yourdomain.com
SMTP_FROM_ADDRESS=bot@yourdomain.com

# === ПЛАТЕЖИ (опционально) ===
YOOKASSA_SHOP_ID=your-shop-id
YOOKASSA_SECRET_KEY=your-secret-key
STRIPE_SECRET_KEY=sk_live_xxx

# === АДМИНКА ===
JWT_SECRET=your-admin-jwt-secret
BASE_URL=https://yourdomain.com
ADMIN_BASE_URL=https://admin.yourdomain.com
```

### 🏗 Архитектура проекта
```text
telemail-bridge/
├── bot/                          # Telegram Bot (Aiogram)
│   ├── main.py                   # 🔵 Точка входа
│   ├── handlers/
│   │   ├── registration.py       # Регистрация пользователя + Telethon
│   │   ├── settings.py           # Команды /status, /contacts, /help, /settings
│   │   └── payments.py           # Платежи Telegram Stars, ЮKassa
│   └── middlewares/
│       ├── subscription.py       # Проверка лимитов и подписки
│       ├── logging.py            # Логирование всех действий
│       └── banned_user.py        # Блокировка забаненных
├── core/                         # Ядро системы
│   ├── telegram_listener.py      # 🔵 Прослушивание ЛС через Telethon
│   ├── telegram_sender.py        # 🔵 Отправка сообщений от имени пользователя
│   ├── telethon_manager.py       # Менеджер Telethon-сессий
│   ├── email_sender.py           # Отправка email-уведомлений
│   ├── email_receiver.py         # Приём ответов с email (IMAP)
│   ├── security.py               # Шифрование паролей и сессий
│   ├── config.py                 # Конфигурация приложения
│   └── db.py                     # Асинхронная работа с PostgreSQL
├── admin/                        # Административная панель
│   ├── web_app/
│   │   └── main.py               # 🔵 FastAPI приложение
│   └── templates/
│       ├── base.html             # Базовый шаблон Bootstrap 5
│       ├── login.html            # Страница входа
│       ├── dashboard.html        # Дашборд со статистикой
│       └── users.html            # Управление пользователями
├── payments/                     # Платёжная система
│   ├── providers/
│   │   ├── yookassa.py           # Интеграция ЮKassa
│   │   ├── stripe.py             # Интеграция Stripe
│   │   └── stars.py              # Telegram Stars
│   └── billing.py                # Логика биллинга
├── database/
│   └── models.py                 # 🔵 Все модели SQLAlchemy (8 таблиц)
├── docker/
│   ├── Dockerfile                # Сборка образа
│   ├── docker-compose.yml        # 🔵 7 сервисов
│   └── nginx.conf                # Конфигурация reverse proxy
├── .env.example                  # Пример переменных окружения
├── requirements.txt              # Python-зависимости
├── LICENSE                       # MIT
└── README.md                     # Вы здесь
```

### 🔐 Безопасность
Пароли почты хранятся в БД в зашифрованном виде (AES-256)

Telethon-сессии шифруются перед сохранением

Admin JWT-токены с ограниченным временем жизни (12 часов)

HTTPS для админ-панели (Traefik + Let's Encrypt)

API-key для программного доступа к админке

Логирование всех действий администраторов

Мягкое удаление — данные не удаляются безвозвратно

