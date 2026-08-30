from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import List

from sqlalchemy.exc import NoResultFound
from steampy.models import GameOptions

from smt.exceptions import OrderBookUnavailable
from smt.logger import get_logger
from smt.schemas.pool import PoolItemUpdate
from smt.schemas.price_history import PriceHistoryRecordCreate
from smt.services.market_analytics import MarketAnalyticsService
from smt.services.pool import PoolService
from smt.services.price_history import PriceHistoryService
from smt.services.settings import SettingsService
from smt.services.steam import SteamService


logger = get_logger("services.stats_refresh")

RECENT_STATS_LOOKBACK = timedelta(days=2)


class StatsRefreshService:
    def __init__(
        self,
        price_history_service: PriceHistoryService,
        pool_service: PoolService,
        steam_service: SteamService,
        analytics_service: MarketAnalyticsService,
        settings_service: SettingsService,
    ):
        self.price_history_service = price_history_service
        self.pool_service = pool_service
        self.steam = steam_service
        self.analytics_service = analytics_service
        self.settings_service = settings_service

    async def refresh_price_history(self, market_hash_names: List[str]) -> None:
        settings = await self.settings_service.get_settings()
        days = settings.price_history_days
        cutoff = datetime.now(UTC) - timedelta(days=days)
        all_records: List[PriceHistoryRecordCreate] = []

        for name in market_hash_names:
            try:
                item = await self.pool_service.get_by_market_hash_name(name)
            except NoResultFound:
                continue

            game_opt = GameOptions(item.app_id, item.context_id)
            raw_hist = await self.steam.get_price_history(market_hash_name=name, game=game_opt, days=days)
            for ts, price, vol in raw_hist:
                all_records.append(
                    PriceHistoryRecordCreate(
                        market_hash_name=name,
                        recorded_at=ts,
                        price=price,
                        volume=vol,
                    )
                )

        if all_records:
            await self.price_history_service.add_many(all_records)

        for name in market_hash_names:
            await self.price_history_service.delete_before(name, cutoff)

    async def refresh_current_stats(self, market_hash_name: str) -> None:
        try:
            item = await self.pool_service.get_by_market_hash_name(market_hash_name)
        except NoResultFound:
            return

        since = datetime.now(UTC) - RECENT_STATS_LOOKBACK
        records = list(await self.price_history_service.list(market_hash_name, since=since))
        median, volume = await self.analytics_service.compute_recent_stats(records)

        values: dict = {"current_median_price": median, "current_volume24h": volume}

        try:
            book = await self.steam.get_order_book(market_hash_name=market_hash_name, app_id=item.app_id)
            values["current_lowest_price"] = book["lowest_sell_order"]
            values["current_highest_buy_order"] = book["highest_buy_order"]
        except OrderBookUnavailable as e:
            logger.warning(f"Could not fetch the order book for {market_hash_name}: {e}")

        await self.pool_service.update(market_hash_name, PoolItemUpdate(**values))

    async def refresh_indicators(self, names: List[str]) -> None:
        settings = await self.settings_service.get_settings()
        days = settings.analysis_window_days
        items = await self.pool_service.get_many(names)
        since = datetime.now(UTC) - timedelta(days=days)

        for item in items:
            records = list(await self.price_history_service.list(item.market_hash_name, since=since))
            clean = self.analytics_service.filter_price_outliers(records)
            dropped = len(records) - len(clean)
            if dropped:
                logger.info(f"Ignoring {dropped} outlier price records for {item.market_hash_name}.")
            if len(clean) < 2:
                continue

            opt_buy, opt_sell = await self.analytics_service.compute_weighted_percentile_targets(clean)
            sigma = await self.analytics_service.compute_volume_weighted_volatility(clean)
            net_sell, profit = await self.analytics_service.compute_net_and_profit(opt_sell, opt_buy)
            flag = await self.analytics_service.decide_trade_flag(profit, item.current_volume24h, sigma)

            if flag and not self.analytics_service.history_describes_current_market(clean, item.current_lowest_price):
                logger.warning(
                    f"{item.market_hash_name}: the price history is centred far from the current price, "
                    f"so its targets are not usable. Not trading it."
                )
                flag = False

            await self._persist_indicators(item.market_hash_name, opt_buy, opt_sell, sigma, profit, flag)

    async def _persist_indicators(
        self, name: str, opt_buy: Decimal, opt_sell: Decimal, sigma: Decimal, profit: Decimal, flag: bool
    ) -> None:
        await self.pool_service.update(
            name,
            PoolItemUpdate(
                optimal_buy_price=opt_buy,
                optimal_sell_price=opt_sell,
                volatility=sigma,
                potential_profit=profit,
                use_for_trading=flag,
            ),
        )

    async def refresh_all(self, market_hash_names: list[str]) -> None:
        await self.refresh_price_history(market_hash_names)

        for name in market_hash_names:
            await self.refresh_current_stats(name)

        await self.refresh_indicators(market_hash_names)
