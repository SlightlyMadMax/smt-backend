from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class PositionStatus(Enum):
    OPEN = "OPEN"
    BOUGHT = "BOUGHT"
    LISTED = "LISTED"
    CLOSED = "CLOSED"


class PositionBase(BaseModel):
    pool_item_hash: str = Field(..., description="Market hash name of the pool item")
    quantity: int = Field(default=1, ge=1)


class PositionCreate(PositionBase):
    buy_order_id: str
    buy_price: Decimal
    sell_price: Decimal


class PositionUpdate(BaseModel):
    sell_order_id: Optional[str] = None
    status: Optional[PositionStatus] = None
    sold_at: Optional[datetime] = None


class Position(PositionBase):
    id: int
    buy_order_id: str
    buy_price: Decimal
    sell_order_id: Optional[str]
    sell_price: Decimal
    sold_at: Optional[datetime]
    status: PositionStatus
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
