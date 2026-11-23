"""Exchange adapters. Both expose the same small interface used by trader.Trader:
klines, price, rules, equity, positions, market, set_stop, cancel_stop, sync."""
import hashlib, hmac, math, time
from decimal import Decimal
from urllib.parse import urlencode
import pandas as pd
import requests

TAKER_FEE, SLIPPAGE = 0.0005, 0.0003


def _fmt(x, step):
    """Round x DOWN to a multiple of step and render without float noise."""
    d = (Decimal(str(x)) / Decimal(str(step))).to_integral_value(rounding="ROUND_DOWN") * Decimal(str(step))
    return format(d.normalize(), "f")


class BinanceFutures:
    """Thin REST client for Binance USDT-M futures (one-way position mode)."""

    def __init__(self, key="", secret="", base="https://fapi.binance.com", interval="4h"):
        self.key, self.secret, self.base, self.interval = key, secret.encode(), base.rstrip("/"), interval
        self.http = requests.Session()
        self.http.headers["X-MBX-APIKEY"] = key
        self._rules, self._offset = None, 0

    # ---- plumbing
    def _req(self, method, path, signed=False, **p):
        p = {k: v for k, v in p.items() if v is not None}
        if signed:
            p |= {"timestamp": int(time.time() * 1000) + self._offset, "recvWindow": 10000}
            p["signature"] = hmac.new(self.secret, urlencode(p).encode(), hashlib.sha256).hexdigest()
        r = self.http.request(method, self.base + path, params=p, timeout=20)
        if r.status_code >= 400:
            raise RuntimeError(f"{method} {path} -> {r.status_code} {r.text[:300]}")
        return r.json()

    def start(self, symbols, leverage):
        """Sync the clock, verify account mode, set leverage. Call once before live trading."""
        self._offset = self._req("GET", "/fapi/v1/time")["serverTime"] - int(time.time() * 1000)
        if self._req("GET", "/fapi/v1/positionSide/dual", signed=True)["dualSidePosition"]:
            raise RuntimeError("Account is in Hedge Mode; switch to One-way Mode in Binance futures settings.")
        for s in symbols:
            self._req("POST", "/fapi/v1/leverage", signed=True, symbol=s, leverage=leverage)

    # ---- market data (no key needed)
    def klines(self, sym, limit=600):
        raw = self._req("GET", "/fapi/v1/klines", symbol=sym, interval=self.interval, limit=limit)
        now = int(time.time() * 1000) + self._offset
        rows = [r for r in raw if r[6] < now]                     # closed bars only
        df = pd.DataFrame([[float(x) for x in r[1:5]] for r in rows], columns=["open", "high", "low", "close"])
        df.index = pd.to_datetime([r[0] for r in rows], unit="ms")
        return df

    def price(self, sym):
        return float(self._req("GET", "/fapi/v1/ticker/price", symbol=sym)["price"])

    def rules(self, sym):
        """(qty step, price tick, min order notional)"""
        if self._rules is None:
            self._rules = {}
            for s in self._req("GET", "/fapi/v1/exchangeInfo")["symbols"]:
                f = {x["filterType"]: x for x in s["filters"]}
                step = max(float(f["LOT_SIZE"]["stepSize"]), float(f["MARKET_LOT_SIZE"]["stepSize"]))
                self._rules[s["symbol"]] = (step, float(f["PRICE_FILTER"]["tickSize"]),
                                            float(f["MIN_NOTIONAL"]["notional"]))
        return self._rules[sym]

    # ---- account
    def equity(self):
        return float(self._req("GET", "/fapi/v3/account", signed=True)["totalWalletBalance"])

    def positions(self):
        out = {}
        for p in self._req("GET", "/fapi/v3/positionRisk", signed=True):
            if float(p["positionAmt"]) != 0:
                out[p["symbol"]] = float(p["positionAmt"])
        return out

    # ---- orders
    def market(self, sym, qty, reduce_only=False):
        """qty signed (+buy / -sell). Returns average fill price."""
        r = self._req("POST", "/fapi/v1/order", signed=True, symbol=sym, side="BUY" if qty > 0 else "SELL",
                      type="MARKET", quantity=_fmt(abs(qty), self.rules(sym)[0]),
                      reduceOnly="true" if reduce_only else None, newOrderRespType="RESULT")
        return float(r.get("avgPrice") or 0) or self.price(sym)

    def cancel_stop(self, sym):
        self._req("DELETE", "/fapi/v1/algoOpenOrders", signed=True, symbol=sym)

    def set_stop(self, sym, pos_sign, stop_price):
        """Replace the protective stop: close the whole position at market if price hits stop_price."""
        self.cancel_stop(sym)
        self._req("POST", "/fapi/v1/algoOrder", signed=True, algoType="CONDITIONAL", symbol=sym,
                  side="SELL" if pos_sign > 0 else "BUY", type="STOP_MARKET",
                  triggerPrice=_fmt(stop_price, self.rules(sym)[1]), closePosition="true",
                  workingType="CONTRACT_PRICE")

    def sync(self, sym, df):
        pass      # the exchange itself executes stops and funding


class PaperExchange:
    """Simulated account on top of any market-data feed. Used for dry-run and for the replay test."""

    def __init__(self, feed, cash=50.0, state=None):
        self.feed = feed
        self.s = state if state else {"cash": cash, "pos": {}, "stops": {}, "seen": {}}
        self.fills = []

    klines = lambda self, sym: self.feed.klines(sym)
    price = lambda self, sym: self.feed.price(sym)
    rules = lambda self, sym: self.feed.rules(sym)
    equity = lambda self: self.s["cash"]
    positions = lambda self: {k: v[0] for k, v in self.s["pos"].items()}

    def market(self, sym, qty, reduce_only=False, px=None):
        px = px or self.price(sym)
        self.s["cash"] -= abs(qty) * px * (TAKER_FEE + SLIPPAGE)
        old = self.s["pos"].pop(sym, None)
        if old:                                   # this bot only ever closes fully
            self.s["cash"] += old[0] * (px - old[1])
        else:
            self.s["pos"][sym] = [qty, px]
        self.fills.append((sym, qty, px))
        return px

    def set_stop(self, sym, pos_sign, stop_price):
        self.s["stops"][sym] = stop_price

    def cancel_stop(self, sym):
        self.s["stops"].pop(sym, None)

    def sync(self, sym, df, funding=0.0):
        """Apply the last closed bar to an open position: stop-out check, then funding."""
        bar, t = df.iloc[-1], str(df.index[-1])
        if self.s["seen"].get(sym) == t:
            return
        self.s["seen"][sym] = t
        p, stop = self.s["pos"].get(sym), self.s["stops"].get(sym)
        if p and stop is not None:
            if p[0] > 0 and bar.low <= stop:
                self.market(sym, -p[0], px=min(stop, bar.open)); self.cancel_stop(sym)
            elif p[0] < 0 and bar.high >= stop:
                self.market(sym, -p[0], px=max(stop, bar.open)); self.cancel_stop(sym)
        p = self.s["pos"].get(sym)
        if p and funding:
            self.s["cash"] -= p[0] * bar.close * funding
