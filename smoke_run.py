"""End-to-end smoke run: start the architecture, stream for a while, query every API.

Prints the results and writes them to docs/sample_run.txt, so the repository
carries a real capture of a run (regenerate it after changing the code).

    python create_database.py --days 10   # once
    python smoke_run.py --seconds 20
"""
import argparse
import contextlib
import datetime as dt
import io
import platform
import subprocess
import sys
import time

import pykx as kx

import tick
from config import PORTS, ROOT

OUT = ROOT / "docs" / "sample_run.txt"

QUERIES = [
    ("trade_count", "TSLA", 5),
    ("intraday_vwap", "AAPL"),
    ("intraday_ohlc", "AAPL", 1),
    ("trade_context", "MSFT"),
    ("daily_stats", "MSFT", 10),
]


def section(title):
    print(f"\n=== {title}")


def run(seconds, speed):
    section("environment")
    print(f"date {dt.datetime.now():%Y-%m-%d %H:%M}  python {platform.python_version()}  "
          f"pykx {kx.__version__}  {platform.system()} {platform.machine()}")

    processes = tick.start()
    feed = subprocess.Popen([sys.executable, "feed.py", "--speed", str(speed), "--seed", "7"],
                            cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        time.sleep(seconds)
        with kx.SyncQConnection(port=PORTS["rdb"], no_ctx=True) as rdb:
            section(f"RDB after {seconds} s of feed at x{speed:g}")
            print(rdb("([] table:`trade`quote`aggregate; rows:count each (trade;quote;aggregate))"))
            section("last aggregate row per symbol (published by the q RTE, once per second)")
            print(rdb("0!select by sym from aggregate"))
        with kx.SyncQConnection(port=PORTS["gateway"], username="analyst", no_ctx=True) as gw:
            for name, *args in QUERIES:
                section(f"gateway {name}{tuple(args)}")
                print(gw(name, *args))
    finally:
        feed.terminate()
        section("feed handler output")
        print(feed.communicate(timeout=10)[0].strip())
        tick.stop(processes)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seconds", type=float, default=20.0, help="wall-clock seconds of feed")
    parser.add_argument("--speed", type=float, default=30.0)
    args = parser.parse_args()
    if not kx.licensed:
        sys.exit("PyKX needs a kdb+ licence to run the tick processes (see README).")

    kx.q("\\c 25 160")                       # console size used to print tables
    buffer = io.StringIO()

    class Tee(io.TextIOBase):
        def write(self, s):
            sys.__stdout__.write(s)
            return buffer.write(s)

    with contextlib.redirect_stdout(Tee()):
        run(args.seconds, args.speed)
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(buffer.getvalue().lstrip(), encoding="utf-8")
    print(f"\nwritten to {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
