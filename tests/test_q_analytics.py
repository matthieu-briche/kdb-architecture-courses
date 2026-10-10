"""Tests of the q code that runs inside the kdb+ processes (RTE post-processor, query APIs).

The q functions are evaluated in PyKX's embedded q, on small hand-built tables whose
expected results can be worked out by hand. They need a kdb+ licence for PyKX and
are skipped without one (see README, "Tests").
"""
import datetime as dt
import os

import numpy as np
import pytest

kx = pytest.importorskip("pykx")
pytestmark = pytest.mark.skipif(not kx.licensed, reason="PyKX has no kdb+ licence")

from config import PORTS, QUOTE_COLUMNS, TRADE_COLUMNS          # noqa: E402
from create_database import business_days_before, to_table     # noqa: E402
from hawkes import simulate_session                            # noqa: E402
from tick import HDB_APIS, RTE_APIS, RTE_POST_PROCESSOR         # noqa: E402


def q(code):
    return kx.q(code).py()


@pytest.fixture
def rt():
    """In-memory trade/quote tables as the RTE sees them, plus the RTE APIs."""
    kx.q("trade:([] time:`timespan$(); sym:`symbol$(); exchange:`symbol$(); sz:`long$(); px:`float$())")
    kx.q("quote:([] time:`timespan$(); sym:`symbol$(); exchange:`symbol$(); bid:`float$(); ask:`float$();"
         " bidsz:`long$(); asksz:`long$())")
    kx.q("`quote insert (0D09:30:00.000 0D09:30:00.900 0D09:30:01.000; `AAPL`MSFT`AAPL; 3#`NYSE;"
         " 100 300 101f; 100.02 300.01 101.02; 3#100; 3#100)")
    kx.q("`trade insert (0D09:30:00.500 0D09:30:01.000; `AAPL`AAPL; `NYSE`IEX; 100 300; 100.02 101)")
    for name, code in RTE_APIS.items():
        kx.q(f"{name}:{code}")


def test_count_trades(rt):
    assert q("count_trades`AAPL") == 2
    assert q("count_trades`MSFT") == 0


def test_trade_context_uses_prevailing_quote(rt):
    q("r:trade_context`AAPL")
    # first trade at 09:30:00.5 sees the 09:30:00 quote; second (same time as a quote) sees that quote
    assert q("exec bid from r") == [100.0, 101.0]
    expected = [1e4 * (100.02 - 100.01) / 100.01, 1e4 * (101 - 101.01) / 101.01]
    assert q("exec slippage_bps from r") == pytest.approx(expected)


def test_ohlc_bars(rt):
    q("r:0!ohlc[`AAPL;1]")
    assert q("count r") == 1
    assert q("first each r`open`high`low`close`volume") == [100.02, 101.0, 100.02, 101.0, 400]


def test_vwap(rt):
    assert q("exec first vwap from vwap`AAPL") == pytest.approx((100.02 * 100 + 101 * 300) / 400)


@pytest.fixture
def post_processor(rt):
    """The RTE post-processor, publishing into a local `.u.upd` that records each message.

    `.agg.h:0i` makes the publish `neg[0i] (".u.upd"; ...)` evaluate in this process.
    """
    kx.q(".test.msgs:(); .u.upd:{[t;x] .test.msgs,:enlist (t;x)}; .agg.h:0i; .agg.next:-0Wp")
    kx.q("pp:" + RTE_POST_PROCESSOR.replace("TP_PORT", str(PORTS["tickerplant"])))


def test_post_processor_publishes_aggregate(post_processor):
    q("pp[`quote;()]")
    assert q("count .test.msgs") == 1
    assert q("string .test.msgs[0;0]") == "aggregate"
    q("a:flip `time`sym`trdvol`vwap`maxpx`minpx`bid`ask`spread_bps`qrate!.test.msgs[0;1]")
    assert q("a`sym") == ["AAPL"]                      # MSFT has quotes but no trades
    assert q("first a`time") == dt.timedelta(hours=9, minutes=30, seconds=1)
    row = q("first each a`trdvol`vwap`maxpx`minpx`bid`ask`spread_bps`qrate")
    assert row == pytest.approx([100.02 * 100 + 101 * 300, (100.02 * 100 + 101 * 300) / 400,
                                 101.0, 100.02, 101.0, 101.02, 1e4 * 0.02 / 101.01, 0.2])


def test_post_processor_is_throttled(post_processor):
    q("pp[`quote;()]")
    q("pp[`trade;()]")
    assert q("count .test.msgs") == 1                  # second call within the same second
    q(".agg.next:.z.P - 1")
    q("pp[`trade;()]")
    assert q("count .test.msgs") == 2


def test_post_processor_waits_for_trades(post_processor):
    q("delete from `trade")
    q("pp[`quote;()]")
    assert q("count .test.msgs") == 0


@pytest.fixture
def hdb(tmp_path):
    """Two short days written like create_database.py, loaded with \\l."""
    rng = np.random.default_rng(3)
    db = kx.DB(path=str(tmp_path / "db"))
    days = business_days_before(dt.date.today() - dt.timedelta(days=1), 2)
    expected = {}
    for day in days:
        s = simulate_session(rng, T=900.0)
        db.create(to_table(s.trades, TRADE_COLUMNS), "trade", kx.toq(day), by_field="sym", log=False)
        db.create(to_table(s.quotes, QUOTE_COLUMNS), "quote", kx.toq(day), by_field="sym", log=False)
        aapl = s.trades["sym"] == 0
        expected[day] = (int(aapl.sum()), int(s.trades["sz"][aapl].sum()))
    cwd = os.getcwd()
    kx.q.system.load(str(tmp_path / "db"))
    for name, code in HDB_APIS.items():
        kx.q(f"{name}:{code}")
    yield expected
    os.chdir(cwd)


def test_hdb_count(hdb):
    assert q("hdb_count[`AAPL;10]") == sum(n for n, _ in hdb.values())


def test_daily_stats(hdb):
    q("r:0!daily_stats[`AAPL;10]")
    assert q("r`date") == sorted(hdb)
    assert q("r`trades") == [hdb[d][0] for d in sorted(hdb)]
    assert q("r`volume") == [hdb[d][1] for d in sorted(hdb)]
    rvol = q("r`rvol")
    assert all(np.isfinite(rvol)) and min(rvol) > 0
