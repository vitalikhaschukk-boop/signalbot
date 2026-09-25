"""Двомовні тексти: українська + російська.

Ключ -> рядок. Підстановки через str.format(**kwargs).
Причини входу в сигналі теж живуть тут (ключі з префіксом reason_),
щоб движок сигналів не знав нічого про мову.
"""
from __future__ import annotations

LANGS = ("uk", "ru")
DEFAULT_LANG = "uk"

TEXTS: dict[str, dict[str, str]] = {
    "uk": {
        "welcome_title": "👋 Ласкаво просимо до {bot_name}",
        "profile_title": "👤 <b>Профіль користувача</b>",
        "profile_id": "🆔 ID: <code>{user_id}</code>",
        "profile_nick": "👤 Нік: {nick}",
        "sub_active": "💎 Підписка: <b>Активна</b>",
        "sub_inactive": "💎 Підписка: <b>Неактивна</b>",
        "sub_until": "📅 Діє до: <b>{until}</b> UTC",
        "sub_required": "🚫 Для запуску торгових сесій потрібна активна підписка.",
        "sessions_today": "🎯 Сесій сьогодні: <b>{used}/{limit}</b>",
        "ai_pitch": "📈 AI аналізує ринок у режимі реального часу та шукає найкращі точки входу для торгівлі.",
        "choose_action": "👇 Оберіть дію нижче.",
        "btn_channel": "🏴 Telegram канал",
        "btn_trader": "💬 Особистий трейдер",
        "btn_pocket": "🎁 Pocket Option",
        "btn_subs": "💎 Підписки",
        "btn_lang": "🌐 Мова",
        "btn_training": "🎓 Навчання",
        "btn_99": "🔥 99 Signal",
        "btn_start_session": "🚀 Почати сесію",
        "kb_home": "🏠 Головне меню",
        "kb_ready": "⌨️ Меню закріплено внизу.",
        "cmd_start": "🏠 Головне меню",
        "btn_back": "⬅️ Назад",
        "s99_title": "🔥 <b>99 SIGNAL</b>",
        "s99_intro": (
            "Один найсильніший сигнал на добу — бот бере його лише тоді, "
            "коли всі правила збігаються одночасно."
        ),
        "s99_used": "🔥 99 Signal на сьогодні вже забрано. Наступний — завтра.",
        "s99_none": (
            "🔍 Зараз ринок не дає сигналу такої сили. Спробуй пізніше — "
            "спроба не витрачена."
        ),
        "s99_badge": "🔥 <b>99 SIGNAL</b> — найсильніший збіг за добу",
        "lang_title": "🌐 <b>Оберіть мову</b>",
        "lang_saved": "✅ Мову змінено на українську.",
        "subs_title": "💎 <b>Підписки</b>",
        "subs_body": (
            "Доступ до сигналів видається за підпискою.\n\n"
            "<b>{plan1}</b>\n{plan1_desc}\n\n"
            "<b>{plan2}</b>\n{plan2_desc}\n\n"
            "Щоб оформити — напиши особистому трейдеру."
        ),
        "tf_title": "⏰ <b>Оберіть таймфрейм</b>",
        "tf_body": "Оберіть інтервал графіка для AI-аналізу.",
        "tf_1": "🟢 1 хвилина",
        "tf_5": "🔵 5 хвилин",
        "tf_10": "🟠 10 хвилин",
        "tf_15": "🟣 15 хвилин",
        "scanner_title": "🚀 <b>AI Market Scanner</b>",
        "scan_step1": "✅ Підключення до ринку виконано",
        "scan_step2": "✅ Торгові інструменти завантажено",
        "scan_step3": "✅ AI-робот готовий до пошуку сигналів",
        "scan_working": "🔄 Виконую аналіз ринкової ситуації...",
        "scan_mode": "🌍 Режим ринку: <b>{mode}</b>",
        "scan_asset": "📊 Аналізую <b>{asset}</b>...",
        "signal_title": "🔴 <b>ТОРГОВИЙ СИГНАЛ</b>",
        "signal_asset": "📊 Інструмент: <b>{asset}</b>",
        "signal_dir_buy": "🟢 Напрямок: <b>BUY</b>",
        "signal_dir_sell": "🔴 Напрямок: <b>SELL</b>",
        "signal_tf": "🕐 Таймфрейм: <b>{tf}</b>",
        "signal_exp": "⏱ Експірація: <b>{minutes} хв</b>",
        "signal_quality": "⚡ Якість сигналу: <b>{quality}%</b>\n{bar}",
        "signal_reasons": "📝 Причина входу:",
        "signal_left": "🎯 Залишилось сесій сьогодні: <b>{left}/{limit}</b>",
        "btn_open_trade": "🎯 Відкрити угоду",
        "btn_new_session": "🚀 Почати нову сесію",
        "no_sessions": "🎯 Сесії на сьогодні закінчились ({limit}/{limit}). Повертайся завтра.",
        "no_signal": "🔍 Зараз чіткої точки входу немає — ринок у боковику. Сесію не списано, спробуй ще раз.",
        "data_error": "⚠️ Немає зв'язку з ринком. Сесію не списано, спробуй за хвилину.",
        "banned": "🚫 Доступ до бота обмежено.",
        "reason_trend_up": "• Висхідний тренд і HH/HL",
        "reason_trend_down": "• Нисхідний тренд і LH/LL",
        "reason_pullback_up": "• Відкат до {level} і відбій",
        "reason_pullback_down": "• Відкат до {level} і розворот",
        "reason_rsi_oversold": "• RSI {value} — перепроданість",
        "reason_rsi_overbought": "• RSI {value} — перекупленість",
        "reason_volume_up": "• Обсяг зростає на зелених свічках",
        "reason_volume_down": "• Червоний обсяг зростає",
        "reason_stall_resistance": "• Нижчі максимуми і затухання під опором",
        "reason_bounce_support": "• Утримання підтримки {level}",
        "reason_continuation_up": "• Ймовірне продовження вгору в найближчі 1–3 свічки",
        "reason_continuation_down": "• Очікуємо короткий прокол вниз",
        # --- адмінка ---
        "admin_denied": "🚫 Ця команда не для тебе.",
        "admin_title": "🛠 <b>Адмін-панель</b>",
        "admin_stats": (
            "🔥 У черзі 99 Signal: <b>{queue}</b>\n"
            "👥 Користувачів: <b>{users}</b> (за добу +{new_24h})\n"
            "💎 З активною підпискою: <b>{active_subs}</b>\n"
            "📨 Запитів усього: <b>{requests}</b> (за добу {requests_24h})\n"
            "🛰 Джерело даних: <b>{backend}</b>"
        ),
        "admin_btn_users": "👥 Користувачі",
        "admin_btn_stats": "📊 Оновити статистику",
        "admin_btn_search": "🔎 Пошук",
        "admin_btn_ssid": "🔑 Оновити сесію Pocket Option",
        "admin_btn_links": "🔗 Посилання й тексти",
        "admin_links_title": (
            "🔗 <b>Посилання й тексти</b>\n\nТицяй, що міняємо — далі надішли нове значення "
            "одним повідомленням. Щоб прибрати кнопку з меню, надішли <code>-</code>."
        ),
        "admin_link_prompt": "Надішли нове значення для <b>{name}</b>.\nЗараз: <code>{value}</code>",
        "admin_link_saved": "✅ Збережено: <b>{name}</b>",
        "admin_link_empty": "порожньо",
        "link_channel_url": "Telegram канал",
        "link_trader_url": "Особистий трейдер",
        "link_pocket_url": "Pocket Option (реферал)",
        "link_training_url": "Навчання (посилання)",
        "link_plan1": "Тариф 1 — назва",
        "link_plan1_desc": "Тариф 1 — опис",
        "link_plan2": "Тариф 2 — назва",
        "link_plan2_desc": "Тариф 2 — опис",
        "admin_users_title": "👥 <b>Користувачі</b> ({total}) — стор. {page}/{pages}",
        "admin_user_card": (
            "👤 <b>{name}</b>\n"
            "🆔 <code>{user_id}</code>\n"
            "🌐 Мова: {user_lang}\n"
            "📨 Запитів з'їдено: <b>{requests}</b>\n"
            "🎯 Сьогодні: <b>{used}/{limit}</b>\n"
            "💎 Підписка: <b>{sub}</b>"
        ),
        "admin_grant_done": "✅ Видано підписку «{plan}» на {days} дн. до {until} UTC.",
        "admin_revoke_done": "✅ Підписку знято.",
        "admin_reset_done": "✅ Лічильник сесій на сьогодні обнулено.",
        "admin_ban_done": "✅ Доступ заблоковано.",
        "admin_unban_done": "✅ Доступ відновлено.",
        "admin_btn_grant": "💎 +{days} дн ({plan})",
        "admin_btn_revoke": "🚫 Зняти підписку",
        "admin_btn_reset": "♻️ Обнулити сесії",
        "admin_btn_ban": "⛔ Заблокувати",
        "admin_btn_unban": "✅ Розблокувати",
        "admin_search_prompt": "Надішли ID, @нік або частину імені:",
        "admin_ssid_prompt": (
            "🔑 Надішли <b>cookies</b> Pocket Option — файлом або текстом "
            "(Cookie-Editor → Export → JSON). Тоді бот сам оновлюватиме ключ, заходити на сайт не треба.\n\n"
            "Або старий спосіб — кадр <code>42[\"auth\",...]</code> з DevTools (протухає за кілька днів).\n\n"
            "Повідомлення з ключем бот одразу видалить із чату."
        ),
        "admin_ssid_saved": "✅ Сесію Pocket Option оновлено.",
        "admin_ids_usage": "👮 Адміни: <code>{ids}</code>\n\nДодати: <code>/addadmin ID</code>\nПрибрати: <code>/deladmin ID</code>",
        "admin_added": "✅ <code>{user_id}</code> тепер адмін. Хай натисне /start у боті, щоб отримувати сповіщення.",
        "admin_removed": "✅ <code>{user_id}</code> більше не адмін.",
        "admin_is_owner": "⚠️ <code>{user_id}</code> заданий у налаштуваннях сервера (ADMIN_IDS) — з бота його не прибрати.",
        "admin_cookies_checking": "⏳ Отримав {n} cookies, перевіряю вхід у Pocket Option…",
        "admin_cookies_ok": (
            "✅ <b>Cookies працюють.</b> Ключ отримано, {asset}: {n} свічок, джерело — <b>{backend}</b>.\n\n"
            "Далі бот сам оновлює ключ кожні 6 годин і щоразу, коли брокер його відкине."
        ),
        "admin_key_bad": "❌ Не вийшло: {error}\n\nСтарий ключ лишився без змін.",
        "po_alert": (
            "🔑 <b>Pocket Option: не вдалось оновити ключ</b>\n\n"
            "Причина: {reason}\n\n"
            "Залогінься в Pocket Option, вивантаж cookies заново (Cookie-Editor → Export) "
            "і надішли їх у /admin → 🔑. Поки що сигнали можуть не працювати."
        ),
        "admin_sub_none": "немає",
        "s99_accepted": "🔥 <b>99 SIGNAL</b>\n\n{sep}\n\n✅ <b>Запит прийнято!</b>\n\n🔬 Почався глибокий аналіз ринку: перебираємо активи й таймфрейми, щоб знайти найсильнішу точку входу дня.\n\n⏳ Сигнал прийде сюди протягом <b>1–5 годин</b>.\n🔔 Не вимикай сповіщення: сигнал прийде сюди, щойно аналіз завершиться.\n\n{sep}\n\n🧾 Запит <b>№{request_id}</b> · {time} UTC",
        "s99_waiting": "⏳ <b>Твій запит №{request_id} уже в роботі.</b>\n\nГлибокий аналіз ще триває — сигнал прийде протягом 1–5 годин з моменту запиту ({time} UTC).",
        "s99_manual_badge": "🔥 <b>99 SIGNAL</b> — результат глибокого аналізу",
        "s99_comment": "💬 <b>Причина входу:</b>",
        "s99_act_now": "⚡ Відкривай угоду одразу: сигнал актуальний кілька хвилин.",
        "s99_rejected": "😔 Сьогодні ринок не дав входу достатньої якості.\n\nСпробу повернуто — натисни 🔥 99 Signal ще раз, коли зручно.",
        "admin_btn_queue": "🔥 Черга 99 Signal ({n})",
        "admin_queue_title": "🔥 <b>Черга 99 Signal</b> — {n} чекають",
        "admin_queue_empty": "🔥 Черга 99 Signal порожня.",
        "admin_new_99": "🔔 <b>Новий запит 99 Signal</b>\n\n👤 {name} · <code>{user_id}</code>\n💎 {sub}\n🧾 Запит №{request_id}\n📋 У черзі всього: <b>{n}</b>\n\nЮзеру обіцяно сигнал протягом 1–5 годин.",
        "admin_btn_issue": "✍️ Видати сигнал",
        "admin_99_card": "🔥 <b>Запит №{request_id}</b>\n\n👤 {name} · <code>{user_id}</code>\n⏳ Чекає: <b>{waited}</b>\n\n{step}",
        "admin_99_step_asset": "1️⃣ Обери актив:",
        "admin_99_step_dir": "📊 {asset}\n\n2️⃣ Напрямок:",
        "admin_99_step_tf": "📊 {asset} · {direction}\n\n3️⃣ Експірація:",
        "admin_99_step_comment": "📊 {asset} · {direction} · {tf}\n\n4️⃣ Надішли коментар (причину входу) одним повідомленням — або тисни «Без коментаря».",
        "admin_btn_no_comment": "➡️ Без коментаря",
        "admin_btn_reject": "❌ Відхилити (повернути спробу)",
        "admin_99_sent": "✅ Сигнал №{request_id} надіслано {name}: {asset} {direction} {tf}.",
        "admin_99_closed": "ℹ️ Запит №{request_id} уже закрито.",
        "admin_99_rejected": "✅ Запит №{request_id} відхилено, спробу юзеру повернуто.",
        "admin_99_undelivered": "⚠️ Не вдалось доставити юзеру (заблокував бота?): {error}",
        "ago_min": "{m} хв",
        "ago_hour": "{h} год {m} хв",
        "user_got_sub": "💎 Тобі видано підписку «{plan}» до <b>{until}</b> UTC. Гарної торгівлі!",
    },
    "ru": {
        "welcome_title": "👋 Добро пожаловать в {bot_name}",
        "profile_title": "👤 <b>Профиль пользователя</b>",
        "profile_id": "🆔 ID: <code>{user_id}</code>",
        "profile_nick": "👤 Ник: {nick}",
        "sub_active": "💎 Подписка: <b>Активна</b>",
        "sub_inactive": "💎 Подписка: <b>Неактивна</b>",
        "sub_until": "📅 Действует до: <b>{until}</b> UTC",
        "sub_required": "🚫 Для запуска торговых сессий нужна активная подписка.",
        "sessions_today": "🎯 Сессий сегодня: <b>{used}/{limit}</b>",
        "ai_pitch": "📈 AI анализирует рынок в реальном времени и ищет лучшие точки входа для торговли.",
        "choose_action": "👇 Выберите действие ниже.",
        "btn_channel": "🏴 Telegram канал",
        "btn_trader": "💬 Личный трейдер",
        "btn_pocket": "🎁 Pocket Option",
        "btn_subs": "💎 Подписки",
        "btn_lang": "🌐 Язык",
        "btn_training": "🎓 Обучение",
        "btn_99": "🔥 99 Signal",
        "btn_start_session": "🚀 Начать сессию",
        "kb_home": "🏠 Главное меню",
        "kb_ready": "⌨️ Меню закреплено внизу.",
        "cmd_start": "🏠 Главное меню",
        "btn_back": "⬅️ Назад",
        "s99_title": "🔥 <b>99 SIGNAL</b>",
        "s99_intro": (
            "Один самый сильный сигнал в сутки — бот берёт его только тогда, "
            "когда все правила совпадают одновременно."
        ),
        "s99_used": "🔥 99 Signal на сегодня уже забран. Следующий — завтра.",
        "s99_none": (
            "🔍 Сейчас рынок не даёт сигнала такой силы. Попробуй позже — "
            "попытка не потрачена."
        ),
        "s99_badge": "🔥 <b>99 SIGNAL</b> — самое сильное совпадение за сутки",
        "lang_title": "🌐 <b>Выберите язык</b>",
        "lang_saved": "✅ Язык изменён на русский.",
        "subs_title": "💎 <b>Подписки</b>",
        "subs_body": (
            "Доступ к сигналам выдаётся по подписке.\n\n"
            "<b>{plan1}</b>\n{plan1_desc}\n\n"
            "<b>{plan2}</b>\n{plan2_desc}\n\n"
            "Чтобы оформить — напиши личному трейдеру."
        ),
        "tf_title": "⏰ <b>Выберите таймфрейм</b>",
        "tf_body": "Выберите интервал графика для AI-анализа.",
        "tf_1": "🟢 1 минута",
        "tf_5": "🔵 5 минут",
        "tf_10": "🟠 10 минут",
        "tf_15": "🟣 15 минут",
        "scanner_title": "🚀 <b>AI Market Scanner</b>",
        "scan_step1": "✅ Подключение к рынку выполнено",
        "scan_step2": "✅ Торговые инструменты загружены",
        "scan_step3": "✅ AI-робот готов к поиску сигналов",
        "scan_working": "🔄 Выполняю анализ рыночной ситуации...",
        "scan_mode": "🌍 Режим рынка: <b>{mode}</b>",
        "scan_asset": "📊 Анализирую <b>{asset}</b>...",
        "signal_title": "🔴 <b>ТОРГОВЫЙ СИГНАЛ</b>",
        "signal_asset": "📊 Инструмент: <b>{asset}</b>",
        "signal_dir_buy": "🟢 Направление: <b>BUY</b>",
        "signal_dir_sell": "🔴 Направление: <b>SELL</b>",
        "signal_tf": "🕐 Таймфрейм: <b>{tf}</b>",
        "signal_exp": "⏱ Экспирация: <b>{minutes} мин</b>",
        "signal_quality": "⚡ Качество сигнала: <b>{quality}%</b>\n{bar}",
        "signal_reasons": "📝 Причина входа:",
        "signal_left": "🎯 Осталось сессий сегодня: <b>{left}/{limit}</b>",
        "btn_open_trade": "🎯 Открыть сделку",
        "btn_new_session": "🚀 Начать новую сессию",
        "no_sessions": "🎯 Сессии на сегодня закончились ({limit}/{limit}). Возвращайся завтра.",
        "no_signal": "🔍 Сейчас чёткой точки входа нет — рынок в боковике. Сессия не списана, попробуй ещё раз.",
        "data_error": "⚠️ Нет связи с рынком. Сессия не списана, попробуй через минуту.",
        "banned": "🚫 Доступ к боту ограничен.",
        "reason_trend_up": "• Восходящий тренд и HH/HL",
        "reason_trend_down": "• Нисходящий тренд и LH/LL",
        "reason_pullback_up": "• Откат к {level} и отбой",
        "reason_pullback_down": "• Откат к {level} и разворот",
        "reason_rsi_oversold": "• RSI {value} — перепроданность",
        "reason_rsi_overbought": "• RSI {value} — перекупленность",
        "reason_volume_up": "• Объём растёт на зелёных свечах",
        "reason_volume_down": "• Красный объём растёт",
        "reason_stall_resistance": "• Более низкие максимумы и затухание под сопротивлением",
        "reason_bounce_support": "• Удержание поддержки {level}",
        "reason_continuation_up": "• Вероятно продолжение вверх в ближайшие 1–3 свечи",
        "reason_continuation_down": "• Ожидаем короткий прокол вниз",
        # --- админка ---
        "admin_denied": "🚫 Эта команда не для тебя.",
        "admin_title": "🛠 <b>Админ-панель</b>",
        "admin_stats": (
            "🔥 В очереди 99 Signal: <b>{queue}</b>\n"
            "👥 Пользователей: <b>{users}</b> (за сутки +{new_24h})\n"
            "💎 С активной подпиской: <b>{active_subs}</b>\n"
            "📨 Запросов всего: <b>{requests}</b> (за сутки {requests_24h})\n"
            "🛰 Источник данных: <b>{backend}</b>"
        ),
        "admin_btn_users": "👥 Пользователи",
        "admin_btn_stats": "📊 Обновить статистику",
        "admin_btn_search": "🔎 Поиск",
        "admin_btn_ssid": "🔑 Обновить сессию Pocket Option",
        "admin_btn_links": "🔗 Ссылки и тексты",
        "admin_links_title": (
            "🔗 <b>Ссылки и тексты</b>\n\nЖми, что меняем — дальше пришли новое значение "
            "одним сообщением. Чтобы убрать кнопку из меню, пришли <code>-</code>."
        ),
        "admin_link_prompt": "Пришли новое значение для <b>{name}</b>.\nСейчас: <code>{value}</code>",
        "admin_link_saved": "✅ Сохранено: <b>{name}</b>",
        "admin_link_empty": "пусто",
        "link_channel_url": "Telegram канал",
        "link_trader_url": "Личный трейдер",
        "link_pocket_url": "Pocket Option (реферал)",
        "link_training_url": "Обучение (ссылка)",
        "link_plan1": "Тариф 1 — название",
        "link_plan1_desc": "Тариф 1 — описание",
        "link_plan2": "Тариф 2 — название",
        "link_plan2_desc": "Тариф 2 — описание",
        "admin_users_title": "👥 <b>Пользователи</b> ({total}) — стр. {page}/{pages}",
        "admin_user_card": (
            "👤 <b>{name}</b>\n"
            "🆔 <code>{user_id}</code>\n"
            "🌐 Язык: {user_lang}\n"
            "📨 Запросов съедено: <b>{requests}</b>\n"
            "🎯 Сегодня: <b>{used}/{limit}</b>\n"
            "💎 Подписка: <b>{sub}</b>"
        ),
        "admin_grant_done": "✅ Выдана подписка «{plan}» на {days} дн. до {until} UTC.",
        "admin_revoke_done": "✅ Подписка снята.",
        "admin_reset_done": "✅ Счётчик сессий на сегодня обнулён.",
        "admin_ban_done": "✅ Доступ заблокирован.",
        "admin_unban_done": "✅ Доступ восстановлен.",
        "admin_btn_grant": "💎 +{days} дн ({plan})",
        "admin_btn_revoke": "🚫 Снять подписку",
        "admin_btn_reset": "♻️ Обнулить сессии",
        "admin_btn_ban": "⛔ Заблокировать",
        "admin_btn_unban": "✅ Разблокировать",
        "admin_search_prompt": "Пришли ID, @ник или часть имени:",
        "admin_ssid_prompt": (
            "🔑 Пришли <b>cookies</b> Pocket Option — файлом или текстом "
            "(Cookie-Editor → Export → JSON). Тогда бот сам будет обновлять ключ, заходить на сайт не нужно.\n\n"
            "Или старый способ — кадр <code>42[\"auth\",...]</code> из DevTools (протухает за несколько дней).\n\n"
            "Сообщение с ключом бот сразу удалит из чата."
        ),
        "admin_ssid_saved": "✅ Сессия Pocket Option обновлена.",
        "admin_ids_usage": "👮 Админы: <code>{ids}</code>\n\nДобавить: <code>/addadmin ID</code>\nУбрать: <code>/deladmin ID</code>",
        "admin_added": "✅ <code>{user_id}</code> теперь админ. Пусть нажмёт /start в боте, чтобы получать уведомления.",
        "admin_removed": "✅ <code>{user_id}</code> больше не админ.",
        "admin_is_owner": "⚠️ <code>{user_id}</code> задан в настройках сервера (ADMIN_IDS) — из бота его не убрать.",
        "admin_cookies_checking": "⏳ Получил {n} cookies, проверяю вход в Pocket Option…",
        "admin_cookies_ok": (
            "✅ <b>Cookies работают.</b> Ключ получен, {asset}: {n} свечей, источник — <b>{backend}</b>.\n\n"
            "Дальше бот сам обновляет ключ каждые 6 часов и каждый раз, когда брокер его отклонит."
        ),
        "admin_key_bad": "❌ Не получилось: {error}\n\nСтарый ключ остался без изменений.",
        "po_alert": (
            "🔑 <b>Pocket Option: не удалось обновить ключ</b>\n\n"
            "Причина: {reason}\n\n"
            "Залогинься в Pocket Option, выгрузи cookies заново (Cookie-Editor → Export) "
            "и пришли их в /admin → 🔑. Пока что сигналы могут не работать."
        ),
        "admin_sub_none": "нет",
        "s99_accepted": "🔥 <b>99 SIGNAL</b>\n\n{sep}\n\n✅ <b>Запрос принят!</b>\n\n🔬 Начался глубокий анализ рынка: перебираем активы и таймфреймы, чтобы найти самую сильную точку входа дня.\n\n⏳ Сигнал придёт сюда в течение <b>1–5 часов</b>.\n🔔 Не отключай уведомления: сигнал придёт сюда, как только анализ завершится.\n\n{sep}\n\n🧾 Запрос <b>№{request_id}</b> · {time} UTC",
        "s99_waiting": "⏳ <b>Твой запрос №{request_id} уже в работе.</b>\n\nГлубокий анализ ещё идёт — сигнал придёт в течение 1–5 часов с момента запроса ({time} UTC).",
        "s99_manual_badge": "🔥 <b>99 SIGNAL</b> — результат глубокого анализа",
        "s99_comment": "💬 <b>Причина входа:</b>",
        "s99_act_now": "⚡ Открывай сделку сразу: сигнал актуален несколько минут.",
        "s99_rejected": "😔 Сегодня рынок не дал входа достаточного качества.\n\nПопытка возвращена — нажми 🔥 99 Signal ещё раз, когда удобно.",
        "admin_btn_queue": "🔥 Очередь 99 Signal ({n})",
        "admin_queue_title": "🔥 <b>Очередь 99 Signal</b> — ждут {n}",
        "admin_queue_empty": "🔥 Очередь 99 Signal пуста.",
        "admin_new_99": "🔔 <b>Новый запрос 99 Signal</b>\n\n👤 {name} · <code>{user_id}</code>\n💎 {sub}\n🧾 Запрос №{request_id}\n📋 В очереди всего: <b>{n}</b>\n\nЮзеру обещан сигнал в течение 1–5 часов.",
        "admin_btn_issue": "✍️ Выдать сигнал",
        "admin_99_card": "🔥 <b>Запрос №{request_id}</b>\n\n👤 {name} · <code>{user_id}</code>\n⏳ Ждёт: <b>{waited}</b>\n\n{step}",
        "admin_99_step_asset": "1️⃣ Выбери актив:",
        "admin_99_step_dir": "📊 {asset}\n\n2️⃣ Направление:",
        "admin_99_step_tf": "📊 {asset} · {direction}\n\n3️⃣ Экспирация:",
        "admin_99_step_comment": "📊 {asset} · {direction} · {tf}\n\n4️⃣ Пришли комментарий (причину входа) одним сообщением — или жми «Без комментария».",
        "admin_btn_no_comment": "➡️ Без комментария",
        "admin_btn_reject": "❌ Отклонить (вернуть попытку)",
        "admin_99_sent": "✅ Сигнал №{request_id} отправлен {name}: {asset} {direction} {tf}.",
        "admin_99_closed": "ℹ️ Запрос №{request_id} уже закрыт.",
        "admin_99_rejected": "✅ Запрос №{request_id} отклонён, попытка юзеру возвращена.",
        "admin_99_undelivered": "⚠️ Не удалось доставить юзеру (заблокировал бота?): {error}",
        "ago_min": "{m} мин",
        "ago_hour": "{h} ч {m} мин",
        "user_got_sub": "💎 Тебе выдана подписка «{plan}» до <b>{until}</b> UTC. Хорошей торговли!",
    },
}


def t(lang: str, key: str, **kwargs: object) -> str:
    table = TEXTS.get(lang) or TEXTS[DEFAULT_LANG]
    template = table.get(key) or TEXTS[DEFAULT_LANG].get(key) or key
    return template.format(**kwargs) if kwargs else template
