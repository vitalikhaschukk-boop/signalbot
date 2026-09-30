"""Джерело ринкових даних.

`MarketSource` — інтерфейс, який реалізують два бекенди:
  * `SimulatedSource` — синтетичні свічки, щоб ганяти бота без Pocket Option;
  * `PocketSource` (data/pocket.py) — реальні свічки Pocket Option по SSID.

Список активів свідомо збігається з тим, що торгує Pocket Option (OTC-пари),
бо саме їхні ціни бачить трейдер у терміналі.
"""
from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol


@dataclass(slots=True, frozen=True)
class Candle:
    ts: int
    open: float
    high: float
    low: float
    close: float
    volume: float

    @property
    def bull(self) -> bool:
        return self.close >= self.open


@dataclass(slots=True, frozen=True)
class Asset:
    symbol: str          # як його звуть у Pocket Option: EURUSD_otc
    title: str           # як показуємо юзеру: EUR/USD OTC
    kind: str            # forex | crypto | metal | stock
    digits: int = 5      # скільки знаків після коми малювати

    @property
    def name(self) -> str:
        """Як бачить юзер: без позначки OTC."""
        return self.title.removesuffix(" OTC")


# 20 валютних пар, які друг бачить у Pocket Option (його список від 2026-09-30).
PAIRS: tuple[str, ...] = (
    "EUR/USD", "GBP/USD", "USD/JPY", "USD/CHF", "USD/CAD", "AUD/USD",
    "EUR/GBP", "EUR/JPY", "EUR/CHF", "EUR/CAD", "EUR/AUD",
    "GBP/AUD", "GBP/JPY", "GBP/CAD", "GBP/CHF",
    "AUD/CHF", "AUD/CAD", "CAD/JPY", "CAD/CHF", "CHF/JPY",
)


def _pair(title: str, otc: bool) -> Asset:
    code = title.replace("/", "")
    digits = 3 if "JPY" in code else 5
    if otc:
        return Asset(code + "_otc", title + " OTC", "forex", digits)
    return Asset(code, title, "forex", digits)


# OTC-пари Pocket Option — працюють цілодобово, у вихідні теж.
ASSETS: tuple[Asset, ...] = tuple(_pair(title, otc=True) for title in PAIRS)
# Звичайні (не OTC) пари — реальний ринок, торгуються лише коли відкритий форекс.
REGULAR: tuple[Asset, ...] = tuple(_pair(title, otc=False) for title in PAIRS)
ALL_ASSETS: tuple[Asset, ...] = REGULAR + ASSETS

ASSETS_BY_SYMBOL = {asset.symbol: asset for asset in ALL_ASSETS}


def forex_open(now: datetime | None = None) -> bool:
    """Валютний ринок відкритий: з неділі 21:00 до пʼятниці 21:00 UTC."""
    now = now or datetime.now(timezone.utc)
    weekday, hour = now.weekday(), now.hour
    if weekday == 5 or (weekday == 4 and hour >= 21) or (weekday == 6 and hour < 21):
        return False
    return True


def live_assets(now: datetime | None = None, bad: set[str] | frozenset[str] = frozenset()) -> list[Asset]:
    """Що давати в сесії: у робочі години ринку — звичайні пари, інакше OTC.

    `bad` — звичайні пари, які брокер не віддав: замість них беремо їхній OTC-двійник.
    """
    if not forex_open(now):
        return list(ASSETS)
    return [ASSETS_BY_SYMBOL[asset.symbol + "_otc"] if asset.symbol in bad else asset for asset in REGULAR]


_BASE_PRICE = {
    "EURUSD": 1.1700, "GBPUSD": 1.3450, "USDJPY": 148.0, "USDCHF": 0.7950, "USDCAD": 1.3900,
    "AUDUSD": 0.6600, "EURGBP": 0.8700, "EURJPY": 173.0, "EURCHF": 0.9300, "EURCAD": 1.6250,
    "EURAUD": 1.7700, "GBPAUD": 2.0350, "GBPJPY": 199.0, "GBPCAD": 1.8700, "GBPCHF": 1.0700,
    "AUDCHF": 0.5250, "AUDCAD": 0.9150, "CADJPY": 106.5, "CADCHF": 0.5720, "CHFJPY": 186.0,
}


class MarketSource(Protocol):
    name: str

    async def assets(self) -> list[Asset]: ...

    async def candles(self, symbol: str, timeframe: int, count: int = 120) -> list[Candle]: ...

    async def close(self) -> None: ...


class SimulatedSource:
    """Випадкове блукання з трендовими ділянками — для розробки й демо.

    Свідомо НЕ видає себе за реальний ринок: бот з цим бекендом ставить
    у підписі графіка позначку DEMO DATA.
    """

    name = "sim"
    real = False

    def __init__(self, seed: int | None = None) -> None:
        self._rng = random.Random(seed)

    async def assets(self) -> list[Asset]:
        return list(ASSETS)

    async def candles(self, symbol: str, timeframe: int, count: int = 120) -> list[Candle]:
        asset = ASSETS_BY_SYMBOL.get(symbol)
        base = _BASE_PRICE.get(symbol.removesuffix("_otc"), 1.0)
        step = base * (0.00035 if asset and asset.kind == "forex" else 0.0018)
        now_ts = int(time.time() // timeframe * timeframe)
        drift_len = self._rng.randint(8, 22)
        drift = self._rng.uniform(-1.0, 1.0)
        price = base
        out: list[Candle] = []
        for index in range(count):
            if index % drift_len == 0:
                drift = self._rng.uniform(-1.0, 1.0)
                drift_len = self._rng.randint(8, 22)
            shock = self._rng.gauss(0.0, 1.0)
            move = step * (drift * 0.55 + shock)
            open_ = price
            close = price + move
            wick = abs(self._rng.gauss(0.0, 1.0)) * step * 0.6
            high = max(open_, close) + wick
            low = min(open_, close) - wick
            volume = abs(move) / step * 40 + self._rng.uniform(15, 60)
            out.append(
                Candle(
                    ts=now_ts - (count - 1 - index) * timeframe,
                    open=open_,
                    high=high,
                    low=low,
                    close=close,
                    volume=round(volume, 1),
                )
            )
            price = close
        return out

    async def close(self) -> None:
        return None


def format_price(value: float, digits: int) -> str:
    return f"{value:.{digits}f}"


def timeframe_label(timeframe: int) -> str:
    minutes = max(1, timeframe // 60)
    return f"M{minutes}"


def round_step(value: float, digits: int) -> float:
    factor = 10 ** digits
    return math.floor(value * factor + 0.5) / factor
