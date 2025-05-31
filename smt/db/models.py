from sqlalchemy import Boolean, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from smt.db.database import Base


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
