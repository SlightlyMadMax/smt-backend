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


class PositionBase(BaseModel):
    pool_item_hash: str = Field(..., description="Market hash name of the pool item")


class PositionCreate(PositionBase):
    buy_order_id: str
    buy_price: Decimal
    sell_price: Decimal


class PositionUpdate(BaseModel):
    asset_id: Optional[str] = None
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
