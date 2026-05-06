# core/security.py
"""
Модуль безопасности для TeleMail Bridge.

Обеспечивает:
- Шифрование/дешифрование конфиденциальных данных (пароли, сессии)
- Хеширование паролей администраторов
- Генерацию случайных токенов и ключей
"""

import os
import base64
import hashlib
import hmac
import secrets
from typing import Optional

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend

from core.config import settings


class SecurityManager:
    """
    Менеджер безопасности.
    
    Использует Fernet (AES-128-CBC + HMAC) для шифрования данных.
    Ключ шифрования хранится в ENCRYPTION_KEY (переменная окружения).
    """
    
    _fernet: Optional[Fernet] = None
    
    @classmethod
    def _get_fernet(cls) -> Fernet:
        """Ленивая инициализация Fernet с ключом из конфига"""
        if cls._fernet is None:
            # Fernet требует ключ в формате base64 (32 байта)
            key = cls._derive_fernet_key(settings.ENCRYPTION_KEY)
            cls._fernet = Fernet(key)
        return cls._fernet
    
    @classmethod
    def _derive_fernet_key(cls, raw_key: str) -> bytes:
        """
        Преобразует строковый ключ в 32-байтовый base64 ключ для Fernet.
        Использует PBKDF2 для усиления ключа.
        """
        # Соль для деривации ключа
        salt = b'telemail_bridge_salt_2024'
        
        kdf = PBKDF2(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=480000,  # Рекомендуемое количество итераций
        )
        
        key = kdf.derive(raw_key.encode('utf-8'))
        return base64.urlsafe_b64encode(key)


def encrypt_data(plaintext: str) -> str:
    """
    Шифрует строку.
    
    Args:
        plaintext: Исходная строка для шифрования
    
    Returns:
        Зашифрованная строка в формате base64
    """
    if not plaintext:
        return ''
    
    try:
        fernet = SecurityManager._get_fernet()
        encrypted = fernet.encrypt(plaintext.encode('utf-8'))
        return base64.urlsafe_b64encode(encrypted).decode('ascii')
    except Exception as e:
        raise EncryptionError(f"Ошибка шифрования: {e}")


def decrypt_data(encrypted_text: str) -> str:
    """
    Расшифровывает строку.
    
    Args:
        encrypted_text: Зашифрованная строка в формате base64
    
    Returns:
        Расшифрованная исходная строка
    """
    if not encrypted_text:
        return ''
    
    try:
        fernet = SecurityManager._get_fernet()
        encrypted = base64.urlsafe_b64decode(encrypted_text.encode('ascii'))
        decrypted = fernet.decrypt(encrypted)
        return decrypted.decode('utf-8')
    except Exception as e:
        raise DecryptionError(f"Ошибка расшифровки: {e}")


def hash_password(password: str) -> str:
    """
    Хеширует пароль с использованием bcrypt.
    
    Args:
        password: Исходный пароль
    
    Returns:
        Хеш пароля в формате bcrypt
    """
    import bcrypt
    return bcrypt.hashpw(
        password.encode('utf-8'),
        bcrypt.gensalt(rounds=12)
    ).decode('utf-8')


def verify_password(password: str, password_hash: str) -> bool:
    """
    Проверяет пароль на соответствие хешу.
    
    Args:
        password: Проверяемый пароль
        password_hash: Хеш пароля
    
    Returns:
        True если пароль верный
    """
    import bcrypt
    return bcrypt.checkpw(
        password.encode('utf-8'),
        password_hash.encode('utf-8')
    )


def generate_token(length: int = 32) -> str:
    """
    Генерирует криптографически безопасный токен.
    
    Args:
        length: Длина токена в байтах
    
    Returns:
        Случайная hex-строка
    """
    return secrets.token_hex(length)


def generate_api_key() -> str:
    """
    Генерирует API ключ для программного доступа к админке.
    
    Формат: tmb_XXXXX... (40 символов)
    """
    return 'tmb_' + secrets.token_hex(18)


def generate_message_id() -> str:
    """
    Генерирует уникальный идентификатор сообщения для email-заголовков.
    
    Формат: <telemail-XXXXX@bridge>
    """
    random_part = secrets.token_hex(16)
    return f"<telemail-{random_part}@bridge>"


def sanitize_filename(filename: str) -> str:
    """
    Очищает имя файла от опасных символов.
    
    Args:
        filename: Исходное имя файла
    
    Returns:
        Безопасное имя файла
    """
    import re
    # Удаляем все символы кроме букв, цифр, точек, дефисов и подчёркиваний
    sanitized = re.sub(r'[^\w\.\-]', '_', filename)
    # Удаляем множественные подчёркивания и точки
    sanitized = re.sub(r'_{2,}', '_', sanitized)
    sanitized = re.sub(r'\.{2,}', '.', sanitized)
    # Ограничиваем длину
    if len(sanitized) > 200:
        name, ext = os.path.splitext(sanitized)
        sanitized = name[:195] + ext
    return sanitized.strip('_.')


def mask_email(email: str) -> str:
    """
    Маскирует email для отображения в логах.
    
    Пример: user@example.com -> u***@e***.com
    
    Args:
        email: Email адрес
    
    Returns:
        Замаскированный email
    """
    if not email or '@' not in email:
        return '***@***.***'
    
    local, domain = email.split('@', 1)
    
    masked_local = local[0] + '***' if len(local) > 1 else '***'
    
    domain_parts = domain.split('.')
    if len(domain_parts) >= 2:
        masked_domain = domain_parts[0][0] + '***' + '.' + '.'.join(domain_parts[1:])
    else:
        masked_domain = '***.***'
    
    return f"{masked_local}@{masked_domain}"


def calculate_file_hash(filepath: str, algorithm: str = 'sha256') -> str:
    """
    Вычисляет хеш файла.
    
    Args:
        filepath: Путь к файлу
        algorithm: Алгоритм хеширования (sha256, md5, sha512)
    
    Returns:
        Hex-строка хеша
    """
    hash_func = getattr(hashlib, algorithm)()
    
    with open(filepath, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            hash_func.update(chunk)
    
    return hash_func.hexdigest()


def verify_data_integrity(data: bytes, expected_hash: str, algorithm: str = 'sha256') -> bool:
    """
    Проверяет целостность данных по хешу.
    
    Args:
        data: Бинарные данные
        expected_hash: Ожидаемый хеш
        algorithm: Алгоритм хеширования
    
    Returns:
        True если хеш совпадает
    """
    hash_func = getattr(hashlib, algorithm)()
    hash_func.update(data)
    actual_hash = hash_func.hexdigest()
    return hmac.compare_digest(actual_hash, expected_hash)


class EncryptionError(Exception):
    """Ошибка при шифровании данных"""
    pass


class DecryptionError(Exception):
    """Ошибка при расшифровке данных"""
    pass


# Удобные алиасы для использования в других модулях
__all__ = [
    'encrypt_data',
    'decrypt_data',
    'hash_password',
    'verify_password',
    'generate_token',
    'generate_api_key',
    'generate_message_id',
    'sanitize_filename',
    'mask_email',
    'calculate_file_hash',
    'verify_data_integrity',
    'EncryptionError',
    'DecryptionError',
]