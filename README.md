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

或复制双语模板（推荐）：

```bash
cp current_position.bilingual.example.md current_position.md
```

或旧版中文模板：

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

---

## 📦 作为 OpenClaw Skill 使用

本项目已打包为 OpenClaw skill，可通过自然语言触发。

### 安装

```bash
# 使用 clawhub 安装（推荐）
clawhub install openclaw-portfolio-skill

# 或手动克隆到skills目录
git clone https://github.com/ninsmiracle/openclaw-portfolio-skill.git ~/.openclaw/skills/openclaw-portfolio-skill
```

安装后重启网关或等待自动加载。

### 触发方式

对 OpenClaw 说以下任一语句：

- "今天的交易机会有哪些？"
- "生成资产报告"
- "持仓分析"
- "再平衡建议"
- "跑一下 portfolio 快照"

Skill 会自动：
1. 读取 `current_position.md` 提取现金
2. 调用 `pull_snapshot.py` 生成快照
3. 生成 Markdown 报告并通过原渠道返回
4. 将报告存档到 `report/YYMMDD-HHMMSS.md`

### 配置要求

- OpenD（Futu）运行在 `127.0.0.1:11111`（CN/HK 行情）
- 可选：`.env` 中设置 `FINNHUB_API_KEY`（US 行情，避免 Yahoo 失败）
- 持仓文件：`current_position.md`（需包含 `asset_buckets` 分类定义）

### 定时任务

设置每日 14:30 自动推送：

```bash
openclaw cron add --name "Portfolio Daily Report" \
  --expr "30 14 * * 1-5" \
  --tz "Asia/Shanghai" \
  --message "使用 portfolio-thin skill 生成今天的交易机会报告" \
  --channel feishu \
  --to ou_你的用户ID
```

---

### 🔌 外部 Webhook 推送（可选）

如需将报告同时推送到第三方群聊机器人（如飞书群机器人），可在项目根目录创建 `.portfolio_webhook` 文件，内容为 Webhook URL。该文件已加入 `.gitignore`，确保不会意外提交。

当文件存在时，`pull_snapshot.py` 会在生成报告后自动 POST 报告全文到该 URL（Feishu 机器人消息格式）。URL 仅存储在本地，**不会暴露到公网**。

示例：
```bash
echo "https://open.feishu.cn/open-apis/bot/v2/hook/xxxx" > .portfolio_webhook
```

> **提示**：Webhook 推送在报告生成后异步执行，不会影响主流程。若推送失败，错误会输出到 stderr（不中断任务）。


---

## 🧮 定投模拟（DCA）功能

本 Skill **可以自动计算定投对资产的未来影响**。在 `current_position.md` 中配置 `dca_plan` 后：

- **自动叠加现金流**：按当前价格预估未来 N 期定投后的持仓变化
- **调整后快照**：展示定投完成后各资产桶的占比
- **再平衡建议**：如果定投导致某个桶超限，会提前提醒

### 示例配置

```yaml
dca_plan:
  enabled: true
  target:
    market: CN
    code: "512890"         # 定投标的：红利低波ETF
    name: "红利低波ETF"
  frequency: "EVERY_TRADING_DAY"
  amount_cny_10k: 0.50     # 每天定投 0.5 万元
  periods: 10              # 模拟未来 10 个交易日
  cash_source:
    market: CN
    code: "CASH"           # 从现金账户扣款
```

**效果**：
```
📈 定投模拟 (DCA Simulation)
计划：每天定投红利低波ETF 0.50万，共10个交易日
现金源：现金人民币 → -5.00万
预期新增：红利低波ETF +0.XX% (价格按当前价)
调整后桶分布：dividend 42.1% (+3.2%), gold 10.0%, ...
建议：定投后 dividend 桶略超上限，可等定投结束后再平衡
```

### 支持的频率

- `EVERY_TRADING_DAY`: 每个交易日（适合 A 股/港股）
- `WEEKLY`: 每周一次
- `MONTHLY`: 每月一次

**提示**：定投金额和期数 (`periods`) 乘积会从现金源扣除，请确保现金充足。

---

## 🔧 开发与贡献

### 项目结构

```
.
├── pull_snapshot.py          # 主脚本（uv 管理依赖）
├── portfolio_snapshot.json   # 生成快照（gitignore）
├── report/                   # 自动生成的报告（gitignore）
├── current_position.md      # 持仓文件（用户维护，gitignore）
├── strategy/                 # 策略文档与函数契约
├── SKILL.md                  # OpenClaw skill 定义（自动加载）
└── pyproject.toml           # 依赖：futu-api, pyyaml
```

### 本地运行测试

```bash
# 安装依赖
uv sync

# 生成快照
uv run pull_snapshot.py --md current_position.md --out test.json --cash_cny_10k 16.00 --us_provider auto

# 查看报告
cat report/$(date +%y%m%d-%H%M%S).md
```

### 多桶分类说明

`current_position.md` 中的 `asset_buckets` 支持一个标的同时属于多个桶。例如：

```yaml
asset_buckets:
  energy_cn:
    - {market: CN, code: "603393", name: "新天然气"}
  shipping_cn:
    - {market: CN, code: "600026", name: "中远海能"}
```

如果希望 `600026` 同时计入 `energy_cn` 和 `shipping_cn`，只需在两个桶中都列出。脚本会自动**平均拆分市值**。

### 隐私保护

- `current_position.md`、`.env`、`portfolio_snapshot.json`、`report/` 已加入 `.gitignore`
- 发布前运行 `uv run check_privacy.py` 自检
- 建议使用 `current_position.example.md` 作为模板，真实数据不提交

---

## 📄 许可证

MIT License - 详见 [LICENSE](LICENSE) 文件

---

## 🙏 致谢

- 飞书/富途/Yahoo Finance 提供行情源
- OpenClaw 社区提供技能框架
