from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class PositionStatus(Enum):
    OPEN = "OPEN"
    BOUGHT = "BOUGHT"
    LISTING_PENDING = "LISTING_PENDING"
    LISTED = "LISTED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


ACTIVE_STATUSES = (
    PositionStatus.OPEN,
    PositionStatus.BOUGHT,
    PositionStatus.LISTING_PENDING,
    PositionStatus.LISTED,
)


class PositionBase(BaseModel):
    pool_item_hash: str = Field(..., description="Market hash name of the item being traded")
    app_id: str = Field(..., description="Steam app the item belongs to")
    context_id: str = Field(..., description="Steam inventory context the item lives in")


class PositionCreate(PositionBase):
    buy_order_id: str
    buy_price: Decimal
    sell_price: Decimal
    forecast_profit: Optional[Decimal] = Field(
        None, description="Profit per trip the pool expected when the order went in"
    )
    forecast_hold_hours: Optional[Decimal] = Field(None, description="Hours from purchase to sale the pool expected")
    forecast_days_to_clear: Optional[Decimal] = Field(
        None, description="Days the listings ahead of ours were expected to take"
    )
    forecast_return_30d: Optional[Decimal] = Field(None, description="Return per 30 days the pool expected")


class PositionUpdate(BaseModel):
    asset_id: Optional[str] = None
    buy_price: Optional[Decimal] = None
    net_proceeds: Optional[Decimal] = None
    realized_profit: Optional[Decimal] = None
    sell_order_id: Optional[str] = None
    status: Optional[PositionStatus] = None
    sold_at: Optional[datetime] = None
    bought_at: Optional[datetime] = None
    listed_at: Optional[datetime] = None


class Position(PositionBase):
    id: int
    buy_order_id: str
    buy_price: Decimal
    asset_id: Optional[str]
    sell_order_id: Optional[str]
    sell_price: Decimal
    sold_at: Optional[datetime]
    net_proceeds: Optional[Decimal]
    realized_profit: Optional[Decimal]
    status: PositionStatus
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PositionRow(BaseModel):
    id: int
    pool_item_hash: str
    name: str
    icon_url: str
    listing_url: str
    status: PositionStatus
    buy_price: Decimal
    sell_price: Decimal
    net_proceeds: Optional[Decimal] = None
    realized_profit: Optional[Decimal] = None
    bought_at: Optional[datetime] = None
    listed_at: Optional[datetime] = None
    sold_at: Optional[datetime] = None
    created_at: datetime


class PositionSortKey(str, Enum):
    NAME = "name"
    STATUS = "status"
    BUY_PRICE = "buy_price"
    SELL_PRICE = "sell_price"
    NET_PROCEEDS = "net_proceeds"
    REALIZED_PROFIT = "realized_profit"
    CREATED_AT = "created_at"
    BOUGHT_AT = "bought_at"
    LISTED_AT = "listed_at"
    SOLD_AT = "sold_at"


class SortOrder(str, Enum):
    ASC = "asc"
    DESC = "desc"


class PositionPage(BaseModel):
    items: list[PositionRow]
    total: int


class PositionSummary(BaseModel):
    counts: dict[str, int]
    active_count: int
    capital_in_open_trades: Decimal
    realized_profit_24h: Decimal
    realized_profit_total: Decimal
