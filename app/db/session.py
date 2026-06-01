from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings

engine = create_async_engine(
    settings.SQLALCHEMY_DATABASE_URI,
    pool_pre_ping=True,
    # Mỗi lượt agent GIỮ 1 connection suốt 8-20s (qua các LLM call) -> nhiều người mention
    # cùng lúc dễ cạn pool mặc định (~15). Nới rộng để chịu tải đồng thời.
    pool_size=20,
    max_overflow=30,
    pool_timeout=30,
    echo=False,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db():
    # Unit of Work boundary for HTTP requests: commit once on success, rollback
    # on any exception. Repositories must not commit on their own.
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@asynccontextmanager
async def session_scope():
    # Unit of Work boundary for non-HTTP entrypoints (Discord cogs, listeners,
    # background tasks). Same contract as get_db: repos flush only; commit
    # happens once at scope exit.
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
