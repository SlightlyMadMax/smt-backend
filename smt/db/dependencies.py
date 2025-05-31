from sqlalchemy.ext.asyncio import AsyncSession

from smt.db.database import async_session_maker


async def get_db() -> AsyncSession:
    """
    Create a new AsyncSession for each request, yield it,
    and ensure it’s closed once the request is done.
    """
    async with async_session_maker() as session:
        yield session
