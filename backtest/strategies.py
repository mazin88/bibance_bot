"""Candidate strategies. Each returns a DataFrame of signals: le/se entries, lx/sx exits, atr."""
import pandas as pd
from engine import atr, rsi


def _pack(df, le, se, lx, sx):
    return pd.DataFrame({"le": le.fillna(False), "se": se.fillna(False),
                         "lx": lx.fillna(False), "sx": sx.fillna(False), "atr": atr(df)})


def donchian(df, n=55, x=20, long_only=False):
    """Trend breakout: enter on an n-bar high/low, exit on the opposite x-bar extreme."""
    hi, lo = df.high.rolling(n).max().shift(), df.low.rolling(n).min().shift()
    xhi, xlo = df.high.rolling(x).max().shift(), df.low.rolling(x).min().shift()
    le, se = df.close > hi, df.close < lo
    if long_only:
        se = se & False
    return _pack(df, le, se, df.close < xlo, df.close > xhi)


def ema_trend(df, fast=20, slow=100, long_only=False):
    """Trend following: fast/slow EMA crossover, flip on the opposite cross."""
    f, s = df.close.ewm(span=fast).mean(), df.close.ewm(span=slow).mean()
    up = f > s
    le, se = up & ~up.shift(fill_value=False), ~up & up.shift(fill_value=True)
    if long_only:
        se = se & False
    return _pack(df, le, se, ~up, up)


def rsi_reversion(df, n=4, lo=20, hi=80, trend=200):
    """Mean reversion with the trend: buy dips in an uptrend, sell rips in a downtrend."""
    r = rsi(df.close, n)
    ma = df.close.rolling(trend).mean()
    le, se = (r < lo) & (df.close > ma), (r > hi) & (df.close < ma)
    return _pack(df, le, se, r > 55, r < 45)


def momentum(df, look=180, long_only=False):
    """Time-series momentum: long if the look-bar return is positive, short if negative."""
    m = df.close.pct_change(look)
    up, dn = m > 0, m < 0
    le, se = up & ~up.shift(fill_value=False), dn & ~dn.shift(fill_value=False)
    if long_only:
        se = se & False
    return _pack(df, le, se, ~up, ~dn)
