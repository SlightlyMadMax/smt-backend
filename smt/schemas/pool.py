from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class PoolItemBase(BaseModel):
    market_hash_name: str = Field(..., description="Steam item market_hash_name")
    name: str = Field(..., description="Human-readable name")
    app_id: str
    context_id: str
    icon_url: str = Field(..., description="URL to item icon")


class PoolItemCreate(PoolItemBase):
    model_config = ConfigDict(from_attributes=False)


class PoolItemUpdate(BaseModel):
    current_lowest_price: Optional[Decimal] = None
    current_median_price: Optional[Decimal] = None
    current_volume24h: Optional[int] = None
    buy_price: Optional[Decimal] = None
    sell_price: Optional[Decimal] = None
    max_listed: Optional[int] = None

    class Config:
        from_attributes = True


class PoolItem(PoolItemBase):
    max_listed: int = None
    buy_price: Optional[Decimal] = None
    sell_price: Optional[Decimal] = None
    current_lowest_price: Optional[Decimal] = None
    current_median_price: Optional[Decimal] = None
    current_volume24h: Optional[int] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PoolItemCreateResponse(BaseModel):
    created: bool
    message: str = "Pool item added"


class PoolItemBulkCreateResponse(BaseModel):
    count: int
    message: str = "Pool items added"


class PoolItemUpdateResponse(BaseModel):
    updated: bool
    message: str = "Pool item updated"


class PoolItemBulkCreateRequest(BaseModel):
    asset_ids: list[str]


class PoolItemCreateRequest(BaseModel):
    asset_id: str
