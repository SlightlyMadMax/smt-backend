from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from smt.schemas.pool import PoolItemCreate
from smt.services.pool import PoolService


def make_candidate(market_hash_name: str) -> PoolItemCreate:
    return PoolItemCreate(
        market_hash_name=market_hash_name,
        name=market_hash_name,
        app_id="440",
        context_id="2",
        icon_url="https://cdn.example/icon.png",
    )


@pytest.fixture
def pool_repo():
    repo = AsyncMock()
    repo.add_many.side_effect = lambda items: list(items)
    return repo


@pytest.fixture
def pool_service(pool_repo):
    return PoolService(pool_repo, AsyncMock())


@pytest.mark.asyncio
class TestAddingScannedItems:
    async def test_items_we_do_not_own_still_reach_the_pool(self, pool_service, pool_repo):
        """Every other path starts from the inventory, which a scan knows nothing about."""
        added = await pool_service.add_unowned([make_candidate("Rainy Day Cosmetic Case")])

        assert [item.market_hash_name for item in added] == ["Rainy Day Cosmetic Case"]
        pool_service.inventory_service.get_by_id.assert_not_awaited()

    async def test_the_same_item_twice_is_added_once(self, pool_service, pool_repo):
        await pool_service.add_unowned([make_candidate("Secret Saxton"), make_candidate("Secret Saxton")])

        sent = pool_repo.add_many.await_args.args[0]
        assert len(sent) == 1

    async def test_an_empty_request_is_refused(self, pool_service):
        with pytest.raises(HTTPException) as refused:
            await pool_service.add_unowned([])

        assert refused.value.status_code == 400
