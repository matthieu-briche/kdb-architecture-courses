"""Start the full tick architecture and keep it running until Ctrl-C.

    tickerplant :5010 -> RDB :5011 ;  HDB :5012 (on-disk, from create_database.py)
    tickerplant :5010 -> chained tickerplant :5013 -> real-time engine :5014
    real-time engine -> publishes `aggregate` back to the tickerplant
    gateway :5015 -> queries the real-time engine and the HDB

Everything that runs inside kdb+ processes (real-time aggregation, query APIs) is
written in q; Python only wires the processes together and runs the gateway.

    python create_database.py      # once
    python tick.py                 # terminal 1
    python feed.py                 # terminal 2
"""
import sys
import time

import pykx as kx

from config import DB_PATH, LOG_PATH, PORTS, schemas

# ---------------------------------------------------------------------------
# Real-time engine (q). Called after every update; recomputes and publishes the
# per-symbol aggregate at most once per second, back to the main tickerplant.
#   trdvol     traded notional        vwap       volume-weighted price
#   bid / ask  latest quote           spread_bps quoted spread in basis points
#   qrate      quote updates per second over the last 10 s (Hawkes intensity proxy)
# ---------------------------------------------------------------------------
RTE_POST_PROCESSOR = """{[tab;msg]
  if[not all `trade`quote in tables[]; :(::)];
  if[.z.P < @[value; `.agg.next; -0Wp]; :(::)];
  `.agg.next set .z.P + 0D00:00:01;
  if[0 = count trade; :(::)];
  now: max (exec last time from trade; exec last time from quote);
  a: 0!(select trdvol:sum px*sz, vwap:sz wavg px, maxpx:max px, minpx:min px by sym from trade)
     lj (select bid:last bid, ask:last ask by sym from quote)
     lj select qrate:(count i)%10 by sym from quote where time > now - 0D00:00:10;
  a: update time:now, qrate:0f^qrate, spread_bps:1e4*(ask-bid)%0.5*ask+bid from a;
  a: select time, sym, trdvol, vwap, maxpx, minpx, bid, ask, spread_bps, qrate from a;
  h: @[value; `.agg.h; 0Ni];
  if[null h; `.agg.h set h: hopen `::TP_PORT];
  neg[h] (".u.upd"; `aggregate; value flip a);
 }"""

RTE_APIS = {
    "count_trades": "{[s] exec count i from trade where sym=s}",
    "vwap": """{[s] select vwap:sz wavg px, volume:sum sz
                  by minute:1 xbar time.minute from trade where sym=s}""",
    "ohlc": """{[s;n] select open:first px, high:max px, low:min px, close:last px, volume:sum sz
                    by minute:n xbar time.minute from trade where sym=s}""",
    # each trade with the prevailing quote (as-of join) and its distance to the mid
    "trade_context": """{[s]
        t: aj[`sym`time; select time, sym, px, sz from trade where sym=s;
                         select time, sym, bid, ask from quote where sym=s];
        update slippage_bps:1e4*(px-mid)%mid from update mid:0.5*bid+ask from t}""",
}

# Historical APIs (q), filtering on date first so only the needed partitions are read.
# Raw columns are selected from the partitioned tables first and aggregated in memory:
# KDB-X does not implement every computed query directly on partitioned tables ('nyi).
HDB_APIS = {
    "hdb_count": """{[s;n] exec sum c from
        select c:count i by date from trade where date within (.z.d-n;.z.d-1), sym=s}""",
    # daily traded volume, VWAP and realised volatility of the 1-minute mid
    "daily_stats": """{[s;n]
        d: (.z.d-n;.z.d-1);
        tr: select date, sz, px from trade where date within d, sym=s;
        qt: select date, time, bid, ask from quote where date within d, sym=s;
        v: select trades:count i, volume:sum sz, vwap:sz wavg px by date from tr;
        m: select mid:last 0.5*bid+ask by date, minute:1 xbar time.minute from qt;
        v lj select rvol:sqrt[390]*dev 1_deltas log mid by date from m}""",
}


# ---------------------------------------------------------------------------
# Gateway APIs (Python). PyKX ships each function's source to the gateway
# process, so they must be self-contained: only `gateway` and `kx` are in scope.
# ---------------------------------------------------------------------------
def trade_count(sym, n_days):
    live = gateway.call_port('rte', 'count_trades', sym)
    if n_days > 0:
        return live + gateway.call_port('hdb', 'hdb_count', sym, n_days)
    return live


def intraday_vwap(sym):
    return gateway.call_port('rte', 'vwap', sym)


def intraday_ohlc(sym, minutes):
    return gateway.call_port('rte', 'ohlc', sym, minutes)


def trade_context(sym):
    return gateway.call_port('rte', 'trade_context', sym)


def daily_stats(sym, n_days):
    return gateway.call_port('hdb', 'daily_stats', sym, n_days)


def check_user(username, password):
    # demo access control: a single allowed user, no password check
    return bool(username == 'analyst')


def start():
    """Start every process; returns them in stop order (see `stop`)."""
    if not DB_PATH.exists():
        sys.exit("No historical database found: run `python create_database.py` first.")
    LOG_PATH.mkdir(exist_ok=True)

    basic = kx.tick.BASIC(
        tables=schemas(),
        ports={k: PORTS[k] for k in ("tickerplant", "rdb", "hdb")},
        log_directory=str(LOG_PATH),
        database=str(DB_PATH),
    )
    try:
        basic.start()
    except kx.QError as err:
        sys.exit(f"Could not start the tickerplant ({err}).\nIf the log mentions pykx.q, run once:\n"
                 '  python -c "import pykx; pykx.install_into_QHOME()"')

    chained = kx.tick.TICK(port=PORTS["chained_tp"], chained=True)
    chained.start({"tickerplant": f"localhost:{PORTS['tickerplant']}"})

    rte = kx.tick.RTP(port=PORTS["rte"], subscriptions=["trade", "quote"], vanilla=False)
    rte.post_processor(kx.q(RTE_POST_PROCESSOR.replace("TP_PORT", str(PORTS["tickerplant"]))))
    rte.start({"tickerplant": f"localhost:{PORTS['chained_tp']}"})
    for name, code in RTE_APIS.items():
        rte.register_api(name, kx.q(code))
    for name, code in HDB_APIS.items():
        basic.hdb.register_api(name, kx.q(code))

    gateway = kx.tick.GATEWAY(
        port=PORTS["gateway"],
        libraries={"kx": "pykx"},
        apis={f.__name__: f for f in
              (trade_count, intraday_vwap, intraday_ohlc, trade_context, daily_stats)},
        connections={"rte": f"localhost:{PORTS['rte']}", "hdb": f"localhost:{PORTS['hdb']}"},
        connection_validator=check_user,
    )
    gateway.start()
    return gateway, rte, chained, basic


def stop(processes):
    for process in processes:
        try:
            process.stop()
        except Exception as err:  # keep stopping the others
            print(f"could not stop {process}: {err}")


def main():
    processes = start()
    print("\nArchitecture running:",
          ", ".join(f"{k} :{v}" for k, v in PORTS.items()),
          "\nStart the feed with `python feed.py`. Ctrl-C to stop.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nstopping ...")
    finally:
        stop(processes)


if __name__ == "__main__":
    main()
