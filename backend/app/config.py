from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    env: str = "dev"
    api_key_internal: str = "CHANGE_ME"

    database_url: str = "postgresql+psycopg2://user:pass@localhost:5432/agenda"

    whatsapp_gateway_url: str = "http://localhost:3001"
    whatsapp_gateway_api_key: str = "CHANGE_ME"
    owner_whatsapp_number: str = "CHANGE_ME"

    openai_api_key: str = "CHANGE_ME"
    openai_model: str = "gpt-4o-mini"

    google_client_id: str = "CHANGE_ME"
    google_client_secret: str = "CHANGE_ME"
    google_redirect_uri: str = "http://localhost:8000/oauth/callback"
    google_token_path: str = "backend/.secrets/token.json"
    google_scopes: str = "https://www.googleapis.com/auth/gmail.modify https://www.googleapis.com/auth/gmail.send https://www.googleapis.com/auth/calendar"
    gmail_poll_minutes: int = 5
    google_calendar_id: str = "primary"

    scheduler_timezone: str = "America/Monterrey"

    class Config:
        env_file = ".env"


settings = Settings()
