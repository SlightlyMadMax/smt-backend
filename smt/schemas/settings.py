from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field


class SettingsResponse(BaseModel):
    id: int
    min_profit_threshold: Decimal
    min_profit_percentage: Decimal
    max_investment_per_item: Decimal
    buy_percentile: int
    sell_percentile: int
    min_volume_24h: int
    min_volume_7d: int
    max_volatility_threshold: Decimal
    min_volatility_threshold: Decimal
    price_history_days: int
    analysis_window_days: int
    max_concurrent_trades: int
    cooldown_after_loss_hours: int
    price_refresh_interval_minutes: int
    stats_refresh_interval_minutes: int
    emergency_stop: bool
    max_daily_loss: Decimal
    updated_at: datetime


class SettingsUpdate(BaseModel):
    min_profit_threshold: Optional[Decimal] = None
    min_profit_percentage: Optional[Decimal] = None
    max_investment_per_item: Optional[Decimal] = None
    buy_percentile: Optional[int] = Field(None, ge=1, le=99)
    sell_percentile: Optional[int] = Field(None, ge=1, le=99)
    min_volume_24h: Optional[int] = Field(None, ge=0)
    min_volume_7d: Optional[int] = Field(None, ge=0)
    max_volatility_threshold: Optional[Decimal] = Field(None, ge=0)
    min_volatility_threshold: Optional[Decimal] = Field(None, ge=0)
    price_history_days: Optional[int] = Field(None, ge=1, le=365)
    analysis_window_days: Optional[int] = Field(None, ge=1, le=90)
    max_concurrent_trades: Optional[int] = Field(None, ge=1)
    cooldown_after_loss_hours: Optional[int] = Field(None, ge=0)
    price_refresh_interval_minutes: Optional[int] = Field(None, ge=5)
    stats_refresh_interval_minutes: Optional[int] = Field(None, ge=10)
    emergency_stop: Optional[bool] = None
    max_daily_loss: Optional[Decimal] = Field(None, ge=0)
