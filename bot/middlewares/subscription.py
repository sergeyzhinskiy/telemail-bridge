# bot/middlewares/subscription.py
import logging
from datetime import datetime
from aiogram import types
from aiogram.dispatcher.middlewares import BaseMiddleware
from aiogram.dispatcher.handler import CancelHandler
from core.db import get_db, get_user_by_telegram_id

logger = logging.getLogger(__name__)


class SubscriptionMiddleware(BaseMiddleware):
    """
    Middleware для проверки подписки и дневного лимита сообщений.
    """

    async def on_pre_process_message(self, message: types.Message, data: dict):
        user_id = message.from_user.id

        # Получаем пользователя из БД
        user = await get_user_by_telegram_id(user_id)

        if not user:
            # Пользователь не зарегистрирован – пропускаем
            return

        # Проверка бана
        if user.is_banned:
            await message.answer(
                "⛔ Ваш аккаунт заблокирован.\n"
                f"Причина: {user.ban_reason or 'Нарушение правил'}\n\n"
                "Обратитесь в поддержку: @telemail_support"
            )
            raise CancelHandler()

        # Проверка лимита
        if user.subscription_tier and user.subscription_tier.value == "free" and user.messages_today >= user.daily_limit:
            await message.answer(
                f"⚠️ Достигнут дневной лимит ({user.daily_limit} сообщений).\n"
                "Повысьте тариф: /upgrade"
            )
            raise CancelHandler()

        # Увеличиваем счётчик
        async with get_db() as db:
            await db.execute(
                "UPDATE users SET messages_today = messages_today + 1, "
                "last_active_at = :now WHERE telegram_user_id = :uid",
                {"now": datetime.utcnow(), "uid": user_id}
            )
            await db.commit()
