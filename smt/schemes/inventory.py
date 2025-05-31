from enum import Enum

from pydantic import BaseModel, ConfigDict
from steampy.models import GameOptions


class GameName(str, Enum):
    steam = "STEAM"
    dota2 = "DOTA2"
    cs = "CS"
    tf2 = "TF2"
    pubg = "PUBG"
    rust = "RUST"


GAME_MAP = {
    GameName.steam: GameOptions.STEAM,
    GameName.dota2: GameOptions.DOTA2,
    GameName.cs: GameOptions.CS,
    GameName.tf2: GameOptions.TF2,
    GameName.pubg: GameOptions.PUBG,
    GameName.rust: GameOptions.RUST,
}


class InventoryItem(BaseModel):
    id: str
    name: str
    market_hash_name: str
    tradable: int
    marketable: int
    amount: str
    icon_url: str

    model_config = ConfigDict(from_attributes=True)
