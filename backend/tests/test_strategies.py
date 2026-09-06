import pytest

from app.models import ScreeningCriteria
from app.providers.mock_provider import MockProvider
from app.screener import screen_chain
from app.strategies import all_strategies, get_strategy

PROVIDER = MockProvider()
CRITERIA = ScreeningCriteria()  # OI > 100, |delta| >= 0.4, DTE >= 14


@pytest.fixture(scope="module")
def screened_aapl():
    underlying = PROVIDER.get_underlying("AAPL")
    chain = PROVIDER.get_option_chain("AAPL", min_days_to_expiration=CRITERIA.min_days_to_expiration)
    return underlying, screen_chain(chain, underlying, CRITERIA)


def test_screened_contracts_all_satisfy_criteria(screened_aapl):
    _, contracts = screened_aapl
    assert contracts, "mock chain should yield at least some qualifying contracts"
    for c in contracts:
        assert c.open_interest > CRITERIA.min_open_interest
        assert abs(c.delta) >= CRITERIA.min_abs_delta
        assert c.days_to_expiration >= CRITERIA.min_days_to_expiration


def test_all_strategies_are_registered():
    keys = {s.key for s in all_strategies()}
    assert keys == {
        "covered_call",
        "cash_secured_put",
        "poor_mans_covered_call",
        "wheel",
        "bull_call_spread",
        "bear_put_spread",
        "long_call",
        "long_put",
    }


def test_covered_call_structure(screened_aapl):
    underlying, contracts = screened_aapl
    ideas = get_strategy("covered_call").scan("AAPL", underlying, contracts)
    assert ideas
    for idea in ideas:
        assert len(idea.legs) == 2
        stock_leg, call_leg = idea.legs
        assert stock_leg.contract is None and stock_leg.quantity == 100
        assert call_leg.action == "sell" and call_leg.contract.option_type.value == "call"
        assert idea.max_loss is not None and idea.max_loss > 0


def test_cash_secured_put_structure(screened_aapl):
    underlying, contracts = screened_aapl
    ideas = get_strategy("cash_secured_put").scan("AAPL", underlying, contracts)
    assert ideas
    for idea in ideas:
        assert len(idea.legs) == 1
        leg = idea.legs[0]
        assert leg.action == "sell" and leg.contract.option_type.value == "put"
        assert idea.max_profit is not None and idea.max_profit > 0


def test_wheel_produces_a_put_entry(screened_aapl):
    underlying, contracts = screened_aapl
    ideas = get_strategy("wheel").scan("AAPL", underlying, contracts)
    assert ideas
    assert ideas[0].legs[0].contract.option_type.value == "put"


def test_long_call_and_long_put(screened_aapl):
    underlying, contracts = screened_aapl
    call_ideas = get_strategy("long_call").scan("AAPL", underlying, contracts)
    put_ideas = get_strategy("long_put").scan("AAPL", underlying, contracts)
    assert call_ideas and put_ideas
    assert call_ideas[0].max_profit is None  # unlimited upside
    assert put_ideas[0].max_profit is not None and put_ideas[0].max_profit > 0


def test_bull_call_spread_is_defined_risk(screened_aapl):
    underlying, contracts = screened_aapl
    ideas = get_strategy("bull_call_spread").scan("AAPL", underlying, contracts)
    for idea in ideas:
        assert len(idea.legs) == 2
        long_leg, short_leg = idea.legs
        assert long_leg.contract.strike < short_leg.contract.strike
        assert idea.max_loss > 0 and idea.max_profit > 0
        assert idea.net_cost == idea.max_loss  # debit spread: net cost == max loss


def test_bear_put_spread_is_defined_risk(screened_aapl):
    underlying, contracts = screened_aapl
    ideas = get_strategy("bear_put_spread").scan("AAPL", underlying, contracts)
    for idea in ideas:
        assert len(idea.legs) == 2
        long_leg, short_leg = idea.legs
        assert long_leg.contract.strike > short_leg.contract.strike
        assert idea.max_loss > 0 and idea.max_profit > 0


def test_poor_mans_covered_call_uses_two_expirations(screened_aapl):
    underlying, contracts = screened_aapl
    ideas = get_strategy("poor_mans_covered_call").scan("AAPL", underlying, contracts)
    for idea in ideas:
        long_leg, short_leg = idea.legs
        assert long_leg.contract.expiration > short_leg.contract.expiration
        assert long_leg.contract.strike < short_leg.contract.strike
