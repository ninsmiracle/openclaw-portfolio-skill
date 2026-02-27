# Portfolio Snapshot (Example)

> 这是开源示例文件，请复制为 `current_position.md` 后改成你自己的数据。

## 1. As-of Snapshot

- **现金（CNY）**：`10.00 万`

## 2. Holdings Table

### 2.1 CN/HK Holdings

| AssetClass | Market | Code | Name | Amount_CNY_10k | Shares |
|---|---|---:|---|---:|---:|
| Gold/Defensive | CN | 518880 | 黄金ETF | 0.00 | 0 |
| Dividend/Defensive | CN | 512890 | 红利低波ETF | 0.00 | 0 |

### 2.2 US Holdings

| AssetClass | Market | Ticker | Name | Amount_USD_k | Shares |
|---|---|---|---|---:|---:|
| US Tech/Growth | US | QQQ | Invesco QQQ | 0.00 | 0 |

## 3. Classification Map

```yaml
asset_buckets:
  dividend:
    - {market: CN, code: "512890", name: "红利低波ETF"}
  gold:
    - {market: CN, code: "518880", name: "黄金ETF"}
  us_equity:
    - {market: US, code: "QQQ", name: "QQQ"}
  cash_cny:
    - {market: CN, code: "CASH", name: "现金人民币"}
```

## 4. DCA Plan

```yaml
dca_plan:
  enabled: false
  target:
    market: CN
    code: ""
    name: ""
  frequency: "EVERY_TRADING_DAY"
  amount_cny_10k: 0.00
  cash_source:
    market: CN
    code: "CASH"
```
