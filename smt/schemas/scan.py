from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, Field


class ScanRequest(BaseModel):
    app_id: str = Field(default="440", description="Steam app id, 440 is TF2 and 730 is CS2")
    context_id: str = Field(default="2", description="Steam inventory context the items live in")
    limit: int = Field(default=50, ge=1, le=500, description="How many items to measure")
    min_price: Decimal = Field(default=Decimal("1.00"), ge=0, description="Ignore items cheaper than this")
    max_price: Decimal = Field(default=Decimal("100.00"), gt=0, description="Ignore items dearer than this")


class ScanStarted(BaseModel):
    scan_id: str


class ScanCandidate(BaseModel):
    market_hash_name: str
    name: str
    icon_url: str
    app_id: str
    context_id: str
    listings: int
    current_price: Optional[Decimal] = None
    volume_window: int = 0
    buy_target: Optional[Decimal] = None
    sell_target: Optional[Decimal] = None
    spread_pct: Optional[Decimal] = None
    required_pct: Optional[Decimal] = None
    profit_per_trade: Optional[Decimal] = None
    round_trips: int = 0
    sell_percentile_used: Optional[int] = None
    queue_ahead: Optional[int] = None
    days_to_clear: Optional[Decimal] = None
    feasible_round_trips: int = 0
    median_hold_hours: Optional[Decimal] = None
    profit_per_window: Optional[Decimal] = None
    return_on_capital_pct: Optional[Decimal] = None
    median_price: Optional[Decimal] = None
    price_drift: Optional[Decimal] = None
    tradable: bool = False
    note: str = ""


class ScanState(BaseModel):
    id: str
    status: str = Field(description="running, done or failed")
    collected: int = Field(default=0, description="Items found in the price band so far")
    measured: int = Field(default=0, description="Items whose history has been read so far")
    error: str = ""
    started_at: str = ""
    finished_at: str = ""
    params: dict = Field(default_factory=dict)
    rules: dict = Field(default_factory=dict, description="The trading settings the scan was judged by")
    candidates: List[ScanCandidate] = Field(default_factory=list)


class ScanHistoryPoint(BaseModel):
    recorded_at: str
    price: Decimal
    volume: int


class ScanCandidateDetails(BaseModel):
    market_hash_name: str
    listing_url: str
    history: List[ScanHistoryPoint] = Field(default_factory=list)
    order_book: Optional[dict] = Field(default=None, description="None when Steam would not answer")
