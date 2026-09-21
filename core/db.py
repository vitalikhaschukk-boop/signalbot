"""Шар зберігання: юзери, витрачені запити, підписки, налаштування.

Працює на двох двигунах з однаковим API:
  * SQLite — локальна розробка (файл `runtime/bot.db`);
  * Postgres — хмара, якщо задано `DATABASE_URL` (у контейнера диск тимчасовий,
    тож юзери й підписки мусять жити в окремій базі, а не у файлі поряд).

Запити пишемо один раз із `?`, драйвер Postgres сам міняє їх на `%s`.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Sequence

UTC = timezone.utc

SCHEMA_SQLITE = """
CREATE TABLE IF NOT EXISTS users (
    user_id        INTEGER PRIMARY KEY,
    username       TEXT,
    first_name     TEXT,
    lang           TEXT NOT NULL DEFAULT 'uk',
    created_at     TEXT NOT NULL,
    last_seen_at   TEXT NOT NULL,
    requests_used  INTEGER NOT NULL DEFAULT 0,
    sessions_today INTEGER NOT NULL DEFAULT 0,
    session_day    TEXT,
    sub_plan       TEXT,
    sub_until      TEXT,
    banned         INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS requests (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id   INTEGER NOT NULL,
    ts        TEXT NOT NULL,
    asset     TEXT,
    timeframe INTEGER,
    direction TEXT
);
CREATE INDEX IF NOT EXISTS idx_requests_user ON requests(user_id, ts);
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sub_log (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id  INTEGER NOT NULL,
    admin_id INTEGER NOT NULL,
    action   TEXT NOT NULL,
    plan     TEXT,
    days     INTEGER,
    ts       TEXT NOT NULL
);
"""

SCHEMA_PG = """
CREATE TABLE IF NOT EXISTS users (
    user_id        BIGINT PRIMARY KEY,
    username       TEXT,
    first_name     TEXT,
    lang           TEXT NOT NULL DEFAULT 'uk',
    created_at     TEXT NOT NULL,
    last_seen_at   TEXT NOT NULL,
    requests_used  INTEGER NOT NULL DEFAULT 0,
    sessions_today INTEGER NOT NULL DEFAULT 0,
    session_day    TEXT,
    sub_plan       TEXT,
    sub_until      TEXT,
    banned         INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS requests (
    id        BIGSERIAL PRIMARY KEY,
    user_id   BIGINT NOT NULL,
    ts        TEXT NOT NULL,
    asset     TEXT,
    timeframe INTEGER,
    direction TEXT
);
CREATE INDEX IF NOT EXISTS idx_requests_user ON requests(user_id, ts);
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sub_log (
    id       BIGSERIAL PRIMARY KEY,
    user_id  BIGINT NOT NULL,
    admin_id BIGINT NOT NULL,
    action   TEXT NOT NULL,
    plan     TEXT,
    days     INTEGER,
    ts       TEXT NOT NULL
);
"""


def now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="seconds")


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def is_postgres_dsn(value: str) -> bool:
    return value.startswith(("postgres://", "postgresql://"))


class _SqliteDriver:
    name = "sqlite"

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA_SQLITE)
        self.conn.commit()

    def query(self, sql: str, params: Sequence[Any] = ()) -> list[Any]:
        rows = self.conn.execute(sql, tuple(params)).fetchall()
        self.conn.commit()
        return rows

    def execute(self, sql: str, params: Sequence[Any] = ()) -> None:
        self.conn.execute(sql, tuple(params))
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()


class _PostgresDriver:
    name = "postgres"

    def __init__(self, dsn: str) -> None:
        import psycopg  # локальна розробка обходиться без драйвера
        from psycopg.rows import dict_row

        self._psycopg = psycopg
        self.conn = psycopg.connect(dsn, autocommit=True, row_factory=dict_row)
        with self.conn.cursor() as cursor:
            cursor.execute(SCHEMA_PG)

    @staticmethod
    def _translate(sql: str) -> str:
        return sql.replace("?", "%s")

    def _cursor(self):
        if self.conn.closed:  # мережа моргнула — піднімаємось без падіння бота
            self.conn = self._psycopg.connect(
                self.conn.info.dsn, autocommit=True, row_factory=self.conn.row_factory
            )
        return self.conn.cursor()

    def query(self, sql: str, params: Sequence[Any] = ()) -> list[Any]:
        with self._cursor() as cursor:
            cursor.execute(self._translate(sql), tuple(params))
            return cursor.fetchall()

    def execute(self, sql: str, params: Sequence[Any] = ()) -> None:
        with self._cursor() as cursor:
            cursor.execute(self._translate(sql), tuple(params))

    def close(self) -> None:
        self.conn.close()


@dataclass(slots=True)
class User:
    user_id: int
    username: str | None
    first_name: str | None
    lang: str
    requests_used: int
    sessions_today: int
    session_day: str | None
    sub_plan: str | None
    sub_until: datetime | None
    banned: bool
    created_at: datetime | None = None

    @property
    def sub_active(self) -> bool:
        return self.sub_until is not None and self.sub_until > now()

    def sessions_left(self, daily_limit: int) -> int:
        if self.session_day != date.today().isoformat():
            return daily_limit
        return max(0, daily_limit - self.sessions_today)

    def sessions_used(self, daily_limit: int) -> int:
        return daily_limit - self.sessions_left(daily_limit)


class Database:
    def __init__(self, target: Path | str) -> None:
        text = str(target)
        self.driver = _PostgresDriver(text) if is_postgres_dsn(text) else _SqliteDriver(Path(text))

    @property
    def engine(self) -> str:
        return self.driver.name

    def close(self) -> None:
        self.driver.close()

    # ---------------- users ----------------
    def upsert_user(self, user_id: int, username: str | None, first_name: str | None) -> User:
        stamp = _iso(now())
        self.driver.execute(
            """INSERT INTO users (user_id, username, first_name, created_at, last_seen_at)
                    VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(user_id) DO UPDATE SET
                    username = excluded.username,
                    first_name = excluded.first_name,
                    last_seen_at = excluded.last_seen_at""",
            (user_id, username, first_name, stamp, stamp),
        )
        user = self.get_user(user_id)
        assert user is not None
        return user

    def get_user(self, user_id: int) -> User | None:
        rows = self.driver.query("SELECT * FROM users WHERE user_id = ?", (user_id,))
        return self._row_to_user(rows[0]) if rows else None

    @staticmethod
    def _row_to_user(row: Any) -> User:
        return User(
            user_id=row["user_id"],
            username=row["username"],
            first_name=row["first_name"],
            lang=row["lang"],
            requests_used=row["requests_used"],
            sessions_today=row["sessions_today"],
            session_day=row["session_day"],
            sub_plan=row["sub_plan"],
            sub_until=_parse(row["sub_until"]),
            banned=bool(row["banned"]),
            created_at=_parse(row["created_at"]),
        )

    def set_lang(self, user_id: int, lang: str) -> None:
        self.driver.execute("UPDATE users SET lang = ? WHERE user_id = ?", (lang, user_id))

    def set_banned(self, user_id: int, banned: bool) -> None:
        self.driver.execute("UPDATE users SET banned = ? WHERE user_id = ?", (int(banned), user_id))

    # ---------------- сесії / запити ----------------
    def consume_session(self, user_id: int, daily_limit: int) -> bool:
        """Списати одну сесію. False — денний ліміт вичерпано."""
        today = date.today().isoformat()
        rows = self.driver.query(
            "SELECT sessions_today, session_day FROM users WHERE user_id = ?", (user_id,)
        )
        if not rows:
            return False
        row = rows[0]
        used = row["sessions_today"] if row["session_day"] == today else 0
        if used >= daily_limit:
            return False
        self.driver.execute(
            "UPDATE users SET sessions_today = ?, session_day = ?, "
            "requests_used = requests_used + 1 WHERE user_id = ?",
            (used + 1, today, user_id),
        )
        return True

    def log_request(self, user_id: int, asset: str, timeframe: int, direction: str) -> None:
        self.driver.execute(
            "INSERT INTO requests (user_id, ts, asset, timeframe, direction) VALUES (?, ?, ?, ?, ?)",
            (user_id, _iso(now()), asset, timeframe, direction),
        )

    # ---------------- підписки ----------------
    def grant_sub(self, user_id: int, plan: str, days: int, admin_id: int) -> datetime:
        user = self.get_user(user_id)
        base = user.sub_until if user and user.sub_until and user.sub_until > now() else now()
        until = base + timedelta(days=days)
        self.driver.execute(
            "UPDATE users SET sub_plan = ?, sub_until = ? WHERE user_id = ?",
            (plan, _iso(until), user_id),
        )
        self.driver.execute(
            "INSERT INTO sub_log (user_id, admin_id, action, plan, days, ts) "
            "VALUES (?, ?, 'grant', ?, ?, ?)",
            (user_id, admin_id, plan, days, _iso(now())),
        )
        return until

    def revoke_sub(self, user_id: int, admin_id: int) -> None:
        self.driver.execute(
            "UPDATE users SET sub_plan = NULL, sub_until = NULL WHERE user_id = ?", (user_id,)
        )
        self.driver.execute(
            "INSERT INTO sub_log (user_id, admin_id, action, ts) VALUES (?, ?, 'revoke', ?)",
            (user_id, admin_id, _iso(now())),
        )

    def reset_today(self, user_id: int) -> None:
        self.driver.execute(
            "UPDATE users SET sessions_today = 0, session_day = NULL WHERE user_id = ?", (user_id,)
        )

    # ---------------- адмінка ----------------
    def list_users(self, offset: int = 0, limit: int = 8, search: str = "") -> list[User]:
        if search:
            like = f"%{search.lstrip('@').lower()}%"
            rows = self.driver.query(
                """SELECT * FROM users
                    WHERE lower(COALESCE(username, '')) LIKE ?
                       OR lower(COALESCE(first_name, '')) LIKE ?
                       OR CAST(user_id AS TEXT) LIKE ?
                    ORDER BY last_seen_at DESC LIMIT ? OFFSET ?""",
                (like, like, like, limit, offset),
            )
        else:
            rows = self.driver.query(
                "SELECT * FROM users ORDER BY last_seen_at DESC LIMIT ? OFFSET ?", (limit, offset)
            )
        return [self._row_to_user(row) for row in rows]

    def count_users(self, search: str = "") -> int:
        if search:
            like = f"%{search.lstrip('@').lower()}%"
            rows = self.driver.query(
                """SELECT COUNT(*) AS n FROM users
                    WHERE lower(COALESCE(username, '')) LIKE ?
                       OR lower(COALESCE(first_name, '')) LIKE ?
                       OR CAST(user_id AS TEXT) LIKE ?""",
                (like, like, like),
            )
        else:
            rows = self.driver.query("SELECT COUNT(*) AS n FROM users")
        return int(rows[0]["n"])

    def stats(self) -> dict[str, int]:
        one_day = _iso(now() - timedelta(days=1))
        one = lambda sql, params=(): int(self.driver.query(sql, params)[0]["n"])  # noqa: E731
        return {
            "users": one("SELECT COUNT(*) AS n FROM users"),
            "active_subs": one("SELECT COUNT(*) AS n FROM users WHERE sub_until > ?", (_iso(now()),)),
            "requests": one("SELECT COUNT(*) AS n FROM requests"),
            "requests_24h": one("SELECT COUNT(*) AS n FROM requests WHERE ts > ?", (one_day,)),
            "new_24h": one("SELECT COUNT(*) AS n FROM users WHERE created_at > ?", (one_day,)),
        }

    # ---------------- settings ----------------
    def get_setting(self, key: str, default: str = "") -> str:
        rows = self.driver.query("SELECT value FROM settings WHERE key = ?", (key,))
        return rows[0]["value"] if rows else default

    def set_setting(self, key: str, value: str) -> None:
        self.driver.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
