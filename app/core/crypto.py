from cryptography.fernet import Fernet

from app.core.config import settings

_fernet = Fernet(settings.TOKEN_ENCRYPTION_KEY.encode())


def encrypt_str(plaintext: str) -> bytes:
    return _fernet.encrypt(plaintext.encode("utf-8"))


def decrypt_str(ciphertext: bytes) -> str:
    return _fernet.decrypt(ciphertext).decode("utf-8")
