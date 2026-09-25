"""Тести ядра без мережі й без Telegram: БД, підписки, сигнали, рендер, i18n.

Запуск:  python scripts/test_core.py
"""
from __future__ import annotations

import asyncio
import sqlite3
import sys
import tempfile
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.chart import render_signal
from core.db import Database, _PostgresDriver, is_postgres_dsn, now
from core.i18n import LANGS, TEXTS, t
from core.signals import analyze, ema, pick_best, rsi
from data.market import Candle, SimulatedSource
from data.pocket import PocketCredentials, PocketUnavailable, _to_candles

PASSED = 0
FAILED: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    global PASSED
    if condition:
        PASSED += 1
        print(f"  ok  {name}")
    else:
        FAILED.append(f"{name} {detail}".strip())
        print(f"  FAIL {name} {detail}")


def trend_candles(direction: int, count: int = 80) -> list[Candle]:
    """Чистий тренд зі зростаючим обсягом — сигнал мусить знайтись."""
    price = 1.1000
    out = []
    for index in range(count):
        step = 0.0004 * direction
        open_ = price
        close = price + step
        high = max(open_, close) + 0.00008
        low = min(open_, close) - 0.00008
        out.append(Candle(ts=1758000000 + index * 60, open=open_, high=high, low=low, close=close,
                          volume=40 + index))
        price = close
    return out


def flat_candles(count: int = 80) -> list[Candle]:
    out = []
    for index in range(count):
        base = 1.1000 + (0.00005 if index % 2 else -0.00005)
        out.append(Candle(ts=1758000000 + index * 60, open=1.1000, high=base + 0.00006,
                          low=base - 0.00006, close=base, volume=30))
    return out


def test_db() -> None:
    print("\n[db]")
    with tempfile.TemporaryDirectory() as tmp:
        db = Database(Path(tmp) / "t.db")
        user = db.upsert_user(1, "fckurslv", "Vit")
        check("створення юзера", user.user_id == 1 and user.lang == "uk")
        check("підписки нема", not user.sub_active)
        check("сесії повні", user.sessions_left(3) == 3)

        check("без підписки сесія все одно списується двигуном", db.consume_session(1, 3))
        db.log_request(1, "EURUSD_otc", 60, "BUY")
        user = db.get_user(1)
        check("лічильник запитів", user.requests_used == 1, str(user.requests_used))
        check("сесій лишилось 2", user.sessions_left(3) == 2)

        db.consume_session(1, 3)
        db.consume_session(1, 3)
        check("четверта сесія відбита лімітом", not db.consume_session(1, 3))
        db.reset_today(1)
        check("обнулення сесій адміном", db.get_user(1).sessions_left(3) == 3)

        until = db.grant_sub(1, "VIP", 30, admin_id=99)
        user = db.get_user(1)
        check("підписка активна", user.sub_active and user.sub_plan == "VIP")
        check("строк ~30 днів", timedelta(days=29) < until - now() < timedelta(days=31))

        until2 = db.grant_sub(1, "VIP", 7, admin_id=99)
        check("продовження додає поверх наявної", until2 > until)

        db.revoke_sub(1, admin_id=99)
        check("зняття підписки", not db.get_user(1).sub_active)

        db.upsert_user(2, "friend", "Друг")
        check("пошук за ніком", [u.user_id for u in db.list_users(search="friend")] == [2])
        check("пошук за id", [u.user_id for u in db.list_users(search="1")] == [1])
        stats = db.stats()
        check("статистика", stats["users"] == 2 and stats["requests"] == 1, str(stats))

        db.set_setting("po_ssid", "abc")
        check("settings", db.get_setting("po_ssid") == "abc")
        db.set_setting("po_ssid", "def")
        check("settings перезапис", db.get_setting("po_ssid") == "def")
        check("двигун — sqlite", db.engine == "sqlite", db.engine)
        db.close()

    print("\n[postgres-переклад]")
    check("? -> %s", _PostgresDriver._translate("SELECT * FROM t WHERE a = ? AND b = ?")
          == "SELECT * FROM t WHERE a = %s AND b = %s")
    check("DSN postgres", is_postgres_dsn("postgres://u:p@h/db") and is_postgres_dsn("postgresql://x"))
    check("шлях — не DSN", not is_postgres_dsn("runtime/bot.db"))


def test_99_and_migration() -> None:
    print("\n[99 signal + міграція]")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "old.db"
        # база, створена версією бота ДО появи 99 Signal
        old = sqlite3.connect(path)
        old.executescript(
            """CREATE TABLE users (
                   user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT,
                   lang TEXT NOT NULL DEFAULT 'uk', created_at TEXT NOT NULL,
                   last_seen_at TEXT NOT NULL, requests_used INTEGER NOT NULL DEFAULT 0,
                   sessions_today INTEGER NOT NULL DEFAULT 0, session_day TEXT,
                   sub_plan TEXT, sub_until TEXT, banned INTEGER NOT NULL DEFAULT 0);
               INSERT INTO users (user_id, created_at, last_seen_at)
                    VALUES (5, '2026-09-01T00:00:00+00:00', '2026-09-01T00:00:00+00:00');"""
        )
        old.commit()
        old.close()

        db = Database(path)
        user = db.get_user(5)
        check("стара база читається після міграції", user is not None and user.last_99_day is None)
        check("старий юзер не втратився", user.user_id == 5)

        check("перший 99 Signal за добу видається", db.consume_99(5))
        check("другий за ту саму добу — ні", not db.consume_99(5))
        user = db.get_user(5)
        check("позначка на сьогодні стоїть", user.has_99_today)
        check("99 теж рахується у «запитів з'їдено»", user.requests_used == 1)

        db.reset_today(5)
        check("адмінський ресет знімає і 99", not db.get_user(5).has_99_today)
        check("після ресету 99 знову доступний", db.consume_99(5))
        db.close()


def test_signals() -> None:
    print("\n[signals]")
    check("ema рахує", abs(ema([1.0] * 10, 5)[-1] - 1.0) < 1e-9)
    check("rsi росту = 100", rsi([1.0 + i * 0.1 for i in range(30)]) > 95)
    check("rsi падіння < 5", rsi([5.0 - i * 0.1 for i in range(30)]) < 5)

    up = analyze(trend_candles(1))
    check("тренд вгору -> BUY", up is not None and up.direction == "BUY", str(up))
    check("є причини входу", up is not None and 1 <= len(up.reasons) <= 3)
    check("причини — відомі ключі i18n", all(key in TEXTS["uk"] for key, _ in up.reasons))

    down = analyze(trend_candles(-1))
    check("тренд вниз -> SELL", down is not None and down.direction == "SELL", str(down))

    check("боковик -> сигналу немає", analyze(flat_candles()) is None)
    check("мало свічок -> None", analyze(trend_candles(1, 20)) is None)

    best = pick_best({"A": flat_candles(), "B": trend_candles(1)}, {"A": 5, "B": 5})
    check("pick_best бере актив із сигналом", best is not None and best[0] == "B")
    check("pick_best на пустому — None", pick_best({"A": flat_candles()}, {"A": 5}) is None)
    check("якість у межах 1..99", up is not None and 1 <= up.quality <= 99, str(up and up.quality))


def test_po_cookies() -> None:
    print("\n[po cookies]")
    from data.po_session import looks_like_cookies, parse_cookies

    editor = '[{"domain":".pocketoption.com","name":"PHPSESSID","value":"abc"},' \
             '{"domain":".google.com","name":"_ga","value":"x"}]'
    check("Cookie-Editor JSON", [c["name"] for c in parse_cookies(editor)] == ["PHPSESSID"])
    netscape = "# Netscape\n#HttpOnly_.pocketoption.com\tTRUE\t/\tTRUE\t0\tautologin\tzzz\n"
    check("cookies.txt", parse_cookies(netscape)[0]["name"] == "autologin")
    check("рядок a=b; c=d", len(parse_cookies("a=1; b=2")) == 2)
    check("cookies розпізнано", looks_like_cookies(editor) and looks_like_cookies("a=1; b=2"))
    check("кадр auth — не cookies", not looks_like_cookies('42["auth",{"session":"x"}]'))
    check("голий SSID — не cookies", not looks_like_cookies("9ocbmdgd25ek1hs25i06l7ttct"))
    backup = '{"url":"https://www.hotcleaner.com/x","version":2,"data":"QRP+/=a;b"}'
    check("бекап Cookie-Editor йде в розбір cookies", looks_like_cookies(backup))
    try:
        parse_cookies(backup)
        check("зашифрований бекап відбито з поясненням", False)
    except PocketUnavailable as exc:
        check("зашифрований бекап відбито з поясненням", "зашифрований" in str(exc) and "QRP" not in str(exc))
    try:
        parse_cookies('[{"domain":".google.com","name":"_ga","value":"x"}]')
        check("чужий домен відбито", False)
    except PocketUnavailable:
        check("чужий домен відбито", True)


def test_99_queue() -> None:
    """99 Signal видає аналітик: черга, один запит на добу, двічі не закривається."""
    print("\n[99 черга]")
    with tempfile.TemporaryDirectory() as tmp:
        db = Database(Path(tmp) / "q.db")
        db.upsert_user(7, "u", "U")
        rid = db.request_99(7)
        check("запит став у чергу", rid is not None and db.pending_99(7)["id"] == rid)
        check("другий запит за добу не створюється", db.request_99(7) is None)
        check("черга видна адміну", [r["id"] for r in db.list_99_pending()] == [rid])
        check("stats рахує чергу", db.stats()["queue"] == 1)
        check("закриття sent", db.close_99(rid, "sent", 1, "EURUSD_otc", "BUY", 300))
        check("повторне закриття відбито", not db.close_99(rid, "sent", 2, "EURUSD_otc", "SELL", 60))
        check("черга порожня", db.list_99_pending() == [] and db.pending_99(7) is None)
        check("збережено актив і напрямок", db.get_99(rid)["direction"] == "BUY")
        db.reset_99(7)
        rid2 = db.request_99(7)
        check("після відмови/ресету можна знову", rid2 is not None and rid2 != rid)
        db.close()


def test_admin_card() -> None:
    """Картка юзера в адмінці — з неї видається підписка; падала на подвійному lang."""
    print("\n[admin]")
    from types import SimpleNamespace

    from bot import admin

    with tempfile.TemporaryDirectory() as tmp:
        db = Database(Path(tmp) / "a.db")
        db.upsert_user(1, "boss", "Boss")
        db.upsert_user(2, None, "Вася <3 & co")
        db.set_lang(2, "ru")
        admin.app = SimpleNamespace(config=SimpleNamespace(admin_ids={1}, daily_sessions=3), db=db)
        for lang in LANGS:
            text, markup = admin._user_card(lang, 2)
            grants = [b.callback_data for row in markup.inline_keyboard for b in row
                      if (b.callback_data or "").startswith("adm:grant:2:")]
            check(f"картка юзера відкривається ({lang})", "ru" in text and len(grants) == 3)
            check(f"HTML з імені екранується ({lang})", "&lt;3 &amp; co" in text, text)
        admin.app = None
        db.close()


def test_chart() -> None:
    print("\n[chart]")
    png = render_signal(trend_candles(1), asset_title="EUR/USD OTC", direction="BUY",
                        timeframe_label="M1", digits=5, demo=True)
    check("png віддається", png[:8] == b"\x89PNG\r\n\x1a\n")
    check("розмір адекватний", 20_000 < len(png) < 2_000_000, f"{len(png)} байт")
    Path("runtime").mkdir(exist_ok=True)
    Path("runtime/sample_signal.png").write_bytes(png)


def test_i18n() -> None:
    print("\n[i18n]")
    keys_uk = set(TEXTS["uk"])
    for lang in LANGS:
        check(f"{lang}: ключі збігаються", set(TEXTS[lang]) == keys_uk,
              str(keys_uk.symmetric_difference(TEXTS[lang])))
    check("підстановка", "SARAT" in t("ru", "welcome_title", bot_name="SARAT"))
    check("невідома мова -> дефолт", t("en", "btn_back") == TEXTS["uk"]["btn_back"])


def test_market() -> None:
    print("\n[market]")
    source = SimulatedSource(seed=7)
    candles = asyncio.run(source.candles("EURUSD_otc", 60, 120))
    check("120 свічок", len(candles) == 120)
    check("час зростає", all(b.ts > a.ts for a, b in zip(candles, candles[1:])))
    check("high >= low", all(c.high >= c.low for c in candles))
    check("тіло всередині тіні", all(c.high >= max(c.open, c.close) and c.low <= min(c.open, c.close)
                                     for c in candles))
    check("бекенд позначений як не-реальний", source.real is False)


def test_pocket_parsing() -> None:
    print("\n[pocket]")
    raw = [{"time": 1758000060, "open": 1.1, "high": 1.2, "low": 1.0, "close": 1.15, "volume": 3},
           {"time": 1758000000, "open": 1.0, "high": 1.1, "low": 0.9, "close": 1.1}]
    candles = _to_candles(raw)
    check("парсинг свічок", len(candles) == 2)
    check("сортування за часом", candles[0].ts < candles[1].ts)
    check("volume за замовчуванням 0", candles[1].volume == 3.0)
    check("сміття -> порожньо", _to_candles({"nope": 1}) == [])

    creds = PocketCredentials.parse('42["auth",{"session":"a:4:{x}","isDemo":1,"uid":7,"platform":2}]')
    check("SSID із цілого кадру 42[auth,...]", creds.session.startswith("a:4:") and creds.uid == 7)
    check("торгова сесія розпізнається", creds.looks_like_trading_session)
    check("чатовий токен — не торгова сесія",
          not PocketCredentials.parse('{"sessionToken":"2aff7e6d","uid":1}').looks_like_trading_session)
    check("sessionToken теж читається",
          PocketCredentials.parse('{"sessionToken":"abc","uid":1}').session == "abc")

    creds = PocketCredentials.parse('{"session":"abc","isDemo":1,"uid":42,"platform":2}')
    check("SSID з JSON", creds.session == "abc" and creds.uid == 42 and creds.is_demo)
    check("голий SSID", PocketCredentials.parse("plain").session == "plain")
    try:
        PocketCredentials.parse("   ")
        check("порожній SSID падає", False)
    except PocketUnavailable:
        check("порожній SSID падає", True)


if __name__ == "__main__":
    test_db()
    test_99_and_migration()
    test_signals()
    test_99_queue()
    test_po_cookies()
    test_admin_card()
    test_chart()
    test_i18n()
    test_market()
    test_pocket_parsing()
    print(f"\n{PASSED} ok, {len(FAILED)} fail")
    for item in FAILED:
        print("  -", item)
    sys.exit(1 if FAILED else 0)
