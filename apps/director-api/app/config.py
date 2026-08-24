from pathlib import Path

from pydantic import model_validator
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
    director_bootstrap_email: str = ""
    director_bootstrap_password: str = ""
    director_bootstrap_name: str = "Titolare studio"
    director_bootstrap_tenant_name: str = "Studio"
    director_bootstrap_tenant_slug: str = "studio"
    heartbeat_timeout_seconds: int = 20
    grant_ttl_seconds: int = 120
    evidence_retention_hours: int = 72

    @property
    def is_production(self) -> bool:
        return self.director_env.strip().lower() in {"production", "prod"}

    @model_validator(mode="after")
    def production_must_be_explicit(self) -> "Settings":
        if not self.is_production:
            return self
        secrets = {
            "DIRECTOR_SIGNING_SEED": self.director_signing_seed,
            "DIRECTOR_SESSION_SECRET": self.director_session_secret,
            "DIRECTOR_EVIDENCE_KEY": self.director_evidence_key,
            "KRELUNA_ENROLLMENT_CODE": self.kreluna_enrollment_code,
        }
        invalid = [
            name
            for name, value in secrets.items()
            if len(value.strip()) < 32 or "dev" in value.lower() or "change" in value.lower()
        ]
        if invalid:
            raise ValueError(
                "Produzione bloccata: configura segreti unici di almeno 32 caratteri: "
                + ", ".join(invalid)
            )
        if len({value.strip() for value in secrets.values()}) != len(secrets):
            raise ValueError("Produzione bloccata: i segreti del Director devono essere distinti")
        if not self.director_bootstrap_email.strip() or len(self.director_bootstrap_password) < 14:
            raise ValueError(
                "Produzione bloccata: configura DIRECTOR_BOOTSTRAP_EMAIL e "
                "DIRECTOR_BOOTSTRAP_PASSWORD (almeno 14 caratteri)"
            )
        return self

    @property
    def llm_ready(self) -> bool:
        return bool(self.kreluna_llm_base_url.strip() and self.kreluna_llm_api_key.strip())

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
