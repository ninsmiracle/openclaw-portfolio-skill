# OpenClaw Portfolio Skill（简版）

这个项目是一个“轻量持仓快照 + 策略建议”工作流，核心产物是 `portfolio_snapshot.json` 和 `report/*.md`。

## 这个 Skill 的主要特点

- **不接入交易账户**：不需要券商账号登录，不读取账户权限，不下单。
- **用户自报持仓**：只基于你初始化时提供的“有哪些品种、买了多少股/份额、现金多少”来计算。
- **默认隐私友好**：`current_position.md`、`.env`、快照和报告都已加入 `.gitignore`。
- **可开源协作**：任何人可用相同模板复用流程，不暴露你的真实资产数据。

## 一般使用流程（首次到日常）

1. **首次初始化持仓**

```bash
uv run init_current_position.py
```

或复制模板：

```bash
cp current_position.example.md current_position.md
```

2. **拉取行情并生成快照**

```bash
uv run pull_snapshot.py \
  --md current_position.md \
  --out portfolio_snapshot.json \
  --cash_cny_10k 10 \
  --cnhk_provider auto \
  --us_provider auto
```

> 推荐保持 `--cnhk_provider auto`：可用时优先走 `futu`（通常质量更高），失败自动回退 `eastmoney`。

3. **开源前隐私自检**

```bash
uv run check_privacy.py
```

## 行情源说明

- `CN/HK`：`futu` 或 `eastmoney`（参数：`--cnhk_provider auto|futu|eastmoney`）
- `US`：`finnhub` 或 `yahoo`（参数：`--us_provider auto|finnhub|yahoo`）
- `finnhub` 需要可选配置：`.env` 中设置 `FINNHUB_API_KEY`

### 东方财富链路说明

- 东方财富链路 **不需要 API key**。
- 根据当前实测，东方财富接口通常在**中国大陆网络环境**更稳定；海外网络可能出现访问失败或不稳定。
- 建议先执行最小验证：`docs/eastmoney_validation.md`。

### Futu 链路说明（质量优先）

- `futu` 行情链路通常在快照完整性、字段稳定性上更优，适合做主链路。
- 使用前需要本地启动 OpenD（默认 `127.0.0.1:11111`）。
- 如果你已具备 Futu 环境，建议：
  - 生产/日常：`--cnhk_provider auto`（主用 futu，失败回退 eastmoney）
  - 强制只走 futu：`--cnhk_provider futu`

## Strategy Demo（`strategy/`）

- `strategy/low_volatility_of_dividends.md`
  - 红利低波策略示例，强调资产桶约束、再平衡闸门、风控校验和函数调用契约。
- `strategy/glod.md`
  - 黄金（`518880`）日线九转（TD Setup 9）策略示例，主张 Buy 9 偏开仓、Sell 9 偏减仓。

## 关键输入与输出

- 输入：`current_position.md`（用户维护的持仓与现金）
- 输出：
  - `portfolio_snapshot.json`（机器可读快照）
  - `report/*.md`（人类可读报告）

若使用 skill 且缺少 `current_position.md`，应先问答收集数据并创建该文件，再继续后续流程。
