from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, Mock

import pytest
import pytest_asyncio

from smt.db.models import Position, PositionStatus
from smt.repositories.position import PositionRepo
from smt.schemas.position import PositionCreate, PositionUpdate
from smt.services.position import PositionService


@pytest_asyncio.fixture
def mock_repo():
    return AsyncMock(spec=PositionRepo)


@pytest_asyncio.fixture
def position_service(mock_repo):
    return PositionService(mock_repo)


@pytest.mark.asyncio
class TestPositionService:
    async def test_add_position(self, position_service, mock_repo):
        # Arrange
        position_data = PositionCreate(
            pool_item_hash="ak47_redline",
            buy_order_id="order_123",
            buy_price=25.50,
            quantity=1,
        )
        expected_position = Position(
            id=1,
            pool_item_hash="ak47_redline",
            buy_order_id="order_123",
            buy_price=Decimal("25.50"),
            quantity=1,
            status=PositionStatus.OPEN,
        )
        mock_repo.add.return_value = expected_position

        # Act
        result = await position_service.add(position_data)

        # Assert
        mock_repo.add.assert_called_once_with(position_data)
        assert result == expected_position

    async def test_list_open(self, position_service, mock_repo):
        # Arrange
        expected_positions = [
            Position(id=1, status=PositionStatus.OPEN),
            Position(id=2, status=PositionStatus.OPEN),
        ]
        mock_repo.list_open.return_value = expected_positions

        # Act
        result = await position_service.list_open()

        # Assert
        mock_repo.list_open.assert_called_once()
        assert result == expected_positions

    async def test_list_listed(self, position_service, mock_repo):
        # Arrange
        expected_positions = [
            Position(id=3, status=PositionStatus.LISTED),
        ]
        mock_repo.list_listed.return_value = expected_positions

        # Act
        result = await position_service.list_listed()

        # Assert
        mock_repo.list_listed.assert_called_once()
        assert result == expected_positions

    async def test_list_closed(self, position_service, mock_repo):
        # Arrange
        expected_positions = [
            Position(id=4, status=PositionStatus.CLOSED),
            Position(id=5, status=PositionStatus.CLOSED),
        ]
        mock_repo.list_closed.return_value = expected_positions

        # Act
        result = await position_service.list_closed()

        # Assert
        mock_repo.list_closed.assert_called_once()
        assert result == expected_positions

    async def test_mark_as_listed(self, position_service, mock_repo):
        # Arrange
        position_id = 1
        sell_order_id = "sell_123"
        sell_price = 30.00

        expected_position = Position(
            id=position_id,
            sell_order_id=sell_order_id,
            sell_price=Decimal("30.00"),
            status=PositionStatus.LISTED,
        )
        mock_repo.update.return_value = expected_position

        # Act
        result = await position_service.mark_as_listed(position_id, sell_order_id, sell_price)

        # Assert
        mock_repo.update.assert_called_once()
        call_args = mock_repo.update.call_args
        assert call_args[0][0] == position_id  # First positional arg

        update_data = call_args[0][1]  # Second positional arg
        assert update_data.sell_order_id == sell_order_id
        assert update_data.sell_price == sell_price
        assert update_data.status == PositionStatus.LISTED

        assert result == expected_position

    async def test_close_with_provided_timestamp(self, position_service, mock_repo):
        # Arrange
        position_id = 1
        sold_at = datetime(2025, 6, 28, 12, 0, 0, tzinfo=timezone.utc)

        expected_position = Position(
            id=position_id,
            status=PositionStatus.CLOSED,
            sold_at=sold_at,
        )
        mock_repo.update.return_value = expected_position

        # Act
        result = await position_service.close(position_id, sold_at)

        # Assert
        mock_repo.update.assert_called_once()
        call_args = mock_repo.update.call_args
        assert call_args[0][0] == position_id

        update_data = call_args[0][1]
        assert update_data.status == PositionStatus.CLOSED
        assert update_data.sold_at == sold_at

        assert result == expected_position

    async def test_close_with_default_timestamp(self, position_service, mock_repo):
        # Arrange
        position_id = 1
        expected_position = Position(
            id=position_id,
            status=PositionStatus.CLOSED,
        )
        mock_repo.update.return_value = expected_position

        # Act
        result = await position_service.close(position_id)

        # Assert
        mock_repo.update.assert_called_once()
        call_args = mock_repo.update.call_args
        assert call_args[0][0] == position_id

        update_data = call_args[0][1]
        assert update_data.status == PositionStatus.CLOSED
        # Verify sold_at is recent (within last few seconds)
        assert isinstance(update_data.sold_at, datetime)
        time_diff = abs((datetime.now(timezone.utc) - update_data.sold_at).total_seconds())
        assert time_diff < 2  # Should be within 2 seconds

        assert result == expected_position

    async def test_get_position(self, position_service, mock_repo):
        # Arrange
        position_id = 1
        expected_position = Position(
            id=position_id,
            pool_item_hash="ak47_redline",
            status=PositionStatus.OPEN,
        )
        mock_repo.get_by_id.return_value = expected_position

        # Act
        result = await position_service.get(position_id)

        # Assert
        mock_repo.get_by_id.assert_called_once_with(position_id)
        assert result == expected_position

    async def test_delete_position(self, position_service, mock_repo):
        # Arrange
        position_id = 1
        mock_repo.delete.return_value = None

        # Act
        result = await position_service.delete(position_id)

        # Assert
        mock_repo.delete.assert_called_once_with(position_id)
        assert result is None

    async def test_mark_as_listed_creates_correct_update_data(self, position_service, mock_repo):
        # Arrange
        position_id = 42
        sell_order_id = "custom_sell_order"
        sell_price = 99.99
        mock_repo.update.return_value = Mock()

        # Act
        await position_service.mark_as_listed(position_id, sell_order_id, sell_price)

        # Assert - verify the exact PositionUpdate object structure
        mock_repo.update.assert_called_once()
        call_args = mock_repo.update.call_args[0]
        update_data = call_args[1]

        assert isinstance(update_data, PositionUpdate)
        assert update_data.sell_order_id == sell_order_id
        assert update_data.sell_price == sell_price
        assert update_data.status == PositionStatus.LISTED

    async def test_close_creates_correct_update_data(self, position_service, mock_repo):
        # Arrange
        position_id = 42
        custom_sold_at = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        mock_repo.update.return_value = Mock()

        # Act
        await position_service.close(position_id, custom_sold_at)

        # Assert - verify the exact PositionUpdate object structure
        mock_repo.update.assert_called_once()
        call_args = mock_repo.update.call_args[0]
        update_data = call_args[1]

        assert isinstance(update_data, PositionUpdate)
        assert update_data.status == PositionStatus.CLOSED
        assert update_data.sold_at == custom_sold_at
