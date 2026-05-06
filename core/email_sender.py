# core/email_sender.py
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from email.utils import formatdate, make_msgid

import aiosmtplib

from core.config import settings
from core.security import decrypt_data

logger = logging.getLogger(__name__)


class EmailSender:
    """Отправка писем пользователю"""

    async def send_telegram_message_to_email(self, user, email_data: dict):
        """Отправить сообщение из Telegram на email пользователя"""
        password = decrypt_data(user.email_password_encrypted)

        msg = MIMEMultipart('mixed')

        msg_id = make_msgid(domain=settings.CATCH_ALL_DOMAIN)
        msg['Message-ID'] = msg_id

        msg['From'] = f"TeleMail Bridge <{settings.SMTP_FROM_ADDRESS}>"
        msg['To'] = user.email

        sender_display = email_data['sender_name']
        if email_data.get('sender_username'):
            sender_display += f" (@{email_data['sender_username']})"

        msg['Subject'] = f"✉ Telegram: {sender_display}"

        msg['X-TeleMail-User-Id'] = str(user.id)
        msg['X-TeleMail-Chat-Id'] = str(email_data['chat_id'])
        msg['X-TeleMail-Message-Id'] = str(email_data['message_id'])
        msg['X-TeleMail-Type'] = email_data['message_type']

        reply_address = f"reply+{user.id}+{email_data['chat_id']}@{settings.CATCH_ALL_DOMAIN}"
        msg['Reply-To'] = reply_address

        html_body = self._generate_html_body(email_data)
        text_body = self._generate_text_body(email_data)

        msg.attach(MIMEText(text_body, 'plain', 'utf-8'))
        msg.attach(MIMEText(html_body, 'html', 'utf-8'))

        if email_data.get('attachment'):
            attachment = email_data['attachment']
            filename = self._get_filename(email_data['message_type'])
            mime_type = self._get_mime_type(email_data['message_type'])

            main_type, sub_type = mime_type.split('/')
            part = MIMEBase(main_type, sub_type)
            part.set_payload(attachment)
            encoders.encode_base64(part)
            part.add_header(
                'Content-Disposition',
                f'attachment; filename="{filename}"'
            )
            msg.attach(part)

        try:
            smtp = aiosmtplib.SMTP(
                hostname=user.smtp_host,
                port=user.smtp_port,
                use_tls=user.smtp_port == 465
            )

            await smtp.connect()

            if user.smtp_port == 587:
                await smtp.starttls()

            await smtp.login(user.email, password)
            await smtp.send_message(msg)
            await smtp.quit()

            logger.info(f"Email отправлен: {user.email} ({email_data['message_type']})")

        except Exception as e:
            logger.error(f"Ошибка отправки email для user_id={user.id}: {e}")
            raise

    def _generate_html_body(self, data: dict) -> str:
        attachment_html = ""
        type_map = {
            'photo': '📷 <em>[Фотография прикреплена к письму]</em>',
            'voice': '🎤 <em>[Голосовое сообщение прикреплено к письму]</em>',
            'video': '🎬 <em>[Видео прикреплено к письму]</em>',
            'document': '📎 <em>[Документ прикреплён к письму]</em>',
            'audio': '🎵 <em>[Аудио прикреплено к письму]</em>',
            'file_too_large': '⚠️ <em>[Файл слишком большой для пересылки]</em>',
        }
        attachment_html = type_map.get(data['message_type'], '') + '</p>' if data['message_type'] in type_map else ''

        text = (data.get('text', '') or '').replace('\n', '<br>')

        return f"""
        <html>
        <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
            <div style="background: #f8f9fa; padding: 20px; border-radius: 10px;">
                <div style="color: #666; font-size: 12px; margin-bottom: 15px;">
                    Сообщение из Telegram → Email
                </div>
                <div style="background: white; padding: 15px; border-radius: 8px; border-left: 3px solid #2AABEE;">
                    <strong style="color: #2AABEE;">{data['sender_name']}</strong>
                    <span style="color: #999; font-size: 12px;">
                        {" @" + data['sender_username'] if data.get('sender_username') else ""}
                    </span>
                    <div style="margin-top: 10px; line-height: 1.5;">
                        {text}
                    </div>
                    {attachment_html}
                </div>
                <div style="margin-top: 15px; padding: 10px; background: #fff3cd; border-radius: 5px; font-size: 13px;">
                    ✏️ Чтобы ответить — просто напишите ответ на это письмо.
                    Сообщение будет доставлено в Telegram.
                </div>
                <div style="color: #999; font-size: 11px; margin-top: 10px;">
                    TeleMail Bridge • {data.get('date', '')}
                </div>
            </div>
        </body>
        </html>
        """

    def _generate_text_body(self, data: dict) -> str:
        lines = [
            f"Telegram-сообщение от: {data['sender_name']}",
        ]
        if data.get('sender_username'):
            lines.append(f"Username: @{data['sender_username']}")

        lines.append("-" * 40)

        if data.get('text'):
            lines.append(data['text'])

        type_emojis = {
            'photo': '📷 [Фотография прикреплена]',
            'voice': '🎤 [Голосовое сообщение прикреплено]',
            'video': '🎬 [Видео прикреплено]',
            'document': '📎 [Документ прикреплён]',
            'audio': '🎵 [Аудио прикреплено]',
        }
        if data['message_type'] in type_emojis:
            lines.append(type_emojis[data['message_type']])

        lines.extend([
            "-" * 40,
            "Чтобы ответить — просто напишите ответ на это письмо.",
            f"Время: {data.get('date', '')}"
        ])

        return '\n'.join(lines)

    @staticmethod
    def _get_filename(message_type: str) -> str:
        names = {
            'photo': 'photo.jpg',
            'voice': 'voice.ogg',
            'video': 'video.mp4',
            'audio': 'audio.mp3',
            'document': 'document.bin',
        }
        return names.get(message_type, 'attachment.bin')

    @staticmethod
    def _get_mime_type(message_type: str) -> str:
        types = {
            'photo': 'image/jpeg',
            'voice': 'audio/ogg',
            'video': 'video/mp4',
            'audio': 'audio/mpeg',
            'document': 'application/octet-stream',
        }
        return types.get(message_type, 'application/octet-stream')