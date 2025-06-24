import datetime
from decimal import Decimal
from unittest.mock import AsyncMock, Mock

import pytest
import pytest_asyncio

from smt.schemas.price_history import PriceHistoryRecord
from smt.services.market_analytics import MarketAnalyticsService


@pytest_asyncio.fixture
def mock_settings_service():
    """Mock settings service with default settings"""
    mock_service = AsyncMock()

    # Default mock settings
    mock_settings = Mock()
    mock_settings.buy_percentile = 25
    mock_settings.sell_percentile = 75
    mock_settings.emergency_stop = False
    mock_settings.min_profit_threshold = Decimal("1.00")
    mock_settings.min_volume_24h = 100
    mock_settings.min_volatility_threshold = Decimal("0.01")
    mock_settings.max_volatility_threshold = Decimal("0.50")

    mock_service.get_settings.return_value = mock_settings
    return mock_service


@pytest_asyncio.fixture
def market_analytics_service(mock_settings_service):
    return MarketAnalyticsService(mock_settings_service)


@pytest_asyncio.fixture
def sample_price_records():
    """Sample price history records for testing"""
    return [
        PriceHistoryRecord(
            id=1,
            market_hash_name="item1",
            price=Decimal("10.00"),
            volume=100,
            recorded_at=datetime.date(year=2025, month=6, day=20),
        ),
        PriceHistoryRecord(
            id=2,
            market_hash_name="item1",
            price=Decimal("12.00"),
            volume=150,
            recorded_at=datetime.date(year=2025, month=6, day=21),
        ),
        PriceHistoryRecord(
            id=3,
            market_hash_name="item1",
            price=Decimal("11.00"),
            volume=120,
            recorded_at=datetime.date(year=2025, month=6, day=22),
        ),
        PriceHistoryRecord(
            id=4,
            market_hash_name="item1",
            price=Decimal("13.00"),
            volume=80,
            recorded_at=datetime.date(year=2025, month=6, day=23),
        ),
        PriceHistoryRecord(
            id=5,
            market_hash_name="item1",
            price=Decimal("10.50"),
            volume=200,
            recorded_at=datetime.date(year=2025, month=6, day=24),
        ),
    ]


@pytest.mark.asyncio
class TestMarketAnalyticsService:

    async def test_compute_weighted_percentile_targets_calls_settings(
        self, market_analytics_service, mock_settings_service, sample_price_records
    ):
        """Test that compute_weighted_percentile_targets calls settings service"""
        await market_analytics_service.compute_weighted_percentile_targets(sample_price_records)
        mock_settings_service.get_settings.assert_called_once()

    async def test_compute_weighted_percentile_targets_returns_tuple(
        self, market_analytics_service, sample_price_records
    ):
        """Test that compute_weighted_percentile_targets returns a tuple of Decimals"""
        buy, sell = await market_analytics_service.compute_weighted_percentile_targets(sample_price_records)

        assert isinstance(buy, Decimal)
        assert isinstance(sell, Decimal)
        assert buy < sell  # Buy percentile should be lower than sell percentile

    async def test_compute_weighted_percentile_targets_empty_records(self, market_analytics_service):
        """Test behavior with empty records list"""
        with pytest.raises(Exception):  # Should handle empty list gracefully or raise appropriate error
            await market_analytics_service.compute_weighted_percentile_targets([])

    async def test_compute_volume_weighted_volatility_returns_decimal(self, sample_price_records):
        """Test that compute_volume_weighted_volatility returns a Decimal"""
        volatility = await MarketAnalyticsService.compute_volume_weighted_volatility(sample_price_records)

        assert isinstance(volatility, Decimal)
        assert volatility >= Decimal("0.0000")

    async def test_compute_volume_weighted_volatility_single_record(self):
        """Test volatility calculation with only one record"""
        single_record = [
            PriceHistoryRecord(
                id=1,
                market_hash_name="item1",
                price=Decimal("10.00"),
                volume=100,
                recorded_at=datetime.date(year=2025, month=6, day=25),
            )
        ]
        volatility = await MarketAnalyticsService.compute_volume_weighted_volatility(single_record)

        # With only one record, there are no returns to calculate, should return 0
        assert volatility == Decimal("0.0000")

    async def test_compute_volume_weighted_volatility_zero_volume(self):
        """Test volatility calculation with zero volumes"""
        zero_volume_records = [
            PriceHistoryRecord(
                id=1,
                market_hash_name="item1",
                price=Decimal("10.00"),
                volume=0,
                recorded_at=datetime.date(year=2025, month=6, day=24),
            ),
            PriceHistoryRecord(
                id=2,
                market_hash_name="item1",
                price=Decimal("12.00"),
                volume=0,
                recorded_at=datetime.date(year=2025, month=6, day=25),
            ),
        ]
        volatility = await MarketAnalyticsService.compute_volume_weighted_volatility(zero_volume_records)

        assert volatility == Decimal("0.0000")

    @pytest.mark.parametrize(
        "sell_price,buy_price",
        [
            (Decimal("10.00"), Decimal("8.00")),
            (Decimal("15.50"), Decimal("12.25")),
            (Decimal("100.00"), Decimal("95.00")),
        ],
    )
    async def test_compute_net_and_profit_returns_tuple(self, sell_price, buy_price):
        """Test that compute_net_and_profit returns correct tuple format"""
        net, profit = await MarketAnalyticsService.compute_net_and_profit(sell_price, buy_price)

        assert isinstance(net, Decimal)
        assert isinstance(profit, Decimal)
        assert net <= sell_price  # Net should be less than gross due to fees
        assert profit == net - buy_price  # Basic profit calculation

    async def test_decide_trade_flag_emergency_stop(self, market_analytics_service, mock_settings_service):
        """Test that emergency stop prevents trading"""
        mock_settings_service.get_settings.return_value.emergency_stop = True

        result = await market_analytics_service.decide_trade_flag(
            profit=Decimal("5.00"), volume24h=500, volatility=Decimal("0.10")
        )

        assert result is False

    async def test_decide_trade_flag_low_profit(self, market_analytics_service, mock_settings_service):
        """Test that low profit prevents trading"""
        mock_settings_service.get_settings.return_value.min_profit_threshold = Decimal("5.00")

        result = await market_analytics_service.decide_trade_flag(
            profit=Decimal("2.00"), volume24h=500, volatility=Decimal("0.10")  # Below threshold
        )

        assert result is False

    async def test_decide_trade_flag_low_volume(self, market_analytics_service, mock_settings_service):
        """Test that low volume prevents trading"""
        mock_settings_service.get_settings.return_value.min_volume_24h = 1000

        result = await market_analytics_service.decide_trade_flag(
            profit=Decimal("5.00"), volume24h=500, volatility=Decimal("0.10")  # Below threshold
        )

        assert result is False

    async def test_decide_trade_flag_none_volume(self, market_analytics_service):
        """Test that None volume prevents trading"""
        result = await market_analytics_service.decide_trade_flag(
            profit=Decimal("5.00"), volume24h=None, volatility=Decimal("0.10")
        )

        assert result is False

    @pytest.mark.parametrize(
        "volatility,expected",
        [
            (Decimal("0.005"), False),  # Below min threshold
            (Decimal("0.60"), False),  # Above max threshold
            (Decimal("0.10"), True),  # Within range
        ],
    )
    async def test_decide_trade_flag_volatility_thresholds(
        self, market_analytics_service, mock_settings_service, volatility, expected
    ):
        """Test volatility threshold checks"""
        mock_settings_service.get_settings.return_value.min_volatility_threshold = Decimal("0.01")
        mock_settings_service.get_settings.return_value.max_volatility_threshold = Decimal("0.50")

        result = await market_analytics_service.decide_trade_flag(
            profit=Decimal("5.00"), volume24h=500, volatility=volatility
        )

        assert result is expected

    async def test_decide_trade_flag_all_conditions_met(self, market_analytics_service):
        """Test that trade is approved when all conditions are met"""
        result = await market_analytics_service.decide_trade_flag(
            profit=Decimal("5.00"), volume24h=500, volatility=Decimal("0.10")
        )

        assert result is True

    async def test_decide_trade_flag_calls_settings(self, market_analytics_service, mock_settings_service):
        """Test that decide_trade_flag calls settings service"""
        await market_analytics_service.decide_trade_flag(
            profit=Decimal("5.00"), volume24h=500, volatility=Decimal("0.10")
        )

        mock_settings_service.get_settings.assert_called_once()
