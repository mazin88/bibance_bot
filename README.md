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
