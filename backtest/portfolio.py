"""Step 3: simulate the actual bot - one shared $50 account trading several coins.
Strategy: 4h EMA(10/50) trend, 3.5xATR trailing stop, long + short.
usage: python backtest/portfolio.py [risk_pct] [SYMBOL ...]"""
import os, sys
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(__file__))
from engine import load, stats, TAKER_FEE, SLIPPAGE
import strategies as S

SPLIT = "2025-07-01"
TOP10 = ["HBARUSDT", "1000PEPEUSDT", "INJUSDT", "SOLUSDT", "XLMUSDT", "WLDUSDT", "WIFUSDT",
         "XRPUSDT", "NEARUSDT", "FETUSDT"]
MIN_NOTIONAL = 5.0     # Binance minimum order value for most alt perps
STOP_ATR = 3.5


def simulate(symbols, start, end, risk=0.01, max_gross_lev=3.0, equity0=50.0,
             strat=S.ema_trend, params=dict(fast=10, slow=50)):
    cost = TAKER_FEE + SLIPPAGE
    D, G = {}, {}
    for s in symbols:
        df = load(s, "4h")
        D[s], G[s] = df.loc[start:end], strat(df, **params).loc[start:end]
    idx = sorted(set().union(*[d.index for d in D.values()]))
    arr = {s: (D[s].reindex(idx), G[s].reindex(idx)) for s in symbols}
    A = {s: {c: d[c].to_numpy() for c in ("open", "high", "low", "close", "funding")} |
            {c: g[c].to_numpy() for c in ("le", "se", "lx", "sx", "atr")} for s, (d, g) in arr.items()}
    eq = equity0
    pos = {s: None for s in symbols}     # s -> [qty_signed, entry, stop, pnl_so_far, entry_i]
    curve, trades, skipped, peak_gross = [], [], 0, 0.0

    def close(s, i, px):
        nonlocal eq
        q, entry, _, p0, ei = pos[s]
        pnl = q * (px - entry) - abs(q) * px * cost
        eq += pnl
        trades.append((s, idx[ei], idx[i], np.sign(q), p0 + pnl))
        pos[s] = None

    for i in range(1, len(idx)):
        for s in symbols:
            a = A[s]
            if np.isnan(a["open"][i]) or np.isnan(a["close"][i - 1]):
                continue
            p = pos[s]
            if p and ((p[0] > 0 and a["lx"][i - 1] == True) or (p[0] < 0 and a["sx"][i - 1] == True)):
                close(s, i, a["open"][i]); p = None
            if p is None and eq > 5 and a["atr"][i - 1] > 0:
                d = 1 if a["le"][i - 1] == True else (-1 if a["se"][i - 1] == True else 0)
                if d:
                    px, dist = a["open"][i], STOP_ATR * a["atr"][i - 1]
                    notional = eq * risk / dist * px
                    if notional < MIN_NOTIONAL:           # bump to the minimum if risk stays <= 2x target
                        notional = MIN_NOTIONAL * 1.05 if MIN_NOTIONAL * 1.05 * dist / px <= 2 * risk * eq else 0
                    gross = sum(abs(q[0]) * A[t]["close"][i - 1] for t, q in pos.items() if q)
                    if notional == 0 or gross + notional > max_gross_lev * eq:
                        skipped += 1
                    else:
                        q = d * notional / px
                        fee = -abs(q) * px * cost
                        eq += fee
                        pos[s] = [q, px, px - d * dist, fee, i]
            p = pos[s]
            if p:
                if p[0] > 0 and a["low"][i] <= p[2]:
                    close(s, i, min(p[2], a["open"][i]))
                elif p[0] < 0 and a["high"][i] >= p[2]:
                    close(s, i, max(p[2], a["open"][i]))
            p = pos[s]
            if p:
                f = -p[0] * a["close"][i] * a["funding"][i]
                eq += f; p[3] += f
                if a["atr"][i] > 0:
                    p[2] = max(p[2], a["close"][i] - STOP_ATR * a["atr"][i]) if p[0] > 0 else \
                           min(p[2], a["close"][i] + STOP_ATR * a["atr"][i])
        unreal = sum(q[0] * (A[t]["close"][i] - q[1]) for t, q in pos.items() if q and not np.isnan(A[t]["close"][i]))
        gross = sum(abs(q[0]) * A[t]["close"][i] for t, q in pos.items() if q and not np.isnan(A[t]["close"][i]))
        peak_gross = max(peak_gross, gross / max(eq, 1e-9))
        curve.append(eq + unreal)
    c = pd.Series(curve, index=idx[1:])
    t = pd.DataFrame(trades, columns=["sym", "entry_time", "exit_time", "side", "pnl"])
    return c, t, skipped, peak_gross


if __name__ == "__main__":
    risk = float(sys.argv[1]) / 100 if len(sys.argv) > 1 else 0.01
    syms = sys.argv[2:] or TOP10
    for name, (a, b) in {"TRAIN 2023-01..2025-06": (None, SPLIT), "TEST  2025-07..2026-10 (unseen)": (SPLIT, None)}.items():
        c, t, sk, pg = simulate(syms, a, b, risk=risk)
        st = stats(c, t)
        print(f"\n{name}  risk/trade {risk:.1%}  ${c.iloc[0]:.0f} -> ${c.iloc[-1]:.2f}")
        print("  ", st, f"skipped_orders={sk} peak_gross_leverage={pg:.2f}x")
        if name.startswith("TEST"):
            m = c.resample("ME").last().pct_change().dropna() * 100
            print("   monthly %:", " ".join(f"{x:+.1f}" for x in m))
            print("   pnl by coin $:", t.groupby("sym").pnl.sum().round(2).sort_values().to_dict())
