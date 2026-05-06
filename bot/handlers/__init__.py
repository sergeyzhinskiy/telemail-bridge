# bot/handlers/__init__.py
from .registration import register_handlers as register_registration
from .settings import register_handlers as register_settings
from .payments import register_handlers as register_payments

__all__ = [
    'register_registration',
    'register_settings',
    'register_payments',
]