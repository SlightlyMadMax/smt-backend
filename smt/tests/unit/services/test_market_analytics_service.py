import datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
import pytest_asyncio

from smt.schemas.price_history import PriceHistoryRecord
from smt.services.market_analytics import ItemIndicators, MarketAnalyticsService


def make_indicators(
    profit=Decimal("5.00"),
    volume24h=500,
    volume7d=3000,
    volatility=Decimal("0.10"),
    round_trips=8,
    median_hold_hours=Decimal("12.0"),
    return_on_capital_30d=Decimal("120.0"),
):
    return ItemIndicators(
        profit=profit,
        volume24h=volume24h,
        volume7d=volume7d,
        volatility=volatility,
        round_trips=round_trips,
        median_hold_hours=median_hold_hours,
        return_on_capital_30d=return_on_capital_30d,
    )


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
    mock_settings.min_volume_7d = 500
    mock_settings.max_volatility_threshold = Decimal("0.50")
    mock_settings.max_hold_hours = 48
    mock_settings.min_return_on_capital_30d = Decimal("20.0")

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

    async def test_decide_trade_flag_low_profit(self, market_analytics_service, mock_settings_service):
        """Test that low profit prevents trading"""
        mock_settings_service.get_settings.return_value.min_profit_threshold = Decimal("5.00")

        result, _ = await market_analytics_service.decide_trade_flag(
            make_indicators(profit=Decimal("2.00"), volume24h=500, volatility=Decimal("0.10"))
        )

        assert result is False

    async def test_decide_trade_flag_low_volume(self, market_analytics_service, mock_settings_service):
        """Test that low volume prevents trading"""
        mock_settings_service.get_settings.return_value.min_volume_24h = 1000

        result, _ = await market_analytics_service.decide_trade_flag(
            make_indicators(profit=Decimal("5.00"), volume24h=500, volatility=Decimal("0.10"))
        )

        assert result is False

    async def test_decide_trade_flag_none_volume(self, market_analytics_service):
        """Test that None volume prevents trading"""
        result, _ = await market_analytics_service.decide_trade_flag(
            make_indicators(profit=Decimal("5.00"), volume24h=None, volatility=Decimal("0.10"))
        )

        assert result is False

    @pytest.mark.parametrize(
        "volatility,expected",
        [
            (Decimal("0.005"), True),
            (Decimal("0.60"), False),
            (Decimal("0.10"), True),  # Within range
        ],
    )
    async def test_decide_trade_flag_volatility_thresholds(
        self, market_analytics_service, mock_settings_service, volatility, expected
    ):
        """A calm price is fine; only a wild one is refused."""
        mock_settings_service.get_settings.return_value.max_volatility_threshold = Decimal("0.50")

        result, _ = await market_analytics_service.decide_trade_flag(
            make_indicators(profit=Decimal("5.00"), volume24h=500, volatility=volatility)
        )

        assert result is expected

    async def test_decide_trade_flag_all_conditions_met(self, market_analytics_service):
        """Test that trade is approved when all conditions are met"""
        result, _ = await market_analytics_service.decide_trade_flag(
            make_indicators(profit=Decimal("5.00"), volume24h=500, volatility=Decimal("0.10"))
        )

        assert result is True

    async def test_decide_trade_flag_calls_settings(self, market_analytics_service, mock_settings_service):
        """Test that decide_trade_flag calls settings service"""
        await market_analytics_service.decide_trade_flag(make_indicators())

        mock_settings_service.get_settings.assert_called_once()


def make_record(
    hours_ago: int, price: str, volume: int, base=datetime.datetime(2026, 8, 30, 12, tzinfo=datetime.timezone.utc)
):
    return PriceHistoryRecord(
        id=hours_ago + 1,
        market_hash_name="item",
        recorded_at=base - datetime.timedelta(hours=hours_ago),
        price=Decimal(price),
        volume=volume,
    )


@pytest.mark.asyncio
class TestComputeRecentStats:
    async def test_returns_none_for_no_records(self, market_analytics_service):
        assert await market_analytics_service.compute_recent_stats([]) == (None, None)

    async def test_sums_volume_inside_the_window(self, market_analytics_service):
        records = [make_record(h, "100.00", 10) for h in range(0, 24)]

        median, volume = await market_analytics_service.compute_recent_stats(records)

        assert volume == 240
        assert median == Decimal("100.00")

    async def test_ignores_records_outside_the_window(self, market_analytics_service):
        records = [make_record(0, "100.00", 5), make_record(48, "999.00", 1000)]

        median, volume = await market_analytics_service.compute_recent_stats(records)

        assert volume == 5
        assert median == Decimal("100.00")

    async def test_window_ends_at_the_newest_record_not_now(self, market_analytics_service):
        base = datetime.datetime(2020, 1, 1, tzinfo=datetime.timezone.utc)
        records = [make_record(h, "50.00", 3, base=base) for h in range(0, 5)]

        median, volume = await market_analytics_service.compute_recent_stats(records)

        assert volume == 15

    async def test_median_is_volume_weighted(self, market_analytics_service):
        records = [make_record(0, "10.00", 1), make_record(1, "20.00", 100)]

        median, volume = await market_analytics_service.compute_recent_stats(records)

        assert volume == 101
        assert median == Decimal("20.00")

    async def test_zero_volume_returns_no_median(self, market_analytics_service):
        records = [make_record(0, "10.00", 0), make_record(1, "20.00", 0)]

        assert await market_analytics_service.compute_recent_stats(records) == (None, 0)

    async def test_window_bound_is_exclusive(self, market_analytics_service):
        records = [make_record(h, "10.00", 1) for h in range(0, 25)]

        _, volume = await market_analytics_service.compute_recent_stats(records)

        assert volume == 24


class TestFilterPriceOutliers:
    def test_keeps_everything_when_prices_are_close(self, market_analytics_service):
        records = [make_record(h, p, 10) for h, p in enumerate(["6.80", "6.90", "7.00", "7.10"])]

        assert len(market_analytics_service.filter_price_outliers(records)) == 4

    def test_drops_prices_far_above_the_median(self, market_analytics_service):
        records = [make_record(h, p, 10) for h, p in enumerate(["6.80", "6.90", "7.00", "1463.75"])]

        kept = market_analytics_service.filter_price_outliers(records)

        assert [str(r.price) for r in kept] == ["6.80", "6.90", "7.00"]

    def test_drops_prices_far_below_the_median(self, market_analytics_service):
        records = [make_record(h, p, 10) for h, p in enumerate(["6.80", "6.90", "7.00", "0.01"])]

        kept = market_analytics_service.filter_price_outliers(records)

        assert all(r.price > Decimal("1") for r in kept)

    def test_keeps_a_genuine_move_within_the_factor(self, market_analytics_service):
        records = [make_record(h, p, 10) for h, p in enumerate(["10.00", "10.00", "10.00", "40.00"])]

        assert len(market_analytics_service.filter_price_outliers(records)) == 4

    def test_handles_no_records(self, market_analytics_service):
        assert market_analytics_service.filter_price_outliers([]) == []

    @pytest.mark.asyncio
    async def test_volatility_drops_once_outliers_are_removed(self, market_analytics_service):
        normal = [make_record(h, "6.90", 10) for h in range(0, 10)]
        spiked = normal + [make_record(10, "1463.75", 8)]

        raw = await market_analytics_service.compute_volume_weighted_volatility(spiked)
        clean = await market_analytics_service.compute_volume_weighted_volatility(
            market_analytics_service.filter_price_outliers(spiked)
        )

        assert raw > clean


class TestHistoryDescribesCurrentMarket:
    def test_accepts_history_around_the_current_price(self, market_analytics_service):
        records = [make_record(h, "6.90", 10) for h in range(4)]

        assert market_analytics_service.history_describes_current_market(records, Decimal("6.82"))

    def test_rejects_history_far_above_the_current_price(self, market_analytics_service):
        records = [make_record(h, "1141.08", 10) for h in range(4)]

        assert not market_analytics_service.history_describes_current_market(records, Decimal("5.18"))

    def test_rejects_history_far_below_the_current_price(self, market_analytics_service):
        records = [make_record(h, "1.00", 10) for h in range(4)]

        assert not market_analytics_service.history_describes_current_market(records, Decimal("50.00"))

    def test_accepts_a_move_inside_the_factor(self, market_analytics_service):
        records = [make_record(h, "10.00", 10) for h in range(4)]

        assert market_analytics_service.history_describes_current_market(records, Decimal("6.00"))

    def test_cannot_judge_without_a_current_price(self, market_analytics_service):
        records = [make_record(h, "1141.08", 10) for h in range(4)]

        assert market_analytics_service.history_describes_current_market(records, None)

    def test_cannot_judge_without_history(self, market_analytics_service):
        assert market_analytics_service.history_describes_current_market([], Decimal("6.82"))


class TestSimulateRoundTrips:
    def test_counts_a_completed_round_trip(self, market_analytics_service):
        records = [make_record(4, "6.00", 10), make_record(2, "9.00", 10)]

        trips, hold = market_analytics_service.simulate_round_trips(records, Decimal("6.50"), Decimal("8.50"))

        assert trips == 1
        assert hold == Decimal("2.0")

    def test_an_unfinished_trip_does_not_count(self, market_analytics_service):
        records = [make_record(4, "6.00", 10), make_record(2, "7.00", 10)]

        trips, hold = market_analytics_service.simulate_round_trips(records, Decimal("6.50"), Decimal("8.50"))

        assert trips == 0
        assert hold is None

    def test_counts_several_trips_and_takes_the_median_hold(self, market_analytics_service):
        records = [
            make_record(10, "6.00", 10),
            make_record(9, "9.00", 10),
            make_record(8, "6.00", 10),
            make_record(4, "9.00", 10),
        ]

        trips, hold = market_analytics_service.simulate_round_trips(records, Decimal("6.50"), Decimal("8.50"))

        assert trips == 2
        assert hold == Decimal("2.5")

    def test_a_rise_without_a_dip_first_is_ignored(self, market_analytics_service):
        records = [make_record(4, "9.00", 10), make_record(2, "9.50", 10)]

        trips, _ = market_analytics_service.simulate_round_trips(records, Decimal("6.50"), Decimal("8.50"))

        assert trips == 0


class TestProjectReturnOnCapital:
    def test_scales_the_window_to_thirty_days(self, market_analytics_service):
        # 1.00 profit on 10.00 capital, 5 trips over 15 days -> 50% per 15d -> 100% per 30d
        result = market_analytics_service.project_return_on_capital(Decimal("1.00"), 5, Decimal("10.00"), 15)

        assert result == Decimal("100.0")

    def test_a_shorter_window_projects_higher(self, market_analytics_service):
        weekly = market_analytics_service.project_return_on_capital(Decimal("1.00"), 5, Decimal("10.00"), 7)
        monthly = market_analytics_service.project_return_on_capital(Decimal("1.00"), 5, Decimal("10.00"), 30)

        assert weekly > monthly

    def test_no_trips_means_no_return(self, market_analytics_service):
        assert market_analytics_service.project_return_on_capital(Decimal("1.00"), 0, Decimal("10.00"), 7) == 0

    def test_guards_against_a_zero_price(self, market_analytics_service):
        assert market_analytics_service.project_return_on_capital(Decimal("1.00"), 5, Decimal("0"), 7) is None


@pytest.mark.asyncio
class TestVelocityGates:
    async def test_a_slow_item_is_rejected(self, market_analytics_service):
        flag, reason = await market_analytics_service.decide_trade_flag(
            make_indicators(median_hold_hours=Decimal("256.0"))
        )

        assert flag is False
        assert "holding time" in reason

    async def test_a_poor_return_is_rejected(self, market_analytics_service):
        flag, reason = await market_analytics_service.decide_trade_flag(
            make_indicators(return_on_capital_30d=Decimal("5.0"))
        )

        assert flag is False
        assert "return" in reason

    async def test_an_item_that_never_completes_a_trip_is_rejected(self, market_analytics_service):
        flag, reason = await market_analytics_service.decide_trade_flag(
            make_indicators(round_trips=0, median_hold_hours=None)
        )

        assert flag is False
        assert "never covered" in reason

    async def test_a_fast_profitable_item_passes(self, market_analytics_service):
        flag, reason = await market_analytics_service.decide_trade_flag(make_indicators())

        assert flag is True
        assert reason == ""


@pytest.mark.asyncio
class TestMarginAndWeeklyVolumeGates:
    async def test_a_thin_week_is_rejected(self, market_analytics_service, mock_settings_service):
        mock_settings_service.get_settings.return_value.min_volume_7d = 5000

        flag, reason = await market_analytics_service.decide_trade_flag(make_indicators(volume7d=100))

        assert flag is False
        assert "7d" in reason

    async def test_a_missing_weekly_volume_is_rejected(self, market_analytics_service):
        flag, reason = await market_analytics_service.decide_trade_flag(make_indicators(volume7d=None))

        assert flag is False


class TestTheQueueInFrontOfUs:
    @staticmethod
    def levels(*pairs):
        return [{"price": Decimal(p), "quantity": q} for p, q in pairs]

    def test_only_listings_at_or_under_our_price_count(self):
        book = self.levels(("10.00", 5), ("11.00", 3), ("12.00", 7))

        assert MarketAnalyticsService.queue_ahead(book, Decimal("11.00")) == 8

    def test_being_the_cheapest_means_an_empty_queue(self):
        book = self.levels(("10.00", 5), ("11.00", 3))

        assert MarketAnalyticsService.queue_ahead(book, Decimal("9.00")) == 0

    def test_an_unreadable_book_is_not_an_empty_one(self):
        assert MarketAnalyticsService.queue_ahead([], Decimal("11.00")) is None
        assert MarketAnalyticsService.queue_ahead(self.levels(("10.00", 5)), None) is None

    def test_the_wait_is_the_queue_over_the_daily_rate(self):
        assert MarketAnalyticsService.days_to_clear(600, Decimal("200")) == Decimal("3.0")

    def test_a_dead_market_gives_no_answer(self):
        assert MarketAnalyticsService.days_to_clear(600, Decimal("0")) is None
        assert MarketAnalyticsService.days_to_clear(None, Decimal("200")) is None

    def test_a_long_queue_caps_the_trips_the_history_promised(self):
        """A week of queue leaves room for four trips a month, whatever the price did."""
        assert MarketAnalyticsService.feasible_round_trips(19, Decimal("7"), 30) == 4

    def test_a_short_queue_leaves_the_history_alone(self):
        assert MarketAnalyticsService.feasible_round_trips(19, Decimal("0.5"), 30) == 19

    def test_an_unknown_queue_changes_nothing(self):
        assert MarketAnalyticsService.feasible_round_trips(19, None, 30) == 19

    def test_a_queue_longer_than_the_window_rules_the_item_out(self):
        assert MarketAnalyticsService.feasible_round_trips(19, Decimal("45"), 30) == 0


def oscillating(low="8.00", high="12.00", cycles=8, volume=40):
    start = datetime.datetime(2026, 9, 1, tzinfo=datetime.timezone.utc)
    points = []
    for i, price in enumerate([low, high] * cycles):
        points.append(
            SimpleNamespace(recorded_at=start + datetime.timedelta(hours=6 * i), price=Decimal(price), volume=volume)
        )
    return points


@pytest.mark.asyncio
class TestTheSharedJudgement:
    @pytest_asyncio.fixture(autouse=True)
    def rules(self, mock_settings_service):
        settings = mock_settings_service.get_settings.return_value
        settings.buy_percentile = 10
        settings.sell_percentile = 90
        settings.min_profit_threshold = Decimal("0.30")
        settings.min_volume_24h = 10
        settings.min_volume_7d = 50
        settings.max_volatility_threshold = Decimal("5")
        settings.max_hold_hours = 48
        settings.min_return_on_capital_30d = Decimal("20")

    async def evaluate(self, service, records, current_price=Decimal("10.00"), levels=None, window=14):
        return await service.evaluate(records, current_price, 500, levels or [], window)

    async def test_a_healthy_item_is_approved(self, market_analytics_service):
        verdict = await self.evaluate(market_analytics_service, oscillating())

        assert verdict.tradable is True
        assert verdict.reason == ""
        assert verdict.choice.price > verdict.buy_target

    async def test_a_thin_history_is_left_undecided(self, market_analytics_service):
        verdict = await self.evaluate(market_analytics_service, oscillating(cycles=1)[:1])

        assert verdict.tradable is False
        assert verdict.choice is None
        assert verdict.reason == "not enough price history"

    async def test_history_from_another_price_era_is_refused(self, market_analytics_service):
        verdict = await self.evaluate(market_analytics_service, oscillating(), current_price=Decimal("40.00"))

        assert verdict.tradable is False
        assert "centred far from the current price" in verdict.reason

    async def test_the_return_follows_the_trips_the_queue_allows(self, market_analytics_service):
        """With a wall in front of every price, the history's trips are not the ones we would get."""
        open_book = await self.evaluate(market_analytics_service, oscillating())
        walled = await self.evaluate(
            market_analytics_service, oscillating(), levels=[{"price": Decimal("7.00"), "quantity": 5000}]
        )

        assert walled.choice.feasible_round_trips < open_book.choice.feasible_round_trips
        assert walled.return_on_capital_30d < open_book.return_on_capital_30d

    async def test_a_razor_thin_margin_is_refused(self, market_analytics_service, mock_settings_service):
        mock_settings_service.get_settings.return_value.min_profit_threshold = Decimal("50.00")

        verdict = await self.evaluate(market_analytics_service, oscillating())

        assert verdict.tradable is False
        assert verdict.reason.startswith("profit")
