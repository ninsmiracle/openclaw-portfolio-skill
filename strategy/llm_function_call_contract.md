# LLM Function Call Contract (Strategy-Agnostic)

doc_type: llm_function_call_contract
version: 1.0
scope: "cross_strategy"
priority_rule:
  priority_order:
    - "hard_risk_limits"
    - "this_contract"
    - "strategy_specific_preferences"
  llm_must_follow: true
  if_conflict: "follow higher priority and output conflict_note"

# ------------------------------
# 1) 设计目标
# ------------------------------
design_goals:
  - "将确定性计算与策略推理解耦，避免 LLM 过载"
  - "所有函数单一职责、结构化输入输出、可审计"
  - "任何策略先走函数链，再由 LLM 解释与排序动作"

# ------------------------------
# 2) 全局输入/输出约束
# ------------------------------
global_io_rules:
  input_must_be_structured_json: true
  output_must_be_structured_json: true
  no_hidden_assumptions: true
  missing_data_behavior: "return data_needed, do_not_guess"
  numeric_fields:
    use_number_type: true
    no_percent_string: true

# ------------------------------
# 3) 原子函数目录（策略无关）
# ------------------------------
function_catalog:
  - name: "get_portfolio_snapshot"
    purpose: "读取实时资产快照"
    input:
      as_of: "datetime"
    output:
      total_equity_value: "number"
      cash_available: "number"
      positions: "array"
      bucket_weights: "object"

  - name: "compute_bucket_weights"
    purpose: "聚合资产桶价值与权重"
    input:
      snapshot: "object"
      bucket_map: "object"
    output:
      bucket_value: "object"
      bucket_weight: "object"
      strategy_key_weights: "object"

  - name: "get_market_window"
    purpose: "获取单标的历史窗口与指标"
    input:
      code: "string"
      lookback_days: "number"
    output:
      ohlc_daily: "array"
      indicators: "object"

  - name: "get_cross_asset_features"
    purpose: "提取跨资产相对强弱、相关性、波动特征"
    input:
      codes: "array[string]"
      lookback_days: "number"
    output:
      rel_strength: "object"
      corr_matrix: "object"
      volatility_rank: "object"

  - name: "evaluate_gates"
    purpose: "根据硬约束和目标区间判断模式"
    input:
      state: "object"
      policy: "object"
    output:
      mode: "string"
      allowed_direction: "string"
      rebalance_target: "number|null"

  - name: "propose_trade_actions"
    purpose: "基于状态与可调参数给出动作草案"
    input:
      state: "object"
      llm_params: "object"
    output:
      recommended_actions: "array"
      projected_post_trade_metrics: "object"

  - name: "validate_risk_checks"
    purpose: "执行交易前风险与合规检查"
    input:
      actions: "array"
      constraints: "object"
    output:
      pass: "bool"
      violations: "array[string]"
      adjusted_actions: "array"

# ------------------------------
# 4) 推荐调用顺序（默认工作流）
# ------------------------------
default_call_sequence:
  - "get_portfolio_snapshot"
  - "compute_bucket_weights"
  - "get_market_window"
  - "get_cross_asset_features"
  - "evaluate_gates"
  - "propose_trade_actions"
  - "validate_risk_checks"

# ------------------------------
# 5) 代码层 vs LLM 层边界（全策略通用）
# ------------------------------
execution_boundary:
  code_layer_must_do:
    - "行情拉取、汇率换算、仓位估值、指标计算"
    - "硬约束校验、手数与现金合法性检查"
    - "函数调用编排与状态持久化"
  llm_layer_should_do:
    - "在约束内选择可调参数"
    - "输出动作优先级与可审计理由"
    - "在冲突条件下给出取舍逻辑"
  llm_must_not_do:
    - "重算底层行情或伪造缺失字段"
    - "跳过 validate_risk_checks 直接下结论"

# ------------------------------
# 6) LLM 执行指令（建议放到系统提示词）
# ------------------------------
llm_operating_instructions:
  - "你必须优先遵循本契约的函数调用顺序与输入输出要求。"
  - "若策略文档与本契约冲突，先执行硬风险约束，再执行本契约，再执行策略偏好。"
  - "任一必需字段缺失时，输出 data_needed，不允许猜测补全。"
  - "输出必须包含 used_functions 与 validation_result，便于审计。"

