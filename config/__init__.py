"""Application configuration."""

import os
import secrets
from datetime import timedelta


class Config:
    SECRET_KEY = os.environ.get("MEDTRACK_SECRET_KEY") or secrets.token_hex(32)
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.environ.get("MEDTRACK_COOKIE_SECURE", "0") == "1"
    PERMANENT_SESSION_LIFETIME = timedelta(hours=8)
    DATABASE_PATH = os.environ.get("MEDTRACK_DATABASE_PATH", "instance/medtrack.sqlite3")
    MEDTRACK_DATA_STORE = os.environ.get("MEDTRACK_DATA_STORE", "sqlite").strip().lower()
    DYNAMODB_TABLE_NAME = os.environ.get("DYNAMODB_TABLE_NAME", "").strip()
    AWS_REGION = os.environ.get("AWS_REGION") or None
    SNS_TOPIC_ARN = os.environ.get("SNS_TOPIC_ARN", "").strip()
    MEDTRACK_SNS_ENABLED = os.environ.get("MEDTRACK_SNS_ENABLED", "0").strip().lower() in {
        "1", "true", "yes", "on"
    }
    MAX_CONTENT_LENGTH = 1024 * 1024
