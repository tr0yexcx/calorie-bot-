"""Dish constructor helpers (pure logic, no Telegram)."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class DishDraft:
    name: str = ""
    ingredients: list[tuple[str, float, tuple[float, float, float, float]]] = field(
        default_factory=list
    )
    # Each ingredient: (product_name, grams, kbju_per_100g)

    def add_ingredient(
        self,
        product_name: str,
        grams: float,
        kbju_per_100: tuple[float, float, float, float],
    ) -> None:
        self.ingredients.append((product_name, grams, kbju_per_100))

    def remove_last(self) -> bool:
        if self.ingredients:
            self.ingredients.pop()
            return True
        return False

    def totals(self) -> tuple[float, float, float, float]:
        """Return (calories, protein, fat, carbs) for the whole dish."""
        cal = prot = fat = carbs = 0.0
        for _, grams, (c, p, f, cb) in self.ingredients:
            factor = grams / 100
            cal += c * factor
            prot += p * factor
            fat += f * factor
            carbs += cb * factor
        return round(cal, 1), round(prot, 1), round(fat, 1), round(carbs, 1)

    def total_grams(self) -> float:
        return sum(grams for _, grams, _ in self.ingredients)

    def summary_text(self) -> str:
        lines = [f"🍳 *{self.name}*\n"]
        for name, grams, (c, p, f, cb) in self.ingredients:
            factor = grams / 100
            lines.append(
                f"  • {name} — {grams}г "
                f"(⚡{round(c*factor,1)} Б{round(p*factor,1)} Ж{round(f*factor,1)} У{round(cb*factor,1)})"
            )
        cal, prot, fat, carbs = self.totals()
        total_g = self.total_grams()
        lines.append(
            f"\n*Итого {total_g}г:* ⚡{cal} ккал | Б:{prot} Ж:{fat} У:{carbs}"
        )
        per100 = kbju_per_100g(cal, prot, fat, carbs, total_g)
        lines.append(
            f"*На 100г:* ⚡{per100[0]} | Б:{per100[1]} Ж:{per100[2]} У:{per100[3]}"
        )
        return "\n".join(lines)


def kbju_per_100g(
    cal: float, prot: float, fat: float, carbs: float, total_grams: float
) -> tuple[float, float, float, float]:
    if total_grams <= 0:
        return (0.0, 0.0, 0.0, 0.0)
    f = 100 / total_grams
    return (round(cal * f, 1), round(prot * f, 1), round(fat * f, 1), round(carbs * f, 1))
