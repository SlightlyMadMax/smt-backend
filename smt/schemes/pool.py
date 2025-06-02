from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class PoolItemBase(BaseModel):
    market_hash_name: str = Field(..., description="Steam item market_hash_name")
    display_name: str = Field(..., description="Human-readable name")
    icon_url: str = Field(..., description="URL to item icon")


class PoolItemCreate(PoolItemBase):
    model_config = ConfigDict(from_attributes=False)


class PoolItem(PoolItemBase):
    max_listed: int
    buy_price: Optional[float] = None
    sell_price: Optional[float] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
