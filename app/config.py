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

    debounce_seconds: float = 2.5
    rate_limit_per_minute: int = 20

    groq_api_key: str | None = None
    crm_webhook_url: str | None = None
    escalation_webhook_url: str | None = None
    public_base_url: str = "https://labarber-production-b9de.up.railway.app"
    owner_wa_id: str | None = None
    barber_obed_wa_id: str | None = None
    barber_jesus_wa_id: str | None = None
    barber_yadier_wa_id: str | None = None

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
