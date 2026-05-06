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
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.backends import default_backend

from core.config import settings


class SecurityManager:
    _fernet: Optional[Fernet] = None

    @classmethod
    def _get_fernet(cls) -> Fernet:
        if cls._fernet is None:
            key = cls._derive_fernet_key(settings.ENCRYPTION_KEY)
            cls._fernet = Fernet(key)
        return cls._fernet

    @classmethod
    def _derive_fernet_key(cls, raw_key: str) -> bytes:
        salt = b'telemail_bridge_salt_2024'
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=480000,
            backend=default_backend()
        )
        key = kdf.derive(raw_key.encode('utf-8'))
        return base64.urlsafe_b64encode(key)


def encrypt_data(plaintext: str) -> str:
    if not plaintext:
        return ''
    try:
        fernet = SecurityManager._get_fernet()
        encrypted = fernet.encrypt(plaintext.encode('utf-8'))
        return base64.urlsafe_b64encode(encrypted).decode('ascii')
    except Exception as e:
        raise EncryptionError(f"Encryption error: {e}")


def decrypt_data(encrypted_text: str) -> str:
    if not encrypted_text:
        return ''
    try:
        fernet = SecurityManager._get_fernet()
        encrypted = base64.urlsafe_b64decode(encrypted_text.encode('ascii'))
        decrypted = fernet.decrypt(encrypted)
        return decrypted.decode('utf-8')
    except Exception as e:
        raise DecryptionError(f"Decryption error: {e}")


def hash_password(password: str) -> str:
    import bcrypt
    return bcrypt.hashpw(
        password.encode('utf-8'),
        bcrypt.gensalt(rounds=12)
    ).decode('utf-8')


def verify_password(password: str, password_hash: str) -> bool:
    import bcrypt
    return bcrypt.checkpw(
        password.encode('utf-8'),
        password_hash.encode('utf-8')
    )


def generate_token(length: int = 32) -> str:
    return secrets.token_hex(length)


def generate_api_key() -> str:
    return 'tmb_' + secrets.token_hex(18)


def generate_message_id() -> str:
    random_part = secrets.token_hex(16)
    return f"<telemail-{random_part}@bridge>"


def sanitize_filename(filename: str) -> str:
    import re
    sanitized = re.sub(r'[^\w\.\-]', '_', filename)
    sanitized = re.sub(r'_{2,}', '_', sanitized)
    sanitized = re.sub(r'\.{2,}', '.', sanitized)
    if len(sanitized) > 200:
        name, ext = os.path.splitext(sanitized)
        sanitized = name[:195] + ext
    return sanitized.strip('_.')


def mask_email(email: str) -> str:
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
    hash_func = getattr(hashlib, algorithm)()
    with open(filepath, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            hash_func.update(chunk)
    return hash_func.hexdigest()


def verify_data_integrity(data: bytes, expected_hash: str, algorithm: str = 'sha256') -> bool:
    hash_func = getattr(hashlib, algorithm)()
    hash_func.update(data)
    actual_hash = hash_func.hexdigest()
    return hmac.compare_digest(actual_hash, expected_hash)


class EncryptionError(Exception):
    pass


class DecryptionError(Exception):
    pass


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
