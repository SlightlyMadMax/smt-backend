import math
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import List

import numpy as np
from anyio import to_thread
from sqlalchemy.exc import NoResultFound
from steampy.models import GameOptions

from smt.repositories.pool_items import PoolRepo
from smt.schemas.pool import PoolItemUpdate
from smt.schemas.price_history import PriceHistoryRecordCreate
from smt.services.price_history import PriceHistoryService
from smt.services.steam import SteamService
from smt.utils.steam import calculate_fees


class StatsRefreshService:
    def __init__(
        self,
        price_history_service: PriceHistoryService,
        pool_repo: PoolRepo,
        steam_service: SteamService,
    ):
        self.price_history_service = price_history_service
        self.pool_repo = pool_repo
        self.steam = steam_service

    async def refresh_price_history(self, market_hash_names: List[str], days: int = 30) -> None:
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

    async def refresh_indicators(self, market_hash_names: List[str]) -> None:
        items = await self.pool_repo.get_many(market_hash_names)

        for item in items:
            since = datetime.now(UTC) - timedelta(days=7)
            history = await self.price_history_service.list(
                market_hash_name=item.market_hash_name,
                since=since,
            )
            prices = [float(r.price) for r in history]
            if len(prices) < 2:
                continue

            buy_pct = 20
            sell_pct = 80
            opt_buy = Decimal(np.percentile(prices, buy_pct)).quantize(Decimal("0.01"))
            opt_sell = Decimal(np.percentile(prices, sell_pct)).quantize(Decimal("0.01"))

            returns = [math.log(prices[i] / prices[i - 1]) for i in range(1, len(prices))]
            sigma = Decimal(
                (sum((r - sum(returns) / len(returns)) ** 2 for r in returns) / (len(returns) - 1)) ** 0.5
            ).quantize(Decimal("0.0001"))

            gross_kopeks = int((opt_sell * 100).to_integral_value())
            fees = calculate_fees(gross_kopeks)
            net_sell = Decimal(fees["net_received"]) / 100
            profit = net_sell - opt_buy

            is_good = profit > Decimal("0.10") and item.current_volume24h is not None and item.current_volume24h > 10

            await self.pool_repo.update(
                item.market_hash_name,
                PoolItemUpdate(
                    optimal_buy_price=opt_buy,
                    optimal_sell_price=opt_sell,
                    volatility=sigma,
                    potential_profit=profit,
                    use_for_trading=is_good,
                ),
            )
