# Binance USDT-M futures bot — research

Backtest of simple strategies on 38 liquid perpetuals, 1h candles 2023-01 → 2026-10, for a $50 account.
Costs modelled: 0.05% taker fee + 0.03% slippage per side, real funding rates, $5 minimum order.
Parameters and coins were chosen on **train** (2023-01 → 2025-06) and checked on unseen **test** (2025-07 → 2026-10).

## Reproduce

```bash
pip install pandas numpy requests
python backtest/download.py        # ~30 MB from data.binance.vision, no API key
python backtest/research.py        # strategy sweep over all coins  -> research_results.csv
python backtest/select_coins.py    # coin ranking                   -> coin_ranking.csv
python backtest/portfolio.py 1     # shared $50 account, 1% risk per trade, top-10 coins
```

## Findings

- Only **4h trend-following** was positive after costs. Every 1h variant and RSI mean-reversion lost money.
- Chosen rule: 4h EMA(10/50) cross, long and short, 3.5×ATR trailing stop, fixed % of equity risked per trade.
- Top 10 coins on train: HBAR, 1000PEPE, INJ, SOL, XLM, WLD, WIF, XRP, NEAR, FET.
- Shared $50 account on the unseen test period (16 months):

| Setup | End balance | Return | Max drawdown | Profit factor |
|---|---|---|---|---|
| Top 10, 0.5% risk/trade | $69.30 | +38.6% | -30.7% | 1.19 |
| Top 10, 1% risk/trade | $67.37 | +34.7% | -41.7% | 1.08 |
| Top 10, 1%, EMA 20/100 instead | $53.73 | +7.5% | -30.3% | 1.03 |
| 12 random 10-coin baskets, 1% | — | -59% … +32%, median -11% | median -53% | — |

The edge is thin: about 31% of trades win, the result depends heavily on which coins and parameters
are used, and past coin ranking only weakly predicted test results. Train results (+370% to +817%)
are inflated by selection and should be ignored.

## The bot (`bot/`)

Trades the rule above on the 10 coins: checks once every 4 hours (just after each candle closes, UTC),
enters on an EMA cross, places a stop-loss order on Binance itself, trails it, and exits when the trend flips.

| File | Purpose |
|---|---|
| `strategy.py` | EMA/ATR signal |
| `trader.py` | Sizing, entries, exits, stop trailing |
| `exchange.py` | Binance REST client and a paper (simulated) account |
| `run.py` | Scheduler; reads settings from `bot/.env` |
| `test_replay.py` | Replays history through the bot and compares with the backtest |

### Run on a VPS

The server must be in a country where Binance futures are available (the API rejects restricted locations).

```bash
git clone https://github.com/mazin88/bibance_bot.git && cd bibance_bot
pip install pandas numpy requests
cp bot/.env.example bot/.env
python bot/run.py                 # paper mode: simulated $50, real prices, no orders
```

To go live: create an API key **on the sub-account** with only "Enable Futures" ticked (no withdrawals),
restrict it to the VPS IP address, put it in `bot/.env`, set `MODE=live`, make sure the futures account is
in One-way position mode, and restart. Keep it running with `tmux`, or a systemd service:

```ini
# /etc/systemd/system/bibance-bot.service
[Service]
WorkingDirectory=/root/bibance_bot
ExecStart=/usr/bin/python3 bot/run.py
Restart=always
[Install]
WantedBy=multi-user.target
```

### What is and is not verified

- Verified: `python bot/test_replay.py` runs the bot's decision code over the 16-month test period and
  reproduces the backtest (624 vs 625 trades, final equity within 0.3%).
- Not verified: the live Binance calls in `exchange.py`. They could not be exercised from the development
  environment (location-blocked). Run paper mode first, then test live on the testnet (`BASE_URL` in `.env`)
  or with the smallest size before trusting it.
- The bot assumes it is the only thing trading these 10 symbols on the account.
