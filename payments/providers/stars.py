# payments/providers/stars.py
"""
Провайдер платежей Telegram Stars.

Документация: https://core.telegram.org/bots/payments
"""

import logging
from typing import Optional, Dict, Any
from datetime import datetime

from aiogram import Bot
from aiogram.types import LabeledPrice, PreCheckoutQuery, Message

from core.db import get_db, create_payment, get_payment_by_provider_id
from database.models import Payment as PaymentModel, PaymentStatus, PaymentProvider, SubscriptionTier

logger = logging.getLogger(__name__)


class StarsProvider:
    """
    Интеграция с Telegram Stars для оплаты через официальный механизм Telegram.
    
    Telegram Stars — внутренняя валюта Telegram, привязанная к TON.
    Позволяет пользователям оплачивать подписку прямо из интерфейса бота.
    """
    
    # Цены в Telegram Stars (XTR)
    PRICING = {
        'pro_monthly': {'stars': 299, 'description': 'TeleMail Pro — 1 месяц'},
        'pro_yearly': {'stars': 2490, 'description': 'TeleMail Pro — 1 год'},
        'business_monthly': {'stars': 999, 'description': 'TeleMail Business — 1 месяц'},
        'business_yearly': {'stars': 8490, 'description': 'TeleMail Business — 1 год'},
    }
    
    def __init__(self):
        self.enabled = True  # Telegram Stars всегда доступен
        logger.info("Telegram Stars инициализирован")
    
    async def create_invoice(
        self,
        bot: Bot,
        user_id: int,
        plan: str
    ) -> Optional[Dict[str, Any]]:
        """
        Создание инвойса для оплаты через Telegram Stars.
        
        Args:
            bot: Экземпляр Aiogram Bot
            user_id: ID пользователя
            plan: План оплаты
        
        Returns:
            Результат создания инвойса
        """
        if plan not in self.PRICING:
            logger.error(f"Неизвестный план для Stars: {plan}")
            return None
        
        pricing = self.PRICING[plan]
        
        try:
            # Отправляем инвойс пользователю
            await bot.send_invoice(
                chat_id=user_id,
                title='TeleMail Bridge',
                description=pricing['description'],
                payload=f"stars_{plan}_{user_id}_{int(datetime.utcnow().timestamp())}",
                provider_token="",  # Пустой для Telegram Stars
                currency="XTR",     # Код валюты Telegram Stars
                prices=[
                    LabeledPrice(
                        label=pricing['description'],
                        amount=pricing['stars']
                    )
                ],
                photo_url="https://telemail.app/assets/logo.png",
                photo_width=512,
                photo_height=512,
                need_name=False,
                need_phone_number=False,
                need_email=False,
                is_flexible=False,
                protect_content=False
            )
            
            logger.info(f"Инвойс Stars создан для user_id={user_id}, план={plan}")
            
            return {
                'status': 'invoice_sent',
                'plan': plan
            }
            
        except Exception as e:
            logger.error(f"Ошибка создания инвойса Stars: {e}")
            return {'error': str(e)}
    
    async def handle_pre_checkout(self, pre_checkout: PreCheckoutQuery) -> bool:
        """
        Обработка предварительной проверки платежа.
        
        Args:
            pre_checkout: PreCheckoutQuery от Telegram
        
        Returns:
            True если платёж может быть обработан
        """
        try:
            payload = pre_checkout.invoice_payload
            
            # Проверяем payload
            if not payload.startswith('stars_'):
                logger.warning(f"Невалидный payload Stars: {payload}")
                return False
            
            parts = payload.split('_')
            plan = parts[1]
            user_id = int(parts[2])
            
            # Проверяем план
            if plan not in self.PRICING:
                logger.warning(f"Неизвестный план в Stars payload: {plan}")
                return False
            
            # Проверяем сумму
            expected_amount = self.PRICING[plan]['stars']
            if pre_checkout.total_amount != expected_amount:
                logger.warning(
                    f"Неверная сумма Stars: ожидалось {expected_amount}, "
                    f"получено {pre_checkout.total_amount}"
                )
                return False
            
            # Сохраняем платёж в БД
            async with get_db() as db:
                tier = SubscriptionTier.PRO if 'pro' in plan else SubscriptionTier.BUSINESS
                period = 'yearly' if 'yearly' in plan else 'monthly'
                
                db_payment = PaymentModel(
                    user_id=user_id,
                    amount=expected_amount,
                    currency='XTR',
                    tier=tier,
                    period=period,
                    provider=PaymentProvider.STARS,
                    provider_payment_id=pre_checkout.id,
                    status=PaymentStatus.PENDING
                )
                db.add(db_payment)
                await db.commit()
            
            logger.info(f"Pre-checkout Stars успешен: user_id={user_id}, plan={plan}")
            return True
            
        except Exception as e:
            logger.error(f"Ошибка pre-checkout Stars: {e}")
            return False
    
    async def handle_successful_payment(self, message: Message) -> Dict[str, Any]:
        """
        Обработка успешного платежа.
        
        Args:
            message: Сообщение с successful_payment от Telegram
        
        Returns:
            Результат обработки
        """
        try:
            payment_info = message.successful_payment
            payload = payment_info.invoice_payload
            
            parts = payload.split('_')
            plan = parts[1]
            user_id = int(parts[2])
            
            # Активируем подписку
            async with get_db() as db:
                user = await db.get_user(user_id)
                if user:
                    tier = SubscriptionTier.PRO if 'pro' in plan else SubscriptionTier.BUSINESS
                    user.subscription_tier = tier
                    
                    from datetime import timedelta
                    days = 365 if 'yearly' in plan else 30
                    user.subscription_expires_at = datetime.utcnow() + timedelta(days=days)
                    
                    # Обновляем статус платежа
                    db_payment = await get_payment_by_provider_id(payment_info.telegram_payment_charge_id)
                    if db_payment:
                        db_payment.status = PaymentStatus.COMPLETED
                        db_payment.completed_at = datetime.utcnow()
                    
                    await db.commit()
                    
                    logger.info(
                        f"Подписка активирована через Stars: "
                        f"user_id={user_id}, tier={tier.value}, до {user.subscription_expires_at}"
                    )
                    
                    return {
                        'status': 'success',
                        'user_id': user_id,
                        'tier': tier.value,
                        'expires_at': user.subscription_expires_at.isoformat()
                    }
            
            return {'status': 'error', 'error': 'User not found'}
            
        except Exception as e:
            logger.error(f"Ошибка обработки успешного платежа Stars: {e}")
            return {'status': 'error', 'error': str(e)}
    
    async def refund_payment(self, payment_id: str, user_id: int) -> Dict[str, Any]:
        """
        Возврат платежа Telegram Stars.
        
        Примечание: Telegram не предоставляет API для возврата Stars.
        Возврат нужно делать вручную через @BotFather или поддержку Telegram.
        
        Args:
            payment_id: ID платежа
            user_id: ID пользователя
        
        Returns:
            Результат операции
        """
        logger.warning(
            f"Возврат Stars требует ручной обработки: "
            f"payment_id={payment_id}, user_id={user_id}"
        )
        
        # Отмечаем в БД, что требуется возврат
        async with get_db() as db:
            db_payment = await get_payment_by_provider_id(payment_id)
            if db_payment:
                db_payment.status = PaymentStatus.REFUNDED
                db_payment.refunded_at = datetime.utcnow()
                await db.commit()
        
        return {
            'status': 'manual_required',
            'message': 'Возврат Telegram Stars требует ручной обработки через @BotFather',
            'payment_id': payment_id,
            'user_id': user_id
        }
    
    @staticmethod
    def get_pricing_info() -> Dict[str, Any]:
        """Получить информацию о ценах"""
        return StarsProvider.PRICING
    
    @staticmethod
    def get_currency_info() -> Dict[str, str]:
        """Получить информацию о валюте"""
        return {
            'code': 'XTR',
            'name': 'Telegram Stars',
            'symbol': '⭐',
            'description': 'Внутренняя валюта Telegram. 1 ⭐ ≈ 1 руб.'
        }