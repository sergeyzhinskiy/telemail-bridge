# bot/middlewares/banned_user.py
import logging
from aiogram import types
from aiogram.dispatcher.middlewares import BaseMiddleware
from aiogram.dispatcher.handler import CancelHandler
from core.db import get_user_by_telegram_id

logger = logging.getLogger(__name__)


class BannedUserMiddleware(BaseMiddleware):
    """
    Middleware для блокировки забаненных пользователей.
    Проверяет статус is_banned перед обработкой любого сообщения.
    """

    BANNED_MESSAGE = (
        "⛔ <b>Ваш аккаунт заблокирован.</b>\n\n"
        "Причина: {reason}\n\n"
        "Если вы считаете это ошибкой, свяжитесь с поддержкой:\n"
        "@telemail_support"
    )

    async def on_pre_process_message(self, message: types.Message, data: dict):
        """Проверка перед обработкой сообщения"""
        if not await self._check_user_banned(message.from_user.id):
            return

        user = await get_user_by_telegram_id(message.from_user.id)

        try:
            await message.answer(
                self.BANNED_MESSAGE.format(
                    reason=user.ban_reason or "Нарушение правил сервиса"
                ),
                parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"Не удалось отправить сообщение забаненному пользователю: {e}")

        raise CancelHandler()

    async def on_pre_process_callback_query(self, callback: types.CallbackQuery, data: dict):
        """Проверка перед обработкой callback"""
        if not await self._check_user_banned(callback.from_user.id):
            return

        user = await get_user_by_telegram_id(callback.from_user.id)

        try:
            await callback.answer(
                f"⛔ Аккаунт заблокирован: {user.ban_reason or 'Нарушение правил'}",
                show_alert=True
            )
        except Exception:
            pass

        raise CancelHandler()

    async def _check_user_banned(self, telegram_user_id: int) -> bool:
        """
        Проверяет, забанен ли пользователь.
        Возвращает True если забанен.
        """
        user = await get_user_by_telegram_id(telegram_user_id)

        if not user:
            return False  # Пользователь не зарегистрирован – пропускаем

        return user.is_banned
