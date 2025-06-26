from datetime import datetime
from decimal import Decimal
from urllib.parse import quote

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from smt.db.database import Base, TimeStampedModel
from smt.schemas.position import PositionStatus


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

    @property
    def listing_url(self) -> str:
        base = "https://steamcommunity.com/market/listings/"
        encoded_name = quote(self.market_hash_name, safe="")
        return f"{base}/{self.app_id}/{encoded_name}"

    def __repr__(self):
        return f"<PoolItem {self.market_hash_name}>"


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


class TradingSettings(TimeStampedModel, Base):
    __tablename__ = "trading_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    min_profit_threshold: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0.10"))
    min_profit_percentage: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("5.00"))
    max_investment_per_item: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("50.00"))
    buy_percentile: Mapped[int] = mapped_column(Integer, default=20)
    sell_percentile: Mapped[int] = mapped_column(Integer, default=80)
    min_volume_24h: Mapped[int] = mapped_column(Integer, default=10)
    min_volume_7d: Mapped[int] = mapped_column(Integer, default=50)
    max_volatility_threshold: Mapped[Decimal] = mapped_column(Numeric(10, 4), default=Decimal("0.5000"))
    min_volatility_threshold: Mapped[Decimal] = mapped_column(Numeric(10, 4), default=Decimal("0.0100"))
    price_history_days: Mapped[int] = mapped_column(Integer, default=30)
    analysis_window_days: Mapped[int] = mapped_column(Integer, default=7)
    max_concurrent_trades: Mapped[int] = mapped_column(Integer, default=10)
    cooldown_after_loss_hours: Mapped[int] = mapped_column(Integer, default=24)
    price_refresh_interval_minutes: Mapped[int] = mapped_column(Integer, default=30)
    stats_refresh_interval_minutes: Mapped[int] = mapped_column(Integer, default=60)
    emergency_stop: Mapped[bool] = mapped_column(Boolean, default=False)
    max_daily_loss: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("100.00"))

    def __repr__(self):
        return f"<TradingSettings {self.id}>"


class Position(TimeStampedModel, Base):
    __tablename__ = "positions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pool_item_hash: Mapped[str] = mapped_column(
        String(255), ForeignKey("pool_items.market_hash_name", ondelete="CASCADE"), nullable=False
    )
    pool_item = relationship("PoolItem", back_populates="positions")
    buy_order_id: Mapped[str] = mapped_column(String(64), nullable=False)
    buy_price: Mapped[Numeric] = mapped_column(Numeric(10, 2), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    sell_order_id: Mapped[str] = mapped_column(String(64), nullable=True)
    sell_price: Mapped[Numeric] = mapped_column(Numeric(10, 2), nullable=True)
    sold_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[PositionStatus] = mapped_column(
        Enum(PositionStatus, name="position_status"), default=PositionStatus.OPEN, nullable=False
    )

    def __repr__(self) -> str:
        return (
            f"<Position id={self.id} item={self.pool_item_hash} "
            f"status={self.status.value} qty={self.quantity} buy={self.buy_price}"
            f" sell={self.sell_price}>"
        )
