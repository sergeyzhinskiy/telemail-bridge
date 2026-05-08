# bot/handlers/registration.py
import re
import logging
import base64
from datetime import datetime

from aiogram import types, Dispatcher
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from sqlalchemy import select

from core.db import get_db
from database.models import User
from core.security import encrypt_data
from core.telethon_manager import TelethonSessionManager

logger = logging.getLogger(__name__)


class RegistrationStates(StatesGroup):
    waiting_email = State()
    waiting_email_password = State()
    waiting_smtp_host = State()
    waiting_smtp_port = State()
    waiting_imap_host = State()
    waiting_imap_port = State()
    waiting_phone_number = State()
    waiting_telegram_code = State()
    waiting_2fa_password = State()


async def cmd_start(message: types.Message, state: FSMContext):
    """Начало регистрации или перезапуск."""
    # Всегда сбрасываем предыдущее состояние, если пользователь хочет начать заново
    await state.finish()

    async with get_db() as db:
        result = await db.execute(
            select(User).where(User.telegram_user_id == message.from_user.id)
        )
        existing_user = result.scalar_one_or_none()

        if existing_user:
            await show_main_menu(message, existing_user)
            return

    await message.answer(
        "👋 Добро пожаловать в TeleMail Bridge!\n\n"
        "Я помогу вам оставаться на связи через Telegram, даже если он заблокирован. "
        "Всё что нужно — ваш email.\n\n"
        "📧 Введите ваш email адрес:"
    )
    await RegistrationStates.waiting_email.set()


async def cmd_cancel(message: types.Message, state: FSMContext):
    """Сброс текущего состояния и возврат в начало."""
    current_state = await state.get_state()
    if current_state is None:
        await message.answer("🤷 Нет активных действий для отмены.")
        return

    await state.finish()
    await message.answer(
        "✅ Действие отменено.\n"
        "Чтобы начать заново, отправьте /start."
    )


async def process_email(message: types.Message, state: FSMContext):
    """Принимаем email"""
    email = message.text.strip().lower()

    if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
        await message.answer("❌ Некорректный email. Попробуйте ещё раз:")
        return

    domain = email.split('@')[1]
    default_servers = {
        'gmail.com': ('smtp.gmail.com', 587, 'imap.gmail.com', 993),
        'mail.ru': ('smtp.mail.ru', 587, 'imap.mail.ru', 993),
        'yandex.ru': ('smtp.yandex.ru', 587, 'imap.yandex.ru', 993),
        'yahoo.com': ('smtp.mail.yahoo.com', 587, 'imap.mail.yahoo.com', 993),
        'outlook.com': ('smtp.office365.com', 587, 'outlook.office365.com', 993),
    }

    if domain in default_servers:
        smtp_host, smtp_port, imap_host, imap_port = default_servers[domain]
        await state.update_data(
            email=email,
            smtp_host=smtp_host,
            smtp_port=smtp_port,
            imap_host=imap_host,
            imap_port=imap_port
        )
        await message.answer(
            f"✅ Почтовый сервер определён автоматически: {domain}\n"
            f"SMTP: {smtp_host}\nIMAP: {imap_host}\n\n"
            "🔑 Введите пароль от вашей почты (или пароль приложения):"
        )
        await RegistrationStates.waiting_email_password.set()
    else:
        await state.update_data(email=email)
        await message.answer("Введите SMTP сервер (например, smtp.yourcompany.com):")
        await RegistrationStates.waiting_smtp_host.set()


async def process_email_password(message: types.Message, state: FSMContext):
    """Принимаем пароль и проверяем подключение"""
    password = message.text
    data = await state.get_data()
    await state.update_data(email_password_encrypted=encrypt_data(password))

    await message.answer("⏳ Проверяю подключение к почте...")

    try:
        import aiosmtplib
        smtp = aiosmtplib.SMTP(
            hostname=data['smtp_host'],
            port=data['smtp_port'],
            use_tls=data['smtp_port'] == 465
        )
        await smtp.connect()
        if data['smtp_port'] == 587:
            try:
                await smtp.starttls()
            except Exception as tls_error:
                # Если соединение уже защищено – игнорируем, иначе пробрасываем дальше
                if "already using TLS" not in str(tls_error) and "TLS already in use" not in str(tls_error):
                    raise
        await smtp.login(data['email'], password)
        await smtp.quit()
    except Exception as e:
        await message.answer(
            f"❌ Не удалось подключиться к почте: {e}\n\n"
            "Проверьте:\n"
            "• Правильность пароля\n"
            "• Для Gmail нужен пароль приложения\n"
            "• Для Mail.ru нужно разрешить IMAP в настройках\n\n"
            "Попробуйте ещё раз или отправьте /cancel для отмены."
        )
        return

    await message.answer("✅ Почта подключена успешно!")
    await message.answer(
        "📱 Теперь нужно подключить Telegram.\n"
        "Введите ваш номер телефона в международном формате (+79161234567):"
    )
    await RegistrationStates.waiting_phone_number.set()


async def process_phone_number(message: types.Message, state: FSMContext):
    """Авторизация в Telegram через Telethon"""
    phone = message.text.strip()
    client = await TelethonSessionManager.create_client(phone=phone, user_id=message.from_user.id)

    await state.update_data(phone_number=phone)

    try:
        result = await client.send_code_request(phone)
        await state.update_data(phone_code_hash=result.phone_code_hash, _telethon_client=client)
        await message.answer("📲 Telegram отправил код подтверждения. Введите его:")
        await RegistrationStates.waiting_telegram_code.set()
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}. Проверьте номер телефона.")
        return


async def process_telegram_code(message: types.Message, state: FSMContext):
    """Принимаем код подтверждения Telegram"""
    code = message.text.strip()
    data = await state.get_data()
    client = data.get('_telethon_client')

    if not client:
        await message.answer("❌ Сессия истекла. Начните заново с /start")
        await state.finish()
        return

    try:
        await client.sign_in(
            phone=data['phone_number'],
            code=code,
            phone_code_hash=data['phone_code_hash']
        )
        await _finish_registration(message, state, client)

    except Exception as e:
        error_str = str(e).lower()
        if '2fa' in error_str or 'password' in error_str:
            await message.answer("🔐 Введите облачный пароль Telegram (2FA):")
            await RegistrationStates.waiting_2fa_password.set()
        else:
            await message.answer(f"❌ Ошибка: {e}. Попробуйте ещё раз:")
            await RegistrationStates.waiting_telegram_code.set()


async def process_2fa_password(message: types.Message, state: FSMContext):
    """Обработка 2FA пароля"""
    password = message.text
    data = await state.get_data()
    client = data.get('_telethon_client')

    if not client:
        await message.answer("❌ Сессия истекла. Начните заново с /start")
        await state.finish()
        return

    try:
        await client.sign_in(password=password)
        await _finish_registration(message, state, client)
    except Exception as e:
        await message.answer(f"❌ Неверный пароль: {e}. Попробуйте ещё раз:")
        await RegistrationStates.waiting_2fa_password.set()


async def _finish_registration(message: types.Message, state: FSMContext, client):
    """Завершение регистрации"""
    data = await state.get_data()

    session_string = client.session.save()
    if isinstance(session_string, str):
        encrypted_session = encrypt_data(base64.b64encode(session_string.encode()).decode())
    else:
        encrypted_session = encrypt_data(base64.b64encode(session_string).decode())

    async with get_db() as db:
        user = User(
            telegram_user_id=message.from_user.id,
            email=data['email'],
            email_password_encrypted=data.get('email_password_encrypted', ''),
            smtp_host=data.get('smtp_host', 'smtp.gmail.com'),
            smtp_port=data.get('smtp_port', 587),
            imap_host=data.get('imap_host', 'imap.gmail.com'),
            imap_port=data.get('imap_port', 993),
            telethon_session_string=encrypted_session,
            phone_number=data['phone_number'],
            is_telegram_authorized=True,
            last_active_at=datetime.utcnow(),
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)

    await state.finish()

    await message.answer(
        "🎉 Отлично! TeleMail Bridge настроен!\n\n"
        "Теперь все ваши личные сообщения из Telegram будут приходить на email.\n\n"
        "📋 Команды:\n"
        "/status — статус подключения\n"
        "/contacts — список контактов\n"
        "/upgrade — улучшить тариф\n"
        "/settings — настройки\n"
        "/help — помощь"
    )

    await TelethonSessionManager.start_listener(user)


async def show_main_menu(message: types.Message, user: User):
    """Показать главное меню"""
    await message.answer(
        f"👋 С возвращением!\n\n"
        f"📧 Email: {user.email}\n"
        f"📊 Сообщений сегодня: {user.messages_today}/{user.daily_limit}\n\n"
        f"Используйте команды:\n"
        f"/status — статус\n"
        f"/contacts — контакты\n"
        f"/upgrade — тариф\n"
        f"/help — помощь"
    )


def register_handlers(dp: Dispatcher):
    """Регистрация обработчиков"""
    dp.register_message_handler(cmd_start, commands=['start'])
    dp.register_message_handler(cmd_cancel, commands=['cancel'], state='*')  # доступна в любом состоянии
    dp.register_message_handler(process_email, state=RegistrationStates.waiting_email)
    dp.register_message_handler(process_email_password, state=RegistrationStates.waiting_email_password)
    dp.register_message_handler(process_phone_number, state=RegistrationStates.waiting_phone_number)
    dp.register_message_handler(process_telegram_code, state=RegistrationStates.waiting_telegram_code)
    dp.register_message_handler(process_2fa_password, state=RegistrationStates.waiting_2fa_password)
