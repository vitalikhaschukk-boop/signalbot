"""Діагностика доступу до Pocket Option з того місця, де крутиться бот.

Кожен хост перевіряється по кроках — DNS → TCP → TLS → перший рядок HTTP-відповіді,
щоб було видно, НА ЯКОМУ кроці висне: блок IP, фільтр TLS чи сайт мовчить на запит.
Жодних cookies і ключів тут не використовується.
"""
from __future__ import annotations

import asyncio
import socket
import ssl
import time

from data.pocket import HEADERS

# дзеркала сайту і хости сокета котирувань
HOSTS = (
    ("pocketoption.com", "/en/cabinet/demo-quick-high-low/"),
    ("po.trade", "/en/cabinet/demo-quick-high-low/"),
    ("pocketoption.net", "/en/cabinet/demo-quick-high-low/"),
    ("po.market", "/"),
    ("demo-api-eu.po.market", "/socket.io/?EIO=4&transport=polling"),
)
STEP_TIMEOUT = 8.0


async def probe(host: str, path: str) -> str:
    started = time.monotonic()

    def ms() -> str:
        return f"{(time.monotonic() - started) * 1000:.0f}мс"

    try:
        infos = await asyncio.wait_for(
            asyncio.get_running_loop().getaddrinfo(host, 443, type=socket.SOCK_STREAM), STEP_TIMEOUT
        )
        ip = infos[0][4][0]
    except Exception as exc:  # noqa: BLE001
        return f"{host}: ❌ DNS ({type(exc).__name__})"

    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(ip, 443), STEP_TIMEOUT)
    except Exception as exc:  # noqa: BLE001
        return f"{host} [{ip}]: ❌ TCP {ms()} ({type(exc).__name__})"
    tcp = ms()
    writer.close()

    context = ssl.create_default_context()
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(ip, 443, ssl=context, server_hostname=host), STEP_TIMEOUT
        )
    except Exception as exc:  # noqa: BLE001
        return f"{host} [{ip}]: TCP ✅ {tcp} · ❌ TLS {ms()} ({type(exc).__name__})"
    tls = ms()

    request = (
        f"GET {path} HTTP/1.1\r\nHost: {host}\r\nUser-Agent: {HEADERS['User-Agent']}\r\n"
        "Accept: text/html,*/*;q=0.8\r\nAccept-Language: en-US,en;q=0.9\r\nConnection: close\r\n\r\n"
    )
    try:
        writer.write(request.encode())
        await writer.drain()
        status = await asyncio.wait_for(reader.readline(), STEP_TIMEOUT)
        location = ""
        for _ in range(40):
            line = await asyncio.wait_for(reader.readline(), STEP_TIMEOUT)
            if not line.strip():
                break
            if line.lower().startswith(b"location:"):
                location = " → " + line.split(b":", 1)[1].strip().decode(errors="replace")[:60]
        answer = status.decode(errors="replace").strip() or "порожньо"
        return f"{host} [{ip}]: TCP ✅ {tcp} · TLS ✅ {tls} · HTTP {answer} {ms()}{location}"
    except Exception as exc:  # noqa: BLE001
        return f"{host} [{ip}]: TCP ✅ {tcp} · TLS ✅ {tls} · ❌ HTTP {ms()} ({type(exc).__name__})"
    finally:
        writer.close()


async def run() -> list[str]:
    return list(await asyncio.gather(*(probe(host, path) for host, path in HOSTS)))


if __name__ == "__main__":
    for line in asyncio.run(run()):
        print(line)
