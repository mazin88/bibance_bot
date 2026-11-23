"""Step 2: rank coins on TRAIN with a small ensemble of robust 4h trend configs,
pick the top 10, then report how that pick did on the unseen TEST period.
Models a $50 account: an order below the exchange minimum notional is skipped."""
import os, sys
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(__file__))
from engine import load, run, stats
from download import UNIVERSE
import strategies as S

SPLIT = "2025-07-01"
CONFIGS = [(S.ema_trend, dict(fast=10, slow=50)), (S.ema_trend, dict(fast=20, slow=100)),
           (S.donchian, dict(n=20, x=10)), (S.donchian, dict(n=40, x=20))]
STOP = 3.5

rows = []
for s in UNIVERSE:
    df = load(s, "4h")
    row = {"sym": s, "avg_qvol_m$": round(df.quote_volume.loc[SPLIT:].resample("1D").sum().mean() / 1e6)}
    for part, sl in (("train", slice(None, SPLIT)), ("test", slice(SPLIT, None))):
        d = df.loc[sl]
        st = [stats(*run(d, fn(df, **p).loc[d.index], stop_atr=STOP)) for fn, p in CONFIGS]
        st = pd.DataFrame(st)
        row |= {f"{part}_sharpe": round(st.sharpe.mean(), 2), f"{part}_ret%": round(st["ret%"].mean(), 1),
                f"{part}_dd%": round(st["maxdd%"].mean(), 1), f"{part}_pf": round(st.pf.mean(), 2),
                f"{part}_cfg_pos": int((st["ret%"] > 0).sum())}
    row["train_months"] = round((pd.Timestamp(SPLIT) - df.index[0]).days / 30)
    rows.append(row)
r = pd.DataFrame(rows).sort_values("train_sharpe", ascending=False).reset_index(drop=True)
r.to_csv(os.path.join(os.path.dirname(__file__), "coin_ranking.csv"), index=False)
pd.set_option("display.width", 250)
print(r.to_string())
elig = r[(r.train_months >= 12) & (r.sym != "BTCUSDT")]   # BTC min order ($100) too big for $50
top = elig.head(10)
print("\nTOP 10 by train:", list(top.sym))
print("top10  test: mean sharpe %.2f, mean ret %.1f%%, positive %d/10" % (top.test_sharpe.mean(), top["test_ret%"].mean(), (top["test_ret%"] > 0).sum()))
rest = r[~r.sym.isin(top.sym)]
print("others test: mean sharpe %.2f, mean ret %.1f%%, positive %d/%d" % (rest.test_sharpe.mean(), rest["test_ret%"].mean(), (rest["test_ret%"] > 0).sum(), len(rest)))
print("rank corr train vs test sharpe: %.2f" % r.train_sharpe.rank().corr(r.test_sharpe.rank()))
