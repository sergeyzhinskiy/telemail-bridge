# database/models.py
from sqlalchemy import (
    Column, Integer, String, Boolean, DateTime, Float,
    Enum as SQLEnum, ForeignKey, Text, JSON, UniqueConstraint, Date
)
from sqlalchemy.orm import relationship
from sqlalchemy.ext.declarative import declarative_base
import enum
from datetime import datetime

Base = declarative_base()


class UserRole(str, enum.Enum):
    USER = "user"
    ADMIN = "admin"
    SUPERADMIN = "superadmin"


class SubscriptionTier(str, enum.Enum):
    FREE = "free"
    PRO = "pro"
    BUSINESS = "business"


class PaymentProvider(str, enum.Enum):
    YOOKASSA = "yookassa"
    STARS = "telegram_stars"
    STRIPE = "stripe"
    MANUAL = "manual"


class PaymentStatus(str, enum.Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    REFUNDED = "refunded"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    telegram_user_id = Column(Integer, unique=True, nullable=False, index=True)
    email = Column(String(255), nullable=False)
    email_password_encrypted = Column(String(500))
    smtp_host = Column(String(255), default="smtp.gmail.com")
    smtp_port = Column(Integer, default=587)
    imap_host = Column(String(255), default="imap.gmail.com")
    imap_port = Column(Integer, default=993)
    use_ssl = Column(Boolean, default=True)

    # Telegram-сессия
    telethon_session_string = Column(Text)  # зашифрованная строка сессии
    phone_number = Column(String(20))
    is_telegram_authorized = Column(Boolean, default=False)
    last_telegram_sync = Column(DateTime)

    # Статус
    role = Column(SQLEnum(UserRole), default=UserRole.USER)
    is_active = Column(Boolean, default=True)
    is_banned = Column(Boolean, default=False)
    ban_reason = Column(String(500))
    banned_by_admin_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    banned_at = Column(DateTime)
    is_deleted = Column(Boolean, default=False)
    deleted_at = Column(DateTime)
    deleted_by_admin_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    # Админские поля
    admin_password_hash = Column(String(255))
    api_key = Column(String(100), unique=True)

    # Монетизация
    subscription_tier = Column(SQLEnum(SubscriptionTier), default=SubscriptionTier.FREE)
    subscription_expires_at = Column(DateTime)
    messages_today = Column(Integer, default=0)
    messages_reset_at = Column(DateTime, default=datetime.utcnow)
    total_messages_sent = Column(Integer, default=0)
    daily_limit = Column(Integer, default=50)

    # Метаданные
    created_at = Column(DateTime, default=datetime.utcnow)
    last_active_at = Column(DateTime)
    registered_by_admin_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    utm_source = Column(String(255))
    notes = Column(Text)

    # Связи
    chat_mappings = relationship("ChatMapping", back_populates="user", cascade="all, delete-orphan")
    payments = relationship("Payment", back_populates="user", cascade="all, delete-orphan")
    admin_actions = relationship(
        "AdminAction",
        back_populates="admin",
        foreign_keys="AdminAction.admin_id"
    )
    message_log = relationship("MessageLog", back_populates="user", cascade="all, delete-orphan")


class ChatMapping(Base):
    __tablename__ = "chat_mappings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    telegram_chat_id = Column(Integer, nullable=False)
    correspondent_telegram_id = Column(Integer)
    correspondent_name = Column(String(255))
    correspondent_username = Column(String(255))
    correspondent_phone = Column(String(20))
    is_active = Column(Boolean, default=True)
    is_favorite = Column(Boolean, default=False)
    last_message_id = Column(Integer)
    last_message_text = Column(Text)
    last_message_at = Column(DateTime)
    email_thread_id = Column(String(500))
    messages_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="chat_mappings")

    __table_args__ = (
        UniqueConstraint('user_id', 'telegram_chat_id', name='uq_user_chat'),
    )


class Payment(Base):
    __tablename__ = "payments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    amount = Column(Float, nullable=False)
    currency = Column(String(3), default="RUB")
    tier = Column(SQLEnum(SubscriptionTier), nullable=False)
    period = Column(String(20), default="monthly")
    provider = Column(SQLEnum(PaymentProvider), nullable=False)
    provider_payment_id = Column(String(255), unique=True, nullable=False)
    status = Column(SQLEnum(PaymentStatus), default=PaymentStatus.PENDING)
    error_message = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime)
    refunded_at = Column(DateTime)
    refunded_by_admin_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    user = relationship("User", back_populates="payments")


class AdminAction(Base):
    __tablename__ = "admin_actions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    admin_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    action_type = Column(String(50), nullable=False)
    target_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    details = Column(JSON)
    ip_address = Column(String(45))
    created_at = Column(DateTime, default=datetime.utcnow)

    admin = relationship("User", back_populates="admin_actions", foreign_keys=[admin_id])


class MessageLog(Base):
    """Лог всех сообщений для статистики и отладки"""
    __tablename__ = "message_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    direction = Column(String(10), nullable=False)  # "incoming" или "outgoing"
    chat_mapping_id = Column(Integer, ForeignKey("chat_mappings.id"), nullable=True)
    message_type = Column(String(20), default="text")
    email_message_id = Column(String(500))
    telegram_message_id = Column(Integer)
    status = Column(String(20), default="delivered")
    error_message = Column(Text)
    size_bytes = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="message_log")


class RateLimit(Base):
    """Отслеживание рейт-лимитов"""
    __tablename__ = "rate_limits"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    date = Column(Date, nullable=False)
    messages_count = Column(Integer, default=0)
    last_message_at = Column(DateTime)

    __table_args__ = (
        UniqueConstraint('user_id', 'date', name='uq_user_date'),
    )


class EmailTemplate(Base):
    """Шаблоны писем"""
    __tablename__ = "email_templates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), unique=True, nullable=False)
    subject = Column(String(500), nullable=False)
    body_html = Column(Text, nullable=False)
    body_text = Column(Text, nullable=False)
    is_active = Column(Boolean, default=True)
    updated_by_admin_id = Column(Integer, ForeignKey("users.id"))
    updated_at = Column(DateTime, default=datetime.utcnow)