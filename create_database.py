"""Build the historical database: N business days of Hawkes-driven trades and quotes.

Layout follows kdb+tick: date-partitioned, each partition sorted by sym with the
parted attribute (written with .Q.dpft through PyKX), gzip-compressed.

    python create_database.py --days 10
"""
import argparse
import datetime as dt
import shutil

import numpy as np
import pykx as kx

from config import DB_PATH, QUOTE_COLUMNS, SESSION_OPEN_SECONDS, TRADE_COLUMNS
from hawkes import CODES, decode, simulate_session


def business_days_before(today, n):
    days, d = [], today
    while len(days) < n:
        d -= dt.timedelta(days=1)
        if d.weekday() < 5:
            days.append(d)
    return sorted(days)


def to_timespan(seconds_from_open):
    """Seconds from the open -> kdb+ timespan, 1 ms resolution."""
    ms = np.round(1e3 * (SESSION_OPEN_SECONDS + seconds_from_open)).astype("int64")
    return kx.toq(ms.astype("timedelta64[ms]").astype("timedelta64[ns]"))


def to_table(cols, names):
    data = {"time": to_timespan(cols["t"])}
    for name in names:
        values = cols[name]
        data[name] = (kx.toq(decode(name, values), kx.SymbolVector)
                      if name in CODES else kx.toq(values))
    return kx.Table(data=data)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--days", type=int, default=10, help="number of business days")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    if DB_PATH.exists():
        shutil.rmtree(DB_PATH)
    DB_PATH.mkdir(parents=True)

    rng = np.random.default_rng(args.seed)
    db = kx.DB(path=str(DB_PATH))
    gzip = kx.Compress(algo=kx.CompressionAlgorithm.gzip, level=6)

    for day in business_days_before(dt.date.today(), args.days):
        session = simulate_session(rng)
        trade = to_table(session.trades, TRADE_COLUMNS)
        quote = to_table(session.quotes, QUOTE_COLUMNS)
        partition = kx.toq(day)
        db.create(trade, "trade", partition, by_field="sym", compress=gzip, log=False)
        db.create(quote, "quote", partition, by_field="sym", compress=gzip, log=False)
        print(f"{day}  trades={len(trade):>8,}  quotes={len(quote):>8,}")

    print("\ntables:", db.tables, " partitions:", args.days)


if __name__ == "__main__":
    main()
