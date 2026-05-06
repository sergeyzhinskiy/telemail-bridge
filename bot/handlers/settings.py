# bot/handlers/settings.py
from aiogram import types, Dispatcher
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from datetime import datetime
from core.db import get_db
from core.security import decrypt_data
from core.telethon_manager import TelethonSessionManager
from core.telegram_listener import TelegramListener


class SettingsStates(StatesGroup):
    waiting_new_email = State()
    waiting_new_password = State()
    confirm_disconnect = State()


async def cmd_status(message: types.Message):
    """Показать статус подключения"""
    async with get_db() as db:
        user = await db.get_user_by_telegram_id(message.from_user.id)
        
        if not user:
            await message.answer(
                "❌ Вы не зарегистрированы. Используйте /start"
            )
            return
        
        # Статус Telegram
        if user.is_telegram_authorized:
            tg_status = "✅ Подключен"
            tg_info = f"📱 {user.phone_number}"
        else:
            tg_status = "❌ Не подключен"
            tg_info = "Требуется авторизация"
        
        # Статус Email
        email_status = "✅ Подключен" if user.email else "❌ Не подключен"
        
        # Тариф
        tier_names = {"free": "Free", "pro": "Pro", "business": "Business"}
        tier = tier_names.get(user.subscription_tier.value, "Free")
        
        # Статистика за сегодня
        messages_left = max(0, user.daily_limit - user.messages_today)
        
        status_text = (
            f"📊 <b>Статус TeleMail Bridge</b>\n\n"
            f"🔷 Telegram: {tg_status}\n"
            f"   {tg_info}\n\n"
            f"📧 Email: {email_status}\n"
            f"   {user.email}\n"
            f"   SMTP: {user.smtp_host}:{user.smtp_port}\n"
            f"   IMAP: {user.imap_host}:{user.imap_port}\n\n"
            f"💎 Тариф: <b>{tier}</b>\n"
            f"📨 Сообщений сегодня: {user.messages_today}/{user.daily_limit}\n"
            f"   Осталось: {messages_left}\n"
            f"📊 Всего сообщений: {user.total_messages_sent}\n\n"
            f"🕐 Последняя активность: "
            f"{user.last_active_at.strftime('%d.%m.%Y %H:%M') if user.last_active_at else 'Нет данных'}\n"
            f"📅 Зарегистрирован: "
            f"{user.created_at.strftime('%d.%m.%Y') if user.created_at else 'Нет данных'}"
        )
        
        if user.subscription_expires_at and user.subscription_tier.value != 'free':
            days_left = (user.subscription_expires_at - datetime.utcnow()).days
            status_text += f"\n⏳ Подписка истекает через: {days_left} дн."
        
        if user.is_banned:
            status_text += f"\n\n⛔ <b>Аккаунт заблокирован!</b>\nПричина: {user.ban_reason}"
        
        keyboard = InlineKeyboardMarkup(row_width=1)
        keyboard.add(
            InlineKeyboardButton("🔄 Обновить статус", callback_data="refresh_status"),
            InlineKeyboardButton("✏️ Изменить email", callback_data="change_email"),
            InlineKeyboardButton("🔌 Переподключить Telegram", callback_data="reconnect_telegram"),
            InlineKeyboardButton("💎 Сменить тариф", callback_data="upgrade_tier"),
            InlineKeyboardButton("📋 Мои контакты", callback_data="my_contacts")
        )
        
        await message.answer(status_text, reply_markup=keyboard, parse_mode="HTML")


async def cmd_contacts(message: types.Message):
    """Показать список контактов для пересылки"""
    async with get_db() as db:
        user = await db.get_user_by_telegram_id(message.from_user.id)
        
        if not user:
            await message.answer("❌ Вы не зарегистрированы.")
            return
        
        mappings = await db.get_active_chat_mappings(user.id)
        
        if not mappings:
            await message.answer(
                "📋 У вас пока нет активных контактов.\n\n"
                "Контакты появятся автоматически, когда кто-то напишет вам в Telegram "
                "или когда вы сами начнёте переписку."
            )
            return
        
        # Группируем: активные переписки и избранные
        favorites = [m for m in mappings if m.is_favorite]
        others = [m for m in mappings if not m.is_favorite]
        
        # Сортируем по дате последнего сообщения
        favorites.sort(key=lambda x: x.last_message_at or datetime.min, reverse=True)
        others.sort(key=lambda x: x.last_message_at or datetime.min, reverse=True)
        
        text = "📋 <b>Ваши контакты</b>\n\n"
        
        if favorites:
            text += "<b>⭐ Избранные:</b>\n"
            for i, m in enumerate(favorites[:20], 1):
                name = m.correspondent_name or "Неизвестный"
                username = f" (@{m.correspondent_username})" if m.correspondent_username else ""
                last_msg = m.last_message_text[:30] + "..." if m.last_message_text and len(m.last_message_text) > 30 else (m.last_message_text or "")
                last_time = m.last_message_at.strftime("%d.%m %H:%M") if m.last_message_at else ""
                text += f"{i}. {name}{username}\n   💬 {last_msg}\n   🕐 {last_time}\n\n"
        
        if others:
            text += "<b>💬 Остальные:</b>\n"
            for i, m in enumerate(others[:50], 1):
                name = m.correspondent_name or "Неизвестный"
                username = f" (@{m.correspondent_username})" if m.correspondent_username else ""
                last_time = m.last_message_at.strftime("%d.%m %H:%M") if m.last_message_at else ""
                text += f"{i}. {name}{username} — {last_time}\n"
        
        text += f"\nВсего контактов: {len(mappings)}"
        
        keyboard = InlineKeyboardMarkup(row_width=2)
        keyboard.add(
            InlineKeyboardButton("⭐ Управление избранным", callback_data="manage_favorites"),
            InlineKeyboardButton("🔄 Обновить", callback_data="refresh_contacts")
        )
        
        await message.answer(text, reply_markup=keyboard, parse_mode="HTML")


async def cmd_help(message: types.Message):
    """Помощь и инструкции"""
    help_text = (
        "📚 <b>TeleMail Bridge — Помощь</b>\n\n"
        "<b>Как это работает:</b>\n"
        "1️⃣ Кто-то пишет вам в Telegram\n"
        "2️⃣ Вы получаете email с этим сообщением\n"
        "3️⃣ Отвечаете на письмо — и ваш ответ уходит в Telegram\n\n"
        "<b>Команды:</b>\n"
        "/start — регистрация\n"
        "/status — статус подключения и статистика\n"
        "/contacts — список ваших контактов\n"
        "/upgrade — сменить тариф\n"
        "/settings — настройки email и Telegram\n"
        "/help — эта справка\n\n"
        "<b>Важно:</b>\n"
        "• Отвечайте на письма, не меняя тему — так бот поймёт, кому отвечать\n"
        "• Не удаляйте служебные заголовки в письмах\n"
        "• Для Gmail используйте пароль приложения\n"
        "• Для Mail.ru включите IMAP в настройках\n\n"
        "<b>Тарифы:</b>\n"
        "🆓 Free — 50 сообщений/день\n"
        "💎 Pro — безлимит, 299₽/мес\n"
        "🏢 Business — безлимит + кастомный домен, 999₽/мес\n\n"
        "<b>Поддержка:</b> @telemail_support"
    )
    
    await message.answer(help_text, parse_mode="HTML")


async def cmd_settings(message: types.Message):
    """Настройки аккаунта"""
    async with get_db() as db:
        user = await db.get_user_by_telegram_id(message.from_user.id)
        
        if not user:
            await message.answer("❌ Вы не зарегистрированы.")
            return
    
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(
        InlineKeyboardButton("✏️ Изменить email адрес", callback_data="change_email"),
        InlineKeyboardButton("🔑 Изменить пароль почты", callback_data="change_password"),
        InlineKeyboardButton("🔌 Переподключить Telegram", callback_data="reconnect_telegram"),
        InlineKeyboardButton("📧 Настроить почтовые серверы вручную", callback_data="manual_email_config"),
        InlineKeyboardButton("⛔ Отключить пересылку", callback_data="disable_forwarding"),
        InlineKeyboardButton("❌ Удалить аккаунт", callback_data="delete_account")
    )
    
    await message.answer("⚙️ <b>Настройки</b>\n\nВыберите действие:", reply_markup=keyboard, parse_mode="HTML")


# ========= CALLBACK HANDLERS =========

async def process_refresh_status(callback: types.CallbackQuery):
    """Обновить статус по кнопке"""
    await callback.answer("Обновляю...")
    await cmd_status(callback.message)
    await callback.message.edit_reply_markup()  # убираем старую клавиатуру


async def process_change_email_start(callback: types.CallbackQuery, state: FSMContext):
    """Начало смены email"""
    await callback.answer()
    await callback.message.answer("📧 Введите новый email адрес:")
    await SettingsStates.waiting_new_email.set()


async def process_new_email(message: types.Message, state: FSMContext):
    """Обработка нового email"""
    email = message.text.strip().lower()
    
    if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
        await message.answer("❌ Некорректный email. Попробуйте ещё раз:")
        return
    
    # Автоопределение серверов
    domain = email.split('@')[1]
    default_servers = {
        'gmail.com': ('smtp.gmail.com', 587, 'imap.gmail.com', 993),
        'mail.ru': ('smtp.mail.ru', 587, 'imap.mail.ru', 993),
        'yandex.ru': ('smtp.yandex.ru', 587, 'imap.yandex.ru', 993),
        'yahoo.com': ('smtp.mail.yahoo.com', 587, 'imap.mail.yahoo.com', 993),
        'outlook.com': ('smtp.office365.com', 587, 'outlook.office365.com', 993),
        'rambler.ru': ('smtp.rambler.ru', 587, 'imap.rambler.ru', 993),
    }
    
    async with get_db() as db:
        user = await db.get_user_by_telegram_id(message.from_user.id)
        
        if domain in default_servers:
            smtp_host, smtp_port, imap_host, imap_port = default_servers[domain]
            user.email = email
            user.smtp_host = smtp_host
            user.smtp_port = smtp_port
            user.imap_host = imap_host
            user.imap_port = imap_port
            await db.commit()
            
            await message.answer(
                f"✅ Email обновлён: {email}\n"
                f"Серверы определены автоматически:\n"
                f"SMTP: {smtp_host}\n"
                f"IMAP: {imap_host}"
            )
        else:
            user.email = email
            await db.commit()
            await message.answer(
                f"✅ Email обновлён: {email}\n"
                "⚠️ Не удалось определить серверы автоматически. "
                "Настройте их вручную через /settings"
            )
    
    await state.finish()


async def process_change_password_start(callback: types.CallbackQuery, state: FSMContext):
    """Начало смены пароля"""
    await callback.answer()
    await callback.message.answer(
        "🔑 Введите новый пароль от почты (или пароль приложения):\n\n"
        "<i>Пароль будет зашифрован и сохранён</i>",
        parse_mode="HTML"
    )
    await SettingsStates.waiting_new_password.set()


async def process_new_password(message: types.Message, state: FSMContext):
    """Сохранение нового пароля"""
    from core.security import encrypt_data
    
    async with get_db() as db:
        user = await db.get_user_by_telegram_id(message.from_user.id)
        user.email_password_encrypted = encrypt_data(message.text)
        await db.commit()
    
    # Удаляем сообщение с паролем для безопасности
    await message.delete()
    await message.answer("✅ Пароль обновлён.")
    await state.finish()


async def process_reconnect_telegram(callback: types.CallbackQuery, state: FSMContext):
    """Переподключение Telegram-сессии"""
    await callback.answer()
    
    async with get_db() as db:
        user = await db.get_user_by_telegram_id(message.from_user.id)
        
        # Останавливаем текущий слушатель
        await TelethonSessionManager.stop_listener(user.id)
        
        # Сбрасываем флаг авторизации
        user.is_telegram_authorized = False
        user.telethon_session_string = None
        await db.commit()
    
    await callback.message.answer(
        "🔌 Telegram-сессия сброшена.\n\n"
        "Введите номер телефона для переподключения "
        "(в международном формате, например +79161234567):"
    )
    await RegistrationStates.waiting_phone_number.set()


async def process_disable_forwarding(callback: types.CallbackQuery, state: FSMContext):
    """Отключение пересылки"""
    await callback.answer()
    
    keyboard = InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        InlineKeyboardButton("✅ Да, отключить", callback_data="confirm_disable"),
        InlineKeyboardButton("❌ Нет, оставить", callback_data="cancel_disable")
    )
    
    await callback.message.answer(
        "⛔ <b>Вы уверены?</b>\n\n"
        "После отключения сообщения из Telegram не будут приходить на email. "
        "Вы сможете включить обратно в любой момент.",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    await SettingsStates.confirm_disconnect.set()


async def process_confirm_disable(callback: types.CallbackQuery, state: FSMContext):
    """Подтверждение отключения"""
    async with get_db() as db:
        user = await db.get_user_by_telegram_id(message.from_user.id)
        user.is_active = False
        await db.commit()
    
    await TelethonSessionManager.stop_listener(user.id)
    
    await callback.message.answer(
        "⛔ Пересылка отключена.\n\n"
        "Чтобы включить снова, используйте /start"
    )
    await state.finish()


async def process_delete_account(callback: types.CallbackQuery):
    """Удаление аккаунта"""
    await callback.answer()
    
    keyboard = InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        InlineKeyboardButton("⚠️ Да, удалить безвозвратно", callback_data="confirm_delete"),
        InlineKeyboardButton("❌ Отмена", callback_data="cancel_delete")
    )
    
    await callback.message.answer(
        "❌ <b>Удаление аккаунта</b>\n\n"
        "Это действие необратимо! Все данные будут удалены:\n"
        "• Связка с Telegram\n"
        "• История переписок\n"
        "• Настройки\n\n"
        "Вы уверены?",
        reply_markup=keyboard,
        parse_mode="HTML"
    )


async def process_confirm_delete(callback: types.CallbackQuery):
    """Подтверждение удаления"""
    async with get_db() as db:
        user = await db.get_user_by_telegram_id(message.from_user.id)
        
        # Останавливаем слушатель
        await TelethonSessionManager.stop_listener(user.id)
        
        # Мягкое удаление
        user.is_active = False
        user.is_deleted = True
        user.deleted_at = datetime.utcnow()
        await db.commit()
    
    await callback.message.answer(
        "👋 Аккаунт удалён.\n\n"
        "Если захотите вернуться — просто напишите /start"
    )


async def process_manage_favorites(callback: types.CallbackQuery):
    """Управление избранными контактами"""
    async with get_db() as db:
        user = await db.get_user_by_telegram_id(message.from_user.id)
        mappings = await db.get_active_chat_mappings(user.id)
        
        if not mappings:
            await callback.answer("Нет контактов", show_alert=True)
            return
        
        text = "⭐ <b>Управление избранными</b>\n\n"
        text += "Нажмите на контакт, чтобы добавить/убрать из избранного:\n\n"
        
        keyboard = InlineKeyboardMarkup(row_width=1)
        for m in mappings[:30]:
            prefix = "⭐" if m.is_favorite else "☆"
            name = m.correspondent_name or "Неизвестный"
            username = f" (@{m.correspondent_username})" if m.correspondent_username else ""
            keyboard.add(
                InlineKeyboardButton(
                    f"{prefix} {name}{username}",
                    callback_data=f"toggle_favorite_{m.id}"
                )
            )
        
        keyboard.add(InlineKeyboardButton("🔙 Назад", callback_data="my_contacts"))
        
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")


async def process_toggle_favorite(callback: types.CallbackQuery):
    """Переключение избранного"""
    mapping_id = int(callback.data.split('_')[-1])
    
    async with get_db() as db:
        mapping = await db.get_chat_mapping_by_id(mapping_id)
        if mapping:
            mapping.is_favorite = not mapping.is_favorite
            await db.commit()
            
            status = "добавлен в избранное ⭐" if mapping.is_favorite else "удалён из избранного"
            await callback.answer(f"Контакт {status}")
    
    # Обновляем список
    await process_manage_favorites(callback)


# ========= РЕГИСТРАЦИЯ ХЕНДЛЕРОВ =========

def register_handlers(dp: Dispatcher):
    """Регистрация всех обработчиков настроек"""
    dp.register_message_handler(cmd_status, commands=['status'])
    dp.register_message_handler(cmd_contacts, commands=['contacts'])
    dp.register_message_handler(cmd_help, commands=['help'])
    dp.register_message_handler(cmd_settings, commands=['settings'])
    
    dp.register_callback_query_handler(process_refresh_status, text='refresh_status')
    dp.register_callback_query_handler(process_change_email_start, text='change_email')
    dp.register_callback_query_handler(process_change_password_start, text='change_password')
    dp.register_callback_query_handler(process_reconnect_telegram, text='reconnect_telegram')
    dp.register_callback_query_handler(process_disable_forwarding, text='disable_forwarding')
    dp.register_callback_query_handler(process_delete_account, text='delete_account')
    dp.register_callback_query_handler(process_confirm_disable, text='confirm_disable')
    dp.register_callback_query_handler(process_confirm_delete, text='confirm_delete')
    dp.register_callback_query_handler(process_manage_favorites, text='manage_favorites')
    dp.register_callback_query_handler(process_manage_favorites, text='my_contacts')
    dp.register_callback_query_handler(process_toggle_favorite, lambda c: c.data.startswith('toggle_favorite_'))
    dp.register_callback_query_handler(process_refresh_status, text='refresh_contacts')
    dp.register_callback_query_handler(process_refresh_status, text='upgrade_tier')
    
    dp.register_message_handler(process_new_email, state=SettingsStates.waiting_new_email)
    dp.register_message_handler(process_new_password, state=SettingsStates.waiting_new_password)