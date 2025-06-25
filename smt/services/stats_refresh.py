from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import List

from anyio import to_thread
from sqlalchemy.exc import NoResultFound
from steampy.models import GameOptions

from smt.repositories.pool_items import PoolRepo
from smt.schemas.pool import PoolItemUpdate
from smt.schemas.price_history import PriceHistoryRecordCreate
from smt.services.market_analytics import MarketAnalyticsService
from smt.services.price_history import PriceHistoryService
from smt.services.settings import SettingsService
from smt.services.steam import SteamService


class StatsRefreshService:
    def __init__(
        self,
        price_history_service: PriceHistoryService,
        pool_repo: PoolRepo,
        steam_service: SteamService,
        analytics_service: MarketAnalyticsService,
        settings_service: SettingsService,
    ):
        self.price_history_service = price_history_service
        self.pool_repo = pool_repo
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
                item = await self.pool_repo.get_by_market_hash_name(name)
            except NoResultFound:
                continue

            game_opt = GameOptions(item.app_id, item.context_id)
            raw_hist = await to_thread.run_sync(
                self.steam.get_price_history,
                name,
                game_opt,
                days,
            )
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
            item = await self.pool_repo.get_by_market_hash_name(market_hash_name)
        except NoResultFound:
            return

        game_opt = GameOptions(item.app_id, item.context_id)
        snap = await to_thread.run_sync(
            self.steam.get_price,
            market_hash_name,
            game_opt,
        )

        await self.pool_repo.update(
            market_hash_name,
            PoolItemUpdate(
                current_lowest_price=snap["lowest_price"],
                current_median_price=snap["median_price"],
                current_volume24h=snap["volume"],
            ),
        )

    async def refresh_indicators(self, names: List[str]) -> None:
        settings = await self.settings_service.get_settings()
        days = settings.analysis_window_days
        items = await self.pool_repo.get_many(names)
        since = datetime.now(UTC) - timedelta(days=days)

        for item in items:
            records = await self.price_history_service.list(item.market_hash_name, since=since)
            records = list(records)
            if len(records) < 2:
                continue

            opt_buy, opt_sell = await self.analytics_service.compute_weighted_percentile_targets(records)
            sigma = await self.analytics_service.compute_volume_weighted_volatility(records)
            net_sell, profit = await self.analytics_service.compute_net_and_profit(opt_sell, opt_buy)
            flag = await self.analytics_service.decide_trade_flag(profit, item.current_volume24h, sigma)

            await self._persist_indicators(item.market_hash_name, opt_buy, opt_sell, sigma, profit, flag)

    async def _fetch_prices(self, name: str, since: datetime) -> list[float]:
        history = await self.price_history_service.list(market_hash_name=name, since=since)
        return [float(r.price) for r in history]

    async def _persist_indicators(
        self, name: str, opt_buy: Decimal, opt_sell: Decimal, sigma: Decimal, profit: Decimal, flag: bool
    ) -> None:
        await self.pool_repo.update(
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
