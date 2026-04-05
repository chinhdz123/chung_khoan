from datetime import date, datetime

from pydantic import BaseModel, Field


class PositionInput(BaseModel):
    symbol: str = Field(min_length=1, max_length=20)
    quantity: float = Field(ge=0)
    avg_cost: float = Field(ge=0)
    current_price: float = Field(default=0, ge=0)


class DisbursementLevel(BaseModel):
    price: float = Field(gt=0)
    ratio: float = Field(gt=0, le=1)


class RuleInput(BaseModel):
    stop_accumulate_price: float | None = Field(default=None, gt=0)
    take_profit_price: float | None = Field(default=None, gt=0)
    target_cash_ratio: float = Field(default=0.2, ge=0, le=1)
    max_position_weight: float = Field(default=0.25, ge=0.05, le=1)
    value_margin_safety: float = Field(default=0.25, ge=0.05, le=0.7)
    buy_zone_extra_margin: float = Field(default=0.01, ge=0, le=0.2)
    allocation_balance_tolerance: float = Field(default=0.02, ge=0, le=0.2)
    target_attack_stock_ratio: float = Field(default=0.34, ge=0, le=1)
    target_balance_stock_ratio: float = Field(default=0.33, ge=0, le=1)
    target_defense_stock_ratio: float = Field(default=0.33, ge=0, le=1)
    disbursement_levels: list[DisbursementLevel] = Field(default_factory=list)


class SymbolRuleInput(BaseModel):
    symbol: str = Field(min_length=1, max_length=20)
    stop_accumulate_price: float | None = Field(default=None, gt=0)
    take_profit_price: float | None = Field(default=None, gt=0)


class PortfolioTemplateInput(BaseModel):
    cash: float = Field(ge=0)
    watchlist_symbols: list[str] = Field(default_factory=list)
    positions: list[PositionInput] = Field(default_factory=list)
    symbol_rules: list[SymbolRuleInput] = Field(default_factory=list)


class PortfolioTemplateOutput(BaseModel):
    user_id: int
    cash: float
    watchlist_symbols: list[str]
    positions: list[PositionInput]
    symbol_rules: list[SymbolRuleInput]
    updated_at: datetime


class WatchlistConfigInput(BaseModel):
    watchlist_symbols: list[str] = Field(default_factory=list)


class WatchlistConfigOutput(BaseModel):
    user_id: int
    watchlist_symbols: list[str]
    updated_at: datetime


class HoldingsConfigInput(BaseModel):
    cash: float = Field(ge=0)
    positions: list[PositionInput] = Field(default_factory=list)
    symbol_rules: list[SymbolRuleInput] = Field(default_factory=list)
    target_cash_ratio: float = Field(default=0.5, ge=0, le=1)
    buy_zone_extra_margin: float = Field(default=0.01, ge=0, le=0.2)
    allocation_balance_tolerance: float = Field(default=0.02, ge=0, le=0.2)
    target_attack_stock_ratio: float = Field(default=0.34, ge=0, le=1)
    target_balance_stock_ratio: float = Field(default=0.33, ge=0, le=1)
    target_defense_stock_ratio: float = Field(default=0.33, ge=0, le=1)


class HoldingsConfigOutput(BaseModel):
    user_id: int
    cash: float
    positions: list[PositionInput]
    symbol_rules: list[SymbolRuleInput]
    target_cash_ratio: float
    target_stock_ratio: float
    buy_zone_extra_margin: float
    allocation_balance_tolerance: float
    target_attack_stock_ratio: float
    target_balance_stock_ratio: float
    target_defense_stock_ratio: float
    updated_at: datetime


class AllocationOut(BaseModel):
    cash: float
    stock_value: float
    total_assets: float
    cash_ratio: float
    stock_ratio: float
    target_cash_ratio: float
    target_stock_ratio: float
    ratio_gap: float


class AlertOut(BaseModel):
    id: int
    symbol: str
    alert_type: str
    message: str
    severity: str
    trigger_price: float | None
    current_price: float | None
    is_read: bool
    created_at: datetime


class HealthOut(BaseModel):
    snapshot_date: date
    risk_score: float
    warnings: list[str]
    suggestions: list[str]


class SymbolDecision(BaseModel):
    symbol: str
    score: float
    risk_score: float
    confidence: float
    action: str
    current_price: float
    buy_zone: float
    sell_zone: float
    reasons: list[str]
    disbursement_ratio: float = 0
    planned_disbursement_value: float = 0
    final_disbursement_value: float = 0
    planned_disbursement_quantity: float = 0
    final_disbursement_quantity: float = 0


class AdviceOut(BaseModel):
    report_date: date
    summary: str
    used_ai: bool
    ai_text: str | None
    confidence: float
    decisions: list[SymbolDecision]
    portfolio_risk_score: float
    portfolio_warnings: list[str]
    portfolio_suggestions: list[str]


class JobRunResult(BaseModel):
    ok: bool
    run_date: date
    details: dict
