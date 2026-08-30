from decimal import Decimal
from typing import Optional

from pydantic import BaseModel


class WalletBalance(BaseModel):
    balance: Optional[Decimal] = None
    cached: bool = False
    stale: bool = False
