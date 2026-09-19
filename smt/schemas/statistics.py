from datetime import date
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel


class Funnel(BaseModel):
    opened: int
    bought: int
    sold: int
    cancelled: int
    fill_rate: Optional[Decimal] = None
    sell_through: Optional[Decimal] = None


class ItemPerformance(BaseModel):
    market_hash_name: str
    name: str
    icon_url: str
    trades: int
    profit: Decimal
    avg_profit: Decimal
    capital: Decimal
    median_hold_hours: Optional[Decimal] = None
    sell_wait_hours: Optional[Decimal] = None
    buy_wait_hours: Optional[Decimal] = None
    observed_days: Optional[Decimal] = None
    actual_return_30d: Optional[Decimal] = None
    forecast_profit: Optional[Decimal] = None
    forecast_hold_hours: Optional[Decimal] = None
    forecast_sell_wait_hours: Optional[Decimal] = None
    forecast_return_30d: Optional[Decimal] = None


class DailyProfit(BaseModel):
    day: date
    profit: Decimal


class StatisticsOverview(BaseModel):
    funnel: Funnel
    items: List[ItemPerformance]
    daily_profit: List[DailyProfit]
