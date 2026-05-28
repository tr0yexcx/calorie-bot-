"""Barcode scanning (image → code) and Open Food Facts lookup."""

from __future__ import annotations

import io
import logging
import os

import requests
from PIL import Image

logger = logging.getLogger(__name__)

TIMEOUT = 15

OFF_URLS = [
    "https://world.openfoodfacts.org/api/v0/product/{barcode}.json",
    "https://ru.openfoodfacts.org/api/v0/product/{barcode}.json",
]


def decode_barcode_from_bytes(data: bytes) -> str | None:
    """Return the first barcode string found in the image bytes, or None."""
    try:
        # On NixOS/Railway the shared lib may live in a non-standard path
        _patch_zbar_path()
        from pyzbar.pyzbar import decode as pyz_decode  # type: ignore

        img = Image.open(io.BytesIO(data))
        # Try original, then grayscale — improves detection rate
        for image in (img, img.convert("L")):
            results = pyz_decode(image)
            if results:
                return results[0].data.decode("utf-8")
    except Exception as exc:
        logger.warning("Barcode decode error: %s", exc)
    return None


def _patch_zbar_path() -> None:
    """Help pyzbar find libzbar.so on NixOS where libs aren't in /usr/lib."""
    import ctypes.util
    if ctypes.util.find_library("zbar"):
        return  # already findable
    # Search common Nix store paths
    import glob
    patterns = [
        "/nix/store/*/lib/libzbar.so*",
        "/nix/store/*/lib/libzbar.so",
    ]
    for pattern in patterns:
        matches = glob.glob(pattern)
        if matches:
            lib_dir = os.path.dirname(matches[0])
            ld_path = os.environ.get("LD_LIBRARY_PATH", "")
            if lib_dir not in ld_path:
                os.environ["LD_LIBRARY_PATH"] = f"{lib_dir}:{ld_path}"
            break


def lookup_barcode(barcode: str) -> dict | None:
    """
    Query Open Food Facts (tries world + ru mirrors).
    Returns a normalised dict: name, calories, protein, fat, carbs (per 100g)
    or None if not found / no nutriment data.
    """
    data = None
    for url_template in OFF_URLS:
        url = url_template.format(barcode=barcode)
        try:
            resp = requests.get(
                url,
                timeout=TIMEOUT,
                headers={"User-Agent": "CalorieBot/1.0"},
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("status") == 1:
                break  # found — stop trying mirrors
            data = None
        except Exception as exc:
            logger.warning("OFF request to %s failed: %s", url, exc)
            data = None

    if not data:
        return None

    product = data["product"]
    nutriments = product.get("nutriments", {})

    def _get(key: str) -> float:
        for candidate in (f"{key}_100g", key, f"{key}_serving"):
            val = nutriments.get(candidate)
            if val is not None:
                try:
                    f = float(val)
                    if f >= 0:
                        return f
                except (ValueError, TypeError):
                    pass
        return 0.0

    name = (
        product.get("product_name_ru")
        or product.get("product_name")
        or product.get("generic_name")
        or "Неизвестный продукт"
    ).strip()

    # Prefer kcal; fall back to kJ → kcal
    kcal = _get("energy-kcal")
    if not kcal:
        kj = _get("energy")
        kcal = round(kj / 4.184, 1) if kj else 0.0

    protein = _get("proteins")
    fat = _get("fat")
    carbs = _get("carbohydrates")

    logger.info(
        "OFF found: %s | kcal=%.1f prot=%.1f fat=%.1f carbs=%.1f",
        name, kcal, protein, fat, carbs,
    )

    return {
        "name": name,
        "calories": round(kcal, 1),
        "protein": round(protein, 1),
        "fat": round(fat, 1),
        "carbs": round(carbs, 1),
    }
