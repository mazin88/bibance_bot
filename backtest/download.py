"""Download USDT-M futures 1h klines + funding rates from Binance's public archive
(data.binance.vision). No API key needed.

usage: python backtest/download.py [--start 2023-01] [--end 2026-10]
"""
import argparse, io, os, sys, zipfile
from concurrent.futures import ThreadPoolExecutor
import pandas as pd
import requests

BASE = "https://data.binance.vision/data/futures/um/monthly"
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
UNIVERSE = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT",
    "AVAXUSDT", "LINKUSDT", "LTCUSDT", "DOTUSDT", "TRXUSDT", "BCHUSDT", "NEARUSDT",
    "UNIUSDT", "AAVEUSDT", "SUIUSDT", "APTUSDT", "ARBUSDT", "OPUSDT", "INJUSDT",
    "FILUSDT", "ATOMUSDT", "ETCUSDT", "XLMUSDT", "HBARUSDT", "TONUSDT", "SEIUSDT",
    "TIAUSDT", "WLDUSDT", "ENAUSDT", "1000PEPEUSDT", "1000SHIBUSDT", "WIFUSDT",
    "FETUSDT", "RENDERUSDT", "HYPEUSDT", "TAOUSDT",
]
KCOLS = ["open_time", "open", "high", "low", "close", "volume", "close_time",
         "quote_volume", "trades", "taker_base", "taker_quote", "ignore"]


def fetch(url):
    for _ in range(4):
        try:
            r = requests.get(url, timeout=60)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return r.content
        except requests.RequestException:
            continue
    return None


def read_zip(content, names=None):
    with zipfile.ZipFile(io.BytesIO(content)) as z:
        raw = z.read(z.namelist()[0])
    has_header = not raw[:1].isdigit()
    return pd.read_csv(io.BytesIO(raw), header=0 if has_header else None,
                       names=None if has_header else names)


def kline_month(sym, month):
    c = fetch(f"{BASE}/klines/{sym}/1h/{sym}-1h-{month}.zip")
    if c is None:
        return None
    df = read_zip(c, KCOLS)
    df.columns = KCOLS[:len(df.columns)]
    return df[["open_time", "open", "high", "low", "close", "volume", "quote_volume"]]


def funding_month(sym, month):
    c = fetch(f"{BASE}/fundingRate/{sym}/{sym}-fundingRate-{month}.zip")
    if c is None:
        return None
    df = read_zip(c, ["calc_time", "funding_interval_hours", "last_funding_rate"])
    df.columns = ["calc_time", "interval_hours", "rate"][:len(df.columns)]
    return df[["calc_time", "rate"]]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2023-01")
    ap.add_argument("--end", default="2026-10")
    a = ap.parse_args()
    months = [p.strftime("%Y-%m") for p in pd.period_range(a.start, a.end, freq="M")]
    os.makedirs(DATA_DIR, exist_ok=True)
    with ThreadPoolExecutor(24) as ex:
        for sym in UNIVERSE:
            ks = [k for k in ex.map(lambda m: kline_month(sym, m), months) if k is not None]
            fs = [f for f in ex.map(lambda m: funding_month(sym, m), months) if f is not None]
            if not ks:
                print(f"{sym}: no data", file=sys.stderr)
                continue
            k = pd.concat(ks).drop_duplicates("open_time").sort_values("open_time")
            k.to_csv(f"{DATA_DIR}/{sym}_1h.csv.gz", index=False)
            if fs:
                pd.concat(fs).sort_values("calc_time").to_csv(
                    f"{DATA_DIR}/{sym}_funding.csv.gz", index=False)
            first = pd.to_datetime(k.open_time.iloc[0], unit="ms").date()
            last = pd.to_datetime(k.open_time.iloc[-1], unit="ms").date()
            print(f"{sym}: {len(k)} bars {first} -> {last}, funding rows {sum(map(len, fs))}")


if __name__ == "__main__":
    main()
