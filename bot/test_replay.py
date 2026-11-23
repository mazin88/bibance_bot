"""Replay history through the real Trader + PaperExchange, bar by bar, and compare with the
backtest's portfolio simulation. Proves the live decision code matches what was backtested.
usage: python bot/test_replay.py   (needs backtest/data, see backtest/download.py)"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(HERE, "..", "backtest")]
import pandas as pd
from engine import load
from portfolio import simulate, TOP10, SPLIT
from exchange import PaperExchange
from trader import Trader

RISK, SYMS = 0.005, TOP10


class Feed:
    def __init__(self):
        self.d = {s: load(s, "4h") for s in SYMS}
        self.now = None                       # open time of the bar that is just starting
    def klines(self, s):
        df = self.d[s]
        return df.iloc[max(0, df.index.searchsorted(self.now) - 600):df.index.searchsorted(self.now)]
    def price(self, s):
        return float(self.d[s].open.loc[self.now])
    def rules(self, s):
        return (1e-9, 1e-12, 5.0)


class Paper(PaperExchange):
    def sync(self, sym, df):                  # feed real funding into the paper account
        super().sync(sym, df, funding=float(df.funding.iloc[-1]))


feed = Feed()
ex = Paper(feed, cash=50.0)
tr = Trader(ex, SYMS, risk=RISK, log=lambda m: None)
times = feed.d[SYMS[0]].loc[SPLIT:].index
for t in times[1:]:
    feed.now = t
    tr.step()
curve, trades, _, _ = simulate(SYMS, SPLIT, None, risk=RISK)
n_bot = len(ex.fills) // 2
print(f"backtest: {len(trades)} closed trades, final realised+open equity ${curve.iloc[-1]:.2f}")
unreal = sum(q * (float(feed.d[s].close.loc[:times[-1]].iloc[-1]) - e) for s, (q, e) in ex.s['pos'].items())
print(f"bot replay: {n_bot} round trips, final equity ${ex.equity() + unreal:.2f}")
diff = abs(ex.equity() + unreal - curve.iloc[-1]) / curve.iloc[-1]
print("MATCH" if diff < 0.02 and abs(n_bot - len(trades)) <= 3 else "MISMATCH", f"(equity diff {diff:.2%})")
