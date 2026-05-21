import pytest
import pytest_asyncio
from dotenv import load_dotenv
from fastapi.testclient import TestClient
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

# Pytest override environment variables for testing
load_dotenv(".env.test")

from app.db.base import Base  # registers all models
from app.db.session import get_db
from app.main import app

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture
async def db_session() -> AsyncSession:
    engine = create_async_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        echo=False,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    Session = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as session:
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


# Shared engine/session for functional tests
_func_engine = create_async_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
    echo=False,
)
_FuncSession = async_sessionmaker(bind=_func_engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture
async def setup_test_db():
    """setup test database schema for each test"""
    async with _func_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with _func_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


async def override_get_db():
    async with _FuncSession() as session:
        yield session


@pytest_asyncio.fixture
async def client(setup_test_db):
    """provide async http client for functional tests"""
    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(
        app=app, base_url="http://test", headers={"X-Client-ID": "test-client"}
    ) as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest.fixture
def sync_client():
    """provide sync test client for simple tests"""
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


@pytest_asyncio.fixture(autouse=True)
async def override_db(db_session):
    from app.db.session import get_db
    from app.main import app

    async def _get_db():
        yield db_session

    app.dependency_overrides[get_db] = _get_db
    yield
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture(autouse=True)
def clear_permission_cache():
    from app.dependencies.services import _perm_svc

    _perm_svc._cache.clear()
    yield
    _perm_svc._cache.clear()
