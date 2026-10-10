"""Tests of the Hawkes market data generator (NumPy only, no kdb+ licence needed)."""
import numpy as np
import pytest

from config import EXCHANGES, SYMBOLS
from hawkes import decode, hawkes_times, simulate_session

MU, ALPHA, BETA = 1.0, 40.0, 50.0          # branching ratio n = 0.8
N = ALPHA / BETA


@pytest.fixture(scope="module")
def long_path():
    return hawkes_times(MU, ALPHA, BETA, T=20_000.0, rng=np.random.default_rng(0))


def test_rejects_non_stationary_parameters():
    with pytest.raises(ValueError, match="non-stationary"):
        hawkes_times(1.0, 50.0, 50.0, 10.0, np.random.default_rng(0))


def test_times_sorted_and_inside_window(long_path):
    assert np.all(np.diff(long_path) >= 0)
    assert long_path.min() >= 0 and long_path.max() < 20_000.0


def test_mean_rate_matches_theory(long_path):
    # stationary rate mu / (1 - n) = 5 events/s; count std is about 1.6 % here
    rate = long_path.size / 20_000.0
    assert rate == pytest.approx(MU / (1 - N), rel=0.05)


def test_fano_factor_matches_theory(long_path):
    # windows much longer than the 20 ms memory: var/mean -> 1 / (1 - n)^2 = 25
    counts = np.histogram(long_path, bins=np.arange(0.0, 20_000.0 + 1, 10.0))[0]
    fano = counts.var() / counts.mean()
    assert fano == pytest.approx(1 / (1 - N) ** 2, rel=0.25)
    assert fano > 5          # far from a Poisson process (Fano = 1)


def test_reproducible_with_seed():
    a = hawkes_times(MU, ALPHA, BETA, 100.0, np.random.default_rng(7))
    b = hawkes_times(MU, ALPHA, BETA, 100.0, np.random.default_rng(7))
    np.testing.assert_array_equal(a, b)


@pytest.fixture(scope="module")
def session():
    return simulate_session(np.random.default_rng(1), T=600.0)


def test_session_columns_aligned_and_time_sorted(session):
    for table in (session.quotes, session.trades):
        sizes = {v.size for v in table.values()}
        assert len(sizes) == 1
        assert np.all(np.diff(table["t"]) >= 0)


def test_quotes_are_valid(session):
    q = session.quotes
    assert np.all(q["ask"] > q["bid"])
    spread_cents = np.round(100 * (q["ask"] - q["bid"]))
    assert set(np.unique(spread_cents)) <= {1.0, 2.0, 3.0}
    assert np.all(q["bidsz"] % 100 == 0) and np.all(q["asksz"] % 100 == 0)
    assert set(np.unique(q["sym"])) == set(range(len(SYMBOLS)))


def test_trades_print_at_prevailing_bid_or_ask(session):
    q, t = session.quotes, session.trades
    for code in range(len(SYMBOLS)):
        qs, ts = q["sym"] == code, t["sym"] == code
        qt, tt = q["t"][qs], t["t"][ts]
        idx = np.searchsorted(qt, tt)                  # trades share their quote's timestamp
        np.testing.assert_array_equal(qt[idx], tt)
        px = t["px"][ts]
        assert np.all((px == q["bid"][qs][idx]) | (px == q["ask"][qs][idx]))


def test_trade_share_close_to_probability(session):
    assert session.trades["t"].size / session.quotes["t"].size == pytest.approx(0.2, abs=0.02)


def test_decode():
    assert decode("sym", np.array([0, 4])) == ["AAPL", "TSLA"]
    assert decode("exchange", np.arange(len(EXCHANGES))) == EXCHANGES
