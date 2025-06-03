from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ItemStatBase(BaseModel):
    market_hash_name: str
    recorded_at: datetime
    price: float
    volume: int


class ItemStatCreate(ItemStatBase):
    model_config = ConfigDict(from_attributes=False)


class ItemStat(ItemStatBase):
    id: int
    market_hash_name: str
    recorded_at: datetime
    price: float
    volume: int
    model_config = ConfigDict(from_attributes=True)
