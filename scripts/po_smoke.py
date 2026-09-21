"""Жива перевірка з'єднання з Pocket Option: авторизація + історія свічок.

Ключ береться з оточення, у репозиторій нічого не пишемо:

    PO_SSID='{"session":"...","isDemo":1,"uid":...,"platform":2}' python scripts/po_smoke.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from data.pocket import PocketCredentials  # noqa: E402

ASSET = os.environ.get("PO_ASSET", "EURUSD_otc")
PERIOD = int(os.environ.get("PO_PERIOD", "60"))


def _patch_dns_for_windows_vpn() -> None:
    """Локальний костиль: під VPN на Windows асинхронний резолвер aiohttp (aiodns) мовчить.

    У контейнері таких проблем немає, тому патч живе тільки у смоук-скрипті.
    """
    import socket as _socket

    import aiohttp

    original = aiohttp.TCPConnector.__init__

    def patched(self, *args, **kwargs):
        kwargs.setdefault("resolver", aiohttp.ThreadedResolver())
        kwargs.setdefault("family", _socket.AF_INET)
        original(self, *args, **kwargs)

    aiohttp.TCPConnector.__init__ = patched


async def main() -> int:
    if os.name == "nt":
        _patch_dns_for_windows_vpn()
    from pocket_option import PocketOptionClient, constants, models

    creds = PocketCredentials.parse(os.environ.get("PO_SSID", ""))
    print(f"вхід: uid={creds.uid} demo={creds.is_demo} довжина сесії={len(creds.session)}")

    client = PocketOptionClient(reconnection=False)
    loop = asyncio.get_running_loop()
    authed: asyncio.Future = loop.create_future()
    history: asyncio.Future = loop.create_future()

    @client.on.success_auth
    async def _on_auth(event) -> None:  # noqa: ANN001
        if not authed.done():
            authed.set_result(event)

    @client.on.load_history_period_fast
    async def _on_history(event) -> None:  # noqa: ANN001
        if not history.done():
            history.set_result(event)

    auth = models.AuthorizationData(
        session=creds.session,
        is_demo=1 if creds.is_demo else 0,
        uid=creds.uid,
        platform=creds.platform,
        is_fast_history=True,
        is_optimized=True,
    )

    url = constants.Regions.DEMO if creds.is_demo else constants.Regions.EUROPA
    print(f"конект: {url}")
    headers = {
        "Origin": "https://pocketoption.com",
        "Referer": "https://pocketoption.com/",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
        ),
    }
    try:
        await client.connect(url, headers=headers, auth=auth.model_dump(by_alias=True))
    except Exception as exc:
        print(f"❌ не під'єднався: {type(exc).__name__}: {exc}")
        return 1

    try:
        await asyncio.wait_for(authed, timeout=15)
        print("✅ авторизація пройшла")
    except asyncio.TimeoutError:
        print("❌ авторизації немає за 15с — ключ не підійшов або не той сокет")
        return 1

    asset = getattr(models.Asset, ASSET, None)
    if asset is None:
        print(f"❌ актив {ASSET} не знайдено у списку SDK")
        return 1

    client.emit.subscribe_to_asset(asset)
    client.emit.load_history_period(
        models.LoadHistoryPeriodRequest(
            asset=asset, index=None, time=float(int(time.time())), offset=PERIOD * 120, period=PERIOD
        )
    )

    try:
        event = await asyncio.wait_for(history, timeout=20)
    except asyncio.TimeoutError:
        print("❌ історія не приїхала за 20с")
        return 1

    candles = getattr(event, "candles", None) or getattr(event, "data", None) or []
    print(f"✅ історія: {len(candles)} записів")
    for item in list(candles)[:3]:
        print("   ", item)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
