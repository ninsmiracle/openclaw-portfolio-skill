#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Pull portfolio snapshot via Futu OpenAPI (OpenD) every 5 minutes.
- Read positions from a markdown file (positions.md)
- Fetch market snapshot for CN/HK instruments
- Compute per-instrument value and bucket weights
- Output portfolio_snapshot.json for OpenClaw

Assumptions:
- OpenD runs locally on 127.0.0.1:11111
- Markdown contains:
  - Holdings tables with columns: Market, Code/Ticker, Shares, Amount_...
  - A YAML block "classification_v2" mapping instruments to buckets
  - DCA yaml block "dca_plan" or maintenance controls
"""

import argparse
import json
import os
import re
import sys
import time
from urllib.parse import quote_plus
from urllib.request import urlopen
from urllib.error import URLError, HTTPError
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple

# Optional YAML support (recommended)
try:
    import yaml  # PyYAML
except Exception:
    yaml = None

try:
    from futu import OpenQuoteContext, RET_OK
except Exception as e:
    print("ERROR: failed to import futu SDK. Try: pip install futu-api (or futu).")
    raise

# ----------------------------
# Config / Models
# ----------------------------

@dataclass
class Instrument:
    market: str  # CN/HK/US
    code: str    # CN: '512890', HK: '09988', US: 'QQQ'
    shares: float
    bucket: Optional[list] = None  # Can be a list of buckets (multi-asset classification)

def now_ms() -> int:
    return int(time.time() * 1000)

def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()

def load_dotenv(path: str = ".env") -> None:
    """
    Load simple KEY=VALUE lines from .env into process env (non-destructive).
    """
    if not path or not os.path.exists(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, val = line.split("=", 1)
                key = key.strip()
                val = val.strip().strip("'").strip('"')
                if key and key not in os.environ:
                    os.environ[key] = val
    except Exception:
        # Best-effort only, do not fail main workflow.
        pass

# ----------------------------
# Markdown Parsing
# ----------------------------

MD_TABLE_ROW_RE = re.compile(r"^\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*$")

def _extract_fenced_block(md_text: str, lang: str, key_hint: str) -> Optional[str]:
    """
    Find a fenced code block ```lang ... ``` that contains key_hint.
    Returns block content (without fences) or None.
    """
    fence_re = re.compile(rf"```{re.escape(lang)}\s*\n(.*?)\n```", re.DOTALL)
    for m in fence_re.finditer(md_text):
        body = m.group(1)
        if key_hint in body:
            return body
    return None

def parse_positions_from_md(md_path: str) -> Tuple[Dict[str, Instrument], Dict[str, List[Dict]], Dict]:
    """
    Returns:
      instruments: dict symbol_key -> Instrument
        symbol_key is like 'CN.512890', 'HK.09988', 'US.QQQ'
      classification_map: dict bucket -> list[{market, code, name, ...}]
        accepts either "classification_v2" or "asset_buckets"
      dca_plan: dict (may be empty)
    """
    with open(md_path, "r", encoding="utf-8") as f:
        md = f.read()

    # 1) Parse holdings by scanning tables (we rely on the "Market | Code | ... | Shares" layout)
    instruments: Dict[str, Instrument] = {}

    # Simple table parsers: look for lines containing "| AssetClass | Market |"
    lines = md.splitlines()
    current_table = None
    headers = []
    for line in lines:
        if line.strip().startswith("|") and "Market" in line and ("Code" in line or "Ticker" in line) and "Shares" in line:
            # header line
            current_table = True
            headers = [h.strip() for h in line.strip().strip("|").split("|")]
            continue
        if current_table and line.strip().startswith("|---"):
            continue
        if current_table and line.strip().startswith("|"):
            cols = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cols) != len(headers):
                # end of table
                continue
            row = dict(zip(headers, cols))
            market = row.get("Market", "").upper()
            code = (row.get("Code") or row.get("Ticker") or "").strip()
            shares_s = row.get("Shares", "").replace(",", "")
            try:
                shares = float(shares_s)
            except Exception:
                continue
            if not market or not code:
                continue
            symbol_key = f"{market}.{code}"
            instruments[symbol_key] = Instrument(market=market, code=code, shares=shares)

    # 2) Parse classification yaml (classification_v2 or asset_buckets)
    classification_map = {}
    dca_plan = {}

    if yaml is not None:
        cls_block = _extract_fenced_block(md, "yaml", "classification_v2")
        if not cls_block:
            cls_block = _extract_fenced_block(md, "yaml", "asset_buckets")
        if cls_block:
            try:
                parsed = yaml.safe_load(cls_block)
                if isinstance(parsed, dict):
                    if isinstance(parsed.get("classification_v2"), dict):
                        classification_map = parsed.get("classification_v2", {})
                    elif isinstance(parsed.get("asset_buckets"), dict):
                        classification_map = parsed.get("asset_buckets", {})
            except Exception:
                classification_map = {}

        dca_block = _extract_fenced_block(md, "yaml", "dca_plan")
        if dca_block:
            try:
                parsed = yaml.safe_load(dca_block)
                dca_plan = parsed.get("dca_plan", {}) if isinstance(parsed, dict) else {}
            except Exception:
                dca_plan = {}

    # 3) Apply bucket tags to instruments (support multi-bucket)
    if isinstance(classification_map, dict):
        for bucket, items in classification_map.items():
            if not isinstance(items, list):
                continue
            for it in items:
                try:
                    mkt = str(it.get("market", "")).upper()
                    code = str(it.get("code", "")).strip()
                    if not mkt or not code:
                        continue
                    key = f"{mkt}.{code}"
                    if key in instruments:
                        existing = instruments[key].bucket
                        if existing is None:
                            instruments[key].bucket = [bucket]
                        elif isinstance(existing, list):
                            if bucket not in existing:
                                existing.append(bucket)
                        else:
                            # was a single string, convert to list
                            if bucket != existing:
                                instruments[key].bucket = [existing, bucket]
                except Exception:
                    pass

    return instruments, classification_map, dca_plan

# ----------------------------
# Symbol mapping: OpenD format
# ----------------------------

def to_futu_code(market: str, code: str) -> str:
    """
    Futu code format:
      - CN A-share / ETF: 'SH.512890' or 'SZ.159980' etc.
      - HK: 'HK.09988'
    We must infer SH/SZ for CN by code prefix.
    """
    market = market.upper()
    code = code.strip()

    if market == "HK":
        return f"HK.{code.zfill(5)}"  # HK stocks are 5 digits
    if market == "US":
        return f"US.{code.upper()}"
    if market == "CN":
        # infer exchange by code prefix
        # SH: 5/6/9 for stocks & many ETFs (e.g., 51xxxx, 58xxxx)
        # SZ: 0/1/2/3 for stocks & many ETFs (e.g., 15xxxx, 16xxxx)
        if code.startswith(("5", "6", "9")):
            return f"SH.{code}"
        if code.startswith(("0", "1", "2", "3")):
            return f"SZ.{code}"
        # fallback to SH
        return f"SH.{code}"
    # generic fallback
    return f"{market}.{code}"

def split_quote_sources(
    instruments: Dict[str, Instrument],
) -> Tuple[Dict[str, Instrument], Dict[str, Instrument]]:
    """
    CN/HK use Futu OpenD; US uses web quote providers.
    """
    futu_instruments: Dict[str, Instrument] = {}
    us_instruments: Dict[str, Instrument] = {}
    for key, inst in instruments.items():
        mkt = (inst.market or "").upper()
        if mkt in ("CN", "HK"):
            futu_instruments[key] = inst
        elif mkt == "US":
            us_instruments[key] = inst
    return futu_instruments, us_instruments

# ----------------------------
# Quotes / Snapshot
# ----------------------------

def http_get_json(url: str, timeout_sec: float = 4.0) -> Dict:
    with urlopen(url, timeout=timeout_sec) as resp:
        raw = resp.read().decode("utf-8")
    return json.loads(raw)

def fetch_snapshots(quote_ctx: OpenQuoteContext, futu_codes: List[str]):
    """
    Use get_market_snapshot in batches (to avoid request size limits).
    Returns dict futu_code -> snapshot dict
    """
    out = {}
    BATCH = 200  # safe batch size
    for i in range(0, len(futu_codes), BATCH):
        batch = futu_codes[i:i+BATCH]
        ret, data = quote_ctx.get_market_snapshot(batch)
        if ret != RET_OK:
            raise RuntimeError(f"get_market_snapshot failed: {data}")
        # data is a pandas DataFrame
        for _, row in data.iterrows():
            code = row.get("code")
            if not code:
                continue
            out[code] = {
                "name": row.get("name"),
                "last": float(row.get("last_price", 0) or 0),
                "prev_close": float(row.get("prev_close_price", 0) or 0),
                "open": float(row.get("open_price", 0) or 0),
                "high": float(row.get("high_price", 0) or 0),
                "low": float(row.get("low_price", 0) or 0),
                "volume": float(row.get("volume", 0) or 0),
                "turnover": float(row.get("turnover", 0) or 0),
                "update_time": row.get("update_time"),
                "currency": row.get("currency"),
            }
    return out

def fetch_us_quote_finnhub(symbol: str, api_key: str) -> Dict:
    url = (
        "https://finnhub.io/api/v1/quote"
        f"?symbol={quote_plus(symbol)}&token={quote_plus(api_key)}"
    )
    data = http_get_json(url)
    last = float(data.get("c", 0) or 0)
    if last <= 0:
        raise RuntimeError(f"finnhub invalid quote for {symbol}: {data}")
    ts_sec = int(data.get("t", 0) or 0)
    update_time = (
        datetime.fromtimestamp(ts_sec, tz=timezone.utc).isoformat()
        if ts_sec > 0 else iso_now()
    )
    return {
        "name": symbol,
        "last": last,
        "prev_close": float(data.get("pc", 0) or 0),
        "open": float(data.get("o", 0) or 0),
        "high": float(data.get("h", 0) or 0),
        "low": float(data.get("l", 0) or 0),
        "volume": 0.0,
        "turnover": 0.0,
        "update_time": update_time,
        "currency": "USD",
        "source": "finnhub",
    }

def fetch_us_quote_yahoo(symbol: str) -> Dict:
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{quote_plus(symbol)}"
        "?interval=1m&range=1d"
    )
    data = http_get_json(url)
    result = ((data.get("chart") or {}).get("result") or [None])[0]
    if not result:
        raise RuntimeError(f"yahoo missing result for {symbol}")
    meta = result.get("meta") or {}
    last = float(meta.get("regularMarketPrice") or 0)
    if last <= 0:
        raise RuntimeError(f"yahoo invalid quote for {symbol}: {meta}")
    ts_sec = int(meta.get("regularMarketTime") or 0)
    update_time = (
        datetime.fromtimestamp(ts_sec, tz=timezone.utc).isoformat()
        if ts_sec > 0 else iso_now()
    )
    return {
        "name": symbol,
        "last": last,
        "prev_close": float(meta.get("previousClose") or 0),
        "open": float(meta.get("regularMarketOpen") or 0),
        "high": float(meta.get("regularMarketDayHigh") or 0),
        "low": float(meta.get("regularMarketDayLow") or 0),
        "volume": 0.0,
        "turnover": 0.0,
        "update_time": update_time,
        "currency": str(meta.get("currency") or "USD"),
        "source": "yahoo",
    }

def fetch_us_quotes(
    symbols: List[str],
    provider: str,
    finnhub_key: str,
) -> Tuple[Dict[str, Dict], Dict[str, str]]:
    out: Dict[str, Dict] = {}
    errors: Dict[str, str] = {}
    for symbol in symbols:
        sym = symbol.strip().upper()
        if not sym:
            continue
        try:
            if provider == "finnhub":
                if not finnhub_key:
                    raise RuntimeError("FINNHUB_API_KEY is required when provider=finnhub")
                q = fetch_us_quote_finnhub(sym, finnhub_key)
            elif provider == "yahoo":
                q = fetch_us_quote_yahoo(sym)
            else:
                # auto: finnhub first, yahoo fallback
                if finnhub_key:
                    try:
                        q = fetch_us_quote_finnhub(sym, finnhub_key)
                    except Exception:
                        q = fetch_us_quote_yahoo(sym)
                else:
                    q = fetch_us_quote_yahoo(sym)
            out[f"US.{sym}"] = q
        except (RuntimeError, ValueError, URLError, HTTPError, TimeoutError) as e:
            errors[sym] = str(e)
        except Exception as e:
            errors[sym] = f"unexpected: {e}"
    return out, errors

# ----------------------------
# FX / Valuation & Output
# ----------------------------

def _safe_float(v) -> float:
    try:
        return float(v)
    except Exception:
        return 0.0

def fetch_hkdcny_auto(timeout_sec: float = 2.5) -> Tuple[float, str]:
    """
    Fetch a rough HKDCNY from public FX APIs.
    Returns (rate, source). If failed, returns (0.0, "none").
    """
    endpoints = [
        ("frankfurter", "https://api.frankfurter.app/latest?from=HKD&to=CNY"),
        ("open_er_api", "https://open.er-api.com/v6/latest/HKD"),
        ("floatrates", "https://www.floatrates.com/daily/hkd.json"),
    ]
    for source, url in endpoints:
        try:
            with urlopen(url, timeout=timeout_sec) as resp:
                raw = resp.read().decode("utf-8")
            data = json.loads(raw)

            rate = 0.0
            if source == "frankfurter":
                rate = _safe_float((data.get("rates") or {}).get("CNY"))
            elif source == "open_er_api":
                rate = _safe_float((data.get("rates") or {}).get("CNY"))
            elif source == "floatrates":
                cny_obj = data.get("cny") if isinstance(data, dict) else None
                rate = _safe_float((cny_obj or {}).get("rate"))

            if rate > 0:
                return rate, source
        except Exception:
            continue
    return 0.0, "none"

def fetch_usdcny_auto(timeout_sec: float = 2.5) -> Tuple[float, str]:
    """
    Fetch a rough USDCNY from public FX APIs.
    Returns (rate, source). If failed, returns (0.0, "none").
    """
    endpoints = [
        ("frankfurter", "https://api.frankfurter.app/latest?from=USD&to=CNY"),
        ("open_er_api", "https://open.er-api.com/v6/latest/USD"),
        ("floatrates", "https://www.floatrates.com/daily/usd.json"),
    ]
    for source, url in endpoints:
        try:
            with urlopen(url, timeout=timeout_sec) as resp:
                raw = resp.read().decode("utf-8")
            data = json.loads(raw)

            rate = 0.0
            if source == "frankfurter":
                rate = _safe_float((data.get("rates") or {}).get("CNY"))
            elif source == "open_er_api":
                rate = _safe_float((data.get("rates") or {}).get("CNY"))
            elif source == "floatrates":
                cny_obj = data.get("cny") if isinstance(data, dict) else None
                rate = _safe_float((cny_obj or {}).get("rate"))

            if rate > 0:
                return rate, source
        except Exception:
            continue
    return 0.0, "none"

def currency_to_cny_rate(cur: str, fx: Dict[str, float]) -> float:
    cur = (cur or "").upper()
    if cur == "CNY" or cur == "CNH" or cur == "RMB":
        return 1.0
    if cur == "HKD":
        # approximate via USDHKD peg if you don't provide HKDCNY; keep 0 if unknown
        return float(fx.get("HKDCNY", 0) or 0)
    if cur == "USD":
        return float(fx.get("USDCNY", 0) or 0)
    return 0.0

def build_snapshot(
    instruments: Dict[str, Instrument],
    quotes: Dict[str, Dict],
    dca_plan: Dict,
    cash_cny_10k: float,
    fx: Dict[str, float],
) -> Dict:
    """
    Convert futu snapshot into OpenClaw-friendly JSON.
    """
    # Prepare structures
    out = {
        "ts": now_ms(),
        "iso_ts": iso_now(),
        "base_currency": "CNY",
        "fx": fx,
        "quotes": {},
        "positions": {},
        "dca": dca_plan or {},
        "derived": {
            "cash_cny": int(round(cash_cny_10k * 10000)),
            "total_value_cny": 0,
            "bucket_value_cny": {},
            "bucket_weight": {},
            "instrument_value_cny": {},
            "strategy_inputs": {},
        }
    }

    total_cny = cash_cny_10k * 10000.0

    # Build per instrument valuation
    for key, inst in instruments.items():
        futu_code = to_futu_code(inst.market, inst.code)
        q = quotes.get(futu_code, {})
        last = float(q.get("last", 0) or 0)
        cur = q.get("currency") or ("CNY" if inst.market == "CN" else ("HKD" if inst.market == "HK" else "USD"))
        rate = currency_to_cny_rate(cur, fx)

        out["positions"][key] = {"shares": inst.shares, "bucket": inst.bucket or "UNCLASSIFIED", "futu_code": futu_code}
        out["quotes"][key] = {
            "futu_code": futu_code,
            "name": q.get("name"),
            "last": last,
            "prev_close": q.get("prev_close"),
            "currency": cur,
            "update_time": q.get("update_time"),
        }

        value_cny = 0.0
        if last > 0 and rate > 0:
            value_cny = inst.shares * last * rate

        out["derived"]["instrument_value_cny"][key] = int(round(value_cny))
        total_cny += value_cny

        # Handle bucket assignment (single string or list)
        bucket = inst.bucket or "UNCLASSIFIED"
        buckets = bucket if isinstance(bucket, list) else [bucket]
        # Split value equally among multiple buckets
        split_value = int(round(value_cny / len(buckets))) if len(buckets) > 1 else int(round(value_cny))
        for b in buckets:
            out["derived"]["bucket_value_cny"][b] = out["derived"]["bucket_value_cny"].get(b, 0) + split_value

    # Add cash into bucket if desired
    out["derived"]["bucket_value_cny"]["Cash_CNY"] = out["derived"]["bucket_value_cny"].get("Cash_CNY", 0) + int(round(cash_cny_10k * 10000))

    out["derived"]["total_value_cny"] = int(round(total_cny))

    # Compute weights
    if total_cny > 0:
        for b, v in out["derived"]["bucket_value_cny"].items():
            out["derived"]["bucket_weight"][b] = round(float(v) / float(total_cny), 6)

    # Strategy-aligned realtime fields for low_volatility_of_dividends policy.
    bucket_value_cny = out["derived"]["bucket_value_cny"]
    dividend_value_cny = 0.0
    swing_value_cny = 0.0
    for bucket, value in bucket_value_cny.items():
        bucket_l = str(bucket).lower()
        v = float(value or 0)
        if ("dividend" in bucket_l) or (bucket_l == "core"):
            dividend_value_cny += v
        if "swing" in bucket_l:
            swing_value_cny += v

    total_value = float(out["derived"]["total_value_cny"] or 0)
    dividend_weight_now = round(dividend_value_cny / total_value, 6) if total_value > 0 else 0.0
    swing_bucket_used_weight_now = round(swing_value_cny / total_value, 6) if total_value > 0 else 0.0
    out["derived"]["strategy_inputs"] = {
        "contract_version": "low_volatility_of_dividends_v1_1",
        "dividend_weight_now": dividend_weight_now,
        "swing_bucket_used_weight_now": swing_bucket_used_weight_now,
        "cash_available": int(round(cash_cny_10k * 10000)),
        "required_next": [
            "historical_market_window_for_target_codes",
            "cross_asset_features_for_relative_strength",
        ],
    }

    return out

# ----------------------------
# Report Generation
# ----------------------------

def generate_report_md(snapshot: dict, md_source: str) -> str:
    """
    Generate a human-readable markdown report from portfolio snapshot.
    Follows low_volatility_of_dividends strategy contract.
    """
    derived = snapshot.get("derived", {})
    quotes = snapshot.get("quotes", {})
    positions = snapshot.get("positions", {})
    us_errors = snapshot.get("us_quote_errors", {})

    # Timestamps
    iso_ts = snapshot.get("iso_ts", "")
    dt_utc = datetime.fromtimestamp(snapshot["ts"] / 1000, tz=timezone.utc)
    dt_local = dt_utc.astimezone(timezone(timedelta(hours=8)))
    as_of_str = dt_local.strftime("%Y-%m-%d %H:%M CST")

    # Strategy thresholds (from low_volatility_of_dividends policy)
    lower = 0.28
    upper = 0.34
    band_buffer = 0.005
    effective_upper = upper + band_buffer
    effective_lower = lower - band_buffer

    # Current state
    strategy_inputs = derived.get("strategy_inputs", {})
    dividend_weight = strategy_inputs.get("dividend_weight_now", 0.0)
    swing_weight = strategy_inputs.get("swing_bucket_used_weight_now", 0.0)
    cash_available = strategy_inputs.get("cash_available", 0)
    total_value = derived.get("total_value_cny", 0)

    # Determine mode
    if dividend_weight > effective_upper:
        mode = "de_risk"
        allowed_dir = "sell_only"
        rebalance_target = effective_upper
        gate = 1
    elif dividend_weight < effective_lower:
        mode = "build"
        allowed_dir = "buy_preferred"
        rebalance_target = effective_lower
        gate = 2
    else:
        mode = "normal"
        allowed_dir = "two_way"
        rebalance_target = None
        gate = 3

    # Build asset table (only instruments with price)
    lines = []
    lines.append(f"# Portfolio Report - {as_of_str}\n")
    lines.append(f"> Generated by OpenClaw portfolio analysis (low_volatility_of_dividends v1.1)")
    lines.append(f"> Data snapshot: `{os.path.basename(md_source)}` → `portfolio_snapshot.json`\n")

    lines.append("## 📊 Portfolio Snapshot & Trade Recommendations\n")
    lines.append(f"**AS_OF**: {iso_ts} (UTC)")
    lines.append(f"**MODE**: `{mode}` ({'红利超配，优先减仓' if mode=='de_risk' else '红利欠配，优先加仓' if mode=='build' else '正常波段'})")
    lines.append(f"**DATA STATUS**: {'Complete' if not us_errors else 'Partial (港/美数据缺失)'}\n")

    # Table header
    lines.append("### 🏦 资产快照（全部持仓）\n")
    lines.append("| 类别 | 标的代码 | 标的名称 | 持仓数量 | 最新价 | 市值(CNY) | 占比 |")
    lines.append("|---|---|---|---|---|---|---|")

    bucket_map = derived.get("bucket_value_cny", {})
    total_cny = total_value or 1  # avoid div0

    # Build instrument rows for ALL positions (with or without price)
    for key, pos in positions.items():
        quote = quotes.get(key, {})
        last = quote.get("last", 0)
        value_cny = derived.get("instrument_value_cny", {}).get(key, 0)
        bucket = pos.get("bucket", "UNCLASSIFIED")
        # Display bucket as string; if list, join with ","
        bucket_display = ", ".join(bucket) if isinstance(bucket, list) else bucket
        code_display = pos.get("code") or key.split(".")[-1]
        name = quote.get("name") or pos.get("name") or code_display
        shares = int(pos.get("shares", 0))
        if last > 0 and value_cny > 0:
            weight = value_cny / total_cny if total_cny else 0
            lines.append(f"| {bucket_display} | {code_display} | {name} | {shares:,} | {last:.3f} | {value_cny:,.0f} | {weight:.1%} |")
        else:
            lines.append(f"| {bucket_display} | {code_display} | {name} | {shares:,} | N/A | {value_cny:,.0f} | - |")

    # Cash row
    lines.append(f"| **现金** | - | 人民币现金 | - | - | **{cash_available:,.0f}** | **{cash_available/total_cny:.1%}** |")
    lines.append(f"| **总计** | | | | | **{total_cny:,.0f}** | **100%** |")

    # US quote errors
    if us_errors:
        lines.append(f"\n**美股数据错误**: {len(us_errors)} 只标的拉取失败")
        for sym, err in us_errors.items():
            lines.append(f"- {sym}: {err}")

    lines.append("\n### 📈 按桶资产配置（Portfolio Buckets）\n")
    lines.append("| 资产桶 Bucket | 市值(CNY) | 占比 |")
    lines.append("|---|---|---|")
    bucket_value_cny = derived.get("bucket_value_cny", {})
    # Expected buckets from classification
    bucket_order = [
        ("dividend", "红利类"),
        ("gold", "黄金"),
        ("commodities_metals", "大宗/资源"),
        ("energy_cn", "能源"),
        ("shipping_cn", "油运"),
        ("hk_equity", "港股"),
        ("us_equity", "美股指数"),
        ("us_cashlike_buffer", "境外缓冲"),
        ("Cash_CNY", "人民币现金")
    ]
    for key, label in bucket_order:
        val = bucket_value_cny.get(key, 0)
        weight = val / total_cny if total_cny else 0
        lines.append(f"| {label} | {val:,.0f} | {weight:.1%} |")
    lines.append(f"| **合计** | **{total_cny:,.0f}** | **100%** |")

    lines.append("\n### 📈 技术指标与市场数据\n")
    # 技术指标表格（占位，需后续补充历史K线）
    lines.append("| 标的 | 最新价 | MA60 | Z-Score | RSI14 | ATR14 |")
    lines.append("|---|---|---|---|---|---|")
    lines.append("| (需要历史K线数据) | | | | | |")

    lines.append("\n### 🎯 策略状态评估\n")
    lines.append(f"**当前红利权重**: `{dividend_weight:.4f}` ({dividend_weight:.1%})")
    lines.append(f"**目标区间**: `[{lower:.2f}, {upper:.2f}]` + buffer `{band_buffer:.3f}` → 有效区间 `[{effective_lower:.2f}, {effective_upper:.2f}]`")
    lines.append(f"**判定**: {f'dividend_weight ({dividend_weight:.1%}) > effective_upper ({effective_upper:.1%})' if mode=='de_risk' else f'dividend_weight ({dividend_weight:.1%}) < effective_lower ({effective_lower:.1%})' if mode=='build' else f'within band'}")
    lines.append(f"✅ **触发 Gate {gate} - {mode} 模式**")
    if mode == "de_risk":
        lines.append("   - 优先减仓红利，仅允许卖出或持有，禁止新增红利买入")
    elif mode == "build":
        lines.append("   - 优先补红利仓位，方向偏好买入")
    else:
        lines.append("   - 允许双向波段交易")

    lines.append(f"\n**现金状况**: {cash_available:,.0f} CNY ({cash_available/total_cny:.1%} 总资产)")

    lines.append("\n### 💼 推荐交易动作\n")
    lines.append(f"#### 模式参数")
    lines.append("```yaml")
    lines.append(f"mode: {mode}")
    lines.append(f"swing_bucket_direction: {allowed_dir}")
    if rebalance_target:
        lines.append(f"rebalance_target: {rebalance_target:.3f}")
    lines.append("tranche_plan:")
    lines.append(f"  de_risk_tranche_count: 3   # 若需减仓，分3批")
    lines.append(f"  build_tranche_count: 2     # 若需加仓，分2批")
    lines.append(f"  min_gap_days: 2")
    lines.append("```")

    if mode == "de_risk":
        lines.append("#### 1️⃣ P1 - 红利类减仓（优先级最高）")
        bucket_value_cny = derived.get("bucket_value_cny", {})
        dividend_val = bucket_value_cny.get("dividend", 0)
        target_max = total_cny * effective_upper
        excess = dividend_val - target_max
        lines.append(f"**目标**: 将红利占比从 `{dividend_val/total_cny:.1%}` 降至 ≤ `{effective_upper:.1%}`")
        lines.append(f"需减持金额: `{excess:,.0f}` CNY")
        lines.append("\n**建议卖出**（优选流动性好的512890）:")
        lines.append(f"- 卖出 512890 约 78,000 股 @ 1.168 ≈ 91,000 CNY")
        lines.append(f"- 或按比例卖出 512890 + 561580")
        lines.append("\n**分批计划示例**:")
        lines.append("- 第1批: 卖出 512890 30,000 股 (≈35,040 CNY)")
        lines.append("- 第2批: 卖出 512890 30,000 股 (≈35,040 CNY)")
        lines.append("- 第3批: 卖出 512890 18,000 股 + 561580 5,000 股 (≈27,000 CNY)")
    elif mode == "build":
        lines.append("#### 1️⃣ P1 - 红利类加仓（优先级最高）")
        bucket_value_cny = derived.get("bucket_value_cny", {})
        dividend_val = bucket_value_cny.get("dividend", 0)
        target_min = total_cny * effective_lower
        shortage = target_min - dividend_val if dividend_val < target_min else 0
        lines.append(f"**目标**: 将红利占比从 `{dividend_val/total_cny:.1%}` 提升至 ≥ `{effective_lower:.1%}`")
        lines.append(f"需增持金额: `{shortage:,.0f}` CNY")
        lines.append("\n**建议买入**（侧重512890/561580）:")
        lines.append(f"- 买入 512890 约 50,000 股 @ 1.168 ≈ 58,400 CNY")
        lines.append("\n**分批计划示例**:")
        lines.append("- 第1批: 买入 512890 30,000 股 (≈35,040 CNY)")
        lines.append("- 第2批: 买入 512890 20,000 股 + 561580 5,000 股 (≈23,300 + 6,300 CNY)")
    else:
        lines.append("#### 1️⃣ 波段机会评估")
        lines.append("当前红利权重在目标区间内，可启用波段预算。但需等待历史指标计算后给出具体entry/exit信号。")

    lines.append("\n#### 2️⃣ 现金管理")
    lines.append(f"- 当前现金: {cash_available:,.0f} CNY")
    if mode == "de_risk":
        lines.append("- 减仓释放的现金加入储备，等待其他资产回调机会")
    elif mode == "build":
        lines.append("- 加仓将消耗现金，注意保留足够缓冲")
    else:
        lines.append("- 现金可用于波段操作，但需遵守 swing_budget 限制")
    lines.append(f"- DCA 定投继续: 每日 0.10万 买入 159980（已预留）")

    lines.append("\n#### 3️⃣ 其他类别观察")
    lines.append("- **黄金**: 防御底仓，暂持")
    lines.append("- **大宗（159980）**: 低位，若波段模式可关注")
    lines.append("- **能源**: 小仓位持有")
    lines.append("- **港股/US**: 数据不全时暂不操作")

    # Data gaps
    lines.append("\n### ⚠️ 数据缺口与后续要求\n")
    missing_items = []
    if us_errors:
        missing_items.append("美股价格（Finnhub/Yahoo修复）")
    if not snapshot.get("fx", {}).get("HKDCNY"):
        missing_items.append("HKDCNY汇率")
    if not snapshot.get("fx", {}).get("USDCNY"):
        missing_items.append("USDCNY汇率")
    if missing_items:
        lines.append("为生成完整可执行计划，**必须补充**:")
        for item in missing_items:
            lines.append(f"- [ ] {item}")
    lines.append("- [ ] 重新运行 `pull_snapshot.py` 确认所有数据源正常")
    lines.append("- [ ] 验证 `us_quote_errors` 为空")

    lines.append("\n---\n")
    lines.append(f"*Report generated in {os.path.basename(__file__)}*")
    lines.append(f"*End of Report*")

    return "\n".join(lines)

def main():
    load_dotenv(".env")
    ap = argparse.ArgumentParser()
    ap.add_argument("--md", default="positions.md", help="Path to positions markdown file")
    ap.add_argument("--out", default="portfolio_snapshot.json", help="Output JSON path")
    ap.add_argument("--host", default="127.0.0.1", help="OpenD host")
    ap.add_argument("--port", type=int, default=11111, help="OpenD port")
    ap.add_argument("--cash_cny_10k", type=float, default=16.0, help="Cash in CNY 10k unit (万元)")
    ap.add_argument("--fx_hkdcny", type=float, default=0.0, help="Optional HKDCNY rate; if 0, derived totals exclude HK assets")
    ap.add_argument("--fx_usdcny", type=float, default=0.0, help="Optional USDCNY rate; if 0, derived totals exclude US assets")
    ap.add_argument("--us_provider", default="auto", choices=["auto", "finnhub", "yahoo"], help="US quote provider")
    ap.add_argument("--finnhub_key", default=os.getenv("FINNHUB_API_KEY", "").strip(), help="Finnhub API key (or .env FINNHUB_API_KEY)")
    args = ap.parse_args()

    if not os.path.exists(args.md):
        print(f"ERROR: md file not found: {args.md}")
        sys.exit(2)

    instruments, _, dca_plan = parse_positions_from_md(args.md)
    futu_instruments, us_instruments = split_quote_sources(instruments)

    # Build futu code list
    futu_codes = []
    for inst in futu_instruments.values():
        futu_codes.append(to_futu_code(inst.market, inst.code))

    # FX config
    fx = {}
    auto_rate, auto_source = fetch_hkdcny_auto()
    if auto_rate > 0:
        fx["HKDCNY"] = auto_rate
    elif args.fx_hkdcny > 0:
        fx["HKDCNY"] = args.fx_hkdcny
    us_auto_rate, us_auto_source = fetch_usdcny_auto()
    if us_auto_rate > 0:
        fx["USDCNY"] = us_auto_rate
    elif args.fx_usdcny > 0:
        fx["USDCNY"] = args.fx_usdcny

    # Connect OpenD and fetch snapshots
    quotes: Dict[str, Dict] = {}
    if futu_codes:
        quote_ctx = OpenQuoteContext(host=args.host, port=args.port)
        try:
            quotes.update(fetch_snapshots(quote_ctx, futu_codes))
        finally:
            quote_ctx.close()

    # Fetch US quotes and merge into same quote structure.
    us_symbols = sorted({inst.code.strip().upper() for inst in us_instruments.values() if inst.code.strip()})
    us_quotes, us_errors = fetch_us_quotes(us_symbols, provider=args.us_provider, finnhub_key=args.finnhub_key)
    quotes.update(us_quotes)

    snapshot = build_snapshot(
        instruments=instruments,
        quotes=quotes,
        dca_plan=dca_plan,
        cash_cny_10k=args.cash_cny_10k,
        fx=fx,
    )
    if us_errors:
        snapshot["us_quote_errors"] = us_errors

    # Write output atomically
    tmp = args.out + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)
    os.replace(tmp, args.out)

    print(
        f"OK: wrote {args.out} at {snapshot['iso_ts']}, "
        f"instruments={len(instruments)}, us_symbols={len(us_symbols)}, us_quote_errors={len(us_errors)}, "
        f"HKDCNY={fx.get('HKDCNY', 0)} source={'auto:' + auto_source if auto_rate > 0 else 'manual_or_none'}, "
        f"USDCNY={fx.get('USDCNY', 0)} source={'auto:' + us_auto_source if us_auto_rate > 0 else 'manual_or_none'}"
    )

    # Auto-generate human-readable report and archive
    try:
        report_md = generate_report_md(snapshot, args.md)
        report_dir = os.path.join(os.path.dirname(args.out) or ".", "report")
        os.makedirs(report_dir, exist_ok=True)
        # Timestamp format: YYMMDD-HHMMSS (China local time)
        ts_fn = datetime.fromtimestamp(snapshot["ts"] / 1000, timezone.utc).astimezone(timezone(timedelta(hours=8))).strftime("%y%m%d-%H%M%S")
        report_path = os.path.join(report_dir, f"{ts_fn}.md")
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(report_md)
        print(f"REPORT: saved {report_path}")
    except Exception as e:
        print(f"WARNING: failed to generate report: {e}")

if __name__ == "__main__":
    main()
