from smt.db.models import TradingSettings
from smt.repositories.settings import SettingsRepo
from smt.schemas.settings import SettingsUpdate


class SettingsService:
    def __init__(self, repo: SettingsRepo):
        self.repo = repo

    async def get_settings(self) -> TradingSettings:
        return await self.repo.get_current()

    async def update_settings(self, update: SettingsUpdate) -> TradingSettings:
        self._validate_settings(update)
        return await self.repo.update(update)

    def _validate_settings(self, update: SettingsUpdate) -> None:
        data = update.dict(exclude_unset=True)

        # Validate percentiles
        if "buy_percentile" in data and "sell_percentile" in data:
            if data["buy_percentile"] >= data["sell_percentile"]:
                raise ValueError("Buy percentile must be less than sell percentile")

        # Validate volatility range
        if "min_volatility_threshold" in data and "max_volatility_threshold" in data:
            if data["min_volatility_threshold"] >= data["max_volatility_threshold"]:
                raise ValueError("Min volatility must be less than max volatility")
