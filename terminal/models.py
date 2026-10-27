"""Pydantic validation for user-editable settings."""
from __future__ import annotations

import re

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class SessionSettings(BaseModel):
    pre_open_start: str
    pre_open_end: str
    market_open: str
    market_close: str
    no_entries_before: str
    no_entries_after: str
    flat_by: str

    @field_validator("*")
    @classmethod
    def hhmm(cls, v: str) -> str:
        if not _HHMM.match(v):
            raise ValueError("use HH:MM (24-hour IST)")
        return v

    @model_validator(mode="after")
    def ordered(self):
        seq = [self.pre_open_start, self.pre_open_end, self.market_open, self.no_entries_before, self.no_entries_after,
               self.flat_by, self.market_close]
        if seq != sorted(seq):
            raise ValueError("times must be in order: pre-open < open <= entries start < entries end < flat-by < close")
        return self


class RiskSettings(BaseModel):
    risk_per_trade_pct: float = Field(gt=0, le=5)
    max_open_risk_pct: float = Field(gt=0, le=20)
    max_daily_loss_pct: float = Field(gt=0, le=20)
    max_positions: int = Field(ge=1, le=50)
    max_trades_per_day: int = Field(ge=1, le=100)
    min_reward_risk: float = Field(ge=0, le=10)
    require_stop: bool
    max_position_pct: float = Field(gt=0, le=100)
    cash_buffer_pct: float = Field(ge=0, lt=100)
    max_leverage: float = Field(gt=0, le=5)
    allow_short: bool
    blocked: list[str]
    min_order_value: float = Field(ge=0)
    enforce_entry_window: bool

    @model_validator(mode="after")
    def consistent(self):
        if self.risk_per_trade_pct > self.max_open_risk_pct:
            raise ValueError("risk per trade cannot exceed the maximum open risk")
        return self


class PaperSettings(BaseModel):
    initial_capital: float = Field(ge=10000)
    automation_enabled: bool
    slippage_pct: float = Field(ge=0, le=2)
    slippage_ticks: int = Field(ge=0, le=50)


MODELS = {"session": SessionSettings, "risk": RiskSettings, "paper": PaperSettings}


def validate_section(name: str, values: dict) -> tuple[dict | None, list[str]]:
    model = MODELS.get(name)
    if model is None:
        return values, []
    try:
        return model(**values).model_dump(), []
    except ValidationError as e:
        return None, [f"{'.'.join(str(x) for x in err['loc']) or name}: {err['msg']}" for err in e.errors()]
