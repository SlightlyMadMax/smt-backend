from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from smt.db.models import TradingSettings
from smt.schemas.settings import SettingsUpdate


class SettingsRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_current(self) -> TradingSettings:
        stmt = select(TradingSettings).order_by(TradingSettings.updated_at.desc()).limit(1)
        result = await self.session.execute(stmt)
        settings = result.scalar_one_or_none()

        if not settings:
            settings = TradingSettings()
            self.session.add(settings)
            await self.session.commit()
            await self.session.refresh(settings)

        return settings

    async def update(self, settings_update: SettingsUpdate) -> TradingSettings:
        current = await self.get_current()

        for field, value in settings_update.dict(exclude_unset=True).items():
            setattr(current, field, value)

        await self.session.commit()
        await self.session.refresh(current)
        return current
