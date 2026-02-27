# OpenClaw 调用说明（简版）

## 目标
- 由 AI（OpenClaw）定时调用脚本，生成统一的 `portfolio_snapshot.json`。
- `CN/HK` 行情来自 Futu OpenD；`US` 行情来自 Finnhub（失败回退 Yahoo）。

## 前置条件
- 我已经将项目uv化了，不用检查我的裸机的依赖
- OpenD 已启动：`127.0.0.1:11111`
- 持仓文件：`current_position.md`（本地私有，不要提交）
- 可选：在 `.env` 配置美股 key  
  `FINNHUB_API_KEY=你的key`

## 开源使用（首次初始化）

为了避免泄露私人信息，本仓库默认不跟踪你的真实持仓文件：

- `current_position.md` 已加入 `.gitignore`
- `.env` 已加入 `.gitignore`

首次使用请二选一：

1. 交互式问答生成（推荐）

```bash
uv run init_current_position.py
```

2. 从示例复制后手改

```bash
cp current_position.example.md current_position.md
```

> 如果你在使用 skill 时项目根目录不存在 `current_position.md`，应先询问用户持仓信息，再生成该文件。

开源前可执行隐私自检：

```bash
uv run check_privacy.py
```

## AI 推荐调用命令
```bash
# 先从 current_position.md 提取现金（单位：万元）
# 示例：匹配 `- **现金（CNY）**：`100.00 万`` -> 100.00
CASH_CNY_10K=$(python3 -c "import re; t=open('current_position.md','r',encoding='utf-8').read(); m=re.search(r'现金（CNY）\\*\\*：`\\s*([0-9]+(?:\\.[0-9]+)?)\\s*万`', t); print(m.group(1) if m else '0')")

uv run pull_snapshot.py \
  --md current_position.md \
  --out portfolio_snapshot.json \
  --host 127.0.0.1 \
  --port 11111 \
  --cash_cny_10k "$CASH_CNY_10K" \
  --us_provider auto
```

## 常用参数（仅 AI 需要知道这些）
- `--md`：持仓 markdown 路径
- `--out`：输出 JSON 路径（给 OpenClaw 读取）
- `--cash_cny_10k`：现金（单位：万元）
- `--us_provider`：`auto|finnhub|yahoo`，默认 `auto`
- `--finnhub_key`：可不传，默认读 `.env` 的 `FINNHUB_API_KEY`
- `--fx_hkdcny` / `--fx_usdcny`：手动汇率兜底（仅自动汇率失败时使用）

## 输出说明
- 主输出：`portfolio_snapshot.json`
- 结构重点：
  - `quotes`：各标的最新价
  - `positions`：份额与分桶
  - `derived.instrument_value_cny`：单标的人民币估值
  - `derived.total_value_cny`：总资产人民币估值
  - `us_quote_errors`：美股拉取失败明细（有失败时才出现）

## 调用约定（给 AI）
- 调用前必须先读取 `current_position.md`，从“`现金（CNY）`”字段提取最新现金值（单位：万元）。
- 若 `current_position.md` 不存在：先进入问答流程收集现金、持仓、资产桶，再创建文件；不要臆造默认仓位。
- 若提取失败，先重试读取一次；仍失败则使用上次成功值，并在日志中标记 `cash_parse_failed`。
- 若一次调用失败，重试 1 次；仍失败则保留上次快照并上报错误。
- `us_quote_errors` 非空时，不中断全局流程，继续使用已成功标的的估值结果。

## Redli 策略调用顺序（定时工作流）
1. 定时器触发：执行 `pull_snapshot.py` 生成最新 `portfolio_snapshot.json`。
2. 计算与聚合（代码层）：读取 `derived.bucket_weight` 与 `derived.strategy_inputs`，拿到 `dividend_weight_now`、`cash_available` 等确定性字段。
3. 特征补全（可扩展）：按策略需要补充历史窗口与跨资产特征（当前作为 `required_next` 输出）。
4. 规则闸门（代码层）：先判断 `de_risk/build/normal` 模式和硬约束边界。
5. 参数选择与动作建议（LLM层）：仅在边界内填写 `llm_tunable_params`，生成建议动作及理由。
6. 风控校验（代码层）：执行仓位区间、手数、现金、预算上限检查；不通过则返回 `data_needed` 或 `hold`。
