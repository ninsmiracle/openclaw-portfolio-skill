# Eastmoney 最小验证指南

## 目标

验证在**不登录 Futu OpenD** 的情况下，`pull_snapshot.py` 能通过东方财富链路拉取 A 股/港股行情并生成快照。

## 是否需要 API 配置

- 东方财富链路：**不需要 API Key**
- 美股链路（可选）：
  - `--us_provider yahoo`：不需要 key
  - `--us_provider finnhub`：需要 `.env` 里配置 `FINNHUB_API_KEY`

## 前置条件

1. 已有 `current_position.md`（可用 `uv run init_current_position.py` 生成）
2. 当前目录在项目根目录（包含 `pull_snapshot.py`）

## 最小验证命令（仅验证 CN/HK）

```bash
uv run pull_snapshot.py \
  --md current_position.md \
  --out test_snapshot.json \
  --cash_cny_10k 10 \
  --cnhk_provider eastmoney \
  --us_provider yahoo
```

## 预期结果

命令成功后你会看到：

- 终端输出 `OK: wrote test_snapshot.json ...`
- 生成 `test_snapshot.json`
- `quotes` 中 CN/HK 标的存在且 `last > 0`
- 对应条目 `source` 为 `eastmoney`

## 快速检查（可选）

```bash
python3 - <<'PY'
import json
f='test_snapshot.json'
d=json.load(open(f,'r',encoding='utf-8'))
q=d.get('quotes',{})
ok=[(k,v.get('last'),v.get('source'),v.get('currency')) for k,v in q.items() if (k.startswith('CN.') or k.startswith('HK.'))]
print('CN/HK quotes:', len(ok))
print('sample:', ok[:5])
print('all_valid_last:', all((x[1] or 0)>0 for x in ok))
PY
```

## 常见问题

- 报网络错误：
  - 检查本机网络与 DNS；东方财富链路需要公网访问。
- 价格明显异常：
  - 脚本已内置自动缩放与合理性校验（含参考上一版快照）；若首次运行仍异常，重跑一次让参考价生效。
- 从子目录运行时报找不到脚本：
  - 请在项目根目录执行，或使用脚本相对路径（例如 `uv run ../pull_snapshot.py`）。
