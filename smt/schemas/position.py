from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class PositionBase(BaseModel):
    pool_item_hash: str = Field(..., description="Market hash name of the pool item")
    quantity: int = Field(1, ge=1)


class PositionCreate(PositionBase):
    buy_order_id: str
    buy_price: float


class PositionUpdate(BaseModel):
    sell_order_id: Optional[str]
    sell_price: Optional[float]
    status: Optional[str]
    sold_at: Optional[datetime]


class Position(PositionBase):
    id: int
    buy_order_id: str
    buy_price: float
    sell_order_id: Optional[str]
    sell_price: Optional[float]
    sold_at: Optional[datetime]
    status: str
    created_at: datetime
    updated_at: datetime

    class Config:
        orm_mode = True
