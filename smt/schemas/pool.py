from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class PoolItemBase(BaseModel):
    market_hash_name: str = Field(..., description="Steam item market_hash_name")
    name: str = Field(..., description="Human-readable name")
    app_id: str
    context_id: str
    icon_url: HttpUrl = Field(..., description="URL to item icon")


class PoolItemCreate(PoolItemBase):
    model_config = ConfigDict(from_attributes=False)


class PoolItemUpdate(BaseModel):
    current_lowest_price: Optional[Decimal]
    current_median_price: Optional[Decimal]
    current_volume24h: Optional[int]
    buy_price: Optional[Decimal]
    sell_price: Optional[Decimal]
    max_listed: Optional[int]

    class Config:
        from_attributes = True


class PoolItem(PoolItemBase):
    max_listed: int
    buy_price: Optional[Decimal] = None
    sell_price: Optional[Decimal] = None
    current_lowest_price: Optional[Decimal] = None
    current_median_price: Optional[Decimal] = None
    current_volume24h: Optional[int] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
