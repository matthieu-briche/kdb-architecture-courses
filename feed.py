"""Feed handler: replays simulated Hawkes sessions into the tickerplant in accelerated time.

Every --interval seconds of wall-clock time, publishes all events whose simulated
time has been reached, as one `.u.upd` call per table. Each row carries its own
`time` (wall-clock time of the event in the accelerated replay), so the tickerplant
keeps it and as-of joins see the true event order inside a batch. When a session
ends, a new one starts.

    python feed.py --speed 10
"""
import argparse
import datetime as dt
import time

import numpy as np
import pykx as kx

from config import PORTS, QUOTE_COLUMNS, SESSION_SECONDS, TRADE_COLUMNS
from hawkes import CODES, decode, simulate_session


def batch(cols, lo, hi, names, origin_ns, speed):
    """Rows [lo, hi) as a list of kdb+ vectors: time, then the schema columns.

    origin_ns is the wall-clock time of the session start, in ns since midnight.
    """
    ns = origin_ns + np.round(1e9 * cols["t"][lo:hi] / speed).astype("int64")
    out = [kx.toq(ns.astype("timedelta64[ns]"))]
    for name in names:
        values = cols[name][lo:hi]
        out.append(kx.toq(decode(name, values), kx.SymbolVector)
                   if name in CODES else kx.toq(values))
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--speed", type=float, default=10.0,
                        help="simulated seconds per wall-clock second")
    parser.add_argument("--interval", type=float, default=0.1,
                        help="seconds between published batches")
    parser.add_argument("--seed", type=int, default=None)
    args = parser.parse_args()

    rng = np.random.default_rng(args.seed)
    print(f"Feed handler -> tickerplant :{PORTS['tickerplant']}  (speed x{args.speed:g})")

    try:
        conn = kx.SyncQConnection(port=PORTS["tickerplant"], no_ctx=True)
    except kx.QError:
        raise SystemExit(f"No tickerplant on port {PORTS['tickerplant']}: start `python tick.py` "
                         "first and wait for 'Architecture running'.")
    with conn as tp:
        session_no = 0
        while True:
            session_no += 1
            session = simulate_session(rng)
            q, t = session.quotes, session.trades
            iq = it = 0
            start = time.monotonic()
            wall = dt.datetime.now()
            midnight = wall.replace(hour=0, minute=0, second=0, microsecond=0)
            origin_ns = (wall - midnight) // dt.timedelta(microseconds=1) * 1000
            print(f"session {session_no}: {q['t'].size:,} quotes, {t['t'].size:,} trades")
            while iq < q["t"].size or it < t["t"].size:
                time.sleep(args.interval)
                now = args.speed * (time.monotonic() - start)
                jq = int(np.searchsorted(q["t"], now, side="right"))
                jt = int(np.searchsorted(t["t"], now, side="right"))
                if jq > iq:
                    tp(".u.upd", "quote", batch(q, iq, jq, QUOTE_COLUMNS, origin_ns, args.speed))
                    iq = jq
                if jt > it:
                    tp(".u.upd", "trade", batch(t, it, jt, TRADE_COLUMNS, origin_ns, args.speed))
                    it = jt
                if now >= SESSION_SECONDS:
                    break


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("feed stopped")
