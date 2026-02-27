doc_type: dividend_band_swing_policy
version: 1.1
locale: zh-CN
time_zone: Asia/Shanghai
owner: nins
strategy_id: low_volatility_of_dividends
strategy_display_name: "Low volatility of dividends"

# ------------------------------
# 0) 策略定位（给 LLM 的北极星）
# ------------------------------
strategy_intent:
  portfolio_role: "红利作为防守型权益底仓（现金流/低波/估值锚），波段用于提高资金效率与纪律化再平衡"
  objective_priority:
    - "优先满足红利占比目标区间（资产配置约束）"
    - "在约束内进行小幅波段增厚，不把低波资产做成高波体验"
    - "控制交易频率与回撤，优先风险收益比而非胜率叙事"

# ------------------------------
# 1) 策略参数（硬约束 + LLM 可调）
# ------------------------------
policy_config:
  hard_limits:
    dividend_assets_target_band:
      lower: 0.28
      upper: 0.34
    band_buffer: 0.005
    swing_budget_weight_bounds:
      min: 0.02
      max: 0.08
      default: 0.05
    risk_limits:
      max_loss_pct_bounds:
        min: 0.015
        max: 0.035
        default: 0.025
      atr_stop_multiple_bounds:
        min: 1.0
        max: 2.0
        default: 1.5
      max_holding_days_bounds:
        min: 8
        max: 30
        default: 20
    tranche_bounds:
      de_risk_tranche_count:
        min: 2
        max: 4
        default: 3
      build_tranche_count:
        min: 1
        max: 3
        default: 2
      min_gap_days:
        min: 1
        max: 5
        default: 2
  llm_tunable_params:
    dynamic_swing_budget_weight:
      source: "llm_fill_within_bounds"
      rule: "must be within swing_budget_weight_bounds"
    signal_thresholds:
      z_entry_1:
        min: -0.04
        max: -0.01
        default: -0.02
      z_entry_2:
        min: -0.08
        max: -0.02
        default: -0.04
      z_take_profit:
        min: 0.01
        max: 0.04
        default: 0.02
      rsi_entry_1_max:
        min: 40
        max: 50
        default: 45
      rsi_entry_2_max:
        min: 35
        max: 45
        default: 40
      rsi_take_profit_min:
        min: 55
        max: 70
        default: 60
    llm_param_explanation_required: true

instrument_universe:
  dividend_instruments:
    - code: "512890"
      name: "红利低波ETF"
      tags: ["dividend", "low_vol", "A-share_etf"]
      trading_lot: 100
  benchmark_for_relative_strength:
    - code: "510300"
      name: "沪深300ETF"
      tags: ["broad_index"]

# ------------------------------
# 2) 运行时输入契约（缺失则返回 data_needed）
# ------------------------------
runtime_inputs_contract:
  required:
    portfolio_state:
      total_equity_value: "number"
      cash_available: "number"
      positions:
        - code: "string"
          quantity: "number"
          market_value: "number"
          avg_cost: "number|null"
          bucket: "core|swing|other|UNCLASSIFIED"
          tags: ["list_of_string"]
    market_data:
      - code: "string"
        last_price: "number"
        ohlc_daily: "array[>=120]"
        ma:
          ma20: "number"
          ma60: "number"
          ma120: "number"
        atr14: "number"
        rsi14: "number"
    trading_constraints:
      min_order_value: "number|null"
      fee_rate: "number|null"
      slippage_bps_assumption: "number"
      is_trading_time: "bool"
  optional:
    corporate_actions:
      - code: "string"
        next_ex_div_date: "date|null"
        announced_dividend: "number|null"
    sentiment_or_macro:
      risk_free_rate: "number|null"
      vix_proxy: "number|null"

runtime_context:
  current_weight_source: "from_snapshot_not_literal"
  required_realtime_fields:
    - "dividend_weight_now"
    - "swing_bucket_used_weight_now"
    - "cash_available"
  required_next:
    - "historical_market_window_for_target_codes"
    - "cross_asset_features_for_relative_strength"

# ------------------------------
# 3) 统一计算定义（代码计算，LLM仅消费结果）
# ------------------------------
definitions:
  dividend_weight_calc:
    formula: "dividend_assets_value / total_equity_value"
    dividend_assets_value_rule: "positions where tags contains 'dividend' OR bucket in ['dividend','core'] sum(market_value)"
  swing_budget_value_calc:
    formula: "total_equity_value * dynamic_swing_budget_weight"
  swing_bucket_used_weight_calc:
    formula: "sum(swing_bucket_market_value) / total_equity_value"
  band_limits_with_buffer:
    lower_effective: "lower - band_buffer"
    upper_effective: "upper + band_buffer"

# ------------------------------
# 4) 总控闸门（先配比，后波段）
# ------------------------------
governance_gates:
  gate_1_rebalance_first:
    description: "红利超配时优先回区间，禁止新增红利净买入"
    trigger: "dividend_weight_now > (upper + band_buffer)"
    actions:
      - "set_mode: de_risk"
      - "swing_bucket_direction: sell_only"
      - "rebalance_target: upper"
  gate_2_underweight_add_first:
    description: "红利欠配时优先补回区间，再恢复双向波段"
    trigger: "dividend_weight_now < (lower - band_buffer)"
    actions:
      - "set_mode: build"
      - "swing_bucket_direction: buy_preferred"
      - "rebalance_target: lower"
  gate_3_normal_band:
    description: "在目标区间内允许双向波段，但交易后占比不得劣化"
    trigger: "else"
    actions:
      - "set_mode: normal"
      - "swing_bucket_direction: two_way"

# ------------------------------
# 5) 波段信号引擎（阈值可调但受 hard_limits 约束）
# ------------------------------
swing_signal_engine:
  base_timeframe: "1D"
  indicators:
    mean_reversion_anchor: "MA60"
    z_def: "(last_price - ma60) / ma60"
  entry_rules:
    entry_1:
      when_all:
        - "z <= llm_params.signal_thresholds.z_entry_1"
        - "rsi14 <= llm_params.signal_thresholds.rsi_entry_1_max"
      size: "0.5 * swing_budget_value"
    entry_2:
      when_all:
        - "z <= llm_params.signal_thresholds.z_entry_2"
        - "rsi14 <= llm_params.signal_thresholds.rsi_entry_2_max"
      size: "0.5 * swing_budget_value"
  exit_rules:
    take_profit:
      when_any:
        - "z >= llm_params.signal_thresholds.z_take_profit"
        - "last_price >= ma20 and rsi14 >= llm_params.signal_thresholds.rsi_take_profit_min"
      action: "exit_all_swing_positions_for_code"
    stop_loss:
      per_position:
        max_loss_pct: "llm_params.risk_limits.max_loss_pct"
        atr_stop_multiple: "llm_params.risk_limits.atr_stop_multiple"
      action: "exit_all_swing_positions_for_code"
    time_stop:
      max_holding_days: "llm_params.risk_limits.max_holding_days"
      action: "exit_all_swing_positions_for_code_if_not_profitable"
  event_overlay_ex_div:
    enabled: true
    logic: "除权后可能出现价格台阶，优先按均值回归信号，不在除权前追涨"
    rules:
      - if: "next_ex_div_date is not null and days_to_ex_div in [0,1]"
        then: ["avoid_new_long_entries: true"]
      - if: "next_ex_div_date is not null and days_since_ex_div in [0,3] and z <= llm_params.signal_thresholds.z_entry_1"
        then: ["allow_entry_per_rules: true"]

# ------------------------------
# 6) 再平衡执行（分批参数可调）
# ------------------------------
rebalance_playbook:
  de_risk_mode:
    principle: "先用波段仓减，再动底仓；分批卖出降低择时风险"
    steps:
      - "if swing_bucket has positions: prioritize exit via take_profit/marketable limit"
      - "if still overweight: sell core bucket in N tranches until dividend_weight <= upper"
    tranche_plan:
      tranche_count: "llm_params.tranche_plan.de_risk_tranche_count"
      min_gap_days: "llm_params.tranche_plan.min_gap_days"
  build_mode:
    principle: "先把红利补回下限，再恢复正常波段"
    steps:
      - "buy core bucket to reach lower (or lower+0.5%) using N tranches"
      - "then enable normal swing"
    tranche_plan:
      tranche_count: "llm_params.tranche_plan.build_tranche_count"
      min_gap_days: "llm_params.tranche_plan.min_gap_days"

# ------------------------------
# 7) 通用 function call 契约引用（策略无关）
# ------------------------------
contract_binding:
  global_contract_file: "strategy/llm_function_call_contract.md"
  llm_must_follow_global_contract: true
  priority_order:
    - "hard_risk_limits"
    - "global_function_call_contract"
    - "low_volatility_of_dividends_strategy_preferences"
  low_volatility_of_dividends_overrides:
    strategy_key_weights:
      - "dividend_weight_now"
      - "swing_bucket_used_weight_now"
    mode_enum: "de_risk|build|normal"

# ------------------------------
# 8) 风控与合规检查（代码必须执行）
# ------------------------------
risk_and_sanity_checks:
  must_pass:
    - name: "post_trade_band_check"
      rule: "post_dividend_weight between [lower, upper] OR closer_to_target_mid_than_pre_trade"
    - name: "swing_budget_cap"
      rule: "sum(swing_bucket_market_value) <= swing_budget_value * 1.05"
    - name: "cash_check"
      rule: "cash_available >= total_buy_order_value + estimated_fees"
    - name: "lot_size_check"
      rule: "order_quantity % trading_lot == 0"
    - name: "no_buy_when_overweight"
      rule: "if mode == de_risk then net_buy_dividend_value <= 0"
  fail_behavior:
    - "return: data_needed_if_any"
    - "or return: hold_with_reason"

# ------------------------------
# 9) 代码 vs LLM 职责边界
# ------------------------------
execution_boundary:
  code_layer_must_do:
    - "行情与汇率拉取"
    - "仓位估值、占比、指标计算（MA/ATR/RSI/z）"
    - "闸门判定与硬约束校验"
    - "手数、最小订单金额、现金可用性校验"
    - "遵循 strategy/llm_function_call_contract.md 的调用顺序"
  llm_layer_should_do:
    - "在 hard_limits 内选择 llm_tunable_params"
    - "生成动作优先级与解释理由"
    - "处理多条件冲突时给出可审计的 tradeoff"
    - "严格按 global contract 的 I/O 契约组织输出"
  anti_overload_rule:
    - "LLM 不负责重算原始行情或估值"
    - "若关键特征缺失，直接输出 data_needed，不推测"

# ------------------------------
# 10) LLM 输出格式（可直接执行前的建议单）
# ------------------------------
llm_output_contract:
  output_type: "trade_recommendation"
  fields:
    as_of: "datetime"
    mode: "de_risk|build|normal"
    selected_llm_params:
      dynamic_swing_budget_weight: "number"
      signal_thresholds: "object"
      risk_limits: "object"
      tranche_plan: "object"
      rationale:
        - "string"
    key_metrics:
      dividend_weight_now: "number"
      dividend_weight_after: "number"
      swing_bucket_used_now: "number"
      swing_bucket_used_after: "number"
      z: "number"
      rsi14: "number"
    recommended_actions:
      - code: "string"
        bucket: "core|swing"
        action: "buy|sell|hold|reduce|increase"
        order_type: "limit|market|twap_like"
        quantity: "number"
        price_hint: "number|null"
        rationale:
          - "string"
        risk_controls:
          stop_loss: "string"
          take_profit: "string"
          time_stop: "string"
    notes:
      - "string"
    data_needed_if_any:
      - "string"
