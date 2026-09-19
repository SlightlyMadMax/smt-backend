import asyncio
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from smt.services.market_analytics import MarketAnalyticsService
from smt.services.market_scan import (
    LATEST_KEY,
    SCAN_KEY,
    Candidate,
    MarketScanService,
    ScanParams,
    candidate_from_search_row,
)
from smt.services.stats_refresh import StatsRefreshService


NOW = datetime(2026, 9, 1, tzinfo=timezone.utc)
WINDOW = 14


class FakeRedis:
    def __init__(self):
        self.store = {}

    async def set(self, key, value, ex=None):
        self.store[key] = value

    async def get(self, key):
        return self.store.get(key)


def search_row(name="Rainy Day Cosmetic Case", price=958):
    return {
        "hash_name": name,
        "name": name,
        "sell_listings": 4200,
        "sell_price": price,
        "asset_description": {"appid": 440, "icon_url": "ICON"},
    }


def history(prices, volume=50, step_hours=6):
    return [(NOW + timedelta(hours=i * step_hours), Decimal(p), volume) for i, p in enumerate(prices)]


def make_candidate(price="9.58"):
    return candidate_from_search_row(search_row(price=int(Decimal(price) * 100)), "440", "2")


@pytest.fixture
def rules():
    return SimpleNamespace(
        analysis_window_days=WINDOW,
        buy_percentile=10,
        sell_percentile=90,
        min_profit_threshold=Decimal("0.30"),
        min_volume_24h=0,
        min_volume_7d=0,
        max_volatility_threshold=Decimal("5"),
        max_hold_hours=48,
        min_return_on_capital_30d=Decimal("0"),
    )


@pytest.fixture
def settings_service(rules):
    service = AsyncMock()
    service.get_settings.return_value = rules
    return service


@pytest.fixture
def redis():
    return FakeRedis()


@pytest.fixture
def scan_service(redis, settings_service):
    service = MarketScanService(AsyncMock(), redis, MarketAnalyticsService(settings_service), settings_service)
    service.steam.get_order_book.return_value = {"sell_levels": []}
    return service


class TestReadingASearchRow:
    def test_every_field_the_pool_needs_is_taken(self):
        candidate = candidate_from_search_row(search_row(), "440", "2")

        assert candidate.market_hash_name == "Rainy Day Cosmetic Case"
        assert candidate.app_id == "440"
        assert candidate.context_id == "2"
        assert candidate.current_price == Decimal("9.58")
        assert candidate.icon_url.endswith("/ICON")

    def test_a_row_without_an_icon_does_not_invent_a_url(self):
        row = search_row()
        row["asset_description"]["icon_url"] = ""

        assert candidate_from_search_row(row, "440", "2").icon_url == ""


@pytest.mark.asyncio
class TestMeasuring:
    async def measure(self, scan_service, points, window=WINDOW, candidate=None):
        scan_service.steam.get_price_history.return_value = points
        return await scan_service.measure(candidate or make_candidate(), window)

    async def test_the_history_read_is_the_window_the_settings_name(self, scan_service):
        await self.measure(scan_service, history(["8.00", "12.00"] * 4))

        assert scan_service.steam.get_price_history.await_args.kwargs["days"] == WINDOW

    async def test_a_thin_history_is_rejected(self, scan_service):
        measured = await self.measure(scan_service, history(["9.50"]))

        assert measured.tradable is False
        assert measured.note == "not enough price history"
        assert measured.buy_target is None

    async def test_history_from_another_price_era_is_rejected(self, scan_service):
        measured = await self.measure(scan_service, history(["40.00", "60.00"] * 4))

        assert measured.tradable is False
        assert "centred far from the current price" in measured.note

    async def test_a_quiet_week_is_rejected_by_the_pool_rule(self, scan_service, rules):
        rules.min_volume_7d = 5000

        measured = await self.measure(scan_service, history(["8.00", "12.00"] * 4, volume=1))

        assert measured.tradable is False
        assert "volume over 7d" in measured.note

    async def test_a_wide_spread_is_approved(self, scan_service):
        measured = await self.measure(scan_service, history(["8.00", "12.00", "8.20", "12.40", "8.10", "12.20"]))

        assert measured.tradable is True
        assert measured.note == ""
        assert measured.sell_target > measured.buy_target
        assert measured.round_trips > 0

    async def test_the_queue_cuts_the_trips_the_history_promised(self, scan_service):
        """240 listings under ours at under eleven sales a day is a three week wait, so one trip a month."""
        scan_service.steam.get_order_book.return_value = {"sell_levels": [{"price": Decimal("9.00"), "quantity": 240}]}

        measured = await self.measure(scan_service, history(["8.00", "12.00"] * 8, volume=20), window=30)

        assert measured.queue_ahead == 240
        assert measured.round_trips == 8
        assert measured.days_to_clear == Decimal("22.5")
        assert measured.feasible_round_trips == 1
        assert measured.profit_per_window == measured.profit_per_trade

    async def test_being_the_cheapest_leaves_the_history_alone(self, scan_service):
        scan_service.steam.get_order_book.return_value = {"sell_levels": [{"price": Decimal("99.00"), "quantity": 5}]}

        measured = await self.measure(scan_service, history(["8.00", "12.00", "8.20", "12.40"]))

        assert measured.queue_ahead == 0
        assert measured.feasible_round_trips == measured.round_trips

    async def test_an_unreadable_book_does_not_sink_the_item(self, scan_service):
        scan_service.steam.get_order_book.side_effect = RuntimeError("429")

        measured = await self.measure(scan_service, history(["8.00", "12.00", "8.20", "12.40"]))

        assert measured.queue_ahead is None
        assert measured.feasible_round_trips == measured.round_trips
        assert measured.tradable is True

    async def test_a_wall_of_listings_pushes_the_asking_price_under_it(self, scan_service):
        """Asking above the wall earns more per sale and never sells; the search should see that."""
        scan_service.steam.get_order_book.return_value = {
            "sell_levels": [
                {"price": Decimal("11.00"), "quantity": 2},
                {"price": Decimal("11.50"), "quantity": 900},
            ]
        }

        measured = await self.measure(
            scan_service, history(["9.00", "11.20", "9.10", "11.90", "9.05", "12.40"] * 3, volume=20)
        )

        assert measured.sell_target <= Decimal("11.50")
        assert measured.queue_ahead <= 2

    async def test_the_ceiling_in_the_settings_is_never_crossed(self, scan_service, rules):
        rules.sell_percentile = 60

        measured = await self.measure(scan_service, history(["8.00", "12.00"] * 6))

        assert measured.sell_percentile_used <= 60

    async def test_the_return_is_quoted_per_thirty_days_like_the_pool(self, scan_service):
        measured = await self.measure(scan_service, history(["8.00", "12.00"] * 6))

        assert measured.return_on_capital_pct == MarketAnalyticsService.project_return_on_capital(
            measured.profit_per_trade, measured.feasible_round_trips, measured.buy_target, WINDOW
        )

    async def test_a_thin_margin_is_refused_by_the_pool_rule(self, scan_service):
        measured = await self.measure(scan_service, history(["9.50", "9.60", "9.55", "9.62", "9.51", "9.58"]))

        assert measured.tradable is False
        assert measured.note.startswith("profit")


@pytest.mark.asyncio
class TestTheScanAndThePoolAgree:
    """The whole point of sharing one judgement: what the scan recommends, the pool takes."""

    @staticmethod
    def pool_for(settings_service, records, item):
        pool = StatsRefreshService(
            price_history_service=AsyncMock(),
            pool_service=AsyncMock(),
            steam_service=AsyncMock(),
            analytics_service=MarketAnalyticsService(settings_service),
            settings_service=settings_service,
        )
        pool.price_history_service.list.return_value = records
        pool.pool_service.get_many.return_value = [item]
        return pool

    @pytest.mark.parametrize(
        "prices, levels",
        [
            (["8.00", "12.00", "8.20", "12.40", "8.10", "12.20"] * 2, []),
            (["8.00", "12.00"] * 8, [{"price": Decimal("9.00"), "quantity": 240}]),
            (["9.50", "9.60", "9.55", "9.62", "9.51", "9.58"], []),
            (["40.00", "60.00"] * 4, []),
        ],
    )
    async def test_same_history_same_verdict(self, scan_service, settings_service, prices, levels):
        points = history(prices)
        scan_service.steam.get_price_history.return_value = points
        scan_service.steam.get_order_book.return_value = {"sell_levels": levels}
        candidate = await scan_service.measure(make_candidate(), WINDOW)

        records = [SimpleNamespace(recorded_at=m, price=p, volume=v) for m, p, v in points]
        _, volume24h = await MarketAnalyticsService.compute_recent_stats(records)
        item = SimpleNamespace(
            market_hash_name=candidate.market_hash_name,
            app_id="440",
            current_volume24h=volume24h,
            current_lowest_price=candidate.current_price,
        )
        pool = self.pool_for(settings_service, records, item)
        pool.steam.get_order_book.return_value = {"sell_levels": levels}

        await pool.refresh_indicators([item.market_hash_name])

        stored = pool.pool_service.update.await_args.args[1]
        assert stored.use_for_trading == candidate.tradable
        assert stored.optimal_sell_price == candidate.sell_target
        assert stored.return_on_capital_30d == candidate.return_on_capital_pct


@pytest.mark.asyncio
class TestRunningAScan:
    @staticmethod
    def one_page(scan_service, rows):
        scan_service.steam.search_market.return_value = {"results": rows, "total_count": len(rows)}
        scan_service.steam.get_price_history.return_value = history(["8.00", "12.00", "8.20", "12.40"])

    async def stored(self, scan_service, scan_id):
        return await scan_service.get(scan_id)

    async def test_a_finished_scan_holds_its_candidates(self, scan_service, redis):
        self.one_page(scan_service, [search_row("A"), search_row("B")])

        await scan_service.run("scan-1", ScanParams(limit=2))

        state = await self.stored(scan_service, "scan-1")
        assert state["status"] == "done"
        assert [c["market_hash_name"] for c in state["candidates"]] == ["A", "B"]
        assert redis.store[LATEST_KEY] == "scan-1"

    async def test_the_rules_it_was_judged_by_are_kept(self, scan_service):
        """Change a setting later and the old scan is visibly stale."""
        self.one_page(scan_service, [search_row("A")])

        await scan_service.run("scan-8", ScanParams(limit=1))

        rules = (await self.stored(scan_service, "scan-8"))["rules"]
        assert rules["analysis_window_days"] == str(WINDOW)
        assert rules["min_profit_threshold"] == "0.30"

    async def test_progress_is_visible_while_it_runs(self, scan_service, redis):
        self.one_page(scan_service, [search_row("A"), search_row("B")])
        seen = []
        original = scan_service.steam.get_price_history

        async def watching(*args, **kwargs):
            seen.append(json.loads(redis.store[f"{SCAN_KEY}scan-2"])["measured"])
            return await original(*args, **kwargs)

        scan_service.steam.get_price_history = watching

        await scan_service.run("scan-2", ScanParams(limit=2))

        assert seen == [0, 1]

    async def test_a_failure_is_recorded_rather_than_raised(self, scan_service):
        scan_service.steam.search_market.side_effect = RuntimeError("steam is down")

        await scan_service.run("scan-3", ScanParams(limit=2))

        state = await self.stored(scan_service, "scan-3")
        assert state["status"] == "failed"
        assert "steam is down" in state["error"]

    async def test_one_bad_item_does_not_sink_the_scan(self, scan_service):
        self.one_page(scan_service, [search_row("A"), search_row("B")])
        scan_service.steam.get_price_history.side_effect = [RuntimeError("429"), history(["8.00", "12.00", "8.20"])]

        await scan_service.run("scan-4", ScanParams(limit=2))

        state = await self.stored(scan_service, "scan-4")
        assert state["status"] == "done"
        assert "RuntimeError" in state["candidates"][0]["note"]
        assert "RuntimeError" not in state["candidates"][1]["note"]

    async def test_a_cancelled_scan_keeps_what_it_measured(self, scan_service):
        """arq cancels a job that runs past its timeout; the work already done is still worth having."""
        self.one_page(scan_service, [search_row("A"), search_row("B")])
        scan_service.steam.get_price_history.side_effect = [
            history(["8.00", "12.00", "8.20"]),
            asyncio.CancelledError(),
        ]

        with pytest.raises(asyncio.CancelledError):
            await scan_service.run("scan-7", ScanParams(limit=2))

        state = await self.stored(scan_service, "scan-7")
        assert state["status"] == "failed"
        assert "measuring 1 of 2 items" in state["error"]
        assert len(state["candidates"]) == 1

    async def test_the_latest_scan_can_be_found_again(self, scan_service):
        self.one_page(scan_service, [search_row("A")])

        await scan_service.run("scan-5", ScanParams(limit=1))

        assert (await scan_service.latest())["id"] == "scan-5"

    async def test_prices_outside_the_band_are_not_collected(self, scan_service):
        self.one_page(scan_service, [search_row("cheap", price=100), search_row("dear", price=9000)])

        await scan_service.run("scan-6", ScanParams(limit=5, min_price=Decimal("50"), max_price=Decimal("200")))

        state = await self.stored(scan_service, "scan-6")
        assert [c["market_hash_name"] for c in state["candidates"]] == ["dear"]


class TestCandidateSerialisation:
    def test_decimals_survive_the_trip_through_json(self):
        candidate = Candidate(
            market_hash_name="A",
            name="A",
            icon_url="",
            app_id="440",
            context_id="2",
            listings=1,
            current_price=Decimal("9.58"),
            buy_target=Decimal("8.71"),
        )

        row = json.loads(json.dumps(candidate.as_dict()))

        assert row["current_price"] == "9.58"
        assert Decimal(row["buy_target"]) == Decimal("8.71")
