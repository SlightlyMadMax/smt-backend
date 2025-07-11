from unittest.mock import AsyncMock, Mock, patch

import pytest
import pytest_asyncio
from steampy.models import GameOptions

from smt.db.models import Item as ItemORM
from smt.repositories.items import ItemRepo
from smt.services.inventory import InventoryService
from smt.services.steam import SteamService


@pytest_asyncio.fixture
def mock_steam_service():
    return Mock(spec=SteamService)


@pytest_asyncio.fixture
def mock_item_repo():
    repo = Mock(spec=ItemRepo)
    repo.list_for_game = AsyncMock()
    repo.replace_for_game = AsyncMock()
    repo.get_by_id = AsyncMock()
    return repo


@pytest_asyncio.fixture
def inventory_service(mock_steam_service, mock_item_repo):
    return InventoryService(
        steam=mock_steam_service,
        item_repo=mock_item_repo,
    )


@pytest_asyncio.fixture
def sample_game_option():
    return GameOptions(app_id="730", context_id="2")


@pytest_asyncio.fixture
def sample_orm_items():
    return [
        ItemORM(
            id="item1",
            app_id="730",
            context_id="2",
            name="AK-47 | Redline",
            market_hash_name="AK-47 | Redline (Field-Tested)",
            tradable=True,
            marketable=True,
            icon_url="https://cdn.steam.com/item1.png",
        ),
        ItemORM(
            id="item2",
            app_id="730",
            context_id="2",
            name="AWP | Dragon Lore",
            market_hash_name="AWP | Dragon Lore (Factory New)",
            tradable=False,
            marketable=True,
            icon_url="https://cdn.steam.com/item2.png",
        ),
    ]


@pytest.mark.asyncio
class TestInventoryService:
    async def test_list_calls_item_repo_with_correct_params(
        self, inventory_service, mock_item_repo, sample_game_option, sample_orm_items
    ):
        # Arrange
        mock_item_repo.list_for_game.return_value = sample_orm_items

        # Act
        result = await inventory_service.list(sample_game_option)

        # Assert
        mock_item_repo.list_for_game.assert_called_once_with("730", "2")
        assert result == sample_orm_items

    async def test_list_returns_empty_list_when_no_items(self, inventory_service, mock_item_repo, sample_game_option):
        # Arrange
        mock_item_repo.list_for_game.return_value = []

        # Act
        result = await inventory_service.list(sample_game_option)

        # Assert
        mock_item_repo.list_for_game.assert_called_once_with("730", "2")
        assert result == []

    async def test_get_by_id_returns_item_from_repo(self, inventory_service, mock_item_repo, sample_orm_items):
        # Arrange
        expected_item = sample_orm_items[0]
        mock_item_repo.get_by_id.return_value = expected_item

        # Act
        result = await inventory_service.get_by_id("item1")

        # Assert
        mock_item_repo.get_by_id.assert_called_once_with("item1")
        assert result == expected_item

    async def test_get_by_id_propagates_repo_exception(self, inventory_service, mock_item_repo):
        # Arrange
        mock_item_repo.get_by_id.side_effect = Exception("Item not found")

        # Act & Assert
        with pytest.raises(Exception, match="Item not found"):
            await inventory_service.get_by_id("nonexistent_item")

    @patch("smt.services.inventory.transform_inventory_item")
    async def test_refresh_processes_inventory_successfully(
        self, mock_transform, inventory_service, mock_steam_service, mock_item_repo, sample_game_option
    ):
        # Arrange
        raw_inventory = {
            "item1": {"some": "raw_data_1"},
            "item2": {"some": "raw_data_2"},
        }
        mock_steam_service.get_inventory.return_value = raw_inventory

        mock_transform.side_effect = [
            {
                "id": "item1",
                "name": "AK-47 | Redline",
                "market_hash_name": "AK-47 | Redline (Field-Tested)",
                "tradable": True,
                "marketable": True,
                "icon_url": "https://cdn.steam.com/item1.png",
            },
            {
                "id": "item2",
                "name": "AWP | Dragon Lore",
                "market_hash_name": "AWP | Dragon Lore (Factory New)",
                "tradable": False,
                "marketable": True,
                "icon_url": "https://cdn.steam.com/item2.png",
            },
        ]

        # Act
        await inventory_service.refresh(sample_game_option)

        # Assert
        mock_steam_service.get_inventory.assert_called_once_with(game=sample_game_option)
        assert mock_transform.call_count == 2
        mock_transform.assert_any_call({"some": "raw_data_1"})
        mock_transform.assert_any_call({"some": "raw_data_2"})

        # Verify replace_for_game was called with correct parameters
        mock_item_repo.replace_for_game.assert_called_once()
        call_args = mock_item_repo.replace_for_game.call_args
        assert call_args.kwargs["app_id"] == "730"
        assert call_args.kwargs["context_id"] == "2"

        # Verify the ORM items were created correctly
        orm_items = call_args.kwargs["items"]
        assert len(orm_items) == 2

        # Check first item
        assert orm_items[0].id == "item1"
        assert orm_items[0].app_id == "730"
        assert orm_items[0].context_id == "2"
        assert orm_items[0].name == "AK-47 | Redline"
        assert orm_items[0].market_hash_name == "AK-47 | Redline (Field-Tested)"
        assert orm_items[0].tradable is True
        assert orm_items[0].marketable is True
        assert orm_items[0].icon_url == "https://cdn.steam.com/item1.png"

        # Check second item
        assert orm_items[1].id == "item2"
        assert orm_items[1].app_id == "730"
        assert orm_items[1].context_id == "2"
        assert orm_items[1].name == "AWP | Dragon Lore"
        assert orm_items[1].market_hash_name == "AWP | Dragon Lore (Factory New)"
        assert orm_items[1].tradable is False
        assert orm_items[1].marketable is True
        assert orm_items[1].icon_url == "https://cdn.steam.com/item2.png"

    @patch("smt.services.inventory.transform_inventory_item")
    async def test_refresh_handles_empty_inventory(
        self, mock_transform, inventory_service, mock_steam_service, mock_item_repo, sample_game_option
    ):
        # Arrange
        mock_steam_service.get_inventory.return_value = {}

        # Act
        await inventory_service.refresh(sample_game_option)

        # Assert
        mock_steam_service.get_inventory.assert_called_once_with(game=sample_game_option)
        mock_transform.assert_not_called()
        mock_item_repo.replace_for_game.assert_called_once_with(app_id="730", context_id="2", items=[])

    @patch("smt.services.inventory.transform_inventory_item")
    async def test_refresh_handles_single_item(
        self, mock_transform, inventory_service, mock_steam_service, mock_item_repo, sample_game_option
    ):
        # Arrange
        raw_inventory = {"item1": {"some": "raw_data"}}
        mock_steam_service.get_inventory.return_value = raw_inventory

        mock_transform.return_value = {
            "id": "item1",
            "name": "Test Item",
            "market_hash_name": "Test Item Name",
            "tradable": True,
            "marketable": False,
            "icon_url": "https://cdn.steam.com/test.png",
        }

        # Act
        await inventory_service.refresh(sample_game_option)

        # Assert
        mock_transform.assert_called_once_with({"some": "raw_data"})

        call_args = mock_item_repo.replace_for_game.call_args
        orm_items = call_args.kwargs["items"]
        assert len(orm_items) == 1
        assert orm_items[0].id == "item1"
        assert orm_items[0].marketable is False

    @patch("smt.services.inventory.transform_inventory_item")
    async def test_refresh_preserves_game_option_data(
        self, mock_transform, inventory_service, mock_steam_service, mock_item_repo
    ):
        # Arrange
        custom_game_option = GameOptions(app_id="440", context_id="3")
        raw_inventory = {"item1": {"data": "test"}}
        mock_steam_service.get_inventory.return_value = raw_inventory

        mock_transform.return_value = {
            "id": "item1",
            "name": "TF2 Item",
            "market_hash_name": "TF2 Item Hash",
            "tradable": True,
            "marketable": True,
            "icon_url": "https://cdn.steam.com/tf2.png",
        }

        # Act
        await inventory_service.refresh(custom_game_option)

        # Assert
        call_args = mock_item_repo.replace_for_game.call_args
        assert call_args.kwargs["app_id"] == "440"
        assert call_args.kwargs["context_id"] == "3"

        orm_items = call_args.kwargs["items"]
        assert orm_items[0].app_id == "440"
        assert orm_items[0].context_id == "3"

    async def test_refresh_propagates_steam_service_exception(
        self, inventory_service, mock_steam_service, sample_game_option
    ):
        # Arrange
        mock_steam_service.get_inventory.side_effect = Exception("Steam API Error")

        # Act & Assert
        with pytest.raises(Exception, match="Steam API Error"):
            await inventory_service.refresh(sample_game_option)

    @patch("smt.services.inventory.transform_inventory_item")
    async def test_refresh_propagates_transform_exception(
        self, mock_transform, inventory_service, mock_steam_service, mock_item_repo, sample_game_option
    ):
        # Arrange
        raw_inventory = {"item1": {"data": "test"}}
        mock_steam_service.get_inventory.return_value = raw_inventory
        mock_transform.side_effect = ValueError("Transform error")

        # Act & Assert
        with pytest.raises(ValueError, match="Transform error"):
            await inventory_service.refresh(sample_game_option)

    @patch("smt.services.inventory.transform_inventory_item")
    async def test_refresh_propagates_repo_exception(
        self, mock_transform, inventory_service, mock_steam_service, mock_item_repo, sample_game_option
    ):
        # Arrange
        raw_inventory = {"item1": {"data": "test"}}
        mock_steam_service.get_inventory.return_value = raw_inventory
        mock_transform.return_value = {
            "id": "item1",
            "name": "Test",
            "market_hash_name": "Test",
            "tradable": True,
            "marketable": True,
            "icon_url": "https://test.com/icon.png",
        }
        mock_item_repo.replace_for_game.side_effect = Exception("Database error")

        # Act & Assert
        with pytest.raises(Exception, match="Database error"):
            await inventory_service.refresh(sample_game_option)

    async def test_snapshot_counts_returns_correct_counts(
        self, inventory_service, mock_steam_service, sample_game_option
    ):
        # Arrange
        raw_inventory = {
            "item1": {"market_hash_name": "AK-47 | Redline (Field-Tested)"},
            "item2": {"market_hash_name": "AWP | Dragon Lore (Factory New)"},
            "item3": {"market_hash_name": "AK-47 | Redline (Field-Tested)"},
            "item4": {"market_hash_name": "AK-47 | Redline (Field-Tested)"},
        }
        mock_steam_service.get_inventory.return_value = raw_inventory

        # Act
        result = await inventory_service.snapshot_counts(sample_game_option)

        # Assert
        mock_steam_service.get_inventory.assert_called_once_with(game=sample_game_option)
        assert result == {
            "AK-47 | Redline (Field-Tested)": 3,
            "AWP | Dragon Lore (Factory New)": 1,
        }

    @patch("smt.services.inventory.transform_inventory_item")
    async def test_snapshot_items_groups_by_market_hash_name(
        self, mock_transform, inventory_service, mock_steam_service, sample_game_option
    ):
        # Arrange
        raw_inventory = {
            "item1": {"data": "ak47_1"},
            "item2": {"data": "awp_1"},
            "item3": {"data": "ak47_2"},
            "item4": {"data": "ak47_3"},
        }
        mock_steam_service.get_inventory.return_value = raw_inventory

        # Mock transform to return different items with some duplicate market hash names
        mock_transform.side_effect = [
            {
                "id": "item1",
                "name": "AK-47 | Redline",
                "market_hash_name": "AK-47 | Redline (Field-Tested)",
                "tradable": True,
                "marketable": True,
                "icon_url": "https://cdn.steam.com/item1.png",
            },
            {
                "id": "item2",
                "name": "AWP | Dragon Lore",
                "market_hash_name": "AWP | Dragon Lore (Factory New)",
                "tradable": False,
                "marketable": True,
                "icon_url": "https://cdn.steam.com/item2.png",
            },
            {
                "id": "item3",
                "name": "AK-47 | Redline",
                "market_hash_name": "AK-47 | Redline (Field-Tested)",
                "tradable": True,
                "marketable": True,
                "icon_url": "https://cdn.steam.com/item3.png",
            },
            {
                "id": "item4",
                "name": "AK-47 | Redline",
                "market_hash_name": "AK-47 | Redline (Field-Tested)",
                "tradable": False,
                "marketable": False,
                "icon_url": "https://cdn.steam.com/item4.png",
            },
        ]

        # Act
        result = await inventory_service.snapshot_items(sample_game_option)

        # Assert
        mock_steam_service.get_inventory.assert_called_once_with(game=sample_game_option)
        assert mock_transform.call_count == 4

        # Verify grouping
        assert len(result) == 2
        assert "AK-47 | Redline (Field-Tested)" in result
        assert "AWP | Dragon Lore (Factory New)" in result

        # Check AK-47 group (should have 3 items)
        ak47_items = result["AK-47 | Redline (Field-Tested)"]
        assert len(ak47_items) == 3
        assert ak47_items[0].id == "item1"
        assert ak47_items[1].id == "item3"
        assert ak47_items[2].id == "item4"
        assert all(item.market_hash_name == "AK-47 | Redline (Field-Tested)" for item in ak47_items)

        # Check AWP group (should have 1 item)
        awp_items = result["AWP | Dragon Lore (Factory New)"]
        assert len(awp_items) == 1
        assert awp_items[0].id == "item2"
        assert awp_items[0].market_hash_name == "AWP | Dragon Lore (Factory New)"

        # Verify all items have correct game option data
        for items_list in result.values():
            for item in items_list:
                assert item.app_id == "730"
                assert item.context_id == "2"

    @patch("smt.services.inventory.transform_inventory_item")
    async def test_snapshot_items_handles_empty_inventory(
        self, mock_transform, inventory_service, mock_steam_service, sample_game_option
    ):
        # Arrange
        mock_steam_service.get_inventory.return_value = {}

        # Act
        result = await inventory_service.snapshot_items(sample_game_option)

        # Assert
        mock_steam_service.get_inventory.assert_called_once_with(game=sample_game_option)
        mock_transform.assert_not_called()
        assert result == {}

    @patch("smt.services.inventory.transform_inventory_item")
    async def test_snapshot_items_handles_single_item(
        self, mock_transform, inventory_service, mock_steam_service, sample_game_option
    ):
        # Arrange
        raw_inventory = {"item1": {"data": "single_item"}}
        mock_steam_service.get_inventory.return_value = raw_inventory

        mock_transform.return_value = {
            "id": "item1",
            "name": "Single Item",
            "market_hash_name": "Single Item Hash",
            "tradable": True,
            "marketable": False,
            "icon_url": "https://cdn.steam.com/single.png",
        }

        # Act
        result = await inventory_service.snapshot_items(sample_game_option)

        # Assert
        mock_transform.assert_called_once_with({"data": "single_item"})
        assert len(result) == 1
        assert "Single Item Hash" in result
        assert len(result["Single Item Hash"]) == 1
        assert result["Single Item Hash"][0].id == "item1"
