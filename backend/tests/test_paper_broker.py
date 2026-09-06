from datetime import date

import pytest

from app.providers.mock_provider import MockProvider
from app.trading.paper_broker import PaperBroker
from app.trading.models import OrderRequest


@pytest.fixture
def broker(fresh_db):
    return PaperBroker(provider=MockProvider())


def test_market_buy_fills_and_debits_cash(broker):
    result = broker.place_order(
        OrderRequest(symbol="AAPL", asset_type="equity", side="buy", quantity=10, order_type="market")
    )
    assert result.status == "filled"
    assert result.filled_price == 230.0  # MockProvider's fixed AAPL price
    account = broker.get_account()
    assert account.cash_balance == 100000.0 - 2300.0
    assert len(account.positions) == 1
    assert account.positions[0].quantity == 10


def test_sell_more_than_held_is_rejected(broker):
    broker.place_order(
        OrderRequest(symbol="AAPL", asset_type="equity", side="buy", quantity=5, order_type="market")
    )
    result = broker.place_order(
        OrderRequest(symbol="AAPL", asset_type="equity", side="sell", quantity=100, order_type="market")
    )
    assert result.status == "rejected"
    assert "Insufficient position" in result.rejection_reason
    # Cash and position should be unaffected by the rejected order.
    account = broker.get_account()
    assert account.cash_balance == 100000.0 - 1150.0
    assert account.positions[0].quantity == 5


def test_sell_closes_position_and_credits_cash(broker):
    broker.place_order(
        OrderRequest(symbol="AAPL", asset_type="equity", side="buy", quantity=5, order_type="market")
    )
    result = broker.place_order(
        OrderRequest(symbol="AAPL", asset_type="equity", side="sell", quantity=5, order_type="market")
    )
    assert result.status == "filled"
    account = broker.get_account()
    assert account.cash_balance == 100000.0
    assert account.positions == []


def test_buy_exceeding_cash_is_rejected(broker):
    result = broker.place_order(
        OrderRequest(symbol="AAPL", asset_type="equity", side="buy", quantity=1_000_000, order_type="market")
    )
    assert result.status == "rejected"
    assert "Insufficient paper cash" in result.rejection_reason


def test_non_marketable_limit_buy_is_rejected(broker):
    # AAPL trades at 230; a limit buy well below that is not marketable.
    result = broker.place_order(
        OrderRequest(
            symbol="AAPL", asset_type="equity", side="buy", quantity=1, order_type="limit", limit_price=50.0
        )
    )
    assert result.status == "rejected"
    assert "not marketable" in result.rejection_reason


def test_marketable_limit_buy_fills_at_limit_price(broker):
    result = broker.place_order(
        OrderRequest(
            symbol="AAPL", asset_type="equity", side="buy", quantity=1, order_type="limit", limit_price=500.0
        )
    )
    assert result.status == "filled"
    assert result.filled_price == 500.0


def test_invalid_order_is_rejected_without_side_effects(broker):
    result = broker.place_order(
        OrderRequest(symbol="AAPL", asset_type="equity", side="buy", quantity=-5, order_type="market")
    )
    assert result.status == "rejected"
    assert broker.get_account().cash_balance == 100000.0


def test_option_order_fills_against_matching_contract(broker):
    provider = MockProvider()
    chain = provider.get_option_chain("AAPL", min_days_to_expiration=14)
    contract = next(c for c in chain if c.option_type.value == "call")
    result = broker.place_order(
        OrderRequest(
            symbol="AAPL",
            asset_type="option",
            side="buy",
            quantity=1,
            order_type="market",
            option_type="call",
            strike=contract.strike,
            expiration=contract.expiration,
        )
    )
    assert result.status == "filled"
    assert result.filled_price == contract.mid_price
    account = broker.get_account()
    assert account.cash_balance == pytest.approx(100000.0 - contract.mid_price * 100)


def test_unknown_option_contract_is_rejected(broker):
    result = broker.place_order(
        OrderRequest(
            symbol="AAPL",
            asset_type="option",
            side="buy",
            quantity=1,
            order_type="market",
            option_type="call",
            strike=999999.0,
            expiration=date(2099, 1, 1),
        )
    )
    assert result.status == "rejected"
    assert "No matching option contract" in result.rejection_reason


def test_cancel_only_allowed_on_pending_orders(broker):
    result = broker.place_order(
        OrderRequest(symbol="AAPL", asset_type="equity", side="buy", quantity=1, order_type="market")
    )
    assert result.status == "filled"
    with pytest.raises(Exception):
        broker.cancel_order(result.id)


def test_list_orders_returns_all_orders_newest_first(broker):
    broker.place_order(OrderRequest(symbol="AAPL", asset_type="equity", side="buy", quantity=1, order_type="market"))
    broker.place_order(OrderRequest(symbol="MSFT", asset_type="equity", side="buy", quantity=1, order_type="market"))
    orders = broker.list_orders()
    assert len(orders) == 2
    assert orders[0].symbol == "MSFT"  # most recent first
    assert orders[1].symbol == "AAPL"
