"""Автооновлення ключа Pocket Option через cookies сайту.

Ключ сокета (`session`, 26 символів) живе кілька днів. Сайт при цьому не вилогінює:
браузер показує довгу cookie «запам'ятати мене», і сайт мовчки видає нову сесію.
Бот робить те саме — відкриває сторінку демо-термінала з cookies, забирає свіжий
`session` + `uid` і зберігає оновлені cookies, щоб довга не старіла.

Секрети ніде не логуються: у логах і діагностиці лише назви й довжини.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field

from data.pocket import HEADERS, PocketCredentials, PocketUnavailable

log = logging.getLogger("signalbot.po_session")

TERMINAL_URL = "https://pocketoption.com/en/cabinet/demo-quick-high-low/"
SITE_DOMAIN = "pocketoption.com"
PLATFORM = 9  # так підписується веб-термінал (звірено з кадром auth 2026-09-22)

# де сторінка терміналу може віддати ключ сокета; перший збіг перемагає
SESSION_PATTERNS = (
    ("json_session", re.compile(r'"session"\s*:\s*"([A-Za-z0-9]{16,64})"')),
    ("js_session", re.compile(r"\bsession\s*[:=]\s*['\"]([A-Za-z0-9]{16,64})['\"]")),
)
UID_PATTERNS = (
    re.compile(r'"uid"\s*:\s*"?(\d{4,})'),
    re.compile(r"\buid\s*[:=]\s*['\"]?(\d{4,})"),
    re.compile(r'"user_id"\s*:\s*"?(\d{4,})'),
)
SESSION_COOKIES = ("PHPSESSID", "ci_session", "session")
COOKIE_NAME = re.compile(r"[A-Za-z0-9_.\-]{1,64}")  # усе інше — не назва cookie, а сміття


@dataclass(slots=True)
class RefreshResult:
    credentials: PocketCredentials
    cookies: list[dict]
    source: str  # звідки взято ключ — для діагностики, без значень
    notes: list[str] = field(default_factory=list)


def parse_cookies(raw: str) -> list[dict]:
    """Приймає експорт Cookie-Editor (JSON), cookies.txt (Netscape) або рядок `a=b; c=d`."""
    raw = raw.strip().lstrip("﻿")
    if not raw:
        raise PocketUnavailable("порожні cookies")
    if raw.startswith("{"):
        if '"version"' in raw and '"data"' in raw:
            raise PocketUnavailable(
                "це зашифрований бекап Cookie-Editor, а не cookies — потрібен Export → JSON без пароля"
            )
        raise PocketUnavailable("очікував список cookies у форматі JSON, а прийшов один обʼєкт")
    if raw.startswith("["):
        try:
            items = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise PocketUnavailable(f"cookies не схожі на JSON: {exc}") from exc
        out = [
            {"name": str(c["name"]), "value": str(c.get("value", "")),
             "domain": str(c.get("domain") or SITE_DOMAIN)}
            for c in items
            if isinstance(c, dict) and c.get("name")
        ]
    elif "\t" in raw:
        out = []
        for line in raw.splitlines():
            if line.startswith("#HttpOnly_"):
                line = line[len("#HttpOnly_"):]
            elif line.startswith("#") or not line.strip():
                continue
            parts = line.split("\t")
            if len(parts) >= 7:
                out.append({"name": parts[5], "value": parts[6], "domain": parts[0]})
    else:
        out = []
        for chunk in raw.split(";"):
            if "=" in chunk:
                name, value = chunk.split("=", 1)
                out.append({"name": name.strip(), "value": value.strip(), "domain": SITE_DOMAIN})
    out = [
        c for c in out
        if ("pocketoption" in c["domain"] or "po.market" in c["domain"]) and COOKIE_NAME.fullmatch(c["name"])
    ]
    if not out:
        raise PocketUnavailable("серед cookies нема жодної від pocketoption.com")
    return out


def masked_hints(html: str, limit: int = 4) -> str:
    """Оточення слова session на сторінці, всі довгі значення замінено на <довжину>."""
    mask = re.compile(r"[A-Za-z0-9_\-+/=]{10,}")
    out = []
    for match in re.finditer(r"session", html, re.IGNORECASE):
        snippet = html[max(0, match.start() - 30): match.end() + 30].replace("\n", " ")
        out.append(mask.sub(lambda m: f"<{len(m.group())}>", snippet))
        if len(out) >= limit:
            break
    return " | ".join(out) or "ніде"


def looks_like_cookies(raw: str) -> bool:
    raw = raw.strip().lstrip("﻿")
    if raw.startswith("42["):
        return False
    if raw.startswith("{"):  # зашифрований бекап Cookie-Editor — хай parse_cookies скаже, що не так
        return '"version"' in raw and '"data"' in raw
    return raw.startswith("[") or "\t" in raw or ("=" in raw and ";" in raw)


async def refresh(cookies: list[dict], timeout: float = 20.0) -> RefreshResult:
    """Відкрити термінал з cookies і дістати свіжий ключ сокета."""
    import aiohttp
    from yarl import URL

    jar = aiohttp.CookieJar()
    base = URL(f"https://{SITE_DOMAIN}/")
    for cookie in cookies:
        jar.update_cookies({cookie["name"]: cookie["value"]}, base)

    headers = {
        "User-Agent": HEADERS["User-Agent"],
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    notes: list[str] = []
    try:
        async with aiohttp.ClientSession(cookie_jar=jar, timeout=aiohttp.ClientTimeout(total=timeout)) as http:
            async with http.get(TERMINAL_URL, headers=headers, allow_redirects=True) as response:
                html = await response.text(errors="replace")
                final_path = response.url.path
                status = response.status
            fresh = {c.key: c.value for c in jar if SITE_DOMAIN in (c["domain"] or SITE_DOMAIN)}
    except Exception as exc:  # noqa: BLE001 - мережа, TLS, блок
        raise PocketUnavailable(f"сайт Pocket Option не відповів: {type(exc).__name__} {exc}") from exc

    notes.append(f"HTTP {status}, сторінка {final_path}, розмір {len(html)}")
    if "login" in final_path or "sign" in final_path:
        raise PocketUnavailable("cookies більше не залогінені — сайт кинув на вхід")

    session, source = "", ""
    for name, pattern in SESSION_PATTERNS:
        match = pattern.search(html)
        if match:
            session, source = match.group(1), name
            break
    if not session:
        for name in SESSION_COOKIES:
            if fresh.get(name):
                session, source = fresh[name], f"cookie:{name}"
                break
    if not session:
        raise PocketUnavailable(
            f"на сторінці терміналу не знайшов ключа сесії ({notes[0]}; cookies: {', '.join(sorted(fresh))}). "
            f"Де згадується session: {masked_hints(html)}"
        )

    uid = 0
    for pattern in UID_PATTERNS:
        match = pattern.search(html)
        if match:
            uid = int(match.group(1))
            break
    notes.append(f"ключ: {source}, довжина {len(session)}; uid {'знайдено' if uid else 'НЕ знайдено'}")

    merged = {c["name"]: dict(c) for c in cookies}
    for name, value in fresh.items():
        merged.setdefault(name, {"name": name, "domain": SITE_DOMAIN})["value"] = value
    credentials = PocketCredentials(session=session, uid=uid, is_demo=True, platform=PLATFORM)
    return RefreshResult(credentials=credentials, cookies=list(merged.values()), source=source, notes=notes)
