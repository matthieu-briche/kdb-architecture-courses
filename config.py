"""Shared settings: ports, symbols, Hawkes parameters and table schemas."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "database"
LOG_PATH = ROOT / "logs"

PORTS = {
    "tickerplant": 5010,
    "rdb": 5011,
    "hdb": 5012,
    "chained_tp": 5013,
    "rte": 5014,
    "gateway": 5015,
}

# Exponential Hawkes parameters per symbol (time in seconds).
# Branching ratio n = alpha / beta < 1; mean event rate = mu / (1 - n).
# p0 is the opening mid price, sigma the log-return per event.
SYMBOLS = {
    "AAPL": dict(mu=1.0, alpha=40.0, beta=50.0, p0=150.0, sigma=1e-4),
    "MSFT": dict(mu=0.8, alpha=35.0, beta=50.0, p0=300.0, sigma=1e-4),
    "GOOG": dict(mu=0.5, alpha=30.0, beta=50.0, p0=140.0, sigma=1e-4),
    "AMZN": dict(mu=0.6, alpha=35.0, beta=50.0, p0=130.0, sigma=1e-4),
    "TSLA": dict(mu=1.2, alpha=45.0, beta=50.0, p0=250.0, sigma=2e-4),
}
EXCHANGES = ["NYSE", "NASDAQ", "BATS", "IEX"]

SESSION_OPEN_SECONDS = 9.5 * 3600      # 09:30
SESSION_SECONDS = 6.5 * 3600           # 09:30 - 16:00
TRADE_PROBABILITY = 0.2                # share of quote updates that also print a trade

# Column order of the published messages (time is added by the tickerplant)
TRADE_COLUMNS = ["sym", "exchange", "sz", "px"]
QUOTE_COLUMNS = ["sym", "exchange", "bid", "ask", "bidsz", "asksz"]


def schemas():
    """kdb+ table schemas (built lazily so that importing config does not need PyKX)."""
    import pykx as kx

    trade = kx.schema.builder({
        "time": kx.TimespanAtom, "sym": kx.SymbolAtom, "exchange": kx.SymbolAtom,
        "sz": kx.LongAtom, "px": kx.FloatAtom})
    quote = kx.schema.builder({
        "time": kx.TimespanAtom, "sym": kx.SymbolAtom, "exchange": kx.SymbolAtom,
        "bid": kx.FloatAtom, "ask": kx.FloatAtom, "bidsz": kx.LongAtom, "asksz": kx.LongAtom})
    aggregate = kx.schema.builder({
        "time": kx.TimespanAtom, "sym": kx.SymbolAtom,
        "trdvol": kx.FloatAtom, "vwap": kx.FloatAtom, "maxpx": kx.FloatAtom, "minpx": kx.FloatAtom,
        "bid": kx.FloatAtom, "ask": kx.FloatAtom, "spread_bps": kx.FloatAtom, "qrate": kx.FloatAtom})
    return {"trade": trade, "quote": quote, "aggregate": aggregate}
