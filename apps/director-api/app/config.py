from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(ROOT / ".env"), extra="ignore")

    director_env: str = "development"
    director_host: str = "127.0.0.1"
    director_port: int = 8080
    director_public_url: str = "http://127.0.0.1:8080"
    director_database_url: str = "sqlite+aiosqlite:///./data/kreluna.db"
    director_evidence_dir: str = "./data/evidence"
    director_signing_seed: str = "kreluna-dev-signing-seed-change-in-production"
    director_session_secret: str = "kreluna-dev-session-secret-change-in-production"
    director_evidence_key: str = "kreluna-dev-evidence-key-32b-change!!"
    director_cors_origins: str = "http://127.0.0.1:5173,http://localhost:5173"
    director_policy_path: str = str(ROOT / "policies" / "default.yaml")
    kreluna_llm_base_url: str = ""
    kreluna_llm_api_key: str = ""
    kreluna_llm_model: str = "gpt-4o-mini"
    kreluna_enrollment_code: str = "KRELUNA-DEV-ENROLL"
    heartbeat_timeout_seconds: int = 20
    grant_ttl_seconds: int = 120
    evidence_retention_hours: int = 72

    @property
    def cors_origins(self) -> list[str]:
        return [item.strip() for item in self.director_cors_origins.split(",") if item.strip()]

    @property
    def evidence_path(self) -> Path:
        path = Path(self.director_evidence_dir)
        if not path.is_absolute():
            path = ROOT / path
        return path


settings = Settings()
