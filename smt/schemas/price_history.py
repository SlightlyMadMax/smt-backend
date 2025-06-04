from datetime import datetime

from pydantic import BaseModel, ConfigDict


class PriceHistoryRecordBase(BaseModel):
    recorded_at: datetime
    price: float
    volume: int


class PriceHistoryRecordCreate(PriceHistoryRecordBase):
    market_hash_name: str


class PriceHistoryRecord(PriceHistoryRecordBase):
    id: int
    market_hash_name: str
    model_config = ConfigDict(from_attributes=True)


class PriceRecordCreateResponse(BaseModel):
    created: bool
    message: str = "Price history record added"


class PriceRecordBulkCreateResponse(BaseModel):
    count: int
    message: str = "Price history records added"
