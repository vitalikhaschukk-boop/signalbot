"""Клавіатури бота — один в один зі скрінів оригіналу, але з «Підписки» замість «Про бота»."""
from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from core.i18n import t

TIMEFRAMES: tuple[tuple[int, str], tuple[int, str], tuple[int, str], tuple[int, str]] = (
    (60, "tf_1"),
    (300, "tf_5"),
    (600, "tf_10"),
    (900, "tf_15"),
)


def main_menu(lang: str, channel_url: str, trader_url: str, pocket_url: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if channel_url:
        builder.row(
            InlineKeyboardButton(text=t(lang, "btn_channel"), url=channel_url),
            InlineKeyboardButton(text=t(lang, "btn_trader"), url=trader_url or channel_url),
        )
    if pocket_url:
        builder.row(
            InlineKeyboardButton(text=t(lang, "btn_pocket"), url=pocket_url),
            InlineKeyboardButton(text=t(lang, "btn_subs"), callback_data="menu:subs"),
        )
    else:
        builder.row(InlineKeyboardButton(text=t(lang, "btn_subs"), callback_data="menu:subs"))
    builder.row(InlineKeyboardButton(text=t(lang, "btn_lang"), callback_data="menu:lang"))
    builder.row(InlineKeyboardButton(text=t(lang, "btn_start_session"), callback_data="menu:session"))
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


def signal_menu(lang: str, pocket_url: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if pocket_url:
        builder.row(InlineKeyboardButton(text=t(lang, "btn_open_trade"), url=pocket_url))
    builder.row(InlineKeyboardButton(text=t(lang, "btn_new_session"), callback_data="menu:session"))
    builder.row(InlineKeyboardButton(text=t(lang, "btn_back"), callback_data="menu:home"))
    return builder.as_markup()
