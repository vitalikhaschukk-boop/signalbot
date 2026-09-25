"""Перевірка автооновлення ключа Pocket Option на справжніх cookies — БЕЗ виводу секретів.

Запуск:  python scripts/po_cookie_check.py C:\\шлях\\до\\cookies.json

Друкує лише назви cookies, звідки взявся ключ (без значення), його довжину
і чи віддав брокер свічки на свіжий ключ. Якщо ключ на сторінці не знайдено —
показує оточення слів session/uid, де всі довгі значення замасковано.
"""
from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from data import po_session  # noqa: E402
from data.pocket import PocketSource, PocketUnavailable  # noqa: E402

MASK = re.compile(r"[A-Za-z0-9_\-]{10,}")


async def main(path: str) -> int:
    raw = Path(path).read_text(encoding="utf-8", errors="replace")
    try:
        cookies = po_session.parse_cookies(raw)
    except PocketUnavailable as exc:
        print("❌ cookies не розібрав:", exc)
        return 1
    print(f"cookies: {len(cookies)} шт. —", ", ".join(sorted(c["name"] for c in cookies)))

    try:
        result = await po_session.refresh(cookies)
    except PocketUnavailable as exc:
        print("❌ оновлення ключа:", exc)
        await _masked_hints(cookies)
        return 1
    for note in result.notes:
        print("  ", note)

    source = PocketSource(refresher=_fixed(result.credentials))
    try:
        candles = await source.candles("EURUSD_otc", 60, count=30)
        print(f"✅ брокер прийняв ключ: EUR/USD OTC — {len(candles)} свічок, остання ціна {candles[-1].close}")
        return 0
    except PocketUnavailable as exc:
        print("❌ брокер ключ не прийняв:", exc)
        return 1
    finally:
        await source.close()


def _fixed(credentials):
    async def get():
        return credentials
    return get


async def _masked_hints(cookies: list[dict]) -> None:
    """Оточення session/uid на сторінці терміналу, значення замасковані."""
    import aiohttp
    from yarl import URL

    jar = aiohttp.CookieJar()
    for cookie in cookies:
        jar.update_cookies({cookie["name"]: cookie["value"]}, URL("https://pocketoption.com/"))
    try:
        async with aiohttp.ClientSession(cookie_jar=jar) as http:
            async with http.get(po_session.TERMINAL_URL, headers={"User-Agent": po_session.HEADERS["User-Agent"]}) as r:
                html = await r.text(errors="replace")
                print(f"   сторінка: HTTP {r.status} {r.url.path}, {len(html)} символів")
    except Exception as exc:  # noqa: BLE001
        print("   сторінку не відкрив:", exc)
        return
    shown = 0
    for match in re.finditer(r"session|uid", html, re.IGNORECASE):
        snippet = html[max(0, match.start() - 40): match.end() + 40].replace("\n", " ")
        print("   …", MASK.sub(lambda m: f"<{len(m.group())}>", snippet), "…")
        shown += 1
        if shown >= 15:
            break
    print("   назви cookies після візиту:", ", ".join(sorted({c.key for c in jar})))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    sys.exit(asyncio.run(main(sys.argv[1])))
