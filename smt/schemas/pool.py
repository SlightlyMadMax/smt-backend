from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PoolItemBase(BaseModel):
    market_hash_name: str = Field(..., description="Steam item market_hash_name")
    name: str = Field(..., description="Human-readable name")
    app_id: str
    context_id: str
    icon_url: str = Field(..., description="URL to item icon")


class PoolItemCreate(PoolItemBase):
    pass


class PoolItemUpdate(BaseModel):
    current_lowest_price: Optional[Decimal] = None
    current_median_price: Optional[Decimal] = None
    current_volume24h: Optional[int] = None
    buy_price: Optional[Decimal] = None
    sell_price: Optional[Decimal] = None
    max_listed: Optional[int] = None

    @field_validator("current_lowest_price", "current_median_price", mode="before")
    def parse_price(cls, v: Any) -> Optional[Decimal]:
        if v is None:
            return None
        if isinstance(v, str):
            price_str = v.split(" ")[0].replace(",", ".")
            return Decimal(price_str)
        return Decimal(v)

    @field_validator("current_volume24h", mode="before")
    def parse_volume(cls, v: Any) -> Optional[int]:
        if v is None:
            return None
        if isinstance(v, str):
            return int(v.replace(",", ""))
        return int(v)


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
