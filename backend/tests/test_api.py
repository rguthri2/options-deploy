def test_unauthenticated_requests_are_rejected(fresh_db):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as anon:
        # Screener/research endpoints are public (the public research site uses
        # them); only the trading/account endpoints require the admin login.
        assert anon.get("/api/strategies").status_code == 200
        assert anon.get("/api/screen", params={"ticker": "AAPL"}).status_code == 200
        assert anon.get("/api/scan", params={"tickers": "AAPL"}).status_code == 200
        assert anon.get("/api/account").status_code == 401


def test_health_is_public(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["data_provider"] == "mock"


def test_login_wrong_password_rejected(fresh_db):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as anon:
        resp = anon.post("/api/auth/login", json={"username": "testadmin", "password": "wrong"})
        assert resp.status_code == 401


def test_list_strategies(client):
    resp = client.get("/api/strategies")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["strategies"]) == 8
    assert all("trader_attribution" in s for s in body["strategies"])


def test_screen_endpoint(client):
    resp = client.get("/api/screen", params={"ticker": "AAPL"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["underlying"]["symbol"] == "AAPL"
    assert body["contracts"]
    for c in body["contracts"]:
        assert c["open_interest"] > 100
        assert abs(c["delta"]) >= 0.4
        assert c["days_to_expiration"] >= 14


def test_screen_unknown_symbol_in_mock_mode_returns_400(client):
    resp = client.get("/api/screen", params={"ticker": "NOTAREALTICKERXYZ"})
    assert resp.status_code == 400


def test_scan_single_strategy(client):
    resp = client.get("/api/scan", params={"tickers": "AAPL", "strategy": "covered_call"})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["results"]) == 1
    result = body["results"][0]
    assert result["symbol"] == "AAPL"
    assert result["ideas"]
    assert all(i["strategy_key"] == "covered_call" for i in result["ideas"])


def test_scan_all_strategies_multiple_tickers(client):
    resp = client.get("/api/scan", params={"tickers": "AAPL,MSFT", "strategy": "all"})
    assert resp.status_code == 200
    body = resp.json()
    assert {r["symbol"] for r in body["results"]} == {"AAPL", "MSFT"}
    for result in body["results"]:
        assert result["ideas"]


def test_scan_unknown_strategy_404(client):
    resp = client.get("/api/scan", params={"tickers": "AAPL", "strategy": "not_a_strategy"})
    assert resp.status_code == 404


def test_scan_custom_criteria_tightens_results(client):
    loose = client.get("/api/scan", params={"tickers": "AAPL", "strategy": "cash_secured_put"}).json()
    strict = client.get(
        "/api/scan",
        params={"tickers": "AAPL", "strategy": "cash_secured_put", "min_delta": 0.9},
    ).json()
    assert len(strict["results"][0]["ideas"]) <= len(loose["results"][0]["ideas"])


# --- Public market data (news / watchlist quotes / research / level 2) ---------


def test_public_quote_is_public(fresh_db):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as anon:
        resp = anon.get("/api/public/quote", params={"symbol": "AAPL"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["symbol"] == "AAPL"
        assert body["price"] > 0


def test_public_history_valid_ranges(client):
    for range_key in ["1D", "5D", "1W", "1M", "1Y"]:
        resp = client.get("/api/public/history", params={"symbol": "AAPL", "range": range_key})
        assert resp.status_code == 200, range_key
        body = resp.json()
        assert body["range"] == range_key
        assert len(body["points"]) > 0


def test_public_history_rejects_bad_range(client):
    resp = client.get("/api/public/history", params={"symbol": "AAPL", "range": "3Y"})
    assert resp.status_code == 400


def test_public_news(client):
    resp = client.get("/api/public/news", params={"symbols": "AAPL,MSFT"})
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert items
    assert {i["symbol"] for i in items} <= {"AAPL", "MSFT"}


def test_public_level2_is_labeled_simulated(client):
    resp = client.get("/api/public/level2", params={"symbol": "AAPL"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["simulated"] is True
    assert "simulated" in body["disclaimer"].lower()
    assert len(body["bids"]) == 10
    assert len(body["asks"]) == 10
    assert body["bids"][0]["price"] < body["asks"][0]["price"]
