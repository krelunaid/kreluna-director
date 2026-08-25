from dataclasses import dataclass
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[3]
AI_PROVIDERS = ("grok", "ollama", "openai")


@dataclass(frozen=True)
class AIProviderConfig:
    provider: str
    label: str
    base_url: str
    api_key: str
    model: str
    credential_error: str = ""

    @property
    def configured(self) -> bool:
        credentials_ready = self.provider == "ollama" or bool(self.api_key)
        return bool(
            self.base_url and self.model and credentials_ready and not self.credential_error
        )


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
    director_credential_key: str = "kreluna-dev-credential-key-change-in-production"
    director_cors_origins: str = "http://127.0.0.1:5173,http://localhost:5173"
    director_policy_path: str = str(ROOT / "policies" / "default.yaml")
    kreluna_llm_provider: str = "grok"
    kreluna_llm_base_url: str = ""
    kreluna_llm_api_key: str = ""
    kreluna_llm_model: str = "gpt-4o-mini"
    kreluna_grok_base_url: str = "https://api.x.ai/v1"
    kreluna_grok_api_key: str = ""
    kreluna_grok_model: str = "grok-4.6"
    kreluna_ollama_base_url: str = "http://127.0.0.1:11434/v1"
    kreluna_ollama_model: str = ""
    kreluna_openai_base_url: str = "https://api.openai.com/v1"
    kreluna_openai_api_key: str = ""
    kreluna_openai_model: str = ""
    kreluna_enrollment_code: str = "KRELUNA-DEV-ENROLL"
    kreluna_update_api_url: str = (
        "https://api.github.com/repos/krelunaid/kreluna-director/releases/latest"
    )
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
        explicit_provider = self.kreluna_llm_provider.strip().lower()
        if explicit_provider and explicit_provider not in AI_PROVIDERS:
            raise ValueError(
                "KRELUNA_LLM_PROVIDER deve essere uno tra: " + ", ".join(AI_PROVIDERS)
            )
        if not self.is_production:
            return self
        secrets = {
            "DIRECTOR_SIGNING_SEED": self.director_signing_seed,
            "DIRECTOR_SESSION_SECRET": self.director_session_secret,
            "DIRECTOR_EVIDENCE_KEY": self.director_evidence_key,
            "DIRECTOR_CREDENTIAL_KEY": self.director_credential_key,
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
    def selected_ai_provider(self) -> str:
        explicit = self.kreluna_llm_provider.strip().lower()
        if explicit:
            return explicit
        legacy_url = self.kreluna_llm_base_url.strip().lower()
        if "x.ai" in legacy_url:
            return "grok"
        if "localhost" in legacy_url or "127.0.0.1" in legacy_url or "11434" in legacy_url:
            return "ollama"
        return "openai"

    def ai_provider_config(self, provider: str | None = None) -> AIProviderConfig:
        selected = (provider or self.selected_ai_provider).strip().lower()
        if selected not in AI_PROVIDERS:
            raise ValueError("Provider IA sconosciuto")
        legacy_selected = selected == self.selected_ai_provider and bool(
            self.kreluna_llm_base_url.strip()
        )
        legacy_url = self.kreluna_llm_base_url.strip() if legacy_selected else ""
        legacy_key = self.kreluna_llm_api_key.strip() if legacy_selected else ""
        legacy_model = self.kreluna_llm_model.strip() if legacy_selected else ""
        if selected == "grok":
            return AIProviderConfig(
                provider="grok",
                label="Grok",
                base_url=legacy_url or self.kreluna_grok_base_url.strip(),
                api_key=self.kreluna_grok_api_key.strip() or legacy_key,
                model=self.kreluna_grok_model.strip() or legacy_model,
            )
        if selected == "ollama":
            return AIProviderConfig(
                provider="ollama",
                label="Ollama",
                base_url=legacy_url or self.kreluna_ollama_base_url.strip(),
                api_key="",
                model=self.kreluna_ollama_model.strip() or legacy_model,
            )
        return AIProviderConfig(
            provider="openai",
            label="OpenAI",
            base_url=legacy_url or self.kreluna_openai_base_url.strip(),
            api_key=self.kreluna_openai_api_key.strip() or legacy_key,
            model=self.kreluna_openai_model.strip() or legacy_model,
        )

    @property
    def llm_ready(self) -> bool:
        return self.ai_provider_config().configured

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
