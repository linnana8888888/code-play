"""Application settings loaded from environment."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # OpenRouter
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"

    # Anthropic (direct or via proxy — LEGO proxy uses AUTH_TOKEN + BASE_URL)
    anthropic_api_key: str = ""
    anthropic_auth_token: str = ""
    anthropic_base_url: str = "https://api.anthropic.com"

    # oMLX local
    omlx_base_url: str = "http://127.0.0.1:8000"
    omlx_api_key: str = ""

    # LEGO proxy → OpenAI (GPT-5). Reuses `anthropic_auth_token` as the api-key header.
    lego_openai_base_url: str = "https://models.assistant.legogroup.io"
    lego_openai_api_version: str = "2025-04-01-preview"

    # GitHub
    github_token: str = ""
    github_owner: str = "linnana8888888"

    # Telegram
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # Server
    host: str = "0.0.0.0"
    port: int = 8080
    debug: bool = False
    environment: str = "development"  # development | test | production — suppresses external side effects when "test"

    # Paths
    agents_dir: str = "agents"
    config_dir: str = "config"
    projects_dir: str = "projects"
    skills_dir: str = "skills"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()
