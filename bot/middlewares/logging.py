# bot/middlewares/logging.py
import logging
import time
from datetime import datetime
from aiogram import types
from aiogram.dispatcher.middlewares import BaseMiddleware

logger = logging.getLogger(__name__)


class LoggingMiddleware(BaseMiddleware):
    """
    Middleware для логирования всех входящих сообщений и callback-запросов.
    Записывает: user_id, username, текст сообщения, время обработки.
    """

    async def on_pre_process_message(self, message: types.Message, data: dict):
        """Логирование входящего сообщения ДО обработки"""
        data['_log_start_time'] = time.time()
        
        user_info = self._get_user_info(message)
        chat_info = self._get_chat_info(message)
        
        logger.info(
            f"[MSG IN] "
            f"user_id={user_info['user_id']} "
            f"username={user_info['username']} "
            f"full_name={user_info['full_name']} "
            f"chat_type={chat_info['chat_type']} "
            f"text={self._truncate(message.text)} "
            f"content_type={message.content_type}"
        )

    async def on_post_process_message(self, message: types.Message, results, data: dict):
        """Логирование после обработки сообщения"""
        start_time = data.get('_log_start_time', time.time())
        elapsed = (time.time() - start_time) * 1000  # в миллисекундах
        
        user_info = self._get_user_info(message)
        
        logger.info(
            f"[MSG OUT] "
            f"user_id={user_info['user_id']} "
            f"elapsed={elapsed:.1f}ms "
            f"success={results is not None}"
        )

    async def on_pre_process_callback_query(self, callback: types.CallbackQuery, data: dict):
        """Логирование callback-запроса"""
        data['_log_start_time'] = time.time()
        
        user_info = self._get_user_info(callback)
        
        logger.info(
            f"[CALLBACK IN] "
            f"user_id={user_info['user_id']} "
            f"username={user_info['username']} "
            f"data={callback.data[:100]}"
        )

    async def on_post_process_callback_query(self, callback: types.CallbackQuery, results, data: dict):
        """Логирование после обработки callback"""
        start_time = data.get('_log_start_time', time.time())
        elapsed = (time.time() - start_time) * 1000
        
        user_info = self._get_user_info(callback)
        
        logger.info(
            f"[CALLBACK OUT] "
            f"user_id={user_info['user_id']} "
            f"data={callback.data[:100]} "
            f"elapsed={elapsed:.1f}ms"
        )

    async def on_pre_process_error(self, update: types.Update, exception: Exception, data: dict):
        """Логирование ошибок"""
        logger.error(
            f"[ERROR] "
            f"update_id={update.update_id} "
            f"error_type={type(exception).__name__} "
            f"error_message={str(exception)[:200]}",
            exc_info=True
        )

    def _get_user_info(self, obj) -> dict:
        """Извлечение информации о пользователе"""
        if hasattr(obj, 'from_user') and obj.from_user:
            return {
                'user_id': obj.from_user.id,
                'username': obj.from_user.username or 'N/A',
                'full_name': f"{obj.from_user.first_name or ''} {obj.from_user.last_name or ''}".strip()
            }
        elif hasattr(obj, 'message') and obj.message:
            return self._get_user_info(obj.message)
        return {'user_id': 'unknown', 'username': 'N/A', 'full_name': 'N/A'}

    def _get_chat_info(self, message: types.Message) -> dict:
        """Извлечение информации о чате"""
        return {
            'chat_type': message.chat.type,
            'chat_id': message.chat.id
        }

    def _truncate(self, text: str, max_len: int = 200) -> str:
        """Обрезание длинных сообщений для логов"""
        if not text:
            return '[empty]'
        if len(text) > max_len:
            return text[:max_len] + '...'
        return text