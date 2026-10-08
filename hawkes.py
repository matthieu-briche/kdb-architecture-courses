"""Hawkes-driven market data generator (NumPy only, no kdb+ needed).

Event times follow an exponential Hawkes process simulated through its branching
(cluster) representation: Poisson(mu*T) immigrants, then each event has
Poisson(alpha/beta) children delayed by Exp(beta), generation after generation.
Every event is a quote update; a fraction of them also prints a trade at the
prevailing bid or ask. Same model as the kdb+/q project kdb-hawkes-simulation-one-day.

`sym` and `exchange` are stored as integer codes into SYM_NAMES / EXCHANGES
(large NumPy string arrays are slow, and can crash when PyKX is loaded).
"""
from dataclasses import dataclass

import numpy as np

from config import EXCHANGES, SESSION_SECONDS, SYMBOLS, TRADE_PROBABILITY

SYM_NAMES = list(SYMBOLS)
CODES = {"sym": SYM_NAMES, "exchange": EXCHANGES}


def decode(name, codes):
    """Integer codes of column `name` -> list of names (Python str)."""
    return np.array(CODES[name], dtype=object)[codes].tolist()


def hawkes_times(mu, alpha, beta, T, rng):
    """Sorted event times in [0, T) of an exponential Hawkes process."""
    n = alpha / beta
    if n >= 1:
        raise ValueError(f"non-stationary process: alpha/beta = {n:.3f} >= 1")
    generation = rng.uniform(0.0, T, rng.poisson(mu * T))
    events = [generation]
    while generation.size:
        parents = np.repeat(generation, rng.poisson(n, generation.size))
        children = parents + rng.exponential(1.0 / beta, parents.size)
        generation = children[children < T]
        events.append(generation)
    return np.sort(np.concatenate(events))


@dataclass
class Session:
    """Column arrays for one simulated session, sorted by time (seconds from the open)."""
    quotes: dict
    trades: dict


def simulate_session(rng, T=SESSION_SECONDS, symbols=SYMBOLS,
                     trade_probability=TRADE_PROBABILITY):
    quote_parts, trade_parts = [], []
    for code, p in enumerate(symbols.values()):
        t = hawkes_times(p["mu"], p["alpha"], p["beta"], T, rng)
        k = t.size
        # mid price: geometric random walk on the event clock, in integer cents
        mid = np.floor(100 * p["p0"] * np.exp(np.cumsum(p["sigma"] * rng.standard_normal(k))))
        spread = rng.integers(1, 4, k)                      # 1 to 3 cents
        bid = mid / 100
        ask = (mid + spread) / 100
        quote_parts.append(dict(
            t=t, sym=np.full(k, code), exchange=rng.integers(0, len(EXCHANGES), k),
            bid=bid, ask=ask,
            bidsz=100 * rng.integers(1, 11, k), asksz=100 * rng.integers(1, 11, k)))

        is_trade = rng.random(k) < trade_probability
        m = int(is_trade.sum())
        buy = rng.random(m) < 0.5                            # buyer lifts the ask, seller hits the bid
        trade_parts.append(dict(
            t=t[is_trade], sym=np.full(m, code), exchange=rng.integers(0, len(EXCHANGES), m),
            sz=100 * rng.integers(1, 6, m),
            px=np.where(buy, ask[is_trade], bid[is_trade])))

    return Session(quotes=_merge(quote_parts), trades=_merge(trade_parts))


def _merge(parts):
    cols = {c: np.concatenate([p[c] for p in parts]) for c in parts[0]}
    order = np.argsort(cols["t"], kind="stable")
    return {c: v[order] for c, v in cols.items()}
