# core/config.py
import os
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field
from dotenv import load_dotenv

# Загружаем .env файл
env_path = Path(__file__).parent.parent / '.env'
load_dotenv(env_path)


@dataclass
class Settings:
    """Настройки приложения"""
    
    # ========== Бот ==========
    BOT_TOKEN: str = os.getenv('BOT_TOKEN', '')
    
    # ========== Telegram API (для Telethon) ==========
    TELEGRAM_API_ID: int = int(os.getenv('TELEGRAM_API_ID', '0'))
    TELEGRAM_API_HASH: str = os.getenv('TELEGRAM_API_HASH', '')
    
    # ========== База данных ==========
    DATABASE_URL: str = os.getenv(
        'DATABASE_URL',
        'postgresql+asyncpg://telemail:password@localhost/telemail'
    )
    DATABASE_POOL_SIZE: int = int(os.getenv('DATABASE_POOL_SIZE', '20'))
    DATABASE_MAX_OVERFLOW: int = int(os.getenv('DATABASE_MAX_OVERFLOW', '40'))
    
    # ========== Redis ==========
    REDIS_URL: Optional[str] = os.getenv('REDIS_URL', None)
    REDIS_HOST: str = os.getenv('REDIS_HOST', 'localhost')
    REDIS_PORT: int = int(os.getenv('REDIS_PORT', '6379'))
    REDIS_PASSWORD: Optional[str] = os.getenv('REDIS_PASSWORD', None)
    REDIS_DB_FSM: int = int(os.getenv('REDIS_DB_FSM', '0'))
    
    # ========== Email (catch-all для приёма ответов) ==========
    CATCH_ALL_EMAIL: str = os.getenv('CATCH_ALL_EMAIL', 'incoming@telemail.app')
    CATCH_ALL_PASSWORD: str = os.getenv('CATCH_ALL_PASSWORD', '')
    CATCH_ALL_IMAP_HOST: str = os.getenv('CATCH_ALL_IMAP_HOST', 'imap.gmail.com')
    CATCH_ALL_IMAP_PORT: int = int(os.getenv('CATCH_ALL_IMAP_PORT', '993'))
    CATCH_ALL_DOMAIN: str = os.getenv('CATCH_ALL_DOMAIN', 'telemail.app')
    SMTP_FROM_ADDRESS: str = os.getenv('SMTP_FROM_ADDRESS', 'bot@telemail.app')
    
    # ========== Шифрование ==========
    ENCRYPTION_KEY: str = os.getenv(
        'ENCRYPTION_KEY',
        'default-key-change-in-production-32bytes!'
    )
    
    # ========== Платежи ==========
    YOOKASSA_SHOP_ID: Optional[str] = os.getenv('YOOKASSA_SHOP_ID', None)
    YOOKASSA_SECRET_KEY: Optional[str] = os.getenv('YOOKASSA_SECRET_KEY', None)
    STRIPE_SECRET_KEY: Optional[str] = os.getenv('STRIPE_SECRET_KEY', None)
    STRIPE_WEBHOOK_SECRET: Optional[str] = os.getenv('STRIPE_WEBHOOK_SECRET', None)
    
    # ========== JWT (админка) ==========
    JWT_SECRET: str = os.getenv('JWT_SECRET', 'admin-jwt-secret-change-me')
    JWT_EXPIRATION_HOURS: int = int(os.getenv('JWT_EXPIRATION_HOURS', '12'))
    
    # ========== Лимиты ==========
    DEFAULT_DAILY_LIMIT_FREE: int = 50
    DEFAULT_DAILY_LIMIT_PRO: int = 10000  # "безлимит"
    DEFAULT_DAILY_LIMIT_BUSINESS: int = 100000
    
    MAX_ATTACHMENT_SIZE: int = 50 * 1024 * 1024  # 50 МБ
    
    # ========== Логирование ==========
    LOG_LEVEL: str = os.getenv('LOG_LEVEL', 'INFO')
    
    # ========== Серверные настройки ==========
    BASE_URL: str = os.getenv('BASE_URL', 'https://telemail.app')
    ADMIN_BASE_URL: str = os.getenv('ADMIN_BASE_URL', 'https://admin.telemail.app')
    
    # ========== Celery ==========
    CELERY_BROKER_URL: str = os.getenv('CELERY_BROKER_URL', 'redis://localhost:6379/0')
    CELERY_RESULT_BACKEND: str = os.getenv('CELERY_RESULT_BACKEND', 'redis://localhost:6379/0')
    
    def validate(self):
        """Проверка обязательных настроек"""
        required = {
            'BOT_TOKEN': self.BOT_TOKEN,
            'TELEGRAM_API_ID': self.TELEGRAM_API_ID,
            'TELEGRAM_API_HASH': self.TELEGRAM_API_HASH,
            'DATABASE_URL': self.DATABASE_URL,
        }
        
        missing = [k for k, v in required.items() if not v]
        
        if missing:
            raise ValueError(
                f"Отсутствуют обязательные переменные окружения: {', '.join(missing)}"
            )
        
        if self.ENCRYPTION_KEY == 'default-key-change-in-production-32bytes!':
            import warnings
            warnings.warn(
                "⚠️ Используется стандартный ключ шифрования! "
                "Установите ENCRYPTION_KEY в .env для продакшена."
            )


# Создаём глобальный экземпляр настроек
settings = Settings()
settings.validate()