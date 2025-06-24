from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from smt.db.models import TradingSettings
from smt.repositories.settings import SettingsRepo
from smt.schemas.settings import SettingsUpdate


@pytest_asyncio.fixture
def settings_repo(db_session) -> SettingsRepo:
    return SettingsRepo(db_session)


@pytest_asyncio.fixture(autouse=True)
async def setup_settings(db_session):
    await db_session.execute(delete(TradingSettings))
    await db_session.commit()
    yield


@pytest.mark.asyncio
class TestSettingsRepo:
    async def test_get_current_creates_default_when_none_exist(self, settings_repo, db_session):
        """Test that get_current creates a default TradingSettings when none exist"""
        # Verify no settings exist initially
        result = await db_session.execute(select(TradingSettings))
        assert result.scalar_one_or_none() is None

        # Call get_current
        settings = await settings_repo.get_current()

        # Verify settings were created and returned
        assert settings is not None
        assert isinstance(settings, TradingSettings)
        assert settings.id is not None

        # Verify settings were persisted to database
        result = await db_session.execute(select(TradingSettings))
        db_settings = result.scalar_one_or_none()
        assert db_settings is not None
        assert db_settings.id == settings.id

    async def test_get_current_returns_existing_settings(self, settings_repo, db_session):
        """Test that get_current returns existing settings when they exist"""
        # Create a settings record
        existing_settings = TradingSettings()
        db_session.add(existing_settings)
        await db_session.commit()
        await db_session.refresh(existing_settings)

        # Call get_current
        settings = await settings_repo.get_current()

        # Verify the existing settings were returned
        assert settings.id == existing_settings.id

    @pytest.mark.parametrize(
        "update_fields",
        [
            {},
            {"min_profit_threshold": 10.0},
            {
                "min_profit_threshold": 5.0,
                "min_profit_percentage": 10.0,
                "max_investment_per_item": 10.0,
                "buy_percentile": 10,
                "sell_percentile": 90,
                "min_volume_24h": 100,
                "min_volume_7d": 700,
                "max_volatility_threshold": Decimal("0.99"),
                "min_volatility_threshold": Decimal("0.1"),
                "price_history_days": 31,
                "analysis_window_days": 7,
                "max_concurrent_trades": 100,
                "cooldown_after_loss_hours": 1,
                "price_refresh_interval_minutes": 60,
                "stats_refresh_interval_minutes": 90,
                "emergency_stop": False,
                "max_daily_loss": 1000,
            },
        ],
    )
    async def test_update_with_various_fields(self, settings_repo, update_fields):
        """Test update with different field combinations"""
        # Get initial settings
        original_settings = await settings_repo.get_current()

        # Create update
        settings_update = SettingsUpdate(**update_fields)

        # Update settings
        updated_settings = await settings_repo.update(settings_update)

        # Verify update was applied
        assert updated_settings.id == original_settings.id

        # Verify specific fields were updated (add assertions based on your actual fields)
        for field, expected_value in update_fields.items():
            assert getattr(updated_settings, field) == expected_value
