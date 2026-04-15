"""Application settings loaded from environment."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # OpenRouter
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"

    # Anthropic direct
    anthropic_api_key: str = ""

    # oMLX local
    omlx_base_url: str = "http://127.0.0.1:8000"
    omlx_api_key: str = ""

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

    # Paths
    agents_dir: str = "agents"
    config_dir: str = "config"
    projects_dir: str = "projects"
    skills_dir: str = "skills"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
