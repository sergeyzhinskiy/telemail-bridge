# core/db.py
import asyncio
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional, List, Tuple, Dict, Any
from datetime import datetime, date, timedelta

from sqlalchemy.ext.asyncio import (
    create_async_engine,
    AsyncSession,
    AsyncEngine,
    async_sessionmaker
)
from sqlalchemy import text, func, and_, or_, desc, asc, select, String, cast
from sqlalchemy.orm import selectinload

from core.config import settings
from database.models import (
    Base, User, ChatMapping, Payment, AdminAction, MessageLog,
    SubscriptionTier, PaymentStatus
)

# Глобальные объекты
_engine: Optional[AsyncEngine] = None
_session_factory: Optional[async_sessionmaker] = None
_initialized = False


async def _ensure_initialized():
    """Автоматическая инициализация движка и фабрики сессий при первом обращении."""
    global _engine, _session_factory, _initialized
    if _initialized:
        return
    if _engine is None:
        _engine = create_async_engine(
            settings.DATABASE_URL,
            pool_size=settings.DATABASE_POOL_SIZE,
            max_overflow=settings.DATABASE_MAX_OVERFLOW,
            echo=False,
            pool_pre_ping=True,
            pool_recycle=3600,
        )
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            _engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False
        )
    # Создаём таблицы, если их ещё нет
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    _initialized = True


async def init_db():
    """Явная инициализация (можно вызывать многократно)."""
    await _ensure_initialized()


async def close_db():
    """Закрытие соединений с БД."""
    global _engine, _session_factory, _initialized
    if _engine:
        await _engine.dispose()
        _engine = None
        _session_factory = None
        _initialized = False


@asynccontextmanager
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Контекстный менеджер для получения асинхронной сессии."""
    await _ensure_initialized()
    async with _session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


# ======================== ПОЛЬЗОВАТЕЛИ ========================
async def get_user_by_telegram_id(telegram_user_id: int) -> Optional[User]:
    async with get_db() as db:
        result = await db.execute(
            select(User).where(User.telegram_user_id == telegram_user_id)
        )
        return result.scalar_one_or_none()


async def get_user(user_id: int) -> Optional[User]:
    async with get_db() as db:
        result = await db.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()


async def get_user_by_email(email: str) -> Optional[User]:
    async with get_db() as db:
        result = await db.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()


async def get_user_by_api_key(api_key: str) -> Optional[User]:
    async with get_db() as db:
        result = await db.execute(select(User).where(User.api_key == api_key))
        return result.scalar_one_or_none()


async def create_user(**kwargs) -> User:
    async with get_db() as db:
        user = User(**kwargs)
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user


async def save_user(user: User) -> User:
    async with get_db() as db:
        merged = await db.merge(user)
        await db.commit()
        await db.refresh(merged)
        return merged


async def soft_delete_user(user_id: int) -> None:
    async with get_db() as db:
        user = await get_user(user_id)
        if user:
            user.is_active = False
            user.is_deleted = True
            user.deleted_at = datetime.utcnow()
            await db.commit()


async def get_active_authorized_users() -> List[User]:
    async with get_db() as db:
        result = await db.execute(
            select(User).where(
                and_(
                    User.is_active == True,
                    User.is_banned == False,
                    User.is_deleted == False,
                    User.is_telegram_authorized == True,
                    User.telethon_session_string.isnot(None)
                )
            )
        )
        return result.scalars().all()


async def count_users() -> int:
    async with get_db() as db:
        result = await db.execute(
            select(func.count(User.id)).where(User.is_deleted == False)
        )
        return result.scalar() or 0


async def count_active_users(today: date) -> int:
    async with get_db() as db:
        result = await db.execute(
            select(func.count(User.id)).where(
                and_(
                    func.date(User.last_active_at) == today,
                    User.is_deleted == False
                )
            )
        )
        return result.scalar() or 0


async def count_new_users_since(since: date) -> int:
    async with get_db() as db:
        result = await db.execute(
            select(func.count(User.id)).where(
                and_(
                    User.created_at >= since,
                    User.is_deleted == False
                )
            )
        )
        return result.scalar() or 0


async def count_users_by_tier(tiers: list) -> int:
    async with get_db() as db:
        result = await db.execute(
            select(func.count(User.id)).where(
                and_(
                    User.subscription_tier.in_(tiers),
                    User.is_deleted == False
                )
            )
        )
        return result.scalar() or 0


async def count_banned_users() -> int:
    async with get_db() as db:
        result = await db.execute(
            select(func.count(User.id)).where(User.is_banned == True)
        )
        return result.scalar() or 0


async def get_users_paginated(
    page: int = 1,
    per_page: int = 50,
    search: str = "",
    tier: Optional[str] = None,
    status: Optional[str] = None,
    sort_by: str = "created_at",
    sort_order: str = "desc"
) -> Tuple[List[User], int]:
    async with get_db() as db:
        query = select(User).where(User.is_deleted == False)

        conditions = []
        if search:
            search_term = f"%{search}%"
            conditions.append(
                or_(
                    User.email.ilike(search_term),
                    cast(User.telegram_user_id, String).ilike(search_term),
                    User.phone_number.ilike(search_term)
                )
            )
        if tier:
            conditions.append(User.subscription_tier == tier)
        if status == 'active':
            conditions.append(User.is_active == True)
            conditions.append(User.is_banned == False)
        elif status == 'banned':
            conditions.append(User.is_banned == True)
        elif status == 'inactive':
            conditions.append(User.is_active == False)

        if conditions:
            query = query.where(and_(*conditions))

        # Подсчёт
        count_query = select(func.count()).select_from(query.subquery())
        total_result = await db.execute(count_query)
        total = total_result.scalar() or 0

        # Сортировка
        sort_column = getattr(User, sort_by, User.created_at)
        if sort_order == 'asc':
            query = query.order_by(asc(sort_column))
        else:
            query = query.order_by(desc(sort_column))

        offset = (page - 1) * per_page
        query = query.offset(offset).limit(per_page)

        result = await db.execute(query)
        users = result.scalars().all()
        return users, total


async def get_expired_premium_users() -> List[User]:
    async with get_db() as db:
        result = await db.execute(
            select(User).where(
                and_(
                    User.subscription_tier.in_([SubscriptionTier.PRO, SubscriptionTier.BUSINESS]),
                    User.subscription_expires_at < datetime.utcnow()
                )
            )
        )
        return result.scalars().all()


async def get_all_users_for_export() -> List[User]:
    async with get_db() as db:
        result = await db.execute(
            select(User).where(User.is_deleted == False).order_by(User.id)
        )
        return result.scalars().all()


async def get_daily_active_stats(days: int = 30) -> List[Dict]:
    async with get_db() as db:
        result = await db.execute(
            text("""
                SELECT 
                    DATE(last_active_at) as day,
                    COUNT(*) as count
                FROM users
                WHERE last_active_at >= CURRENT_DATE - :days
                GROUP BY DATE(last_active_at)
                ORDER BY day
            """),
            {"days": days}
        )
        return [
            {"day": str(row[0]), "count": row[1]}
            for row in result.fetchall()
        ]


# ======================== ЧАТЫ ========================
async def get_chat_mapping(user_id: int, telegram_chat_id: int) -> Optional[ChatMapping]:
    async with get_db() as db:
        result = await db.execute(
            select(ChatMapping).where(
                and_(
                    ChatMapping.user_id == user_id,
                    ChatMapping.telegram_chat_id == telegram_chat_id
                )
            )
        )
        return result.scalar_one_or_none()


async def get_chat_mapping_by_id(mapping_id: int) -> Optional[ChatMapping]:
    async with get_db() as db:
        result = await db.execute(
            select(ChatMapping).where(ChatMapping.id == mapping_id)
        )
        return result.scalar_one_or_none()


async def get_active_chat_mappings(user_id: int) -> List[ChatMapping]:
    async with get_db() as db:
        result = await db.execute(
            select(ChatMapping)
            .where(
                and_(
                    ChatMapping.user_id == user_id,
                    ChatMapping.is_active == True
                )
            )
            .order_by(desc(ChatMapping.last_message_at))
        )
        return result.scalars().all()


async def create_chat_mapping(**kwargs) -> ChatMapping:
    async with get_db() as db:
        mapping = ChatMapping(**kwargs)
        db.add(mapping)
        await db.commit()
        await db.refresh(mapping)
        return mapping


async def get_user_chat_mappings(user_id: int) -> List[ChatMapping]:
    async with get_db() as db:
        result = await db.execute(
            select(ChatMapping)
            .where(ChatMapping.user_id == user_id)
            .order_by(desc(ChatMapping.last_message_at))
        )
        return result.scalars().all()


# ======================== ПЛАТЕЖИ ========================
async def get_payment(payment_id: int) -> Optional[Payment]:
    async with get_db() as db:
        result = await db.execute(
            select(Payment).where(Payment.id == payment_id)
        )
        return result.scalar_one_or_none()


async def get_payment_by_provider_id(provider_payment_id: str) -> Optional[Payment]:
    async with get_db() as db:
        result = await db.execute(
            select(Payment).where(Payment.provider_payment_id == provider_payment_id)
        )
        return result.scalar_one_or_none()


async def get_user_payments(user_id: int) -> List[Payment]:
    async with get_db() as db:
        result = await db.execute(
            select(Payment)
            .where(Payment.user_id == user_id)
            .order_by(desc(Payment.created_at))
        )
        return result.scalars().all()


async def create_payment(**kwargs) -> Payment:
    async with get_db() as db:
        payment = Payment(**kwargs)
        db.add(payment)
        await db.commit()
        await db.refresh(payment)
        return payment


async def save_payment(payment: Payment) -> Payment:
    async with get_db() as db:
        merged = await db.merge(payment)
        await db.commit()
        await db.refresh(merged)
        return merged


async def sum_revenue_current_month() -> float:
    async with get_db() as db:
        result = await db.execute(
            text("""
                SELECT COALESCE(SUM(amount), 0)
                FROM payments
                WHERE status = 'COMPLETED'
                AND DATE_TRUNC('month', completed_at) = DATE_TRUNC('month', NOW())
            """)
        )
        return float(result.scalar() or 0)


async def sum_revenue_total() -> float:
    async with get_db() as db:
        result = await db.execute(
            text("""
                SELECT COALESCE(SUM(amount), 0)
                FROM payments
                WHERE status = 'COMPLETED'
            """)
        )
        return float(result.scalar() or 0)


async def count_pending_payments() -> int:
    async with get_db() as db:
        result = await db.execute(
            select(func.count(Payment.id)).where(Payment.status == PaymentStatus.PENDING)
        )
        return result.scalar() or 0


# ======================== СООБЩЕНИЯ ========================
async def log_message(**kwargs) -> MessageLog:
    async with get_db() as db:
        log_entry = MessageLog(**kwargs)
        db.add(log_entry)
        await db.commit()
        await db.refresh(log_entry)
        return log_entry


async def get_user_messages(user_id: int, limit: int = 100) -> List[MessageLog]:
    async with get_db() as db:
        result = await db.execute(
            select(MessageLog)
            .where(MessageLog.user_id == user_id)
            .order_by(desc(MessageLog.created_at))
            .limit(limit)
        )
        return result.scalars().all()


async def count_messages_today() -> int:
    async with get_db() as db:
        result = await db.execute(
            select(func.count(MessageLog.id)).where(
                func.date(MessageLog.created_at) == date.today()
            )
        )
        return result.scalar() or 0


async def count_messages_since(since: date) -> int:
    async with get_db() as db:
        result = await db.execute(
            select(func.count(MessageLog.id)).where(
                MessageLog.created_at >= since
            )
        )
        return result.scalar() or 0


async def calculate_delivery_rate(since: date) -> float:
    async with get_db() as db:
        total_result = await db.execute(
            select(func.count(MessageLog.id)).where(
                MessageLog.created_at >= since
            )
        )
        total = total_result.scalar() or 0

        if total == 0:
            return 100.0

        delivered_result = await db.execute(
            select(func.count(MessageLog.id)).where(
                and_(
                    MessageLog.created_at >= since,
                    MessageLog.status == 'delivered'
                )
            )
        )
        delivered = delivered_result.scalar() or 0
        return (delivered / total) * 100


# ======================== ДЕЙСТВИЯ АДМИНИСТРАТОРОВ ========================
async def log_admin_action(**kwargs) -> AdminAction:
    async with get_db() as db:
        action = AdminAction(**kwargs)
        db.add(action)
        await db.commit()
        await db.refresh(action)
        return action


async def get_admin_actions_for_user(user_id: int) -> List[AdminAction]:
    async with get_db() as db:
        result = await db.execute(
            select(AdminAction)
            .where(AdminAction.target_user_id == user_id)
            .order_by(desc(AdminAction.created_at))
            .limit(50)
        )
        return result.scalars().all()


async def verify_admin_password(user: User, password: str) -> bool:
    import bcrypt
    return bcrypt.checkpw(
        password.encode('utf-8'),
        user.admin_password_hash.encode('utf-8')
    )


async def execute(sql: str, params: dict = None) -> Any:
    async with get_db() as db:
        result = await db.execute(text(sql), params or {})
        return result
