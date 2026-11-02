from functools import lru_cache

from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_PLACEHOLDER_MODELS = {"", "changeme", "your-model"}


class BarberConfig(BaseModel):
    name: str = Field(min_length=1, max_length=80, pattern=r"^[\w ÁÉÍÓÚáéíóúÑñ-]+$")
    phone: str | None = None
    # Weekday 0=Monday, 6=Sunday; omitted days are closed when hours is provided.
    hours: dict[str, list[list[int]]] | None = None

    @model_validator(mode="after")
    def valid_roster_entry(self):
        from app.identity import normalize_phone

        self.name = self.name.strip()
        if not self.name:
            raise ValueError("El nombre del barbero no puede estar vacío")
        if self.name.casefold() in {"all", "owner", "assigned", "unspecified"}:
            raise ValueError("Nombre reservado")
        if self.phone and not normalize_phone(self.phone):
            raise ValueError("Teléfono inválido")
        for day, windows in (self.hours or {}).items():
            if day not in {str(i) for i in range(7)}:
                raise ValueError("Día de semana inválido")
            previous = -1
            for window in sorted(windows):
                if len(window) != 2:
                    raise ValueError("Horario debe tener inicio y fin en minutos")
                start, end = window
                if not (0 <= start < end <= 1440) or start % 30 or end % 30 or start < previous:
                    raise ValueError("Horario inválido: intervalos de 30 minutos sin solapamiento")
                previous = end
        return self


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
    barbers: list[BarberConfig] = Field(default_factory=list)
    business_name: str = "BARBER CG"
    automatic_notices_enabled: bool = False
    reminder_template_name: str = ""
    turn_template_name: str = ""
    notification_template_language: str = "es_MX"

    @field_validator("barbers")
    @classmethod
    def unique_barbers(cls, value):
        from app.identity import normalize_phone
        import unicodedata

        names = [
            "".join(
                c
                for c in unicodedata.normalize("NFD", b.name.casefold())
                if not unicodedata.combining(c)
            )
            for b in value
        ]
        phones = [normalize_phone(b.phone) for b in value if b.phone]
        if len(names) != len(set(names)) or len(phones) != len(set(phones)):
            raise ValueError("Barberos o teléfonos duplicados")
        return value

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
