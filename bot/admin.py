"""Адмінка: /admin — список юзерів, скільки запитів з'їли, видача підписки.

Доступ тільки для ID зі змінної ADMIN_IDS.
"""
from __future__ import annotations

import asyncio
import contextlib
import html
import json
import logging
from datetime import datetime

from aiogram import Bot, F, Router
from aiogram.enums import ButtonStyle
from aiogram.filters import Command, CommandObject
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.keyboards import TIMEFRAMES, signal_menu
from core.chart import render_signal
from core.db import now
from core.i18n import t
from data import po_diag, po_session
from data.market import ASSETS, timeframe_label
from data.pocket import PocketUnavailable

log = logging.getLogger("signalbot.admin")
router = Router()

app = None  # підставляє bot/main.py на старті

PAGE_SIZE = 8
PLANS = (("Standard", 30), ("VIP", 30), ("Trial", 3))

# що адмін може міняти прямо з бота, без деплою
EDITABLE = ("channel_url", "trader_url", "pocket_url", "training_url",
            "plan1", "plan1_desc", "plan2", "plan2_desc")

# що саме адмін зараз вводить текстом: {admin_id: "search" | "ssid"}
_pending: dict[int, str] = {}


def admin_ids() -> set[int]:
    """Адміни зі змінної ADMIN_IDS плюс додані з бота командою /addadmin."""
    if app is None:
        return set()
    extra = {int(x) for x in app.db.get_setting("admin_ids_extra").split(",") if x.strip().isdigit()}
    return set(app.config.admin_ids) | extra


def _is_admin(user_id: int) -> bool:
    return user_id in admin_ids()


def _lang(user_id: int) -> str:
    user = app.db.get_user(user_id) if app else None
    return user.lang if user else "uk"


def _home_text(lang: str) -> str:
    stats = app.db.stats()
    return "\n\n".join(
        [
            t(lang, "admin_title"),
            t(lang, "admin_stats", backend=app.source.name, **stats),
        ]
    )


def _home_markup(lang: str):
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text=t(lang, "admin_btn_queue", n=len(app.db.list_99_pending())),
            callback_data="adm:q",
            style=ButtonStyle.DANGER,
        )
    )
    builder.row(
        InlineKeyboardButton(text=t(lang, "admin_btn_users"), callback_data="adm:users:0"),
        InlineKeyboardButton(text=t(lang, "admin_btn_stats"), callback_data="adm:home"),
    )
    builder.row(
        InlineKeyboardButton(text=t(lang, "admin_btn_search"), callback_data="adm:search"),
        InlineKeyboardButton(text=t(lang, "admin_btn_ssid"), callback_data="adm:ssid"),
    )
    builder.row(InlineKeyboardButton(text=t(lang, "admin_btn_links"), callback_data="adm:links"))
    return builder.as_markup()


def _current_value(key: str) -> str:
    if key.startswith("plan"):
        return app.plan(key)
    return app.links().get(key, "")


def _links_markup(lang: str):
    builder = InlineKeyboardBuilder()
    for key in EDITABLE:
        value = _current_value(key)
        mark = "✅" if value else "▫️"
        builder.row(
            InlineKeyboardButton(
                text=f"{mark} {t(lang, 'link_' + key)}", callback_data=f"adm:edit:{key}"
            )
        )
    builder.row(InlineKeyboardButton(text=t(lang, "btn_back"), callback_data="adm:home"))
    return builder.as_markup()


def _users_markup(lang: str, page: int, search: str = ""):
    total = app.db.count_users(search)
    pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(0, min(page, pages - 1))
    users = app.db.list_users(page * PAGE_SIZE, PAGE_SIZE, search)
    builder = InlineKeyboardBuilder()
    for user in users:
        name = f"@{user.username}" if user.username else (user.first_name or str(user.user_id))
        mark = "💎" if user.sub_active else "▫️"
        builder.row(
            InlineKeyboardButton(
                text=f"{mark} {name} · {user.requests_used}",
                callback_data=f"adm:u:{user.user_id}",
            )
        )
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"adm:users:{page - 1}"))
    nav.append(InlineKeyboardButton(text=f"{page + 1}/{pages}", callback_data="adm:noop"))
    if page < pages - 1:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"adm:users:{page + 1}"))
    builder.row(*nav)
    builder.row(InlineKeyboardButton(text=t(lang, "btn_back"), callback_data="adm:home"))
    return builder.as_markup(), t(lang, "admin_users_title", total=total, page=page + 1, pages=pages)


def _user_card(lang: str, user_id: int) -> tuple[str, object]:
    user = app.db.get_user(user_id)
    if user is None:
        return "—", _home_markup(lang)
    limit = app.config.daily_sessions
    sub = (
        f"{user.sub_plan or '—'} → {user.sub_until.strftime('%d.%m.%Y %H:%M')} UTC"
        if user.sub_active and user.sub_until
        else t(lang, "admin_sub_none")
    )
    text = t(
        lang,
        "admin_user_card",
        name=html.escape(f"@{user.username}" if user.username else (user.first_name or "—")),
        user_id=user.user_id,
        user_lang=user.lang,
        requests=user.requests_used,
        used=user.sessions_used(limit),
        limit=limit,
        sub=sub,
    )
    builder = InlineKeyboardBuilder()
    for plan, days in PLANS:
        builder.row(
            InlineKeyboardButton(
                text=t(lang, "admin_btn_grant", days=days, plan=plan),
                callback_data=f"adm:grant:{user.user_id}:{days}:{plan}",
            )
        )
    builder.row(
        InlineKeyboardButton(text=t(lang, "admin_btn_revoke"), callback_data=f"adm:revoke:{user.user_id}"),
        InlineKeyboardButton(text=t(lang, "admin_btn_reset"), callback_data=f"adm:reset:{user.user_id}"),
    )
    builder.row(
        InlineKeyboardButton(
            text=t(lang, "admin_btn_unban" if user.banned else "admin_btn_ban"),
            callback_data=f"adm:ban:{user.user_id}:{0 if user.banned else 1}",
        )
    )
    builder.row(InlineKeyboardButton(text=t(lang, "btn_back"), callback_data="adm:users:0"))
    return text, builder.as_markup()


@router.message(Command("admin"))
async def cmd_admin(message: Message) -> None:
    assert message.from_user is not None
    lang = _lang(message.from_user.id)
    if not _is_admin(message.from_user.id):
        await message.answer(t(lang, "admin_denied"))
        return
    await message.answer(_home_text(lang), reply_markup=_home_markup(lang))


@router.message(Command("podiag"))
async def cmd_podiag(message: Message) -> None:
    """Звідки бот бачить Pocket Option: DNS → TCP → TLS → HTTP по дзеркалах."""
    assert message.from_user is not None
    if not _is_admin(message.from_user.id):
        await message.answer(t(_lang(message.from_user.id), "admin_denied"))
        return
    status = await message.answer("🩺 Pocket Option: перевіряю доступ із сервера…")
    lines = await po_diag.run()
    await status.edit_text("🩺 <b>Pocket Option з сервера</b>\n\n" + "\n\n".join(html.escape(x) for x in lines))


@router.message(Command("addadmin", "deladmin"))
async def cmd_manage_admins(message: Message, command: CommandObject) -> None:
    """/addadmin 123 — дати доступ до адмінки; /deladmin 123 — забрати (крім тих, що з ADMIN_IDS)."""
    assert message.from_user is not None
    lang = _lang(message.from_user.id)
    if not _is_admin(message.from_user.id):
        await message.answer(t(lang, "admin_denied"))
        return
    arg = (command.args or "").strip()
    if not arg.isdigit():
        await message.answer(t(lang, "admin_ids_usage", ids=", ".join(map(str, sorted(admin_ids())))))
        return
    target = int(arg)
    extra = admin_ids() - set(app.config.admin_ids)
    if command.command == "addadmin":
        extra.add(target)
        key = "admin_added"
    elif target in app.config.admin_ids:
        await message.answer(t(lang, "admin_is_owner", user_id=target))
        return
    else:
        extra.discard(target)
        key = "admin_removed"
    app.db.set_setting("admin_ids_extra", ",".join(map(str, sorted(extra))))
    await message.answer(t(lang, key, user_id=target))


@router.callback_query(F.data.startswith("adm:"))
async def admin_callbacks(call: CallbackQuery) -> None:
    assert call.from_user is not None and call.data is not None
    lang = _lang(call.from_user.id)
    if not _is_admin(call.from_user.id):
        await call.answer(t(lang, "admin_denied"), show_alert=True)
        return

    parts = call.data.split(":")
    action = parts[1]
    await call.answer()

    if action == "home":
        await _edit(call, _home_text(lang), _home_markup(lang))
    elif action == "users":
        markup, title = _users_markup(lang, int(parts[2]))
        await _edit(call, title, markup)
    elif action == "u":
        text, markup = _user_card(lang, int(parts[2]))
        await _edit(call, text, markup)
    elif action == "grant":
        user_id, days, plan = int(parts[2]), int(parts[3]), parts[4]
        until = app.db.grant_sub(user_id, plan, days, call.from_user.id)
        await call.message.answer(
            t(lang, "admin_grant_done", plan=plan, days=days, until=until.strftime("%d.%m.%Y %H:%M"))
        )
        await _notify_user(call, user_id, plan, until)
        text, markup = _user_card(lang, user_id)
        await _edit(call, text, markup)
    elif action == "revoke":
        app.db.revoke_sub(int(parts[2]), call.from_user.id)
        await call.message.answer(t(lang, "admin_revoke_done"))
        text, markup = _user_card(lang, int(parts[2]))
        await _edit(call, text, markup)
    elif action == "reset":
        app.db.reset_today(int(parts[2]))
        await call.message.answer(t(lang, "admin_reset_done"))
        text, markup = _user_card(lang, int(parts[2]))
        await _edit(call, text, markup)
    elif action == "ban":
        user_id, flag = int(parts[2]), bool(int(parts[3]))
        app.db.set_banned(user_id, flag)
        await call.message.answer(t(lang, "admin_ban_done" if flag else "admin_unban_done"))
        text, markup = _user_card(lang, user_id)
        await _edit(call, text, markup)
    elif action == "links":
        await _edit(call, t(lang, "admin_links_title"), _links_markup(lang))
    elif action == "edit":
        key = parts[2]
        _pending[call.from_user.id] = f"link:{key}"
        await call.message.answer(
            t(
                lang,
                "admin_link_prompt",
                name=t(lang, "link_" + key),
                value=_current_value(key) or t(lang, "admin_link_empty"),
            )
        )
    elif action == "search":
        _pending[call.from_user.id] = "search"
        await call.message.answer(t(lang, "admin_search_prompt"))
    elif action == "ssid":
        _pending[call.from_user.id] = "ssid"
        await call.message.answer(t(lang, "admin_ssid_prompt"))
    elif action.startswith("q"):
        await _queue_callback(call, lang, action, parts[2:])


# ---------------- 99 Signal: черга запитів, сигнал видає аналітик ----------------
def _display_name(user_id: int) -> str:
    user = app.db.get_user(user_id)
    if user is None:
        return str(user_id)
    return html.escape(f"@{user.username}" if user.username else (user.first_name or str(user_id)))


def _waited(created_at: str, lang: str) -> str:
    minutes = max(0, int((now() - datetime.fromisoformat(created_at)).total_seconds() // 60))
    if minutes < 60:
        return t(lang, "ago_min", m=minutes)
    return t(lang, "ago_hour", h=minutes // 60, m=minutes % 60)


def _queue_view(lang: str):
    pending = app.db.list_99_pending()
    builder = InlineKeyboardBuilder()
    for request in pending:
        builder.row(
            InlineKeyboardButton(
                text=f"🔥 №{request['id']} · {_display_name(request['user_id'])} · "
                f"{_waited(request['created_at'], lang)}",
                callback_data=f"adm:qr:{request['id']}",
            )
        )
    builder.row(InlineKeyboardButton(text=t(lang, "btn_back"), callback_data="adm:home"))
    title = t(lang, "admin_queue_title", n=len(pending)) if pending else t(lang, "admin_queue_empty")
    return title, builder.as_markup()


def _request_text(lang: str, request: dict, step: str) -> str:
    return t(
        lang,
        "admin_99_card",
        request_id=request["id"],
        name=_display_name(request["user_id"]),
        user_id=request["user_id"],
        waited=_waited(request["created_at"], lang),
        step=step,
    )


async def _queue_callback(call: CallbackQuery, lang: str, action: str, args: list[str]) -> None:
    if action == "q":
        title, markup = _queue_view(lang)
        await _edit(call, title, markup)
        return

    request = app.db.get_99(int(args[0]))
    if request is None or request["status"] != "pending":
        await call.message.answer(t(lang, "admin_99_closed", request_id=args[0]))
        title, markup = _queue_view(lang)
        await _edit(call, title, markup)
        return
    rid = request["id"]
    builder = InlineKeyboardBuilder()

    if action == "qr":  # 1) актив
        for index, asset in enumerate(ASSETS):
            builder.button(text=asset.title.replace(" OTC", ""), callback_data=f"adm:qa:{rid}:{index}")
        builder.adjust(3)
        builder.row(InlineKeyboardButton(text=t(lang, "admin_btn_reject"), callback_data=f"adm:qx:{rid}"))
        builder.row(InlineKeyboardButton(text=t(lang, "btn_back"), callback_data="adm:q"))
        await _edit(call, _request_text(lang, request, t(lang, "admin_99_step_asset")), builder.as_markup())
    elif action == "qa":  # 2) напрямок
        index = int(args[1])
        builder.row(
            InlineKeyboardButton(text="🟢 BUY", callback_data=f"adm:qd:{rid}:{index}:B",
                                 style=ButtonStyle.SUCCESS),
            InlineKeyboardButton(text="🔴 SELL", callback_data=f"adm:qd:{rid}:{index}:S",
                                 style=ButtonStyle.DANGER),
        )
        builder.row(InlineKeyboardButton(text=t(lang, "btn_back"), callback_data=f"adm:qr:{rid}"))
        step = t(lang, "admin_99_step_dir", asset=ASSETS[index].title)
        await _edit(call, _request_text(lang, request, step), builder.as_markup())
    elif action == "qd":  # 3) експірація
        index, side = int(args[1]), args[2]
        builder.row(
            *[
                InlineKeyboardButton(
                    text=timeframe_label(seconds), callback_data=f"adm:qt:{rid}:{index}:{side}:{seconds}"
                )
                for seconds, _key in TIMEFRAMES
            ]
        )
        builder.row(InlineKeyboardButton(text=t(lang, "btn_back"), callback_data=f"adm:qa:{rid}:{index}"))
        step = t(lang, "admin_99_step_tf", asset=ASSETS[index].title, direction=_side(side))
        await _edit(call, _request_text(lang, request, step), builder.as_markup())
    elif action == "qt":  # 4) коментар або «без коментаря»
        index, side, seconds = int(args[1]), args[2], int(args[3])
        _pending[call.from_user.id] = f"s99:{rid}:{index}:{side}:{seconds}"
        builder.row(
            InlineKeyboardButton(
                text=t(lang, "admin_btn_no_comment"),
                callback_data=f"adm:qs:{rid}:{index}:{side}:{seconds}",
            )
        )
        builder.row(InlineKeyboardButton(text=t(lang, "btn_back"), callback_data=f"adm:qd:{rid}:{index}:{side}"))
        step = t(
            lang,
            "admin_99_step_comment",
            asset=ASSETS[index].title,
            direction=_side(side),
            tf=timeframe_label(seconds),
        )
        await _edit(call, _request_text(lang, request, step), builder.as_markup())
    elif action == "qs":
        _pending.pop(call.from_user.id, None)
        await _send_99(call.bot, call.message, lang, call.from_user.id, rid,
                       int(args[1]), args[2], int(args[3]), comment="")
    elif action == "qx":
        if app.db.close_99(rid, "rejected", call.from_user.id):
            app.db.reset_99(request["user_id"])
            user = app.db.get_user(request["user_id"])
            try:
                await call.bot.send_message(request["user_id"], t(user.lang if user else "uk", "s99_rejected"))
            except Exception as exc:  # noqa: BLE001 - юзер міг заблокувати бота
                log.info("не зміг повідомити %s про відмову 99: %s", request["user_id"], exc)
            await call.message.answer(t(lang, "admin_99_rejected", request_id=rid))
        title, markup = _queue_view(lang)
        await _edit(call, title, markup)


def _side(code: str) -> str:
    return "BUY" if code == "B" else "SELL"


async def _send_99(
    bot: Bot,
    reply_to: Message,
    lang: str,
    admin_id: int,
    request_id: int,
    index: int,
    side: str,
    seconds: int,
    comment: str,
) -> None:
    """Рендер картки з реальних свічок активу й відправка юзеру. Двічі не піде: close_99 атомарний."""
    request = app.db.get_99(request_id)
    asset = ASSETS[index]
    direction = _side(side)
    if request is None or not app.db.close_99(request_id, "sent", admin_id, asset.symbol, direction, seconds):
        await reply_to.answer(t(lang, "admin_99_closed", request_id=request_id))
        return
    user = app.db.get_user(request["user_id"])
    user_lang = user.lang if user else "uk"
    app.db.log_request(request["user_id"], asset.symbol, seconds, direction)

    lines = [
        t(user_lang, "s99_manual_badge"),
        "",
        "—" * 18,
        "",
        t(user_lang, "signal_asset", asset=asset.title),
        t(user_lang, "signal_dir_buy" if direction == "BUY" else "signal_dir_sell"),
        t(user_lang, "signal_tf", tf=timeframe_label(seconds)),
        t(user_lang, "signal_exp", minutes=max(1, seconds // 60)),
    ]
    if comment:
        lines += ["", "—" * 18, "", t(user_lang, "s99_comment"), html.escape(comment)]
    lines += ["", "—" * 18, "", t(user_lang, "s99_act_now")]
    caption = "\n".join(lines)
    markup = signal_menu(user_lang, app.links()["pocket_url"])

    try:
        png = None
        try:
            candles = await app.source.candles(asset.symbol, seconds, count=120)
            if len(candles) >= 20:
                png = await asyncio.to_thread(
                    render_signal,
                    candles,
                    asset_title=asset.title,
                    direction=direction,
                    timeframe_label=timeframe_label(seconds),
                    digits=asset.digits,
                    demo=app.demo_data,
                    header="99 SIGNAL",
                    subtitle="Analyst Signal",
                )
        except Exception as exc:  # noqa: BLE001 - без графіка сигнал все одно піде текстом
            log.warning("99: не вдалось намалювати графік %s: %s", asset.symbol, exc)
        if png and len(caption) <= 1024:
            await bot.send_photo(
                request["user_id"], BufferedInputFile(png, filename="signal.png"),
                caption=caption, reply_markup=markup,
            )
        elif png:
            await bot.send_photo(request["user_id"], BufferedInputFile(png, filename="signal.png"))
            await bot.send_message(request["user_id"], caption, reply_markup=markup)
        else:
            await bot.send_message(request["user_id"], caption, reply_markup=markup)
    except Exception as exc:  # noqa: BLE001
        await reply_to.answer(t(lang, "admin_99_undelivered", error=html.escape(str(exc))))
        return
    await reply_to.answer(
        t(
            lang,
            "admin_99_sent",
            request_id=request_id,
            name=_display_name(request["user_id"]),
            asset=asset.title,
            direction=direction,
            tf=timeframe_label(seconds),
        ),
        reply_markup=_queue_view(lang)[1],
    )


async def notify_new_99(bot: Bot, request_id: int) -> None:
    """Сповістити всіх адмінів про новий запит 99 Signal — з кнопкою одразу видати."""
    request = app.db.get_99(request_id)
    if request is None:
        return
    user = app.db.get_user(request["user_id"])
    queue = len(app.db.list_99_pending())
    for admin_id in admin_ids():
        lang = _lang(admin_id)
        sub = (
            f"{user.sub_plan or '—'} → {user.sub_until.strftime('%d.%m.%Y')}"
            if user and user.sub_active and user.sub_until
            else t(lang, "admin_sub_none")
        )
        builder = InlineKeyboardBuilder()
        builder.row(
            InlineKeyboardButton(
                text=t(lang, "admin_btn_issue"), callback_data=f"adm:qr:{request_id}",
                style=ButtonStyle.SUCCESS,
            )
        )
        try:
            await bot.send_message(
                admin_id,
                t(
                    lang,
                    "admin_new_99",
                    name=_display_name(request["user_id"]),
                    user_id=request["user_id"],
                    sub=sub,
                    request_id=request_id,
                    n=queue,
                ),
                reply_markup=builder.as_markup(),
            )
        except Exception as exc:  # noqa: BLE001 - адмін міг не натиснути /start
            log.warning("не зміг сповістити адміна %s про 99: %s", admin_id, exc)


@router.message(
    F.document,
    lambda message: message.from_user and _pending.get(message.from_user.id) == "ssid",
)
async def admin_key_file(message: Message) -> None:
    """Cookies з Cookie-Editor бувають довші за ліміт повідомлення — тому приймаємо й файлом."""
    assert message.from_user is not None and message.document is not None
    lang = _lang(message.from_user.id)
    _pending.pop(message.from_user.id, None)
    if (message.document.file_size or 0) > 512 * 1024:
        await message.answer(t(lang, "admin_key_bad", error="файл завеликий"))
        return
    buffer = await message.bot.download(message.document)
    await _save_po_key(message, lang, buffer.read().decode("utf-8", errors="replace"))


async def _save_po_key(message: Message, lang: str, value: str) -> None:
    """Ключ сокета або cookies сайту. Повідомлення з секретом одразу прибираємо з чату."""
    with contextlib.suppress(Exception):
        await message.delete()
    if not po_session.looks_like_cookies(value):
        app.db.set_setting("po_ssid", value)
        app.reload_source()
        # у відповіді не повторюємо сам ключ — щоб він не висів у чаті
        await message.answer(t(lang, "admin_ssid_saved") + f" ({app.source.name})")
        return
    try:
        cookies = po_session.parse_cookies(value)
    except PocketUnavailable as exc:
        await message.answer(t(lang, "admin_key_bad", error=html.escape(str(exc))))
        return
    previous = app.db.get_setting("po_cookies")
    app.db.set_setting("po_cookies", json.dumps(cookies))
    status = await message.answer(t(lang, "admin_cookies_checking", n=len(cookies)))
    try:
        await app.refresh_po_session(alert=False)
        app.reload_source()
        # перевірка до кінця: брокер реально віддає свічки на свіжий ключ
        candles = await app.source.candles(ASSETS[0].symbol, 60, count=30)
    except PocketUnavailable as exc:
        # старі робочі cookies не затираємо невдалими
        app.db.set_setting("po_cookies", previous)
        app.reload_source()
        await status.edit_text(t(lang, "admin_key_bad", error=html.escape(str(exc))))
        return
    await status.edit_text(
        t(lang, "admin_cookies_ok", backend=app.source.name, asset=ASSETS[0].title, n=len(candles))
    )


@router.message(F.text, lambda message: message.from_user and message.from_user.id in _pending)
async def admin_text_input(message: Message) -> None:
    assert message.from_user is not None
    lang = _lang(message.from_user.id)
    mode = _pending.pop(message.from_user.id, "")
    value = (message.text or "").strip()

    if mode == "ssid":
        await _save_po_key(message, lang, value)
        return

    if mode.startswith("link:"):
        key = mode.split(":", 1)[1]
        if key not in EDITABLE:
            return
        app.db.set_setting(key, value)
        await message.answer(
            t(lang, "admin_link_saved", name=t(lang, "link_" + key)),
            reply_markup=_links_markup(lang),
        )
        return

    if mode.startswith("s99:"):
        _, rid, index, side, seconds = mode.split(":")
        await _send_99(message.bot, message, lang, message.from_user.id,
                       int(rid), int(index), side, int(seconds), comment=value)
        return

    if mode == "search":
        markup, title = _users_markup(lang, 0, value)
        await message.answer(title, reply_markup=markup)


async def _notify_user(call: CallbackQuery, user_id: int, plan: str, until) -> None:
    user = app.db.get_user(user_id)
    if user is None:
        return
    try:
        await call.bot.send_message(
            user_id,
            t(user.lang, "user_got_sub", plan=plan, until=until.strftime("%d.%m.%Y %H:%M")),
        )
    except Exception as exc:  # noqa: BLE001 - юзер міг заблокувати бота
        log.info("не зміг повідомити %s про підписку: %s", user_id, exc)


async def _edit(call: CallbackQuery, text: str, markup) -> None:
    if call.message is None:
        return
    try:
        await call.message.edit_text(text, reply_markup=markup)
    except Exception:  # noqa: BLE001
        await call.message.answer(text, reply_markup=markup)
