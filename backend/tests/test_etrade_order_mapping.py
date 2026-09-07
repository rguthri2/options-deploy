from app.trading.etrade_broker import _map_order_pricing
from app.trading.models import OrderRequest


def _req(**overrides):
    fields = dict(symbol="AAPL", asset_type="equity", side="buy", quantity=1, order_type="market")
    fields.update(overrides)
    return OrderRequest(**fields)


def test_market_order_mapping():
    price_type, order_term, fields = _map_order_pricing(_req())
    assert price_type == "MARKET"
    assert order_term == "GOOD_FOR_DAY"
    assert fields == {}


def test_limit_order_mapping():
    price_type, order_term, fields = _map_order_pricing(_req(order_type="limit", limit_price=101.5))
    assert price_type == "LIMIT"
    assert fields == {"limitPrice": 101.5}


def test_stop_order_mapping():
    price_type, _, fields = _map_order_pricing(_req(order_type="stop", stop_price=95.0))
    assert price_type == "STOP"
    assert fields == {"stopPrice": 95.0}


def test_stop_limit_order_mapping():
    price_type, _, fields = _map_order_pricing(
        _req(order_type="stop_limit", stop_price=95.0, limit_price=94.0)
    )
    assert price_type == "STOP_LIMIT"
    assert fields == {"limitPrice": 94.0, "stopPrice": 95.0}


def test_trailing_stop_amount_mapping():
    price_type, _, fields = _map_order_pricing(_req(order_type="trailing_stop", trail_amount=5.0))
    assert price_type == "TRAILING_STOP_CNST"
    assert fields == {"stopPrice": 5.0}


def test_trailing_stop_percent_mapping():
    price_type, _, fields = _map_order_pricing(_req(order_type="trailing_stop", trail_percent=3.0))
    assert price_type == "TRAILING_STOP_PRCT"
    assert fields == {"stopPrice": 3.0}


def test_gtc_time_in_force_mapping():
    _, order_term, _ = _map_order_pricing(_req(time_in_force="gtc"))
    assert order_term == "GOOD_TILL_CANCEL"
