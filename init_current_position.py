#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
交互式生成 current_position.md（首次开源使用友好版）。

设计目标：
1) 避免把个人真实持仓提交到仓库
2) 让新用户通过问答快速生成可运行的 current_position.md
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict, List


@dataclass
class Holding:
    market: str
    code: str
    name: str
    shares: float
    bucket: str
    asset_class: str


def ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    text = input(f"{prompt}{suffix}: ").strip()
    return text if text else default


def ask_float(prompt: str, default: float = 0.0) -> float:
    while True:
        raw = ask(prompt, str(default))
        try:
            return float(raw)
        except ValueError:
            print("请输入数字，例如 16 或 16.5")


def ask_int(prompt: str, default: int = 0) -> int:
    while True:
        raw = ask(prompt, str(default))
        try:
            return int(raw)
        except ValueError:
            print("请输入整数，例如 3")


def collect_holdings() -> List[Holding]:
    print("\n=== 持仓录入（支持 CN / HK / US）===")
    count = ask_int("你要录入几只持仓", 0)
    holdings: List[Holding] = []

    for i in range(1, count + 1):
        print(f"\n--- 第 {i} 只 ---")
        market = ask("市场（CN/HK/US）", "CN").upper()
        while market not in {"CN", "HK", "US"}:
            print("仅支持 CN/HK/US")
            market = ask("市场（CN/HK/US）", "CN").upper()

        code = ask("代码（如 518880 / 09988 / QQQ）").upper()
        name = ask("名称（如 黄金ETF）", code)
        shares = ask_float("持仓份额/股数", 0.0)
        bucket = ask("资产桶（如 gold/dividend/us_equity）", "UNCLASSIFIED")
        asset_class = ask("资产类别标签（如 Gold/Defensive）", "Other")

        holdings.append(
            Holding(
                market=market,
                code=code,
                name=name,
                shares=shares,
                bucket=bucket,
                asset_class=asset_class,
            )
        )

    return holdings


def render_bucket_yaml(holdings: List[Holding]) -> str:
    bucket_map: Dict[str, List[Holding]] = {}
    for h in holdings:
        bucket_map.setdefault(h.bucket, []).append(h)

    lines = ["```yaml", "asset_buckets:"]
    if not bucket_map:
        lines.append("  cash_cny:")
        lines.append('    - {market: CN, code: "CASH", name: "现金人民币"}')
    else:
        for bucket, items in bucket_map.items():
            lines.append(f"  {bucket}:")
            for h in items:
                lines.append(
                    f'    - {{market: {h.market}, code: "{h.code}", name: "{h.name}"}}'
                )
        lines.append("  cash_cny:")
        lines.append('    - {market: CN, code: "CASH", name: "现金人民币"}')
    lines.append("```")
    return "\n".join(lines)


def render_md(cash_cny_10k: float, holdings: List[Holding]) -> str:
    cn_hk = [h for h in holdings if h.market in {"CN", "HK"}]
    us = [h for h in holdings if h.market == "US"]

    lines: List[str] = []
    lines.append("# Portfolio Snapshot (for OpenClaw)")
    lines.append("")
    lines.append("> 由 `init_current_position.py` 生成，可按需手工编辑。")
    lines.append("")
    lines.append("## 1. As-of Snapshot")
    lines.append("")
    lines.append(f"- **现金（CNY）**：`{cash_cny_10k:.2f} 万`")
    lines.append("")
    lines.append("## 2. Holdings Table")
    lines.append("")
    lines.append("### 2.1 CN/HK Holdings")
    lines.append("")
    lines.append("| AssetClass | Market | Code | Name | Amount_CNY_10k | Shares |")
    lines.append("|---|---|---:|---|---:|---:|")
    if cn_hk:
        for h in cn_hk:
            lines.append(
                f"| {h.asset_class} | {h.market} | {h.code} | {h.name} | 0.00 | {h.shares:g} |"
            )
    else:
        lines.append("| - | CN | 000000 | 示例占位 | 0.00 | 0 |")

    lines.append("")
    lines.append("### 2.2 US Holdings")
    lines.append("")
    lines.append("| AssetClass | Market | Ticker | Name | Amount_USD_k | Shares |")
    lines.append("|---|---|---|---|---:|---:|")
    if us:
        for h in us:
            lines.append(
                f"| {h.asset_class} | US | {h.code} | {h.name} | 0.00 | {h.shares:g} |"
            )
    else:
        lines.append("| - | US | QQQ | 示例占位 | 0.00 | 0 |")

    lines.append("")
    lines.append("## 3. Classification Map")
    lines.append("")
    lines.append(render_bucket_yaml(holdings))
    lines.append("")
    lines.append("## 4. DCA Plan")
    lines.append("")
    lines.append("```yaml")
    lines.append("dca_plan:")
    lines.append("  enabled: false")
    lines.append("  target:")
    lines.append('    market: CN')
    lines.append('    code: ""')
    lines.append('    name: ""')
    lines.append('  frequency: "EVERY_TRADING_DAY"')
    lines.append("  amount_cny_10k: 0.00")
    lines.append("  cash_source:")
    lines.append("    market: CN")
    lines.append('    code: "CASH"')
    lines.append("```")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    out = "current_position.md"
    if os.path.exists(out):
        overwrite = ask(f"{out} 已存在，是否覆盖？(y/N)", "N").lower()
        if overwrite not in {"y", "yes"}:
            print("已取消。")
            return

    print("=== current_position 初始化向导 ===")
    cash_cny_10k = ask_float("请输入现金（单位：万元）", 10.0)
    holdings = collect_holdings()
    content = render_md(cash_cny_10k, holdings)

    with open(out, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"\n已生成：{out}")
    print("下一步可运行：uv run pull_snapshot.py --md current_position.md --out portfolio_snapshot.json")


if __name__ == "__main__":
    main()
