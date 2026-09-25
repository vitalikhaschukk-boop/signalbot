"""Клавіатури бота — один в один зі скрінів оригіналу, але з «Підписки» замість «Про бота»."""
from __future__ import annotations

from aiogram.enums import ButtonStyle
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from core.i18n import t

TIMEFRAMES: tuple[tuple[int, str], tuple[int, str], tuple[int, str], tuple[int, str]] = (
    (60, "tf_1"),
    (300, "tf_5"),
    (600, "tf_10"),
    (900, "tf_15"),
)


def main_menu(lang: str, links: dict[str, str]) -> InlineKeyboardMarkup:
    """Меню будується з посилань, які адмін міняє на льоту.

    Порожнє посилання = кнопки просто немає, меню не ламається.
    """
    builder = InlineKeyboardBuilder()

    top = []
    if links.get("channel_url"):
        top.append(InlineKeyboardButton(text=t(lang, "btn_channel"), url=links["channel_url"]))
    if links.get("trader_url"):
        top.append(InlineKeyboardButton(text=t(lang, "btn_trader"), url=links["trader_url"]))
    if top:
        builder.row(*top)

    second = []
    if links.get("pocket_url"):
        second.append(InlineKeyboardButton(text=t(lang, "btn_pocket"), url=links["pocket_url"]))
    second.append(InlineKeyboardButton(text=t(lang, "btn_subs"), callback_data="menu:subs"))
    builder.row(*second)

    third = []
    if links.get("training_url"):
        third.append(InlineKeyboardButton(text=t(lang, "btn_training"), url=links["training_url"]))
    third.append(InlineKeyboardButton(text=t(lang, "btn_lang"), callback_data="menu:lang"))
    builder.row(*third)

    # кольорові кнопки (Bot API 9.4+): золотого в Telegram нема — лише червоний/зелений/синій
    builder.row(
        InlineKeyboardButton(text=t(lang, "btn_99"), callback_data="menu:99", style=ButtonStyle.DANGER)
    )
    builder.row(
        InlineKeyboardButton(
            text=t(lang, "btn_start_session"), callback_data="menu:session", style=ButtonStyle.SUCCESS
        )
    )
    return builder.as_markup()


def language_menu(lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🇺🇦 Українська", callback_data="lang:uk"),
        InlineKeyboardButton(text="🇷🇺 Русский", callback_data="lang:ru"),
    )
    builder.row(InlineKeyboardButton(text=t(lang, "btn_back"), callback_data="menu:home"))
    return builder.as_markup()


def timeframe_menu(lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for seconds, key in TIMEFRAMES:
        builder.row(InlineKeyboardButton(text=t(lang, key), callback_data=f"tf:{seconds}"))
    builder.row(InlineKeyboardButton(text=t(lang, "btn_back"), callback_data="menu:home"))
    return builder.as_markup()


def back_menu(lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text=t(lang, "btn_back"), callback_data="menu:home"))
    return builder.as_markup()


def signal_menu(lang: str, pocket_url: str, repeat: str = "menu:session") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if pocket_url:
        builder.row(InlineKeyboardButton(text=t(lang, "btn_open_trade"), url=pocket_url))
    builder.row(InlineKeyboardButton(text=t(lang, "btn_new_session"), callback_data=repeat))
    builder.row(InlineKeyboardButton(text=t(lang, "btn_back"), callback_data="menu:home"))
    return builder.as_markup()
