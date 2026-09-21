"""Реальні свічки Pocket Option через неофіційний SDK `pocket-option`.

Як це працює: власник заходить у СВІЙ ДЕМО-акаунт Pocket Option у браузері,
звідти дістається кадр авторизації websocket (SSID) — і бот слухає ті самі
ціни, що бачить трейдер у терміналі. Ключ живе в БД (`po_ssid`) і міняється
командою в адмінці, коли протухне.

Офіційного API в Pocket Option немає, тож цей шар свідомо:
  * тільки ЧИТАЄ котирування, жодних угод з коду;
  * ходить від демо-акаунта, щоб не тягнути під ToS-ризик реальний рахунок;
  * при будь-якій помилці віддає порожньо, а бот каже юзеру «немає зв'язку»
    і НЕ списує сесію.

Протокол звірено живцем 2026-09-21: socket.io v4 на wss://demo-api-eu.po.market,
кадр `42["auth",{...}]`, історія приходить подією `load_history_period_fast`.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass

from data.market import ASSETS, Asset, Candle

log = logging.getLogger("signalbot.pocket")

# без браузерних заголовків анти-DDoS перед брокером рве рукостискання
HEADERS = {
    "Origin": "https://pocketoption.com",
    "Referer": "https://pocketoption.com/",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
    ),
}

AUTH_TIMEOUT = 15.0
HISTORY_TIMEOUT = 15.0


class PocketUnavailable(RuntimeError):
    """SDK не встановлено, немає SSID або біржа не відповідає."""


@dataclass(slots=True)
class PocketCredentials:
    session: str
    uid: int = 0
    is_demo: bool = True
    platform: int = 2

    @classmethod
    def parse(cls, raw: str) -> "PocketCredentials":
        """SSID копіюють по-різному: або голий рядок, або цілий JSON з кадру auth."""
        raw = raw.strip()
        if not raw:
            raise PocketUnavailable("порожній SSID")
        if raw.startswith("42["):  # цілий кадр із DevTools — витягнемо об'єкт
            try:
                raw = json.dumps(json.loads(raw[2:])[1])
            except (ValueError, IndexError) as exc:
                raise PocketUnavailable(f"не розібрав кадр auth: {exc}") from exc
        if raw.startswith("{"):
            try:
                data = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise PocketUnavailable(f"SSID не схожий на JSON: {exc}") from exc
            session = data.get("session") or data.get("ssid") or data.get("sessionToken") or ""
            return cls(
                session=str(session),
                uid=int(data.get("uid") or 0),
                is_demo=bool(int(data.get("isDemo", 1))),
                platform=int(data.get("platform", 2)),
            )
        return cls(session=raw)

    @property
    def looks_like_trading_session(self) -> bool:
        """Торгова сесія — серіалізований PHP-рядок, а не 32-символьний токен чату."""
        return self.session.startswith("a:")


class PocketSource:
    """Адаптер поверх `pocket_option.PocketOptionClient`.

    Тримає одне з'єднання на весь процес і кешує свічки на кілька секунд —
    юзерів мало, а зайвий трафік на брокера тут нікому не потрібен.
    """

    name = "pocket"
    real = True

    def __init__(self, ssid: str, cache_ttl: float = 5.0) -> None:
        self.credentials = PocketCredentials.parse(ssid)
        self.cache_ttl = cache_ttl
        self._client = None
        self._lock = asyncio.Lock()
        self._cache: dict[tuple[str, int], tuple[float, list[Candle]]] = {}
        self._waiters: dict[tuple[str, int], asyncio.Future] = {}

    # ---------------------------------------------------------------- connect
    async def _ensure_client(self):
        if self._client is not None:
            return self._client
        try:
            from pocket_option import PocketOptionClient  # type: ignore import-not-found
            from pocket_option.constants import Regions  # type: ignore import-not-found
            from pocket_option.models import AuthorizationData  # type: ignore import-not-found
        except ImportError as exc:  # pragma: no cover - залежить від оточення
            raise PocketUnavailable(
                "пакет pocket-option не встановлено (pip install pocket-option, Python 3.13+)"
            ) from exc

        client = PocketOptionClient(reconnection=True, reconnection_attempts=0)
        authed: asyncio.Future = asyncio.get_running_loop().create_future()

        @client.on.success_auth
        async def _on_auth(_event) -> None:  # noqa: ANN001
            if not authed.done():
                authed.set_result(True)

        @client.on.load_history_period_fast
        async def _on_history(event) -> None:  # noqa: ANN001
            key = (getattr(event.asset, "name", str(event.asset)), int(event.period))
            waiter = self._waiters.pop(key, None)
            if waiter is not None and not waiter.done():
                waiter.set_result(event)

        @client.on.disconnect
        async def _on_disconnect(*_args) -> None:  # noqa: ANN002
            log.warning("Pocket Option розірвав з'єднання — перепідключусь на наступному запиті")
            self._client = None

        auth = AuthorizationData(
            session=self.credentials.session,
            is_demo=1 if self.credentials.is_demo else 0,
            uid=self.credentials.uid,
            platform=self.credentials.platform,
            is_fast_history=True,
            is_optimized=True,
        )
        url = Regions.DEMO if self.credentials.is_demo else Regions.EUROPA

        try:
            # socket.io серіалізує auth сам, тому віддаємо звичайний словник
            await client.connect(url, headers=HEADERS, auth=auth.model_dump(by_alias=True))
        except Exception as exc:  # noqa: BLE001 - SDK кидає свої класи помилок
            raise PocketUnavailable(f"не під'єднався до {url}: {exc}") from exc

        try:
            await asyncio.wait_for(authed, timeout=AUTH_TIMEOUT)
        except asyncio.TimeoutError as exc:
            await self._close_client(client)
            hint = (
                ""
                if self.credentials.looks_like_trading_session
                else " (схоже, це ключ чату/графіка, а не торгового сокета — "
                "потрібен кадр auth зі з'єднання з api-eu.po.market, там session починається з a:)"
            )
            raise PocketUnavailable(f"сесію не прийнято за {AUTH_TIMEOUT:.0f}с{hint}") from exc

        self._client = client
        log.info("Pocket Option: авторизовано, demo=%s", self.credentials.is_demo)
        return client

    # ------------------------------------------------------------------ data
    async def assets(self) -> list[Asset]:
        # Список тримаємо свій: нам потрібні конкретні пари, а не весь каталог брокера.
        return list(ASSETS)

    async def candles(self, symbol: str, timeframe: int, count: int = 120) -> list[Candle]:
        cached = self._cache.get((symbol, timeframe))
        if cached and time.time() - cached[0] < self.cache_ttl:
            return cached[1]

        async with self._lock:
            cached = self._cache.get((symbol, timeframe))
            if cached and time.time() - cached[0] < self.cache_ttl:
                return cached[1]

            client = await self._ensure_client()
            from pocket_option.models import (  # type: ignore import-not-found
                Asset as SdkAsset,
                LoadHistoryPeriodRequest,
            )

            sdk_asset = getattr(SdkAsset, symbol, None)
            if sdk_asset is None:
                raise PocketUnavailable(f"актив {symbol} не відомий SDK")

            key = (symbol, timeframe)
            waiter: asyncio.Future = asyncio.get_running_loop().create_future()
            self._waiters[key] = waiter
            try:
                client.emit.load_history_period(
                    LoadHistoryPeriodRequest(
                        asset=sdk_asset,
                        index=None,
                        time=float(int(time.time())),
                        offset=timeframe * count,
                        period=timeframe,
                    )
                )
                event = await asyncio.wait_for(waiter, timeout=HISTORY_TIMEOUT)
            except asyncio.TimeoutError as exc:
                self._waiters.pop(key, None)
                raise PocketUnavailable(f"історія {symbol} не приїхала за {HISTORY_TIMEOUT:.0f}с") from exc
            except Exception as exc:  # noqa: BLE001
                self._waiters.pop(key, None)
                raise PocketUnavailable(f"помилка Pocket Option: {exc}") from exc

            candles = _to_candles(event)
            if not candles:
                raise PocketUnavailable(f"Pocket Option повернув порожню історію по {symbol}")
            self._cache[key] = (time.time(), candles)
            return candles

    async def close(self) -> None:
        client, self._client = self._client, None
        await self._close_client(client)

    @staticmethod
    async def _close_client(client) -> None:  # noqa: ANN001
        if client is None:
            return
        for method in ("disconnect", "close"):
            handler = getattr(client, method, None)
            if handler is None:
                continue
            try:
                result = handler()
                if asyncio.iscoroutine(result):
                    await result
            except Exception as exc:  # noqa: BLE001
                log.debug("не зміг закрити з'єднання: %s", exc)
            return


def _to_candles(raw: object) -> list[Candle]:
    """Нормалізувати відповідь SDK у наші свічки.

    Приймає і подію SDK (у неї свічки лежать у `.data`), і сирий список
    словників — щоб шар не ламався, якщо бібліотека змінить обгортку.
    """
    items = raw
    for attribute in ("data", "candles", "history"):
        if hasattr(items, attribute):
            items = getattr(items, attribute)
            break
    if isinstance(items, dict):
        items = items.get("candles") or items.get("data") or []
    if not isinstance(items, (list, tuple)):
        return []

    out: list[Candle] = []
    for item in items:
        get = item.get if isinstance(item, dict) else lambda key, default=None: getattr(item, key, default)
        ts = get("time", get("ts", 0))
        open_ = get("open")
        high = get("high")
        low = get("low")
        close = get("close")
        if None in (open_, high, low, close):
            continue
        out.append(
            Candle(
                ts=int(float(ts)),
                open=float(open_),
                high=float(high),
                low=float(low),
                close=float(close),
                volume=float(get("volume", 0.0) or 0.0),
            )
        )
    out.sort(key=lambda candle: candle.ts)
    return out
