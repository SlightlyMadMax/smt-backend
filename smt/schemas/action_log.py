from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, ConfigDict


class ActionLevel(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class ActionKind(str, Enum):
    BUY_ORDER_PLACED = "buy_order_placed"
    BUY_ORDER_REFUSED = "buy_order_refused"
    POSITION_BOUGHT = "position_bought"
    SELL_ORDER_PLACED = "sell_order_placed"
    LISTING_RESOLVED = "listing_resolved"
    LISTING_VANISHED = "listing_vanished"
    LISTING_CANCELLED = "listing_cancelled"
    POSITION_CLOSED = "position_closed"
    POSITION_CANCELLED = "position_cancelled"
    UNTRACKED_ORDER = "untracked_order"
    CYCLE_FAILED = "cycle_failed"


class ActionLogEntry(BaseModel):
    id: int
    occurred_at: datetime
    kind: str
    level: str
    market_hash_name: Optional[str] = None
    position_id: Optional[int] = None
    message: str

    model_config = ConfigDict(from_attributes=True)


class ActionLogSortKey(str, Enum):
    OCCURRED_AT = "occurred_at"
    KIND = "kind"
    LEVEL = "level"
    MARKET_HASH_NAME = "market_hash_name"


class ActionLogPage(BaseModel):
    items: List[ActionLogEntry]
    total: int


class ActionLogPurged(BaseModel):
    removed: int
