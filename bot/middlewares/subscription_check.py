# bot/middlewares/subscription_check.py
from aiogram import types
from aiogram.dispatcher.middlewares import BaseMiddleware

class SubscriptionMiddleware(BaseMiddleware):
    async def on_pre_process_message(self, message: types.Message, data: dict):
        user = await get_user(message.from_user.id)
        
        # Проверяем бан
        if user.is_banned:
            await message.answer(f"⛔ Ваш аккаунт заблокирован: {user.ban_reason}")
            raise CancelHandler()
        
        # Проверяем подписку
        if user.subscription_tier == SubscriptionTier.FREE:
            if user.messages_today >= user.daily_limit:
                await message.answer(
                    f"⚠️ Достигнут лимит ({user.daily_limit} сообщений/день). "
                    f"Повысьте тариф: /upgrade"
                )
                raise CancelHandler()
        
        # Увеличиваем счётчик
        user.messages_today += 1
        await save_user(user)