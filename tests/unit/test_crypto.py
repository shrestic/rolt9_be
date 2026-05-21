import pytest

from app.core.crypto import decrypt_str, encrypt_str


def test_roundtrip_returns_original_value():
    cipher = encrypt_str("hello world")
    assert decrypt_str(cipher) == "hello world"


def test_ciphertext_is_not_the_plaintext():
    cipher = encrypt_str("hello world")
    assert "hello world" not in cipher.decode("utf-8", errors="ignore")


def test_decrypt_rejects_garbage():
    with pytest.raises(Exception):
        decrypt_str(b"not-a-valid-fernet-token")
