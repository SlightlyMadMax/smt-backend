from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, Mock

import pytest
import pytest_asyncio

from smt.db.models import PriceHistoryRecord as PriceHistoryRecordORM
from smt.repositories.price_history import PriceHistoryRepo
from smt.schemas.price_history import PriceHistoryRecordCreate
from smt.services.price_history import PriceHistoryService


@pytest_asyncio.fixture
def mock_price_history_repo():
    repo = Mock(spec=PriceHistoryRepo)
    repo.list_records = AsyncMock()
    repo.add_record = AsyncMock()
    repo.add_records = AsyncMock()
    return repo


@pytest_asyncio.fixture
def price_history_service(mock_price_history_repo):
    return PriceHistoryService(price_history_repo=mock_price_history_repo)


@pytest_asyncio.fixture
def sample_datetime():
    return datetime(2025, 1, 15, 10, 30, 0, tzinfo=timezone.utc)


@pytest_asyncio.fixture
def sample_price_record_create():
    return PriceHistoryRecordCreate(
        market_hash_name="AK-47 | Redline (Field-Tested)",
        recorded_at=datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc),
        price=Decimal("25.50"),
        volume=150,
    )


@pytest_asyncio.fixture
def sample_price_record_orm():
    return PriceHistoryRecordORM(
        id=1,
        market_hash_name="AK-47 | Redline (Field-Tested)",
        recorded_at=datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc),
        price=Decimal("25.50"),
        volume=150,
    )


@pytest_asyncio.fixture
def sample_price_records_create():
    return [
        PriceHistoryRecordCreate(
            market_hash_name="AK-47 | Redline (Field-Tested)",
            recorded_at=datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc),
            price=Decimal("25.50"),
            volume=150,
        ),
        PriceHistoryRecordCreate(
            market_hash_name="AWP | Dragon Lore (Factory New)",
            recorded_at=datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc),
            price=Decimal("8500.00"),
            volume=5,
        ),
        PriceHistoryRecordCreate(
            market_hash_name="AK-47 | Redline (Field-Tested)",
            recorded_at=datetime(2025, 1, 15, 13, 0, 0, tzinfo=timezone.utc),
            price=Decimal("26.00"),
            volume=120,
        ),
    ]


@pytest_asyncio.fixture
def sample_price_records_orm():
    return [
        PriceHistoryRecordORM(
            id=1,
            market_hash_name="AK-47 | Redline (Field-Tested)",
            recorded_at=datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc),
            price=Decimal("25.50"),
            volume=150,
        ),
        PriceHistoryRecordORM(
            id=2,
            market_hash_name="AWP | Dragon Lore (Factory New)",
            recorded_at=datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc),
            price=Decimal("8500.00"),
            volume=5,
        ),
        PriceHistoryRecordORM(
            id=3,
            market_hash_name="AK-47 | Redline (Field-Tested)",
            recorded_at=datetime(2025, 1, 15, 13, 0, 0, tzinfo=timezone.utc),
            price=Decimal("26.00"),
            volume=120,
        ),
    ]


@pytest.mark.asyncio
class TestPriceHistoryService:

    async def test_list_calls_repo_with_correct_params(
        self, price_history_service, mock_price_history_repo, sample_datetime, sample_price_records_orm
    ):
        # Arrange
        market_hash_name = "AK-47 | Redline (Field-Tested)"
        # Filter records to only include matching market_hash_name AND recorded_at >= since
        filtered_records = [
            r
            for r in sample_price_records_orm
            if r.market_hash_name == market_hash_name and r.recorded_at >= sample_datetime
        ]
        mock_price_history_repo.list_records.return_value = filtered_records

        # Act
        result = await price_history_service.list(market_hash_name, sample_datetime)

        # Assert
        mock_price_history_repo.list_records.assert_called_once_with(market_hash_name, sample_datetime)
        assert result == filtered_records
        # Verify all returned records match both filters
        for record in result:
            assert record.market_hash_name == market_hash_name
            assert record.recorded_at >= sample_datetime

    async def test_list_returns_empty_sequence_when_no_records(
        self, price_history_service, mock_price_history_repo, sample_datetime
    ):
        # Arrange
        market_hash_name = "Nonexistent Item"
        mock_price_history_repo.list_records.return_value = []

        # Act
        result = await price_history_service.list(market_hash_name, sample_datetime)

        # Assert
        mock_price_history_repo.list_records.assert_called_once_with(market_hash_name, sample_datetime)
        assert result == []

    async def test_list_handles_different_market_hash_names(
        self, price_history_service, mock_price_history_repo, sample_datetime, sample_price_records_orm
    ):
        # Arrange
        market_hash_name = "AWP | Dragon Lore (Factory New)"
        filtered_records = [r for r in sample_price_records_orm if r.market_hash_name == market_hash_name]
        mock_price_history_repo.list_records.return_value = filtered_records

        # Act
        result = await price_history_service.list(market_hash_name, sample_datetime)

        # Assert
        mock_price_history_repo.list_records.assert_called_once_with(market_hash_name, sample_datetime)
        assert len(result) == 1
        assert result[0].market_hash_name == market_hash_name

    async def test_list_handles_different_datetime_filters(
        self, price_history_service, mock_price_history_repo, sample_price_records_orm
    ):
        # Arrange
        market_hash_name = "AK-47 | Redline (Field-Tested)"
        # Use a datetime that should filter out the first record (12:00) but include the second (13:00)
        filter_datetime = datetime(2025, 1, 15, 12, 30, 0, tzinfo=timezone.utc)

        # Expected: only the 13:00 record should remain after filtering
        expected_filtered = [
            r
            for r in sample_price_records_orm
            if r.market_hash_name == market_hash_name and r.recorded_at >= filter_datetime
        ]
        mock_price_history_repo.list_records.return_value = expected_filtered

        # Act
        result = await price_history_service.list(market_hash_name, filter_datetime)

        # Assert
        mock_price_history_repo.list_records.assert_called_once_with(market_hash_name, filter_datetime)
        assert len(result) == 1  # Should only return the 13:00 record
        assert all(r.recorded_at >= filter_datetime for r in result)
        assert all(r.market_hash_name == market_hash_name for r in result)

    async def test_add_one_calls_repo_with_correct_params(
        self, price_history_service, mock_price_history_repo, sample_price_record_create, sample_price_record_orm
    ):
        # Arrange
        mock_price_history_repo.add_record.return_value = sample_price_record_orm

        # Act
        result = await price_history_service.add_one(sample_price_record_create)

        # Assert
        mock_price_history_repo.add_record.assert_called_once_with(sample_price_record_create)
        assert result == sample_price_record_orm

    async def test_add_one_handles_none_return_from_repo(
        self, price_history_service, mock_price_history_repo, sample_price_record_create
    ):
        # Arrange - repo returns None when there's a constraint violation
        mock_price_history_repo.add_record.return_value = None

        # Act
        result = await price_history_service.add_one(sample_price_record_create)

        # Assert
        mock_price_history_repo.add_record.assert_called_once_with(sample_price_record_create)
        assert result is None

    async def test_add_one_with_different_price_values(self, price_history_service, mock_price_history_repo):
        # Arrange
        price_record = PriceHistoryRecordCreate(
            market_hash_name="Test Item",
            recorded_at=datetime.now(timezone.utc),
            price=Decimal("0.03"),  # Very low price
            volume=1000,
        )
        expected_orm = PriceHistoryRecordORM(
            id=1,
            market_hash_name="Test Item",
            recorded_at=price_record.recorded_at,
            price=price_record.price,
            volume=price_record.volume,
        )
        mock_price_history_repo.add_record.return_value = expected_orm

        # Act
        result = await price_history_service.add_one(price_record)

        # Assert
        mock_price_history_repo.add_record.assert_called_once_with(price_record)
        assert result.price == Decimal("0.03")
        assert result.volume == 1000

    async def test_add_many_calls_repo_with_correct_params(
        self, price_history_service, mock_price_history_repo, sample_price_records_create, sample_price_records_orm
    ):
        # Arrange
        mock_price_history_repo.add_records.return_value = sample_price_records_orm

        # Act
        result = await price_history_service.add_many(sample_price_records_create)

        # Assert
        mock_price_history_repo.add_records.assert_called_once_with(sample_price_records_create)
        assert result == sample_price_records_orm

    async def test_add_many_handles_empty_list(self, price_history_service, mock_price_history_repo):
        # Arrange
        empty_list = []
        mock_price_history_repo.add_records.return_value = []

        # Act
        result = await price_history_service.add_many(empty_list)

        # Assert
        mock_price_history_repo.add_records.assert_called_once_with(empty_list)
        assert result == []

    async def test_add_many_handles_single_record(
        self, price_history_service, mock_price_history_repo, sample_price_record_create
    ):
        # Arrange
        single_record_list = [sample_price_record_create]
        expected_orm_list = [
            PriceHistoryRecordORM(
                id=1,
                market_hash_name=sample_price_record_create.market_hash_name,
                recorded_at=sample_price_record_create.recorded_at,
                price=sample_price_record_create.price,
                volume=sample_price_record_create.volume,
            )
        ]
        mock_price_history_repo.add_records.return_value = expected_orm_list

        # Act
        result = await price_history_service.add_many(single_record_list)

        # Assert
        mock_price_history_repo.add_records.assert_called_once_with(single_record_list)
        assert len(result) == 1
        assert result[0].market_hash_name == sample_price_record_create.market_hash_name

    async def test_add_many_handles_partial_success(
        self, price_history_service, mock_price_history_repo, sample_price_records_create
    ):
        # Arrange - only some records are successfully added (duplicates filtered out)
        partial_success_orm = [sample_price_records_create[0]]  # Only first record added
        mock_price_history_repo.add_records.return_value = partial_success_orm

        # Act
        result = await price_history_service.add_many(sample_price_records_create)

        # Assert
        mock_price_history_repo.add_records.assert_called_once_with(sample_price_records_create)
        assert len(result) == 1

    async def test_add_many_preserves_order_and_data(self, price_history_service, mock_price_history_repo):
        # Arrange
        records = [
            PriceHistoryRecordCreate(
                market_hash_name="Item A",
                recorded_at=datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc),
                price=Decimal("10.00"),
                volume=100,
            ),
            PriceHistoryRecordCreate(
                market_hash_name="Item B",
                recorded_at=datetime(2025, 1, 15, 11, 0, 0, tzinfo=timezone.utc),
                price=Decimal("20.00"),
                volume=200,
            ),
        ]
        expected_orm = [
            PriceHistoryRecordORM(id=1, **records[0].model_dump()),
            PriceHistoryRecordORM(id=2, **records[1].model_dump()),
        ]
        mock_price_history_repo.add_records.return_value = expected_orm

        # Act
        result = await price_history_service.add_many(records)

        # Assert
        assert len(result) == 2
        assert result[0].market_hash_name == "Item A"
        assert result[0].price == Decimal("10.00")
        assert result[1].market_hash_name == "Item B"
        assert result[1].price == Decimal("20.00")

    # Error handling tests
    async def test_list_propagates_repo_exception(
        self, price_history_service, mock_price_history_repo, sample_datetime
    ):
        # Arrange
        mock_price_history_repo.list_records.side_effect = Exception("Database error")

        # Act & Assert
        with pytest.raises(Exception, match="Database error"):
            await price_history_service.list("test", sample_datetime)

    async def test_add_one_propagates_repo_exception(
        self, price_history_service, mock_price_history_repo, sample_price_record_create
    ):
        # Arrange
        mock_price_history_repo.add_record.side_effect = Exception("Database error")

        # Act & Assert
        with pytest.raises(Exception, match="Database error"):
            await price_history_service.add_one(sample_price_record_create)

    async def test_add_many_propagates_repo_exception(
        self, price_history_service, mock_price_history_repo, sample_price_records_create
    ):
        # Arrange
        mock_price_history_repo.add_records.side_effect = Exception("Database error")

        # Act & Assert
        with pytest.raises(Exception, match="Database error"):
            await price_history_service.add_many(sample_price_records_create)

    # Edge cases with special characters and unicode
    async def test_list_handles_special_characters_in_market_hash_name(
        self, price_history_service, mock_price_history_repo, sample_datetime
    ):
        # Arrange
        special_name = "AK-47 | 红线 (Field-Tested) ★"  # Unicode characters
        mock_price_history_repo.list_records.return_value = []

        # Act
        result = await price_history_service.list(special_name, sample_datetime)

        # Assert
        mock_price_history_repo.list_records.assert_called_once_with(special_name, sample_datetime)
        assert result == []

    async def test_add_one_handles_special_characters_in_market_hash_name(
        self, price_history_service, mock_price_history_repo
    ):
        # Arrange
        special_record = PriceHistoryRecordCreate(
            market_hash_name="Karambit | 多普勒 (Factory New) ★",  # Unicode
            recorded_at=datetime.now(timezone.utc),
            price=Decimal("1500.00"),
            volume=3,
        )
        expected_orm = PriceHistoryRecordORM(id=1, **special_record.model_dump())
        mock_price_history_repo.add_record.return_value = expected_orm

        # Act
        result = await price_history_service.add_one(special_record)

        # Assert
        mock_price_history_repo.add_record.assert_called_once_with(special_record)
        assert result.market_hash_name == "Karambit | 多普勒 (Factory New) ★"
