"""Text reports for /today, /week, /month."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

import database as db


def _progress_bar(value: float, total: float, width: int = 10) -> str:
    if total <= 0:
        return "▓" * width
    filled = min(int(round(value / total * width)), width)
    return "█" * filled + "░" * (width - filled)


def _sum_entries(entries) -> tuple[float, float, float, float]:
    cal = prot = fat = carbs = 0.0
    for e in entries:
        cal += e["calories"]
        prot += e["protein"]
        fat += e["fat"]
        carbs += e["carbs"]
    return round(cal, 1), round(prot, 1), round(fat, 1), round(carbs, 1)


def report_today(user_id: int) -> str:
    today = date.today()
    entries = db.get_entries_for_date(user_id, today)
    goal = db.get_goal(user_id)

    lines = [f"📅 *Дневник за {today.strftime('%d.%m.%Y')}*\n"]

    if not entries:
        lines.append("Записей нет. Добавьте приём пищи командой /log")
    else:
        for i, e in enumerate(entries, 1):
            t = e["logged_at"][11:16]
            lines.append(
                f"{i}. [{t}] *{e['description']}* — {e['grams']}г\n"
                f"   ⚡{e['calories']} ккал | Б:{e['protein']} Ж:{e['fat']} У:{e['carbs']}"
            )

    cal, prot, fat, carbs = _sum_entries(entries)
    lines.append(f"\n*Итого:* ⚡{cal} ккал | Б:{prot} Ж:{fat} У:{carbs}")

    if goal and goal["goal_cal"]:
        g = goal
        lines.append("\n*Прогресс к норме:*")
        for label, eaten, limit in (
            ("Ккал", cal, g["goal_cal"]),
            ("Белки", prot, g["goal_protein"]),
            ("Жиры", fat, g["goal_fat"]),
            ("Углеводы", carbs, g["goal_carbs"]),
        ):
            if limit:
                bar = _progress_bar(eaten, limit)
                lines.append(f"{label}: {bar} {eaten}/{limit}")

    return "\n".join(lines)


def report_week(user_id: int) -> str:
    today = date.today()
    start = today - timedelta(days=6)
    entries = db.get_entries_for_range(user_id, start, today)

    by_day: dict[str, list] = defaultdict(list)
    for e in entries:
        by_day[e["logged_at"][:10]].append(e)

    lines = [f"📊 *Сводка за 7 дней* ({start.strftime('%d.%m')} – {today.strftime('%d.%m')})\n"]
    lines.append(f"{'Дата':<12} {'Ккал':>7} {'Б':>6} {'Ж':>6} {'У':>6}")
    lines.append("─" * 42)

    totals = [0.0, 0.0, 0.0, 0.0]
    day_count = 0
    cur = start
    while cur <= today:
        key = cur.isoformat()
        day_entries = by_day.get(key, [])
        cal, prot, fat, carbs = _sum_entries(day_entries)
        label = cur.strftime("%a %d.%m")
        lines.append(f"{label:<12} {cal:>7.0f} {prot:>6.1f} {fat:>6.1f} {carbs:>6.1f}")
        if day_entries:
            for i, v in enumerate((cal, prot, fat, carbs)):
                totals[i] += v
            day_count += 1
        cur += timedelta(days=1)

    lines.append("─" * 42)
    if day_count:
        avg = [round(v / day_count, 1) for v in totals]
        lines.append(
            f"{'Среднее':<12} {avg[0]:>7.0f} {avg[1]:>6.1f} {avg[2]:>6.1f} {avg[3]:>6.1f}"
        )
        lines.append(
            f"{'Итого':<12} {totals[0]:>7.0f} {totals[1]:>6.1f} {totals[2]:>6.1f} {totals[3]:>6.1f}"
        )

    return "```\n" + "\n".join(lines) + "\n```"


def report_month(user_id: int) -> str:
    today = date.today()
    start = today - timedelta(days=29)
    entries = db.get_entries_for_range(user_id, start, today)

    # Group by ISO week
    by_week: dict[str, list] = defaultdict(list)
    for e in entries:
        d = date.fromisoformat(e["logged_at"][:10])
        week_key = d.strftime("%Y-W%V")
        by_week[week_key].append(e)

    lines = [f"📆 *Сводка за 30 дней* ({start.strftime('%d.%m')} – {today.strftime('%d.%m')})\n"]
    lines.append(f"{'Неделя':<12} {'Ккал':>7} {'Б':>6} {'Ж':>6} {'У':>6} {'Дней':>5}")
    lines.append("─" * 48)

    grand = [0.0, 0.0, 0.0, 0.0]
    total_days = 0

    for week_key in sorted(by_week):
        week_entries = by_week[week_key]
        cal, prot, fat, carbs = _sum_entries(week_entries)
        # count distinct days
        days_in_week = len({e["logged_at"][:10] for e in week_entries})
        lines.append(
            f"{week_key:<12} {cal:>7.0f} {prot:>6.1f} {fat:>6.1f} {carbs:>6.1f} {days_in_week:>5}"
        )
        for i, v in enumerate((cal, prot, fat, carbs)):
            grand[i] += v
        total_days += days_in_week

    lines.append("─" * 48)
    if total_days:
        avg = [round(v / total_days, 1) for v in grand]
        lines.append(
            f"{'Среднее/день':<12} {avg[0]:>7.0f} {avg[1]:>6.1f} {avg[2]:>6.1f} {avg[3]:>6.1f}"
        )
    else:
        lines.append("Данных нет.")

    return "```\n" + "\n".join(lines) + "\n```"
