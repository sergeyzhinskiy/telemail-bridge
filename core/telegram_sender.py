# core/telegram_sender.py
from telethon import TelegramClient
from telethon.tl.types import (
    InputMediaUploadedDocument, 
    DocumentAttributeAudio,
    DocumentAttributeVideo,
    InputFile
)
from core.db import get_db
from core.security import decrypt_data
from core.telethon_manager import TelethonSessionManager
import os
import tempfile
import logging
from datetime import datetime
import mimetypes

logger = logging.getLogger(__name__)


class TelegramSender:
    """
    Отправка сообщений в Telegram от имени пользователя
    через его Telethon-сессию.
    Используется при получении ответа с email.
    """
    
    # Максимальный размер файла для отправки (2 ГБ — лимит Telegram)
    MAX_FILE_SIZE = 2 * 1024 * 1024 * 1024
    
    # Поддерживаемые типы медиа
    MEDIA_TYPES = {
        'text': 'text',
        'voice': 'voice',
        'video': 'video',
        'photo': 'photo',
        'audio': 'audio',
        'document': 'document',
        'video_note': 'video_note'
    }
    
    async def send_message(
        self,
        user,
        chat_id: int,
        text: str = None,
        media_data: bytes = None,
        media_type: str = 'text',
        filename: str = None,
        reply_to_message_id: int = None,
        parse_mode: str = None
    ) -> bool:
        """
        Отправка сообщения в Telegram от имени пользователя.
        
        Args:
            user: объект User из БД
            chat_id: ID чата Telegram
            text: текст сообщения
            media_data: бинарные данные файла
            media_type: тип медиа ('text', 'voice', 'video', 'photo', etc.)
            filename: имя файла
            reply_to_message_id: ID сообщения для ответа
        
        Returns:
            bool: успешность отправки
        """
        # Получаем клиент Telethon для пользователя
        client = TelethonSessionManager._clients.get(user.id)
        
        if not client:
            # Пробуем создать и подключить
            try:
                session_string = decrypt_data(user.telethon_session_string)
                client = await self._create_client_from_session(session_string, user.id)
                TelethonSessionManager._clients[user.id] = client
            except Exception as e:
                logger.error(f"Не удалось создать клиент для user_id={user.id}: {e}")
                return False
        
        try:
            # Проверяем, подключен ли клиент
            if not client.is_connected():
                await client.connect()
            
            # Определяем сущность чата
            entity = await client.get_input_entity(chat_id)
            
            # Отправляем в зависимости от типа
            if media_type == 'text' or (not media_data and text):
                # Простое текстовое сообщение
                await client.send_message(
                    entity,
                    text or '',
                    reply_to=reply_to_message_id,
                    parse_mode=parse_mode or 'html'
                )
                
            elif media_type == 'voice' and media_data:
                # Голосовое сообщение
                temp_file = self._save_temp_file(media_data, filename or 'voice.ogg')
                
                await client.send_file(
                    entity,
                    temp_file,
                    voice_note=True,
                    reply_to=reply_to_message_id,
                    caption=text
                )
                
                self._cleanup_temp_file(temp_file)
                
            elif media_type == 'video' and media_data:
                # Видео
                temp_file = self._save_temp_file(media_data, filename or 'video.mp4')
                
                # Определяем атрибуты видео
                attributes = self._get_video_attributes(temp_file)
                
                await client.send_file(
                    entity,
                    temp_file,
                    attributes=attributes,
                    reply_to=reply_to_message_id,
                    caption=text,
                    supports_streaming=True
                )
                
                self._cleanup_temp_file(temp_file)
                
            elif media_type == 'photo' and media_data:
                # Фото
                temp_file = self._save_temp_file(media_data, filename or 'photo.jpg')
                
                await client.send_file(
                    entity,
                    temp_file,
                    reply_to=reply_to_message_id,
                    caption=text
                )
                
                self._cleanup_temp_file(temp_file)
                
            elif media_type == 'audio' and media_data:
                # Аудио (музыка)
                temp_file = self._save_temp_file(media_data, filename or 'audio.mp3')
                
                await client.send_file(
                    entity,
                    temp_file,
                    attributes=[DocumentAttributeAudio(
                        duration=0,
                        title=filename,
                        performer=''
                    )],
                    reply_to=reply_to_message_id,
                    caption=text
                )
                
                self._cleanup_temp_file(temp_file)
                
            elif media_type == 'document' and media_data:
                # Документ
                temp_file = self._save_temp_file(media_data, filename or 'document')
                
                await client.send_file(
                    entity,
                    temp_file,
                    force_document=True,
                    reply_to=reply_to_message_id,
                    caption=text
                )
                
                self._cleanup_temp_file(temp_file)
                
            elif media_type == 'video_note' and media_data:
                # Видео-кружок
                temp_file = self._save_temp_file(media_data, filename or 'video_note.mp4')
                
                await client.send_file(
                    entity,
                    temp_file,
                    video_note=True,
                    reply_to=reply_to_message_id
                )
                
                self._cleanup_temp_file(temp_file)
            
            else:
                # Неизвестный тип — отправляем как текст
                if text:
                    await client.send_message(
                        entity,
                        text,
                        reply_to=reply_to_message_id
                    )
            
            logger.info(
                f"Сообщение отправлено в Telegram: "
                f"user_id={user.id}, chat_id={chat_id}, type={media_type}"
            )
            
            # Обновляем статистику
            await self._update_stats(user.id)
            
            return True
            
        except Exception as e:
            logger.error(
                f"Ошибка отправки в Telegram: "
                f"user_id={user.id}, chat_id={chat_id}, error={e}",
                exc_info=True
            )
            
            # Пробуем переподключить клиент при ошибке
            try:
                await client.connect()
                logger.info(f"Клиент переподключен для user_id={user.id}")
            except:
                pass
            
            return False
    
    async def send_multiple_messages(
        self,
        user,
        chat_id: int,
        messages: list
    ) -> int:
        """
        Отправка нескольких сообщений в один чат.
        Используется когда пользователь отправляет несколько файлов разом.
        
        Args:
            user: пользователь
            chat_id: ID чата
            messages: список словарей [{text, media_data, media_type, filename}, ...]
        
        Returns:
            int: количество успешно отправленных сообщений
        """
        success_count = 0
        
        for msg in messages:
            result = await self.send_message(
                user=user,
                chat_id=chat_id,
                text=msg.get('text'),
                media_data=msg.get('media_data'),
                media_type=msg.get('media_type', 'text'),
                filename=msg.get('filename')
            )
            if result:
                success_count += 1
        
        return success_count
    
    async def forward_message_to_user(
        self,
        source_user,
        target_chat_id: int,
        message_id: int
    ) -> bool:
        """
        Пересылка конкретного сообщения в другой чат.
        
        Args:
            source_user: пользователь-отправитель
            target_chat_id: целевой чат
            message_id: ID сообщения для пересылки
        
        Returns:
            bool: успешность
        """
        client = TelethonSessionManager._clients.get(source_user.id)
        
        if not client or not client.is_connected():
            logger.error(f"Клиент не доступен для user_id={source_user.id}")
            return False
        
        try:
            entity = await client.get_input_entity(target_chat_id)
            await client.forward_messages(entity, message_id, source_user.telegram_user_id)
            return True
        except Exception as e:
            logger.error(f"Ошибка пересылки: {e}")
            return False
    
    async def edit_message(
        self,
        user,
        chat_id: int,
        message_id: int,
        new_text: str
    ) -> bool:
        """Редактирование отправленного сообщения"""
        client = TelethonSessionManager._clients.get(user.id)
        
        if not client or not client.is_connected():
            return False
        
        try:
            entity = await client.get_input_entity(chat_id)
            await client.edit_message(entity, message_id, new_text)
            return True
        except Exception as e:
            logger.error(f"Ошибка редактирования: {e}")
            return False
    
    async def delete_message(
        self,
        user,
        chat_id: int,
        message_id: int
    ) -> bool:
        """Удаление сообщения"""
        client = TelethonSessionManager._clients.get(user.id)
        
        if not client or not client.is_connected():
            return False
        
        try:
            entity = await client.get_input_entity(chat_id)
            await client.delete_messages(entity, [message_id], revoke=True)
            return True
        except Exception as e:
            logger.error(f"Ошибка удаления: {e}")
            return False
    
    async def get_chat_info(self, user, chat_id: int) -> dict:
        """Получение информации о чате"""
        client = TelethonSessionManager._clients.get(user.id)
        
        if not client or not client.is_connected():
            return {}
        
        try:
            entity = await client.get_entity(chat_id)
            
            info = {
                'name': getattr(entity, 'first_name', '') or getattr(entity, 'title', ''),
                'username': getattr(entity, 'username', None),
                'phone': getattr(entity, 'phone', None),
                'is_bot': getattr(entity, 'bot', False),
                'is_verified': getattr(entity, 'verified', False),
            }
            
            return info
        except Exception as e:
            logger.error(f"Ошибка получения информации о чате: {e}")
            return {}
    
    def _save_temp_file(self, data: bytes, filename: str) -> str:
        """Сохранить бинарные данные во временный файл"""
        temp_dir = tempfile.gettempdir()
        filepath = os.path.join(temp_dir, f"telemail_{int(datetime.utcnow().timestamp())}_{filename}")
        
        with open(filepath, 'wb') as f:
            f.write(data)
        
        return filepath
    
    def _cleanup_temp_file(self, filepath: str):
        """Удалить временный файл"""
        try:
            if os.path.exists(filepath):
                os.remove(filepath)
        except Exception as e:
            logger.warning(f"Не удалось удалить временный файл {filepath}: {e}")
    
    def _get_video_attributes(self, filepath: str) -> list:
        """Получить атрибуты видеофайла"""
        try:
            import subprocess
            
            # Пробуем получить информацию через ffprobe
            result = subprocess.run(
                ['ffprobe', '-v', 'quiet', '-print_format', 'json', 
                 '-show_format', '-show_streams', filepath],
                capture_output=True, text=True, timeout=10
            )
            
            if result.returncode == 0:
                import json
                info = json.loads(result.stdout)
                
                video_stream = None
                audio_stream = None
                
                for stream in info.get('streams', []):
                    if stream['codec_type'] == 'video':
                        video_stream = stream
                    elif stream['codec_type'] == 'audio':
                        audio_stream = stream
                
                if video_stream:
                    width = int(video_stream.get('width', 640))
                    height = int(video_stream.get('height', 480))
                    duration = int(float(info['format'].get('duration', 0)))
                    
                    return [
                        DocumentAttributeVideo(
                            duration=duration,
                            w=width,
                            h=height,
                            supports_streaming=True
                        )
                    ]
        except Exception as e:
            logger.warning(f"Не удалось получить атрибуты видео: {e}")
        
        # Возвращаем базовые атрибуты
        return [DocumentAttributeVideo(
            duration=0,
            w=640,
            h=480,
            supports_streaming=True
        )]
    
    async def _create_client_from_session(
        self,
        session_string: str,
        user_id: int
    ) -> TelegramClient:
        """Создать Telethon клиент из строки сессии"""
        from core.config import settings
        
        client = TelegramClient(
            f"sessions/user_{user_id}",
            settings.TELEGRAM_API_ID,
            settings.TELEGRAM_API_HASH,
            device_model="TeleMail Bridge",
            system_version="1.0.0"
        )
        
        await client.connect()
        
        # Загружаем сессию из строки
        # Примечание: Telethon требует сохранения в файл
        session_file = f"sessions/user_{user_id}.session"
        
        import base64
        with open(session_file, 'wb') as f:
            f.write(base64.b64decode(session_string))
        
        return client
    
    async def _update_stats(self, user_id: int):
        """Обновить статистику пользователя"""
        async with get_db() as db:
            await db.execute(
                "UPDATE users SET "
                "messages_today = messages_today + 1, "
                "total_messages_sent = total_messages_sent + 1, "
                "last_active_at = NOW() "
                "WHERE id = :user_id",
                {"user_id": user_id}
            )
            await db.commit()


# Создаём глобальный экземпляр
telegram_sender = TelegramSender()