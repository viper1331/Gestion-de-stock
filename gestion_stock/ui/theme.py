"""Modern ttk theming utilities for Gestion Stock Pro."""

from __future__ import annotations

import colorsys
import os
from functools import lru_cache
from typing import Optional


try:  # Optional ttkbootstrap support
    import ttkbootstrap as ttkb
except Exception:  # pragma: no cover - optional dependency
    ttkb = None  # type: ignore

import tkinter as tk
from tkinter import PhotoImage, Tk
from tkinter import ttk

PALETTE_DARK = {
    "bg": "#0b1220",
    "fg": "#e6e8eb",
    "muted": "#9aa3af",
    "border": "#1f2937",
    "primary": "#2563eb",
    "success": "#22c55e",
    "warning": "#f59e0b",
    "danger": "#ef4444",
    "info": "#06b6d4",
    "surface": "#111827",
    "surface2": "#0f172a",
    "row_alt": "#0d1530",
    "selection": "#1f64ff",
    "accent": "#8b5cf6",
}

PALETTE_LIGHT = {
    "bg": "#f3f4f6",
    "fg": "#111827",
    "muted": "#4b5563",
    "border": "#d1d5db",
    "primary": "#1d4ed8",
    "success": "#16a34a",
    "warning": "#d97706",
    "danger": "#dc2626",
    "info": "#0ea5e9",
    "surface": "#ffffff",
    "surface2": "#e5e7eb",
    "row_alt": "#f9fafb",
    "selection": "#2f6bff",
    "accent": "#7c3aed",
}

PALETTE = PALETTE_DARK

FONTS = {
    "base": ("Segoe UI", 10),
    "mono": ("Cascadia Mono", 10),
}

FALLBACK_ICONS: dict[str, tuple[str, ...]] = {
    "barcode.png": (
        "iVBORw0KGgoAAAANSUhEUgAAABgAAAAYCAYAAADgdz34AAAAM0lEQVR4nGNgGAWjgFLA",
        "iC7gHZr8nxIDt66ei2ImEyWGEQNGLRi1YNSCUQtGhAWjgCAAAP9WBB4a98xrAAAAAElF",
        "TkSuQmCC",
    ),
    "camera.png": (
        "iVBORw0KGgoAAAANSUhEUgAAABgAAAAYCAYAAADgdz34AAAAi0lEQVR4nGNgGAUDDRgJ",
        "KfAOTf5PSM3W1XNxmsNEqotIBUPfAoywIybMCQHkOKG5D1iIVbg7sRBDzHV+P2UWwLzK",
        "tu0K1mDbnVjI8MtLh5GBAXfQEgwiXIYTK4/XAkKaiVE39PPBMLcAlgQJAXzq8FrgHZr8",
        "n1Bmcp3fj7d4ISqIcFlCcU4m1bDhCQCPqS0XyuSGMAAAAABJRU5ErkJggg==",
    ),
    "download.png": (
        "iVBORw0KGgoAAAANSUhEUgAAABgAAAAYCAYAAADgdz34AAAAdklEQVR4nGNgGAXDHjAS",
        "q1A1+fV/dLHbc0UJ6mci1UWkglELRoAFOJMZtmRJCGBLtjh9QEwaJ0Y93iAi1hJ86gjG",
        "ASFLCMkPXCSzbbuCEsnya8Ux1DwMfonC/+WlQ3wkEzIMnY8LkBREMEOJNZxkC0g1fBQQ",
        "BQCEZyMDwUq24gAAAABJRU5ErkJggg==",
    ),
    "edit.png": (
        "iVBORw0KGgoAAAANSUhEUgAAABgAAAAYCAYAAADgdz34AAAAaUlEQVR4nGNgGAWjYBSM",
        "giEG2LZd+U+qHiZSDSfVEkZSDEcHv7x0COon6AN8LibGN1hd4B2ajFXj7sRCrIbg8wnR",
        "cYAP4PMJVSyAWYLNIqpZgGwRMp+FWgbjigeykykxSZQkQE4upgsAAETxKBlU8iPzAAAA",
        "AElFTkSuQmCC",
    ),
    "file-csv.png": (
        "iVBORw0KGgoAAAANSUhEUgAAABgAAAAYCAYAAADgdz34AAABBElEQVR4nO3VoUqEQRQF",
        "4M/VsIhdxSBOEXyFAdEHsBi0/c9gUDAYFYNg8gn+DYoYzCYNA1aLcarNZFzU4IZl3cVZ",
        "2EWFPWWGO4dz5p6ZYZjgtzE1aCGk6mNYsRzrb3qNYUWGxd826BfJSA1K8P8NZkpIJVkP",
        "wtg7KH1ot4ho4gmbOdbtkKoz7HfxtnCEZSzlWL+XdrCGDaziEdMhVes94jCLSyxgncIz",
        "wHGO9XNnfgAhVXO9pBzr65CqRZxjB/elHeQ+tTtcdxdCqmKO9QsesB1S1Sw1WOmz23aO",
        "9W5P+bQzXmEeJ6URtUKqWgW8t854gwvsjfqaHkKO9auvCBtj/w8m+BGf0uA/v6dIrcoA",
        "AAAASUVORK5CYII=",
    ),
    "file-pdf.png": (
        "iVBORw0KGgoAAAANSUhEUgAAABgAAAAYCAYAAADgdz34AAAAyklEQVR4nO2VPQrCQBBG",
        "nyJiuycQexvvMGfRLoJtbFOKop1nmdrSxgMIglgueIFYmGJRo7OQoEJeOfvtfMzM/kDD",
        "t2mVLXiRPDaZU33K145NEstvG7xqSaUGFv7foGMRWXpdRu0VxFy0HDgDC6e68iJD4PCg",
        "SZzqJlyzVpABPWAPLL3IoES39iLjcF9Mi7q8qbjgAiRhwGqQAldgBMyc6rFEdwLC6lLT",
        "KQIypzo36PpAaJ5V+poWTIAd9yFHzcDC1Kluw0Dt/0HDR24ecjMPjbzBTgAAAABJRU5E",
        "rkJggg==",
    ),
    "plus.png": (
        "iVBORw0KGgoAAAANSUhEUgAAABgAAAAYCAYAAADgdz34AAAAQUlEQVR4nGNgGAUDDRhJ",
        "Uaya/Po/jH17rihReplIdRGpYNSCEWABRlJDTorkAuQkPAyDCB8YzcmjFgyMBaOAIAAA",
        "dg4MIBd8OTUAAAAASUVORK5CYII=",
    ),
    "save.png": (
        "iVBORw0KGgoAAAANSUhEUgAAABgAAAAYCAYAAADgdz34AAAAQklEQVR4nGNgGAXDHjBi",
        "E1RNfv2fXANvzxVFMZOJXIOIBaMWjFowBCxgIVYhegZiYCAuQ46gICK3fBr6QTQKBh4A",
        "AA7ECpR8nNOCAAAAAElFTkSuQmCC",
    ),
    "search.png": (
        "iVBORw0KGgoAAAANSUhEUgAAABgAAAAYCAYAAADgdz34AAAAhElEQVR4nGNgGAUDDRgJ",
        "KWDbduU/utgvLx2C+mCAiVTD8YmTZAEhQ4i1BKtX0TUjBwk+OWwAwweEDEDnE/IJ3jjA",
        "5TqqRTI1wMBaQJNkSigSSU1FOCVJcSU+S3AGESkpBZ9jqJZMcVlCtCuxAWIKQoqSKTE+",
        "oTgfECpKqAZISXWjAAUAAMhFSTtdMuCZAAAAAElFTkSuQmCC",
    ),
    "settings.png": (
        "iVBORw0KGgoAAAANSUhEUgAAABgAAAAYCAYAAADgdz34AAAAh0lEQVR4nGNgGAXUBt6h",
        "yf+9Q5P/E6ueiZaOoYsFjMQqxBYsW1fPJaifKB/gCnNi4oKgBYQMISSP14vompGDBJ8c",
        "URZgMwBZDJ2PyxKi4gCbYd6hyf+JiWQWfK4mFaD7kIFhIPMBteJg4FIRLoOwAXyRTTAO",
        "CKUUQvJEJ1NyDCcLjLz6YOgDAF/cVimDQh80AAAAAElFTkSuQmCC",
    ),
    "trash.png": (
        "iVBORw0KGgoAAAANSUhEUgAAABgAAAAYCAYAAADgdz34AAAAU0lEQVR4nGNgGAUDDRjx",
        "Sb53cflPrEGCe/ZgNYuJVBeRCoaxBaSEPz71wziI0IHgnj2MyEkRnU+xBeSCUQtGLaAc",
        "4EzHpBYVDAzYi+yhH0RDHwAA/HUTN2NLgq8AAAAASUVORK5CYII=",
    ),
    "upload.png": (
        "iVBORw0KGgoAAAANSUhEUgAAABgAAAAYCAYAAADgdz34AAAAbklEQVR4nGNgGAVDDnyd",
        "x/2fFPVM5BhOiiVEW4BuKLGWEGUBLsOIsYSkICIHELSAkCsJyeO1gNhwxqcOpwWkJkdc",
        "6hkpMYA76StB/TSP5FFAEOCMJLZtV0hKRQwMDAy/vHQwzBv4nDzoLRgFBAEAEpYqEtlF",
        "51AAAAAASUVORK5CYII=",
    ),
    "voice-off.png": (
        "iVBORw0KGgoAAAANSUhEUgAAABgAAAAYCAYAAADgdz34AAAAp0lEQVR4nO2UsRGDMAxF",
        "H2zgCbKMO2o6OuZKly51Oi/DBB4BKjgOLFsyKf0r7ji9hyQbaGnRJHq/Su+6UvEwzmIx",
        "wCcux7ML4cbrSwItHNKdVAuucPhjB1p4lcACNwtS8Mm9sjU3s3RqLPDf931wVR3UfLla",
        "8AReFDyFQ+Ympy6NC6Hbd3Secy7JDiS4BqgSXGG1cCj87KL3q3bm0siyS7Yu1CxoAdgA",
        "+CdBF6v+7IIAAAAASUVORK5CYII=",
    ),
    "voice.png": (
        "iVBORw0KGgoAAAANSUhEUgAAABgAAAAYCAYAAADgdz34AAAAUklEQVR4nGNgGAWjgFLA",
        "SEgB27Yr/wmp+eWlg9McJlJdRCoYtWDgLcCIfWJSDSGAnKqGfhDR3AKSAdu2K/9Jiaeh",
        "H0R4CztSggJXgTf0g2joAwDU0BE6VJXxhQAAAABJRU5ErkJggg==",
    ),
    "warning.png": (
        "iVBORw0KGgoAAAANSUhEUgAAABgAAAAYCAYAAADgdz34AAAAdUlEQVR4nGNgGAVDDnyd",
        "x/2fFPVMtHIIWRbAXE+KLwaPD9BdTawvaO4DRmIUwVzLlfgFLvZtPg8DAwMDA3fSV7xm",
        "DHwcEAprQvID6wNiUwo+dQPnA1LLHFzqB8YHpLoen77BkZNh4P///3AXMjIykqR3FOAE",
        "AG/vLRiAEb9bAAAAAElFTkSuQmCC",
    ),
}


@lru_cache(maxsize=32)
def _pct(color: str, factor: float = 1.06) -> str:
    """Adjust color lightness by the given factor."""

    color = color.lstrip("#")
    r, g, b = int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16)
    h, l, s = colorsys.rgb_to_hls(r / 255.0, g / 255.0, b / 255.0)
    l = max(0.0, min(1.0, l * factor))
    r2, g2, b2 = colorsys.hls_to_rgb(h, l, s)
    return f"#{int(r2 * 255):02x}{int(g2 * 255):02x}{int(b2 * 255):02x}"


def _palette(mode: str) -> dict[str, str]:
    return PALETTE_DARK if mode == "dark" else PALETTE_LIGHT


def _configure_buttons(style: ttk.Style, palette: dict[str, str]) -> None:
    def _btn(name: str, base: str, foreground: str = "#ffffff") -> None:
        style.configure(
            f"{name}.TButton",
            background=base,
            foreground=foreground,
            focuscolor=palette["selection"],
            anchor="center",
            borderwidth=0,
            padding=(14, 8),
        )
        style.map(
            f"{name}.TButton",
            background=[
                ("disabled", _pct(base, 0.9)),
                ("pressed", _pct(base, 0.92)),
                ("active", _pct(base, 1.08)),
            ],
            foreground=[("disabled", palette["muted"])],
        )

    _btn("Primary", palette["primary"])
    _btn("Success", palette["success"])
    _btn("Warning", palette["warning"])
    _btn("Danger", palette["danger"])
    _btn("Info", palette["info"])
    _btn("Secondary", _pct(palette["surface"], 0.85), foreground=palette["fg"])


def _configure_fields(style: ttk.Style, palette: dict[str, str]) -> None:
    common = dict(
        fieldbackground=palette["surface2"],
        background=palette["surface2"],
        foreground=palette["fg"],
        bordercolor=palette["border"],
        lightcolor=palette["primary"],
        darkcolor=palette["border"],
        insertcolor=palette["fg"],
        padding=6,
        borderwidth=1,
    )
    for widget_style in ("TEntry", "TCombobox", "TSpinbox"):
        style.configure(widget_style, **common)
        style.map(
            widget_style,
            fieldbackground=[("disabled", palette["surface"]), ("focus", palette["surface"])],
            bordercolor=[("focus", palette["primary"]), ("!focus", palette["border"])],
        )

    style.configure("TMenubutton", background=palette["surface"], foreground=palette["fg"], padding=(10, 6))
    style.map("TMenubutton", background=[("active", _pct(palette["surface"], 1.08))])

    style.configure("TCheckbutton", background=palette["bg"], foreground=palette["fg"])
    style.configure("TRadiobutton", background=palette["bg"], foreground=palette["fg"])


def _configure_treeview(style: ttk.Style, palette: dict[str, str]) -> None:
    style.configure(
        "Treeview",
        background=palette["surface"],
        fieldbackground=palette["surface"],
        foreground=palette["fg"],
        bordercolor=palette["border"],
        lightcolor=palette["border"],
        darkcolor=palette["border"],
        rowheight=26,
        relief="flat",
        borderwidth=0,
    )
    style.map(
        "Treeview",
        background=[
            ("selected", palette["selection"]),
            ("!selected", palette["surface"]),
        ],
        foreground=[("selected", "#ffffff")],
    )
    style.configure(
        "Treeview.Heading",
        background=palette["surface2"],
        foreground=palette["fg"],
        padding=(10, 6),
        relief="flat",
        font=(FONTS["base"][0], FONTS["base"][1], "semibold"),
        bordercolor=palette["border"],
    )
    style.map("Treeview.Heading", background=[("active", _pct(palette["surface"], 1.05))])


def _configure_misc(style: ttk.Style, palette: dict[str, str]) -> None:
    style.configure("TFrame", background=palette["bg"])
    style.configure("Toolbar.TFrame", background=palette["surface"], padding=(12, 8))
    style.configure("Surface.TFrame", background=palette["surface2"], padding=(12, 12))

    style.configure("TLabel", background=palette["bg"], foreground=palette["fg"])
    style.configure("Status.TLabel", background=palette["surface"], foreground=palette["muted"], padding=(12, 4))
    style.configure(
        "TLabelframe",
        background=palette["surface"],
        foreground=palette["fg"],
        bordercolor=palette["border"],
        relief="flat",
        borderwidth=1,
    )
    style.configure(
        "TLabelframe.Label",
        background=palette["surface"],
        foreground=palette["fg"],
        padding=(4, 0),
    )

    style.configure(
        "TScrollbar",
        troughcolor=palette["surface2"],
        background=palette["surface"],
        bordercolor=palette["border"],
        lightcolor=palette["border"],
        darkcolor=palette["border"],
    )
    style.map(
        "TScrollbar",
        background=[("active", _pct(palette["surface"], 1.08))],
    )

    style.configure("TNotebook", background=palette["bg"], borderwidth=0)
    style.configure(
        "TNotebook.Tab",
        background=palette["surface"],
        foreground=palette["fg"],
        padding=(12, 8),
    )
    style.map(
        "TNotebook.Tab",
        background=[
            ("selected", palette["surface2"]),
            ("active", _pct(palette["surface"], 1.06)),
        ],
        foreground=[("disabled", palette["muted"])],
    )

    style.configure("TSeparator", background=palette["border"])


def apply_theme(root: Tk, mode: str = "dark", *, font_size: Optional[int] = None) -> dict[str, str]:
    """Apply the modern theme to the root window and return the palette used."""

    palette = _palette(mode)
    base_font = (FONTS["base"][0], font_size or FONTS["base"][1])
    root.option_add("*Font", base_font)
    root.option_add("*TCombobox*Listbox.font", base_font)
    root.configure(background=palette["bg"])
    try:
        root.tk_setPalette(
            background=palette["bg"],
            foreground=palette["fg"],
            activeBackground=palette["surface"],
            activeForeground=palette["fg"],
            highlightColor=palette["selection"],
            highlightBackground=palette["selection"],
            insertBackground=palette["fg"],
            selectBackground=palette["selection"],
            selectForeground=palette["fg"],
        )
    except Exception:
        pass

    if ttkb is not None:
        try:  # pragma: no cover - optional path
            root.style = ttkb.Style(theme="flatly" if mode == "light" else "cosmo")
        except Exception:
            root.style = ttk.Style(root)
            root.style.theme_use("clam")
    else:
        root.style = ttk.Style(root)
        try:
            root.style.theme_use("clam")
        except tk.TclError:  # pragma: no cover - fallback when clam missing
            pass

    style = root.style
    _configure_misc(style, palette)
    _configure_buttons(style, palette)
    _configure_fields(style, palette)
    _configure_treeview(style, palette)

    return palette


@lru_cache(maxsize=64)
def make_icon(rel_path: str, size: int = 20) -> Optional[PhotoImage]:
    """Load a PNG icon located in the assets directory."""

    base_dir = os.path.join(os.path.dirname(__file__), "..", "assets")
    path = os.path.normpath(os.path.join(base_dir, rel_path))
    image: Optional[PhotoImage] = None
    if os.path.exists(path):
        try:
            image = PhotoImage(file=path)
        except Exception:
            image = None
    if image is None:
        name = os.path.basename(rel_path)
        data_parts = FALLBACK_ICONS.get(name)
        if data_parts:
            try:
                image = PhotoImage(data="".join(data_parts))
            except Exception:
                image = None
    if image is None:
        return None
    if image.width() > size:
        scale = max(1, image.width() // size)
        try:
            image = image.subsample(scale)
        except Exception:
            pass
    return image


def button(parent, text: str, *, style: str = "Primary.TButton", command=None, icon: Optional[PhotoImage] = None):
    """Create a themed ttk button."""

    btn = ttk.Button(parent, text=text, style=style, command=command, takefocus=True)
    if icon is not None:
        btn.configure(image=icon, compound="left")
    btn.bind("<Enter>", lambda _e, b=btn: b.state(["active"]))
    btn.bind("<Leave>", lambda _e, b=btn: b.state(["!active"]))
    return btn


def toolbar(parent):
    """Create a themed toolbar frame."""

    bar = ttk.Frame(parent, style="Toolbar.TFrame")
    bar.pack(fill="x", side="top", anchor="n")
    return bar


__all__ = [
    "PALETTE",
    "PALETTE_DARK",
    "PALETTE_LIGHT",
    "FONTS",
    "apply_theme",
    "make_icon",
    "button",
    "toolbar",
]
