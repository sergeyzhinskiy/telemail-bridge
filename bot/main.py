# bot/main.py
import asyncio
import logging
import sys
from pathlib import Path

from aiogram import Bot, Dispatcher, executor
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.contrib.fsm_storage.redis import RedisStorage2
from aiogram.types import BotCommand
from aiohttp import ClientSession, TCPConnector

from aiohttp import ClientSession  # для создания сессии с прокси

try:
    from aiohttp_socks import ProxyConnector
    SOCKS_AVAILABLE = True
except ImportError:
    SOCKS_AVAILABLE = False

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

# Настройка логирования
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL, logging.INFO),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('logs/bot.log', encoding='utf-8')
    ]
)

logger = logging.getLogger(__name__)

# Параметры прокси
PROXY_HOST = "149.62.186.244"
PROXY_PORT = 1080
PROXY_URL = f"socks5://{PROXY_HOST}:{PROXY_PORT}"

# Глобальные переменные
bot = None
dp = None
bot_session = None          # для закрытия сессии при остановке


async def on_startup(dp: Dispatcher):
    logger.info("=" * 50)
    logger.info("TeleMail Bridge starting...")
    logger.info("=" * 50)

    await init_db()
    logger.info("[OK] Database initialized")

    await bot.set_my_commands([
        BotCommand("start", "Registration / Restart"),
        BotCommand("status", "Connection status"),
        BotCommand("contacts", "My contacts"),
        BotCommand("upgrade", "Change tariff"),
        BotCommand("settings", "Settings"),
        BotCommand("help", "Help"),
    ])
    logger.info("[OK] Bot commands set")

    await start_active_listeners()

    asyncio.create_task(email_receiver.start())
    logger.info("[OK] Email receiver launched")

    logger.info("=" * 50)
    logger.info("TeleMail Bridge is ready!")
    logger.info("=" * 50)


async def on_shutdown(dp: Dispatcher):
    logger.info("TeleMail Bridge stopping...")

    await stop_all_listeners()
    logger.info("[OK] Listeners stopped")

    await email_receiver.stop()
    logger.info("[OK] Email receiver stopped")

    await close_db()
    logger.info("[OK] Database closed")

    # Закрываем сессию aiohttp, если она была создана
    global bot_session
    if bot_session and not bot_session.closed:
        await bot_session.close()
        logger.info("[OK] HTTP session closed")

    logger.info("TeleMail Bridge stopped.")


async def start_active_listeners():
    from core.db import get_active_authorized_users
    try:
        active_users = await get_active_authorized_users()
        logger.info(f"Starting listeners for {len(active_users)} active users...")

        success_count = 0
        for user in active_users:
            try:
                await TelethonSessionManager.start_listener(user)
                success_count += 1
            except Exception as e:
                logger.error(f"Failed to start listener for user_id={user.id}: {e}")

        logger.info(f"Listeners started: {success_count}/{len(active_users)}")
    except Exception as e:
        logger.error(f"Error starting listeners: {e}", exc_info=True)


async def stop_all_listeners():
    for user_id in list(TelethonSessionManager._listeners.keys()):
        try:
            await TelethonSessionManager.stop_listener(user_id)
        except Exception as e:
            logger.error(f"Error stopping listener user_id={user_id}: {e}")


async def init_bot_and_dispatcher():
    """Асинхронная инициализация бота и диспетчера (вызывается внутри event loop)."""
    global bot, dp, bot_session

    # Хранилище состояний
    if settings.REDIS_URL:
        try:
            storage = RedisStorage2(
                host=settings.REDIS_HOST,
                port=settings.REDIS_PORT,
                password=settings.REDIS_PASSWORD,
                db=settings.REDIS_DB_FSM
            )
            logger.info("Using Redis for FSM storage")
        except Exception:
            storage = MemoryStorage()
            logger.warning("Redis unavailable, using memory storage")
    else:
        storage = MemoryStorage()
        logger.info("Using memory storage")

    # Создаём бота с SOCKS5-прокси (через сессию aiohttp)
    if SOCKS_AVAILABLE:
        logger.info(f"Using SOCKS5 proxy {PROXY_URL} for Telegram API")
        loop = asyncio.get_event_loop()
        connector = ProxyConnector.from_url(PROXY_URL)
        session = ClientSession(connector=connector, loop=loop)
        #bot_session = ClientSession(connector=connector)
        bot = Bot(token=settings.BOT_TOKEN, parse_mode='HTML')#, session=bot_session)
        bot._session = session
    else:
        logger.warning("aiohttp-socks not installed, running without proxy")
        bot = Bot(token=settings.BOT_TOKEN, parse_mode='HTML')

    dp = Dispatcher(bot, storage=storage)
    init_payments(bot, dp)

    # Подключаем middleware
    dp.middleware.setup(LoggingMiddleware())
    dp.middleware.setup(SubscriptionMiddleware())
    dp.middleware.setup(BannedUserMiddleware())

    # Регистрируем обработчики
    register_registration(dp)
    register_settings(dp)
    register_payments(dp)

    return dp


def main():
    # Создаём новый event loop и устанавливаем его
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    # Инициализируем бота внутри event loop
    dp = loop.run_until_complete(init_bot_and_dispatcher())

    # Запускаем polling (aiogram 2.x)
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
