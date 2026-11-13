"""Backtest the opening-range breakout on Alpaca historical 5-minute bars.

Usage: python -m bot.backtest [days]   (needs ALPACA_API_KEY / ALPACA_API_SECRET)
"""
import sys
from datetime import datetime, timedelta, timezone

import pandas as pd

from bot import config as C
from bot.strategy import exit_time, find_signal, levels


def simulate_day(day: pd.DataFrame, capital: float = C.CAPITAL):
    sig = find_signal(day)
    if sig is None or sig.entry_bar is None:
        return None
    entry = float(day.loc[sig.entry_bar, "open"]) * (1 + C.SLIPPAGE_PCT)
    stop, target = levels(entry, sig.or_low)
    qty = capital / entry
    flat_at = exit_time(day.index[0])
    exit_px, reason = None, None
    for ts, b in day[day.index >= sig.entry_bar].iterrows():
        if ts >= flat_at:
            exit_px, reason = b["open"], "time"
            break
        if b["low"] <= stop:  # conservative: stop checked before target
            exit_px, reason = min(stop, b["open"]), "stop"
            break
        if b["high"] >= target:
            exit_px, reason = max(target, b["open"]), "target"
            break
    if exit_px is None:
        exit_px, reason = day["close"].iloc[-1], "close"
    exit_px *= 1 - C.SLIPPAGE_PCT
    pnl = (exit_px - entry) * qty
    return dict(date=day.index[0].date(), entry=entry, exit=exit_px, reason=reason, pnl=pnl)


def run(bars: pd.DataFrame, capital: float = C.CAPITAL) -> pd.DataFrame:
    bars = bars.between_time("09:30", "15:55")
    trades = [t for _, d in bars.groupby(bars.index.date) if (t := simulate_day(d, capital))]
    return pd.DataFrame(trades)


def report(trades: pd.DataFrame, n_days: int, capital: float = C.CAPITAL) -> str:
    if trades.empty:
        return f"No trades in {n_days} sessions."
    eq = capital + trades["pnl"].cumsum()
    dd = (eq - eq.cummax().clip(lower=capital)).min()
    wins = trades[trades.pnl > 0]
    losses = trades[trades.pnl <= 0]
    pf = wins.pnl.sum() / -losses.pnl.sum() if len(losses) and losses.pnl.sum() else float("inf")
    lines = [
        f"Symbol {C.SYMBOL}, capital ${capital:.0f}, {n_days} sessions",
        f"Trades: {len(trades)}  ({len(trades)/n_days:.0%} of days)",
        f"Win rate: {len(wins)/len(trades):.1%}",
        f"Avg win ${wins.pnl.mean() if len(wins) else 0:.2f} | avg loss ${losses.pnl.mean() if len(losses) else 0:.2f}",
        f"Profit factor: {pf:.2f}",
        f"Total P&L: ${trades.pnl.sum():.2f} ({trades.pnl.sum()/capital:.1%})",
        f"Max drawdown: ${dd:.2f}",
        f"Exit reasons: {trades.reason.value_counts().to_dict()}",
    ]
    by_year = trades.groupby(pd.to_datetime(trades.date).dt.year).pnl.sum()
    lines.append("P&L by year: " + ", ".join(f"{y}: ${v:.2f}" for y, v in by_year.items()))
    return "\n".join(lines)


def fetch_bars(days: int) -> pd.DataFrame:
    from alpaca.data.enums import DataFeed
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

    client = StockHistoricalDataClient(C.API_KEY, C.API_SECRET)
    end = datetime.now(timezone.utc) - timedelta(minutes=20)  # free plan: SIP needs >15 min delay
    req = StockBarsRequest(
        symbol_or_symbols=C.SYMBOL,
        timeframe=TimeFrame(5, TimeFrameUnit.Minute),
        start=end - timedelta(days=days),
        end=end,
        feed=DataFeed.SIP,
    )
    df = client.get_stock_bars(req).df.xs(C.SYMBOL, level="symbol")
    df.index = df.index.tz_convert("America/New_York")
    return df[["open", "high", "low", "close"]]


if __name__ == "__main__":
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 1095
    bars = fetch_bars(days)
    sessions = len(set(bars.between_time("09:30", "15:55").index.date))
    trades = run(bars)
    print(report(trades, sessions))
    if not trades.empty:
        print("\nLast 10 trades:\n" + trades.tail(10).to_string(index=False))
