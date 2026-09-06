import os

os.environ.setdefault("DATA_PROVIDER", "mock")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

client = TestClient(app)


def test_health():
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["data_provider"] == "mock"


def test_list_strategies():
    resp = client.get("/api/strategies")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["strategies"]) == 8
    assert all("trader_attribution" in s for s in body["strategies"])


def test_screen_endpoint():
    resp = client.get("/api/screen", params={"ticker": "AAPL"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["underlying"]["symbol"] == "AAPL"
    assert body["contracts"]
    for c in body["contracts"]:
        assert c["open_interest"] > 100
        assert abs(c["delta"]) >= 0.4
        assert c["days_to_expiration"] >= 14


def test_screen_unknown_symbol_in_mock_mode_returns_400():
    resp = client.get("/api/screen", params={"ticker": "NOTAREALTICKERXYZ"})
    assert resp.status_code == 400


def test_scan_single_strategy():
    resp = client.get("/api/scan", params={"tickers": "AAPL", "strategy": "covered_call"})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["results"]) == 1
    result = body["results"][0]
    assert result["symbol"] == "AAPL"
    assert result["ideas"]
    assert all(i["strategy_key"] == "covered_call" for i in result["ideas"])


def test_scan_all_strategies_multiple_tickers():
    resp = client.get("/api/scan", params={"tickers": "AAPL,MSFT", "strategy": "all"})
    assert resp.status_code == 200
    body = resp.json()
    assert {r["symbol"] for r in body["results"]} == {"AAPL", "MSFT"}
    for result in body["results"]:
        assert result["ideas"]


def test_scan_unknown_strategy_404():
    resp = client.get("/api/scan", params={"tickers": "AAPL", "strategy": "not_a_strategy"})
    assert resp.status_code == 404


def test_scan_custom_criteria_tightens_results():
    loose = client.get("/api/scan", params={"tickers": "AAPL", "strategy": "cash_secured_put"}).json()
    strict = client.get(
        "/api/scan",
        params={"tickers": "AAPL", "strategy": "cash_secured_put", "min_delta": 0.9},
    ).json()
    assert len(strict["results"][0]["ideas"]) <= len(loose["results"][0]["ideas"])
