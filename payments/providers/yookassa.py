# payments/providers/yookassa.py
"""
Провайдер платежей ЮKassa.

Документация: https://yookassa.ru/developers/api
"""

import logging
from typing import Optional, Dict, Any
from datetime import datetime

from yookassa import Configuration, Payment, Refund
from yookassa.domain.exceptions import ApiError

from core.config import settings
from core.db import get_db, get_payment_by_provider_id, create_payment, create_payment as save_payment
from database.models import Payment as PaymentModel, PaymentStatus, PaymentProvider, SubscriptionTier

logger = logging.getLogger(__name__)


class YookassaProvider:
    """
    Интеграция с ЮKassa для приёма платежей из РФ.
    
    Поддерживаемые методы оплаты:
    - Банковские карты (Мир, Visa, Mastercard)
    - СБП (Система быстрых платежей)
    - ЮMoney (бывшие Яндекс.Деньги)
    - SberPay
    - Qiwi
    """
    
    PRICING = {
        'pro_monthly': {'amount': '299.00', 'currency': 'RUB', 'description': 'TeleMail Pro — Месяц'},
        'pro_yearly': {'amount': '2990.00', 'currency': 'RUB', 'description': 'TeleMail Pro — Год'},
        'business_monthly': {'amount': '999.00', 'currency': 'RUB', 'description': 'TeleMail Business — Месяц'},
        'business_yearly': {'amount': '9990.00', 'currency': 'RUB', 'description': 'TeleMail Business — Год'},
    }
    
    def __init__(self):
        if not settings.YOOKASSA_SHOP_ID or not settings.YOOKASSA_SECRET_KEY:
            logger.warning("ЮKassa не настроена. Платежи через ЮKassa недоступны.")
            self.enabled = False
        else:
            Configuration.configure(settings.YOOKASSA_SHOP_ID, settings.YOOKASSA_SECRET_KEY)
            self.enabled = True
            logger.info("ЮKassa инициализирована")
    
    async def create_payment(
        self,
        user_id: int,
        plan: str,
        return_url: str = None
    ) -> Optional[Dict[str, Any]]:
        """
        Создание платежа в ЮKassa.
        
        Args:
            user_id: ID пользователя
            plan: План оплаты (pro_monthly, pro_yearly, business_monthly, business_yearly)
            return_url: URL для возврата после оплаты
        
        Returns:
            Словарь с данными платежа или None при ошибке
        """
        if not self.enabled:
            logger.error("Попытка создать платёж ЮKassa, но провайдер не настроен")
            return None
        
        if plan not in self.PRICING:
            logger.error(f"Неизвестный план: {plan}")
            return None
        
        pricing = self.PRICING[plan]
        
        try:
            payment = Payment.create({
                "amount": {
                    "value": pricing['amount'],
                    "currency": pricing['currency']
                },
                "confirmation": {
                    "type": "redirect",
                    "return_url": return_url or f"{settings.BASE_URL}/payment/success"
                },
                "capture": True,
                "description": pricing['description'],
                "metadata": {
                    "user_id": str(user_id),
                    "plan": plan
                }
            })
            
            # Сохраняем платёж в БД
            async with get_db() as db:
                tier = SubscriptionTier.PRO if 'pro' in plan else SubscriptionTier.BUSINESS
                period = 'yearly' if 'yearly' in plan else 'monthly'
                
                db_payment = PaymentModel(
                    user_id=user_id,
                    amount=float(pricing['amount']),
                    currency=pricing['currency'],
                    tier=tier,
                    period=period,
                    provider=PaymentProvider.YOOKASSA,
                    provider_payment_id=payment.id,
                    status=PaymentStatus.PENDING
                )
                db.add(db_payment)
                await db.commit()
            
            logger.info(f"Платёж ЮKassa создан: {payment.id} для user_id={user_id}")
            
            return {
                'payment_id': payment.id,
                'confirmation_url': payment.confirmation.confirmation_url,
                'status': payment.status
            }
            
        except ApiError as e:
            logger.error(f"Ошибка создания платежа ЮKassa: {e}")
            return None
    
    async def check_payment_status(self, payment_id: str) -> Dict[str, Any]:
        """
        Проверка статуса платежа.
        
        Args:
            payment_id: ID платежа в ЮKassa
        
        Returns:
            Словарь со статусом платежа
        """
        if not self.enabled:
            return {'status': 'unknown', 'error': 'Provider not configured'}
        
        try:
            payment = Payment.find_one(payment_id)
            
            # Обновляем статус в БД
            async with get_db() as db:
                db_payment = await get_payment_by_provider_id(payment_id)
                if db_payment:
                    if payment.status == 'succeeded':
                        db_payment.status = PaymentStatus.COMPLETED
                        db_payment.completed_at = datetime.utcnow()
                        
                        # Активируем подписку
                        user = await db.get_user(db_payment.user_id)
                        if user:
                            user.subscription_tier = db_payment.tier
                            from datetime import timedelta
                            days = 365 if db_payment.period == 'yearly' else 30
                            user.subscription_expires_at = datetime.utcnow() + timedelta(days=days)
                            await db.commit()
                            logger.info(f"Подписка активирована для user_id={user.id}: {db_payment.tier.value}")
                    
                    elif payment.status == 'canceled':
                        db_payment.status = PaymentStatus.FAILED
                        await db.commit()
            
            return {
                'status': payment.status,
                'paid': payment.paid,
                'amount': payment.amount.value
            }
            
        except ApiError as e:
            logger.error(f"Ошибка проверки платежа ЮKassa: {e}")
            return {'status': 'unknown', 'error': str(e)}
    
    async def refund_payment(self, payment_id: str, amount: float = None) -> Dict[str, Any]:
        """
        Возврат платежа.
        
        Args:
            payment_id: ID платежа в ЮKassa
            amount: Сумма возврата (None = полный возврат)
        
        Returns:
            Словарь с результатом возврата
        """
        if not self.enabled:
            return {'status': 'error', 'error': 'Provider not configured'}
        
        try:
            refund_params = {
                "payment_id": payment_id
            }
            
            if amount:
                refund_params["amount"] = {
                    "value": f"{amount:.2f}",
                    "currency": "RUB"
                }
            
            refund = Refund.create(refund_params)
            
            # Обновляем статус в БД
            async with get_db() as db:
                db_payment = await get_payment_by_provider_id(payment_id)
                if db_payment:
                    db_payment.status = PaymentStatus.REFUNDED
                    db_payment.refunded_at = datetime.utcnow()
                    await db.commit()
            
            logger.info(f"Возврат выполнен: payment_id={payment_id}, refund_id={refund.id}")
            
            return {
                'refund_id': refund.id,
                'status': refund.status,
                'amount': refund.amount.value
            }
            
        except ApiError as e:
            logger.error(f"Ошибка возврата ЮKassa: {e}")
            return {'status': 'error', 'error': str(e)}
    
    @staticmethod
    def get_payment_methods() -> list:
        """Получить доступные методы оплаты"""
        return [
            {'id': 'bank_card', 'name': 'Банковская карта', 'icon': '💳'},
            {'id': 'sbp', 'name': 'СБП', 'icon': '⚡'},
            {'id': 'yoo_money', 'name': 'ЮMoney', 'icon': '💰'},
            {'id': 'sberbank', 'name': 'SberPay', 'icon': '🏦'},
            {'id': 'qiwi', 'name': 'Qiwi', 'icon': '🟠'},
        ]