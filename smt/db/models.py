from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from smt.db.database import Base, TimeStampedModel


class Item(Base):
    __tablename__ = "items"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    app_id: Mapped[str] = mapped_column(String(32), nullable=False)
    context_id: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    market_hash_name: Mapped[str] = mapped_column(String(255), nullable=False)
    tradable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    marketable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    icon_url: Mapped[str] = mapped_column(String(512), nullable=False)

    def __repr__(self):
        return f"<Item {self.name} ({self.id})>"


class PoolItem(TimeStampedModel, Base):
    __tablename__ = "pool_items"
    __table_args__ = (Index("ix_pool_items_use_for_trading", "use_for_trading"),)

    market_hash_name: Mapped[str] = mapped_column(String(255), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    app_id: Mapped[str] = mapped_column(String(32), nullable=False)
    context_id: Mapped[str] = mapped_column(String(64), nullable=False)
    icon_url: Mapped[str] = mapped_column(String(512), nullable=False)
    max_listed: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    optimal_buy_price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=True)
    optimal_sell_price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=True)
    manual_buy_price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=True)
    manual_sell_price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=True)
    current_lowest_price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=True)
    current_median_price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=True)
    current_volume24h: Mapped[int] = mapped_column(Integer, nullable=True)
    volatility: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=True)
    potential_profit: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=True)
    use_for_trading: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    def __repr__(self):
        return f"<PoolItem {self.market_hash_name}>"

    @property
    def effective_buy_price(self) -> Decimal | None:
        """
        Return manual override if set, else optimal buy price.
        """
        return self.manual_buy_price or self.optimal_buy_price

    @property
    def effective_sell_price(self) -> Decimal | None:
        """
        Return manual override if set, else optimal sell price.
        """
        return self.manual_sell_price or self.optimal_sell_price


class PriceHistoryRecord(Base):
    __tablename__ = "price_history_record"
    __table_args__ = (UniqueConstraint("market_hash_name", "recorded_at", name="uq_item_stats_item_time"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    market_hash_name: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("pool_items.market_hash_name", ondelete="CASCADE"),
        nullable=False,
    )
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    volume: Mapped[int] = mapped_column(Integer, nullable=False)

    def __repr__(self):
        return f"<Price for {self.market_hash_name} at {self.recorded_at}"
