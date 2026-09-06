from datetime import date, timedelta

from app.models import OptionContract, OptionType, ScreeningCriteria, Underlying
from app.screener import screen_chain

TODAY = date(2026, 1, 1)
UNDERLYING = Underlying(symbol="TEST", price=100)


def make_contract(*, strike, dte, oi, iv=0.3, option_type=OptionType.CALL):
    return OptionContract(
        symbol="TEST",
        option_type=option_type,
        strike=strike,
        expiration=TODAY + timedelta(days=dte),
        bid=1.0,
        ask=1.2,
        last_price=1.1,
        open_interest=oi,
        implied_volatility=iv,
    )


def test_filters_out_low_open_interest():
    contracts = [make_contract(strike=100, dte=30, oi=50), make_contract(strike=100, dte=30, oi=500)]
    result = screen_chain(contracts, UNDERLYING, as_of=TODAY)
    assert len(result) == 1
    assert result[0].open_interest == 500


def test_filters_out_low_delta():
    # Deep OTM call at 30 days should have a low delta and get filtered out.
    contracts = [make_contract(strike=200, dte=30, oi=500), make_contract(strike=100, dte=30, oi=500)]
    result = screen_chain(contracts, UNDERLYING, as_of=TODAY)
    strikes = {c.strike for c in result}
    assert 200 not in strikes
    assert 100 in strikes


def test_filters_out_short_dated_contracts():
    contracts = [make_contract(strike=100, dte=7, oi=500), make_contract(strike=100, dte=21, oi=500)]
    result = screen_chain(contracts, UNDERLYING, as_of=TODAY)
    dtes = {c.days_to_expiration for c in result}
    assert 7 not in dtes
    assert 21 in dtes


def test_custom_criteria_overrides_defaults():
    contracts = [make_contract(strike=100, dte=30, oi=150)]
    strict = ScreeningCriteria(min_open_interest=1000, min_abs_delta=0.4, min_days_to_expiration=14)
    assert screen_chain(contracts, UNDERLYING, strict, as_of=TODAY) == []

    lenient = ScreeningCriteria(min_open_interest=100, min_abs_delta=0.4, min_days_to_expiration=14)
    assert len(screen_chain(contracts, UNDERLYING, lenient, as_of=TODAY)) == 1
