# core/telegram_listener.py
import asyncio
import logging
from datetime import datetime

from telethon import TelegramClient, events
from telethon.tl.types import (
    MessageMediaPhoto, MessageMediaDocument,
    MessageMediaWebPage
)

from core.config import settings
from core.email_sender import EmailSender
from core.db import get_db, get_chat_mapping, create_chat_mapping, log_message

logger = logging.getLogger(__name__)


class TelegramListener:
    """Слушает личные сообщения пользователя и пересылает на email"""

    def __init__(self, client: TelegramClient, user):
        self.client = client
        self.user = user
        self.email_sender = EmailSender()
        self._running = False

    async def run(self):
        """Запуск слушателя"""
        self._running = True

        @self.client.on(events.NewMessage(incoming=True))
        async def handle_new_message(event):
            if not self._running:
                return

            if not event.is_private:
                return

            if event.message.out:
                return

            try:
                await self._process_incoming_message(event.message)
            except Exception as e:
                logger.error(f"Ошибка обработки сообщения: {e}", exc_info=True)

        logger.info(f"Слушатель запущен для user_id={self.user.id}")

        while self._running:
            try:
                await asyncio.sleep(1)
            except asyncio.CancelledError:
                break

        logger.info(f"Слушатель остановлен для user_id={self.user.id}")

    async def _process_incoming_message(self, message):
        """Обработка входящего сообщения из Telegram"""
        sender = await message.get_sender()

        if self.user.subscription_tier.value == 'free':
            if self.user.messages_today >= self.user.daily_limit:
                logger.info(f"Лимит превышен для user_id={self.user.id}")
                return

        msg_type, attachment = await self._extract_message_content(message)

        email_data = {
            'chat_id': message.chat_id,
            'sender_name': getattr(sender, 'first_name', 'Неизвестный'),
            'sender_username': getattr(sender, 'username', None),
            'sender_id': sender.id,
            'message_type': msg_type,
            'text': message.text or '',
            'attachment': attachment,
            'message_id': message.id,
            'date': message.date.isoformat()
        }

        await self.email_sender.send_telegram_message_to_email(
            user=self.user,
            email_data=email_data
        )

        await self._update_chat_mapping(message, sender)

        await log_message(
            user_id=self.user.id,
            direction='incoming',
            message_type=msg_type,
            telegram_message_id=message.id,
            status='delivered',
            size_bytes=len(attachment) if attachment else None,
        )

        self.user.messages_today = (self.user.messages_today or 0) + 1
        self.user.total_messages_sent = (self.user.total_messages_sent or 0) + 1
        self.user.last_active_at = datetime.utcnow()

        async with get_db() as db:
            merged = await db.merge(self.user)
            await db.commit()

    async def _extract_message_content(self, message):
        """Извлечение контента сообщения"""
        msg_type = 'text'
        attachment = None

        if message.media:
            if isinstance(message.media, MessageMediaPhoto):
                msg_type = 'photo'
                attachment = await message.download_media(bytes)

            elif isinstance(message.media, MessageMediaDocument):
                mime_type = message.file.mime_type if message.file else ''

                if 'voice' in (mime_type or '') or message.voice:
                    msg_type = 'voice'
                elif 'video' in (mime_type or '') or message.video:
                    msg_type = 'video'
                elif 'audio' in (mime_type or ''):
                    msg_type = 'audio'
                else:
                    msg_type = 'document'

                if message.file and message.file.size > settings.MAX_ATTACHMENT_SIZE:
                    msg_type = 'file_too_large'
                else:
                    attachment = await message.download_media(bytes)

            elif isinstance(message.media, MessageMediaWebPage):
                msg_type = 'link'

        return msg_type, attachment

    async def _update_chat_mapping(self, message, sender):
        """Обновление информации о чате"""
        mapping = await get_chat_mapping(self.user.id, message.chat_id)

        if not mapping:
            mapping = await create_chat_mapping(
                user_id=self.user.id,
                telegram_chat_id=message.chat_id,
                correspondent_name=getattr(sender, 'first_name', 'Неизвестный'),
                correspondent_username=getattr(sender, 'username', None),
                correspondent_phone=getattr(sender, 'phone', None),
                correspondent_telegram_id=sender.id
            )

        mapping.last_message_id = message.id
        mapping.last_message_text = (message.text or '')[:200]
        mapping.last_message_at = message.date
        mapping.messages_count = (mapping.messages_count or 0) + 1

        async with get_db() as db:
            await db.merge(mapping)
            await db.commit()