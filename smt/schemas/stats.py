from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ItemStatBase(BaseModel):
    recorded_at: datetime
    price: float
    volume: int


class ItemStatCreate(ItemStatBase):
    market_hash_name: str
    model_config = ConfigDict(from_attributes=False)


class ItemStat(ItemStatBase):
    id: int
    model_config = ConfigDict(from_attributes=True)
