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
def clear_di_caches():
    # Resets every in-memory cache held by module-level DI singletons (currently
    # just the permission cache). Public API so we don't reach into underscore
    # attributes from tests.
    from app.dependencies.services import reset_caches

    reset_caches()
    yield
    reset_caches()


# After merging the bot into the FastAPI process, get_discord_io reads from
# app.state.bot — which only exists if lifespan ran with a real DISCORD_BOT_TOKEN.
# Tests bypass lifespan, so we override the dependency to return a FakeDiscordClient.
# Tests can grab this fake via the `fake_discord` fixture to seed state or assert calls.
@pytest.fixture
def fake_discord():
    from app.dependencies.services import get_discord_io
    from app.main import app
    from tests.fakes.discord import FakeDiscordClient

    fake = FakeDiscordClient()
    app.dependency_overrides[get_discord_io] = lambda: fake
    yield fake
    app.dependency_overrides.pop(get_discord_io, None)


# Autouse default: every test gets a baseline FakeDiscordClient override even if
# it doesn't ask for one. Tests that need to inspect state should depend on
# `fake_discord` directly to get the same instance.
@pytest.fixture(autouse=True)
def _default_fake_discord_override(request):
    from app.dependencies.services import get_discord_io
    from app.main import app
    from tests.fakes.discord import FakeDiscordClient

    # If the test already depends on `fake_discord`, that fixture installs its own
    # override and we don't want to clobber it.
    if "fake_discord" in request.fixturenames:
        yield
        return
    fake = FakeDiscordClient()
    app.dependency_overrides[get_discord_io] = lambda: fake
    yield
    app.dependency_overrides.pop(get_discord_io, None)
