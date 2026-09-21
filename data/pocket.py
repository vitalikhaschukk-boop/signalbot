"""Реальні свічки Pocket Option через неофіційний SDK `pocket-option`.

Як це працює: друг заходить у СВІЙ ДЕМО-акаунт Pocket Option у браузері,
звідти дістається `session` (SSID) — і бот по websocket слухає ті самі ціни,
що бачить трейдер у терміналі. Ключ живе в БД (`po_ssid`) і міняється
командою в адмінці, коли протухне.

Офіційного API в Pocket Option немає, тож цей шар свідомо:
  * тільки ЧИТАЄ котирування, жодних угод з коду;
  * ходить від демо-акаунта, щоб не тягнути під ToS-ризик реальний рахунок;
  * при будь-якій помилці віддає порожньо, а бот каже юзеру «немає зв'язку»
    і НЕ списує сесію.
"""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass

from data.market import ASSETS, Asset, Candle


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
        """SSID копіюють по-різному: або голий рядок, або цілий JSON з консолі."""
        raw = raw.strip()
        if not raw:
            raise PocketUnavailable("порожній SSID")
        if raw.startswith("{"):
            try:
                data = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise PocketUnavailable(f"SSID не схожий на JSON: {exc}") from exc
            return cls(
                session=str(data.get("session") or data.get("ssid") or ""),
                uid=int(data.get("uid") or 0),
                is_demo=bool(int(data.get("isDemo", 1))),
                platform=int(data.get("platform", 2)),
            )
        return cls(session=raw)


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
                "пакет pocket-option не встановлено (pip install pocket-option, потрібен Python 3.13+)"
            ) from exc

        client = PocketOptionClient(
            auth_data=AuthorizationData.model_validate(
                {
                    "session": self.credentials.session,
                    "isDemo": int(self.credentials.is_demo),
                    "uid": self.credentials.uid,
                    "platform": self.credentials.platform,
                }
            )
        )
        await client.connect(Regions.DEMO if self.credentials.is_demo else Regions.EUROPE)
        self._client = client
        return client

    # ------------------------------------------------------------------ data
    async def assets(self) -> list[Asset]:
        # Список тримаємо свій: нам потрібні конкретні пари, а не весь каталог брокера.
        return list(ASSETS)

    async def candles(self, symbol: str, timeframe: int, count: int = 120) -> list[Candle]:
        key = (symbol, timeframe)
        cached = self._cache.get(key)
        if cached and time.time() - cached[0] < self.cache_ttl:
            return cached[1]

        async with self._lock:
            cached = self._cache.get(key)
            if cached and time.time() - cached[0] < self.cache_ttl:
                return cached[1]
            client = await self._ensure_client()
            end = int(time.time())
            try:
                raw = await asyncio.wait_for(
                    client.emit.load_history_period(
                        asset=symbol,
                        period=timeframe,
                        time=end,
                        offset=timeframe * count,
                    ),
                    timeout=12.0,
                )
            except asyncio.TimeoutError as exc:
                raise PocketUnavailable("Pocket Option не відповів за 12с") from exc
            except Exception as exc:  # noqa: BLE001 - SDK кидає свої класи помилок
                raise PocketUnavailable(f"помилка Pocket Option: {exc}") from exc

            candles = _to_candles(raw)
            if not candles:
                raise PocketUnavailable("Pocket Option повернув порожню історію")
            self._cache[key] = (time.time(), candles)
            return candles

    async def close(self) -> None:
        client, self._client = self._client, None
        if client is None:
            return
        for method in ("disconnect", "close"):
            handler = getattr(client, method, None)
            if handler is None:
                continue
            result = handler()
            if asyncio.iscoroutine(result):
                await result
            return


def _to_candles(raw: object) -> list[Candle]:
    """Нормалізувати відповідь SDK у наші свічки.

    Брокер віддає або список словників (`time/open/high/low/close/volume`),
    або об'єкти-моделі pydantic — приймаємо обидва варіанти.
    """
    items = raw
    for attribute in ("candles", "data", "history"):
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
