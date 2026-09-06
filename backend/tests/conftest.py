"""Shared pytest fixtures: sets required env vars before any `app.*` module
is imported (get_settings() is process-wide lru_cache'd), and provides an
authenticated TestClient with a fresh SQLite DB per test.
"""
from __future__ import annotations

import os

# Must happen before any test module imports app.config/app.main.
os.environ.setdefault("DATA_PROVIDER", "mock")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("ADMIN_USERNAME", "testadmin")
os.environ.setdefault("COOKIE_SECURE", "false")  # TestClient talks plain http
os.environ.setdefault("PAPER_STARTING_CASH", "100000")

import pytest  # noqa: E402

from app.auth import hash_password  # noqa: E402
from app.config import get_settings  # noqa: E402

TEST_PASSWORD = "correct horse battery staple"
os.environ.setdefault("ADMIN_PASSWORD_HASH", hash_password(TEST_PASSWORD))


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    """Point DB_PATH at a fresh temp file and (re-)initialize it."""
    from app import db

    db_path = tmp_path / "test.db"
    monkeypatch.setenv("DB_PATH", str(db_path))
    get_settings.cache_clear()
    db.init_db(get_settings().paper_starting_cash)
    yield db_path
    get_settings.cache_clear()


@pytest.fixture
def client(fresh_db):
    """An authenticated TestClient (lifespan-aware, so startup/init_db runs)."""
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        resp = c.post("/api/auth/login", json={"username": "testadmin", "password": TEST_PASSWORD})
        assert resp.status_code == 200, resp.text
        yield c
