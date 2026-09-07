from datetime import date

from app.trading.models import OrderRequest


def _base(**overrides):
    fields = dict(symbol="AAPL", asset_type="equity", side="buy", quantity=1, order_type="market")
    fields.update(overrides)
    return OrderRequest(**fields)


def test_market_order_is_valid():
    assert _base().validate() is None


def test_invalid_order_type_rejected():
    assert "Invalid order_type" in _base(order_type="bogus").validate()


def test_invalid_time_in_force_rejected():
    assert "Invalid time_in_force" in _base(time_in_force="60_days").validate()


def test_limit_requires_limit_price():
    assert "limit_price" in _base(order_type="limit").validate()
    assert _base(order_type="limit", limit_price=100.0).validate() is None


def test_stop_requires_stop_price():
    assert "stop_price" in _base(order_type="stop").validate()
    assert _base(order_type="stop", stop_price=100.0).validate() is None


def test_stop_limit_requires_both_prices():
    assert _base(order_type="stop_limit", stop_price=100.0).validate() is not None
    assert _base(order_type="stop_limit", limit_price=100.0).validate() is not None
    assert _base(order_type="stop_limit", stop_price=100.0, limit_price=101.0).validate() is None


def test_trailing_stop_requires_exactly_one_trail_field():
    assert "trail_amount or trail_percent" in _base(order_type="trailing_stop").validate()
    assert _base(order_type="trailing_stop", trail_amount=5.0).validate() is None
    assert _base(order_type="trailing_stop", trail_percent=5.0).validate() is None
    both = _base(order_type="trailing_stop", trail_amount=5.0, trail_percent=5.0).validate()
    assert both is not None and "only one" in both


def test_option_order_requires_option_fields():
    assert _base(asset_type="option").validate() is not None
    assert (
        _base(asset_type="option", option_type="call", strike=100.0, expiration=date(2030, 1, 1)).validate() is None
    )


def test_negative_quantity_rejected():
    assert "Quantity" in _base(quantity=-1).validate()


def test_invalid_side_rejected():
    assert "Invalid side" in _base(side="short").validate()
