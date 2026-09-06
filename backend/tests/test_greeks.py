from datetime import date, timedelta

from app.greeks import black_scholes_delta, days_to_expiration, enrich_contract
from app.models import OptionContract, OptionType, Underlying


def test_atm_call_delta_is_roughly_half():
    delta = black_scholes_delta(
        spot=100,
        strike=100,
        years_to_expiration=30 / 365,
        volatility=0.3,
        option_type=OptionType.CALL,
    )
    assert delta is not None
    assert 0.45 < delta < 0.60


def test_deep_itm_call_delta_near_one():
    delta = black_scholes_delta(
        spot=200,
        strike=100,
        years_to_expiration=30 / 365,
        volatility=0.3,
        option_type=OptionType.CALL,
    )
    assert delta > 0.95


def test_deep_otm_call_delta_near_zero():
    delta = black_scholes_delta(
        spot=50,
        strike=100,
        years_to_expiration=30 / 365,
        volatility=0.3,
        option_type=OptionType.CALL,
    )
    assert delta < 0.05


def test_put_delta_is_negative_and_call_put_parity_ish():
    call_delta = black_scholes_delta(
        spot=100, strike=100, years_to_expiration=30 / 365, volatility=0.3, option_type=OptionType.CALL
    )
    put_delta = black_scholes_delta(
        spot=100, strike=100, years_to_expiration=30 / 365, volatility=0.3, option_type=OptionType.PUT
    )
    assert put_delta < 0
    # call_delta - put_delta ~= 1 for zero dividend yield (put-call parity on delta)
    assert abs((call_delta - put_delta) - 1.0) < 0.01


def test_degenerate_inputs_return_none():
    assert black_scholes_delta(spot=0, strike=100, years_to_expiration=1, volatility=0.3, option_type=OptionType.CALL) is None
    assert black_scholes_delta(spot=100, strike=100, years_to_expiration=0, volatility=0.3, option_type=OptionType.CALL) is None
    assert black_scholes_delta(spot=100, strike=100, years_to_expiration=1, volatility=0, option_type=OptionType.CALL) is None


def test_days_to_expiration():
    today = date(2026, 1, 1)
    assert days_to_expiration(date(2026, 1, 15), as_of=today) == 14


def test_enrich_contract_sets_delta_and_dte():
    today = date(2026, 1, 1)
    contract = OptionContract(
        symbol="TEST",
        option_type=OptionType.CALL,
        strike=100,
        expiration=today + timedelta(days=30),
        bid=5.0,
        ask=5.2,
        last_price=5.1,
        open_interest=500,
        implied_volatility=0.3,
    )
    underlying = Underlying(symbol="TEST", price=100)
    enrich_contract(contract, underlying, as_of=today)
    assert contract.days_to_expiration == 30
    assert contract.delta is not None
    assert 0 < contract.delta < 1
