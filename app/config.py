import os

from dotenv import load_dotenv

load_dotenv()

# Streamlit is optional here: the ingest script runs outside Streamlit.
try:
    import streamlit as st
except Exception:  # pragma: no cover
    st = None


def _get(key: str, default=None):
    """Read config from Streamlit secrets first (cloud), then .env (local)."""
    if st is not None:
        try:
            val = st.secrets[key]     # direct access; KeyError if absent
            if val is not None:
                return val
        except Exception:
            pass  # no secrets.toml / key not set -> fall through to env
    return os.getenv(key, default)


class Settings:
    # Cloud Postgres/PostGIS URL, or local Docker URL.
    database_url = _get("DATABASE_URL")
    gee_project = _get("GEE_PROJECT")

    # For deployment: a GEE service account instead of interactive auth.
    # Leave these unset locally (interactive `earthengine authenticate` is used).
    gee_service_account = _get("GEE_SERVICE_ACCOUNT")   # the client_email
    gee_key_json = _get("GEE_KEY_JSON")                 # the key file's JSON, as a string


settings = Settings()
