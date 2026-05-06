# core/__init__.py
"""
Ядро TeleMail Bridge.

Основные модули:
- telegram_listener: Прослушивание новых сообщений в Telegram
- telegram_sender: Отправка сообщений в Telegram от имени пользователя
- telethon_manager: Управление Telethon-сессиями
- email_sender: Отправка email-уведомлений
- email_receiver: Приём ответов с email (IMAP)
- security: Шифрование и безопасность
- config: Конфигурация приложения
- db: Асинхронная работа с PostgreSQL
- tasks: Фоновые задачи Celery
"""

__version__ = '1.0.0'
__author__ = 'TeleMail Bridge Team'