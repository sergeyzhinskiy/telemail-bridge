# core/email_receiver.py
import asyncio
import logging
import re
from email import message_from_bytes
from datetime import datetime

from aioimaplib import aioimaplib
from sqlalchemy import select

from core.config import settings
from core.db import get_db, get_user, log_message
from core.telegram_sender import telegram_sender
from core.security import decrypt_data

logger = logging.getLogger(__name__)


class EmailReceiver:
    """Слушает catch-all ящик для получения ответов от пользователей"""

    def __init__(self):
        self.imap = None
        self._running = False

    async def start(self):
        """Запуск IMAP слушателя"""
        logger.info("Email-приёмник запускается...")

        self.imap = aioimaplib.IMAP4_SSL(
            host=settings.CATCH_ALL_IMAP_HOST,
            port=settings.CATCH_ALL_IMAP_PORT
        )

        await self.imap.login(
            settings.CATCH_ALL_EMAIL,
            settings.CATCH_ALL_PASSWORD
        )

        await self.imap.select('INBOX')
        self._running = True

        logger.info(f"Email-приёмник запущен ({settings.CATCH_ALL_EMAIL})")

        while self._running:
            try:
                status, messages = await self.imap.search('UNSEEN')

                if messages and messages[0]:
                    for msg_id in messages[0].split():
                        try:
                            await self._process_incoming_email(msg_id)
                        except Exception as e:
                            logger.error(f"Ошибка обработки письма {msg_id}: {e}", exc_info=True)

                await self.imap.idle_start(timeout=30)
                await self.imap.wait_server_push()
                self.imap.idle_done()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Ошибка IMAP цикла: {e}", exc_info=True)
                await asyncio.sleep(10)

    async def stop(self):
        """Остановка слушателя"""
        self._running = False
        if self.imap:
            try:
                await self.imap.logout()
            except Exception:
                pass
        logger.info("Email-приёмник остановлен")

    async def _process_incoming_email(self, msg_id: bytes):
        """Обработка входящего письма"""
        status, msg_data = await self.imap.fetch(msg_id, '(RFC822)')

        if not msg_data or not msg_data[0]:
            return

        raw_email = msg_data[0][1]
        msg = message_from_bytes(raw_email)

        to_address = msg.get('To', '')

        pattern = r'reply\+(\d+)\+(\d+)@'
        match = re.search(pattern, to_address)

        if not match:
            await self.imap.store(msg_id, '+FLAGS', '\\Seen')
            return

        user_id = int(match.group(1))
        chat_id = int(match.group(2))

        body = self._extract_reply_text(msg)

        async with get_db() as db:
            result = await db.execute(select(User).where(User.id == user_id))
            user = result.scalar_one_or_none()

            from database.models import User

            if not user:
                logger.warning(f"Пользователь {user_id} не найден для ответа")
                await self.imap.store(msg_id, '+FLAGS', '\\Seen')
                return

            if not await self._check_user_can_reply(user):
                await self.imap.store(msg_id, '+FLAGS', '\\Seen')
                return

            success = await telegram_sender.send_message(
                user=user,
                chat_id=chat_id,
                text=body
            )

            if success:
                await log_message(
                    user_id=user_id,
                    direction='outgoing',
                    message_type='text',
                    status='delivered',
                    email_message_id=msg.get('Message-ID', ''),
                )

                user.messages_today = (user.messages_today or 0) + 1
                user.total_messages_sent = (user.total_messages_sent or 0) + 1
                user.last_active_at = datetime.utcnow()
                await db.commit()

                logger.info(f"Ответ доставлен: user={user_id}, chat={chat_id}")

        await self.imap.store(msg_id, '+FLAGS', '\\Seen')

    async def _check_user_can_reply(self, user) -> bool:
        """Проверка, может ли пользователь отвечать"""
        if user.is_banned:
            logger.info(f"Забаненный пользователь {user.id} пытался ответить")
            return False

        if not user.is_active:
            logger.info(f"Неактивный пользователь {user.id} пытался ответить")
            return False

        if user.subscription_tier.value == 'free':
            if user.messages_today >= user.daily_limit:
                logger.info(f"Лимит превышен для пользователя {user.id}")
                return False

        return True

    def _extract_reply_text(self, msg) -> str:
        """Извлечение текста ответа (обрезаем цитирование)"""
        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                if content_type == 'text/plain':
                    try:
                        payload = part.get_payload(decode=True)
                        if payload:
                            charset = part.get_content_charset() or 'utf-8'
                            try:
                                text = payload.decode(charset)
                            except (UnicodeDecodeError, LookupError):
                                text = payload.decode('utf-8', errors='ignore')
                            return self._clean_reply_text(text)
                    except Exception:
                        continue
        else:
            try:
                payload = msg.get_payload(decode=True)
                if payload:
                    charset = msg.get_content_charset() or 'utf-8'
                    try:
                        text = payload.decode(charset)
                    except (UnicodeDecodeError, LookupError):
                        text = payload.decode('utf-8', errors='ignore')
                    return self._clean_reply_text(text)
            except Exception:
                pass

        return "[Пустое сообщение]"

    def _clean_reply_text(self, text: str) -> str:
        """Удаляем цитируемый текст"""
        for separator in [
            '\n> ', '\n>', '\nOn ', '\n—',
            '\n---', '\n‐‐‐', 'From:',
            '\n>On ', '\n> On ',
            '\nSent from', '\nОтправлено из',
            '\nПользователь ', '\nUser ',
        ]:
            if separator in text:
                text = text.split(separator)[0]

        return text.strip()


# Глобальный экземпляр
email_receiver = EmailReceiver()