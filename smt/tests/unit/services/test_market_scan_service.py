import asyncio
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from smt.services.market_scan import (
    LATEST_KEY,
    SCAN_KEY,
    Candidate,
    MarketScanService,
    ScanParams,
    candidate_from_search_row,
)


NOW = datetime(2026, 9, 1, tzinfo=timezone.utc)


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
def redis():
    return FakeRedis()


@pytest.fixture
def scan_service(redis):
    return MarketScanService(AsyncMock(), redis)


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
    async def measure(self, scan_service, points, **overrides):
        scan_service.steam.get_price_history.return_value = points
        params = ScanParams(**{"min_volume": 0, **overrides})
        return await scan_service.measure(make_candidate(), params)

    async def test_a_thin_history_is_rejected(self, scan_service):
        measured = await self.measure(scan_service, history(["9.50"]))

        assert measured.note == "not enough history"
        assert measured.buy_target is None

    async def test_history_from_another_price_era_is_rejected(self, scan_service):
        measured = await self.measure(scan_service, history(["40.00", "42.00", "41.00", "43.00"]))

        assert "the current price" in measured.note

    async def test_a_quiet_item_is_rejected(self, scan_service):
        points = history(["9.00", "10.00", "9.20", "10.40"], volume=1)

        measured = await self.measure(scan_service, points, min_volume=500)

        assert "sold over the window" in measured.note

    async def test_a_wide_spread_is_measured(self, scan_service):
        points = history(["8.00", "12.00", "8.20", "12.40", "8.10", "12.20"])

        measured = await self.measure(scan_service, points)

        assert measured.buy_target is not None
        assert measured.sell_target > measured.buy_target
        assert measured.tradable is True
        assert measured.round_trips > 0

    async def test_a_spread_the_fee_eats_is_not_tradable(self, scan_service):
        points = history(["9.50", "9.60", "9.55", "9.62", "9.51", "9.58"])

        measured = await self.measure(scan_service, points)

        assert measured.profit_per_trade <= 0
        assert measured.tradable is False


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

        await scan_service.run("scan-1", ScanParams(limit=2, min_volume=0))

        state = await self.stored(scan_service, "scan-1")
        assert state["status"] == "done"
        assert [c["market_hash_name"] for c in state["candidates"]] == ["A", "B"]
        assert redis.store[LATEST_KEY] == "scan-1"

    async def test_progress_is_visible_while_it_runs(self, scan_service, redis):
        self.one_page(scan_service, [search_row("A"), search_row("B")])
        seen = []
        original = scan_service.steam.get_price_history

        async def watching(*args, **kwargs):
            seen.append(json.loads(redis.store[f"{SCAN_KEY}scan-2"])["measured"])
            return await original(*args, **kwargs)

        scan_service.steam.get_price_history = watching

        await scan_service.run("scan-2", ScanParams(limit=2, min_volume=0))

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

        await scan_service.run("scan-4", ScanParams(limit=2, min_volume=0))

        state = await self.stored(scan_service, "scan-4")
        assert state["status"] == "done"
        assert "RuntimeError" in state["candidates"][0]["note"]
        assert state["candidates"][1]["note"] == ""

    async def test_a_cancelled_scan_keeps_what_it_measured(self, scan_service):
        """arq cancels a job that runs past its timeout; the work already done is still worth having."""
        self.one_page(scan_service, [search_row("A"), search_row("B")])
        scan_service.steam.get_price_history.side_effect = [
            history(["8.00", "12.00", "8.20"]),
            asyncio.CancelledError(),
        ]

        with pytest.raises(asyncio.CancelledError):
            await scan_service.run("scan-7", ScanParams(limit=2, min_volume=0))

        state = await self.stored(scan_service, "scan-7")
        assert state["status"] == "failed"
        assert "measuring 1 of 2 items" in state["error"]
        assert len(state["candidates"]) == 1

    async def test_the_latest_scan_can_be_found_again(self, scan_service):
        self.one_page(scan_service, [search_row("A")])

        await scan_service.run("scan-5", ScanParams(limit=1, min_volume=0))

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
