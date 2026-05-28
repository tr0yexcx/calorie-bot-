"""All ConversationHandler states and command handlers."""

from __future__ import annotations

import logging
import re
from datetime import date

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

import barcode as bc
import database as db
import dishes as dsh
import products as prod
import reports

logger = logging.getLogger(__name__)

# ── ConversationHandler states ──────────────────────────────────────────────
(
    # /goal
    GOAL_CAL, GOAL_PROTEIN, GOAL_FAT, GOAL_CARBS,
    # /log
    LOG_PICK, LOG_GRAMS,
    # /create_dish
    DISH_NAME, DISH_ADD, DISH_CONFIRM,
    # /calc
    CALC_ADD,
    # barcode manual
    BARCODE_MANUAL_GRAMS, BARCODE_SAVE_MANUAL,
    BARCODE_MANUAL_CAL, BARCODE_MANUAL_PROT, BARCODE_MANUAL_FAT, BARCODE_MANUAL_CARBS,
) = range(16)

CANCEL_TEXT = "Действие отменено."


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _kbju_text(cal, prot, fat, carbs) -> str:
    return f"⚡{cal} ккал | Б:{prot} Ж:{fat} У:{carbs}"


def _parse_grams(text: str) -> float | None:
    text = text.strip().replace(",", ".")
    try:
        v = float(text)
        return v if v > 0 else None
    except ValueError:
        return None


def _product_kbju(user_id: int, name: str) -> tuple[float, float, float, float] | None:
    """Look up product in built-in DB then user's custom products."""
    kbju = prod.get_product(name)
    if kbju:
        return kbju
    rows = db.find_custom_products(user_id, name)
    for r in rows:
        if r["name"] == name.lower():
            return (r["calories"], r["protein"], r["fat"], r["carbs"])
    return None


async def _cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(CANCEL_TEXT)
    ctx.user_data.clear()
    return ConversationHandler.END


# ─────────────────────────────────────────────────────────────────────────────
# /start  /help
# ─────────────────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    db.ensure_user(update.effective_user.id)
    await update.message.reply_text(
        "👋 Привет! Я бот для подсчёта калорий.\n\n"
        "Команды:\n"
        "/find <название> — поиск продукта\n"
        "/log — добавить приём пищи\n"
        "/today — дневник за сегодня\n"
        "/week — сводка за 7 дней\n"
        "/month — сводка за 30 дней\n"
        "/reset — сбросить записи за сегодня\n"
        "/goal — установить дневную норму\n"
        "/create_dish — конструктор блюд\n"
        "/my_dishes — мои блюда\n"
        "/calc — быстрый калькулятор\n\n"
        "Отправь фото штрихкода или введи цифры — и я найду продукт!\n"
        "/cancel — отменить текущее действие"
    )


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await cmd_start(update, ctx)


# ─────────────────────────────────────────────────────────────────────────────
# /find
# ─────────────────────────────────────────────────────────────────────────────

async def cmd_find(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    query = " ".join(ctx.args).strip() if ctx.args else ""
    if not query:
        await update.message.reply_text("Использование: /find <название>")
        return

    results = prod.find_products(query)
    uid = update.effective_user.id
    custom = db.find_custom_products(uid, query)
    for r in custom:
        results.append((r["name"] + " ★", (r["calories"], r["protein"], r["fat"], r["carbs"])))

    if not results:
        await update.message.reply_text("Продукт не найден. Попробуйте другой запрос.")
        return

    lines = [f"🔍 Результаты по «{query}»:\n"]
    for name, (cal, prot, fat, carbs) in results[:20]:
        lines.append(f"• *{name}* — {_kbju_text(cal, prot, fat, carbs)} /100г")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


# ─────────────────────────────────────────────────────────────────────────────
# Barcode — photo or manual digits
# ─────────────────────────────────────────────────────────────────────────────

async def handle_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int | None:
    photo = update.message.photo[-1]
    file = await ctx.bot.get_file(photo.file_id)
    data = await file.download_as_bytearray()

    code = bc.decode_barcode_from_bytes(bytes(data))
    if not code:
        await update.message.reply_text(
            "Не удалось распознать штрихкод. Попробуйте сфотографировать чётче "
            "или введите цифры штрихкода вручную."
        )
        return None

    await update.message.reply_text(f"Штрихкод: `{code}` — ищу в базе…", parse_mode=ParseMode.MARKDOWN)
    return await _process_barcode(update, ctx, code)


async def handle_barcode_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int | None:
    code = update.message.text.strip()
    if not re.fullmatch(r"\d{8,14}", code):
        return None  # Not a barcode — ignore
    await update.message.reply_text(f"Ищу штрихкод `{code}`…", parse_mode=ParseMode.MARKDOWN)
    return await _process_barcode(update, ctx, code)


async def _process_barcode(update: Update, ctx: ContextTypes.DEFAULT_TYPE, code: str) -> int | None:
    uid = update.effective_user.id

    # Check user's custom db first
    custom = db.get_custom_product_by_barcode(uid, code)
    if custom:
        info = {
            "name": custom["name"],
            "calories": custom["calories"],
            "protein": custom["protein"],
            "fat": custom["fat"],
            "carbs": custom["carbs"],
        }
    else:
        info = bc.lookup_barcode(code)

    if info:
        ctx.user_data["barcode_info"] = info
        ctx.user_data["barcode_code"] = code
        text = (
            f"✅ *{info['name']}*\n"
            f"На 100г: {_kbju_text(info['calories'], info['protein'], info['fat'], info['carbs'])}\n\n"
            "Введите количество граммов чтобы добавить в дневник (или /cancel):"
        )
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)
        return BARCODE_MANUAL_GRAMS

    # Not found
    ctx.user_data["barcode_code"] = code
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("Ввести КБЖУ вручную", callback_data="barcode_manual_enter")],
        [InlineKeyboardButton("Отмена", callback_data="barcode_cancel")],
    ])
    await update.message.reply_text(
        f"Продукт со штрихкодом `{code}` не найден в базе Open Food Facts.",
        reply_markup=keyboard,
        parse_mode=ParseMode.MARKDOWN,
    )
    return None


async def barcode_grams_received(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    grams = _parse_grams(update.message.text)
    if grams is None:
        await update.message.reply_text("Введите положительное число граммов:")
        return BARCODE_MANUAL_GRAMS

    info = ctx.user_data["barcode_info"]
    cal, prot, fat, carbs = prod.calc_kbju(
        (info["calories"], info["protein"], info["fat"], info["carbs"]), grams
    )
    uid = update.effective_user.id
    db.log_entry(uid, info["name"], grams, cal, prot, fat, carbs)

    await update.message.reply_text(
        f"✅ Добавлено: *{info['name']}* {grams}г\n"
        f"{_kbju_text(cal, prot, fat, carbs)}",
        parse_mode=ParseMode.MARKDOWN,
    )
    ctx.user_data.clear()
    return ConversationHandler.END


async def barcode_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if query.data == "barcode_cancel":
        await query.edit_message_text(CANCEL_TEXT)
        ctx.user_data.clear()
        return ConversationHandler.END
    # barcode_manual_enter
    await query.edit_message_text(
        "Введите название продукта:"
    )
    return BARCODE_SAVE_MANUAL


async def barcode_save_name(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    ctx.user_data["manual_name"] = update.message.text.strip()
    await update.message.reply_text("Калории на 100г:")
    return BARCODE_MANUAL_CAL


async def barcode_save_cal(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    v = _parse_grams(update.message.text)
    if v is None:
        await update.message.reply_text("Введите число:")
        return BARCODE_MANUAL_CAL
    ctx.user_data["manual_cal"] = v
    await update.message.reply_text("Белки на 100г:")
    return BARCODE_MANUAL_PROT


async def barcode_save_prot(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    v = _parse_grams(update.message.text)
    if v is None:
        await update.message.reply_text("Введите число:")
        return BARCODE_MANUAL_PROT
    ctx.user_data["manual_prot"] = v
    await update.message.reply_text("Жиры на 100г:")
    return BARCODE_MANUAL_FAT


async def barcode_save_fat(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    v = _parse_grams(update.message.text)
    if v is None:
        await update.message.reply_text("Введите число:")
        return BARCODE_MANUAL_FAT
    ctx.user_data["manual_fat"] = v
    await update.message.reply_text("Углеводы на 100г:")
    return BARCODE_MANUAL_CARBS


async def barcode_save_carbs(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    v = _parse_grams(update.message.text)
    if v is None:
        await update.message.reply_text("Введите число:")
        return BARCODE_MANUAL_CARBS
    ctx.user_data["manual_carbs"] = v

    ud = ctx.user_data
    uid = update.effective_user.id
    db.save_custom_product(
        uid,
        ud["manual_name"],
        ud["manual_cal"],
        ud["manual_prot"],
        ud["manual_fat"],
        ud["manual_carbs"],
        barcode=ud.get("barcode_code"),
    )
    await update.message.reply_text(
        f"✅ Продукт *{ud['manual_name']}* сохранён в вашу базу!\n"
        f"{_kbju_text(ud['manual_cal'], ud['manual_prot'], ud['manual_fat'], ud['manual_carbs'])} /100г",
        parse_mode=ParseMode.MARKDOWN,
    )
    ctx.user_data.clear()
    return ConversationHandler.END


# ─────────────────────────────────────────────────────────────────────────────
# /goal
# ─────────────────────────────────────────────────────────────────────────────

async def cmd_goal(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    uid = update.effective_user.id
    g = db.get_goal(uid)
    current = ""
    if g and g["goal_cal"]:
        current = (
            f"Текущая норма: {_kbju_text(g['goal_cal'], g['goal_protein'], g['goal_fat'], g['goal_carbs'])}\n\n"
        )
    await update.message.reply_text(
        f"{current}Введите дневную норму калорий (или /cancel):"
    )
    return GOAL_CAL


async def goal_cal(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    v = _parse_grams(update.message.text)
    if v is None:
        await update.message.reply_text("Введите положительное число:")
        return GOAL_CAL
    ctx.user_data["goal_cal"] = v
    await update.message.reply_text("Норма белков (г):")
    return GOAL_PROTEIN


async def goal_protein(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    v = _parse_grams(update.message.text)
    if v is None:
        await update.message.reply_text("Введите число:")
        return GOAL_PROTEIN
    ctx.user_data["goal_protein"] = v
    await update.message.reply_text("Норма жиров (г):")
    return GOAL_FAT


async def goal_fat(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    v = _parse_grams(update.message.text)
    if v is None:
        await update.message.reply_text("Введите число:")
        return GOAL_FAT
    ctx.user_data["goal_fat"] = v
    await update.message.reply_text("Норма углеводов (г):")
    return GOAL_CARBS


async def goal_carbs(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    v = _parse_grams(update.message.text)
    if v is None:
        await update.message.reply_text("Введите число:")
        return GOAL_CARBS
    ud = ctx.user_data
    uid = update.effective_user.id
    db.set_goal(uid, ud["goal_cal"], ud["goal_protein"], ud["goal_fat"], v)
    await update.message.reply_text(
        f"✅ Норма установлена:\n"
        f"{_kbju_text(ud['goal_cal'], ud['goal_protein'], ud['goal_fat'], v)}",
        parse_mode=ParseMode.MARKDOWN,
    )
    ctx.user_data.clear()
    return ConversationHandler.END


# ─────────────────────────────────────────────────────────────────────────────
# /log — add diary entry
# ─────────────────────────────────────────────────────────────────────────────

async def cmd_log(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    uid = update.effective_user.id
    dishes = db.get_user_dishes(uid)

    buttons = []
    if dishes:
        buttons.append([InlineKeyboardButton("📚 Из моих блюд", callback_data="log_from_dishes")])
    buttons.append([InlineKeyboardButton("🔍 Найти продукт", callback_data="log_search")])
    buttons.append([InlineKeyboardButton("📷 Штрихкод", callback_data="log_barcode")])
    buttons.append([InlineKeyboardButton("❌ Отмена", callback_data="log_cancel")])

    await update.message.reply_text(
        "Что хотите добавить в дневник?",
        reply_markup=InlineKeyboardMarkup(buttons),
    )
    return LOG_PICK


async def log_pick_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "log_cancel":
        await query.edit_message_text(CANCEL_TEXT)
        ctx.user_data.clear()
        return ConversationHandler.END

    if data == "log_barcode":
        await query.edit_message_text(
            "Отправьте фото штрихкода или введите его цифры:"
        )
        ctx.user_data["log_mode"] = "barcode"
        return LOG_PICK

    if data == "log_search":
        await query.edit_message_text("Введите название продукта для поиска:")
        ctx.user_data["log_mode"] = "search"
        return LOG_PICK

    if data == "log_from_dishes":
        uid = query.from_user.id
        dishes = db.get_user_dishes(uid)
        keyboard = []
        for d in dishes:
            keyboard.append([
                InlineKeyboardButton(
                    f"{d['name']} ({d['total_grams']}г, ⚡{d['calories']}ккал)",
                    callback_data=f"log_dish_{d['id']}",
                )
            ])
        keyboard.append([InlineKeyboardButton("❌ Отмена", callback_data="log_cancel")])
        await query.edit_message_text(
            "Выберите блюдо:", reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return LOG_PICK

    if data.startswith("log_dish_"):
        dish_id = int(data.split("_")[2])
        uid = query.from_user.id
        dish = db.get_dish(dish_id, uid)
        if not dish:
            await query.edit_message_text("Блюдо не найдено.")
            return ConversationHandler.END
        ctx.user_data["log_dish"] = dict(dish)
        await query.edit_message_text(
            f"Порция блюда *{dish['name']}* (стандарт {dish['total_grams']}г).\n"
            "Введите граммы (или нажмите Enter чтобы добавить целую порцию):\n"
            "Напишите количество граммов:",
            parse_mode=ParseMode.MARKDOWN,
        )
        return LOG_GRAMS

    if data.startswith("log_prod_"):
        name = data[len("log_prod_"):]
        ctx.user_data["log_product"] = name
        await query.edit_message_text(f"Введите граммы для *{name}*:", parse_mode=ParseMode.MARKDOWN)
        return LOG_GRAMS

    return LOG_PICK


async def log_text_in_pick(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle text input during LOG_PICK (search query or barcode)."""
    text = update.message.text.strip()
    mode = ctx.user_data.get("log_mode")
    uid = update.effective_user.id

    # Always treat digit-only strings as barcodes regardless of mode
    if re.fullmatch(r"\d{8,14}", text):
        result = await _process_barcode(update, ctx, text)
        return result if result is not None else LOG_PICK

    if mode == "barcode":
        await update.message.reply_text("Введите корректный штрихкод (8-14 цифр) или отправьте фото:")
        return LOG_PICK

    # search mode
    results = prod.find_products(text)
    custom = db.find_custom_products(uid, text)
    all_results = [(r["name"], r["name"]) for r in custom] + [(n, n) for n, _ in results[:10]]

    if not all_results:
        await update.message.reply_text("Продукт не найден. Попробуйте другое название:")
        return LOG_PICK

    keyboard = []
    for label, cb_name in all_results[:10]:
        keyboard.append([InlineKeyboardButton(label, callback_data=f"log_prod_{cb_name}")])
    keyboard.append([InlineKeyboardButton("❌ Отмена", callback_data="log_cancel")])
    await update.message.reply_text(
        "Выберите продукт:", reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return LOG_PICK


async def log_grams(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    grams = _parse_grams(update.message.text)
    if grams is None:
        await update.message.reply_text("Введите положительное число граммов:")
        return LOG_GRAMS

    uid = update.effective_user.id

    if "log_dish" in ctx.user_data:
        d = ctx.user_data["log_dish"]
        factor = grams / d["total_grams"]
        cal = round(d["calories"] * factor, 1)
        prot = round(d["protein"] * factor, 1)
        fat = round(d["fat"] * factor, 1)
        carbs = round(d["carbs"] * factor, 1)
        name = d["name"]
    else:
        name = ctx.user_data.get("log_product", "Продукт")
        kbju = _product_kbju(uid, name)
        if kbju is None:
            await update.message.reply_text("Продукт не найден.")
            ctx.user_data.clear()
            return ConversationHandler.END
        cal, prot, fat, carbs = prod.calc_kbju(kbju, grams)

    db.log_entry(uid, name, grams, cal, prot, fat, carbs)
    await update.message.reply_text(
        f"✅ Добавлено: *{name}* — {grams}г\n{_kbju_text(cal, prot, fat, carbs)}",
        parse_mode=ParseMode.MARKDOWN,
    )
    ctx.user_data.clear()
    return ConversationHandler.END


# ─────────────────────────────────────────────────────────────────────────────
# /today  /week  /month  /reset
# ─────────────────────────────────────────────────────────────────────────────

async def cmd_today(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    db.ensure_user(uid)
    text = reports.report_today(uid)
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def cmd_week(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    db.ensure_user(uid)
    text = reports.report_week(uid)
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def cmd_month(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    db.ensure_user(uid)
    text = reports.report_month(uid)
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def cmd_reset(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    n = db.delete_entries_for_date(uid, date.today())
    await update.message.reply_text(f"🗑 Удалено записей за сегодня: {n}")


# ─────────────────────────────────────────────────────────────────────────────
# /create_dish
# ─────────────────────────────────────────────────────────────────────────────

async def cmd_create_dish(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    ctx.user_data["dish_draft"] = dsh.DishDraft()
    await update.message.reply_text(
        "🍳 Конструктор блюд\n\nВведите название блюда (или /cancel):"
    )
    return DISH_NAME


async def dish_name(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    name = update.message.text.strip()
    if not name:
        await update.message.reply_text("Введите непустое название:")
        return DISH_NAME
    ctx.user_data["dish_draft"].name = name
    await update.message.reply_text(
        f"Блюдо: *{name}*\n\n"
        "Добавляйте ингредиенты в формате:\n"
        "`название продукта граммы`\n"
        "Например: `курица грудка 200`\n\n"
        "Команды:\n"
        "• `готово` — сохранить блюдо\n"
        "• `отмена` / /cancel — отменить\n"
        "• `убрать` — удалить последний ингредиент\n"
        "• `список` — показать текущий состав",
        parse_mode=ParseMode.MARKDOWN,
    )
    return DISH_ADD


async def dish_add_ingredient(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip().lower()
    draft: dsh.DishDraft = ctx.user_data["dish_draft"]
    uid = update.effective_user.id

    if text in ("готово", "сохранить"):
        if not draft.ingredients:
            await update.message.reply_text("Добавьте хотя бы один ингредиент!")
            return DISH_ADD
        return await _finish_dish(update, ctx)

    if text in ("отмена", "cancel"):
        await update.message.reply_text(CANCEL_TEXT)
        ctx.user_data.clear()
        return ConversationHandler.END

    if text == "убрать":
        if draft.remove_last():
            await update.message.reply_text("Последний ингредиент удалён.\n" + draft.summary_text(), parse_mode=ParseMode.MARKDOWN)
        else:
            await update.message.reply_text("Список пуст.")
        return DISH_ADD

    if text == "список":
        if draft.ingredients:
            await update.message.reply_text(draft.summary_text(), parse_mode=ParseMode.MARKDOWN)
        else:
            await update.message.reply_text("Ингредиентов ещё нет.")
        return DISH_ADD

    # Parse "product name grams"
    parts = text.rsplit(None, 1)
    if len(parts) != 2:
        await update.message.reply_text("Формат: `название граммы`, например: `рис 150`", parse_mode=ParseMode.MARKDOWN)
        return DISH_ADD

    product_name, grams_str = parts
    grams = _parse_grams(grams_str)
    if grams is None:
        await update.message.reply_text("Неверное количество граммов.")
        return DISH_ADD

    kbju = _product_kbju(uid, product_name)
    if kbju is None:
        # Try finding close match
        results = prod.find_products(product_name)
        if results:
            closest = results[0][0]
            kbju = results[0][1]
            await update.message.reply_text(
                f"Точного совпадения нет, использую *{closest}*.", parse_mode=ParseMode.MARKDOWN
            )
            product_name = closest
        else:
            await update.message.reply_text(
                f"Продукт «{product_name}» не найден. Попробуйте другое название."
            )
            return DISH_ADD

    draft.add_ingredient(product_name, grams, kbju)
    cal, prot, fat, carbs = prod.calc_kbju(kbju, grams)
    await update.message.reply_text(
        f"✅ +{product_name} {grams}г ({_kbju_text(cal, prot, fat, carbs)})\n\n"
        f"Итого блюда: {_kbju_text(*draft.totals())}\n\n"
        "Продолжайте добавлять или напишите `готово`.",
        parse_mode=ParseMode.MARKDOWN,
    )
    return DISH_ADD


async def _finish_dish(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    draft: dsh.DishDraft = ctx.user_data["dish_draft"]
    uid = update.effective_user.id

    cal, prot, fat, carbs = draft.totals()
    total_g = draft.total_grams()
    ingredients = [(name, grams) for name, grams, _ in draft.ingredients]

    db.save_dish(uid, draft.name, cal, prot, fat, carbs, total_g, ingredients)

    await update.message.reply_text(
        draft.summary_text() + "\n\n✅ Блюдо сохранено в «Мои блюда»!",
        parse_mode=ParseMode.MARKDOWN,
    )
    ctx.user_data.clear()
    return ConversationHandler.END


# ─────────────────────────────────────────────────────────────────────────────
# /my_dishes
# ─────────────────────────────────────────────────────────────────────────────

async def cmd_my_dishes(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    dishes = db.get_user_dishes(uid)
    if not dishes:
        await update.message.reply_text(
            "У вас нет сохранённых блюд. Создайте первое с помощью /create_dish"
        )
        return

    keyboard = []
    for d in dishes:
        keyboard.append([
            InlineKeyboardButton(f"📋 {d['name']}", callback_data=f"dish_info_{d['id']}"),
            InlineKeyboardButton("🗑", callback_data=f"dish_del_{d['id']}"),
        ])
    await update.message.reply_text(
        "📚 *Мои блюда:*", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN
    )


async def my_dishes_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id

    if query.data.startswith("dish_info_"):
        dish_id = int(query.data.split("_")[2])
        dish = db.get_dish(dish_id, uid)
        if not dish:
            await query.edit_message_text("Блюдо не найдено.")
            return
        ings = db.get_dish_ingredients(dish_id)
        lines = [f"🍳 *{dish['name']}*\n"]
        for ing in ings:
            lines.append(f"  • {ing['product_name']} — {ing['grams']}г")
        lines.append(
            f"\nИтого {dish['total_grams']}г: {_kbju_text(dish['calories'], dish['protein'], dish['fat'], dish['carbs'])}"
        )
        await query.edit_message_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)

    elif query.data.startswith("dish_del_"):
        dish_id = int(query.data.split("_")[2])
        deleted = db.delete_dish(dish_id, uid)
        if deleted:
            await query.edit_message_text("🗑 Блюдо удалено.")
        else:
            await query.edit_message_text("Блюдо не найдено.")


# ─────────────────────────────────────────────────────────────────────────────
# /calc — quick calculator
# ─────────────────────────────────────────────────────────────────────────────

async def cmd_calc(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    ctx.user_data["calc_items"] = []
    await update.message.reply_text(
        "🧮 *Калькулятор КБЖУ*\n\n"
        "Вводите продукты в формате `название граммы`.\n"
        "Напишите `итого` для результата или /cancel для выхода.",
        parse_mode=ParseMode.MARKDOWN,
    )
    return CALC_ADD


async def calc_add(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip().lower()
    uid = update.effective_user.id
    items: list[tuple[str, float, float, float, float, float]] = ctx.user_data["calc_items"]

    if text in ("итого", "результат", "total"):
        if not items:
            await update.message.reply_text("Список пуст.")
            return CALC_ADD
        total_cal = sum(i[2] for i in items)
        total_prot = sum(i[3] for i in items)
        total_fat = sum(i[4] for i in items)
        total_carbs = sum(i[5] for i in items)
        lines = ["*Итог калькулятора:*\n"]
        for name, grams, cal, prot, fat, carbs in items:
            lines.append(f"• {name} {grams}г — {_kbju_text(cal, prot, fat, carbs)}")
        lines.append(f"\n*Всего:* {_kbju_text(round(total_cal,1), round(total_prot,1), round(total_fat,1), round(total_carbs,1))}")
        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)
        ctx.user_data.clear()
        return ConversationHandler.END

    parts = text.rsplit(None, 1)
    if len(parts) != 2:
        await update.message.reply_text("Формат: `название граммы`", parse_mode=ParseMode.MARKDOWN)
        return CALC_ADD

    product_name, grams_str = parts
    grams = _parse_grams(grams_str)
    if grams is None:
        await update.message.reply_text("Неверное кол-во граммов.")
        return CALC_ADD

    kbju = _product_kbju(uid, product_name)
    if kbju is None:
        results = prod.find_products(product_name)
        if results:
            product_name, kbju = results[0]
            await update.message.reply_text(
                f"Использую *{product_name}*.", parse_mode=ParseMode.MARKDOWN
            )
        else:
            await update.message.reply_text("Продукт не найден.")
            return CALC_ADD

    cal, prot, fat, carbs = prod.calc_kbju(kbju, grams)
    items.append((product_name, grams, cal, prot, fat, carbs))
    await update.message.reply_text(
        f"✅ {product_name} {grams}г — {_kbju_text(cal, prot, fat, carbs)}\n"
        "Продолжайте или напишите `итого`.",
        parse_mode=ParseMode.MARKDOWN,
    )
    return CALC_ADD


# ─────────────────────────────────────────────────────────────────────────────
# ConversationHandler registration
# ─────────────────────────────────────────────────────────────────────────────

def build_conv_handlers() -> list[ConversationHandler]:
    cancel_cmd = CommandHandler("cancel", _cancel)

    goal_conv = ConversationHandler(
        entry_points=[CommandHandler("goal", cmd_goal)],
        states={
            GOAL_CAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, goal_cal)],
            GOAL_PROTEIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, goal_protein)],
            GOAL_FAT: [MessageHandler(filters.TEXT & ~filters.COMMAND, goal_fat)],
            GOAL_CARBS: [MessageHandler(filters.TEXT & ~filters.COMMAND, goal_carbs)],
        },
        fallbacks=[cancel_cmd],
    )

    log_conv = ConversationHandler(
        entry_points=[CommandHandler("log", cmd_log)],
        states={
            LOG_PICK: [
                CallbackQueryHandler(log_pick_cb),
                MessageHandler(filters.PHOTO, handle_photo),
                MessageHandler(filters.TEXT & ~filters.COMMAND, log_text_in_pick),
            ],
            LOG_GRAMS: [MessageHandler(filters.TEXT & ~filters.COMMAND, log_grams)],
        },
        fallbacks=[cancel_cmd],
    )

    dish_conv = ConversationHandler(
        entry_points=[CommandHandler("create_dish", cmd_create_dish)],
        states={
            DISH_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, dish_name)],
            DISH_ADD: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, dish_add_ingredient),
                MessageHandler(filters.PHOTO, handle_photo),
            ],
        },
        fallbacks=[cancel_cmd],
    )

    calc_conv = ConversationHandler(
        entry_points=[CommandHandler("calc", cmd_calc)],
        states={
            CALC_ADD: [MessageHandler(filters.TEXT & ~filters.COMMAND, calc_add)],
        },
        fallbacks=[cancel_cmd],
    )

    barcode_conv = ConversationHandler(
        entry_points=[
            MessageHandler(filters.PHOTO, handle_photo),
            MessageHandler(filters.Regex(r"^\d{8,14}$"), handle_barcode_text),
        ],
        states={
            BARCODE_MANUAL_GRAMS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, barcode_grams_received)
            ],
            BARCODE_SAVE_MANUAL: [
                CallbackQueryHandler(barcode_cb),
                MessageHandler(filters.TEXT & ~filters.COMMAND, barcode_save_name),
            ],
            BARCODE_MANUAL_CAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, barcode_save_cal)],
            BARCODE_MANUAL_PROT: [MessageHandler(filters.TEXT & ~filters.COMMAND, barcode_save_prot)],
            BARCODE_MANUAL_FAT: [MessageHandler(filters.TEXT & ~filters.COMMAND, barcode_save_fat)],
            BARCODE_MANUAL_CARBS: [MessageHandler(filters.TEXT & ~filters.COMMAND, barcode_save_carbs)],
        },
        fallbacks=[cancel_cmd],
    )

    return [goal_conv, log_conv, dish_conv, calc_conv, barcode_conv]
