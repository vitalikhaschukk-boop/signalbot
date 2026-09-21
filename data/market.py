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


ASSETS: tuple[Asset, ...] = (
    Asset("EURUSD_otc", "EUR/USD OTC", "forex", 5),
    Asset("GBPUSD_otc", "GBP/USD OTC", "forex", 5),
    Asset("USDJPY_otc", "USD/JPY OTC", "forex", 3),
    Asset("EURJPY_otc", "EUR/JPY OTC", "forex", 3),
    Asset("AUDCAD_otc", "AUD/CAD OTC", "forex", 5),
    Asset("USDCHF_otc", "USD/CHF OTC", "forex", 5),
    Asset("BTCUSD_otc", "BTC/USD OTC", "crypto", 2),
    Asset("ETHUSD_otc", "ETH/USD OTC", "crypto", 2),
    Asset("SOLUSD_otc", "SOL/USD OTC", "crypto", 3),
    Asset("XAUUSD_otc", "XAU/USD OTC", "metal", 2),
)

ASSETS_BY_SYMBOL = {asset.symbol: asset for asset in ASSETS}

_BASE_PRICE = {
    "EURUSD_otc": 1.0850,
    "GBPUSD_otc": 1.2720,
    "USDJPY_otc": 156.40,
    "EURJPY_otc": 180.65,
    "AUDCAD_otc": 0.9120,
    "USDCHF_otc": 0.8890,
    "BTCUSD_otc": 96300.0,
    "ETHUSD_otc": 3120.0,
    "SOLUSD_otc": 188.40,
    "XAUUSD_otc": 4295.0,
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
        base = _BASE_PRICE.get(symbol, 1.0)
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
