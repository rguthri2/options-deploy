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


# --- Stop / stop-limit / trailing-stop -------------------------------------


class _MovablePriceProvider(MockProvider):
    """MockProvider's ticker prices are static, so stop/trailing-stop logic
    (which depends on the price actually moving between checks) needs a way
    to simulate that -- this overrides the AAPL quote with whatever price
    the test sets, leaving every other symbol untouched."""

    def __init__(self):
        super().__init__()
        self.price_override: dict = {}

    def get_underlying(self, symbol: str):
        underlying = super().get_underlying(symbol)
        if symbol.upper() in self.price_override:
            underlying.price = self.price_override[symbol.upper()]
        return underlying


@pytest.fixture
def movable_broker(fresh_db):
    provider = _MovablePriceProvider()
    return PaperBroker(provider=provider), provider


def test_sell_stop_rests_until_price_falls_to_it(movable_broker):
    broker, provider = movable_broker
    broker.place_order(OrderRequest(symbol="AAPL", asset_type="equity", side="buy", quantity=10, order_type="market"))

    result = broker.place_order(
        OrderRequest(symbol="AAPL", asset_type="equity", side="sell", quantity=10, order_type="stop", stop_price=225.0)
    )
    assert result.status == "pending"  # AAPL is at 230; 225 hasn't been reached

    provider.price_override["AAPL"] = 220.0
    broker.check_pending_orders()
    order = broker.list_orders()[0]
    assert order.status == "filled"
    assert order.filled_price == 220.0


def test_buy_stop_triggers_on_price_rising_through_it(movable_broker):
    broker, provider = movable_broker
    result = broker.place_order(
        OrderRequest(symbol="AAPL", asset_type="equity", side="buy", quantity=1, order_type="stop", stop_price=235.0)
    )
    assert result.status == "pending"  # AAPL is at 230; hasn't risen to 235 yet

    provider.price_override["AAPL"] = 240.0
    broker.check_pending_orders()
    order = broker.list_orders()[0]
    assert order.status == "filled"
    assert order.filled_price == 240.0


def test_stop_limit_waits_for_marketable_limit_after_triggering(movable_broker):
    broker, provider = movable_broker
    broker.place_order(
        OrderRequest(
            symbol="AAPL", asset_type="equity", side="buy", quantity=1,
            order_type="stop_limit", stop_price=235.0, limit_price=236.0,
        )
    )

    # Crosses the stop, but the limit isn't marketable yet at this price.
    provider.price_override["AAPL"] = 237.0
    broker.check_pending_orders()
    order = broker.list_orders()[0]
    assert order.status == "pending"

    # Price settles back under the limit -- now fillable at the limit price.
    provider.price_override["AAPL"] = 235.5
    broker.check_pending_orders()
    order = broker.list_orders()[0]
    assert order.status == "filled"
    assert order.filled_price == 236.0


def test_trailing_stop_sell_ratchets_up_and_triggers_on_pullback(movable_broker):
    broker, provider = movable_broker
    broker.place_order(OrderRequest(symbol="AAPL", asset_type="equity", side="buy", quantity=10, order_type="market"))
    broker.place_order(
        OrderRequest(
            symbol="AAPL", asset_type="equity", side="sell", quantity=10,
            order_type="trailing_stop", trail_amount=10.0,
        )
    )

    # Price rallies -- the trail should follow it up (reference 230 -> 250),
    # so the effective stop (250 - 10 = 240) is nowhere near triggered.
    provider.price_override["AAPL"] = 250.0
    broker.check_pending_orders()
    order = broker.list_orders()[0]
    assert order.status == "pending"
    assert order.trail_reference_price == 250.0

    # A pullback that doesn't cross the trailed stop must not trigger, and
    # must not drag the reference back down either.
    provider.price_override["AAPL"] = 245.0
    broker.check_pending_orders()
    order = broker.list_orders()[0]
    assert order.status == "pending"
    assert order.trail_reference_price == 250.0

    # Now it crosses the trailed stop (240) and fills at the market price.
    provider.price_override["AAPL"] = 238.0
    broker.check_pending_orders()
    order = broker.list_orders()[0]
    assert order.status == "filled"
    assert order.filled_price == 238.0


def test_trailing_stop_percent_variant(movable_broker):
    broker, provider = movable_broker
    broker.place_order(OrderRequest(symbol="AAPL", asset_type="equity", side="buy", quantity=1, order_type="market"))
    broker.place_order(
        OrderRequest(
            symbol="AAPL", asset_type="equity", side="sell", quantity=1,
            order_type="trailing_stop", trail_percent=10.0,  # stop = reference * 0.90
        )
    )

    # Ratchet the reference up to 300 first (placement price was 230, and
    # the reference never moves down on its own -- see the ratchet test
    # above) so the 10% trail level lands at 270.
    provider.price_override["AAPL"] = 300.0
    broker.check_pending_orders()
    assert broker.list_orders()[0].status == "pending"

    provider.price_override["AAPL"] = 265.0  # below the 270 stop
    broker.check_pending_orders()
    order = broker.list_orders()[0]
    assert order.status == "filled"
    assert order.filled_price == 265.0


def test_check_pending_orders_is_a_safe_no_op_with_nothing_pending(broker):
    broker.check_pending_orders()  # must not raise
