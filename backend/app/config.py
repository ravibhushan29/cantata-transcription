from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')

    database_url: str = 'postgresql+psycopg2://cantata:cantata@localhost:5432/cantata'
    redis_url: str = 'redis://localhost:6379/0'

    stt_vendor_base_url: str = 'https://stt-vendor.example.test'
    stt_vendor_api_key: str = 'cantata-test-key'

    magic_link_signing_secret: str = 'change-me-in-prod'

    manual_qa_time_limit_seconds: int = 60 * 60 * 24 * 7

    dlq_max_retries: int = 5
    dlq_retention_days: int = 90
    dlq_scheduler_interval_seconds: int = 30


settings = Settings()
