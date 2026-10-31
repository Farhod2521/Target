from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[2]
CommaList = Annotated[list[str], NoDecode]


def _split_csv(value: Any) -> Any:
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return value


def _strip_site_url(value: Any) -> Any:
    if isinstance(value, str):
        return value.rstrip("/")
    return value


def _blank_as_none(value: Any) -> Any:
    if isinstance(value, str) and not value.strip():
        return None
    return value


def _bare_username(value: Any) -> Any:
    if isinstance(value, str):
        return value.strip().lstrip("@")
    return value


class Env(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )
    secret_key: str = Field(
        default="dev-insecure-key-do-not-use-in-production", alias="DJANGO_SECRET_KEY"
    )
    debug: bool = Field(default=False, alias="DJANGO_DEBUG")
    allowed_hosts: CommaList = Field(
        default=["localhost", "127.0.0.1"], alias="DJANGO_ALLOWED_HOSTS"
    )
    csrf_trusted_origins: CommaList = Field(
        default=["http://localhost:8000"], alias="DJANGO_CSRF_TRUSTED_ORIGINS"
    )
    cors_allowed_origins: CommaList = Field(
        default=["https://targetolog.ai"], alias="CORS_ALLOWED_ORIGINS"
    )
    auth_throttle: bool = Field(default=True, alias="AUTH_THROTTLE")
    purge_test_emails: CommaList = Field(default=[], alias="PURGE_TEST_EMAILS")
    database_url: str = Field(
        default="postgres://targetolog:targetolog@localhost:5433/targetolog",
        alias="DATABASE_URL",
    )
    redis_url: str = Field(default="redis://localhost:6380/0", alias="REDIS_URL")
    celery_broker_url: str = Field(
        default="redis://localhost:6380/1", alias="CELERY_BROKER_URL"
    )
    celery_result_backend: str = Field(
        default="redis://localhost:6380/2", alias="CELERY_RESULT_BACKEND"
    )
    channels_redis_url: str = Field(
        default="redis://localhost:6380/3", alias="CHANNELS_REDIS_URL"
    )
    site_domain: str = Field(default="targetolog.ai", alias="SITE_DOMAIN")
    site_url: str = Field(default="https://targetolog.ai", alias="SITE_URL")
    company_tax_id: str = Field(default="311076944", alias="COMPANY_TAX_ID")
    support_email: str = Field(default="Abdullamn1996@gmail.com", alias="SUPPORT_EMAIL")
    support_telegram: str = Field(
        default="targetolog_ai_konsultant", alias="SUPPORT_TELEGRAM"
    )
    withdrawals_open: bool = Field(default=False, alias="WITHDRAWALS_OPEN")
    default_country_code: str = Field(default="UZ", alias="DEFAULT_COUNTRY_CODE")
    default_timezone: str = Field(default="Asia/Tashkent", alias="DEFAULT_TIMEZONE")
    encryption_key: str = Field(default="", alias="ENCRYPTION_KEY")
    encryption_key_fallbacks: CommaList = Field(
        default=[], alias="ENCRYPTION_KEY_FALLBACKS"
    )
    meta_app_id: str = Field(default="", alias="META_APP_ID")
    meta_app_secret: str = Field(default="", alias="META_APP_SECRET")
    meta_webhook_verify_token: str = Field(
        default="", alias="META_WEBHOOK_VERIFY_TOKEN"
    )
    google_oauth_client_id: str = Field(default="", alias="GOOGLE_OAUTH_CLIENT_ID")
    google_oauth_client_secret: str = Field(
        default="", alias="GOOGLE_OAUTH_CLIENT_SECRET"
    )
    google_picker_api_key: str = Field(default="", alias="GOOGLE_PICKER_API_KEY")
    google_cloud_project_number: str = Field(
        default="", alias="GOOGLE_CLOUD_PROJECT_NUMBER"
    )
    map_tile_url: str = Field(
        default="https://tile.openstreetmap.org/{z}/{x}/{y}.png", alias="MAP_TILE_URL"
    )
    map_tile_attribution: str = Field(
        default='© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
        alias="MAP_TILE_ATTRIBUTION",
    )
    map_max_zoom: int = Field(default=18, alias="MAP_MAX_ZOOM")
    default_ad_provider: str = Field(default="meta", alias="DEFAULT_AD_PROVIDER")
    fallback_category: str = Field(default="services", alias="FALLBACK_CATEGORY")
    default_ad_link: str = Field(
        default="https://targetolog.ai/", alias="DEFAULT_AD_LINK"
    )
    ads_dry_run: bool = Field(default=True, alias="ADS_DRY_RUN")
    ads_max_creatives: int = Field(default=10, ge=1, alias="ADS_MAX_CREATIVES")
    ads_per_group: int = Field(default=6, ge=1, alias="ADS_PER_GROUP")
    ads_per_group_min: int = Field(default=3, ge=1, alias="ADS_PER_GROUP_MIN")
    ads_max_adsets_per_campaign: int = Field(
        default=5, ge=1, alias="ADS_MAX_ADSETS_PER_CAMPAIGN"
    )
    metrics_retry_minutes: int = Field(default=12, ge=0, alias="METRICS_RETRY_MINUTES")
    launch_trace_enabled: bool = Field(default=False, alias="LAUNCH_TRACE_ENABLED")
    launch_goal_picker_v2: bool = Field(default=False, alias="LAUNCH_GOAL_PICKER_V2")
    launch_goal_picker_v2_users: CommaList = Field(
        default=[], alias="LAUNCH_GOAL_PICKER_V2_USERS"
    )
    google_ads_enabled: bool = Field(default=False, alias="GOOGLE_ADS_ENABLED")
    google_ads_users: CommaList = Field(default=[], alias="GOOGLE_ADS_USERS")
    google_ads_dry_run: bool = Field(default=True, alias="GOOGLE_ADS_DRY_RUN")
    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")
    anthropic_model: str = Field(default="claude-sonnet-5", alias="ANTHROPIC_MODEL")
    anthropic_input_price_minor: int = Field(
        default=0, alias="ANTHROPIC_INPUT_PRICE_MINOR"
    )
    anthropic_output_price_minor: int = Field(
        default=0, alias="ANTHROPIC_OUTPUT_PRICE_MINOR"
    )
    anthropic_price_currency: str = Field(
        default="USD", alias="ANTHROPIC_PRICE_CURRENCY"
    )
    anthropic_model_unattended: str = Field(
        default="", alias="ANTHROPIC_MODEL_UNATTENDED"
    )
    anthropic_unattended_input_price_minor: int = Field(
        default=0, alias="ANTHROPIC_UNATTENDED_INPUT_PRICE_MINOR"
    )
    anthropic_unattended_output_price_minor: int = Field(
        default=0, alias="ANTHROPIC_UNATTENDED_OUTPUT_PRICE_MINOR"
    )
    anthropic_cache_write_price_minor: int = Field(
        default=0, alias="ANTHROPIC_CACHE_WRITE_PRICE_MINOR"
    )
    anthropic_cache_read_price_minor: int = Field(
        default=0, alias="ANTHROPIC_CACHE_READ_PRICE_MINOR"
    )
    anthropic_prompt_cache: bool = Field(default=False, alias="ANTHROPIC_PROMPT_CACHE")
    shotstack_api_key: str = Field(default="", alias="SHOTSTACK_API_KEY")
    shotstack_env: Literal["stage", "v1"] = Field(
        default="stage", alias="SHOTSTACK_ENV"
    )
    elevenlabs_api_key: str = Field(default="", alias="ELEVENLABS_API_KEY")
    montage_pipeline: Literal["v2", "v3"] = Field(
        default="v2", alias="MONTAGE_PIPELINE"
    )
    montage_sync_offset_ms: int = Field(
        default=-160, ge=-500, le=500, alias="MONTAGE_SYNC_OFFSET_MS"
    )
    montage_direct_source: bool = Field(default=False, alias="MONTAGE_DIRECT_SOURCE")
    montage_source_base_url: str = Field(default="", alias="MONTAGE_SOURCE_BASE_URL")
    montage_anthropic_model: str = Field(
        default="claude-opus-5-5", alias="MONTAGE_ANTHROPIC_MODEL"
    )
    montage_anthropic_api_key: str = Field(
        default="", alias="MONTAGE_ANTHROPIC_API_KEY"
    )
    montage_anthropic_workspace_id: str = Field(
        default="", alias="MONTAGE_ANTHROPIC_WORKSPACE_ID"
    )
    montage_input_price_minor: int = Field(
        default=400, alias="MONTAGE_INPUT_PRICE_MINOR"
    )
    montage_output_price_minor: int = Field(
        default=2000, alias="MONTAGE_OUTPUT_PRICE_MINOR"
    )
    montage_speech_price_minor_per_hour: int = Field(
        default=22, ge=0, alias="MONTAGE_SPEECH_PRICE_MINOR_PER_HOUR"
    )
    montage_render_price_minor_per_minute: int = Field(
        default=20, ge=0, alias="MONTAGE_RENDER_PRICE_MINOR_PER_MINUTE"
    )
    montage_service_price_currency: str = Field(
        default="USD", alias="MONTAGE_SERVICE_PRICE_CURRENCY"
    )
    ffmpeg_bin: str = Field(default="ffmpeg", alias="FFMPEG_BIN")
    ffprobe_bin: str = Field(default="ffprobe", alias="FFPROBE_BIN")
    telegram_bot_token: str = Field(default="", alias="TELEGRAM_BOT_TOKEN")
    telegram_webhook_secret: str = Field(default="", alias="TELEGRAM_WEBHOOK_SECRET")
    telegram_bot_username: str = Field(default="", alias="TELEGRAM_BOT_USERNAME")
    telegram_mandatory_notices: bool = Field(
        default=True, alias="TELEGRAM_MANDATORY_NOTICES"
    )
    telegram_expiry_notices: bool = Field(
        default=False, alias="TELEGRAM_EXPIRY_NOTICES"
    )
    staff_bot_token: str = Field(default="", alias="STAFF_BOT_TOKEN")
    staff_bot_webhook_secret: str = Field(default="", alias="STAFF_BOT_WEBHOOK_SECRET")
    staff_bot_username: str = Field(default="", alias="STAFF_BOT_USERNAME")
    billing_currency: str = Field(default="USD", alias="BILLING_CURRENCY")
    payme_merchant_id: str = Field(default="", alias="PAYME_MERCHANT_ID")
    payme_key: str = Field(default="", alias="PAYME_KEY")
    payme_account_field: str = Field(default="order_id", alias="PAYME_ACCOUNT_FIELD")
    payme_checkout_url: str = Field(
        default="https://checkout.paycom.uz", alias="PAYME_CHECKOUT_URL"
    )
    click_service_id: str = Field(default="", alias="CLICK_SERVICE_ID")
    click_merchant_id: str = Field(default="", alias="CLICK_MERCHANT_ID")
    click_secret_key: str = Field(default="", alias="CLICK_SECRET_KEY")
    click_checkout_url: str = Field(
        default="https://my.click.uz/services/pay", alias="CLICK_CHECKOUT_URL"
    )
    paynet_username: str = Field(default="", alias="PAYNET_USERNAME")
    paynet_password: str = Field(default="", alias="PAYNET_PASSWORD")
    paynet_service_id: str = Field(default="", alias="PAYNET_SERVICE_ID")
    multicard_application_id: str = Field(default="", alias="MULTICARD_APPLICATION_ID")
    multicard_secret: str = Field(default="", alias="MULTICARD_SECRET")
    multicard_store_id: str = Field(default="", alias="MULTICARD_STORE_ID")
    multicard_api_url: str = Field(
        default="https://mesh.multicard.uz", alias="MULTICARD_API_URL"
    )
    multicard_callback_url: str = Field(default="", alias="MULTICARD_CALLBACK_URL")
    multicard_ofd_mxik: str = Field(default="", alias="MULTICARD_OFD_MXIK")
    multicard_ofd_package_code: str = Field(
        default="", alias="MULTICARD_OFD_PACKAGE_CODE"
    )
    multicard_ofd_name: str = Field(
        default="TargetologAI obunasi", alias="MULTICARD_OFD_NAME"
    )
    multicard_ofd_vat: int | None = Field(default=None, alias="MULTICARD_OFD_VAT")
    multicard_ofd_tin: str = Field(default="", alias="MULTICARD_OFD_TIN")
    multicard_allowed_ips: str = Field(default="", alias="MULTICARD_ALLOWED_IPS")
    sentry_dsn: str = Field(default="", alias="SENTRY_DSN")
    sentry_traces_sample_rate: float = Field(
        default=0.1, alias="SENTRY_TRACES_SAMPLE_RATE"
    )
    sentry_environment: str = Field(default="production", alias="SENTRY_ENVIRONMENT")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    db_pool_max_size: int = Field(default=8, ge=1, alias="DB_POOL_MAX_SIZE")
    celery_always_eager: bool = Field(default=False, alias="CELERY_ALWAYS_EAGER")
    cache_backend: Literal["redis", "memory"] = Field(
        default="redis", alias="CACHE_BACKEND"
    )
    email_backend: Literal["smtp", "console", "memory"] = Field(
        default="console", alias="EMAIL_BACKEND"
    )
    email_host: str = Field(default="", alias="EMAIL_HOST")
    email_port: int = Field(default=587, alias="EMAIL_PORT")
    email_host_user: str = Field(default="", alias="EMAIL_HOST_USER")
    email_host_password: str = Field(default="", alias="EMAIL_HOST_PASSWORD")
    email_use_tls: bool = Field(default=True, alias="EMAIL_USE_TLS")
    email_use_ssl: bool = Field(default=False, alias="EMAIL_USE_SSL")
    email_timeout: int = Field(default=10, alias="EMAIL_TIMEOUT")
    default_from_email: str = Field(
        default="TargetologAI <no-reply@targetolog.ai>", alias="DEFAULT_FROM_EMAIL"
    )
    media_root: Path = Field(default=BASE_DIR / "media", alias="MEDIA_ROOT")
    geoip_db_path: str = Field(default="", alias="GEOIP_DB_PATH")
    usd_uzs_rate: str = Field(default="", alias="USD_UZS_RATE")
    media_url: str = Field(default="/media/", alias="MEDIA_URL")
    agent_small_budgets: dict[str, tuple[int, int]] = {"USD": (1_000, 500)}
    frequency_min_spend: dict[str, int] = {"USD": 300}
    _split = field_validator(
        "allowed_hosts",
        "csrf_trusted_origins",
        "cors_allowed_origins",
        "purge_test_emails",
        "encryption_key_fallbacks",
        "launch_goal_picker_v2_users",
        "google_ads_users",
        mode="before",
    )(_split_csv)
    _normalise_site_url = field_validator("site_url", mode="before")(_strip_site_url)
    _blank_vat = field_validator("multicard_ofd_vat", mode="before")(_blank_as_none)
    _normalise_handle = field_validator("support_telegram", mode="before")(
        _bare_username
    )

    @property
    def office_timezone(self) -> str:
        return self.default_timezone

    @property
    def profile_defaults(self) -> dict[str, str]:
        return {
            "country_code": self.default_country_code,
            "timezone": self.default_timezone,
        }

    @property
    def geoip_db(self) -> Path:
        if self.geoip_db_path:
            return Path(self.geoip_db_path)
        return self.media_root / "geoip" / "country.mmdb"

    @property
    def support_telegram_url(self) -> str:
        return f"https://t.me/{self.support_telegram}" if self.support_telegram else ""

    @property
    def sqlalchemy_url(self) -> str:
        url = self.database_url
        for prefix in ("postgres://", "postgresql://"):
            if url.startswith(prefix):
                return "postgresql+psycopg://" + url[len(prefix) :]
        return url
