import uuid

from app.core.security import create_session_token, decode_session_token


def test_create_and_decode_round_trip():
    user_id = uuid.uuid4()
    token = create_session_token(user_id)
    assert decode_session_token(token) == user_id


def test_decode_returns_none_on_garbage():
    assert decode_session_token("not-a-jwt") is None


def test_decode_returns_none_on_wrong_signature():
    # Forge with a different secret; should fail verify.
    from jose import jwt as _jwt

    forged = _jwt.encode({"sub": str(uuid.uuid4())}, "wrong-secret", algorithm="HS256")
    assert decode_session_token(forged) is None
