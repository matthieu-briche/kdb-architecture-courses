"""Query tuning benchmarks on the historical database.

Measures, with q's own timer (`\\t:n`), how much a few classic choices matter:
  1. filter order on a date-partitioned table (date first vs sym first)
  2. attributes on an in-memory column: none vs grouped (g#) vs parted (p#)
  3. sorted attribute (s#) on a time column for range lookups

    python query_tuning.py
"""
import pykx as kx

from config import DB_PATH


def timed(label, expr, repeat=20):
    ms = kx.q("{system\"t:\",string[x],\" \",y}", repeat, kx.toq(expr, kx.CharVector)).py()
    print(f"  {ms / repeat:8.3f} ms   {label}")
    return ms / repeat


def main():
    kx.DB(path=str(DB_PATH))
    kx.q("d: last date")
    print(f"HDB: {kx.q('count date').py()} partitions, "
          f"{kx.q('count select from trade where date=d').py():,} trades on the last day\n")

    print("1. Filter order on a partitioned table (where date=..., sym=... vs reversed)")
    timed("date first, then sym", "select avg sz from trade where date=d, sym=`AAPL")
    timed("sym first, then date", "select avg sz from trade where sym=`AAPL, date=d")
    timed("date and time range first", "select avg sz from trade where date=d, time>0D12:00:00, sym=`AAPL")

    print("\n2. Attributes on the sym column of one day held in memory")
    kx.q("t: select from quote where date=d")                       # sorted by sym, p# from .Q.dpft
    kx.q("tnone: update `#sym from t")                              # no attribute
    kx.q("tg: update `g#sym from tnone")                            # grouped
    kx.q("tp: update `p#sym from tnone")                            # parted (data sorted by sym)
    timed("no attribute (linear scan)", "select from tnone where sym=`TSLA", 50)
    timed("grouped g#", "select from tg where sym=`TSLA", 50)
    timed("parted p#", "select from tp where sym=`TSLA", 50)

    print("\n3. Sorted attribute on time for a range lookup")
    kx.q("ts: select from t where sym=`AAPL")
    kx.q("ts0: update `#time from ts")
    kx.q("ts1: update `s#time from ts0")
    timed("no attribute", "select from ts0 where time within 0D12:00:00 0D12:05:00", 200)
    timed("sorted s#", "select from ts1 where time within 0D12:00:00 0D12:05:00", 200)


if __name__ == "__main__":
    main()
