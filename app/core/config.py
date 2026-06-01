from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # API
    API_V1_STR: str = "/api/v1"
    JWT_SECRET: str = Field(default="")
    JWT_ALGORITHM: str = "HS256"
    JWT_TTL_MINUTES: int = 60 * 24 * 7
    JWT_ISSUER: str = "http://localhost:8000"

    # CORS
    FRONTEND_URL: str = "http://localhost:5173"

    # Database
    POSTGRES_SERVER: str = "localhost"
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "postgres"
    POSTGRES_DB: str = "rolt9"

    # Discord
    DISCORD_CLIENT_ID: str = Field(default="")
    DISCORD_CLIENT_SECRET: str = Field(default="")
    DISCORD_BOT_TOKEN: str = Field(default="")
    DISCORD_REDIRECT_URI: str = "http://localhost:8000/api/v1/auth/discord/callback"
    BOT_INVITE_URL: str = Field(default="")

    # AI — BYO-key per-guild (xem ai_gateway). ANTHROPIC_API_KEY deprecated (không
    # còn fallback). AI_MAX_TOKENS phải đủ rộng cho model reasoning (DeepSeek,
    # o-series…) vì chúng tiêu token cho phần suy luận trước khi trả lời.
    ANTHROPIC_API_KEY: str = Field(default="")
    AI_MODEL: str = "claude-haiku-4-5-20251001"
    # 200k: trần OUTPUT rộng để reasoning model (deepseek v4 pro/flash) KHÔNG đốt sạch token
    # vào phần suy luận rồi trả rỗng ("Model dùng hết token cho phần suy luận"). max_tokens chỉ
    # là TRẦN — model xong là dừng, đặt cao không tốn thêm tiền nếu nó trả lời ngắn.
    AI_MAX_TOKENS: int = 200000
    # Claw Agent tools: web search qua Tavily (key global, bot trả). Rỗng = tắt web_search.
    TAVILY_API_KEY: str = Field(default="")

    # Tokens
    TOKEN_ENCRYPTION_KEY: str = Field(default="")

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # Legacy / internal client IDs (comma-separated); used by ClientIdMiddleware
    CLIENT_IDS: str = "test-client"

    @computed_field
    @property
    def SQLALCHEMY_DATABASE_URI(self) -> str:
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_SERVER}/{self.POSTGRES_DB}"
        )


settings = Settings()
