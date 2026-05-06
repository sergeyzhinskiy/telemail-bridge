# core/telethon_manager.py
import asyncio
import logging
import base64
from typing import Dict, Optional

from telethon import TelegramClient

from core.config import settings
from core.security import decrypt_data

logger = logging.getLogger(__name__)


class TelethonSessionManager:
    """Управление сессиями пользователей"""

    _clients: Dict[int, TelegramClient] = {}
    _listeners: Dict[int, asyncio.Task] = {}

    @classmethod
    async def create_client(cls, phone: str = None, user_id: int = None) -> TelegramClient:
        """Создать новый клиент"""
        session_name = f"sessions/user_{user_id or phone or 'temp'}"

        client = TelegramClient(
            session_name,
            settings.TELEGRAM_API_ID,
            settings.TELEGRAM_API_HASH,
            device_model="TeleMail Bridge",
            system_version="1.0.0",
            app_version="1.0.0"
        )
        await client.connect()
        return client

    @classmethod
    async def load_client_from_session(cls, session_string: str, user_id: int) -> TelegramClient:
        """Загрузить клиент из строки сессии"""
        session_file = f"sessions/user_{user_id}.session"

        with open(session_file, 'wb') as f:
            f.write(base64.b64decode(session_string))

        client = TelegramClient(
            session_file,
            settings.TELEGRAM_API_ID,
            settings.TELEGRAM_API_HASH,
            device_model="TeleMail Bridge",
            system_version="1.0.0",
            app_version="1.0.0"
        )
        await client.connect()
        return client

    @classmethod
    async def start_listener(cls, user) -> None:
        """Запустить прослушивание для пользователя"""
        from core.telegram_listener import TelegramListener

        if user.id in cls._listeners:
            await cls.stop_listener(user.id)

        session_string = decrypt_data(user.telethon_session_string)
        client = await cls.load_client_from_session(session_string, user.id)

        listener = TelegramListener(client, user)
        task = asyncio.create_task(listener.run())

        cls._clients[user.id] = client
        cls._listeners[user.id] = task

        logger.info(f"Слушатель запущен для user_id={user.id}")

    @classmethod
    async def stop_listener(cls, user_id: int) -> None:
        """Остановить прослушивание"""
        if user_id in cls._listeners:
            task = cls._listeners[user_id]
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            del cls._listeners[user_id]
            logger.info(f"Слушатель остановлен для user_id={user_id}")

        if user_id in cls._clients:
            try:
                await cls._clients[user_id].disconnect()
            except Exception as e:
                logger.warning(f"Ошибка отключения клиента {user_id}: {e}")
            del cls._clients[user_id]

    @classmethod
    async def restart_listener(cls, user) -> None:
        """Перезапустить слушатель"""
        await cls.stop_listener(user.id)
        await cls.start_listener(user)

    @classmethod
    def get_client(cls, user_id: int) -> Optional[TelegramClient]:
        """Получить клиент по ID"""
        return cls._clients.get(user_id)