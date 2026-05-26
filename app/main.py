import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.v1.api import api_router
from app.bot.client import build_bot
from app.core.config import settings
from app.dependencies.services import close_http_client
from app.exceptions.handlers import add_exception_handlers
from app.middlewares.setup import setup_middlewares
from app.utils.docs import setup_swagger_documentation
from app.utils.response import create_response

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# Single-process lifespan: spins up the Discord bot as a background task
# alongside the FastAPI HTTP server. Endpoints reach the live bot through
# request.app.state.bot, which BotDiscordClient wraps for outbound calls.
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting up the application...")

    # Skip bot startup when there's no token (tests, local API-only dev).
    # Endpoints that hit DiscordClient will fail until they override the
    # dependency — tests already do this through dependency_overrides.
    bot = None
    bot_task = None
    if settings.DISCORD_BOT_TOKEN:
        bot = build_bot()
        # discord.py's start() is login() + connect(). We have to split them:
        #   - login() initializes the client's internal _ready event and async
        #     resources. Until it returns, bot.wait_until_ready() raises
        #     "Client has not been properly initialised".
        #   - connect() opens the gateway and runs the receive loop forever, so
        #     it must run as a background task.
        await bot.login(settings.DISCORD_BOT_TOKEN)
        bot_task = asyncio.create_task(bot.connect())
        # Now that login finished, wait_until_ready can subscribe to the READY
        # event. This blocks lifespan startup until the bot has the initial
        # gateway state, so the first HTTP request never sees a half-loaded bot.
        await bot.wait_until_ready()
        logger.info("Discord bot connected and ready.")
    else:
        logger.warning(
            "DISCORD_BOT_TOKEN not set — skipping bot startup. "
            "Endpoints using DiscordClient will fail unless overridden."
        )

    app.state.bot = bot

    try:
        yield
    finally:
        logger.info("Shutting down the application...")
        if bot is not None:
            # bot.close() signals connect()'s receive loop to exit cleanly.
            await bot.close()
        if bot_task is not None:
            try:
                await bot_task
            except (asyncio.CancelledError, Exception):
                # Swallow whatever connect() raises during teardown — close()
                # above is the source of truth for the shutdown.
                pass
        await close_http_client()


app = FastAPI(
    title="FastAPI Application",
    description="FastAPI application with SQLAlchemy and PostgreSQL",
    version="0.1.0",
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    docs_url=None,
    redoc_url=None,
    lifespan=lifespan,
)

# Mount the "public" folder at "/static" path
app.mount("/images", StaticFiles(directory="app/public/images"), name="images")
app.mount("/css", StaticFiles(directory="app/public/css"), name="css")
app.mount("/js", StaticFiles(directory="app/public/js"), name="js")

# Set up custom Swagger documentation
setup_swagger_documentation(app, settings.API_V1_STR)

# global error handler
add_exception_handlers(app)

# Set up middlewares
setup_middlewares(app)

# Include API router
app.include_router(prefix=settings.API_V1_STR, router=api_router)


# Root health check endpoint
@app.get("/", tags=["health"])
def root():
    """Root endpoint for health checks"""
    data = {"status": "ok", "message": "API is running"}
    return create_response(
        data=data,
        message="API is running",
    )


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    """Favicon endpoint"""
    return FileResponse("app/public/images/favicon.ico")
