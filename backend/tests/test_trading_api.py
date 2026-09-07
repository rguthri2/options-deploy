from app.config import get_settings


def test_broker_status_defaults_to_paper(client):
    resp = client.get("/api/broker/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["effective_broker"] == "paper"
    assert body["is_live"] is False


def test_toggle_to_etrade_rejected_when_live_trading_disabled(client):
    resp = client.post("/api/broker/mode", json={"mode": "etrade"})
    assert resp.status_code == 400
    assert "not enabled on the server" in resp.json()["detail"]
    # Must not have flipped anything.
    assert client.get("/api/broker/status").json()["effective_broker"] == "paper"


def test_toggle_rejects_unknown_mode(client):
    resp = client.post("/api/broker/mode", json={"mode": "bogus"})
    assert resp.status_code == 400


def test_toggle_between_paper_and_live_once_server_allows_it(client, monkeypatch):
    monkeypatch.setenv("ACTIVE_BROKER", "paper")
    monkeypatch.setenv("LIVE_TRADING_ENABLED", "true")
    get_settings.cache_clear()
    try:
        # Server opened the gate, but ACTIVE_BROKER=paper and the in-app
        # toggle has never been touched -- still paper.
        assert client.get("/api/broker/status").json()["effective_broker"] == "paper"

        resp = client.post("/api/broker/mode", json={"mode": "etrade"})
        assert resp.status_code == 200
        assert resp.json()["effective_broker"] == "etrade"
        assert client.get("/api/broker/status").json()["effective_broker"] == "etrade"

        # And back to paper for testing strategies without touching the server.
        resp = client.post("/api/broker/mode", json={"mode": "paper"})
        assert resp.status_code == 200
        assert resp.json()["effective_broker"] == "paper"
    finally:
        get_settings.cache_clear()


def test_toggle_forced_back_to_paper_if_server_disables_live_trading(client, monkeypatch):
    monkeypatch.setenv("LIVE_TRADING_ENABLED", "true")
    get_settings.cache_clear()
    client.post("/api/broker/mode", json={"mode": "etrade"})
    assert client.get("/api/broker/status").json()["effective_broker"] == "etrade"

    # Server-side gate closes again (e.g. LIVE_TRADING_ENABLED unset) -- the
    # in-app toggle's already-stored "etrade" choice must not override that.
    monkeypatch.setenv("LIVE_TRADING_ENABLED", "false")
    get_settings.cache_clear()
    try:
        assert client.get("/api/broker/status").json()["effective_broker"] == "paper"
    finally:
        get_settings.cache_clear()


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


def test_stop_order_rests_pending_until_triggered(client):
    # AAPL is at 230 in mock mode; a buy-stop far above that hasn't triggered.
    resp = client.post(
        "/api/orders",
        json={
            "symbol": "AAPL", "asset_type": "equity", "side": "buy", "quantity": 1,
            "order_type": "stop", "stop_price": 500.0,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "pending"
    assert body["stop_price"] == 500.0
    assert body["time_in_force"] == "day"

    orders = client.get("/api/orders").json()["orders"]
    assert orders[0]["status"] == "pending"


def test_stop_order_already_marketable_fills_immediately(client):
    # A sell-stop whose trigger the market has already reached behaves like
    # a real broker's would: it fills right away rather than waiting.
    client.post(
        "/api/orders",
        json={"symbol": "AAPL", "asset_type": "equity", "side": "buy", "quantity": 5, "order_type": "market"},
    )
    resp = client.post(
        "/api/orders",
        json={
            "symbol": "AAPL", "asset_type": "equity", "side": "sell", "quantity": 5,
            "order_type": "stop", "stop_price": 300.0,  # AAPL at 230 <= 300 already
        },
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "filled"
    assert resp.json()["filled_price"] == 230.0


def test_stop_limit_order_via_api(client):
    resp = client.post(
        "/api/orders",
        json={
            "symbol": "AAPL", "asset_type": "equity", "side": "buy", "quantity": 1,
            "order_type": "stop_limit", "stop_price": 500.0, "limit_price": 505.0, "time_in_force": "gtc",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "pending"
    assert body["stop_price"] == 500.0
    assert body["limit_price"] == 505.0
    assert body["time_in_force"] == "gtc"


def test_trailing_stop_order_via_api(client):
    client.post(
        "/api/orders",
        json={"symbol": "AAPL", "asset_type": "equity", "side": "buy", "quantity": 2, "order_type": "market"},
    )
    resp = client.post(
        "/api/orders",
        json={
            "symbol": "AAPL", "asset_type": "equity", "side": "sell", "quantity": 2,
            "order_type": "trailing_stop", "trail_amount": 15.0,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "pending"
    assert body["trail_amount"] == 15.0
    assert body["trail_reference_price"] == 230.0  # seeded from AAPL's price at placement


def test_trailing_stop_missing_trail_field_rejected(client):
    resp = client.post(
        "/api/orders",
        json={
            "symbol": "AAPL", "asset_type": "equity", "side": "sell", "quantity": 1,
            "order_type": "trailing_stop",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "rejected"


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
