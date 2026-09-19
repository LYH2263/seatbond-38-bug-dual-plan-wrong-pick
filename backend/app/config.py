from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")
    database_url: str = "postgresql+psycopg2://seatbond:seatbond@localhost:5442/seatbond"
    seed_on_empty: bool = True
    preview_ttl_seconds: int = 120  # confirm token lifetime for a dual-plan preview


settings = Settings()
