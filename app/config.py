import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class AdminUser:
    username: str
    password: str
    display_name: str


def _parse_admins(raw: str) -> dict[str, AdminUser]:
    users = {}
    for entry in filter(None, (e.strip() for e in raw.split(";"))):
        parts = entry.split(":", 2)
        if len(parts) < 2:
            continue
        name = parts[2] if len(parts) == 3 else parts[0]
        users[parts[0]] = AdminUser(parts[0], parts[1], name)
    return users


class Settings:
    def __init__(self) -> None:
        self.base_url = os.getenv("BASE_URL", "http://localhost:8000").rstrip("/")
        self.secret_key = os.getenv("SECRET_KEY", "dev-only-secret")
        self.database_url = os.getenv("DATABASE_URL", f"sqlite:///{ROOT / 'dev.db'}")
        self.media_dir = Path(os.getenv("MEDIA_DIR", str(ROOT / "media")))
        self.content_dir = Path(os.getenv("CONTENT_DIR", str(ROOT / "content")))
        self.admins = _parse_admins(os.getenv("ADMIN_USERS", "admin:admin:Admin"))
        self.org_name = os.getenv("ORG_NAME", "Maintenance Department")
        self.assignment_valid_days = int(os.getenv("ASSIGNMENT_VALID_DAYS", "30"))


settings = Settings()

LANGUAGES = {
    "en": {"name": "English", "native": "English", "dir": "ltr"},
    "ar": {"name": "Arabic", "native": "العربية", "dir": "rtl"},
    "hi": {"name": "Hindi", "native": "हिन्दी", "dir": "ltr"},
    "ml": {"name": "Malayalam", "native": "മലയാളം", "dir": "ltr"},
}
