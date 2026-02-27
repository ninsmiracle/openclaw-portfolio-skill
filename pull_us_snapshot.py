# #!/usr/bin/env python3
# # -*- coding: utf-8 -*-

# """
# Pull US ETF/stock quotes at minute-level cadence.

# Priority:
# 1) Finnhub (requires FINNHUB_API_KEY or --finnhub-key)
# 2) Yahoo chart API (no key, best-effort fallback)

# Examples:
#   python3 pull_us_snapshot.py
#   python3 pull_us_snapshot.py --symbols QQQ,VOO,BOXX --interval-sec 60
#   python3 pull_us_snapshot.py --provider finnhub --finnhub-key <YOUR_KEY>
# """

# import argparse
# import json
# import os
# import time
# from datetime import datetime, timezone
# from typing import Dict, List, Optional, Tuple
# from urllib.error import URLError, HTTPError
# from urllib.parse import quote_plus
# from urllib.request import urlopen


# def now_ms() -> int:
#     return int(time.time() * 1000)


# def iso_now() -> str:
#     return datetime.now(timezone.utc).isoformat()


# def load_dotenv(path: str = ".env") -> None:
#     """
#     Load simple KEY=VALUE lines from .env into process env (non-destructive).
#     """
#     if not path or not os.path.exists(path):
#         return
#     try:
#         with open(path, "r", encoding="utf-8") as f:
#             for raw in f:
#                 line = raw.strip()
#                 if not line or line.startswith("#") or "=" not in line:
#                     continue
#                 key, val = line.split("=", 1)
#                 key = key.strip()
#                 val = val.strip().strip("'").strip('"')
#                 if key and key not in os.environ:
#                     os.environ[key] = val
#     except Exception:
#         pass


# def http_get_json(url: str, timeout_sec: float = 4.0) -> Dict:
#     with urlopen(url, timeout=timeout_sec) as resp:
#         raw = resp.read().decode("utf-8")
#     return json.loads(raw)


# def fetch_finnhub_quote(symbol: str, api_key: str) -> Dict:
#     url = (
#         "https://finnhub.io/api/v1/quote"
#         f"?symbol={quote_plus(symbol)}&token={quote_plus(api_key)}"
#     )
#     data = http_get_json(url)
#     # Finnhub fields:
#     # c current, pc prev close, t timestamp(sec), h/l/o high/low/open
#     last = float(data.get("c") or 0.0)
#     if last <= 0:
#         raise RuntimeError(f"Finnhub invalid quote for {symbol}: {data}")
#     ts_sec = int(data.get("t") or 0)
#     update_iso = (
#         datetime.fromtimestamp(ts_sec, tz=timezone.utc).isoformat()
#         if ts_sec > 0
#         else iso_now()
#     )
#     return {
#         "symbol": symbol,
#         "last": last,
#         "prev_close": float(data.get("pc") or 0.0),
#         "open": float(data.get("o") or 0.0),
#         "high": float(data.get("h") or 0.0),
#         "low": float(data.get("l") or 0.0),
#         "currency": "USD",
#         "update_time": update_iso,
#         "source": "finnhub",
#     }


# def fetch_yahoo_quote(symbol: str) -> Dict:
#     # Best-effort fallback, usually minute-level with slight delay.
#     url = (
#         f"https://query1.finance.yahoo.com/v8/finance/chart/{quote_plus(symbol)}"
#         "?interval=1m&range=1d"
#     )
#     data = http_get_json(url)
#     result = ((data.get("chart") or {}).get("result") or [None])[0]
#     if not result:
#         raise RuntimeError(f"Yahoo missing result for {symbol}")
#     meta = result.get("meta") or {}
#     last = float(meta.get("regularMarketPrice") or 0.0)
#     if last <= 0:
#         raise RuntimeError(f"Yahoo invalid quote for {symbol}: {meta}")
#     ts_sec = int(meta.get("regularMarketTime") or 0)
#     update_iso = (
#         datetime.fromtimestamp(ts_sec, tz=timezone.utc).isoformat()
#         if ts_sec > 0
#         else iso_now()
#     )
#     return {
#         "symbol": symbol,
#         "last": last,
#         "prev_close": float(meta.get("previousClose") or 0.0),
#         "open": float(meta.get("regularMarketOpen") or 0.0),
#         "high": float(meta.get("regularMarketDayHigh") or 0.0),
#         "low": float(meta.get("regularMarketDayLow") or 0.0),
#         "currency": str(meta.get("currency") or "USD"),
#         "update_time": update_iso,
#         "source": "yahoo",
#     }


# def fetch_quote(symbol: str, provider: str, finnhub_key: Optional[str]) -> Dict:
#     symbol = symbol.strip().upper()
#     if not symbol:
#         raise ValueError("empty symbol")

#     if provider == "finnhub":
#         if not finnhub_key:
#             raise RuntimeError("provider=finnhub but no FINNHUB key provided")
#         return fetch_finnhub_quote(symbol, finnhub_key)

#     if provider == "yahoo":
#         return fetch_yahoo_quote(symbol)

#     # provider=auto
#     errors: List[str] = []
#     if finnhub_key:
#         try:
#             return fetch_finnhub_quote(symbol, finnhub_key)
#         except Exception as e:
#             errors.append(f"finnhub: {e}")
#     try:
#         return fetch_yahoo_quote(symbol)
#     except Exception as e:
#         errors.append(f"yahoo: {e}")
#     raise RuntimeError(f"all providers failed for {symbol}; {' | '.join(errors)}")


# def fetch_all_quotes(
#     symbols: List[str],
#     provider: str,
#     finnhub_key: Optional[str],
# ) -> Tuple[Dict[str, Dict], Dict[str, str]]:
#     quotes: Dict[str, Dict] = {}
#     errors: Dict[str, str] = {}
#     for s in symbols:
#         sym = s.strip().upper()
#         if not sym:
#             continue
#         try:
#             quotes[sym] = fetch_quote(sym, provider=provider, finnhub_key=finnhub_key)
#         except (RuntimeError, ValueError, URLError, HTTPError, TimeoutError) as e:
#             errors[sym] = str(e)
#         except Exception as e:
#             errors[sym] = f"unexpected: {e}"
#     return quotes, errors


# def build_snapshot(symbols: List[str], quotes: Dict[str, Dict], errors: Dict[str, str]) -> Dict:
#     return {
#         "ts": now_ms(),
#         "iso_ts": iso_now(),
#         "market": "US",
#         "base_currency": "USD",
#         "symbols": [s.strip().upper() for s in symbols if s.strip()],
#         "quotes": quotes,
#         "errors": errors,
#     }


# def write_json_atomic(path: str, obj: Dict) -> None:
#     tmp = path + ".tmp"
#     with open(tmp, "w", encoding="utf-8") as f:
#         json.dump(obj, f, ensure_ascii=False, indent=2)
#     os.replace(tmp, path)


# def run_once(args) -> Dict:
#     symbols = [x.strip().upper() for x in args.symbols.split(",") if x.strip()]
#     quotes, errors = fetch_all_quotes(
#         symbols=symbols,
#         provider=args.provider,
#         finnhub_key=args.finnhub_key,
#     )
#     snapshot = build_snapshot(symbols=symbols, quotes=quotes, errors=errors)
#     write_json_atomic(args.out, snapshot)
#     print(
#         f"OK: wrote {args.out} at {snapshot['iso_ts']}, "
#         f"quotes={len(quotes)}, errors={len(errors)}"
#     )
#     if errors:
#         print("WARN: failed symbols:", ", ".join(f"{k}({v})" for k, v in errors.items()))
#     return snapshot


# def main():
#     load_dotenv(".env")
#     ap = argparse.ArgumentParser()
#     ap.add_argument("--symbols", default="QQQ,VOO,BOXX", help="Comma-separated US symbols")
#     ap.add_argument("--out", default="us_snapshot.json", help="Output JSON path")
#     ap.add_argument(
#         "--provider",
#         default="auto",
#         choices=["auto", "finnhub", "yahoo"],
#         help="Quote provider",
#     )
#     ap.add_argument(
#         "--finnhub-key",
#         default=os.getenv("FINNHUB_API_KEY", "").strip(),
#         help="Finnhub API key (or set env FINNHUB_API_KEY)",
#     )
#     ap.add_argument(
#         "--interval-sec",
#         type=int,
#         default=0,
#         help="If >0, keep polling every N seconds",
#     )
#     args = ap.parse_args()

#     if args.provider == "finnhub" and not args.finnhub_key:
#         raise SystemExit("ERROR: provider=finnhub requires --finnhub-key or FINNHUB_API_KEY")

#     if args.interval_sec <= 0:
#         run_once(args)
#         return

#     while True:
#         started = time.time()
#         run_once(args)
#         elapsed = time.time() - started
#         sleep_sec = max(1.0, float(args.interval_sec) - elapsed)
#         time.sleep(sleep_sec)


# if __name__ == "__main__":
#     main()
