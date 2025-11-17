"""Utilitaires de génération de QR codes."""

from io import BytesIO
from typing import Optional

import qrcode
from PIL import Image, ImageDraw, ImageFont


def generate_qr_png(data: str, *, label: Optional[str] = None) -> BytesIO:
    """Génère une image PNG de QR code pour la donnée fournie.

    Args:
        data: Texte ou URL à encoder dans le QR code.
        label: Texte optionnel à afficher sous le QR code.
    """

    qr = qrcode.QRCode(border=2, box_size=8)
    qr.add_data(data)
    qr.make(fit=True)
    qr_image = qr.make_image(fill_color="black", back_color="white").convert("RGB")

    if label:
        font = ImageFont.load_default()
        draw = ImageDraw.Draw(qr_image)
        label_bbox = draw.textbbox((0, 0), label, font=font)
        label_height = label_bbox[3] - label_bbox[1]
        label_width = label_bbox[2] - label_bbox[0]
        width, height = qr_image.size
        padded_height = height + label_height + 12
        combined = Image.new("RGB", (width, padded_height), color="white")
        combined.paste(qr_image, (0, 0))
        draw = ImageDraw.Draw(combined)
        text_x = (width - label_width) // 2
        text_y = height + 8
        draw.text((text_x, text_y), label, fill="black", font=font)
        qr_image = combined

    buffer = BytesIO()
    qr_image.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer
