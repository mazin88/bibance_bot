"""Entry point.  python bot/run.py          -> paper trading (default, no keys needed)
                 MODE=live python bot/run.py -> real orders (needs BINANCE_KEY / BINANCE_SECRET)
Settings come from environment variables or a .env file next to this script."""
import json, logging, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from exchange import BinanceFutures, PaperExchange
from trader import Trader

HERE = os.path.dirname(os.path.abspath(__file__))
env_file = os.path.join(HERE, ".env")
if os.path.exists(env_file):
    for line in open(env_file):
        line = line.split("#", 1)[0].strip()          # drop comments, incl. inline "# ..." notes
        if "=" in line:
            k, v = line.split("=", 1)
            if k.strip() and v.strip():
                os.environ.setdefault(k.strip(), v.strip())
E = os.environ.get
MODE = E("MODE", "paper")
SYMBOLS = E("SYMBOLS", "HBARUSDT,1000PEPEUSDT,INJUSDT,SOLUSDT,XLMUSDT,WLDUSDT,WIFUSDT,XRPUSDT,NEARUSDT,FETUSDT").split(",")
RISK = float(E("RISK_PCT", "0.5")) / 100
LEVERAGE = int(E("LEVERAGE", "3"))
BAR = 4 * 3600

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                    handlers=[logging.StreamHandler(), logging.FileHandler(os.path.join(HERE, f"bot_{MODE}.log"))])
log = logging.info


def main():
    api = BinanceFutures(E("BINANCE_KEY", ""), E("BINANCE_SECRET", ""), E("BASE_URL", "https://fapi.binance.com"))
    state_path = os.path.join(HERE, f"state_{MODE}.json")
    if MODE == "live":
        if not E("BINANCE_KEY") or not E("BINANCE_SECRET"):
            sys.exit("MODE=live needs BINANCE_KEY and BINANCE_SECRET")
        api.start(SYMBOLS, LEVERAGE)
        ex = api
    else:
        saved = json.load(open(state_path)).get("paper") if os.path.exists(state_path) else None
        ex = PaperExchange(api, cash=float(E("PAPER_CASH", "50")), state=saved)
    tr = Trader(ex, SYMBOLS, risk=RISK, max_gross_lev=LEVERAGE, halt_below=float(E("HALT_BELOW", "30")),
                state_path=state_path, log=log)
    log(f"started: mode={MODE} risk/trade={RISK:.2%} symbols={len(SYMBOLS)} equity=${ex.equity():.2f}")
    while True:
        for attempt in range(5):
            try:
                tr.step()
                if MODE != "live":
                    tr.state["paper"] = ex.s
                    tr.save()
                log(f"checked: equity ${ex.equity():.2f}, open positions {ex.positions()}")
                break
            except Exception as e:          # network blips etc: retry, never crash the loop
                log(f"error (attempt {attempt + 1}/5): {e}")
                time.sleep(60)
        if E("ONCE"):
            return
        time.sleep(BAR - time.time() % BAR + 20)   # 20s after the next 4h bar closes (UTC 0/4/8/...)


if __name__ == "__main__":
    main()
