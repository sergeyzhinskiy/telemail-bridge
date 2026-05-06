# bot/main.py
import asyncio
import logging
import sys
from pathlib import Path

from aiogram import Bot, Dispatcher, executor
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.contrib.fsm_storage.redis import RedisStorage2
from aiogram.types import BotCommand

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.config import settings
from core.db import init_db, close_db
from core.telethon_manager import TelethonSessionManager
from core.email_receiver import email_receiver

from bot.handlers.registration import register_handlers as register_registration
from bot.handlers.settings import register_handlers as register_settings
from bot.handlers.payments import register_handlers as register_payments, init as init_payments
from bot.middlewares.subscription import SubscriptionMiddleware
from bot.middlewares.logging import LoggingMiddleware
from bot.middlewares.banned_user import BannedUserMiddleware

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL, logging.INFO),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('logs/bot.log')
    ]
)

logger = logging.getLogger(__name__)

bot = None
dp = None


async def on_startup(dp: Dispatcher):
    logger.info("=" * 50)
    logger.info("TeleMail Bridge запускается...")
    logger.info("=" * 50)

    await init_db()
    logger.info("✓ База данных инициализирована")

    await bot.set_my_commands([
        BotCommand("start", "Регистрация / перезапуск"),
        BotCommand("status", "Статус подключения"),
        BotCommand("contacts", "Мои контакты"),
        BotCommand("upgrade", "Сменить тариф"),
        BotCommand("settings", "Настройки"),
        BotCommand("help", "Помощь"),
    ])
    logger.info("✓ Команды бота установлены")

    await start_active_listeners()

    asyncio.create_task(email_receiver.start())
    logger.info("✓ Email-приёмник запущен")

    logger.info("=" * 50)
    logger.info("TeleMail Bridge готов к работе!")
    logger.info("=" * 50)


async def on_shutdown(dp: Dispatcher):
    logger.info("TeleMail Bridge останавливается...")

    await stop_all_listeners()
    logger.info("✓ Слушатели остановлены")

    await email_receiver.stop()
    logger.info("✓ Email-приёмник остановлен")

    await close_db()
    logger.info("✓ База данных закрыта")

    logger.info("TeleMail Bridge остановлен.")


async def start_active_listeners():
    from core.db import get_db

    try:
        async with get_db() as db:
            from database.models import User
            from sqlalchemy import select, and_

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
            active_users = result.scalars().all()

            logger.info(f"Запуск слушателей для {len(active_users)} активных пользователей...")

            success_count = 0
            for user in active_users:
                try:
                    await TelethonSessionManager.start_listener(user)
                    success_count += 1
                except Exception as e:
                    logger.error(f"Не удалось запустить слушатель для user_id={user.id}: {e}")

            logger.info(f"Слушатели запущены: {success_count}/{len(active_users)} успешно")
    except Exception as e:
        logger.error(f"Ошибка запуска слушателей: {e}", exc_info=True)


async def stop_all_listeners():
    for user_id in list(TelethonSessionManager._listeners.keys()):
        try:
            await TelethonSessionManager.stop_listener(user_id)
        except Exception as e:
            logger.error(f"Ошибка остановки слушателя user_id={user_id}: {e}")


def main():
    global bot, dp

    if settings.REDIS_URL:
        try:
            storage = RedisStorage2(
                host=settings.REDIS_HOST,
                port=settings.REDIS_PORT,
                password=settings.REDIS_PASSWORD,
                db=settings.REDIS_DB_FSM
            )
            logger.info("Используется Redis для хранения состояний")
        except Exception:
            storage = MemoryStorage()
            logger.warning("Redis недоступен, используется память для состояний")
    else:
        storage = MemoryStorage()
        logger.info("Используется память для хранения состояний")

    bot = Bot(token=settings.BOT_TOKEN, parse_mode='HTML')
    dp = Dispatcher(bot, storage=storage)

    init_payments(bot, dp)

    dp.middleware.setup(LoggingMiddleware())
    dp.middleware.setup(SubscriptionMiddleware())
    dp.middleware.setup(BannedUserMiddleware())

    register_registration(dp)
    register_settings(dp)
    register_payments(dp)

    executor.start_polling(
        dp,
        on_startup=on_startup,
        on_shutdown=on_shutdown,
        skip_updates=True
    )


if __name__ == '__main__':
    Path('logs').mkdir(exist_ok=True)
    Path('sessions').mkdir(exist_ok=True)
    Path('media').mkdir(exist_ok=True)

    main()