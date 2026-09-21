"""Жива перевірка Pocket Option: свічки -> движок сигналів -> картинка.

    PO_SSID='42["auth",{...}]' python scripts/po_live.py

Нічого не купує і не продає — тільки читає котирування.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.chart import render_signal  # noqa: E402
from core.signals import analyze  # noqa: E402
from data.market import ASSETS, ASSETS_BY_SYMBOL, timeframe_label  # noqa: E402
from data.pocket import PocketSource  # noqa: E402


def _patch_dns_for_windows_vpn() -> None:
    """Під VPN на Windows асинхронний резолвер aiohttp мовчить; у контейнері це не потрібно."""
    import socket as _socket

    import aiohttp

    original = aiohttp.TCPConnector.__init__

    def patched(self, *args, **kwargs):  # noqa: ANN001, ANN202
        kwargs.setdefault("resolver", aiohttp.ThreadedResolver())
        kwargs.setdefault("family", _socket.AF_INET)
        original(self, *args, **kwargs)

    aiohttp.TCPConnector.__init__ = patched


async def main() -> int:
    if os.name == "nt":
        _patch_dns_for_windows_vpn()

    timeframe = int(os.environ.get("PO_PERIOD", "60"))
    source = PocketSource(os.environ.get("PO_SSID", ""))
    best = None
    ok = 0

    for asset in ASSETS:
        try:
            candles = await source.candles(asset.symbol, timeframe, 120)
        except Exception as exc:  # noqa: BLE001
            print(f"{asset.title:14} ПОМИЛКА: {exc}")
            continue
        ok += 1
        signal = analyze(candles, asset.digits)
        note = f"{signal.direction} score {signal.score}" if signal else "сигналу нема"
        print(f"{asset.title:14} {len(candles):>3} свічок  остання {candles[-1].close:<12} {note}")
        score = signal.score if signal else 0.0
        if best is None or score > best[0]:
            best = (score, asset, candles, signal)

    if best is not None:
        score, asset, candles, signal = best
        direction = signal.direction if signal else "BUY"
        png = render_signal(
            candles,
            asset_title=asset.title,
            direction=direction,
            timeframe_label=timeframe_label(timeframe),
            digits=asset.digits,
            demo=False,
        )
        out = Path("runtime") / "po_live.png"
        out.parent.mkdir(exist_ok=True)
        out.write_bytes(png)
        print(f"\nграфік {asset.title} ({direction}) -> {out}, {len(png)} байт")

    await source.close()
    print(f"\nактивів із даними: {ok}/{len(ASSETS)}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
