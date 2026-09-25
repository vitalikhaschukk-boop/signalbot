"""Реальні свічки Pocket Option — власний клієнт socket.io поверх websocket.

Офіційного API брокер не дає. Готовий SDK (`pocket-option`) ми пробували й
відмовились: він рве зʼєднання, не знає половини OTC-активів і чекає на події,
яких сервер не шле. Протокол простий, тож говоримо з ним самі — звірено
живцем 2026-09-21:

    <- 0{"sid":...}                  рукостискання engine.io
    -> 40                            відкрити namespace
    <- 40{"sid":...}
    -> 42["auth",{...}]              кадр з демо-термінала (поле session)
    -> 42["loadHistoryPeriod",{asset,index,time,offset,period}]
    <- 451-["loadHistoryPeriodFast",...] + бінарний кадр зі свічками
    <- 2  ->  3                      пінг/понг, інакше сервер відключить

Свідомі обмеження шару: тільки ЧИТАННЯ котирувань, жодних угод з коду,
і ходимо від ДЕМО-акаунта, щоб не тягнути реальний рахунок під ToS-ризик.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from dataclasses import dataclass
from typing import Awaitable, Callable

from data.market import ASSETS, Asset, Candle

log = logging.getLogger("signalbot.pocket")

DEMO_URL = "wss://demo-api-eu.po.market/socket.io/?transport=websocket&EIO=4"
REAL_URL = "wss://api-eu.po.market/socket.io/?transport=websocket&EIO=4"

# без браузерних заголовків анти-DDoS перед брокером рве рукостискання
HEADERS = {
    "Origin": "https://pocketoption.com",
    "Referer": "https://pocketoption.com/",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
    ),
}

CONNECT_TIMEOUT = 15.0
HISTORY_TIMEOUT = 15.0


class PocketUnavailable(RuntimeError):
    """Немає SSID, ключ протух або брокер не відповідає."""


@dataclass(slots=True)
class PocketCredentials:
    session: str
    uid: int = 0
    is_demo: bool = True
    platform: int = 2
    from_chart: bool = False  # ключ із сокета графіка/чату — торговий такий не пустить

    @classmethod
    def parse(cls, raw: str) -> "PocketCredentials":
        """Приймає і голий рядок, і JSON, і цілий кадр `42["auth",{...}]` з DevTools."""
        raw = raw.strip()
        if not raw:
            raise PocketUnavailable("порожній SSID")
        if raw.startswith("42["):
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
                from_chart=bool(data.get("sessionToken") and not data.get("session")),
            )
        return cls(session=raw)

    @property
    def looks_like_trading_session(self) -> bool:
        """У торгового кадру поле зветься `session`; у графіка — `sessionToken`."""
        return not self.from_chart and bool(self.session)

    def auth_payload(self) -> dict[str, object]:
        return {
            "session": self.session,
            "isDemo": 1 if self.is_demo else 0,
            "uid": self.uid,
            "platform": self.platform,
            "isFastHistory": True,
            "isOptimized": True,
        }


class PocketSource:
    """Одне живе зʼєднання на процес плюс короткий кеш свічок."""

    name = "pocket"
    real = True

    def __init__(
        self,
        ssid: str = "",
        cache_ttl: float = 5.0,
        refresher: Callable[[], Awaitable[PocketCredentials]] | None = None,
    ) -> None:
        if not ssid and refresher is None:
            raise PocketUnavailable("порожній SSID")
        self.credentials = PocketCredentials.parse(ssid) if ssid else None
        self.refresher = refresher  # дістає свіжий ключ через cookies сайту
        self.cache_ttl = cache_ttl
        self._session = None
        self._ws = None
        self._reader: asyncio.Task | None = None
        self._lock = asyncio.Lock()
        self._ready: asyncio.Future | None = None
        self._cache: dict[tuple[str, int], tuple[float, list[Candle]]] = {}
        self._waiters: dict[str, asyncio.Future] = {}

    # ---------------------------------------------------------------- connect
    async def _connect(self) -> None:
        """Підʼєднатись; якщо ключа нема або брокер його відкинув — оновити через cookies і ще раз."""
        refreshed = False
        if self.credentials is None:
            await self._refresh()
            refreshed = True
        try:
            await self._open()
        except PocketUnavailable as exc:
            if self.refresher is None or refreshed:
                raise
            log.info("Pocket Option: ключ не пройшов (%s) — оновлюю через cookies", exc)
            await self._refresh()
            await self._open()

    async def _refresh(self) -> None:
        assert self.refresher is not None
        self.credentials = await self.refresher()

    async def _open(self) -> None:
        import aiohttp

        await self._teardown()
        self._session = aiohttp.ClientSession()
        url = DEMO_URL if self.credentials.is_demo else REAL_URL
        try:
            self._ws = await self._session.ws_connect(url, headers=HEADERS, heartbeat=None)
        except Exception as exc:  # noqa: BLE001 - мережа, TLS, блокування
            await self._teardown()
            raise PocketUnavailable(f"не підʼєднався до {url}: {exc}") from exc

        self._ready = asyncio.get_running_loop().create_future()
        self._reader = asyncio.create_task(self._read_loop())
        try:
            await asyncio.wait_for(self._ready, timeout=CONNECT_TIMEOUT)
        except asyncio.TimeoutError as exc:
            await self._teardown()
            raise PocketUnavailable("брокер не відкрив канал за 15с") from exc
        except PocketUnavailable:
            await self._teardown()
            raise
        log.info("Pocket Option: зʼєднання відкрите (demo=%s)", self.credentials.is_demo)

    async def _read_loop(self) -> None:
        """Читає кадри, тримає пінг-понг і роздає відповіді тим, хто їх чекає."""
        import aiohttp

        pending_event: str | None = None
        try:
            async for msg in self._ws:  # type: ignore[union-attr]
                if msg.type is aiohttp.WSMsgType.BINARY:
                    if pending_event is not None:
                        self._dispatch(pending_event, msg.data)
                        pending_event = None
                    continue
                if msg.type is not aiohttp.WSMsgType.TEXT:
                    break

                data: str = msg.data
                if data.startswith("0{"):
                    await self._send("40")
                elif data.startswith("40"):
                    await self._send("42" + json.dumps(["auth", self.credentials.auth_payload()]))
                elif data == "2":
                    await self._send("3")
                elif data.startswith("41"):
                    # сервер закрив namespace одразу після auth — ключ не прийнято
                    if self._ready is not None and not self._ready.done():
                        self._ready.set_exception(PocketUnavailable("брокер відкинув ключ"))
                    break
                elif data.startswith("451-"):
                    pending_event = _event_name(data)
                    self._mark_ready()
                elif data.startswith("42"):
                    name = _event_name(data)
                    if name:
                        self._dispatch(name, data, inline=True)
        except Exception as exc:  # noqa: BLE001
            log.info("Pocket Option: читання обірвалось (%s)", exc)
        finally:
            for waiter in self._waiters.values():
                if not waiter.done():
                    waiter.set_exception(PocketUnavailable("зʼєднання з брокером закрилось"))
            self._waiters.clear()
            self._ws = None

    def _mark_ready(self) -> None:
        """Брокер шле події лише після вдалої авторизації — це і є наш сигнал готовності."""
        if self._ready is not None and not self._ready.done():
            self._ready.set_result(True)

    def _dispatch(self, event: str, payload: object, inline: bool = False) -> None:
        if event != "loadHistoryPeriodFast":
            return
        try:
            if inline:
                body = json.loads(payload[payload.index("[") :])[1]  # type: ignore[union-attr]
            else:
                body = json.loads(payload)  # type: ignore[arg-type]
        except (ValueError, IndexError, TypeError, AttributeError):
            return
        waiter = self._waiters.pop(str(body.get("asset")), None)
        if waiter is not None and not waiter.done():
            waiter.set_result(body)

    async def _send(self, frame: str) -> None:
        if self._ws is None:
            raise PocketUnavailable("немає зʼєднання з брокером")
        await self._ws.send_str(frame)

    async def _teardown(self) -> None:
        if self._reader is not None:
            self._reader.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._reader
            self._reader = None
        if self._ws is not None:
            with contextlib.suppress(Exception):
                await self._ws.close()
            self._ws = None
        if self._session is not None:
            with contextlib.suppress(Exception):
                await self._session.close()
            self._session = None

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

            if self._ws is None:
                await self._connect()

            waiter: asyncio.Future = asyncio.get_running_loop().create_future()
            self._waiters[symbol] = waiter
            request = {
                "asset": symbol,
                "index": int(time.time() * 1000),
                "time": int(time.time()),
                "offset": timeframe * count,
                "period": timeframe,
            }
            try:
                await self._send("42" + json.dumps(["loadHistoryPeriod", request]))
                body = await asyncio.wait_for(waiter, timeout=HISTORY_TIMEOUT)
            except asyncio.TimeoutError as exc:
                self._waiters.pop(symbol, None)
                await self._teardown()
                raise PocketUnavailable(
                    f"історія {symbol} не приїхала за {HISTORY_TIMEOUT:.0f}с{self._hint()}"
                ) from exc
            except PocketUnavailable:
                self._waiters.pop(symbol, None)
                raise
            except Exception as exc:  # noqa: BLE001
                self._waiters.pop(symbol, None)
                await self._teardown()
                raise PocketUnavailable(f"помилка Pocket Option: {exc}") from exc

            candles = _to_candles(body)
            if not candles:
                raise PocketUnavailable(f"порожня історія по {symbol}")
            self._cache[(symbol, timeframe)] = (time.time(), candles)
            return candles

    def _hint(self) -> str:
        if self.credentials is None or self.credentials.looks_like_trading_session:
            return " — схоже, ключ протух, онови його в /admin"
        return (
            " — ключ узято з сокета графіка/чату; потрібен кадр auth торгового "
            "зʼєднання (поле session, а не sessionToken)"
        )

    async def close(self) -> None:
        await self._teardown()

    async def drop_connection(self) -> None:
        """Закрити зʼєднання між запитами (не посеред чужого): наступний підʼєднається заново."""
        async with self._lock:
            await self._teardown()


def _event_name(frame: str) -> str:
    try:
        return str(json.loads(frame[frame.index("[") :])[0])
    except (ValueError, IndexError):
        return ""


def _to_candles(raw: object) -> list[Candle]:
    """Нормалізувати відповідь брокера у наші свічки (приймає і dict, і обʼєкти)."""
    items = raw
    for attribute in ("data", "candles", "history"):
        if hasattr(items, attribute):
            items = getattr(items, attribute)
            break
    if isinstance(items, dict):
        items = items.get("data") or items.get("candles") or []
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
