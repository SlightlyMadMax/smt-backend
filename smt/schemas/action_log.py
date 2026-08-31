from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict


class ActionLevel(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class ActionKind(str, Enum):
    BUY_ORDER_PLACED = "buy_order_placed"
    POSITION_BOUGHT = "position_bought"
    SELL_ORDER_PLACED = "sell_order_placed"
    LISTING_RESOLVED = "listing_resolved"
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
