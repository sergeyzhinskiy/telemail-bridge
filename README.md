# telemail-bridge
# 🌉 TeleMail Bridge

**Email-шлюз для Telegram на случай блокировки.** (в процессе разработки\ **тестирования**)

[![Python](https://img.shields.io/badge/Python-3.11-blue.svg)](https://python.org)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
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

===================================================

# 🌉 TeleMail Bridge

**TeleMail Bridge** is a service that turns your email into a gateway to Telegram. When Telegram is blocked, you can keep talking to your contacts using nothing but your mailbox. The bot automatically forwards incoming private Telegram messages to your email, and your replies are sent back to Telegram.

As the administrator, you run the backend on your Windows PC or VPS. Users (including yourself) register with the bot and link their email inboxes. Then they communicate the usual way – via Gmail, Mail.ru, Yandex.Mail, etc.

---

## 🛠 1. What you need to get started

- A computer running **Windows 10 (build 1809 or newer)** or **Windows 11**.
- At least **4 GB of RAM**.
- About **12 GB of free space** on drive `C:`.
- A stable internet connection.
- An **administrator account** (Windows administrator rights).
- A **Telegram account** (to create a bot and obtain API credentials).
- Software that the script will install automatically: Python 3.11, PostgreSQL 16, Redis, Git, ffmpeg (you don’t need to install anything manually).

---

## 🚀 2. Server installation in 10 minutes

1. **Download** the installation script `install.ps1` (the latest version you received).
2. Press `Win + X` → choose `Windows PowerShell (Admin)` or `Terminal (Admin)`.
3. **Navigate** to the folder containing the script, e.g.:
   ```powershell
   cd C:\bots\telemail_bridge
   ```
4. Allow script execution and run it:

   ```powershell
  Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
  .\install.ps1
  ```
5.Answer the questions asked by the script.

6. After installation finishes, shortcuts TeleMail Admin and TeleMail Management (service management) will appear on your desktop.

7. Open the file C:\TeleMailBridge\config\credentials.txt – it contains the admin password and other important data.

 📌 **Important:** During installation, the script will ask for the Telegram Bot Token, API ID, and API Hash – all of these are obtained from @BotFather and my.telegram.org/apps.

## 👥 4. How users register and start communicating
The user finds your bot on Telegram (via a link you give them).

1. They send the /start command.

2. The bot asks for their email and password (or an app password).

3. Then the bot asks them to log into Telegram – enter their phone number and the SMS code. This is required so the bot can listen to the user’s private messages and forward them to email.

4. After successful login, private Telegram messages start arriving at the provided email address.

5. To reply to a message, the user simply replies to the email – the reply is automatically sent back to Telegram.

🔐 **Privacy:** email passwords are stored encrypted. The bot uses a Telegram session only to forward messages; only the user themselves has access to their conversations.
   
