"""Адмінка: /admin — список юзерів, скільки запитів з'їли, видача підписки.

Доступ тільки для ID зі змінної ADMIN_IDS.
"""
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from core.i18n import t

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


def _is_admin(user_id: int) -> bool:
    return app is not None and user_id in app.config.admin_ids


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
        name=(f"@{user.username}" if user.username else (user.first_name or "—")),
        user_id=user.user_id,
        lang=user.lang,
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


@router.message(F.text, lambda message: message.from_user and message.from_user.id in _pending)
async def admin_text_input(message: Message) -> None:
    assert message.from_user is not None
    lang = _lang(message.from_user.id)
    mode = _pending.pop(message.from_user.id, "")
    value = (message.text or "").strip()

    if mode == "ssid":
        app.db.set_setting("po_ssid", value)
        app.reload_source()
        # у відповіді не повторюємо сам ключ — щоб він не висів у чаті
        await message.answer(t(lang, "admin_ssid_saved") + f" ({app.source.name})")
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
