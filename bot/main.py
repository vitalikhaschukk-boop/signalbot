"""Точка входу: меню, вибір таймфрейму, сканер, видача сигналу."""
from __future__ import annotations

import asyncio
import contextlib
import html
import json
import logging
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aiogram import Bot, Dispatcher, F, Router  # noqa: E402
from aiogram.client.default import DefaultBotProperties  # noqa: E402
from aiogram.enums import ParseMode  # noqa: E402
from aiogram.filters import CommandStart  # noqa: E402
from aiogram.types import BufferedInputFile, CallbackQuery, Message  # noqa: E402

from bot import admin as admin_module  # noqa: E402
from bot.keyboards import back_menu, language_menu, main_menu, signal_menu, timeframe_menu  # noqa: E402
from core.chart import render_signal  # noqa: E402
from core.config import Config  # noqa: E402
from core.db import Database, User  # noqa: E402
from core.i18n import t  # noqa: E402
from core.signals import pick_best  # noqa: E402
from data.market import ASSETS_BY_SYMBOL, SimulatedSource, timeframe_label  # noqa: E402
from data import po_session  # noqa: E402
from data.pocket import PocketCredentials, PocketSource, PocketUnavailable  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("signalbot")

router = Router()

# як часто фоном оновлювати ключ Pocket Option через cookies
PO_REFRESH_EVERY = timedelta(hours=6)

PLAN_DEFAULTS = {
    "plan1": "Standard — 3 сигнали/день",
    "plan1_desc": "• 3 сесії на добу\n• Forex + Crypto OTC\n• підтримка в чаті",
    "plan2": "VIP — без обмежень",
    "plan2_desc": "• необмежені сесії\n• пріоритетний підбір активів\n• особистий трейдер",
}


class App:
    """Вся розділювана обв'язка в одному місці, щоб хендлери лишались тонкими."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.db = Database(config.database_url or config.db_path)
        self.bot: Bot | None = None  # підставляє main(), потрібен для тривог адмінам
        self.source = self._build_source()

    def _build_source(self):
        ssid = self.db.get_setting("po_ssid", self.config.po_ssid)
        has_cookies = bool(self.db.get_setting("po_cookies"))
        if self.config.data_backend == "pocket" and (ssid or has_cookies):
            try:
                return PocketSource(ssid, refresher=self.refresh_po_session if has_cookies else None)
            except PocketUnavailable as exc:
                log.warning("Pocket Option недоступний (%s) — працюю на симуляції", exc)
        return SimulatedSource()

    def reload_source(self) -> None:
        old = self.source
        self.source = self._build_source()
        if old is not self.source:
            with contextlib.suppress(RuntimeError):  # поза циклом подій закривати нічого
                asyncio.get_running_loop().create_task(old.close())

    async def refresh_po_session(self, alert: bool = True) -> PocketCredentials:
        """Свіжий ключ сокета через cookies сайту; оновлені cookies і ключ одразу в базу."""
        cookies = json.loads(self.db.get_setting("po_cookies") or "[]")
        try:
            result = await po_session.refresh(cookies)
        except PocketUnavailable as exc:
            log.warning("Pocket Option: автооновлення ключа не вдалось: %s", exc)
            if alert:
                await self.alert_po_failure(str(exc))
            raise
        credentials = result.credentials
        if not credentials.uid:  # сторінка uid не віддала — беремо з попереднього ключа
            with contextlib.suppress(PocketUnavailable, ValueError):
                credentials.uid = PocketCredentials.parse(self.db.get_setting("po_ssid")).uid
        self.db.set_setting("po_cookies", json.dumps(result.cookies))
        self.db.set_setting("po_ssid", json.dumps(credentials.auth_payload()))
        self.db.set_setting("po_refreshed_at", datetime.now(timezone.utc).isoformat(timespec="seconds"))
        self.db.set_setting("po_alert_at", "")
        log.info("Pocket Option: ключ оновлено через cookies (%s)", "; ".join(result.notes))
        return credentials

    async def alert_po_failure(self, reason: str) -> None:
        """Одна тривога адмінам на 6 годин, щоб не засипати чат."""
        last = self.db.get_setting("po_alert_at")
        if last and datetime.now(timezone.utc) - datetime.fromisoformat(last) < PO_REFRESH_EVERY:
            return
        self.db.set_setting("po_alert_at", datetime.now(timezone.utc).isoformat(timespec="seconds"))
        if self.bot is None:
            return
        for admin_id in admin_module.admin_ids():
            user = self.db.get_user(admin_id)
            with contextlib.suppress(Exception):
                await self.bot.send_message(
                    admin_id, t(user.lang if user else "uk", "po_alert", reason=html.escape(reason))
                )

    async def keep_po_fresh(self) -> None:
        """Фоном раз на 6 годин оновлювати ключ, щоб довга cookie теж оновлювалась і не старіла."""
        while True:
            await asyncio.sleep(PO_REFRESH_EVERY.total_seconds())
            source = self.source
            if not isinstance(source, PocketSource) or source.refresher is None:
                continue
            with contextlib.suppress(PocketUnavailable):
                source.credentials = await self.refresh_po_session()
                await source.drop_connection()  # наступний запит підʼєднається з новим ключем

    @property
    def demo_data(self) -> bool:
        return not getattr(self.source, "real", False)

    def user_or_create(self, message_from) -> User:
        return self.db.upsert_user(
            message_from.id, message_from.username, message_from.first_name
        )

    def plan(self, key: str) -> str:
        return self.db.get_setting(key, PLAN_DEFAULTS[key])

    def links(self) -> dict[str, str]:
        """Посилання кнопок: спершу те, що адмін задав у боті, інакше — зі змінних оточення.

        Значення «-» означає «прибрати кнопку», щоб адмін міг це зробити без деплою.
        """
        fallbacks = {
            "channel_url": self.config.channel_url,
            "trader_url": self.config.trader_url,
            "pocket_url": self.config.po_ref_url,
            "training_url": "",
        }
        out = {}
        for key, fallback in fallbacks.items():
            value = self.db.get_setting(key, fallback).strip()
            out[key] = "" if value == "-" else value
        return out


app: App | None = None


def profile_block(user: User, config: Config, lang: str) -> str:
    nick = html.escape(f"@{user.username}" if user.username else (user.first_name or "—"))
    lines = [
        t(lang, "welcome_title", bot_name=config.bot_name),
        "",
        "—" * 18,
        "",
        t(lang, "profile_title"),
        t(lang, "profile_id", user_id=user.user_id),
        t(lang, "profile_nick", nick=nick),
        "",
    ]
    if user.sub_active:
        lines.append(t(lang, "sub_active"))
        lines.append(t(lang, "sub_until", until=user.sub_until.strftime("%d.%m.%Y %H:%M")))
    else:
        lines.append(t(lang, "sub_inactive"))
        lines.append(t(lang, "sub_required"))
    lines.append(
        t(
            lang,
            "sessions_today",
            used=user.sessions_used(config.daily_sessions),
            limit=config.daily_sessions,
        )
    )
    lines += ["", "—" * 18, "", t(lang, "ai_pitch"), "", t(lang, "choose_action")]
    return "\n".join(lines)


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    assert app is not None and message.from_user is not None
    user = app.user_or_create(message.from_user)
    if user.banned:
        await message.answer(t(user.lang, "banned"))
        return
    await message.answer(
        profile_block(user, app.config, user.lang),
        reply_markup=main_menu(user.lang, app.links()),
    )


@router.callback_query(F.data == "menu:home")
async def cb_home(call: CallbackQuery) -> None:
    assert app is not None and call.from_user is not None
    user = app.user_or_create(call.from_user)
    await _replace(
        call,
        profile_block(user, app.config, user.lang),
        main_menu(user.lang, app.links()),
    )


@router.callback_query(F.data == "menu:lang")
async def cb_lang(call: CallbackQuery) -> None:
    assert app is not None and call.from_user is not None
    user = app.user_or_create(call.from_user)
    await _replace(call, t(user.lang, "lang_title"), language_menu(user.lang))


@router.callback_query(F.data.startswith("lang:"))
async def cb_set_lang(call: CallbackQuery) -> None:
    assert app is not None and call.from_user is not None and call.data is not None
    lang = call.data.split(":", 1)[1]
    app.db.set_lang(call.from_user.id, lang)
    await call.answer(t(lang, "lang_saved"))
    user = app.user_or_create(call.from_user)
    await _replace(
        call,
        profile_block(user, app.config, lang),
        main_menu(lang, app.links()),
    )


@router.callback_query(F.data == "menu:subs")
async def cb_subs(call: CallbackQuery) -> None:
    assert app is not None and call.from_user is not None
    user = app.user_or_create(call.from_user)
    text = "\n\n".join(
        [
            t(user.lang, "subs_title"),
            t(
                user.lang,
                "subs_body",
                plan1=app.plan("plan1"),
                plan1_desc=app.plan("plan1_desc"),
                plan2=app.plan("plan2"),
                plan2_desc=app.plan("plan2_desc"),
            ),
        ]
    )
    await _replace(call, text, back_menu(user.lang))


@router.callback_query(F.data == "menu:session")
async def cb_session(call: CallbackQuery) -> None:
    assert app is not None and call.from_user is not None
    user = app.user_or_create(call.from_user)
    if user.banned:
        await call.answer(t(user.lang, "banned"), show_alert=True)
        return
    if not user.sub_active:
        await call.answer(t(user.lang, "sub_required"), show_alert=True)
        return
    if user.sessions_left(app.config.daily_sessions) <= 0:
        await call.answer(
            t(user.lang, "no_sessions", limit=app.config.daily_sessions), show_alert=True
        )
        return
    await _replace(
        call,
        t(user.lang, "tf_title") + "\n\n" + t(user.lang, "tf_body"),
        timeframe_menu(user.lang),
    )


@router.callback_query(F.data.startswith("tf:"))
async def cb_timeframe(call: CallbackQuery) -> None:
    assert app is not None and call.from_user is not None and call.data is not None
    user = app.user_or_create(call.from_user)
    timeframe = int(call.data.split(":", 1)[1])
    if not user.sub_active or user.sessions_left(app.config.daily_sessions) <= 0:
        await call.answer(t(user.lang, "sub_required"), show_alert=True)
        return
    await _deliver_signal(call, user, timeframe=timeframe)


@router.callback_query(F.data == "menu:99")
async def cb_99(call: CallbackQuery) -> None:
    """99 Signal видає аналітик вручну: юзер стає в чергу, адміни отримують сповіщення."""
    assert app is not None and call.from_user is not None
    user = app.user_or_create(call.from_user)
    if user.banned:
        await call.answer(t(user.lang, "banned"), show_alert=True)
        return
    if not user.sub_active:
        await call.answer(t(user.lang, "sub_required"), show_alert=True)
        return
    waiting = app.db.pending_99(user.user_id)
    if waiting:
        created = _parse_ts(waiting["created_at"])
        await call.answer()
        await _replace(
            call,
            t(user.lang, "s99_waiting", request_id=waiting["id"], time=created.strftime("%H:%M")),
            back_menu(user.lang),
        )
        return
    request_id = app.db.request_99(user.user_id)
    if request_id is None:
        await call.answer(t(user.lang, "s99_used"), show_alert=True)
        return
    await _replace(
        call,
        t(
            user.lang,
            "s99_accepted",
            sep="—" * 18,
            request_id=request_id,
            time=_parse_ts(app.db.get_99(request_id)["created_at"]).strftime("%H:%M"),
        ),
        back_menu(user.lang),
    )
    await admin_module.notify_new_99(call.bot, request_id)


def _parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value)


async def _deliver_signal(call: CallbackQuery, user: User, *, timeframe: int) -> None:
    """Звичайна сесія: сканер → пошук → картка.

    Ліміт списується ЛИШЕ коли сигнал реально знайдено.
    """
    assert app is not None
    message = call.message
    await call.answer()
    if message is None:
        return
    await _scanner_animation(message, user.lang)

    try:
        market, digits = await _load_market(timeframe)
    except PocketUnavailable as exc:
        log.warning("немає даних: %s", exc)
        await message.edit_text(t(user.lang, "data_error"), reply_markup=back_menu(user.lang))
        return

    best = pick_best(market, digits)
    if best is None:
        await message.edit_text(t(user.lang, "no_signal"), reply_markup=back_menu(user.lang))
        return

    symbol, signal = best
    if not app.db.consume_session(user.user_id, app.config.daily_sessions):
        await message.edit_text(
            t(user.lang, "no_sessions", limit=app.config.daily_sessions), reply_markup=back_menu(user.lang)
        )
        return
    app.db.log_request(user.user_id, symbol, timeframe, signal.direction)

    asset = ASSETS_BY_SYMBOL[symbol]
    png = await asyncio.to_thread(
        render_signal,
        market[symbol],
        asset_title=asset.title,
        direction=signal.direction,
        timeframe_label=timeframe_label(timeframe),
        digits=asset.digits,
        demo=app.demo_data,
    )

    fresh = app.db.get_user(user.user_id) or user
    caption = _signal_caption(fresh, asset.title, signal, timeframe)
    await message.delete()
    await message.answer_photo(
        BufferedInputFile(png, filename="signal.png"),
        caption=caption,
        reply_markup=signal_menu(fresh.lang, app.links()["pocket_url"]),
    )


def _signal_caption(user: User, asset_title: str, signal, timeframe: int) -> str:
    assert app is not None
    lang = user.lang
    minutes = max(1, timeframe // 60)
    lines = [
        t(lang, "signal_title"),
        "",
        "—" * 18,
        "",
        t(lang, "signal_asset", asset=asset_title),
        t(lang, "signal_dir_buy" if signal.direction == "BUY" else "signal_dir_sell"),
        t(lang, "signal_tf", tf=timeframe_label(timeframe)),
        t(lang, "signal_exp", minutes=minutes),
        "",
        t(lang, "signal_quality", quality=signal.quality, bar=_quality_bar(signal.quality)),
        "",
        "—" * 18,
        "",
        t(lang, "signal_reasons"),
        "",
    ]
    lines += [t(lang, key, **params) for key, params in signal.reasons]
    lines += [
        "",
        t(
            lang,
            "signal_left",
            left=user.sessions_left(app.config.daily_sessions),
            limit=app.config.daily_sessions,
        ),
    ]
    return "\n".join(lines)


def _quality_bar(quality: int, cells: int = 10) -> str:
    filled = max(1, min(cells, round(quality / 100 * cells)))
    return "🟩" * filled + "⬜" * (cells - filled)


async def _load_market(timeframe: int, limit: int = 5):
    """Випадкова вибірка з `limit` активів."""
    assert app is not None
    symbols = [asset.symbol for asset in await app.source.assets()]
    random.shuffle(symbols)
    if limit:
        symbols = symbols[:limit]
    market = {}
    digits = {}
    for symbol in symbols:
        candles = await app.source.candles(symbol, timeframe, count=120)
        if len(candles) >= 40:
            market[symbol] = candles
            digits[symbol] = ASSETS_BY_SYMBOL[symbol].digits
    if not market:
        raise PocketUnavailable("жоден актив не віддав свічки")
    return market, digits


async def _scanner_animation(message: Message, lang: str) -> None:
    """Той самий «AI Market Scanner», що в оригіналі: одне повідомлення, три кадри."""
    title = t(lang, "scanner_title")
    lines = [title, "", "—" * 18, "", t(lang, "scan_step1")]
    frames = (
        lines,
        lines + [t(lang, "scan_step2")],
        lines + [t(lang, "scan_step2"), t(lang, "scan_step3"), "", "—" * 18, "", t(lang, "scan_working")],
    )
    for frame in frames:
        await message.edit_text("\n".join(frame))
        await asyncio.sleep(0.7)


async def _replace(call: CallbackQuery, text: str, markup) -> None:
    await call.answer()
    message = call.message
    if message is None:
        return
    try:
        if message.photo:
            await message.delete()
            await message.answer(text, reply_markup=markup)
        else:
            await message.edit_text(text, reply_markup=markup)
    except Exception:  # noqa: BLE001 - «message is not modified» тощо
        await message.answer(text, reply_markup=markup)


async def main() -> None:
    global app
    config = Config.load()
    if not config.token:
        raise SystemExit("BOT_TOKEN не заданий — скопіюй .env.example у .env")
    app = App(config)
    admin_module.app = app

    bot = Bot(config.token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    app.bot = bot
    keeper = asyncio.create_task(app.keep_po_fresh())
    dispatcher = Dispatcher()
    dispatcher.include_router(admin_module.router)
    dispatcher.include_router(router)
    log.info(
        "старт: дані=%s, база=%s, адмінів=%d, ліміт сесій=%d",
        app.source.name,
        app.db.engine,
        len(admin_module.admin_ids()),
        config.daily_sessions,
    )
    try:
        await dispatcher.start_polling(bot)
    finally:
        keeper.cancel()
        await app.source.close()


if __name__ == "__main__":
    asyncio.run(main())
