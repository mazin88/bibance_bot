"""Step 1: which strategy family + parameters hold up across ALL coins on the TRAIN period?"""
import sys, itertools
import numpy as np, pandas as pd
sys.path.insert(0, __import__("os").path.dirname(__file__))
from engine import load, run, stats
from download import UNIVERSE
import strategies as S

SPLIT = "2025-07-01"
GRID = {
    "donchian": (S.donchian, [dict(n=n, x=x) for n, x in [(20, 10), (40, 20), (55, 20), (80, 40), (120, 40)]]),
    "ema_trend": (S.ema_trend, [dict(fast=f, slow=s) for f, s in [(10, 50), (20, 100), (30, 150), (50, 200)]]),
    "momentum": (S.momentum, [dict(look=k) for k in (60, 120, 180, 360)]),
    "rsi_reversion": (S.rsi_reversion, [dict(n=n, lo=lo, hi=100 - lo) for n, lo in [(2, 10), (4, 20), (7, 25)]]),
}
rows = []
for tf in ("1h", "4h"):
    data = {s: load(s, tf) for s in UNIVERSE}
    for name, (fn, params) in GRID.items():
        for p in params:
            for stop in (2.0, 3.5):
                res = {"train": [], "test": []}
                for s, df in data.items():
                    sig = fn(df, **p)
                    for part, sl in (("train", slice(None, SPLIT)), ("test", slice(SPLIT, None))):
                        d = df.loc[sl]
                        if len(d) < 500:
                            continue
                        c, t = run(d, sig.loc[d.index], stop_atr=stop)
                        res[part].append(stats(c, t))
                row = {"tf": tf, "strat": name, "params": str(p), "stop": stop}
                for part in ("train", "test"):
                    r = pd.DataFrame(res[part])
                    row |= {f"{part}_med_ret": r["ret%"].median(), f"{part}_pos%": round((r["ret%"] > 0).mean() * 100),
                            f"{part}_med_sharpe": r["sharpe"].median(), f"{part}_med_dd": r["maxdd%"].median(),
                            f"{part}_trades": int(r["trades"].median())}
                rows.append(row)
                print(row, flush=True)
pd.DataFrame(rows).to_csv(__import__("os").path.join(__import__("os").path.dirname(__file__), "research_results.csv"), index=False)
