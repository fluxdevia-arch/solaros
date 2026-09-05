from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Mapping

from PIL import Image, ImageOps, UnidentifiedImageError


PROJECT_ROOT = Path(__file__).resolve().parents[1]

APP_NAME = "SolarOS By OnGrid"
APP_LOGO = PROJECT_ROOT / "assets" / "ongrid_logo_transparent.png"

MAX_BRAND_LOGO_BYTES = 5 * 1024 * 1024
MAX_BRAND_LOGO_PIXELS = 16_000_000


def normalize_brand_logo(data: bytes) -> bytes:
    """Validate and resize a company logo while preserving PNG transparency."""
    if not data:
        raise ValueError("O arquivo do logotipo está vazio.")
    if len(data) > MAX_BRAND_LOGO_BYTES:
        raise ValueError("O logotipo deve ter no máximo 5 MB.")
    try:
        with Image.open(BytesIO(data)) as source:
            if source.width * source.height > MAX_BRAND_LOGO_PIXELS:
                raise ValueError("A imagem do logotipo possui resolução excessiva.")
            image = ImageOps.exif_transpose(source).convert("RGBA")
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError("Envie um logotipo PNG ou JPG válido.") from exc

    image.thumbnail((1800, 700), Image.Resampling.LANCZOS)
    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()


def configured_app_name(settings: Mapping | None) -> str:
    if settings:
        value = str(settings.get("app_name") or "").strip()
        if value:
            return value
    return APP_NAME


def configured_logo(settings: Mapping | None):
    if settings and settings.get("brand_logo"):
        return bytes(settings["brand_logo"])
    return APP_LOGO
