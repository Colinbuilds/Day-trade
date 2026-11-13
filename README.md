# Day-trade bot

An automated intraday trading bot for **Alpaca**. It runs on a GitHub Actions schedule, holds no state of its own, and has hard risk limits.

## Strategy: opening-range breakout on SPY, long only

1. The **opening range** is SPY's high and low from 09:30 to 09:45 ET.
2. **Entry:** the first 5-minute bar that closes above the range high, before 11:30 ET. The bot buys at market. If price has already run more than 0.2% past the breakout level, it skips the trade instead of chasing.
3. **Stop:** the range low, but never more than 1% below entry. The stop is a real order resting at Alpaca, so it protects the position between scheduled runs.
4. **Target:** 2× the risk.
5. **Time exit:** the bot is flat by 15:45 ET, or 15 minutes before an early close.
6. **One trade per day at most.**

## Hard limits (`bot/config.py`)

| Limit | Value |
|---|---|
| Capital deployed | **$100** maximum, whatever the account holds |
| Daily loss limit | **−2% ($2)**: closes everything and stops trading for the day |
| Trades per day | 1 |
| Overnight positions | none; a leftover position is closed on the next run |
| If the stop order is rejected | the position is closed immediately |

> The daily loss check uses the **whole account's** P&L for the day. Use an Alpaca account (or sub-account) dedicated to this bot, and don't trade it by hand.

## Setup

1. Open an Alpaca account. For live trading, fund it with about $100 to $200.
2. Create API keys at alpaca.markets, under **API Keys**. Live keys and paper keys are different.
3. In this GitHub repository, open **Settings → Secrets and variables → Actions**:
   - **Secrets:** `ALPACA_API_KEY`, `ALPACA_API_SECRET`
   - **Variables:**
     - `ALPACA_PAPER` = `false` for real money. If it is unset, the bot uses paper trading.
     - `LIVE_TRADING` = `true`. This is the **kill switch**: change it to anything else, or delete it, and the bot stops.
4. Run the **backtest** workflow (Actions → backtest → Run workflow) and read the summary.
5. Set `LIVE_TRADING=true` only when you're happy with the backtest results.

## Operating notes

- **Logs:** every run's decisions are in the Actions tab under the **trade** workflow.
- **Schedule:** GitHub cron can run a few minutes late or skip a run. The protective stop sits at Alpaca, so a late run delays the target or time exit but never removes the stop.
- **Actions minutes:** about 70 runs per trading day. That's free on a public repo. A private repo uses roughly 1,500 of the 2,000 free minutes a month.
- **Pattern-day-trader rule:** a margin account under $25k can make only a limited number of day trades. The bot checks `daytrade_count` and skips a trade that would break the limit. A cash account avoids the rule, and one trade a day only ever uses settled cash.
- **Risk:** most day-trading strategies lose money after costs. Past backtest results don't predict future returns. Only trade money you can afford to lose.

## Local development

```bash
pip install -r requirements.txt pytest
python -m pytest -q
ALPACA_API_KEY=... ALPACA_API_SECRET=... python -m bot.backtest 365
```
