"""One pass of the live bot. Meant to run every few minutes during market hours.

The bot keeps no state of its own: every run rebuilds the picture from Alpaca
(clock, account, position, today's orders, today's bars), so a skipped or
delayed scheduled run never leaves it confused.
"""
import logging
import sys
import time as _time
from datetime import datetime

import pandas as pd
from alpaca.data.enums import DataFeed
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest, StockLatestTradeRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, OrderStatus, QueryOrderStatus, TimeInForce
from alpaca.trading.requests import GetOrdersRequest, MarketOrderRequest, StopOrderRequest

from bot import config as C
from bot.strategy import exit_time, find_signal, levels

log = logging.getLogger("bot")
NY = "America/New_York"


class Bot:
    def __init__(self):
        if not (C.API_KEY and C.API_SECRET):
            sys.exit("ALPACA_API_KEY / ALPACA_API_SECRET not set")
        self.tc = TradingClient(C.API_KEY, C.API_SECRET, paper=C.PAPER)
        self.dc = StockHistoricalDataClient(C.API_KEY, C.API_SECRET)

    # ---------- helpers ----------
    def now(self) -> pd.Timestamp:
        return pd.Timestamp.now(tz=NY)

    def today_tag(self) -> str:
        return f"{C.ORDER_PREFIX}-{self.now():%Y%m%d}"

    def position(self):
        try:
            return self.tc.get_open_position(C.SYMBOL)
        except Exception:
            return None

    def todays_orders(self):
        start = self.now().normalize().tz_convert("UTC").to_pydatetime()
        orders = self.tc.get_orders(GetOrdersRequest(status=QueryOrderStatus.ALL, after=start,
                                                     symbols=[C.SYMBOL], limit=500))
        return [o for o in orders if (o.client_order_id or "").startswith(self.today_tag())]

    def open_orders(self):
        return self.tc.get_orders(GetOrdersRequest(status=QueryOrderStatus.OPEN, symbols=[C.SYMBOL]))

    def bars_today(self) -> pd.DataFrame:
        start = self.now().normalize() + pd.Timedelta(hours=9, minutes=30)
        req = StockBarsRequest(symbol_or_symbols=C.SYMBOL, timeframe=TimeFrame(5, TimeFrameUnit.Minute),
                               start=start.tz_convert("UTC").to_pydatetime(), feed=DataFeed.IEX)
        df = self.dc.get_stock_bars(req).df
        if df.empty:
            return df
        df = df.xs(C.SYMBOL, level="symbol")
        df.index = df.index.tz_convert(NY)
        # drop the bar still forming
        return df[df.index + pd.Timedelta(minutes=C.BAR_MINUTES) <= self.now()][["open", "high", "low", "close"]]

    def last_price(self) -> float:
        t = self.dc.get_stock_latest_trade(StockLatestTradeRequest(symbol_or_symbols=C.SYMBOL, feed=DataFeed.IEX))
        return float(t[C.SYMBOL].price)

    def flatten(self, why: str):
        for o in self.open_orders():
            self.tc.cancel_order_by_id(o.id)
        if self.position():
            _time.sleep(1)
            self.tc.close_position(C.SYMBOL)
            log.warning("FLATTENED %s: %s", C.SYMBOL, why)

    def ensure_stop(self, pos, stop: float):
        if any(o.side == OrderSide.SELL and o.stop_price for o in self.open_orders()):
            return
        qty = abs(float(pos.qty))
        try:
            self.tc.submit_order(StopOrderRequest(symbol=C.SYMBOL, qty=qty, side=OrderSide.SELL,
                                                  stop_price=round(stop, 2), time_in_force=TimeInForce.DAY,
                                                  client_order_id=f"{self.today_tag()}-stop-{int(_time.time())}"))
            log.info("Stop placed at %.2f for %s sh", stop, qty)
        except Exception as e:  # never hold a position without protection
            log.error("Stop order rejected (%s); closing position", e)
            self.flatten("could not place stop")

    # ---------- main ----------
    def run(self):
        clock = self.tc.get_clock()
        if not clock.is_open:
            log.info("Market closed. Nothing to do.")
            return
        now = self.now()
        acct = self.tc.get_account()
        pos = self.position()

        # 1. Daily loss limit (account-level: use a dedicated account for the bot)
        day_pnl = float(acct.equity) - float(acct.last_equity)
        limit = C.CAPITAL * C.DAILY_LOSS_LIMIT_PCT
        log.info("Equity %.2f, day P&L %.2f (limit -%.2f), position: %s",
                 float(acct.equity), day_pnl, limit, f"{pos.qty} @ {pos.avg_entry_price}" if pos else "none")
        if day_pnl <= -limit:
            self.flatten(f"daily loss limit hit ({day_pnl:.2f})")
            return

        # 2. Leftover position from a previous day (e.g. a missed close run)
        orders = self.todays_orders()
        if pos and not any(o.side == OrderSide.BUY for o in orders):
            self.flatten("position not opened today")
            return

        # 3. End-of-day exit
        flat_at = exit_time(now, pd.Timestamp(clock.next_close).tz_convert(NY))
        if now >= flat_at:
            if pos:
                self.flatten("end of day")
            return

        bars = self.bars_today()
        sig = find_signal(bars) if not bars.empty else None

        # 4. Manage an open position: stop on the broker, target checked here
        if pos:
            entry = float(pos.avg_entry_price)
            or_low = sig.or_low if sig else entry * (1 - C.MAX_STOP_PCT)
            stop, target = levels(entry, or_low)
            self.ensure_stop(pos, stop)
            px = self.last_price()
            log.info("Managing: last %.2f stop %.2f target %.2f", px, stop, target)
            if px >= target:
                self.flatten(f"target hit ({px:.2f})")
            return

        # 5. Look for a new entry
        entries = [o for o in orders if o.side == OrderSide.BUY]
        if len(entries) >= C.MAX_TRADES_PER_DAY:
            log.info("Already traded today.")
            return
        if sig is None:
            log.info("No breakout signal yet.")
            return
        deadline = now.normalize() + pd.Timedelta(C.ENTRY_DEADLINE + ":00")
        px = self.last_price()
        if now > deadline or px > sig.or_high * (1 + C.MAX_CHASE_PCT) or px <= sig.or_high * (1 - C.MAX_STOP_PCT):
            log.info("Signal at %s but entry not allowed now (price %.2f, OR high %.2f).",
                     sig.signal_bar, px, sig.or_high)
            return
        if not acct.pattern_day_trader and float(acct.multiplier) > 1 and \
                float(acct.equity) < 25000 and int(acct.daytrade_count) >= 3:
            log.info("Would exceed day-trade limit for a small margin account; skipping.")
            return

        buying_power = float(getattr(acct, "non_marginable_buying_power", None) or acct.cash)
        notional = round(min(C.CAPITAL, buying_power) * 0.99, 2)
        if notional < 1:
            log.warning("Not enough settled cash (%.2f).", buying_power)
            return
        o = self.tc.submit_order(MarketOrderRequest(symbol=C.SYMBOL, notional=notional, side=OrderSide.BUY,
                                                    time_in_force=TimeInForce.DAY,
                                                    client_order_id=f"{self.today_tag()}-buy"))
        log.info("BUY $%.2f %s submitted (OR %.2f-%.2f, last %.2f)", notional, C.SYMBOL, sig.or_low, sig.or_high, px)
        for _ in range(30):
            o = self.tc.get_order_by_id(o.id)
            if o.status == OrderStatus.FILLED:
                break
            _time.sleep(1)
        pos = self.position()
        if pos:
            stop, target = levels(float(pos.avg_entry_price), sig.or_low)
            self.ensure_stop(pos, stop)
            log.info("Filled %s @ %s; target %.2f", pos.qty, pos.avg_entry_price, target)
        else:
            log.error("Buy not filled after 30s (status %s); cancelling.", o.status)
            self.tc.cancel_order_by_id(o.id)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    log.info("Mode: %s, symbol %s, capital $%.0f", "PAPER" if C.PAPER else "LIVE", C.SYMBOL, C.CAPITAL)
    Bot().run()
