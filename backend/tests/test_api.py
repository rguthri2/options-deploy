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


def test_public_screen_stocks_default_ranks_by_abs_change(client):
    resp = client.get("/api/public/screen-stocks")
    assert resp.status_code == 200
    body = resp.json()
    symbols = [s["symbol"] for s in body["stocks"]]
    assert symbols[0] == "JPM"  # -1.71% is the largest mover in the mock universe
    changes = [abs(s["change_percent"]) for s in body["stocks"]]
    assert changes == sorted(changes, reverse=True)


def test_public_screen_stocks_gainers_direction(client):
    resp = client.get("/api/public/screen-stocks", params={"direction": "gainers", "min_change_pct": 1.0})
    assert resp.status_code == 200
    stocks = resp.json()["stocks"]
    assert [s["symbol"] for s in stocks] == ["NVDA"]
    assert all(s["change_percent"] >= 1.0 for s in stocks)


def test_public_screen_stocks_losers_direction(client):
    resp = client.get("/api/public/screen-stocks", params={"direction": "losers", "min_change_pct": 1.5})
    assert resp.status_code == 200
    symbols = {s["symbol"] for s in resp.json()["stocks"]}
    assert symbols == {"JPM", "AMD"}


def test_public_screen_stocks_min_market_cap_excludes_unknown(client):
    resp = client.get("/api/public/screen-stocks", params={"min_market_cap": 1e12})
    assert resp.status_code == 200
    symbols = {s["symbol"] for s in resp.json()["stocks"]}
    assert symbols == {"AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META"}
    assert "SPY" not in symbols  # ETF, no market cap in the mock data
    assert "TSLA" not in symbols  # below the 1e12 threshold


def test_public_screen_stocks_price_range(client):
    resp = client.get("/api/public/screen-stocks", params={"min_price": 300})
    assert resp.status_code == 200
    symbols = {s["symbol"] for s in resp.json()["stocks"]}
    assert symbols == {"META", "MSFT", "NFLX", "SPY"}


def test_public_screen_stocks_limit(client):
    resp = client.get("/api/public/screen-stocks", params={"limit": 3})
    assert resp.status_code == 200
    stocks = resp.json()["stocks"]
    assert len(stocks) == 3
    assert [s["symbol"] for s in stocks] == ["JPM", "AMD", "NVDA"]


def test_public_screen_stocks_rejects_bad_direction(client):
    resp = client.get("/api/public/screen-stocks", params={"direction": "sideways"})
    assert resp.status_code == 400


def test_public_screen_stocks_rejects_max_less_than_min_price(client):
    resp = client.get("/api/public/screen-stocks", params={"min_price": 100, "max_price": 50})
    assert resp.status_code == 400


def test_public_level2_is_labeled_simulated(client):
    resp = client.get("/api/public/level2", params={"symbol": "AAPL"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["simulated"] is True
    assert "simulated" in body["disclaimer"].lower()
    assert len(body["bids"]) == 10
    assert len(body["asks"]) == 10
    assert body["bids"][0]["price"] < body["asks"][0]["price"]
