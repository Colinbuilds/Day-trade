import pandas as pd
import pytest

from bot import config as C
from bot.backtest import run, simulate_day
from bot.strategy import find_signal, levels


def make_day(closes, date="2026-03-02", spread=0.05):
    idx = pd.date_range(f"{date} 09:30", periods=len(closes), freq="5min", tz="America/New_York")
    c = pd.Series(closes, index=idx, dtype=float)
    o = c.shift(1).fillna(c.iloc[0])
    return pd.DataFrame({"open": o, "close": c,
                         "high": pd.concat([o, c], axis=1).max(axis=1) + spread,
                         "low": pd.concat([o, c], axis=1).min(axis=1) - spread})


def flat(n, px=100.0):
    return [px] * n


def test_no_signal_on_flat_day():
    assert find_signal(make_day(flat(78))) is None


def test_breakout_signal_and_entry_bar():
    closes = [100, 100.2, 99.9] + flat(3, 100) + [100.5] + flat(71, 100.5)
    sig = find_signal(make_day(closes))
    assert sig is not None
    assert sig.or_high == pytest.approx(100.25)
    assert sig.signal_bar.strftime("%H:%M") == "10:00"
    assert sig.entry_bar.strftime("%H:%M") == "10:05"


def test_no_entry_after_deadline():
    closes = flat(30, 100) + [101] + flat(47, 101)   # breakout at 12:00
    assert find_signal(make_day(closes)) is None


def test_stop_capped_at_max_pct():
    stop, target = levels(100.0, or_low=95.0)
    assert stop == pytest.approx(100 * (1 - C.MAX_STOP_PCT))
    assert target == pytest.approx(100 + C.TARGET_R * (100 - stop))


def test_target_hit_is_profitable():
    closes = [100, 100.1, 99.95] + [100.4] + [100.4, 100.8, 101.2, 101.6] + flat(70, 101.6)
    t = simulate_day(make_day(closes))
    assert t["reason"] == "target" and t["pnl"] > 0


def test_stop_hit_loss_is_bounded():
    closes = [100, 100.1, 99.95] + [100.4, 100.4, 99.0] + flat(72, 99.0)
    t = simulate_day(make_day(closes))
    assert t["reason"] == "stop"
    assert t["pnl"] < 0
    assert -t["pnl"] <= C.CAPITAL * C.DAILY_LOSS_LIMIT_PCT  # one stop-out stays inside the daily limit


def test_time_exit():
    closes = [100, 100.1, 99.95] + [100.4] + flat(74, 100.45)
    t = simulate_day(make_day(closes))
    assert t["reason"] == "time"


def test_run_multiple_days():
    a = make_day([100, 100.1, 99.95, 100.4, 100.4, 100.8, 101.2, 101.6] + flat(70, 101.6), "2026-03-02")
    b = make_day(flat(78), "2026-03-03")
    trades = run(pd.concat([a, b]))
    assert len(trades) == 1
