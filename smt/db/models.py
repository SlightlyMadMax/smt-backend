from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, Numeric, String, UniqueConstraint, func
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
    amount: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    icon_url: Mapped[str] = mapped_column(String(512), nullable=False)

    def __repr__(self):
        return f"<Item {self.name} ({self.id})>"


class PoolItem(TimeStampedModel):
    __tablename__ = "pool_items"

    market_hash_name: Mapped[str] = mapped_column(String(255), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    max_listed: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    buy_price: Mapped[float] = mapped_column(Float, nullable=True)
    sell_price: Mapped[float] = mapped_column(Float, nullable=True)
    icon_url: Mapped[str] = mapped_column(String(512), nullable=False)

    def __repr__(self):
        return f"<Pool item {self.market_hash_name}"


class ItemStat(Base):
    __tablename__ = "item_stats"
    __table_args__ = (UniqueConstraint("market_hash_name", "recorded_at", name="uq_item_stats_item_time"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    market_hash_name: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("pool_items.market_hash_name", ondelete="CASCADE"),
        nullable=False,
    )
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    price: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    volume: Mapped[int] = mapped_column(Integer, nullable=False)

    def __repr__(self):
        return f"<Price for {self.market_hash_name} at {self.recorded_at}"
