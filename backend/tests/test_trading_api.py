from app.config import get_settings


def test_broker_status_defaults_to_paper(client):
    resp = client.get("/api/broker/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["effective_broker"] == "paper"
    assert body["is_live"] is False


def test_place_order_updates_account_and_positions(client):
    resp = client.post(
        "/api/orders",
        json={"symbol": "AAPL", "asset_type": "equity", "side": "buy", "quantity": 3, "order_type": "market"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "filled"

    account = client.get("/api/account").json()
    assert account["cash_balance"] == 100000.0 - 3 * 230.0
    assert len(account["positions"]) == 1
    assert account["positions"][0]["quantity"] == 3

    positions = client.get("/api/positions").json()["positions"]
    assert len(positions) == 1

    orders = client.get("/api/orders").json()["orders"]
    assert len(orders) == 1
    assert orders[0]["symbol"] == "AAPL"


def test_place_order_rejects_invalid_side(client):
    resp = client.post(
        "/api/orders",
        json={"symbol": "AAPL", "asset_type": "equity", "side": "sideways", "quantity": 1, "order_type": "market"},
    )
    assert resp.status_code == 200  # broker returns a rejected order, not an HTTP error
    assert resp.json()["status"] == "rejected"


def test_cancel_already_filled_order_returns_400(client):
    order = client.post(
        "/api/orders",
        json={"symbol": "AAPL", "asset_type": "equity", "side": "buy", "quantity": 1, "order_type": "market"},
    ).json()
    resp = client.post(f"/api/orders/{order['id']}/cancel")
    assert resp.status_code == 400


def test_cancel_nonexistent_order_returns_400(client):
    resp = client.post("/api/orders/999999/cancel")
    assert resp.status_code == 400


def test_live_trading_requires_confirm_live(client, monkeypatch):
    monkeypatch.setenv("ACTIVE_BROKER", "etrade")
    monkeypatch.setenv("LIVE_TRADING_ENABLED", "true")
    get_settings.cache_clear()
    try:
        resp = client.post(
            "/api/orders",
            json={"symbol": "AAPL", "asset_type": "equity", "side": "buy", "quantity": 1, "order_type": "market"},
        )
        assert resp.status_code == 400
        assert "confirm_live" in resp.json()["detail"]

        status = client.get("/api/broker/status").json()
        assert status["is_live"] is True
        assert status["effective_broker"] == "etrade"
    finally:
        get_settings.cache_clear()


def test_live_trading_with_confirm_but_no_etrade_credentials_fails_clearly(client, monkeypatch):
    monkeypatch.setenv("ACTIVE_BROKER", "etrade")
    monkeypatch.setenv("LIVE_TRADING_ENABLED", "true")
    get_settings.cache_clear()
    try:
        resp = client.post(
            "/api/orders",
            json={
                "symbol": "AAPL",
                "asset_type": "equity",
                "side": "buy",
                "quantity": 1,
                "order_type": "market",
                "confirm_live": True,
            },
        )
        assert resp.status_code == 400
        assert "not configured" in resp.json()["detail"].lower()
    finally:
        get_settings.cache_clear()


def test_etrade_auth_url_without_credentials_fails_fast_no_network_call(client):
    # Must not attempt a real network call to etrade.com when unconfigured.
    resp = client.get("/api/broker/etrade/auth-url")
    assert resp.status_code == 400
    assert "not configured" in resp.json()["detail"].lower()


def test_option_order_via_api(client):
    screen = client.get("/api/screen", params={"ticker": "AAPL"}).json()
    call = next(c for c in screen["contracts"] if c["option_type"] == "call")
    resp = client.post(
        "/api/orders",
        json={
            "symbol": "AAPL",
            "asset_type": "option",
            "side": "buy",
            "quantity": 1,
            "order_type": "market",
            "option_type": "call",
            "strike": call["strike"],
            "expiration": call["expiration"],
        },
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "filled"
