from smt.db.models import TradingSettings
from smt.repositories.settings import SettingsRepo
from smt.schemas.settings import SettingsUpdate


class SettingsService:
    def __init__(self, repo: SettingsRepo):
        self.repo = repo

    async def get_settings(self) -> TradingSettings:
        return await self.repo.get_current()

    async def update_settings(self, update: SettingsUpdate) -> TradingSettings:
        await self._validate_settings(update)
        return await self.repo.update(update)

    async def _validate_settings(self, update: SettingsUpdate) -> None:
        """Check the settings as they will look after the update."""
        current = await self.repo.get_current()
        patch = update.model_dump(exclude_unset=True)

        def value(field: str):
            return patch[field] if field in patch else getattr(current, field)

        if value("buy_percentile") >= value("sell_percentile"):
            raise ValueError("Buy percentile must be less than sell percentile")

        if value("min_volatility_threshold") >= value("max_volatility_threshold"):
            raise ValueError("Min volatility must be less than max volatility")
