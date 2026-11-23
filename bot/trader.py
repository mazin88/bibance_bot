"""Decision loop, independent of where orders go (real exchange or paper)."""
import json, math, os
from strategy import signal, STOP_ATR


class Trader:
    def __init__(self, ex, symbols, risk=0.005, max_gross_lev=3.0, halt_below=0.0,
                 state_path=None, log=print):
        self.ex, self.symbols, self.risk, self.max_lev = ex, symbols, risk, max_gross_lev
        self.halt_below, self.path, self.log = halt_below, state_path, log
        self.state = {"last_bar": {}, "stops": {}}
        if state_path and os.path.exists(state_path):
            self.state |= json.load(open(state_path))

    def save(self):
        if self.path:
            tmp = self.path + ".tmp"
            json.dump(self.state, open(tmp, "w"), indent=1)
            os.replace(tmp, self.path)

    def step(self):
        """Run once after each 4h bar closes. Safe to call repeatedly: each bar is handled once."""
        ex, stops, bars = self.ex, self.state["stops"], {}
        for s in self.symbols:                      # pass 1: data + settle what happened last bar
            df = ex.klines(s)
            if len(df) < 200:
                continue
            ex.sync(s, df)
            bars[s] = df
        pos = ex.positions()
        closes = {s: float(df.close.iloc[-1]) for s, df in bars.items()}
        for s, df in bars.items():                  # pass 2: decisions
            last = str(df.index[-1])
            if self.state["last_bar"].get(s) == last:
                continue
            g, q = signal(df), pos.get(s, 0.0)
            if q == 0 and s in stops:               # stopped out since last bar
                self.log(f"{s}: position was stopped out at ~{stops[s]:.6g}")
                ex.cancel_stop(s); del stops[s]
            if q != 0 and ((q > 0) != g["up"]):     # trend flipped -> exit
                px = ex.market(s, -q, reduce_only=True)
                ex.cancel_stop(s); stops.pop(s, None)
                self.log(f"{s}: EXIT {'long' if q > 0 else 'short'} at {px:.6g} (trend flipped)")
                pos.pop(s, None); q = 0.0
            elif q != 0:                            # trail the stop
                d = 1 if q > 0 else -1
                new = g["close"] - d * STOP_ATR * g["atr"]
                old = stops.get(s)
                if old is None or (new - old) * d > ex.rules(s)[1]:
                    ex.set_stop(s, d, new); stops[s] = new
                    self.log(f"{s}: stop moved to {new:.6g}")
            d = 1 if g["cross_up"] else (-1 if g["cross_dn"] else 0)
            if q == 0 and d and g["atr"] > 0:
                self._enter(s, d, g, pos, closes)
            self.state["last_bar"][s] = last
            self.save()

    def _enter(self, s, d, g, pos, closes):
        ex = self.ex
        eq = ex.equity()
        if eq <= max(5.0, self.halt_below):
            self.log(f"{s}: signal skipped, equity {eq:.2f} is below the halt level")
            return
        px, dist = ex.price(s), STOP_ATR * g["atr"]
        step, _, min_notional = ex.rules(s)
        notional = eq * self.risk / dist * px
        if notional < min_notional:                 # bump to the minimum only if risk stays <= 2x target
            notional = min_notional * 1.05 if min_notional * 1.05 * dist / px <= 2 * self.risk * eq else 0
        gross = sum(abs(q) * closes.get(t, 0) for t, q in pos.items())
        if notional == 0 or gross + notional > self.max_lev * eq:
            self.log(f"{s}: signal skipped (order too small for the risk limit, or leverage cap reached)")
            return
        qty = math.floor(notional / px / step) * step
        if qty * px < min_notional:
            qty += step
        fill = ex.market(s, d * qty)
        stop = fill - d * dist
        ex.set_stop(s, d, stop)
        self.state["stops"][s] = stop
        pos[s] = d * qty
        self.log(f"{s}: ENTER {'long' if d > 0 else 'short'} {qty:.6g} at {fill:.6g}, stop {stop:.6g}, "
                 f"risk ${qty * dist:.2f} of ${eq:.2f}")
