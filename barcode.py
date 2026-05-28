"""Barcode scanning (image → code) and Open Food Facts lookup."""

from __future__ import annotations

import io
import logging

import requests
from PIL import Image

logger = logging.getLogger(__name__)

OFF_URL = "https://world.openfoodfacts.org/api/v0/product/{barcode}.json"
TIMEOUT = 10


def decode_barcode_from_bytes(data: bytes) -> str | None:
    """Return the first barcode string found in the image bytes, or None."""
    try:
        from pyzbar.pyzbar import decode as pyz_decode  # type: ignore

        img = Image.open(io.BytesIO(data))
        results = pyz_decode(img)
        if results:
            return results[0].data.decode("utf-8")
    except Exception as exc:
        logger.warning("Barcode decode error: %s", exc)
    return None


def lookup_barcode(barcode: str) -> dict | None:
    """
    Query Open Food Facts.
    Returns a normalised dict with keys:
        name, calories, protein, fat, carbs   (all per 100 g)
    or None if not found / no nutriment data.
    """
    try:
        resp = requests.get(OFF_URL.format(barcode=barcode), timeout=TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.warning("OFF request failed: %s", exc)
        return None

    if data.get("status") != 1:
        return None

    product = data["product"]
    nutriments = product.get("nutriments", {})

    def _get(key: str) -> float:
        for candidate in (f"{key}_100g", key):
            val = nutriments.get(candidate)
            if val is not None:
                try:
                    return float(val)
                except (ValueError, TypeError):
                    pass
        return 0.0

    name = (
        product.get("product_name_ru")
        or product.get("product_name")
        or product.get("generic_name")
        or "Неизвестный продукт"
    )

    calories = _get("energy-kcal") or _get("energy") / 4.184 if _get("energy") else 0.0

    return {
        "name": name,
        "calories": round(calories, 1),
        "protein": round(_get("proteins"), 1),
        "fat": round(_get("fat"), 1),
        "carbs": round(_get("carbohydrates"), 1),
    }
