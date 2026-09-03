from __future__ import annotations

from io import BytesIO

from PIL import Image, ImageChops, ImageOps, UnidentifiedImageError


MAX_SIGNATURE_BYTES = 5 * 1024 * 1024
MAX_SIGNATURE_PIXELS = 12_000_000


def normalize_signature_image(data: bytes) -> bytes:
    """Crop and normalize a handwritten signature to a transparent PNG."""
    if not data:
        raise ValueError("O arquivo da assinatura está vazio.")
    if len(data) > MAX_SIGNATURE_BYTES:
        raise ValueError("A assinatura deve ter no máximo 5 MB.")

    try:
        with Image.open(BytesIO(data)) as source:
            if source.width * source.height > MAX_SIGNATURE_PIXELS:
                raise ValueError("A imagem da assinatura possui resolução excessiva.")
            image = ImageOps.exif_transpose(source).convert("RGBA")
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError("Envie uma imagem PNG ou JPG válida.") from exc

    grayscale = ImageOps.grayscale(image.convert("RGB"))
    ink_alpha = grayscale.point(lambda value: 0 if value >= 248 else min(255, (248 - value) * 7))
    original_alpha = image.getchannel("A")
    alpha = ImageChops.multiply(original_alpha, ink_alpha)
    image.putalpha(alpha)

    bounds = alpha.getbbox()
    if not bounds:
        raise ValueError("Não foi possível identificar os traços da assinatura.")
    image = image.crop(bounds)

    padding = max(10, round(max(image.size) * 0.035))
    canvas = Image.new("RGBA", (image.width + 2 * padding, image.height + 2 * padding), (255, 255, 255, 0))
    canvas.alpha_composite(image, (padding, padding))

    max_width, max_height = 1200, 400
    scale = min(1.0, max_width / canvas.width, max_height / canvas.height)
    if scale < 1:
        canvas = canvas.resize((round(canvas.width * scale), round(canvas.height * scale)), Image.Resampling.LANCZOS)

    output = BytesIO()
    canvas.save(output, format="PNG", optimize=True)
    return output.getvalue()
