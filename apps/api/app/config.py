from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

API_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = API_DIR.parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AGENTATHON_", env_file=(REPO_DIR / ".env",), extra="ignore")

    host: str = "127.0.0.1"
    port: int = 8000
    data_dir: Path = Field(default=REPO_DIR / "data")
    database_url: str | None = None
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000", "http://127.0.0.1:3000"])

    # Autenticacao: "local" = workspace unico sem token (somente loopback); "token" = Bearer obrigatorio.
    auth_mode: str = "local"
    api_tokens: str = Field(default="", description="Formato: token1:owner1,token2:owner2")

    # Limites do servidor
    max_upload_mb: int = 10
    max_pdf_pages: int = 100
    max_sources: int = 5
    server_max_deadline_s: int = 600
    executor_enabled: bool = True
    executor_poll_s: float = 0.25

    # NeuraLake (somente backend; nunca enviado ao frontend)
    neuralake_api_key: str | None = None
    neuralake_base_url: str = "https://api.neuralake.cloud/v1"
    neuralake_json_mode: bool = Field(default=False, description="Envia response_format=json_object (compatibilidade nao confirmada).")
    neuralake_prices_file: Path | None = Field(
        default=REPO_DIR / "fixtures" / "prices" / "neuralake.public-2026-09-30.json",
        description="Tabela de precos versionada. Default: pagina publica de precos (estimativa, nao fatura).",
    )

    @property
    def db_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite+aiosqlite:///{(self.data_dir / 'agentathon.db').as_posix()}"

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    def token_map(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for pair in filter(None, (p.strip() for p in self.api_tokens.split(","))):
            token, _, owner = pair.partition(":")
            if token and owner:
                out[token] = owner
        return out


@lru_cache
def get_settings() -> Settings:
    return Settings()
