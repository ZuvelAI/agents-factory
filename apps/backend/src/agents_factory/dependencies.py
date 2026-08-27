from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from agents_factory.database import Database, transaction


async def get_transaction(request: Request) -> AsyncIterator[AsyncSession]:
    """Resolve the application database into one request transaction."""

    database: Database = request.app.state.database
    async for session in transaction(database.session_factory):
        yield session


TransactionSession = Annotated[AsyncSession, Depends(get_transaction)]
