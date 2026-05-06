# payments/billing.py
from yookassa import Configuration, Payment as YooPayment
import stripe

class BillingService:
    def __init__(self):
        # ЮKassa (РФ)
        Configuration.account_id = config.YOOKASSA_SHOP_ID
        Configuration.secret_key = config.YOOKASSA_SECRET_KEY
        
        # Stripe (международные)
        stripe.api_key = config.STRIPE_SECRET_KEY
    
    PRICING = {
        "pro": {
            "monthly": {"RUB": 29900, "USD": 399},  # в копейках/центах
            "yearly": {"RUB": 299000, "USD": 3999}
        },
        "business": {
            "monthly": {"RUB": 99900, "USD": 1199},
            "yearly": {"RUB": 999000, "USD": 11999}
        }
    }
    
    async def create_payment(self, user, tier, period, provider):
        amount = self.PRICING[tier][period][user.currency]
        
        if provider == "yookassa":
            return await self._create_yookassa_payment(user, amount, tier, period)
        elif provider == "stripe":
            return await self._create_stripe_payment(user, amount, tier, period)
        elif provider == "telegram_stars":
            return await self._create_stars_payment(user, amount, tier)
    
    async def _create_yookassa_payment(self, user, amount, tier, period):
        payment = YooPayment.create({
            "amount": {
                "value": f"{amount/100:.2f}",
                "currency": "RUB"
            },
            "confirmation": {
                "type": "redirect",
                "return_url": f"https://telemail.app/payment/success"
            },
            "description": f"TeleMail {tier.upper()} - {period}"
        })
        
        # Сохраняем в БД
        await save_payment(user.id, amount, "yookassa", payment.id)
        return payment.confirmation.confirmation_url
    
    async def check_subscription(self, user):
        """Проверка при каждом действии пользователя"""
        if user.subscription_tier == SubscriptionTier.FREE:
            if user.messages_today >= user.daily_limit:
                raise DailyLimitExceeded()
        elif user.subscription_expires_at and user.subscription_expires_at < datetime.now():
            user.subscription_tier = SubscriptionTier.FREE
            await save_user(user)
    
    async def activate_subscription(self, payment_id, user_id):
        """Активация после успешного платежа"""
        payment = await get_payment(payment_id)
        if payment.status == "completed":
            user = await get_user_by_id(user_id)
            user.subscription_tier = payment.tier
            user.subscription_expires_at = datetime.now() + timedelta(days=30)
            await save_user(user)