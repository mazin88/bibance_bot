"""Signal logic: 4h EMA(10/50) trend with ATR stop. Same maths as backtest/strategies.py."""
import pandas as pd

FAST, SLOW, ATR_N, STOP_ATR = 10, 50, 14, 3.5


def signal(df):
    """df: CLOSED 4h bars (open/high/low/close). Returns the state on the last closed bar."""
    f = df.close.ewm(span=FAST).mean()
    s = df.close.ewm(span=SLOW).mean()
    up = f > s
    pc = df.close.shift()
    tr = pd.concat([df.high - df.low, (df.high - pc).abs(), (df.low - pc).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / ATR_N, adjust=False).mean()
    now, prev = bool(up.iloc[-1]), bool(up.iloc[-2])
    return {"up": now, "cross_up": now and not prev, "cross_dn": prev and not now,
            "atr": float(atr.iloc[-1]), "close": float(df.close.iloc[-1])}
