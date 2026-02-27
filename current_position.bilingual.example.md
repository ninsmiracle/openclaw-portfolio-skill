# Portfolio Position Template / 持仓模板（双语示例）

> 这是一个开源示例文件，复制为 `current_position.md` 后改成你的真实数据。
> This is an open-source example. Copy to `current_position.md` and customize with your data.

---

## 📋 1. As-of Snapshot / 快照

- **现金（CNY）**：`现金金额 万` (e.g., `16.00 万`)
- **总资产（约）**：`总金额 万` (自动计算)

---

## 📊 2. Holdings Table / 持仓表

### 2.1 CN/HK Holdings / 境内/香港持仓

| AssetClass / 资产类别 | Market / 市场 | Code / 代码 | Name / 名称 | Amount_CNY_10k / 金额(万) | Shares / 股数 |
|---|---|---:|---|---:|---:|
| Gold/Defensive | CN | 518880 | 黄金ETF | 0.00 | 0 |
| Dividend/Defensive | CN | 512890 | 红利低波ETF | 0.00 | 0 |
| Energy | CN | 603393 | 新天然气 | 0.00 | 0 |
| Shipping | CN | 600026 | 中远海能 | 0.00 | 0 |

### 2.2 US Holdings / 美国持仓

| AssetClass / 资产类别 | Market / 市场 | Ticker / 代码 | Name / 名称 | Amount_USD_k / 金额(k) | Shares / 股数 |
|---|---|---|---|---:|---:|
| US Tech/Growth | US | QQQ | Invesco QQQ | 0.00 | 0 |

---

## 🗂️ 3. Classification Map / 分类映射

```yaml
# 每个资产可以属于多个桶（多桶支持）。如果同时在多个桶出现，其市值会自动平均拆分。
# Each instrument can belong to multiple buckets. If listed in multiple buckets, its market value is split equally.
asset_buckets:
  dividend:                    # 红利/防御类
    - {market: CN, code: "512890", name: "红利低波ETF"}
  gold:                       # 黄金/防御类
    - {market: CN, code: "518880", name: "黄金ETF"}
  energy_cn:                  # 能源类（中国）
    - {market: CN, code: "603393", name: "新天然气"}
  shipping_cn:                # 航运类（中国）  
    - {market: CN, code: "600026", name: "中远海能"}
  us_equity:                  # 美股权益类
    - {market: US, code: "QQQ", name: "QQQ"}
  cash_cny:                   # 现金（人民币）
    - {market: CN, code: "CASH", name: "现金人民币"}
```

---

## 💰 4. DCA Plan / 定投计划（自动计算未来资产变化）

本 Skill **支持自动计算定投对资产配置的影响**。设定 `dca_plan` 后，每次生成快照时会：

1. **计算当前持仓**（基于 snapshot 当日的真实价格）
2. **叠加未来定投现金流**：
   - 追加现金买入目标标的（按当前价格预估股数）
   - 扣除 `cash_source` 账户的现金
3. **生成调整后快照**：展示如果执行定投，未来持仓会如何变化
4. **给出再平衡建议**：对比定投后各桶占比 vs 目标比例

### 4.1 DCA 配置示例

```yaml
dca_plan:
  enabled: true                      # 启用定投模拟
  target:
    market: CN                       # 定投标的市场：CN 或 US
    code: "512890"                   # 定投代码（必须）
    name: "红利低波ETF"              # 定投名称
  frequency: "EVERY_TRADING_DAY"    # 频率：EVERY_TRADING_DAY | WEEKLY | MONTHLY
  amount_cny_10k: 0.50              # 每期定投金额（万人民币）
  periods: 10                        # 模拟未来多少期（e.g., 10个交易日或10周/月）
  cash_source:
    market: CN                       # 现金来源市场
    code: "CASH"                     # 现金账户代码（必须，表示从哪扣款）
```

### 4.2 支持的频率与 Periods 含义

| `frequency` | `periods` 的含义 |
|---|---|
| `EVERY_TRADING_DAY` | 未来 N 个交易日 |
| `WEEKLY` | 未来 N 周（每7天一次） |
| `MONTHLY` | 未来 N 个月（每月一次） |

### 4.3 定投输出效果

启用 DCA 后，报告将增加：

```
📈 定投模拟 (DCA Simulation)
计划：每天定投红利低波ETF 0.50万，共10个交易日
现金源：现金人民币 → -5.00万
预期新增：红利低波ETF +0.XX% (价格按当前价估算)
调整后桶分布：dividend 42.1% (+3.2%), gold 10.0%, ...
建议：定投后 dividend 桶略超上限，可考虑单次再平衡
```

---

## 🛠️ 5. Usage / 使用说明

1. **复制本文件**：
   ```bash
   cp current_position.bilingual.example.md current_position.md
   ```

2. **编辑 `current_position.md`**：
   - 修改 `1. As-of Snapshot` 的现金金额
   - 在 `2. Holdings Table` 填写你的持仓（股数、标的代码）
   - 在 `3. Classification Map` 调整 `asset_buckets`，确保所有持仓都在某个桶中
   - （可选）设置 `4. DCA Plan` 参数

3. **运行快照**：
   ```bash
   uv run pull_snapshot.py \
     --md current_position.md \
     --out portfolio_snapshot.json \
     --cash_cny_10k 16.00 \
     --cnhk_provider auto \
     --us_provider auto
   ```

4. **查看报告**：
   ```bash
   cat report/$(date +%y%m%d-%H%M%S).md
   ```

5. **Skill 触发**：
   - 对 OpenClaw 说："今天的交易机会有哪些？"
   - 或："生成资产报告"
   - 或："定投模拟"

---

## 🔐 6. Privacy Notice / 隐私提示

- 本文件是**示例**，真实持仓数据请勿提交到公开仓库
- `current_position.md`、`.env`、`portfolio_snapshot.json`、`report/` 已在 `.gitignore` 中
- 发布前运行 `uv run check_privacy.py` 确保无敏感数据泄露

---

## 📚 7. Full Documentation / 完整文档

详见项目主 README：https://github.com/ninsmiracle/openclaw-portfolio-skill
