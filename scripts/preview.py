"""Зібрати приклад картки сигналу на симульованих даних (для перегляду дизайну)."""
import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.chart import render_signal
from core.signals import analyze
from data.market import ASSETS_BY_SYMBOL, SimulatedSource, timeframe_label

async def main():
    found = {}
    for seed in range(400):
        src = SimulatedSource(seed=seed)
        for symbol in ("EURUSD_otc", "EURJPY_otc", "BTCUSD_otc"):
            candles = await src.candles(symbol, 60, 120)
            sig = analyze(candles, ASSETS_BY_SYMBOL[symbol].digits)
            if sig and sig.direction not in found:
                found[sig.direction] = (symbol, candles, sig)
        if len(found) == 2:
            break
    for direction, (symbol, candles, sig) in found.items():
        asset = ASSETS_BY_SYMBOL[symbol]
        png = render_signal(candles, asset_title=asset.title, direction=direction,
                            timeframe_label=timeframe_label(60), digits=asset.digits, demo=True)
        out = Path("runtime") / f"preview_{direction.lower()}.png"
        out.write_bytes(png)
        print(direction, symbol, "score", sig.score, "reasons", [k for k, _ in sig.reasons], "->", out, len(png), "bytes")

asyncio.run(main())
