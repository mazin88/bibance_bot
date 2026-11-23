"""Bar-based futures backtest engine with realistic costs.

- signals are computed on a bar's close and executed at the NEXT bar's open
- protective stops are checked intrabar (filled at the stop, or at the open on a gap)
- taker fee + slippage charged on every fill, funding charged while a position is open
- position size = fixed % of equity risked between entry and stop, capped by leverage
"""
import os
import numpy as np
import pandas as pd

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
TAKER_FEE = 0.0005   # 0.05% per side (Binance USDT-M, VIP0, no BNB discount)
SLIPPAGE = 0.0003    # 0.03% per side, conservative for small market orders


def load(sym, tf="4h"):
    k = pd.read_csv(f"{DATA_DIR}/{sym}_1h.csv.gz")
    k.index = pd.to_datetime(k.pop("open_time"), unit="ms")
    if tf != "1h":
        k = k.resample(tf).agg({"open": "first", "high": "max", "low": "min",
                                "close": "last", "volume": "sum", "quote_volume": "sum"}).dropna()
    try:
        f = pd.read_csv(f"{DATA_DIR}/{sym}_funding.csv.gz")
        f.index = pd.to_datetime(f.pop("calc_time"), unit="ms").dt.floor("h")
        # funding paid during each bar (sum of rates whose timestamp falls inside the bar)
        k["funding"] = f["rate"].groupby(f.index.floor(tf)).sum().reindex(k.index).fillna(0.0)
    except FileNotFoundError:
        k["funding"] = 0.0
    return k


def atr(df, n=14):
    pc = df.close.shift()
    tr = pd.concat([df.high - df.low, (df.high - pc).abs(), (df.low - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def rsi(s, n=14):
    d = s.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn)


def run(df, sig, risk=0.01, max_lev=3.0, stop_atr=2.5, trail=True, start_equity=50.0,
        fee=TAKER_FEE, slip=SLIPPAGE):
    """sig: DataFrame with bool cols le, se (entries), lx, sx (exits) and float col atr.
    Returns (equity Series, trades DataFrame)."""
    o, h, l, c = (df[x].to_numpy() for x in ("open", "high", "low", "close"))
    fund = df.funding.to_numpy()
    le, se, lx, sx = (sig[x].to_numpy() for x in ("le", "se", "lx", "sx"))
    a = sig["atr"].to_numpy()
    n = len(df)
    eq = start_equity
    curve = np.empty(n)
    pos = 0.0          # signed quantity
    entry = stop = 0.0
    ei = 0
    trades = []
    cost = fee + slip

    def close_pos(i, px):
        nonlocal eq, pos
        pnl = pos * (px - entry) - abs(pos) * px * cost
        eq += pnl
        trades.append((df.index[ei], df.index[i], np.sign(pos), entry, px, trade_pnl0 + pnl))
        pos = 0.0

    trade_pnl0 = 0.0
    for i in range(1, n):
        # 1) act on previous bar's signals at this bar's open
        if pos != 0:
            if (pos > 0 and lx[i - 1]) or (pos < 0 and sx[i - 1]):
                close_pos(i, o[i])
        if pos == 0 and eq > 1 and not np.isnan(a[i - 1]) and a[i - 1] > 0:
            d = 1 if le[i - 1] else (-1 if se[i - 1] else 0)
            if d:
                dist = stop_atr * a[i - 1]
                qty = min(eq * risk / dist, eq * max_lev / o[i])
                pos = d * qty
                entry = o[i]
                stop = entry - d * dist
                ei = i
                trade_pnl0 = -qty * entry * cost
                eq += trade_pnl0
        # 2) intrabar stop
        if pos > 0 and l[i] <= stop:
            close_pos(i, min(stop, o[i]))
        elif pos < 0 and h[i] >= stop:
            close_pos(i, max(stop, o[i]))
        # 3) funding + trailing stop update
        if pos != 0:
            f = -pos * c[i] * fund[i]
            eq += f
            trade_pnl0 += f
            if trail and not np.isnan(a[i]):
                if pos > 0:
                    stop = max(stop, c[i] - stop_atr * a[i])
                else:
                    stop = min(stop, c[i] + stop_atr * a[i])
        curve[i] = eq + (pos * (c[i] - entry) if pos else 0.0)
    curve[0] = start_equity
    t = pd.DataFrame(trades, columns=["entry_time", "exit_time", "side", "entry", "exit", "pnl"])
    return pd.Series(curve, index=df.index), t


def stats(curve, trades):
    if len(curve) < 2:
        return {}
    ret = curve.iloc[-1] / curve.iloc[0] - 1
    years = (curve.index[-1] - curve.index[0]).days / 365.25
    daily = curve.resample("1D").last().pct_change().dropna()
    dd = (curve / curve.cummax() - 1).min()
    wins = trades.pnl[trades.pnl > 0].sum()
    losses = -trades.pnl[trades.pnl <= 0].sum()
    return {
        "ret%": round(ret * 100, 1),
        "cagr%": round(((1 + ret) ** (1 / years) - 1) * 100, 1) if years > 0 and ret > -1 else -100.0,
        "maxdd%": round(dd * 100, 1),
        "sharpe": round(daily.mean() / daily.std() * np.sqrt(365), 2) if daily.std() > 0 else 0.0,
        "trades": len(trades),
        "win%": round((trades.pnl > 0).mean() * 100, 1) if len(trades) else 0.0,
        "pf": round(wins / losses, 2) if losses > 0 else float("inf"),
    }
