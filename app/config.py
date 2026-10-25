from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_PLACEHOLDER_MODELS = {"", "changeme", "your-model"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )

    meta_app_secret: str
    meta_webhook_verify_token: str
    whatsapp_phone_number_id: str
    whatsapp_access_token: str

    openai_api_key: str
    openai_model: str = Field(min_length=1)

    redis_url: str = "redis://localhost:6379/0"
    database_url: str

    debounce_seconds: float = Field(default=2.5, ge=0, le=10)
    rate_limit_per_minute: int = Field(default=20, ge=1, le=300)

    groq_api_key: str | None = None
    crm_webhook_url: str | None = None
    escalation_webhook_url: str | None = None
    public_base_url: str = "https://labarber-production-b9de.up.railway.app"
    owner_wa_id: str | None = None
    barber_obed_wa_id: str | None = None
    barber_jesus_wa_id: str | None = None
    barber_yadier_wa_id: str | None = None

    @field_validator(
        "meta_app_secret",
        "meta_webhook_verify_token",
        "whatsapp_phone_number_id",
        "whatsapp_access_token",
        "openai_api_key",
        "database_url",
        "redis_url",
    )
    @classmethod
    def required_values_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("La variable requerida no puede estar vacía.")
        return value

    @field_validator("database_url")
    @classmethod
    def use_installed_postgres_driver(cls, value: str) -> str:
        for prefix in ("postgres://", "postgresql://"):
            if value.startswith(prefix):
                return "postgresql+psycopg://" + value[len(prefix) :]
        return value

    @field_validator(
        "owner_wa_id", "barber_obed_wa_id", "barber_jesus_wa_id", "barber_yadier_wa_id"
    )
    @classmethod
    def validate_staff_phone(cls, value: str | None) -> str | None:
        from app.identity import normalize_phone

        if value is None or not value.strip():
            return None
        if normalize_phone(value) is None:
            raise ValueError("Usa un número local de 10 dígitos o un número internacional válido.")
        return value.strip()

    @field_validator("openai_model")
    @classmethod
    def openai_model_must_be_real(cls, value: str) -> str:
        model = value.strip()
        if model.lower() in _PLACEHOLDER_MODELS:
            raise ValueError(
                "OPENAI_MODEL está vacío o es un placeholder. "
                "Configura un modelo real de OpenAI en OPENAI_MODEL."
            )
        return model


@lru_cache
def get_settings() -> Settings:
    return Settings()
