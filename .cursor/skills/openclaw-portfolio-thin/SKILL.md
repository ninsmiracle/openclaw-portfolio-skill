---
name: openclaw-portfolio-thin
description: Orchestrates a thin OpenClaw portfolio workflow with fixed call sequence, fixed failure policy, and fixed output format. Use when user requests current market snapshot, DCA impact calculation, position updates in current_position.md, asset amount and total weight calculation, strategy opportunity scan from strategy/*.md, or explicit trade event phrases like "我今天卖了500股红利低波".
---

# OpenClaw Portfolio Thin Skill

## Scope

This skill is intentionally thin and only enforces:
1. Fixed call sequence
2. Fixed failure policy
3. Fixed response format

Do not invent new trading logic or override existing strategy parameters.

## Source Of Truth

- Global function call contract: `strategy/llm_function_call_contract.md`
- Rebalance/agent execution hints: `plan.md`
- Snapshot generator: `pull_snapshot.py`
- Position file to read/update: `current_position.md`
- Strategy docs to scan: `strategy/*.md`

Priority order is fixed:
1. `hard_risk_limits`
2. `strategy/llm_function_call_contract.md`
3. strategy-specific preferences in `strategy/*.md`

## Trigger Conditions

Use this skill when requests involve any of the following:
- Get latest market/portfolio status now
- Calculate DCA impact and update holdings
- Recompute per-asset amount and total allocation
- Scan strategy docs and report opportunities
- Natural-language trade events that imply position changes

## Fixed Call Sequence

Always execute in this sequence. Do not skip or reorder.

### Step -1: Bootstrap `current_position.md` (first use only)

Before any other step, check whether `current_position.md` exists in project root.

If file does not exist:
- Enter Q&A mode and ask user for:
  - cash (CNY, 万元)
  - holdings list (market, code/ticker, name, shares)
  - optional bucket mapping (if unknown, ask user to confirm `UNCLASSIFIED`)
- Generate `current_position.md` from user answers (do not invent holdings)
- Return `status=data_needed` if key fields are still missing after one clarification round
- Only continue to Step 0 after file creation succeeds

### Step 0: Trade Event Detection (pre-check)

Before snapshot pull, detect whether the user message contains explicit trade events.

Examples:
- `我今天卖了500股红利低波`
- `买入100股QQQ`
- `减仓央企红利ETF 200股`

If detected:
- Parse `action`, `instrument`, `quantity`, optional `price`/`time`
- Apply position delta to `current_position.md` first
- If required fields are missing, return `data_needed` with missing fields list

### Step 1: Get Current Snapshot

- Read `current_position.md`, extract cash field first
- Generate/refresh `portfolio_snapshot.json` via existing workflow based on `pull_snapshot.py`
- Use contract function identity: `get_portfolio_snapshot`

### Step 2: Compute DCA Impact And Position Update

- Compute DCA state from `current_position.md` + snapshot output
- Reflect DCA-caused position/cash delta in `current_position.md` when applicable
- Use contract function identity: `compute_bucket_weights` (for post-update aggregation)

### Step 3: Compute Asset Amounts And Weights

- Compute each asset amount and total allocation from latest snapshot + positions
- Required outputs include per-asset CNY amount, total CNY value, and bucket weights

### Step 4: Scan Strategy Docs For Opportunities

- Read `strategy/llm_function_call_contract.md` first, then scan other `strategy/*.md`
- Use market/position state to produce possible opportunities with evidence
- Contract-driven function chain (as needed): `get_market_window` -> `get_cross_asset_features` -> `evaluate_gates` -> `propose_trade_actions` -> `validate_risk_checks`

### Step 5: Finalize Output

- Return strictly with the fixed JSON schema below
- Then append a short Chinese summary (3-6 lines) that only restates JSON conclusions

## Fixed Failure Policy

Apply these rules exactly.

1. Cash parse failure:
   - Retry read/parse once
   - If still failed, use last successful cash value
   - Add error tag: `cash_parse_failed`

2. Snapshot pull failure:
   - Retry full pull once
   - If still failed, keep last valid snapshot and report failure in `errors`

3. US quote partial failure:
   - Preserve `us_quote_errors`
   - Do not abort global valuation if other assets are available

4. Missing required fields:
   - Return `status=data_needed`
   - Fill `data_needed_if_any`
   - Do not guess or synthesize missing values

5. Risk/constraint validation failure:
   - Allowed outputs only: `hold` or adjusted compliant actions
   - Never output executable non-compliant action

## Fixed Output Format

Always output this JSON object first, then the short Chinese summary.

```json
{
  "status": "ok|partial|data_needed|error",
  "as_of": "ISO-8601 datetime",
  "used_functions": [
    "get_portfolio_snapshot",
    "compute_bucket_weights",
    "get_market_window",
    "get_cross_asset_features",
    "evaluate_gates",
    "propose_trade_actions",
    "validate_risk_checks"
  ],
  "position_update": {
    "event_detected": true,
    "events_applied": [
      {
        "instrument": "512890",
        "action": "sell",
        "quantity": 500,
        "source_text": "我今天卖了500股红利低波"
      }
    ],
    "current_position_md_updated": true
  },
  "portfolio_metrics": {
    "per_asset_amount_cny": {
      "CN.512890": 0
    },
    "total_value_cny": 0,
    "bucket_weight": {
      "dividend": 0.0
    }
  },
  "opportunities": [
    {
      "strategy_id": "low_volatility_of_dividends",
      "instrument": "512890",
      "action_hint": "hold|buy|sell|reduce|increase",
      "confidence": 0.0,
      "evidence": [
        "来自 strategy 文档和当前仓位/行情的可审计证据"
      ]
    }
  ],
  "risk_validation": {
    "pass": true,
    "violations": [],
    "adjusted_actions": []
  },
  "errors": [
    {
      "code": "cash_parse_failed|snapshot_pull_failed|us_quote_partial_failed|...",
      "message": "string"
    }
  ],
  "data_needed_if_any": []
}
```

Rules:
- Keep `used_functions` in execution order.
- If a function is not run due to early `data_needed`, include only executed functions.
- Numeric fields must be numbers, not percent strings.
- `confidence` range: `0.0` to `1.0`.

## External Delivery (Optional)

If a file named `.portfolio_webhook` exists in the project root containing a webhook URL, `pull_snapshot.py` will automatically POST the generated markdown report to that URL after completion. This enables pushing reports to third-party chat bots (e.g., Feishu group bots). The file is gitignored to prevent accidental exposure.

## Acceptance Checklist

- Normal path:
  - No manual trade event
  - Returns complete `portfolio_metrics` + `opportunities`
  - Sequence, failure handling, and output schema are stable

- Special keyword path:
  - Input includes explicit event (for example `我今天卖了500股红利低波`)
  - Position update is applied first to `current_position.md`
  - Recalculation and opportunity output use updated positions

