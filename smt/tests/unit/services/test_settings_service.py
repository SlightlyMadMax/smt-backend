from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from smt.schemas.settings import SettingsUpdate
from smt.services.settings import SettingsService


def stored(buy_percentile=20, sell_percentile=80):
    return SimpleNamespace(buy_percentile=buy_percentile, sell_percentile=sell_percentile)


@pytest.fixture
def service():
    repo = AsyncMock()
    repo.get_current.return_value = stored()
    return SettingsService(repo)


@pytest.mark.asyncio
class TestSettingsValidation:
    async def test_accepts_a_consistent_update(self, service):
        await service.update_settings(SettingsUpdate(buy_percentile=10, sell_percentile=90))

        service.repo.update.assert_awaited_once()

    async def test_rejects_crossed_percentiles_in_one_patch(self, service):
        with pytest.raises(ValueError, match="percentile"):
            await service.update_settings(SettingsUpdate(buy_percentile=90, sell_percentile=10))

    async def test_rejects_a_single_field_that_crosses_the_stored_one(self, service):
        # stored sell percentile is 80, so raising buy alone must not slip through
        with pytest.raises(ValueError, match="percentile"):
            await service.update_settings(SettingsUpdate(buy_percentile=85))

    async def test_allows_a_single_field_that_stays_consistent(self, service):
        await service.update_settings(SettingsUpdate(buy_percentile=15))

        service.repo.update.assert_awaited_once()

    async def test_nothing_is_written_when_validation_fails(self, service):
        with pytest.raises(ValueError):
            await service.update_settings(SettingsUpdate(sell_percentile=5))

        service.repo.update.assert_not_awaited()
