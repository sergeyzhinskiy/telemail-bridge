# core/email_receiver.py
import asyncio
import logging
import re
from email import message_from_bytes
from datetime import datetime

from aioimaplib import aioimaplib
from sqlalchemy import select

from core.config import settings
from core.db import get_db, log_message
from core.telegram_sender import telegram_sender

logger = logging.getLogger(__name__)


class EmailReceiver:
    """Слушает catch-all ящик для получения ответов от пользователей"""

    def __init__(self):
        self.imap = None
        self._running = False

    async def _connect(self):
        """Подключиться к IMAP и авторизоваться."""
        if self.imap:
            try:
                await self.imap.logout()
            except Exception:
                pass
        self.imap = aioimaplib.IMAP4_SSL(
            host=settings.CATCH_ALL_IMAP_HOST,
            port=settings.CATCH_ALL_IMAP_PORT,
            timeout=30
        )
        await self.imap.wait_hello_from_server()
        await self.imap.login(
            settings.CATCH_ALL_EMAIL,
            settings.CATCH_ALL_PASSWORD
        )
        await self.imap.select('INBOX')
        logger.info(f"Connected to IMAP as {settings.CATCH_ALL_EMAIL}")

    async def start(self):
        """Запуск слушателя с восстановлением соединения."""
        logger.info("Email receiver starting...")
        self._running = True
        consecutive_errors = 0

        while self._running:
            try:
                if not self.imap or self.imap.get_state() == 'LOGOUT':
                    await self._connect()
                    consecutive_errors = 0
                # Ищем непрочитанные письма
                status, messages = await self.imap.search('UNSEEN')
                if messages[0]:
                    msg_ids = messages[0].split()
                    logger.info(f"Found {len(msg_ids)} unseen messages")
                    # Обрабатываем не более 10 писем за раз, чтобы не перегружать соединение
                    for msg_id in msg_ids[:10]:
                        try:
                            await self._process_incoming_email(msg_id)
                        except Exception as e:
                            logger.error(f"Error processing email {msg_id}: {e}", exc_info=True)
                            # Помечаем прочитанным даже при ошибке, чтобы не зациклиться
                            await self._safe_store(msg_id)
                            continue
                # Ждём новые письма через IDLE
                await self.imap.idle_start(timeout=30)
                await self.imap.wait_server_push()
                self.imap.idle_done()
            except asyncio.CancelledError:
                break
            except (aioimaplib.Abort, ConnectionError, TimeoutError, OSError) as e:
                consecutive_errors += 1
                logger.warning(f"IMAP connection error: {e}. Consecutive errors: {consecutive_errors}")
                if consecutive_errors > 5:
                    logger.error("Too many IMAP errors, stopping receiver.")
                    break
                # Сбрасываем соединение и переподключаемся
                try:
                    await self.imap.close()
                except Exception:
                    pass
                self.imap = None
                await asyncio.sleep(5)
            except Exception as e:
                logger.error(f"Unexpected error in IMAP loop: {e}", exc_info=True)
                await asyncio.sleep(10)

        if self.imap:
            try:
                await self.imap.logout()
            except Exception:
                pass
        logger.info("Email receiver stopped")

    async def stop(self):
        self._running = False

    async def _safe_store(self, msg_id: bytes, flags='\\Seen'):
        """Безопасная команда STORE с таймаутом."""
        try:
            await asyncio.wait_for(self.imap.store(msg_id, '+FLAGS', flags), timeout=10)
        except Exception:
            logger.debug(f"Could not store flags for {msg_id}")

    async def _process_incoming_email(self, msg_id: bytes):
        """Обрабатывает одно письмо."""
        # Получаем данные письма
        status, msg_data = await self.imap.fetch(msg_id, '(RFC822)')
        if not msg_data or not isinstance(msg_data, list) or len(msg_data) == 0:
            logger.warning(f"No data for msg {msg_id}")
            await self._safe_store(msg_id)
            return

        # Извлекаем байты письма
        raw_email = None
        first = msg_data[0]
        if isinstance(first, tuple) and len(first) >= 2:
            raw_email = first[1]
        elif isinstance(first, bytes):
            raw_email = first
        else:
            for part in msg_data:
                if isinstance(part, bytes):
                    raw_email = part
                    break
                if isinstance(part, tuple):
                    for p in part:
                        if isinstance(p, bytes) and len(p) > 100:
                            raw_email = p
                            break
                    if raw_email:
                        break

        if not isinstance(raw_email, bytes):
            logger.error(f"Could not extract raw email for msg {msg_id}")
            await self._safe_store(msg_id)
            return

        try:
            msg = message_from_bytes(raw_email)
        except Exception as e:
            logger.error(f"Error parsing email {msg_id}: {e}")
            await self._safe_store(msg_id)
            return

        to_address = msg.get('To', '')
        match = re.search(r'reply\+(\d+)\+(\d+)@', to_address)
        if not match:
            # Не наш ответ
            await self._safe_store(msg_id)
            return

        user_id = int(match.group(1))
        chat_id = int(match.group(2))
        body = self._extract_reply_text(msg)

        async with get_db() as db:
            from database.models import User
            result = await db.execute(select(User).where(User.id == user_id))
            user = result.scalar_one_or_none()
            if not user or not await self._check_user_can_reply(user):
                await self._safe_store(msg_id)
                return

            success = await telegram_sender.send_message(
                user=user, chat_id=chat_id, text=body
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
                logger.info(f"Reply delivered: user={user_id}, chat={chat_id}")

        await self._safe_store(msg_id)

    async def _check_user_can_reply(self, user) -> bool:
        if user.is_banned or not user.is_active:
            return False
        if user.subscription_tier and str(user.subscription_tier) == 'free':
            if user.messages_today >= user.daily_limit:
                return False
        return True

    def _extract_reply_text(self, msg) -> str:
        """Извлечение текста ответа (без цитирования)."""
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == 'text/plain':
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
        return "[Empty message]"

    def _clean_reply_text(self, text: str) -> str:
        for sep in ['\n> ', '\n>', '\nOn ', '\n—', '\n---', '\n‐‐‐', 'From:',
                    '\n>On ', '\nSent from', '\nОтправлено из', '\nПользователь ']:
            if sep in text:
                text = text.split(sep)[0]
        return text.strip()


# Глобальный экземпляр
email_receiver = EmailReceiver()
