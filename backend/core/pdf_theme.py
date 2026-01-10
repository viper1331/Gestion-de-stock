"""Theme utilities for PDF configuration."""
from __future__ import annotations

import re
from typing import Tuple

_HEX_COLOR_RE = re.compile(r"^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")
_RGB_COLOR_RE = re.compile(r"^(rgba?)\\(([^)]+)\\)$")


def parse_color(value: str) -> Tuple[float, float, float, float]:
    """Parse a color value into normalized RGBA (0..1) tuple.

    Supported formats:
    - #RGB, #RRGGBB, #RRGGBBAA
    - rgb(r,g,b)
    - rgba(r,g,b,a) where alpha is 0..1
    - transparent
    """
    if value is None:
        raise ValueError("Couleur manquante.")
    value = value.strip()
    if not value:
        raise ValueError("Couleur vide.")

    lower = value.lower()
    if lower == "transparent":
        return (0.0, 0.0, 0.0, 0.0)

    match = _HEX_COLOR_RE.match(value)
    if match:
        hex_value = match.group(1)
        if len(hex_value) == 3:
            r = int(hex_value[0] * 2, 16)
            g = int(hex_value[1] * 2, 16)
            b = int(hex_value[2] * 2, 16)
            a = 255
        elif len(hex_value) == 6:
            r = int(hex_value[0:2], 16)
            g = int(hex_value[2:4], 16)
            b = int(hex_value[4:6], 16)
            a = 255
        else:
            r = int(hex_value[0:2], 16)
            g = int(hex_value[2:4], 16)
            b = int(hex_value[4:6], 16)
            a = int(hex_value[6:8], 16)
        return (r / 255, g / 255, b / 255, a / 255)

    match = _RGB_COLOR_RE.match(lower)
    if match:
        mode = match.group(1)
        parts = [part.strip() for part in match.group(2).split(",")]
        if mode == "rgb" and len(parts) != 3:
            raise ValueError("Format rgb invalide.")
        if mode == "rgba" and len(parts) != 4:
            raise ValueError("Format rgba invalide.")
        try:
            r = float(parts[0])
            g = float(parts[1])
            b = float(parts[2])
        except ValueError as exc:
            raise ValueError("Composantes RGB invalides.") from exc
        if not (0 <= r <= 255 and 0 <= g <= 255 and 0 <= b <= 255):
            raise ValueError("Composantes RGB hors limite (0-255).")
        a = 1.0
        if mode == "rgba":
            try:
                a = float(parts[3])
            except ValueError as exc:
                raise ValueError("Alpha invalide.") from exc
            if not (0 <= a <= 1):
                raise ValueError("Alpha hors limite (0-1).")
        return (r / 255, g / 255, b / 255, a)

    raise ValueError("Format de couleur non supporté.")
