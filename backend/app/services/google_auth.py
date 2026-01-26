import os
from typing import List

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

from ..config import settings


def _scopes() -> List[str]:
    return [s.strip() for s in settings.google_scopes.split(" ") if s.strip()]


def _client_config():
    return {
        "web": {
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "redirect_uris": [settings.google_redirect_uri],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }


def get_auth_url() -> str:
    flow = Flow.from_client_config(_client_config(), scopes=_scopes())
    flow.redirect_uri = settings.google_redirect_uri
    auth_url, _ = flow.authorization_url(
        access_type="offline", include_granted_scopes="true", prompt="consent"
    )
    return auth_url


def save_token_from_code(code: str) -> Credentials:
    flow = Flow.from_client_config(_client_config(), scopes=_scopes())
    flow.redirect_uri = settings.google_redirect_uri
    flow.fetch_token(code=code)
    creds = flow.credentials

    os.makedirs(os.path.dirname(settings.google_token_path), exist_ok=True)
    with open(settings.google_token_path, "w", encoding="utf-8") as f:
        f.write(creds.to_json())
    return creds


def load_credentials() -> Credentials | None:
    if not os.path.exists(settings.google_token_path):
        return None
    creds = Credentials.from_authorized_user_file(settings.google_token_path, _scopes())
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(settings.google_token_path, "w", encoding="utf-8") as f:
            f.write(creds.to_json())
    return creds


def get_gmail_service():
    creds = load_credentials()
    if not creds or not creds.valid:
        return None
    return build("gmail", "v1", credentials=creds)


def get_calendar_service():
    creds = load_credentials()
    if not creds or not creds.valid:
        return None
    return build("calendar", "v3", credentials=creds)
