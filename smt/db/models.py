from sqlalchemy import Boolean, Column, Integer, String

from smt.db.database import Base


class Item(Base):
    __tablename__ = "items"

    id = Column(String, primary_key=True)
    app_id = Column(String, nullable=False)
    context_id = Column(String, nullable=False)
    name = Column(String, nullable=False)
    market_hash_name = Column(String, nullable=False)
    tradable = Column(Boolean, nullable=False)
    marketable = Column(Boolean, nullable=False)
    amount = Column(Integer, nullable=False)
    icon_url = Column(String, nullable=False)
