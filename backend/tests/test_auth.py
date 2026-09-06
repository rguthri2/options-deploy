import time

from app.auth import (
    create_session_token,
    hash_password,
    verify_password,
    verify_session_token,
)


def test_password_hash_roundtrip():
    hashed = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", hashed)
    assert not verify_password("wrong password", hashed)


def test_password_hash_is_salted():
    # Same password hashed twice should produce different hashes (random salt).
    assert hash_password("same-password") != hash_password("same-password")


def test_verify_password_rejects_garbage_hash():
    assert not verify_password("anything", "not-a-valid-hash")
    assert not verify_password("anything", "")


def test_session_token_roundtrip():
    token = create_session_token("alice", secret_key="s3cr3t", max_age_seconds=3600)
    assert verify_session_token(token, secret_key="s3cr3t") == "alice"


def test_session_token_rejects_wrong_secret():
    token = create_session_token("alice", secret_key="s3cr3t", max_age_seconds=3600)
    assert verify_session_token(token, secret_key="wrong-secret") is None


def test_session_token_rejects_tampering():
    token = create_session_token("alice", secret_key="s3cr3t", max_age_seconds=3600)
    payload_b64, signature_b64 = token.split(".")
    tampered = f"{payload_b64}x.{signature_b64}"
    assert verify_session_token(tampered, secret_key="s3cr3t") is None


def test_session_token_rejects_expired():
    token = create_session_token("alice", secret_key="s3cr3t", max_age_seconds=0)
    time.sleep(0.01)
    assert verify_session_token(token, secret_key="s3cr3t") is None


def test_session_token_rejects_malformed():
    assert verify_session_token("not-a-token", secret_key="s3cr3t") is None
    assert verify_session_token("", secret_key="s3cr3t") is None
