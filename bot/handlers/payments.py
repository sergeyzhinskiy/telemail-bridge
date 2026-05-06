# bot/handlers/payments.py
import logging
from datetime import datetime, timedelta

from aiogram import types, Dispatcher, Bot
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    LabeledPrice, PreCheckoutQuery, ContentType
)

from core.db import get_db
from database.models import User, SubscriptionTier, PaymentStatus

logger = logging.getLogger(__name__)

# Эти переменные будут установлены при инициализации бота
bot: Bot = None
dp: Dispatcher = None


def init(bot_instance: Bot, dispatcher: Dispatcher):
    """Инициализация модуля платежей"""
    global bot, dp
    bot = bot_instance
    dp = dispatcher


async def cmd_upgrade(message: types.Message):
    """Команда смены тарифа"""
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(
        InlineKeyboardButton("💎 Pro — 299₽/мес", callback_data="tier_pro_monthly"),
        InlineKeyboardButton("💎 Pro — 2990₽/год", callback_data="tier_pro_yearly"),
        InlineKeyboardButton("🏢 Business — 999₽/мес", callback_data="tier_business_monthly"),
        InlineKeyboardButton("🏢 Business — 9990₽/год", callback_data="tier_business_yearly"),
        InlineKeyboardButton("⭐ Оплатить через Telegram Stars", callback_data="pay_stars_pro_monthly"),
    )

    await message.answer(
        "💎 <b>Выберите тариф:</b>\n\n"
        "<b>Pro</b> — безлимитные сообщения, до 50 контактов\n"
        "<b>Business</b> — всё включено + кастомный домен\n\n"
        "Все цены указаны с НДС.",
        reply_markup=keyboard,
        parse_mode="HTML"
    )


async def process_tier_selection(callback: types.CallbackQuery):
    """Обработка выбора тарифа"""
    data = callback.data

    if data.startswith('pay_stars_'):
        plan = data.replace('pay_stars_', '')
        await pay_with_stars(callback, plan)
        return

    tier_map = {
        'tier_pro_monthly': ('pro', 'monthly', 29900, 'Pro — Месяц'),
        'tier_pro_yearly': ('pro', 'yearly', 299000, 'Pro — Год'),
        'tier_business_monthly': ('business', 'monthly', 99900, 'Business — Месяц'),
        'tier_business_yearly': ('business', 'yearly', 999000, 'Business — Год'),
    }

    if data not in tier_map:
        await callback.answer("Неизвестный тариф")
        return

    tier, period, amount_kopecks, description = tier_map[data]

    from payments.providers.yookassa import YookassaProvider
    yookassa = YookassaProvider()

    if yookassa.enabled:
        result = await yookassa.create_payment(
            user_id=callback.from_user.id,
            plan=f"{tier}_{period}"
        )
        if result:
            keyboard = InlineKeyboardMarkup()
            keyboard.add(InlineKeyboardButton("💳 Оплатить", url=result['confirmation_url']))
            await callback.message.edit_text(
                f"💎 <b>{description}</b>\n"
                f"Сумма: {amount_kopecks / 100:.2f} ₽\n\n"
                f"Нажмите кнопку для оплаты:",
                reply_markup=keyboard,
                parse_mode="HTML"
            )
            return

    await callback.answer("Платёжная система временно недоступна", show_alert=True)


async def pay_with_stars(callback: types.CallbackQuery, plan: str):
    """Оплата через Telegram Stars"""
    stars_map = {
        'pro_monthly': (299, 'TeleMail Pro — 1 месяц'),
        'pro_yearly': (2490, 'TeleMail Pro — 1 год'),
        'business_monthly': (999, 'TeleMail Business — 1 месяц'),
        'business_yearly': (8490, 'TeleMail Business — 1 год'),
    }

    if plan not in stars_map:
        await callback.answer("Неизвестный план")
        return

    amount, description = stars_map[plan]

    await bot.send_invoice(
        chat_id=callback.from_user.id,
        title='TeleMail Bridge',
        description=description,
        payload=f"stars_{plan}_{callback.from_user.id}_{int(datetime.utcnow().timestamp())}",
        provider_token="",
        currency="XTR",
        prices=[LabeledPrice(label=description, amount=amount)],
    )

    await callback.answer()


async def process_pre_checkout(pre_checkout: PreCheckoutQuery):
    """Обработка предварительной проверки платежа"""
    payload = pre_checkout.invoice_payload

    if not payload.startswith('stars_'):
        await bot.answer_pre_checkout_query(pre_checkout.id, ok=False, error_message="Ошибка платежа")
        return

    parts = payload.split('_')
    plan = parts[1]

    valid_plans = ['pro_monthly', 'pro_yearly', 'business_monthly', 'business_yearly']
    if plan not in valid_plans:
        await bot.answer_pre_checkout_query(pre_checkout.id, ok=False, error_message="Неизвестный план")
        return

    await bot.answer_pre_checkout_query(pre_checkout.id, ok=True)


async def process_successful_payment(message: types.Message):
    """Обработка успешного платежа"""
    payment_info = message.successful_payment
    payload = payment_info.invoice_payload

    parts = payload.split('_')
    plan = parts[1]
    user_id = int(parts[2])

    tier = SubscriptionTier.PRO if 'pro' in plan else SubscriptionTier.BUSINESS
    period = 'yearly' if 'yearly' in plan else 'monthly'
    days = 365 if period == 'yearly' else 30

    async with get_db() as db:
        result = await db.execute(
            select(User).where(User.id == user_id)
        )
        user = result.scalar_one_or_none()

        if user:
            user.subscription_tier = tier
            user.subscription_expires_at = datetime.utcnow() + timedelta(days=days)
            if tier == SubscriptionTier.PRO:
                user.daily_limit = 10000
            elif tier == SubscriptionTier.BUSINESS:
                user.daily_limit = 100000
            await db.commit()

    await message.answer(
        f"✅ <b>Подписка активирована!</b>\n\n"
        f"Тариф: {tier.value.upper()}\n"
        f"Действует до: {(datetime.utcnow() + timedelta(days=days)).strftime('%d.%m.%Y')}\n\n"
        f"Спасибо за покупку! 🎉",
        parse_mode="HTML"
    )


def register_handlers(dp: Dispatcher):
    """Регистрация обработчиков платежей"""
    from database.models import User
    from sqlalchemy import select

    dp.register_message_handler(cmd_upgrade, commands=['upgrade'])
    dp.register_callback_query_handler(process_tier_selection, lambda c: c.data.startswith('tier_'))
    dp.register_callback_query_handler(pay_with_stars, lambda c: c.data.startswith('pay_stars_'), state=None)
    dp.register_pre_checkout_query_handler(process_pre_checkout)
    dp.register_message_handler(process_successful_payment, content_types=ContentType.SUCCESSFUL_PAYMENT)