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
    inbound_limit_per_minute: int = Field(default=20, ge=1, le=300)
    max_pending_messages: int = Field(default=40, ge=2, le=300)
    global_ai_turns_per_minute: int = Field(default=60, ge=1, le=10000)
    booking_min_notice_minutes: int = Field(default=0, ge=0, le=43200)
    booking_max_advance_days: int | None = Field(default=None, ge=1, le=730)
    service_durations: dict[str, int] = Field(default_factory=dict)
    calendar_utc_migration_enabled: bool = False

    groq_api_key: str | None = None
    crm_webhook_url: str | None = None
    escalation_webhook_url: str | None = None
    owner_wa_id: str | None = None
    barber_obed_wa_id: str | None = None
    barber_jesus_wa_id: str | None = None
    barber_yadier_wa_id: str | None = None
    barbers: list[BarberConfig] = Field(default_factory=list)
    business_name: str = "Red Level Barber"
    automatic_notices_enabled: bool = False
    reminder_template_name: str = ""
    turn_template_name: str = ""
    appointment_template_name: str = ""
    support_template_name: str = ""
    notification_template_language: str = "es_MX"

    @model_validator(mode="after")
    def valid_booking_policy(self):
        services = {"corte normal", "corte clásico", "barba y corte", "servicio completo"}
        for service, minutes in self.service_durations.items():
            if service not in services or minutes < 30 or minutes > 720 or minutes % 30:
                raise ValueError(
                    "Duraciones: servicio válido y múltiplos de 30, entre 30 y 720 minutos"
                )
        if (
            self.booking_max_advance_days is not None
            and self.booking_min_notice_minutes >= self.booking_max_advance_days * 1440
        ):
            raise ValueError("La anticipación mínima debe ser menor que la máxima")
        return self

    @field_validator("barbers")
    @classmethod
    def unique_barbers(cls, value):
        import unicodedata

        from app.identity import normalize_phone

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
