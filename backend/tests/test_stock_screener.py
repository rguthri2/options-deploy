from app.stock_screener import StockScreenCriteria, filter_and_rank, passes


def _quote(**overrides):
    base = {
        "symbol": "TEST",
        "price": 100.0,
        "volume": 1_000_000,
        "change_percent": 0.0,
        "market_cap": 5e11,
    }
    base.update(overrides)
    return base


def test_passes_default_criteria_accepts_everything():
    assert passes(_quote(), StockScreenCriteria())


def test_passes_rejects_below_min_price():
    assert not passes(_quote(price=10.0), StockScreenCriteria(min_price=50.0))


def test_passes_rejects_above_max_price():
    assert not passes(_quote(price=200.0), StockScreenCriteria(max_price=150.0))


def test_passes_rejects_below_min_volume():
    assert not passes(_quote(volume=500), StockScreenCriteria(min_volume=1000))


def test_passes_market_cap_none_fails_when_threshold_set():
    assert not passes(_quote(market_cap=None), StockScreenCriteria(min_market_cap=1))


def test_passes_market_cap_none_ok_when_no_threshold():
    assert passes(_quote(market_cap=None), StockScreenCriteria())


def test_passes_gainers_direction():
    criteria = StockScreenCriteria(direction="gainers", min_change_pct=2.0)
    assert passes(_quote(change_percent=3.0), criteria)
    assert not passes(_quote(change_percent=-3.0), criteria)
    assert not passes(_quote(change_percent=1.0), criteria)


def test_passes_losers_direction():
    criteria = StockScreenCriteria(direction="losers", min_change_pct=2.0)
    assert passes(_quote(change_percent=-3.0), criteria)
    assert not passes(_quote(change_percent=3.0), criteria)
    assert not passes(_quote(change_percent=-1.0), criteria)


def test_passes_either_direction_uses_magnitude():
    criteria = StockScreenCriteria(direction="either", min_change_pct=2.0)
    assert passes(_quote(change_percent=3.0), criteria)
    assert passes(_quote(change_percent=-3.0), criteria)
    assert not passes(_quote(change_percent=1.0), criteria)


def test_filter_and_rank_sorts_by_abs_change_desc_and_caps_limit():
    quotes = [
        _quote(symbol="A", change_percent=1.0),
        _quote(symbol="B", change_percent=-5.0),
        _quote(symbol="C", change_percent=2.5),
    ]
    result = filter_and_rank(quotes, StockScreenCriteria(limit=2))
    assert [q["symbol"] for q in result] == ["B", "C"]
