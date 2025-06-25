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
    max_listed: int = Field(default=1)


class PoolItemCreate(PoolItemBase):
    pass


class PoolItemUpdate(BaseModel):
    current_lowest_price: Optional[Decimal] = None
    current_median_price: Optional[Decimal] = None
    current_volume24h: Optional[int] = None
    optimal_buy_price: Optional[Decimal] = None
    optimal_sell_price: Optional[Decimal] = None
    manual_buy_price: Optional[Decimal] = None
    manual_sell_price: Optional[Decimal] = None
    volatility: Optional[Decimal] = None
    potential_profit: Optional[Decimal] = None
    use_for_trading: Optional[bool] = None
    max_listed: Optional[int] = None

    @field_validator(
        "current_lowest_price",
        "current_median_price",
        "optimal_buy_price",
        "optimal_sell_price",
        "manual_buy_price",
        "manual_sell_price",
        "volatility",
        "potential_profit",
        mode="before",
    )
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
    buy_price: Optional[Decimal] = None
    sell_price: Optional[Decimal] = None
    current_lowest_price: Optional[Decimal] = None
    current_median_price: Optional[Decimal] = None
    current_volume24h: Optional[int] = None
    optimal_buy_price: Optional[Decimal] = None
    optimal_sell_price: Optional[Decimal] = None
    manual_buy_price: Optional[Decimal] = None
    manual_sell_price: Optional[Decimal] = None
    volatility: Optional[Decimal] = None
    potential_profit: Optional[Decimal] = None
    use_for_trading: bool = False
    listing_url: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PoolItemStatus(BaseModel):
    market_hash_name: str
    current_lowest_price: Optional[Decimal] = None
    current_volume24h: Optional[int] = None
    optimal_buy_price: Optional[Decimal] = None
    optimal_sell_price: Optional[Decimal] = None
    volatility: Optional[Decimal] = None
    potential_profit: Optional[Decimal] = None
    use_for_trading: bool = False
    updated_at: Optional[datetime] = None


class PoolItemBulkCreateResponse(BaseModel):
    count: int
    message: str = "Pool items added"


class PoolItemBulkCreateRequest(BaseModel):
    asset_ids: list[str]


class PoolItemCreateRequest(BaseModel):
    asset_id: str


class RemoveManyRequest(BaseModel):
    market_hash_names: list[str]


class RemoveResponse(BaseModel):
    success: bool
    message: str


class RemoveManyResponse(BaseModel):
    removed_count: int
    message: str
