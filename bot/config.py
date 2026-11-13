"""All tunable settings and hard risk limits live here."""
import os

# --- Hard risk limits ---------------------------------------------------------
CAPITAL = float(os.getenv("BOT_CAPITAL", "100"))            # max $ the bot ever deploys
DAILY_LOSS_LIMIT_PCT = 0.02                                   # flatten + halt at -2% of CAPITAL
MAX_TRADES_PER_DAY = 1                                        # also keeps us clear of PDT limits

# --- Strategy: opening-range breakout, long only -------------------------------
SYMBOL = os.getenv("BOT_SYMBOL", "SPY")
OPENING_RANGE_MIN = 15          # 09:30-09:45 ET defines the range
BAR_MINUTES = 5
ENTRY_DEADLINE = "11:30"        # no new entries after this (ET)
EXIT_TIME = "15:45"             # flat by this time (ET), earlier on half-days
MAX_STOP_PCT = 0.010            # stop never further than 1% below entry
TARGET_R = 2.0                  # take profit at 2x the risk
MAX_CHASE_PCT = 0.002           # live: skip if price ran >0.2% past the breakout level

# --- Backtest assumptions -----------------------------------------------------
SLIPPAGE_PCT = 0.0002           # 0.02% per side

# --- Broker -------------------------------------------------------------------
PAPER = os.getenv("ALPACA_PAPER", "true").lower() != "false"
API_KEY = os.getenv("ALPACA_API_KEY", "")
API_SECRET = os.getenv("ALPACA_API_SECRET", "")
ORDER_PREFIX = "orb"
