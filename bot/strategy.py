"""Pure strategy logic shared by the backtest and the live bot.

`day` is a DataFrame of 5-minute bars for ONE regular session, indexed by the
bar's start time in America/New_York, with columns open/high/low/close.
"""
from dataclasses import dataclass
from datetime import time, timedelta

import pandas as pd

from bot import config as C


def _t(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


OPEN = time(9, 30)


@dataclass
class Signal:
    or_high: float
    or_low: float
    signal_bar: pd.Timestamp   # bar whose close broke out
    entry_bar: pd.Timestamp | None  # next bar (entry at its open), None if not formed yet


def opening_range(day: pd.DataFrame):
    start = day.index[0].normalize() + pd.Timedelta(hours=9, minutes=30)
    end = start + pd.Timedelta(minutes=C.OPENING_RANGE_MIN)
    rng = day[(day.index >= start) & (day.index < end)]
    if len(rng) < C.OPENING_RANGE_MIN // C.BAR_MINUTES:
        return None
    return float(rng["high"].max()), float(rng["low"].min()), end


def find_signal(day: pd.DataFrame) -> Signal | None:
    o = opening_range(day)
    if o is None:
        return None
    hi, lo, or_end = o
    deadline = day.index[0].normalize() + _td(C.ENTRY_DEADLINE)
    after = day[(day.index >= or_end)]
    for i, (ts, bar) in enumerate(after.iterrows()):
        bar_close_time = ts + pd.Timedelta(minutes=C.BAR_MINUTES)
        if bar_close_time > deadline:
            return None
        if bar["close"] > hi:
            nxt = after.index[i + 1] if i + 1 < len(after) else None
            return Signal(hi, lo, ts, nxt)
    return None


def levels(entry: float, or_low: float):
    stop = max(or_low, entry * (1 - C.MAX_STOP_PCT))
    if stop >= entry:  # entry gapped below range low: use max stop distance
        stop = entry * (1 - C.MAX_STOP_PCT)
    target = entry + C.TARGET_R * (entry - stop)
    return stop, target


def _td(hhmm: str) -> pd.Timedelta:
    h, m = hhmm.split(":")
    return pd.Timedelta(hours=int(h), minutes=int(m))


def exit_time(day_start: pd.Timestamp, session_close: pd.Timestamp | None = None) -> pd.Timestamp:
    t = day_start.normalize() + _td(C.EXIT_TIME)
    if session_close is not None:
        t = min(t, session_close - pd.Timedelta(minutes=15))
    return t
