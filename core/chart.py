"""Рендер картки сигналу: темний свічковий графік з плашкою BUY/SELL.

Малюємо самі (matplotlib), не тягнемо чужі скріни TradingView.
Повертає PNG у пам'яті — на диск нічого не пишемо.
"""
from __future__ import annotations

import io
from datetime import datetime, timezone

import matplotlib

matplotlib.use("Agg")

import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyBboxPatch  # noqa: E402

from data.market import Candle  # noqa: E402

BG = "#0d1117"
PANEL = "#111827"
GRID = "#1f2937"
TEXT = "#c9d1d9"
MUTED = "#6b7280"
GREEN = "#26a69a"
RED = "#ef5350"


def render_signal(
    candles: list[Candle],
    *,
    asset_title: str,
    direction: str,
    timeframe_label: str,
    digits: int = 5,
    header: str = "AI MARKET SCANNER",
    subtitle: str = "Premium Trading Signal",
    demo: bool = False,
) -> bytes:
    candles = candles[-90:]
    times = [datetime.fromtimestamp(c.ts, tz=timezone.utc) for c in candles]
    width = (times[1] - times[0]).total_seconds() / 86400 * 0.7 if len(times) > 1 else 0.0004

    fig = plt.figure(figsize=(9.6, 6.4), dpi=110, facecolor=BG)
    grid = fig.add_gridspec(nrows=5, ncols=1, hspace=0.05, left=0.02, right=0.90, top=0.86, bottom=0.07)
    ax = fig.add_subplot(grid[0:4, 0], facecolor=BG)
    ax_vol = fig.add_subplot(grid[4, 0], facecolor=BG, sharex=ax)

    for candle, stamp in zip(candles, times):
        color = GREEN if candle.bull else RED
        ax.plot([stamp, stamp], [candle.low, candle.high], color=color, linewidth=0.9, zorder=2)
        bottom = min(candle.open, candle.close)
        height = max(abs(candle.close - candle.open), (candle.high - candle.low) * 0.02)
        ax.bar(stamp, height, bottom=bottom, width=width, color=color, edgecolor=color, zorder=3)
        ax_vol.bar(stamp, candle.volume, width=width, color=color, alpha=0.55, zorder=2)

    last = candles[-1]
    ax.axhline(last.close, color="#f5c518", linewidth=0.7, linestyle=(0, (4, 3)), alpha=0.8, zorder=1)

    for axis in (ax, ax_vol):
        axis.grid(color=GRID, linewidth=0.5, alpha=0.7)
        axis.set_axisbelow(True)
        for spine in axis.spines.values():
            spine.set_color(GRID)
        axis.tick_params(colors=MUTED, labelsize=7)
        axis.yaxis.tick_right()

    ax.set_xticklabels([])
    ax_vol.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    ax_vol.set_yticks([])
    ax.yaxis.set_major_formatter(lambda value, _pos: f"{value:.{digits}f}")

    # цінник останньої ціни збоку
    ax.annotate(
        f"{last.close:.{digits}f}",
        xy=(1.0, last.close),
        xycoords=("axes fraction", "data"),
        xytext=(4, 0),
        textcoords="offset points",
        va="center",
        ha="left",
        fontsize=8,
        color="#0d1117",
        bbox={"boxstyle": "square,pad=0.25", "facecolor": "#f5c518", "edgecolor": "none"},
    )

    # шапка
    fig.text(0.02, 0.945, header, color="#e6edf3", fontsize=13, fontweight="bold")
    fig.text(0.02, 0.905, subtitle, color=MUTED, fontsize=9)
    fig.text(
        0.90,
        0.945,
        datetime.now(tz=timezone.utc).strftime("%d %b %Y • %H:%M UTC"),
        color=MUTED,
        fontsize=9,
        ha="right",
    )
    fig.text(0.90, 0.905, asset_title + f"  ·  {timeframe_label}", color=TEXT, fontsize=9, ha="right")

    # плашка сигналу
    is_buy = direction.upper() == "BUY"
    plate_color = "#1b8f70" if is_buy else "#c62828"
    plate = FancyBboxPatch(
        (0.33, 0.70),
        0.34,
        0.12,
        transform=fig.transFigure,
        boxstyle="round,pad=0.012,rounding_size=0.02",
        facecolor=plate_color,
        edgecolor="#ffffff",
        linewidth=1.4,
        zorder=10,
    )
    fig.patches.append(plate)
    fig.text(
        0.50,
        0.757,
        ("● BUY SIGNAL" if is_buy else "● SELL SIGNAL"),
        color="#ffffff",
        fontsize=17,
        fontweight="bold",
        ha="center",
        va="center",
        zorder=11,
    )

    if demo:
        fig.text(
            0.50,
            0.40,
            "DEMO DATA",
            color="#ffffff",
            alpha=0.10,
            fontsize=46,
            fontweight="bold",
            ha="center",
            va="center",
            rotation=18,
            zorder=12,
        )

    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", facecolor=BG)
    plt.close(fig)
    return buffer.getvalue()
