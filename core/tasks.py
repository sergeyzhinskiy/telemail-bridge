# core/tasks.py
from celery import Celery
from celery.schedules import crontab

app = Celery('telemail', broker=settings.REDIS_URL)


@app.on_after_configure.connect
def setup_periodic_tasks(sender, **kwargs):
    """Периодические задачи"""
    # Сброс дневных счётчиков (каждую полночь по Москве)
    sender.add_periodic_task(
        crontab(hour=21, minute=0),  # 00:00 MSK = 21:00 UTC
        reset_daily_counters.s(),
        name="Сброс дневных счётчиков"
    )
    
    # Проверка истекающих подписок (каждый час)
    sender.add_periodic_task(
        crontab(minute=0),
        check_expired_subscriptions.s(),
        name="Проверка подписок"
    )
    
    # Сбор статистики (каждые 30 минут)
    sender.add_periodic_task(
        crontab(minute="*/30"),
        collect_hourly_stats.s(),
        name="Сбор статистики"
    )


@app.task
async def reset_daily_counters():
    """Сброс дневных счётчиков сообщений"""
    async with get_db() as db:
        await db.execute(
            "UPDATE users SET messages_today = 0, messages_reset_at = NOW()"
        )
        await db.commit()
    logger.info("Дневные счётчики сброшены")


@app.task
async def check_expired_subscriptions():
    """Проверка истекающих премиум-подписок"""
    async with get_db() as db:
        expired = await db.get_expired_premium_users()
        for user in expired:
            user.subscription_tier = SubscriptionTier.FREE
            user.daily_limit = 50
            logger.info(f"Подписка истекла: user_id={user.id}")
        await db.commit()


@app.task
async def send_email_async(user_id: int, email_data: dict):
    """Асинхронная отправка email (из очереди)"""
    async with get_db() as db:
        user = await db.get_user(user_id)
        if not user:
            return
    
    sender = EmailSender()
    await sender.send_telegram_message_to_email(user, email_data)