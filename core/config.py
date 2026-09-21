"""Налаштування з оточення. Нічого секретного в коді — все через .env / змінні середовища."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _load_dotenv() -> None:
    path = ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.split("#")[0].strip())


@dataclass(slots=True)
class Config:
    token: str = ""
    admin_ids: set[int] = field(default_factory=set)
    bot_name: str = "SIGNAL BOT"
    channel_url: str = ""
    trader_url: str = ""
    po_ref_url: str = ""
    daily_sessions: int = 3
    data_backend: str = "sim"
    po_ssid: str = ""
    db_path: Path = ROOT / "runtime" / "bot.db"
    database_url: str = ""  # Postgres у хмарі; порожньо -> SQLite-файл

    @classmethod
    def load(cls) -> "Config":
        _load_dotenv()
        admins = {
            int(chunk)
            for chunk in _env("ADMIN_IDS").replace(";", ",").split(",")
            if chunk.strip().lstrip("-").isdigit()
        }
        db = _env("DB_PATH", "runtime/bot.db")
        return cls(
            token=_env("BOT_TOKEN"),
            admin_ids=admins,
            bot_name=_env("BOT_NAME", "SIGNAL BOT"),
            channel_url=_env("CHANNEL_URL"),
            trader_url=_env("TRADER_URL"),
            po_ref_url=_env("PO_REF_URL"),
            daily_sessions=int(_env("DAILY_SESSIONS", "3") or 3),
            data_backend=_env("DATA_BACKEND", "sim").lower(),
            po_ssid=_env("PO_SSID"),
            # Northflank/Neon/Railway називають цю змінну по-різному — беремо першу непорожню
            database_url=next(
                (
                    _env(name)
                    for name in (
                        "DATABASE_URL", "DATABASE_URI", "POSTGRES_URL",
                        "POSTGRES_URI", "POSTGRESQL_URI", "PG_URI",
                    )
                    if _env(name)
                ),
                "",
            ),
            db_path=(ROOT / db) if not os.path.isabs(db) else Path(db),
        )
