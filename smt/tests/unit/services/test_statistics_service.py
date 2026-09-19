from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import delete

from smt.db.models import PoolItem, Position
from smt.repositories.position import PositionRepo
from smt.schemas.position import PositionStatus
from smt.services.statistics import StatisticsService


FAST = "Rainy Day Cosmetic Case"
SLOW = "Secret Saxton"
NOW = datetime.now(timezone.utc).replace(tzinfo=None)


@pytest_asyncio.fixture
def statistics_service(db_session) -> StatisticsService:
    return StatisticsService(PositionRepo(db_session))


@pytest_asyncio.fixture(autouse=True)
async def pool(db_session):
    await db_session.execute(delete(Position))
    await db_session.execute(delete(PoolItem))
    db_session.add_all(
        [
            PoolItem(
                market_hash_name=FAST,
                name="Rainy Day",
                app_id="440",
                context_id="2",
                icon_url="http://example.com/fast.png",
                potential_profit=Decimal("2.25"),
                median_hold_hours=Decimal("2.0"),
                return_on_capital_30d=Decimal("262.5"),
            ),
            PoolItem(
                market_hash_name=SLOW,
                name="Secret Saxton",
                app_id="440",
                context_id="2",
                icon_url="http://example.com/slow.png",
            ),
        ]
    )
    await db_session.commit()
    yield


def closed(
    hash_name: str,
    buy: str,
    profit: str,
    sold_days_ago: float,
    hold_hours: float = 4.0,
    listed_hours: float = 1.0,
    buy_wait_hours: float = 2.0,
    **forecast,
) -> Position:
    sold_at = NOW - timedelta(days=sold_days_ago)
    bought_at = sold_at - timedelta(hours=hold_hours)
    return Position(
        pool_item_hash=hash_name,
        app_id="440",
        context_id="2",
        buy_order_id=f"buy-{hash_name}-{sold_days_ago}-{profit}-{hold_hours}",
        buy_price=Decimal(buy),
        sell_price=Decimal(buy) * Decimal("1.2"),
        net_proceeds=Decimal(buy) + Decimal(profit),
        realized_profit=Decimal(profit),
        status=PositionStatus.CLOSED,
        created_at=bought_at - timedelta(hours=buy_wait_hours),
        bought_at=bought_at,
        listed_at=sold_at - timedelta(hours=listed_hours),
        sold_at=sold_at,
        **forecast,
    )


async def add(db_session, *positions):
    db_session.add_all(positions)
    await db_session.commit()


@pytest.mark.asyncio
class TestFunnel:
    async def test_every_stage_is_counted(self, db_session, statistics_service):
        await add(
            db_session,
            Position(
                pool_item_hash=FAST,
                app_id="440",
                context_id="2",
                buy_order_id="never-filled",
                buy_price=Decimal("10"),
                sell_price=Decimal("12"),
                status=PositionStatus.CANCELLED,
            ),
            Position(
                pool_item_hash=FAST,
                app_id="440",
                context_id="2",
                buy_order_id="still-waiting",
                buy_price=Decimal("10"),
                sell_price=Decimal("12"),
                status=PositionStatus.OPEN,
            ),
            Position(
                pool_item_hash=FAST,
                app_id="440",
                context_id="2",
                buy_order_id="not-sold-yet",
                buy_price=Decimal("10"),
                sell_price=Decimal("12"),
                status=PositionStatus.LISTED,
                bought_at=NOW - timedelta(hours=3),
            ),
            closed(FAST, "10", "1.00", sold_days_ago=1),
        )

        funnel = (await statistics_service.overview())["funnel"]

        assert funnel["opened"] == 4
        assert funnel["bought"] == 2
        assert funnel["sold"] == 1
        assert funnel["cancelled"] == 1
        assert funnel["fill_rate"] == Decimal("50.0")
        assert funnel["sell_through"] == Decimal("50.0")

    async def test_rates_are_absent_without_positions(self, statistics_service):
        funnel = (await statistics_service.overview())["funnel"]

        assert funnel["opened"] == 0
        assert funnel["fill_rate"] is None
        assert funnel["sell_through"] is None


@pytest.mark.asyncio
class TestItems:
    async def test_ranked_by_realised_profit(self, db_session, statistics_service):
        await add(
            db_session,
            closed(SLOW, "10", "0.50", sold_days_ago=2),
            closed(FAST, "10", "3.00", sold_days_ago=3),
        )

        items = (await statistics_service.overview())["items"]

        assert [item["market_hash_name"] for item in items] == [FAST, SLOW]

    async def test_trades_of_one_item_are_added_up(self, db_session, statistics_service):
        await add(
            db_session,
            closed(FAST, "10", "1.00", sold_days_ago=2),
            closed(FAST, "12", "2.00", sold_days_ago=3),
        )

        item = (await statistics_service.overview())["items"][0]

        assert item["trades"] == 2
        assert item["profit"] == Decimal("3.00")
        assert item["avg_profit"] == Decimal("1.50")
        assert item["capital"] == Decimal("11.00")

    async def test_top_limits_the_rows(self, db_session, statistics_service):
        await add(
            db_session,
            closed(FAST, "10", "1.00", sold_days_ago=2),
            closed(SLOW, "10", "2.00", sold_days_ago=2),
        )

        assert len((await statistics_service.overview(top=1))["items"]) == 1

    async def test_hold_time_comes_from_the_timestamps(self, db_session, statistics_service):
        await add(
            db_session,
            closed(FAST, "10", "1.00", sold_days_ago=2, hold_hours=3),
            closed(FAST, "10", "1.00", sold_days_ago=3, hold_hours=5),
            closed(FAST, "10", "1.00", sold_days_ago=4, hold_hours=13),
        )

        assert (await statistics_service.overview())["items"][0]["median_hold_hours"] == Decimal("5.0")

    async def test_the_forecast_is_the_one_each_trade_was_opened_on(self, db_session, statistics_service):
        """The pool re-estimates every hour; comparing today's estimate with last week's trade says nothing."""
        await add(
            db_session,
            closed(
                FAST,
                "10",
                "1.00",
                sold_days_ago=2,
                forecast_profit=Decimal("0.80"),
                forecast_hold_hours=Decimal("6.0"),
                forecast_days_to_clear=Decimal("0.5"),
                forecast_return_30d=Decimal("90.0"),
            ),
        )

        item = (await statistics_service.overview())["items"][0]

        assert item["forecast_profit"] == Decimal("0.80")
        assert item["forecast_hold_hours"] == Decimal("6.0")
        assert item["forecast_sell_wait_hours"] == Decimal("12.0")
        assert item["forecast_return_30d"] == Decimal("90.0")

    async def test_several_trades_are_summarised_like_the_actuals(self, db_session, statistics_service):
        await add(
            db_session,
            closed(FAST, "10", "1.00", 1, forecast_profit=Decimal("0.60"), forecast_hold_hours=Decimal("4.0")),
            closed(FAST, "10", "1.00", 2, forecast_profit=Decimal("0.80"), forecast_hold_hours=Decimal("6.0")),
            closed(FAST, "10", "1.00", 3, forecast_profit=Decimal("1.30"), forecast_hold_hours=Decimal("30.0")),
        )

        item = (await statistics_service.overview())["items"][0]

        assert item["forecast_profit"] == Decimal("0.90")
        assert item["forecast_hold_hours"] == Decimal("6.0")

    async def test_the_forecast_outlives_the_item_leaving_the_pool(self, db_session, statistics_service):
        await add(db_session, closed(FAST, "10", "1.00", 2, forecast_profit=Decimal("0.80")))
        await db_session.execute(delete(PoolItem).where(PoolItem.market_hash_name == FAST))
        await db_session.commit()
        db_session.expunge_all()

        item = (await statistics_service.overview())["items"][0]

        assert item["forecast_profit"] == Decimal("0.80")

    async def test_a_trade_opened_before_forecasts_were_kept_shows_none(self, db_session, statistics_service):
        """Falling back on the pool's current estimate would quietly bring the old mistake back."""
        await add(db_session, closed(FAST, "10", "1.00", sold_days_ago=2))

        item = (await statistics_service.overview())["items"][0]

        assert item["forecast_profit"] is None
        assert item["forecast_return_30d"] is None

    async def test_the_waits_on_both_sides_are_measured(self, db_session, statistics_service):
        """Nothing forecasts the buy wait; the model assumes the order fills. This is where that gets checked."""
        await add(db_session, closed(FAST, "10", "1.00", 2, listed_hours=5, buy_wait_hours=30))

        item = (await statistics_service.overview())["items"][0]

        assert item["sell_wait_hours"] == Decimal("5.0")
        assert item["buy_wait_hours"] == Decimal("30.0")

    async def test_return_is_scaled_to_thirty_days(self, db_session, statistics_service):
        """Ten percent earned over fifteen days is twenty percent over thirty.

        The window runs from the first purchase to the last sale, so these hold nothing.
        """
        await add(
            db_session,
            closed(FAST, "10", "0.00", sold_days_ago=15, hold_hours=0),
            closed(FAST, "10", "0.00", sold_days_ago=8, hold_hours=0),
            closed(FAST, "10", "1.00", sold_days_ago=0, hold_hours=0),
        )

        item = (await statistics_service.overview())["items"][0]

        assert item["observed_days"] == Decimal("15.0")
        assert item["actual_return_30d"] == Decimal("20.0")

    async def test_a_short_run_is_not_scaled_up(self, db_session, statistics_service):
        """Three days of trading says nothing about thirty."""
        await add(
            db_session,
            closed(FAST, "10", "1.00", sold_days_ago=3, hold_hours=0),
            closed(FAST, "10", "1.00", sold_days_ago=2, hold_hours=0),
            closed(FAST, "10", "1.00", sold_days_ago=0, hold_hours=0),
        )

        item = (await statistics_service.overview())["items"][0]

        assert item["profit"] == Decimal("3.00")
        assert item["actual_return_30d"] is None

    async def test_too_few_trades_are_not_scaled_up(self, db_session, statistics_service):
        await add(
            db_session,
            closed(FAST, "10", "1.00", sold_days_ago=20, hold_hours=0),
            closed(FAST, "10", "1.00", sold_days_ago=0, hold_hours=0),
        )

        assert (await statistics_service.overview())["items"][0]["actual_return_30d"] is None

    async def test_positions_still_in_flight_are_left_out(self, db_session, statistics_service):
        await add(
            db_session,
            Position(
                pool_item_hash=FAST,
                app_id="440",
                context_id="2",
                buy_order_id="open",
                buy_price=Decimal("10"),
                sell_price=Decimal("12"),
                status=PositionStatus.LISTED,
                bought_at=NOW - timedelta(hours=2),
            ),
        )

        assert (await statistics_service.overview())["items"] == []


@pytest.mark.asyncio
class TestDailyProfit:
    async def test_profit_is_grouped_by_the_day_it_closed(self, db_session, statistics_service):
        await add(
            db_session,
            closed(FAST, "10", "1.00", sold_days_ago=1),
            closed(FAST, "10", "2.00", sold_days_ago=1),
            closed(SLOW, "10", "0.50", sold_days_ago=2),
        )

        daily = (await statistics_service.overview())["daily_profit"]

        assert [entry["profit"] for entry in daily] == [Decimal("0.50"), Decimal("3.00")]

    async def test_older_closes_fall_outside_the_window(self, db_session, statistics_service):
        await add(
            db_session,
            closed(FAST, "10", "1.00", sold_days_ago=2),
            closed(FAST, "10", "5.00", sold_days_ago=40),
        )

        daily = (await statistics_service.overview(days=30))["daily_profit"]

        assert [entry["profit"] for entry in daily] == [Decimal("1.00")]


@pytest.mark.asyncio
class TestClocksThatDisagree:
    async def test_a_sale_stamped_before_the_listing_counts_as_instant(self, db_session, statistics_service):
        """Steam's clock ran ten seconds behind ours on the one real sale; a negative wait is that, not time travel."""
        await add(db_session, closed(FAST, "10", "1.00", 2, listed_hours=-9 / 3600))

        item = (await statistics_service.overview())["items"][0]

        assert item["sell_wait_hours"] == Decimal("0.0")
