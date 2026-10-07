from app.technicals import average_true_range, average_volume


def _bar(h, l, c, v):
    return {"h": h, "l": l, "c": c, "v": v}


def test_average_true_range_needs_period_plus_one_bars():
    bars = [_bar(101, 99, 100, 1_000_000) for _ in range(14)]  # only 14, needs 15
    assert average_true_range(bars, period=14) is None


def test_average_true_range_known_value():
    # Flat 2-point true range every bar (high-low=2, no gaps vs prior close)
    # over 15 bars should average to exactly 2.
    bars = [_bar(101, 99, 100, 1_000_000) for _ in range(15)]
    assert average_true_range(bars, period=14) == 2.0


def test_average_true_range_picks_up_a_gap():
    bars = [_bar(101, 99, 100, 1_000_000) for _ in range(14)]
    bars.append(_bar(110, 108, 109, 1_000_000))  # gapped up from prior close 100
    # True range for the last bar is max(2, |110-100|, |108-100|) = 10, the
    # other 13 true ranges (bars 2..14) are each 2.
    expected = round((13 * 2 + 10) / 14, 4)
    assert average_true_range(bars, period=14) == expected


def test_average_volume_uses_last_period_bars_only():
    bars = [_bar(1, 1, 1, 1_000_000) for _ in range(30)]
    bars[-5]["v"] = 5_000_000  # inside the last-20 window
    bars[0]["v"] = 100_000_000  # outside the last-20 window, must be ignored
    avg = average_volume(bars, period=20)
    assert avg == (19 * 1_000_000 + 5_000_000) / 20


def test_average_volume_handles_fewer_bars_than_period():
    bars = [_bar(1, 1, 1, 2_000_000) for _ in range(5)]
    assert average_volume(bars, period=20) == 2_000_000


def test_average_volume_empty_bars_returns_none():
    assert average_volume([]) is None
