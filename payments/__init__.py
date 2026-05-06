# payments/__init__.py
"""
Платёжная система TeleMail Bridge.

Поддерживаемые провайдеры:
- ЮKassa (российские платежи)
- Telegram Stars (оплата через Telegram)
- Stripe (международные платежи)
"""

from .billing import BillingService

__all__ = ['BillingService']