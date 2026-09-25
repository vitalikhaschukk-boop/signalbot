"""Движок сигналів: реальні індикатори по реальних свічках.

Ніякого рандому. Якщо ринок не дає чіткої структури — повертаємо None,
і бот чесно каже «точки входу зараз немає» (і НЕ списує сесію).

Причини входу віддаються ключами i18n, щоб рендерити їх укр/рос.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from data.market import Candle

BUY = "BUY"
SELL = "SELL"

# сума ваг усіх правил однієї сторони: тренд 2.0 + відкат 1.2 + RSI 1.0 + обсяг 0.8 + рівень 0.6
MAX_SCORE = 5.6


@dataclass(slots=True)
class Signal:
    direction: str
    score: float
    reasons: list[tuple[str, dict[str, object]]] = field(default_factory=list)
    rsi: float = 50.0
    ema_fast: float = 0.0
    ema_slow: float = 0.0
    level: float = 0.0
    against: float = 0.0

    @property
    def quality(self) -> int:
        """Якість у відсотках: яка частка правил підтвердила вхід, мінус половина протилежних.

        Це сила збігу індикаторів, а не ймовірність виграшу.
        """
        net = self.score - self.against * 0.5
        return max(1, min(99, round(net / MAX_SCORE * 100)))


def ema(values: list[float], period: int) -> list[float]:
    if not values:
        return []
    alpha = 2.0 / (period + 1.0)
    out = [values[0]]
    for value in values[1:]:
        out.append(out[-1] + alpha * (value - out[-1]))
    return out


def rsi(values: list[float], period: int = 14) -> float:
    if len(values) <= period:
        return 50.0
    gains = 0.0
    losses = 0.0
    for prev, curr in zip(values[-period - 1:-1], values[-period:]):
        delta = curr - prev
        if delta >= 0:
            gains += delta
        else:
            losses -= delta
    if losses == 0:
        return 100.0 if gains > 0 else 50.0
    rs = (gains / period) / (losses / period)
    return 100.0 - 100.0 / (1.0 + rs)


def atr(candles: list[Candle], period: int = 14) -> float:
    if len(candles) < 2:
        return 0.0
    trs: list[float] = []
    for prev, curr in zip(candles[-period - 1:-1], candles[-period:]):
        trs.append(max(curr.high - curr.low, abs(curr.high - prev.close), abs(curr.low - prev.close)))
    return sum(trs) / len(trs) if trs else 0.0


def _swings(candles: list[Candle], window: int = 10) -> tuple[list[float], list[float]]:
    """Дві останні пари максимумів/мінімумів по вікнах — структура ринку."""
    chunk_a = candles[-window * 2:-window]
    chunk_b = candles[-window:]
    if not chunk_a or not chunk_b:
        return [], []
    highs = [max(c.high for c in chunk_a), max(c.high for c in chunk_b)]
    lows = [min(c.low for c in chunk_a), min(c.low for c in chunk_b)]
    return highs, lows


def analyze(candles: list[Candle], digits: int = 5, min_score: float = 3.0) -> Signal | None:
    """Повертає сигнал, лише якщо кілька незалежних правил дивляться в один бік."""
    if len(candles) < 40:
        return None

    closes = [c.close for c in candles]
    fast = ema(closes, 9)
    slow = ema(closes, 21)
    value_rsi = rsi(closes, 14)
    value_atr = atr(candles, 14)
    if value_atr <= 0:
        return None

    last = candles[-1]
    highs, lows = _swings(candles)
    if not highs:
        return None

    trend_up = fast[-1] > slow[-1] and fast[-1] - fast[-5] > 0
    trend_down = fast[-1] < slow[-1] and fast[-1] - fast[-5] < 0
    structure_up = highs[1] > highs[0] and lows[1] > lows[0]
    structure_down = highs[1] < highs[0] and lows[1] < lows[0]

    recent = candles[-5:]
    bull_volume = sum(c.volume for c in recent if c.bull)
    bear_volume = sum(c.volume for c in recent if not c.bull)
    prior_volume = sum(c.volume for c in candles[-10:-5]) / 5 if len(candles) >= 10 else 0.0
    volume_now = sum(c.volume for c in recent) / 5

    near_fast = abs(last.close - fast[-1]) <= value_atr * 0.6
    level = round(slow[-1], digits)

    buy = 0.0
    sell = 0.0
    reasons_buy: list[tuple[str, dict[str, object]]] = []
    reasons_sell: list[tuple[str, dict[str, object]]] = []

    if trend_up and structure_up:
        buy += 2.0
        reasons_buy.append(("reason_trend_up", {}))
    if trend_down and structure_down:
        sell += 2.0
        reasons_sell.append(("reason_trend_down", {}))

    if trend_up and near_fast and last.bull:
        buy += 1.2
        reasons_buy.append(("reason_pullback_up", {"level": f"{level:.{digits}f}"}))
    if trend_down and near_fast and not last.bull:
        sell += 1.2
        reasons_sell.append(("reason_pullback_down", {"level": f"{level:.{digits}f}"}))

    if value_rsi <= 32:
        buy += 1.0
        reasons_buy.append(("reason_rsi_oversold", {"value": round(value_rsi)}))
    elif value_rsi >= 68:
        sell += 1.0
        reasons_sell.append(("reason_rsi_overbought", {"value": round(value_rsi)}))

    if volume_now > prior_volume > 0:
        if bull_volume > bear_volume:
            buy += 0.8
            reasons_buy.append(("reason_volume_up", {}))
        elif bear_volume > bull_volume:
            sell += 0.8
            reasons_sell.append(("reason_volume_down", {}))

    if structure_down and not trend_up:
        sell += 0.6
        reasons_sell.append(("reason_stall_resistance", {}))
    if structure_up and lows[1] > lows[0]:
        buy += 0.6
        reasons_buy.append(("reason_bounce_support", {"level": f"{level:.{digits}f}"}))

    if buy >= sell and buy >= min_score:
        reasons_buy.append(("reason_continuation_up", {}))
        return Signal(
            direction=BUY,
            score=round(buy, 2),
            reasons=reasons_buy[:3],
            rsi=round(value_rsi, 1),
            ema_fast=fast[-1],
            ema_slow=slow[-1],
            level=level,
            against=round(sell, 2),
        )
    if sell > buy and sell >= min_score:
        reasons_sell.append(("reason_continuation_down", {}))
        return Signal(
            direction=SELL,
            score=round(sell, 2),
            reasons=reasons_sell[:3],
            rsi=round(value_rsi, 1),
            ema_fast=fast[-1],
            ema_slow=slow[-1],
            level=level,
            against=round(buy, 2),
        )
    return None


def pick_best(
    market: dict[str, list[Candle]], digits: dict[str, int], min_score: float = 3.0
) -> tuple[str, Signal] | None:
    """Обрати найсильніший сигнал серед кількох активів."""
    best: tuple[str, Signal] | None = None
    for symbol, candles in market.items():
        signal = analyze(candles, digits.get(symbol, 5), min_score)
        if signal is None:
            continue
        if best is None or signal.score > best[1].score:
            best = (symbol, signal)
    return best
