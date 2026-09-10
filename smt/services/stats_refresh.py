from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import List, Optional

from sqlalchemy.exc import NoResultFound
from steampy.exceptions import TooManyRequests
from steampy.models import GameOptions

from smt.exceptions import OrderBookUnavailable
from smt.logger import get_logger
from smt.schemas.action_log import ActionKind, ActionLevel
from smt.schemas.pool import PoolItemUpdate
from smt.schemas.price_history import PriceHistoryRecordCreate
from smt.services.action_log import ActionLogService
from smt.services.market_analytics import ItemIndicators, MarketAnalyticsService
from smt.services.pool import PoolService
from smt.services.price_history import PriceHistoryService
from smt.services.settings import SettingsService
from smt.services.steam import SteamService


logger = get_logger("services.stats_refresh")

RECENT_STATS_LOOKBACK = timedelta(days=2)
WEEKLY_WINDOW = timedelta(days=7)


class StatsRefreshService:
    def __init__(
        self,
        price_history_service: PriceHistoryService,
        pool_service: PoolService,
        steam_service: SteamService,
        analytics_service: MarketAnalyticsService,
        settings_service: SettingsService,
        action_log: Optional[ActionLogService] = None,
    ):
        self.price_history_service = price_history_service
        self.pool_service = pool_service
        self.steam = steam_service
        self.analytics_service = analytics_service
        self.settings_service = settings_service
        self.action_log = action_log

    async def refresh_price_history(self, market_hash_names: List[str]) -> None:
        settings = await self.settings_service.get_settings()
        days = settings.price_history_days
        cutoff = datetime.now(UTC) - timedelta(days=days)
        all_records: List[PriceHistoryRecordCreate] = []
        throttled: List[str] = []

        for name in market_hash_names:
            try:
                item = await self.pool_service.get_by_market_hash_name(name)
            except NoResultFound:
                continue

            game_opt = GameOptions(item.app_id, item.context_id)
            try:
                raw_hist = await self.steam.get_price_history(market_hash_name=name, game=game_opt, days=days)
            except TooManyRequests:
                logger.warning(f"Steam is throttling price history, {name} was not refreshed.")
                throttled.append(name)
                continue

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

        if throttled and self.action_log:
            await self.action_log.record(
                ActionKind.STEAM_THROTTLED,
                f"Steam limited how often price history may be read, so {len(throttled)} item(s) "
                f"kept their previous prices. It will be tried again on the next refresh.",
                level=ActionLevel.WARNING,
                market_hash_name=throttled[0] if len(throttled) == 1 else None,
            )

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

            round_trips, median_hold = self.analytics_service.simulate_round_trips(clean, opt_buy, opt_sell)
            return_on_capital = self.analytics_service.project_return_on_capital(profit, round_trips, opt_buy, days)
            _, volume7d = await self.analytics_service.compute_recent_stats(clean, WEEKLY_WINDOW)
            profit_pct = (profit / opt_buy * 100).quantize(Decimal("0.01")) if opt_buy > 0 else None

            flag, reason = await self.analytics_service.decide_trade_flag(
                ItemIndicators(
                    profit=profit,
                    profit_pct=profit_pct,
                    volume24h=item.current_volume24h,
                    volume7d=volume7d,
                    volatility=sigma,
                    round_trips=round_trips,
                    median_hold_hours=median_hold,
                    return_on_capital_30d=return_on_capital,
                )
            )

            if flag and not self.analytics_service.history_describes_current_market(clean, item.current_lowest_price):
                flag, reason = False, "the price history is centred far from the current price"

            if not flag:
                logger.info(f"{item.market_hash_name} is not traded: {reason}.")

            await self.pool_service.update(
                item.market_hash_name,
                PoolItemUpdate(
                    optimal_buy_price=opt_buy,
                    optimal_sell_price=opt_sell,
                    volatility=sigma,
                    potential_profit=profit,
                    current_volume7d=volume7d,
                    round_trips=round_trips,
                    median_hold_hours=median_hold,
                    return_on_capital_30d=return_on_capital,
                    use_for_trading=flag,
                ),
            )

    async def refresh_all(self, market_hash_names: list[str]) -> None:
        await self.refresh_price_history(market_hash_names)

        for name in market_hash_names:
            await self.refresh_current_stats(name)

        await self.refresh_indicators(market_hash_names)
