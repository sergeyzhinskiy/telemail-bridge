# payments/providers/stripe.py
"""
Провайдер платежей Stripe.

Документация: https://stripe.com/docs/api
"""

import logging
from typing import Optional, Dict, Any
from datetime import datetime

import stripe
from stripe.error import StripeError

from core.config import settings
from core.db import get_db, get_payment_by_provider_id
from database.models import Payment as PaymentModel, PaymentStatus, PaymentProvider, SubscriptionTier

logger = logging.getLogger(__name__)


class StripeProvider:
    """
    Интеграция со Stripe для международных платежей.
    
    Поддерживаемые методы оплаты:
    - Банковские карты (Visa, Mastercard, Amex)
    - Apple Pay / Google Pay
    - SEPA Direct Debit
    - и другие методы Stripe
    """
    
    PRICING = {
        'pro_monthly': {'amount': 399, 'currency': 'usd', 'description': 'TeleMail Pro - Monthly'},
        'pro_yearly': {'amount': 3999, 'currency': 'usd', 'description': 'TeleMail Pro - Yearly'},
        'business_monthly': {'amount': 1199, 'currency': 'usd', 'description': 'TeleMail Business - Monthly'},
        'business_yearly': {'amount': 11999, 'currency': 'usd', 'description': 'TeleMail Business - Yearly'},
    }
    
    def __init__(self):
        if not settings.STRIPE_SECRET_KEY:
            logger.warning("Stripe не настроен. Международные платежи недоступны.")
            self.enabled = False
        else:
            stripe.api_key = settings.STRIPE_SECRET_KEY
            stripe.api_version = '2023-10-16'
            self.enabled = True
            logger.info("Stripe инициализирован")
    
    async def create_checkout_session(
        self,
        user_id: int,
        plan: str,
        success_url: str = None,
        cancel_url: str = None
    ) -> Optional[Dict[str, Any]]:
        """
        Создание Checkout Session в Stripe.
        
        Args:
            user_id: ID пользователя
            plan: План оплаты
            success_url: URL после успешной оплаты
            cancel_url: URL при отмене
        
        Returns:
            Словарь с данными сессии или None при ошибке
        """
        if not self.enabled:
            logger.error("Попытка создать платёж Stripe, но провайдер не настроен")
            return None
        
        if plan not in self.PRICING:
            logger.error(f"Неизвестный план: {plan}")
            return None
        
        pricing = self.PRICING[plan]
        
        try:
            session = stripe.checkout.Session.create(
                payment_method_types=['card'],
                line_items=[{
                    'price_data': {
                        'currency': pricing['currency'],
                        'product_data': {
                            'name': pricing['description'],
                            'description': 'TeleMail Bridge - Email шлюз для Telegram',
                        },
                        'unit_amount': pricing['amount'],
                        'recurring': {
                            'interval': 'month' if 'monthly' in plan else 'year'
                        } if 'monthly' in plan or 'yearly' in plan else None,
                    },
                    'quantity': 1,
                }],
                mode='subscription' if 'monthly' in plan or 'yearly' in plan else 'payment',
                success_url=success_url or f"{settings.BASE_URL}/payment/success?session_id={{CHECKOUT_SESSION_ID}}",
                cancel_url=cancel_url or f"{settings.BASE_URL}/payment/cancel",
                metadata={
                    'user_id': str(user_id),
                    'plan': plan
                }
            )
            
            # Сохраняем в БД
            async with get_db() as db:
                tier = SubscriptionTier.PRO if 'pro' in plan else SubscriptionTier.BUSINESS
                period = 'yearly' if 'yearly' in plan else 'monthly'
                
                db_payment = PaymentModel(
                    user_id=user_id,
                    amount=pricing['amount'] / 100,  # Stripe использует центы
                    currency=pricing['currency'].upper(),
                    tier=tier,
                    period=period,
                    provider=PaymentProvider.STRIPE,
                    provider_payment_id=session.id,
                    status=PaymentStatus.PENDING
                )
                db.add(db_payment)
                await db.commit()
            
            logger.info(f"Stripe сессия создана: {session.id} для user_id={user_id}")
            
            return {
                'session_id': session.id,
                'url': session.url
            }
            
        except StripeError as e:
            logger.error(f"Ошибка создания Stripe сессии: {e}")
            return {'error': str(e)}
    
    async def check_session_status(self, session_id: str) -> Dict[str, Any]:
        """
        Проверка статуса Checkout Session.
        
        Args:
            session_id: ID сессии Stripe
        
        Returns:
            Словарь со статусом
        """
        if not self.enabled:
            return {'status': 'unknown', 'error': 'Provider not configured'}
        
        try:
            session = stripe.checkout.Session.retrieve(session_id)
            
            # Обновляем статус в БД
            async with get_db() as db:
                db_payment = await get_payment_by_provider_id(session_id)
                if db_payment:
                    if session.payment_status == 'paid':
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
                            logger.info(f"Подписка активирована через Stripe для user_id={user.id}")
                    
                    elif session.payment_status == 'unpaid':
                        db_payment.status = PaymentStatus.FAILED
                        await db.commit()
            
            return {
                'status': session.payment_status,
                'customer_email': session.customer_details.email if session.customer_details else None,
                'amount_total': session.amount_total
            }
            
        except StripeError as e:
            logger.error(f"Ошибка проверки Stripe сессии: {e}")
            return {'status': 'unknown', 'error': str(e)}
    
    async def refund_payment(self, payment_intent_id: str, amount: int = None) -> Dict[str, Any]:
        """
        Возврат платежа в Stripe.
        
        Args:
            payment_intent_id: ID Payment Intent
            amount: Сумма возврата в центах (None = полный возврат)
        
        Returns:
            Словарь с результатом
        """
        if not self.enabled:
            return {'status': 'error', 'error': 'Provider not configured'}
        
        try:
            refund_params = {
                'payment_intent': payment_intent_id
            }
            
            if amount:
                refund_params['amount'] = amount
            
            refund = stripe.Refund.create(**refund_params)
            
            logger.info(f"Stripe возврат: {refund.id} для {payment_intent_id}")
            
            return {
                'refund_id': refund.id,
                'status': refund.status,
                'amount': refund.amount
            }
            
        except StripeError as e:
            logger.error(f"Ошибка возврата Stripe: {e}")
            return {'status': 'error', 'error': str(e)}
    
    async def handle_webhook(self, payload: bytes, signature: str) -> Dict[str, Any]:
        """
        Обработка вебхука Stripe.
        
        Args:
            payload: Тело запроса
            signature: Подпись из заголовка Stripe-Signature
        
        Returns:
            Результат обработки
        """
        if not settings.STRIPE_WEBHOOK_SECRET:
            logger.error("Stripe webhook secret не настроен")
            return {'status': 'error', 'error': 'Webhook secret not configured'}
        
        try:
            event = stripe.Webhook.construct_event(
                payload, signature, settings.STRIPE_WEBHOOK_SECRET
            )
            
            event_type = event['type']
            
            if event_type == 'checkout.session.completed':
                session = event['data']['object']
                await self._handle_successful_payment(session)
            
            elif event_type == 'customer.subscription.deleted':
                subscription = event['data']['object']
                # Обработка отмены подписки
                logger.info(f"Подписка отменена: {subscription.id}")
            
            return {
                'status': 'processed',
                'event_type': event_type
            }
            
        except stripe.error.SignatureVerificationError as e:
            logger.error(f"Ошибка верификации подписи Stripe: {e}")
            return {'status': 'error', 'error': 'Invalid signature'}
        except Exception as e:
            logger.error(f"Ошибка обработки вебхука Stripe: {e}")
            return {'status': 'error', 'error': str(e)}
    
    async def _handle_successful_payment(self, session):
        """Обработка успешного платежа"""
        user_id = int(session['metadata']['user_id'])
        plan = session['metadata']['plan']
        
        logger.info(f"Успешный платёж Stripe: user_id={user_id}, plan={plan}")
        
        async with get_db() as db:
            user = await db.get_user(user_id)
            if user:
                tier = SubscriptionTier.PRO if 'pro' in plan else SubscriptionTier.BUSINESS
                user.subscription_tier = tier
                
                from datetime import timedelta
                days = 365 if 'yearly' in plan else 30
                user.subscription_expires_at = datetime.utcnow() + timedelta(days=days)
                
                await db.commit()
                logger.info(f"Подписка активирована через вебхук Stripe: user_id={user_id}, tier={tier.value}")