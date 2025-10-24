# -*- coding: utf-8 -*-
from __future__ import annotations

# Copyright (c) 2025 Sebastien Cangemi
# Tous droits réservés.
# Gestion Stock Pro - Interface graphique professionnelle
# (version avec base utilisateur séparée/protégée et mémorisation des largeurs de colonnes)
#
# Pour générer un exécutable Windows :
#   pip install -r requirements.txt
#   pyinstaller --onefile --windowed --name GestionStockPro gestion_stock.py

import csv
import sqlite3
import threading
import time
import os
import sys
import shutil
import zipfile
import hashlib
import json
import logging
from typing import Any, Callable, Dict, Iterable, Optional
import importlib.util
import webbrowser
from datetime import datetime, timedelta
import traceback
import configparser

# ----------------------------
# Lecture de la configuration
# ----------------------------
CONFIG_FILE = 'config.ini'
CONFIG_DIRECTORY = os.path.dirname(os.path.abspath(CONFIG_FILE)) or os.getcwd()
LOG_FILE = os.path.join(CONFIG_DIRECTORY, "gestion_stock_log.txt")
config = configparser.ConfigParser()
config.optionxform = str  # Préserve la casse des clés (ex: noms de colonnes)
DEFAULT_INVENTORY_COLUMNS = (
    'ID',
    'Nom',
    'Code-Barres',
    'Catégorie',
    'Fournisseur',
    'Taille',
    'Note',
    'Quantité',
    'Dernière MAJ',
)

CLOTHING_COLUMN_KEYS: tuple[str, ...] = (
    'name',
    'barcode',
    'size',
    'category',
    'quantity',
    'reorder_point',
    'unit_cost',
    'supplier',
    'updated_at',
)

CLOTHING_COLUMN_LABELS: dict[str, str] = {
    'name': 'Article',
    'barcode': 'Code-Barres',
    'size': 'Taille',
    'category': 'Catégorie',
    'quantity': 'Quantité',
    'reorder_point': 'Seuil',
    'unit_cost': 'Coût (€)',
    'supplier': 'Fournisseur',
    'updated_at': 'Dernière MAJ',
}

PHARMACY_COLUMN_KEYS: tuple[str, ...] = (
    'name',
    'lot',
    'expiration',
    'days_left',
    'quantity',
    'dosage',
    'form',
    'storage',
    'prescription',
)

PHARMACY_COLUMN_LABELS: dict[str, str] = {
    'name': 'Nom',
    'lot': 'Lot',
    'expiration': 'Péremption',
    'days_left': 'Jours restants',
    'quantity': 'Quantité',
    'dosage': 'Dosage',
    'form': 'Forme',
    'storage': 'Condition',
    'prescription': 'Ordonnance',
}


def _normalize_columns_section(
    section: configparser.SectionProxy,
    default_columns: tuple[str, ...],
) -> None:
    """Assure la présence d'une configuration cohérente pour l'ordre et la visibilité des colonnes."""

    order_raw = section.get('order', '')
    order = [col.strip() for col in order_raw.split(',') if col.strip()]
    order = [col for col in order if col in default_columns]
    for col in default_columns:
        if col not in order:
            order.append(col)
    section['order'] = ','.join(order)

    hidden_raw = section.get('hidden', '')
    hidden = [col.strip() for col in hidden_raw.split(',') if col.strip()]
    hidden = [col for col in hidden if col in default_columns]
    section['hidden'] = ','.join(hidden)


def export_rows_to_csv(file_path: str, headers: tuple[str, ...], rows: list[tuple]) -> None:
    """Écrit un fichier CSV en utilisant un séparateur point-virgule."""
    with open(file_path, 'w', newline='', encoding='utf-8') as csv_file:
        writer = csv.writer(csv_file, delimiter=';')
        writer.writerow(headers)
        for row in rows:
            sanitized = ["" if value is None else value for value in row]
            writer.writerow(sanitized)


def parse_user_date(date_str: Optional[str]) -> Optional[str]:
    """Convertit une date JJ/MM/AAAA en ISO (AAAA-MM-JJ)."""
    if not date_str:
        return None
    cleaned = date_str.strip()
    if not cleaned:
        return None
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(cleaned, fmt).date().isoformat()
        except ValueError:
            continue
    raise ValueError("Format de date invalide. Utilisez JJ/MM/AAAA.")


def format_display_date(date_str: Optional[str]) -> str:
    """Affiche une date stockée en ISO au format JJ/MM/AAAA."""
    if not date_str:
        return ''
    cleaned = str(date_str).strip()
    if not cleaned:
        return ''
    for fmt in ("%Y-%m-%d",):
        try:
            return datetime.strptime(cleaned, fmt).strftime("%d/%m/%Y")
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(cleaned).strftime("%d/%m/%Y")
    except ValueError:
        pass
    try:
        return datetime.strptime(cleaned, "%d/%m/%Y").strftime("%d/%m/%Y")
    except ValueError:
        return cleaned


def format_display_datetime(value: Optional[str]) -> str:
    """Affiche une date/heure ISO en JJ/MM/AAAA HH:MM."""
    if not value:
        return ''
    try:
        return datetime.fromisoformat(value).strftime("%d/%m/%Y %H:%M")
    except ValueError:
        return value


default_config = {
    'db_path': 'stock.db',
    'user_db_path': 'users.db',
    'barcode_dir': 'barcodes',
    'camera_index': '0',
    'microphone_index': '',
    'enable_voice': 'true',
    'enable_tts': 'true',
    'tts_type': 'auto',
    'enable_barcode_generation': 'true',
    'low_stock_threshold': '5',
    'last_user': '',
    'enable_pharmacy_module': 'true',
    'enable_clothing_module': 'true',
    'theme': 'dark',
    'font_size': '10',
}
if not os.path.exists(CONFIG_FILE):
    config['Settings'] = default_config
    config['ColumnWidths'] = {}
    config['InventoryColumns'] = {
        'order': ','.join(DEFAULT_INVENTORY_COLUMNS),
        'hidden': '',
    }
    config['ClothingColumns'] = {
        'order': ','.join(CLOTHING_COLUMN_KEYS),
        'hidden': '',
    }
    config['PharmacyColumns'] = {
        'order': ','.join(PHARMACY_COLUMN_KEYS),
        'hidden': '',
    }
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        config.write(f)
else:
    config.read(CONFIG_FILE)
    if 'Settings' not in config:
        config['Settings'] = default_config
    else:
        if 'microphone_index' not in config['Settings']:
            config['Settings']['microphone_index'] = config['Settings'].get('camera_index', default_config['camera_index'])
        for key, val in default_config.items():
            if key not in config['Settings']:
                config['Settings'][key] = val
    if 'ColumnWidths' not in config:
        config['ColumnWidths'] = {}
    if 'InventoryColumns' not in config:
        config['InventoryColumns'] = {
            'order': ','.join(DEFAULT_INVENTORY_COLUMNS),
            'hidden': '',
        }
    else:
        _normalize_columns_section(config['InventoryColumns'], DEFAULT_INVENTORY_COLUMNS)
    if 'ClothingColumns' not in config:
        config['ClothingColumns'] = {
            'order': ','.join(CLOTHING_COLUMN_KEYS),
            'hidden': '',
        }
    else:
        _normalize_columns_section(config['ClothingColumns'], CLOTHING_COLUMN_KEYS)
    if 'PharmacyColumns' not in config:
        config['PharmacyColumns'] = {
            'order': ','.join(PHARMACY_COLUMN_KEYS),
            'hidden': '',
        }
    else:
        _normalize_columns_section(config['PharmacyColumns'], PHARMACY_COLUMN_KEYS)
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        config.write(f)

# Extraction des paramètres
DB_PATH = config['Settings'].get('db_path', default_config['db_path'])
USER_DB_PATH = config['Settings'].get('user_db_path', default_config['user_db_path'])
BARCODE_DIR = config['Settings'].get('barcode_dir', default_config['barcode_dir'])
try:
    CAMERA_INDEX = int(config['Settings'].get('camera_index', default_config['camera_index']))
except ValueError:
    CAMERA_INDEX = 0
microphone_value = config['Settings'].get('microphone_index', '').strip()
try:
    MICROPHONE_INDEX = int(microphone_value) if microphone_value else None
except ValueError:
    MICROPHONE_INDEX = None
ENABLE_VOICE = config['Settings'].getboolean('enable_voice', fallback=True)
ENABLE_TTS = config['Settings'].getboolean('enable_tts', fallback=True)
TTS_TYPE = config['Settings'].get('tts_type', default_config['tts_type']).strip().lower() or 'auto'
ENABLE_BARCODE_GENERATION = config['Settings'].getboolean('enable_barcode_generation', fallback=True)
DEFAULT_LOW_STOCK_THRESHOLD = config['Settings'].getint('low_stock_threshold', fallback=5)
LAST_USER = config['Settings'].get('last_user', '')
ENABLE_PHARMACY_MODULE = config['Settings'].getboolean('enable_pharmacy_module', fallback=True)
ENABLE_CLOTHING_MODULE = config['Settings'].getboolean('enable_clothing_module', fallback=True)

AVAILABLE_MODULES: tuple[str, ...] = ("pharmacy", "clothing")
MODULE_LABELS: dict[str, str] = {
    "pharmacy": "Pharmacie",
    "clothing": "Habillement",
}

KNOWN_TTS_DRIVERS = ("sapi5", "nsss", "espeak")
DEFAULT_TTS_TYPE_LABELS = {
    'auto': "Automatique (détection par défaut)",
    'sapi5': "Windows - SAPI5",
    'nsss': "macOS - NSSpeechSynthesizer",
    'espeak': "Linux - eSpeak",
}
ACTIVE_TTS_DRIVER: Optional[str] = None

if ENABLE_BARCODE_GENERATION and not os.path.exists(BARCODE_DIR):
    os.makedirs(BARCODE_DIR)

# -----------------------------------
# Gestion des imports facultatifs
# -----------------------------------
if not logging.getLogger().hasHandlers():
    log_handlers = [logging.StreamHandler()]
    file_handler_added = False
    try:
        file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    except OSError:
        file_handler = None
    else:
        log_handlers.append(file_handler)
        file_handler_added = True
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
        handlers=log_handlers,
    )
else:
    file_handler_added = any(
        isinstance(handler, logging.FileHandler)
        for handler in logging.getLogger().handlers
    )

logger = logging.getLogger(__name__)
audit_logger = logging.getLogger(f"{__name__}.audit")
if file_handler_added:
    logger.info("Journalisation des événements dans le fichier : %s", LOG_FILE)


class StartupEventListener:
    """Collecte les événements de démarrage pour faciliter le diagnostic."""

    def __init__(self, logger_instance: logging.Logger, *, enabled: bool = True) -> None:
        self._logger = logger_instance
        self._enabled = enabled
        self._events: list[str] = []
        self._lock = threading.Lock()
        self._listening = enabled

    def reset(self) -> None:
        """Réinitialise la collecte des événements."""
        if not self._enabled:
            return
        with self._lock:
            self._events.clear()
            self._listening = True

    def record(self, message: str, level: int = logging.INFO) -> None:
        """Ajoute un événement horodaté et le journalise."""
        if not self._enabled:
            return
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        entry = f"{timestamp} | {message}"
        with self._lock:
            if self._listening:
                self._events.append(entry)
        self._logger.log(level, "[Startup] %s", message)

    def stop(self) -> None:
        """Arrête l'écoute des événements supplémentaires."""
        if not self._enabled:
            return
        with self._lock:
            if not self._listening:
                return
            self._listening = False
        self._logger.debug("[Startup] Arrêt de l'écoute des événements de démarrage.")

    def flush_to_logger(self, level: int = logging.INFO) -> None:
        """Envoie la chronologie collectée vers le journal."""
        if not self._enabled:
            return
        with self._lock:
            events_snapshot = list(self._events)
        if not events_snapshot:
            return
        self._logger.log(level, "[Startup] Chronologie (%d événement(s)) :", len(events_snapshot))
        for entry in events_snapshot:
            self._logger.log(level, "[Startup] %s", entry)

    @property
    def listening(self) -> bool:
        if not self._enabled:
            return False
        with self._lock:
            return self._listening


startup_listener = StartupEventListener(logger)


def _check_directory_permissions(directory: str) -> tuple[bool, str]:
    """Retourne ``(ok, detail)`` en vérifiant l'accès en écriture au dossier."""

    target = directory or "."
    target = os.path.abspath(target)
    if not os.path.exists(target):
        return False, f"Dossier inexistant : {target}"
    if not os.path.isdir(target):
        return False, f"Chemin non valide (pas un dossier) : {target}"
    if not os.access(target, os.W_OK):
        return False, f"Dossier non inscriptible : {target}"
    return True, f"Dossier accessible : {target}"


def collect_environment_diagnostics() -> Dict[str, Dict[str, object]]:
    """Analyse l'environnement et indique la disponibilité des composants clés."""

    diagnostics: Dict[str, Dict[str, object]] = {}
    diagnostics["tkinter"] = {
        "ok": TK_AVAILABLE,
        "detail": "Tkinter importé" if TK_AVAILABLE else "Tkinter indisponible",
    }

    if sys.platform.startswith("linux"):
        display = os.environ.get("DISPLAY", "").strip()
        diagnostics["display"] = {
            "ok": bool(display),
            "detail": f"DISPLAY={display or '<non défini>'}",
        }
    else:
        diagnostics["display"] = {
            "ok": True,
            "detail": "Vérification non requise sur ce système",
        }

    diagnostics["barcode_camera"] = {
        "ok": CAMERA_AVAILABLE,
        "detail": (
            "OpenCV + pyzbar disponibles" if CAMERA_AVAILABLE else "Installer opencv-python et pyzbar"
        ),
    }

    diagnostics["barcode_generation"] = {
        "ok": BARCODE_GENERATOR_LIB,
        "detail": (
            "Bibliothèque python-barcode prête" if BARCODE_GENERATOR_LIB else "Installer python-barcode[images] et Pillow"
        ),
    }

    diagnostics["voice_recognition"] = {
        "ok": SR_LIB_AVAILABLE,
        "detail": "SpeechRecognition disponible" if SR_LIB_AVAILABLE else "Installer SpeechRecognition (+ PyAudio)",
    }

    if PYTTS3_LIB_AVAILABLE:
        available = ', '.join(AVAILABLE_TTS_TYPES)
        selected = ACTIVE_TTS_DRIVER or TTS_TYPE or 'auto'
        tts_detail = f"pyttsx3 disponible (sélection : {selected} | options : {available})"
    else:
        tts_detail = "Installer pyttsx3"
    diagnostics["text_to_speech"] = {
        "ok": PYTTS3_LIB_AVAILABLE,
        "detail": tts_detail,
    }

    db_directory = os.path.dirname(os.path.abspath(DB_PATH)) or "."
    db_ok, db_detail = _check_directory_permissions(db_directory)
    diagnostics["database_directory"] = {"ok": db_ok, "detail": db_detail}

    user_db_directory = os.path.dirname(os.path.abspath(USER_DB_PATH)) or "."
    user_db_ok, user_db_detail = _check_directory_permissions(user_db_directory)
    diagnostics["user_database_directory"] = {
        "ok": user_db_ok,
        "detail": user_db_detail,
    }

    barcode_dir = os.path.abspath(BARCODE_DIR)
    if os.path.exists(barcode_dir):
        barcode_ok, barcode_detail = _check_directory_permissions(barcode_dir)
    else:
        parent_dir = os.path.dirname(barcode_dir) or "."
        parent_ok, parent_detail = _check_directory_permissions(parent_dir)
        barcode_ok = parent_ok
        barcode_detail = parent_detail if parent_ok else parent_detail
        if parent_ok:
            barcode_detail = f"Le dossier sera créé à l'utilisation : {barcode_dir}"
    diagnostics["barcode_directory"] = {
        "ok": barcode_ok,
        "detail": barcode_detail,
    }

    return diagnostics


def format_environment_diagnostics(diagnostics: Dict[str, Dict[str, object]]) -> str:
    """Formate les diagnostics sous forme de texte lisible."""

    lines = []
    for key, info in diagnostics.items():
        status = "OK" if info.get("ok") else "KO"
        lines.append(f"- {key}: {status} – {info.get('detail', '')}")
    return "\n".join(lines)

try:
    import cv2
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False

try:
    from pyzbar import pyzbar
    BARCODE_AVAILABLE = True
except ImportError:
    BARCODE_AVAILABLE = False

try:
    import barcode
    from barcode.writer import ImageWriter
    BARCODE_GENERATOR_LIB = True
except ImportError:
    BARCODE_GENERATOR_LIB = False

try:
    import speech_recognition as sr
    SR_LIB_AVAILABLE = True
except ImportError:
    SR_LIB_AVAILABLE = False

try:
    import pyttsx3
    PYTTS3_LIB_AVAILABLE = True
except ImportError:
    PYTTS3_LIB_AVAILABLE = False

if PYTTS3_LIB_AVAILABLE:
    AVAILABLE_TTS_TYPES = ['auto']
    for driver_name in KNOWN_TTS_DRIVERS:
        if importlib.util.find_spec(f"pyttsx3.drivers.{driver_name}") is not None:
            AVAILABLE_TTS_TYPES.append(driver_name)
else:
    AVAILABLE_TTS_TYPES = ['auto']

try:
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox, simpledialog, PhotoImage
    TK_AVAILABLE = True
except ImportError:
    TK_AVAILABLE = False

if TK_AVAILABLE:
    from gestion_stock.ui.theme import (
        PALETTE,
        apply_theme,
        button as themed_button,
        toolbar as themed_toolbar,
        make_icon,
    )

    def _ideal_text_color(background: str, *, light: str = "#ffffff", dark: str = "#111827") -> str:
        """Return a readable text color for the given hex background."""

        color = background.lstrip("#")
        if len(color) != 6:
            return light
        try:
            r = int(color[0:2], 16) / 255.0
            g = int(color[2:4], 16) / 255.0
            b = int(color[4:6], 16) / 255.0
        except ValueError:
            return light
        luminance = 0.2126 * r + 0.7152 * g + 0.0722 * b
        return dark if luminance >= 0.55 else light


    def _apply_listbox_palette(listbox: tk.Listbox, palette: dict[str, str], *, theme: str = "dark") -> None:
        """Style a Tk listbox so its text stays readable with the active theme."""

        background = palette.get("surface2", palette.get("surface", "#1f2937"))
        foreground = palette.get("fg", "#e6e8eb" if theme == "dark" else "#111827")
        selection_bg = palette.get("selection", "#2563eb")
        selection_fg = _ideal_text_color(selection_bg)
        border = palette.get("border", background)
        listbox.configure(
            background=background,
            foreground=foreground,
            selectbackground=selection_bg,
            selectforeground=selection_fg,
            highlightbackground=border,
            highlightcolor=selection_bg,
            insertbackground=foreground,
            relief=tk.FLAT,
            borderwidth=0,
        )
else:

    def _apply_listbox_palette(*_args, **_kwargs):  # pragma: no cover - GUI fallback
        return None

try:
    import matplotlib
    if 'TK_AVAILABLE' in globals() and TK_AVAILABLE:
        matplotlib.use('TkAgg')
    else:
        matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages
    from matplotlib.figure import Figure
    try:
        from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    except ImportError:
        FigureCanvasTkAgg = None
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False
    FigureCanvasTkAgg = None

CAMERA_AVAILABLE = CV2_AVAILABLE and BARCODE_AVAILABLE
voice_active = False
recognizer = None
microphone = None
db_lock = threading.Lock()


try:
    from .pharmacy_inventory import PharmacyInventoryManager, PharmacyBatch
except Exception:  # pragma: no cover - import errors reported during initialization
    PharmacyInventoryManager = None  # type: ignore[assignment]
    PharmacyBatch = None  # type: ignore[assignment]

try:
    from .clothing_inventory import ClothingInventoryManager, ClothingItem
except Exception:  # pragma: no cover - import errors reported during initialization
    ClothingInventoryManager = None  # type: ignore[assignment]
    ClothingItem = None  # type: ignore[assignment]


def log_stock_movement(cursor, item_id, quantity_change, movement_type, source, operator=None, note=None, timestamp=None):
    """Insère un mouvement de stock dans la table dédiée."""
    if quantity_change == 0:
        return
    if timestamp is None:
        timestamp = datetime.now().isoformat()
    cursor.execute(
        """
        INSERT INTO stock_movements (
            item_id, quantity_change, movement_type, source, operator, note, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (item_id, quantity_change, movement_type, source, operator, note, timestamp)
    )


if PharmacyInventoryManager is not None:
    pharmacy_inventory_manager = PharmacyInventoryManager(
        db_path_getter=lambda: DB_PATH,
        lock=db_lock,
        log_stock_movement=log_stock_movement,
        parse_user_date=parse_user_date,
    )
else:  # pragma: no cover - résidu si l'import échoue
    pharmacy_inventory_manager = None


if ClothingInventoryManager is not None:
    clothing_inventory_manager = ClothingInventoryManager(
        db_path_getter=lambda: DB_PATH,
        lock=db_lock,
    )
else:  # pragma: no cover - résidu si l'import échoue
    clothing_inventory_manager = None



def ensure_pharmacy_inventory_schema(db_path: Optional[str] = None) -> None:
    """Garantit la présence des structures dédiées à la pharmacie."""
    if pharmacy_inventory_manager is None:
        raise RuntimeError("Le module pharmacy_inventory n'est pas disponible.")
    pharmacy_inventory_manager.ensure_schema(db_path=db_path)


def register_pharmacy_batch(*, name: str, lot_number: str, quantity: int, expiration_date: Optional[str] = None, barcode: Optional[str] = None, category: Optional[str] = None, dosage: Optional[str] = None, form: Optional[str] = None, storage_condition: Optional[str] = None, prescription_required: bool = False, note: Optional[str] = None, operator: Optional[str] = None, source: str = 'pharmacy_module', db_path: Optional[str] = None) -> dict:
    """Enregistre ou met à jour un lot pharmaceutique."""
    if pharmacy_inventory_manager is None:
        raise RuntimeError("Le module pharmacy_inventory n'est pas disponible.")
    return pharmacy_inventory_manager.register_batch(
        name=name,
        lot_number=lot_number,
        quantity=quantity,
        expiration_date=expiration_date,
        barcode=barcode,
        category=category,
        dosage=dosage,
        form=form,
        storage_condition=storage_condition,
        prescription_required=prescription_required,
        note=note,
        operator=operator,
        source=source,
        db_path=db_path,
    )


def get_pharmacy_batch(
    batch_id: int,
    *,
    db_path: Optional[str] = None,
) -> Optional[dict]:
    if pharmacy_inventory_manager is None:
        raise RuntimeError("Le module pharmacy_inventory n'est pas disponible.")
    return pharmacy_inventory_manager.get_batch(batch_id, db_path=db_path)


def update_pharmacy_batch(
    batch_id: int,
    *,
    name: str,
    lot_number: str,
    quantity: int,
    expiration_date: Optional[str] = None,
    barcode: Optional[str] = None,
    category: Optional[str] = None,
    dosage: Optional[str] = None,
    form: Optional[str] = None,
    storage_condition: Optional[str] = None,
    prescription_required: bool = False,
    note: Optional[str] = None,
    operator: Optional[str] = None,
    source: str = 'pharmacy_module',
    db_path: Optional[str] = None,
) -> Optional[dict]:
    if pharmacy_inventory_manager is None:
        raise RuntimeError("Le module pharmacy_inventory n'est pas disponible.")
    return pharmacy_inventory_manager.update_batch(
        batch_id,
        name=name,
        lot_number=lot_number,
        quantity=quantity,
        expiration_date=expiration_date,
        barcode=barcode,
        category=category,
        dosage=dosage,
        form=form,
        storage_condition=storage_condition,
        prescription_required=prescription_required,
        note=note,
        operator=operator,
        source=source,
        db_path=db_path,
    )


def delete_pharmacy_batch(
    batch_id: int,
    *,
    operator: Optional[str] = None,
    source: str = 'pharmacy_module',
    note: Optional[str] = None,
    db_path: Optional[str] = None,
) -> bool:
    if pharmacy_inventory_manager is None:
        raise RuntimeError("Le module pharmacy_inventory n'est pas disponible.")
    return pharmacy_inventory_manager.delete_batch(
        batch_id,
        operator=operator,
        source=source,
        note=note,
        db_path=db_path,
    )


def adjust_pharmacy_batch_quantity(batch_id: int, delta: int, *, operator: Optional[str] = None, source: str = 'pharmacy_module', note: Optional[str] = None, db_path: Optional[str] = None) -> Optional[dict]:
    """Modifie la quantité d'un lot pharmaceutique et synchronise l'article."""
    if pharmacy_inventory_manager is None:
        raise RuntimeError("Le module pharmacy_inventory n'est pas disponible.")
    return pharmacy_inventory_manager.adjust_batch_quantity(
        batch_id,
        delta,
        operator=operator,
        source=source,
        note=note,
        db_path=db_path,
    )


def list_expiring_pharmacy_batches(*, within_days: int = 30, include_empty: bool = False, db_path: Optional[str] = None):
    """Retourne les lots pharmaceutiques approchant de la péremption."""
    if pharmacy_inventory_manager is None:
        raise RuntimeError("Le module pharmacy_inventory n'est pas disponible.")
    return pharmacy_inventory_manager.list_expiring_batches(
        within_days=within_days,
        include_empty=include_empty,
        db_path=db_path,
    )


def summarize_pharmacy_stock(*, db_path: Optional[str] = None) -> dict:
    """Fournit un résumé agrégé du stock pharmaceutique."""
    if pharmacy_inventory_manager is None:
        raise RuntimeError("Le module pharmacy_inventory n'est pas disponible.")
    return pharmacy_inventory_manager.summarize_stock(db_path=db_path)


def list_pharmacy_batches(
    *,
    search: Optional[str] = None,
    include_zero: bool = True,
    db_path: Optional[str] = None,
):
    """Retourne les lots pharmaceutiques pour l'interface graphique."""

    if pharmacy_inventory_manager is None:
        raise RuntimeError("Le module pharmacy_inventory n'est pas disponible.")
    return pharmacy_inventory_manager.list_batches(
        search=search,
        include_zero=include_zero,
        db_path=db_path,
    )


def ensure_clothing_inventory_schema(
    *, db_path: Optional[str] = None, cursor: Optional[sqlite3.Cursor] = None
) -> None:
    """Garantit la présence des structures dédiées à l'habillement."""

    if clothing_inventory_manager is None:
        raise RuntimeError("Le module clothing_inventory n'est pas disponible.")
    clothing_inventory_manager.ensure_schema(db_path=db_path, cursor=cursor)


def register_clothing_item(
    *,
    name: str,
    barcode: Optional[str] = None,
    size: Optional[str] = None,
    category: Optional[str] = None,
    quantity: int = 0,
    unit_cost: Optional[float] = None,
    reorder_point: Optional[int] = None,
    preferred_supplier_id: Optional[int] = None,
    location: Optional[str] = None,
    note: Optional[str] = None,
    operator: Optional[str] = None,
    db_path: Optional[str] = None,
) -> ClothingItem:
    """Crée ou met à jour un article d'habillement."""

    if clothing_inventory_manager is None:
        raise RuntimeError("Le module clothing_inventory n'est pas disponible.")
    return clothing_inventory_manager.register_item(
        name=name,
        barcode=barcode,
        size=size,
        category=category,
        quantity=quantity,
        unit_cost=unit_cost,
        reorder_point=reorder_point,
        preferred_supplier_id=preferred_supplier_id,
        location=location,
        note=note,
        operator=operator,
        db_path=db_path,
    )


def update_clothing_item(
    clothing_id: int,
    *,
    name: str,
    barcode: Optional[str] = None,
    size: Optional[str] = None,
    category: Optional[str] = None,
    quantity: int = 0,
    unit_cost: Optional[float] = None,
    reorder_point: Optional[int] = None,
    preferred_supplier_id: Optional[int] = None,
    note: Optional[str] = None,
    operator: Optional[str] = None,
    db_path: Optional[str] = None,
) -> Optional[ClothingItem]:
    if clothing_inventory_manager is None:
        raise RuntimeError("Le module clothing_inventory n'est pas disponible.")
    return clothing_inventory_manager.update_item(
        clothing_id,
        name=name,
        barcode=barcode,
        size=size,
        category=category,
        quantity=quantity,
        unit_cost=unit_cost,
        reorder_point=reorder_point,
        preferred_supplier_id=preferred_supplier_id,
        note=note,
        operator=operator,
        db_path=db_path,
    )


def delete_clothing_item(
    clothing_id: int,
    *,
    db_path: Optional[str] = None,
) -> bool:
    if clothing_inventory_manager is None:
        raise RuntimeError("Le module clothing_inventory n'est pas disponible.")
    return clothing_inventory_manager.delete_item(clothing_id, db_path=db_path)


def adjust_clothing_item_quantity(
    clothing_id: int,
    delta: int,
    *,
    operator: Optional[str] = None,
    note: Optional[str] = None,
    db_path: Optional[str] = None,
) -> Optional[ClothingItem]:
    """Ajuste la quantité d'un article d'habillement."""

    if clothing_inventory_manager is None:
        raise RuntimeError("Le module clothing_inventory n'est pas disponible.")
    return clothing_inventory_manager.adjust_quantity(
        clothing_id,
        delta,
        operator=operator,
        note=note,
        db_path=db_path,
    )


def list_clothing_items(
    *,
    search: str = "",
    include_zero: bool = True,
    db_path: Optional[str] = None,
) -> list[ClothingItem]:
    """Retourne les articles d'habillement pour l'interface graphique."""

    if clothing_inventory_manager is None:
        raise RuntimeError("Le module clothing_inventory n'est pas disponible.")
    return clothing_inventory_manager.list_items(
        search=search,
        include_zero=include_zero,
        db_path=db_path,
    )


def summarize_clothing_stock(*, db_path: Optional[str] = None) -> dict:
    """Fournit un résumé agrégé du stock d'habillement."""

    if clothing_inventory_manager is None:
        raise RuntimeError("Le module clothing_inventory n'est pas disponible.")
    return clothing_inventory_manager.summarize_stock(db_path=db_path)

def adjust_item_quantity(item_id, delta, operator='system', source='manual', note=None):
    """Modifie la quantité d'un article et journalise le mouvement."""
    conn = None
    try:
        with db_lock:
            conn = sqlite3.connect(DB_PATH, timeout=30)
            cursor = conn.cursor()
            cursor.execute("SELECT quantity FROM items WHERE id = ?", (item_id,))
            result = cursor.fetchone()
            if not result:
                return None
            old_qty = result[0] or 0
            if delta == 0:
                return old_qty, 0, old_qty
            new_qty = old_qty + delta
            if new_qty < 0:
                new_qty = 0
            timestamp = datetime.now().isoformat()
            cursor.execute(
                "UPDATE items SET quantity = ?, last_updated = ? WHERE id = ?",
                (new_qty, timestamp, item_id)
            )
            change = new_qty - old_qty
            if change != 0:
                movement_type = 'IN' if change > 0 else 'OUT'
                log_stock_movement(
                    cursor,
                    item_id,
                    change,
                    movement_type,
                    source,
                    operator,
                    note,
                    timestamp,
                )
            conn.commit()
            return new_qty, change, old_qty
    except sqlite3.Error as e:
        print(f"[DB Error] adjust_item_quantity: {e}")
        return None
    finally:
        if conn:
            conn.close()

# ------------------------
# INITIATION / MIGRATION BASE UTILISATEURS
# ------------------------


def default_module_permissions_for_role(role: Optional[str]) -> dict[str, bool]:
    """Retourne les permissions modules par défaut pour un rôle donné."""

    base_permissions = {
        "pharmacy": config['Settings'].getboolean(
            'enable_pharmacy_module',
            fallback=ENABLE_PHARMACY_MODULE,
        ),
        "clothing": config['Settings'].getboolean(
            'enable_clothing_module',
            fallback=ENABLE_CLOTHING_MODULE,
        ),
    }
    if role == 'admin':
        return {module: True for module in AVAILABLE_MODULES}
    return {
        module: bool(base_permissions.get(module, False))
        for module in AVAILABLE_MODULES
    }


def init_user_db(user_db_path=USER_DB_PATH):
    """
    Initialise la base de données des utilisateurs, distincte de la base de stock.
    Crée la table users et ajoute la colonne role si manquante.
    """
    startup_listener.record(
        f"Initialisation de la base utilisateurs : {os.path.abspath(user_db_path)}",
        level=logging.DEBUG,
    )
    conn = None
    try:
        conn = sqlite3.connect(user_db_path, timeout=30)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL
            )
        ''')
        conn.commit()

        # Vérifier si la colonne 'role' existe
        cursor.execute("PRAGMA table_info(users)")
        columns = [info[1] for info in cursor.fetchall()]
        if 'role' not in columns:
            cursor.execute("ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'user'")
            # Si des utilisateurs existaient, leur attribuer le rôle 'admin'
            cursor.execute("UPDATE users SET role = 'admin'")
            conn.commit()

        # Normaliser les rôles existants
        cursor.execute("PRAGMA table_info(users)")
        columns = [info[1] for info in cursor.fetchall()]
        if 'role' in columns:
            cursor.execute("UPDATE users SET role = 'user' WHERE role NOT IN ('admin','user')")
            conn.commit()

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_modules (
                user_id INTEGER NOT NULL,
                module TEXT NOT NULL,
                allowed INTEGER NOT NULL DEFAULT 1,
                PRIMARY KEY (user_id, module),
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        ''')
        conn.commit()

        cursor.execute("SELECT id, role FROM users")
        existing_users = cursor.fetchall()
        for user_id, role in existing_users:
            defaults = default_module_permissions_for_role(role)
            for module, allowed in defaults.items():
                cursor.execute(
                    """
                    INSERT OR IGNORE INTO user_modules (user_id, module, allowed)
                    VALUES (?, ?, ?)
                    """,
                    (user_id, module, 1 if allowed else 0),
                )
        conn.commit()

        conn.commit()
        startup_listener.record("Base utilisateurs prête.", level=logging.DEBUG)
    except sqlite3.Error as e:
        startup_listener.record(
            f"Échec lors de l'initialisation de la base utilisateurs : {e}",
            level=logging.ERROR,
        )
        print(f"[DB Error] init_user_db: {e}")
    finally:
        if conn:
            conn.close()

# ------------------------
# INITIATION / MIGRATION BASE STOCK
# ------------------------
def init_stock_db(db_path=DB_PATH):
    """
    Initialise la base de données du stock.
    Crée tables categories et items (avec colonne size).
    Crée un index sur items.name.
    """
    startup_listener.record(
        f"Initialisation de la base stock : {os.path.abspath(db_path)}",
        level=logging.DEBUG,
    )
    conn = None
    try:
        conn = sqlite3.connect(db_path, timeout=30)
        cursor = conn.cursor()

        # Table catégories
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                note TEXT
            )
        ''')
        cursor.execute("PRAGMA table_info(categories)")
        category_columns = [info[1] for info in cursor.fetchall()]
        if 'note' not in category_columns:
            cursor.execute("ALTER TABLE categories ADD COLUMN note TEXT")

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS category_sizes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category_id INTEGER NOT NULL,
                size_label TEXT NOT NULL,
                UNIQUE(category_id, size_label),
                FOREIGN KEY(category_id) REFERENCES categories(id)
            )
        ''')

        # Table articles
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                barcode TEXT UNIQUE,
                category_id INTEGER,
                size TEXT,
                quantity INTEGER NOT NULL DEFAULT 0,
                last_updated TEXT,
                unit_cost REAL DEFAULT 0,
                reorder_point INTEGER,
                preferred_supplier_id INTEGER,
                FOREIGN KEY(category_id) REFERENCES categories(id)
            )
        ''')

        # Index sur le nom (pour recherche rapide)
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_items_name ON items(name COLLATE NOCASE)
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS stock_movements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_id INTEGER NOT NULL,
                quantity_change INTEGER NOT NULL,
                movement_type TEXT NOT NULL,
                source TEXT NOT NULL,
                operator TEXT,
                note TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(item_id) REFERENCES items(id)
            )
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_movements_item ON stock_movements(item_id)
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_movements_date ON stock_movements(created_at)
        ''')

        # Table fournisseurs
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS suppliers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                contact_name TEXT,
                email TEXT,
                phone TEXT,
                notes TEXT,
                created_at TEXT NOT NULL
            )
        ''')

        # Table bons de commande
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS purchase_orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                supplier_id INTEGER,
                status TEXT NOT NULL DEFAULT 'PENDING',
                expected_date TEXT,
                created_at TEXT NOT NULL,
                created_by TEXT,
                received_at TEXT,
                note TEXT,
                FOREIGN KEY(supplier_id) REFERENCES suppliers(id)
            )
        ''')

        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_purchase_orders_status ON purchase_orders(status)
        ''')

        # Lignes de bon de commande
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS purchase_order_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                purchase_order_id INTEGER NOT NULL,
                item_id INTEGER NOT NULL,
                quantity_ordered INTEGER NOT NULL,
                quantity_received INTEGER NOT NULL DEFAULT 0,
                unit_cost REAL DEFAULT 0,
                FOREIGN KEY(purchase_order_id) REFERENCES purchase_orders(id),
                FOREIGN KEY(item_id) REFERENCES items(id)
            )
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_purchase_order_items_po ON purchase_order_items(purchase_order_id)
        ''')

        # Demandes d'approbation
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS approval_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_id INTEGER,
                request_type TEXT NOT NULL,
                quantity INTEGER,
                note TEXT,
                requested_by TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                reviewed_by TEXT,
                reviewed_at TEXT,
                response_note TEXT,
                payload TEXT,
                FOREIGN KEY(item_id) REFERENCES items(id)
            )
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_approval_status ON approval_requests(status)
        ''')

        # Collaborateurs
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS collaborators (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                full_name TEXT NOT NULL,
                department TEXT,
                job_title TEXT,
                email TEXT,
                phone TEXT,
                hire_date TEXT,
                notes TEXT
            )
        ''')

        # Dotations collaborateurs
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS collaborator_gear (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                collaborator_id INTEGER NOT NULL,
                item_id INTEGER NOT NULL,
                size TEXT,
                quantity INTEGER NOT NULL,
                issued_at TEXT NOT NULL,
                due_date TEXT,
                status TEXT NOT NULL DEFAULT 'issued',
                returned_at TEXT,
                notes TEXT,
                FOREIGN KEY(collaborator_id) REFERENCES collaborators(id),
                FOREIGN KEY(item_id) REFERENCES items(id)
            )
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_collaborator_gear_status ON collaborator_gear(status)
        ''')

        # Historique des alertes de réapprovisionnement
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS stock_alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_id INTEGER NOT NULL,
                triggered_at TEXT NOT NULL,
                alert_level TEXT,
                channel TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                message TEXT,
                FOREIGN KEY(item_id) REFERENCES items(id)
            )
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_stock_alerts_item ON stock_alerts(item_id)
        ''')

        # Ajouter colonnes si manquantes (migration)
        cursor.execute("PRAGMA table_info(items)")
        item_columns = [info[1] for info in cursor.fetchall()]
        if 'unit_cost' not in item_columns:
            cursor.execute("ALTER TABLE items ADD COLUMN unit_cost REAL DEFAULT 0")
        if 'reorder_point' not in item_columns:
            cursor.execute("ALTER TABLE items ADD COLUMN reorder_point INTEGER")
        if 'preferred_supplier_id' not in item_columns:
            cursor.execute("ALTER TABLE items ADD COLUMN preferred_supplier_id INTEGER")

        if pharmacy_inventory_manager is not None:
            pharmacy_inventory_manager.ensure_schema(cursor=cursor)
        if clothing_inventory_manager is not None:
            clothing_inventory_manager.ensure_schema(cursor=cursor)

        conn.commit()
        startup_listener.record("Base stock prête.", level=logging.DEBUG)
    except sqlite3.Error as e:
        startup_listener.record(
            f"Échec lors de l'initialisation de la base stock : {e}",
            level=logging.ERROR,
        )
        print(f"[DB Error] init_stock_db: {e}")
    finally:
        if conn:
            conn.close()

# ------------------------
# FONCTIONS UTILISATEURS (base séparée USER_DB_PATH)
# ------------------------
def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode('utf-8')).hexdigest()

def create_user(username: str, password: str, role: str = 'user') -> bool:
    """
    Crée un nouvel utilisateur dans USER_DB_PATH. role ∈ {'admin','user'}.
    Retourne True si succès, False sinon.
    """
    if role not in {'admin', 'user'}:
        raise ValueError("Le rôle doit être 'admin' ou 'user'.")
    conn = None
    try:
        pwd_hash = hash_password(password)
        with db_lock:
            conn = sqlite3.connect(USER_DB_PATH, timeout=30)
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
                (username, pwd_hash, role)
            )
            user_id = cursor.lastrowid
            defaults = default_module_permissions_for_role(role)
            for module, allowed in defaults.items():
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO user_modules (user_id, module, allowed)
                    VALUES (?, ?, ?)
                    """,
                    (user_id, module, 1 if allowed else 0),
                )
            conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    except sqlite3.Error as e:
        print(f"[DB Error] create_user: {e}")
        return False
    finally:
        if conn:
            conn.close()

def verify_user(username: str, password: str):
    """
    Vérifie les identifiants dans USER_DB_PATH. Retourne (True, role) si succès, sinon (False, None).
    """
    conn = None
    try:
        pwd_hash = hash_password(password)
        with db_lock:
            conn = sqlite3.connect(USER_DB_PATH, timeout=30)
            cursor = conn.cursor()
            cursor.execute("SELECT password_hash, role FROM users WHERE username = ?", (username,))
            row = cursor.fetchone()
        if row and row[0] == pwd_hash:
            audit_logger.info("Authentification réussie pour l'utilisateur '%s'.", username)
            return True, row[1]
        else:
            audit_logger.warning("Échec d'authentification pour l'utilisateur '%s'.", username)
            return False, None
    except sqlite3.Error as e:
        print(f"[DB Error] verify_user: {e}")
        return False, None
    finally:
        if conn:
            conn.close()

def users_exist() -> bool:
    """
    Indique s'il existe au moins un utilisateur dans USER_DB_PATH.
    """
    conn = None
    try:
        with db_lock:
            conn = sqlite3.connect(USER_DB_PATH, timeout=30)
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM users")
            count = cursor.fetchone()[0]
        return count > 0
    except sqlite3.Error as e:
        print(f"[DB Error] users_exist: {e}")
        return False
    finally:
        if conn:
            conn.close()

def fetch_all_users():
    """
    Récupère tous les utilisateurs (id, username, role) depuis USER_DB_PATH.
    """
    conn = None
    try:
        with db_lock:
            conn = sqlite3.connect(USER_DB_PATH, timeout=30)
            cursor = conn.cursor()
            cursor.execute("SELECT id, username, role FROM users ORDER BY username")
            rows = cursor.fetchall()
        return rows
    except sqlite3.Error as e:
        print(f"[DB Error] fetch_all_users: {e}")
        return []
    finally:
        if conn:
            conn.close()


def count_admin_users(exclude_user_id: Optional[int] = None) -> int:
    """Retourne le nombre d'utilisateurs disposant du rôle administrateur."""

    conn = None
    try:
        with db_lock:
            conn = sqlite3.connect(USER_DB_PATH, timeout=30)
            cursor = conn.cursor()
            query = "SELECT COUNT(*) FROM users WHERE role = 'admin'"
            params: list[Any] = []
            if exclude_user_id is not None:
                query += " AND id != ?"
                params.append(exclude_user_id)
            cursor.execute(query, params)
            row = cursor.fetchone()
        return row[0] if row else 0
    except sqlite3.Error as e:
        print(f"[DB Error] count_admin_users: {e}")
        return 0
    finally:
        if conn:
            conn.close()


def get_user_module_permissions(user_id: Optional[int], *, role: Optional[str] = None) -> dict[str, bool]:
    """Obtient les permissions de modules pour un utilisateur donné."""

    if user_id is None:
        return default_module_permissions_for_role(role)
    conn = None
    try:
        with db_lock:
            conn = sqlite3.connect(USER_DB_PATH, timeout=30)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT module, allowed FROM user_modules WHERE user_id = ?",
                (user_id,),
            )
            rows = cursor.fetchall()
        permissions = {
            module: bool(allowed)
            for module, allowed in rows
            if module in AVAILABLE_MODULES
        }
        if len(permissions) < len(AVAILABLE_MODULES):
            defaults = default_module_permissions_for_role(role)
            for module in AVAILABLE_MODULES:
                permissions.setdefault(module, bool(defaults.get(module, False)))
        return permissions
    except sqlite3.Error as e:
        print(f"[DB Error] get_user_module_permissions: {e}")
        return default_module_permissions_for_role(role)
    finally:
        if conn:
            conn.close()


def set_user_module_permissions(user_id: int, permissions: dict[str, bool]) -> bool:
    """Met à jour les permissions de modules pour un utilisateur donné."""

    conn = None
    try:
        filtered = {
            module: bool(permissions.get(module, False))
            for module in AVAILABLE_MODULES
        }
        with db_lock:
            conn = sqlite3.connect(USER_DB_PATH, timeout=30)
            cursor = conn.cursor()
            for module, allowed in filtered.items():
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO user_modules (user_id, module, allowed)
                    VALUES (?, ?, ?)
                    """,
                    (user_id, module, 1 if allowed else 0),
                )
            conn.commit()
        return True
    except sqlite3.Error as e:
        print(f"[DB Error] set_user_module_permissions: {e}")
        return False
    finally:
        if conn:
            conn.close()


# ------------------------
# FONCTIONS FOURNISSEURS / APPROVISIONNEMENTS
# ------------------------

def fetch_suppliers(search: Optional[str] = None):
    conn = None
    try:
        params: list = []
        query = (
            "SELECT id, name, contact_name, email, phone, notes, created_at "
            "FROM suppliers"
        )
        if search:
            like = f"%{search.lower()}%"
            query += (
                " WHERE lower(COALESCE(name,'')) LIKE ?"
                " OR lower(COALESCE(contact_name,'')) LIKE ?"
                " OR lower(COALESCE(email,'')) LIKE ?"
                " OR lower(COALESCE(phone,'')) LIKE ?"
            )
            params.extend([like, like, like, like])
        query += " ORDER BY name"
        with db_lock:
            conn = sqlite3.connect(DB_PATH, timeout=30)
            cursor = conn.cursor()
            cursor.execute(query, params)
            return cursor.fetchall()
    except sqlite3.Error as e:
        print(f"[DB Error] fetch_suppliers: {e}")
        return []
    finally:
        if conn:
            conn.close()


def save_supplier(name, contact_name='', email='', phone='', notes='', supplier_id=None):
    if not name:
        raise ValueError("Le nom du fournisseur est requis")
    conn = None
    try:
        timestamp = datetime.now().isoformat()
        with db_lock:
            conn = sqlite3.connect(DB_PATH, timeout=30)
            cursor = conn.cursor()
            if supplier_id:
                cursor.execute(
                    """
                    UPDATE suppliers
                    SET name = ?, contact_name = ?, email = ?, phone = ?, notes = ?
                    WHERE id = ?
                    """,
                    (name, contact_name, email, phone, notes, supplier_id),
                )
            else:
                cursor.execute(
                    """
                    INSERT INTO suppliers (name, contact_name, email, phone, notes, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (name, contact_name, email, phone, notes, timestamp),
                )
            conn.commit()
            return supplier_id or cursor.lastrowid
    except sqlite3.Error as e:
        print(f"[DB Error] save_supplier: {e}")
        return None
    finally:
        if conn:
            conn.close()


def delete_supplier(supplier_id):
    conn = None
    try:
        with db_lock:
            conn = sqlite3.connect(DB_PATH, timeout=30)
            cursor = conn.cursor()
            cursor.execute("DELETE FROM suppliers WHERE id = ?", (supplier_id,))
            conn.commit()
        return True
    except sqlite3.Error as e:
        print(f"[DB Error] delete_supplier: {e}")
        return False
    finally:
        if conn:
            conn.close()


def fetch_items_lookup(*, only_clothing: bool = False):
    conn = None
    rows: list[tuple] = []
    try:
        with db_lock:
            conn = sqlite3.connect(DB_PATH, timeout=30)
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT
                    items.id,
                    items.name,
                    COALESCE(items.unit_cost, 0),
                    COALESCE(items.reorder_point, ?),
                    items.barcode,
                    COALESCE(categories.name, ''),
                    COALESCE(categories.note, '')
                FROM items
                LEFT JOIN categories ON categories.id = items.category_id
                ORDER BY items.name
                """,
                (DEFAULT_LOW_STOCK_THRESHOLD,),
            )
            rows = cursor.fetchall()
    except sqlite3.Error as e:
        print(f"[DB Error] fetch_items_lookup: {e}")
        return []
    finally:
        if conn:
            conn.close()

    if not only_clothing:
        return [row[:4] for row in rows]

    clothing_names: list[str] = []
    clothing_categories: list[str] = []
    clothing_barcodes: set[str] = set()
    if clothing_inventory_manager is not None:
        try:
            clothing_items = clothing_inventory_manager.list_items(search="", include_zero=True)
        except Exception as exc:  # pragma: no cover - garde-fou
            print(f"[Clothing] fetch_items_lookup fallback: {exc}")
        else:
            for clothing_item in clothing_items:
                if clothing_item.name:
                    clothing_names.append(clothing_item.name.strip().lower())
                if clothing_item.category:
                    clothing_categories.append(clothing_item.category.strip().lower())
                if clothing_item.barcode:
                    clothing_barcodes.add(clothing_item.barcode.strip().lower())

    CATEGORY_KEYWORDS = (
        "habil",
        "vêt",
        "vet",
        "tenue",
        "uniform",
        "epi",
        "chaus",
        "pantal",
        "chemise",
        "gilet",
        "blous",
        "tablier",
    )

    def _matches_any(value: str, candidates: list[str]) -> bool:
        if not value:
            return False
        for candidate in candidates:
            if not candidate:
                continue
            if value == candidate or value in candidate or candidate in value:
                return True
        return False

    filtered: list[tuple[int, str, float, int]] = []
    for item_id, name, unit_cost, reorder_point, barcode, category_name, category_note in rows:
        label = (name or "").strip().lower()
        barcode_value = (barcode or "").strip().lower()
        cat_label = (category_name or "").strip().lower()
        note_label = (category_note or "").strip().lower()

        matches_clothing_inventory = (
            _matches_any(label, clothing_names)
            or (barcode_value and barcode_value in clothing_barcodes)
        )
        matches_categories = _matches_any(cat_label, clothing_categories)
        matches_keywords = any(keyword in cat_label for keyword in CATEGORY_KEYWORDS) or any(
            keyword in note_label for keyword in CATEGORY_KEYWORDS
        )

        if matches_clothing_inventory or matches_categories or matches_keywords:
            filtered.append((item_id, name, unit_cost, reorder_point))

    return filtered


def get_item_name(item_id):
    conn = None
    try:
        with db_lock:
            conn = sqlite3.connect(DB_PATH, timeout=30)
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM items WHERE id = ?", (item_id,))
            row = cursor.fetchone()
            if row:
                return row[0]
    except sqlite3.Error as e:
        print(f"[DB Error] get_item_name: {e}")
    finally:
        if conn:
            conn.close()
    return None


def create_purchase_order(supplier_id, expected_date, note, created_by, lines, status='PENDING'):
    if not lines:
        raise ValueError("Le bon de commande doit contenir au moins une ligne")
    conn = None
    try:
        timestamp = datetime.now().isoformat()
        normalized_expected = None
        if expected_date:
            try:
                normalized_expected = parse_user_date(expected_date)
            except ValueError:
                normalized_expected = expected_date.strip()
        with db_lock:
            conn = sqlite3.connect(DB_PATH, timeout=30)
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO purchase_orders (supplier_id, status, expected_date, created_at, created_by, note)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (supplier_id, status, normalized_expected, timestamp, created_by, note),
            )
            po_id = cursor.lastrowid
            for line in lines:
                cursor.execute(
                    """
                    INSERT INTO purchase_order_items (
                        purchase_order_id, item_id, quantity_ordered, quantity_received, unit_cost
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        po_id,
                        line['item_id'],
                        line.get('quantity_ordered', 0),
                        line.get('quantity_received', 0),
                        line.get('unit_cost', 0),
                    ),
                )
            conn.commit()
            return po_id
    except sqlite3.Error as e:
        print(f"[DB Error] create_purchase_order: {e}")
        return None
    finally:
        if conn:
            conn.close()


def fetch_purchase_orders(status=None, search: Optional[str] = None):
    conn = None
    try:
        query = (
            "SELECT purchase_orders.id, purchase_orders.created_at, purchase_orders.status, purchase_orders.expected_date, "
            "purchase_orders.received_at, suppliers.name, purchase_orders.note, purchase_orders.created_by "
            "FROM purchase_orders LEFT JOIN suppliers ON suppliers.id = purchase_orders.supplier_id"
        )
        params: list = []
        clauses: list[str] = []
        if status:
            if isinstance(status, (list, tuple, set)):
                placeholders = ','.join('?' for _ in status)
                clauses.append(f"purchase_orders.status IN ({placeholders})")
                params.extend(status)
            elif status == 'active':
                clauses.append("purchase_orders.status IN ('PENDING', 'PARTIAL', 'SUGGESTED')")
            elif status == 'closed':
                clauses.append("purchase_orders.status IN ('RECEIVED', 'CANCELLED')")
            else:
                clauses.append("purchase_orders.status = ?")
                params.append(status)
        if search:
            like = f"%{search.lower()}%"
            clauses.append(
                "(" 
                "lower(COALESCE(suppliers.name,'')) LIKE ? OR "
                "lower(COALESCE(purchase_orders.note,'')) LIKE ? OR "
                "lower(COALESCE(purchase_orders.created_by,'')) LIKE ? OR "
                "CAST(purchase_orders.id AS TEXT) LIKE ?"
                ")"
            )
            params.extend([like, like, like, f"%{search}%"])
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY purchase_orders.created_at DESC"
        with db_lock:
            conn = sqlite3.connect(DB_PATH, timeout=30)
            cursor = conn.cursor()
            cursor.execute(query, params)
            return cursor.fetchall()
    except sqlite3.Error as e:
        print(f"[DB Error] fetch_purchase_orders: {e}")
        return []
    finally:
        if conn:
            conn.close()


def fetch_purchase_order_items(purchase_order_id):
    conn = None
    try:
        with db_lock:
            conn = sqlite3.connect(DB_PATH, timeout=30)
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT purchase_order_items.id, items.name, purchase_order_items.quantity_ordered,
                       purchase_order_items.quantity_received, purchase_order_items.unit_cost, items.id
                FROM purchase_order_items
                JOIN items ON items.id = purchase_order_items.item_id
                WHERE purchase_order_items.purchase_order_id = ?
                ORDER BY items.name
                """,
                (purchase_order_id,),
            )
            return cursor.fetchall()
    except sqlite3.Error as e:
        print(f"[DB Error] fetch_purchase_order_items: {e}")
        return []
    finally:
        if conn:
            conn.close()


def update_purchase_order_status(purchase_order_id, status, reviewer, receipt_lines=None, note=None):
    conn = None
    try:
        now = datetime.now()
        timestamp_iso = now.isoformat()
        display_timestamp = now.strftime('%d/%m/%Y %H:%M')
        operator = reviewer or 'système'
        trimmed_note = (note or '').strip()
        status_label = status.upper()
        log_entry = f"[{display_timestamp}] {operator} - Statut {status_label}"
        if trimmed_note:
            log_entry += f" | {trimmed_note}"
        with db_lock:
            conn = sqlite3.connect(DB_PATH, timeout=30)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT note, received_at FROM purchase_orders WHERE id = ?",
                (purchase_order_id,),
            )
            row = cursor.fetchone()
            existing_note = row[0] if row and row[0] else ''
            current_received_at = row[1] if row else None
            combined_note = f"{existing_note}\n{log_entry}" if existing_note else log_entry
            new_received_at = current_received_at
            if status in ('RECEIVED', 'PARTIAL'):
                new_received_at = timestamp_iso
            cursor.execute(
                "UPDATE purchase_orders SET status = ?, received_at = ?, note = ? WHERE id = ?",
                (status, new_received_at, combined_note, purchase_order_id),
            )
            if status in ('RECEIVED', 'PARTIAL') and receipt_lines:
                for item_id, received_qty in receipt_lines.items():
                    cursor.execute(
                        """
                        UPDATE purchase_order_items
                        SET quantity_received = COALESCE(quantity_received, 0) + ?
                        WHERE purchase_order_id = ? AND item_id = ?
                        """,
                        (received_qty, purchase_order_id, item_id),
                    )
                    cursor.execute("SELECT quantity FROM items WHERE id = ?", (item_id,))
                    row = cursor.fetchone()
                    current_qty = row[0] if row else 0
                    new_qty = (current_qty or 0) + received_qty
                    cursor.execute(
                        "UPDATE items SET quantity = ?, last_updated = ? WHERE id = ?",
                        (new_qty, timestamp_iso, item_id),
                    )
                    log_stock_movement(
                        cursor,
                        item_id,
                        received_qty,
                        'IN',
                        'purchase_order_receipt',
                        reviewer,
                        note=f"Réception bon #{purchase_order_id}",
                        timestamp=timestamp_iso,
                    )
            conn.commit()
            return True
    except sqlite3.Error as e:
        print(f"[DB Error] update_purchase_order_status: {e}")
        return False
    finally:
        if conn:
            conn.close()


def create_suggested_purchase_order(item_id, deficit, created_by='system'):
    lines = [{'item_id': item_id, 'quantity_ordered': max(deficit, 1), 'unit_cost': 0}]
    existing = None
    conn = None
    try:
        with db_lock:
            conn = sqlite3.connect(DB_PATH, timeout=30)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id FROM purchase_orders WHERE status = 'SUGGESTED' AND note LIKE ? LIMIT 1",
                (f"%item:{item_id}%",),
            )
            existing = cursor.fetchone()
    except sqlite3.Error:
        existing = None
    finally:
        if conn:
            conn.close()
    if existing:
        return existing[0]
    note = f"Suggestion automatique pour item:{item_id} déficit:{deficit}"
    return create_purchase_order(None, None, note, created_by, lines, status='SUGGESTED')


# ------------------------
# FONCTIONS APPROBATIONS
# ------------------------

def create_approval_request(item_id, request_type, quantity, note, requested_by, payload=None):
    conn = None
    try:
        timestamp = datetime.now().isoformat()
        with db_lock:
            conn = sqlite3.connect(DB_PATH, timeout=30)
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO approval_requests (
                    item_id, request_type, quantity, note, requested_by, status, created_at, payload
                ) VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)
                """,
                (item_id, request_type, quantity, note, requested_by, timestamp, json.dumps(payload) if payload else None),
            )
            conn.commit()
            return cursor.lastrowid
    except sqlite3.Error as e:
        print(f"[DB Error] create_approval_request: {e}")
        return None
    finally:
        if conn:
            conn.close()


def fetch_approval_requests(status='pending'):
    conn = None
    try:
        query = (
            "SELECT approval_requests.id, approval_requests.item_id, approval_requests.request_type, approval_requests.quantity,"
            " approval_requests.note, approval_requests.requested_by, approval_requests.created_at, approval_requests.status,"
            " approval_requests.payload FROM approval_requests"
        )
        params = []
        if status:
            query += " WHERE approval_requests.status = ?"
            params.append(status)
        query += " ORDER BY approval_requests.created_at DESC"
        with db_lock:
            conn = sqlite3.connect(DB_PATH, timeout=30)
            cursor = conn.cursor()
            cursor.execute(query, params)
            return cursor.fetchall()
    except sqlite3.Error as e:
        print(f"[DB Error] fetch_approval_requests: {e}")
        return []
    finally:
        if conn:
            conn.close()


def update_approval_request(approval_id, status, reviewer, response_note=None):
    conn = None
    try:
        timestamp = datetime.now().isoformat()
        with db_lock:
            conn = sqlite3.connect(DB_PATH, timeout=30)
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE approval_requests SET status = ?, reviewed_by = ?, reviewed_at = ?, response_note = ? WHERE id = ?",
                (status, reviewer, timestamp, response_note, approval_id),
            )
            conn.commit()
            return True
    except sqlite3.Error as e:
        print(f"[DB Error] update_approval_request: {e}")
        return False
    finally:
        if conn:
            conn.close()


# ------------------------
# FONCTIONS COLLABORATEURS
# ------------------------

def fetch_collaborators():
    conn = None
    try:
        with db_lock:
            conn = sqlite3.connect(DB_PATH, timeout=30)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, full_name, department, job_title, email, phone, hire_date, notes FROM collaborators ORDER BY full_name"
            )
            return cursor.fetchall()
    except sqlite3.Error as e:
        print(f"[DB Error] fetch_collaborators: {e}")
        return []
    finally:
        if conn:
            conn.close()


def save_collaborator(full_name, department='', job_title='', email='', phone='', hire_date='', notes='', collaborator_id=None):
    if not full_name:
        raise ValueError("Le nom complet est requis")
    conn = None
    try:
        with db_lock:
            conn = sqlite3.connect(DB_PATH, timeout=30)
            cursor = conn.cursor()
            if collaborator_id:
                cursor.execute(
                    """
                    UPDATE collaborators
                    SET full_name = ?, department = ?, job_title = ?, email = ?, phone = ?, hire_date = ?, notes = ?
                    WHERE id = ?
                    """,
                    (full_name, department, job_title, email, phone, hire_date, notes, collaborator_id),
                )
            else:
                cursor.execute(
                    """
                    INSERT INTO collaborators (full_name, department, job_title, email, phone, hire_date, notes)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (full_name, department, job_title, email, phone, hire_date, notes),
                )
            conn.commit()
            return collaborator_id or cursor.lastrowid
    except sqlite3.Error as e:
        print(f"[DB Error] save_collaborator: {e}")
        return None
    finally:
        if conn:
            conn.close()


def delete_collaborator(collaborator_id):
    conn = None
    try:
        with db_lock:
            conn = sqlite3.connect(DB_PATH, timeout=30)
            cursor = conn.cursor()
            cursor.execute("DELETE FROM collaborator_gear WHERE collaborator_id = ?", (collaborator_id,))
            cursor.execute("DELETE FROM collaborators WHERE id = ?", (collaborator_id,))
            conn.commit()
            return True
    except sqlite3.Error as e:
        print(f"[DB Error] delete_collaborator: {e}")
        return False
    finally:
        if conn:
            conn.close()


def fetch_collaborator_gear(collaborator_id=None, status=None):
    conn = None
    try:
        query = (
            "SELECT collaborator_gear.id, collaborators.full_name, items.name, collaborator_gear.size, collaborator_gear.quantity,"
            " collaborator_gear.issued_at, collaborator_gear.due_date, collaborator_gear.status, collaborator_gear.returned_at,"
            " collaborator_gear.notes, collaborator_gear.item_id, collaborator_gear.collaborator_id"
            " FROM collaborator_gear"
            " JOIN collaborators ON collaborators.id = collaborator_gear.collaborator_id"
            " JOIN items ON items.id = collaborator_gear.item_id"
        )
        params = []
        conditions: list[str] = []
        if collaborator_id:
            conditions.append("collaborator_gear.collaborator_id = ?")
            params.append(collaborator_id)
        if status:
            if isinstance(status, (list, tuple, set)):
                placeholders = ','.join('?' for _ in status)
                conditions.append(f"collaborator_gear.status IN ({placeholders})")
                params.extend(status)
            elif status == 'active':
                conditions.append("collaborator_gear.status NOT IN ('returned', 'lost', 'damaged')")
            else:
                conditions.append("collaborator_gear.status = ?")
                params.append(status)
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY collaborator_gear.issued_at DESC"
        with db_lock:
            conn = sqlite3.connect(DB_PATH, timeout=30)
            cursor = conn.cursor()
            cursor.execute(query, params)
            return cursor.fetchall()
    except sqlite3.Error as e:
        print(f"[DB Error] fetch_collaborator_gear: {e}")
        return []
    finally:
        if conn:
            conn.close()


def assign_collaborator_gear(collaborator_id, item_id, quantity, size, due_date, notes, operator):
    conn = None
    try:
        issued_at = datetime.now().isoformat()
        normalized_due = None
        if due_date:
            normalized_due = parse_user_date(due_date)
        with db_lock:
            conn = sqlite3.connect(DB_PATH, timeout=30)
            cursor = conn.cursor()
            cursor.execute("SELECT quantity FROM items WHERE id = ?", (item_id,))
            row = cursor.fetchone()
            if not row:
                raise ValueError("Article introuvable dans l'inventaire")
            available = row[0] or 0
            if quantity > available:
                raise ValueError(f"Stock insuffisant : {available} article(s) disponible(s)")
            cursor.execute(
                """
                INSERT INTO collaborator_gear (collaborator_id, item_id, size, quantity, issued_at, due_date, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (collaborator_id, item_id, size, quantity, issued_at, normalized_due, notes),
            )
            conn.commit()
        adjust_item_quantity(
            item_id,
            -abs(quantity),
            operator=operator,
            source='collaborator_assignment',
            note=f"Attribution collaborateur #{collaborator_id}",
        )
        return True
    except ValueError:
        raise
    except sqlite3.Error as e:
        print(f"[DB Error] assign_collaborator_gear: {e}")
        return False
    finally:
        if conn:
            conn.close()


def close_collaborator_gear(gear_id, quantity, operator, response_note='', status='returned', restock=True):
    conn = None
    try:
        returned_at = datetime.now().isoformat()
        note_suffix = ''
        if response_note:
            timestamp = datetime.now().strftime('%d/%m/%Y %H:%M')
            author = operator or 'système'
            note_suffix = f"\n[{timestamp}] {author} - {response_note}"
        with db_lock:
            conn = sqlite3.connect(DB_PATH, timeout=30)
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE collaborator_gear
                SET status = ?, returned_at = ?, notes = COALESCE(notes, '') || ?
                WHERE id = ?
                """,
                (status, returned_at, note_suffix, gear_id),
            )
            conn.commit()
        if restock:
            item_info = get_item_from_gear(gear_id)
            if item_info:
                item_id, stored_quantity = item_info
                quantity_to_add = abs(quantity if quantity is not None else stored_quantity or 0)
                if quantity_to_add:
                    adjust_item_quantity(
                        item_id,
                        quantity_to_add,
                        operator=operator,
                        source='collaborator_return',
                        note=f"Retour dotation #{gear_id}",
                    )
        return True
    except sqlite3.Error as e:
        print(f"[DB Error] close_collaborator_gear: {e}")
        return False
    finally:
        if conn:
            conn.close()


def update_collaborator_gear_due_date(gear_id, new_due_date, operator, note=''):
    conn = None
    try:
        normalized = parse_user_date(new_due_date) if new_due_date else None
        message = "Échéance supprimée"
        if normalized:
            message = f"Échéance ajustée au {format_display_date(normalized)}"
        if note:
            message = f"{message} ({note})"
        timestamp = datetime.now().strftime('%d/%m/%Y %H:%M')
        author = operator or 'système'
        suffix = f"\n[{timestamp}] {author} - {message}"
        with db_lock:
            conn = sqlite3.connect(DB_PATH, timeout=30)
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE collaborator_gear SET due_date = ?, notes = COALESCE(notes, '') || ? WHERE id = ?",
                (normalized, suffix, gear_id),
            )
            conn.commit()
        return True
    except ValueError:
        raise
    except sqlite3.Error as e:
        print(f"[DB Error] update_collaborator_gear_due_date: {e}")
        return False
    finally:
        if conn:
            conn.close()


def get_item_from_gear(gear_id):
    conn = None
    try:
        with db_lock:
            conn = sqlite3.connect(DB_PATH, timeout=30)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT item_id, quantity FROM collaborator_gear WHERE id = ?",
                (gear_id,),
            )
            result = cursor.fetchone()
            if result:
                return result[0], result[1]
    except sqlite3.Error as e:
        print(f"[DB Error] get_item_from_gear: {e}")
    finally:
        if conn:
            conn.close()
    return None


# ------------------------
# ALERTES / TABLEAU DE BORD
# ------------------------

def record_stock_alert(item_id, message, channel='internal', alert_level='low'):
    conn = None
    try:
        timestamp = datetime.now().isoformat()
        with db_lock:
            conn = sqlite3.connect(DB_PATH, timeout=30)
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO stock_alerts (item_id, triggered_at, alert_level, channel, message) VALUES (?, ?, ?, ?, ?)",
                (item_id, timestamp, alert_level, channel, message),
            )
            conn.commit()
            return cursor.lastrowid
    except sqlite3.Error as e:
        print(f"[DB Error] record_stock_alert: {e}")
        return None
    finally:
        if conn:
            conn.close()


def has_recent_alert(item_id, within_hours=24):
    conn = None
    try:
        threshold_time = (datetime.now() - timedelta(hours=within_hours)).isoformat()
        with db_lock:
            conn = sqlite3.connect(DB_PATH, timeout=30)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) FROM stock_alerts WHERE item_id = ? AND triggered_at >= ?",
                (item_id, threshold_time),
            )
            count = cursor.fetchone()[0]
            return count > 0
    except sqlite3.Error as e:
        print(f"[DB Error] has_recent_alert: {e}")
        return False
    finally:
        if conn:
            conn.close()


def _fetch_clothing_dashboard_metrics(
    low_stock_threshold: int,
    *,
    sales_days: int = 30,
    movement_days: int = 14,
) -> dict:
    summary = {
        "total_items": 0,
        "total_quantity": 0,
        "stock_value": 0.0,
        "low_stock_count": 0,
        "top_sales": [],
        "movement_history": [],
    }
    if clothing_inventory_manager is None:
        return summary

    conn = None
    try:
        with db_lock:
            conn = sqlite3.connect(DB_PATH, timeout=30)
            cursor = conn.cursor()
            clothing_inventory_manager.ensure_schema(cursor=cursor)

            cursor.execute(
                "SELECT COUNT(*), COALESCE(SUM(quantity), 0), "
                "COALESCE(SUM(quantity * COALESCE(unit_cost, 0)), 0) "
                "FROM clothing_inventory"
            )
            total_items, total_quantity, stock_value = cursor.fetchone()

            cursor.execute(
                """
                SELECT COUNT(*)
                  FROM clothing_inventory
                 WHERE quantity <= COALESCE(reorder_point, ?)
                """,
                (low_stock_threshold,),
            )
            low_stock = cursor.fetchone()[0]

            sales_since = (datetime.now() - timedelta(days=sales_days)).isoformat()
            cursor.execute(
                """
                SELECT ci.name,
                       ABS(SUM(CASE WHEN cm.quantity_change < 0 THEN cm.quantity_change ELSE 0 END))
                  FROM clothing_movements AS cm
                  JOIN clothing_inventory AS ci ON ci.id = cm.clothing_id
                 WHERE cm.created_at >= ?
              GROUP BY ci.name
              ORDER BY 2 DESC
                 LIMIT 5
                """,
                (sales_since,),
            )
            top_sales = cursor.fetchall()

            movement_since = (datetime.now() - timedelta(days=movement_days)).isoformat()
            cursor.execute(
                """
                SELECT DATE(substr(cm.created_at, 1, 10)) AS jour,
                       SUM(CASE WHEN cm.quantity_change > 0 THEN cm.quantity_change ELSE 0 END) AS entrees,
                       SUM(CASE WHEN cm.quantity_change < 0 THEN ABS(cm.quantity_change) ELSE 0 END) AS sorties
                  FROM clothing_movements AS cm
                 WHERE cm.created_at >= ?
              GROUP BY jour
              ORDER BY jour
                """,
                (movement_since,),
            )
            movement_history = cursor.fetchall()

        summary.update(
            {
                "total_items": total_items or 0,
                "total_quantity": total_quantity or 0,
                "stock_value": float(stock_value or 0.0),
                "low_stock_count": low_stock or 0,
                "top_sales": top_sales,
                "movement_history": movement_history,
            }
        )
    except sqlite3.Error as exc:
        print(f"[DB Error] _fetch_clothing_dashboard_metrics: {exc}")
    finally:
        if conn:
            conn.close()
    return summary


def fetch_dashboard_metrics(
    low_stock_threshold,
    category_id=None,
    sales_days=30,
    movement_days=14,
    module_scope: str = "general",
):
    if module_scope == "clothing":
        return _fetch_clothing_dashboard_metrics(
            int(low_stock_threshold),
            sales_days=int(sales_days),
            movement_days=int(movement_days),
        )
    conn = None
    try:
        with db_lock:
            conn = sqlite3.connect(DB_PATH, timeout=30)
            cursor = conn.cursor()
            filter_is_medicine = module_scope == "pharmacy"

            item_conditions: list[str] = []
            item_params: list[Any] = []
            if filter_is_medicine:
                item_conditions.append("items.is_medicine = 1")
            if category_id is not None:
                item_conditions.append("items.category_id = ?")
                item_params.append(category_id)

            item_query = (
                "SELECT COUNT(*), COALESCE(SUM(quantity),0), "
                "COALESCE(SUM(quantity * COALESCE(unit_cost,0)),0) FROM items"
            )
            if item_conditions:
                item_query += " WHERE " + " AND ".join(item_conditions)
            cursor.execute(item_query, item_params)
            total_items, total_quantity, stock_value = cursor.fetchone()

            low_stock_query = (
                "SELECT COUNT(*) FROM items "
                "WHERE quantity <= COALESCE(reorder_point, ?)"
            )
            low_stock_params: list[Any] = [low_stock_threshold]
            if filter_is_medicine:
                low_stock_query += " AND is_medicine = 1"
            if category_id is not None:
                low_stock_query += " AND category_id = ?"
                low_stock_params.append(category_id)
            cursor.execute(low_stock_query, low_stock_params)
            low_stock_count = cursor.fetchone()[0]

            sales_since = (datetime.now() - timedelta(days=sales_days)).isoformat()
            scope_filter = ""
            if filter_is_medicine:
                scope_filter += " AND items.is_medicine = 1"
            if category_id is not None:
                scope_filter += " AND items.category_id = ?"

            top_sales_query = (
                """
                SELECT items.name, ABS(SUM(stock_movements.quantity_change)) AS total_movement
                FROM stock_movements
                JOIN items ON items.id = stock_movements.item_id
                WHERE stock_movements.movement_type = 'OUT' AND stock_movements.created_at >= ?
                {scope_filter}
                GROUP BY items.name
                ORDER BY total_movement DESC
                LIMIT 5
                """
            ).format(scope_filter=scope_filter)
            top_sales_params = [sales_since]
            if category_id is not None:
                top_sales_params.append(category_id)
            cursor.execute(top_sales_query, top_sales_params)
            top_sales = cursor.fetchall()

            movement_since = (datetime.now() - timedelta(days=movement_days)).isoformat()
            movement_query = (
                """
                SELECT DATE(substr(stock_movements.created_at, 1, 10)) AS jour,
                       SUM(CASE WHEN stock_movements.movement_type = 'IN' THEN stock_movements.quantity_change ELSE 0 END) AS entrees,
                       SUM(CASE WHEN stock_movements.movement_type = 'OUT' THEN ABS(stock_movements.quantity_change) ELSE 0 END) AS sorties
                FROM stock_movements
                JOIN items ON items.id = stock_movements.item_id
                WHERE stock_movements.created_at >= ?
                {scope_filter}
                GROUP BY jour
                ORDER BY jour
                """
            ).format(scope_filter=scope_filter)
            movement_params = [movement_since]
            if category_id is not None:
                movement_params.append(category_id)
            cursor.execute(movement_query, movement_params)
            movement_history = cursor.fetchall()
        return {
            'total_items': total_items,
            'total_quantity': total_quantity,
            'stock_value': stock_value,
            'low_stock_count': low_stock_count,
            'top_sales': top_sales,
            'movement_history': movement_history,
        }
    except sqlite3.Error as e:
        print(f"[DB Error] fetch_dashboard_metrics: {e}")
        return {
            'total_items': 0,
            'total_quantity': 0,
            'stock_value': 0,
            'low_stock_count': 0,
            'top_sales': [],
            'movement_history': [],
        }
    finally:
        if conn:
            conn.close()

def delete_user_by_id(user_id: int) -> bool:
    """
    Supprime un utilisateur par son ID dans USER_DB_PATH. Retourne True si succès.
    """
    conn = None
    try:
        with db_lock:
            conn = sqlite3.connect(USER_DB_PATH, timeout=30)
            cursor = conn.cursor()
            cursor.execute("SELECT role FROM users WHERE id = ?", (user_id,))
            row = cursor.fetchone()
            if not row:
                return False
            role = row[0]
            if role == 'admin':
                cursor.execute(
                    "SELECT COUNT(*) FROM users WHERE role = 'admin' AND id != ?",
                    (user_id,),
                )
                remaining = cursor.fetchone()[0]
                if remaining <= 0:
                    return False
            cursor.execute("DELETE FROM user_modules WHERE user_id = ?", (user_id,))
            cursor.execute("DELETE FROM users WHERE id = ?", (user_id,))
            deleted = cursor.rowcount
            conn.commit()
        return deleted > 0
    except sqlite3.Error as e:
        print(f"[DB Error] delete_user_by_id: {e}")
        return False
    finally:
        if conn:
            conn.close()

def update_user_role(user_id: int, new_role: str) -> bool:
    """
    Met à jour le rôle d'un utilisateur dans USER_DB_PATH. new_role ∈ {'admin','user'}.
    """
    if new_role not in {'admin', 'user'}:
        raise ValueError("Le rôle doit être 'admin' ou 'user'.")
    conn = None
    try:
        with db_lock:
            conn = sqlite3.connect(USER_DB_PATH, timeout=30)
            cursor = conn.cursor()
            cursor.execute("SELECT role FROM users WHERE id = ?", (user_id,))
            row = cursor.fetchone()
            if not row:
                return False
            current_role = row[0]
            if current_role == new_role:
                return True
            if current_role == 'admin' and new_role != 'admin':
                cursor.execute(
                    "SELECT COUNT(*) FROM users WHERE role = 'admin' AND id != ?",
                    (user_id,),
                )
                remaining = cursor.fetchone()[0]
                if remaining <= 0:
                    return False
            cursor.execute("UPDATE users SET role = ? WHERE id = ?", (new_role, user_id))
            updated = cursor.rowcount
            if updated:
                defaults = default_module_permissions_for_role(new_role)
                for module, allowed in defaults.items():
                    cursor.execute(
                        """
                        INSERT OR REPLACE INTO user_modules (user_id, module, allowed)
                        VALUES (?, ?, ?)
                        """,
                        (user_id, module, 1 if allowed else 0),
                    )
            conn.commit()
        return updated > 0
    except sqlite3.Error as e:
        print(f"[DB Error] update_user_role: {e}")
        return False
    finally:
        if conn:
            conn.close()

# ------------------------
# SYNTHÈSE VOCALE
# ------------------------
if ENABLE_TTS and PYTTS3_LIB_AVAILABLE:
    def _configure_tts_engine(engine: "pyttsx3.Engine") -> None:
        """Ajuste la voix et la vitesse pour un rendu plus naturel."""

        try:
            voices = engine.getProperty("voices") or []
        except Exception as voices_err:  # pragma: no cover - dépend du backend TTS
            print(f"[TTS] Impossible de récupérer les voix : {voices_err}")
            voices = []

        def _matches_french_voice(voice: "pyttsx3.voice.Voice") -> bool:
            voice_id = getattr(voice, "id", "") or ""
            languages = []
            try:
                languages = list(getattr(voice, "languages", []) or [])
            except Exception:
                languages = []
            normalized_langs = []
            for lang in languages:
                if isinstance(lang, bytes):
                    normalized_langs.append(lang.decode("utf-8", errors="ignore"))
                elif isinstance(lang, str):
                    normalized_langs.append(lang)
            normalized_langs.append(voice_id)
            return any("fr" in (lang or "").lower() for lang in normalized_langs)

        selected_voice = next((voice for voice in voices if _matches_french_voice(voice)), None)
        if selected_voice is not None:
            try:
                engine.setProperty("voice", selected_voice.id)
                print(f"[TTS] Voix sélectionnée : {getattr(selected_voice, 'name', selected_voice.id)}")
            except Exception as voice_err:  # pragma: no cover - dépend du backend TTS
                print(f"[TTS] Impossible de sélectionner la voix '{selected_voice.id}': {voice_err}")

        try:
            current_rate = engine.getProperty("rate")
            if isinstance(current_rate, (int, float)):
                # Une vitesse légèrement réduite donne un rendu plus naturel.
                target_rate = max(140, min(180, int(current_rate * 0.9)))
                engine.setProperty("rate", target_rate)
                print(f"[TTS] Vitesse ajustée à {target_rate} (anciennement {current_rate})")
        except Exception as rate_err:  # pragma: no cover - dépend du backend TTS
            print(f"[TTS] Impossible d'ajuster la vitesse : {rate_err}")

        try:
            engine.setProperty("volume", 1.0)
        except Exception as volume_err:  # pragma: no cover - dépend du backend TTS
            print(f"[TTS] Impossible d'ajuster le volume : {volume_err}")

    def _create_tts_engine() -> tuple["pyttsx3.Engine", str]:
        attempts: list[str] = []
        preferred = (TTS_TYPE or 'auto').lower()
        if preferred and preferred not in {'', 'auto'}:
            attempts.append(preferred)
        attempts.append('auto')
        last_error: Optional[Exception] = None
        for driver_name in attempts:
            try:
                init_kwargs = {} if driver_name == 'auto' else {'driverName': driver_name}
                engine = pyttsx3.init(**init_kwargs)
                print(f"[TTS] Moteur initialisé avec '{driver_name}'.")
                return engine, driver_name
            except Exception as err:  # pragma: no cover - dépend du backend TTS
                last_error = err
                print(f"[TTS] Échec initialisation driver '{driver_name}': {err}")
        raise last_error or RuntimeError("Impossible d'initialiser le moteur TTS")

    try:
        tts_engine, ACTIVE_TTS_DRIVER = _create_tts_engine()
        _configure_tts_engine(tts_engine)

        def speak(text):
            print(f"[SPEAK] {text}")
            try:
                tts_engine.say(text)
                tts_engine.runAndWait()
            except Exception as e:  # pragma: no cover - dépend du backend TTS
                print(f"[TTS erreur] {e} | Texte à lire : {text}")
    except Exception as init_err:
        ACTIVE_TTS_DRIVER = None
        print(f"[TTS désactivé à l'init] {init_err}")

        def speak(text):
            print(f"[SPEAK-DISABLED] {text}")
else:
    def speak(text):
        print(f"[SPEAK-DISABLED] {text}")

# ---------------------------
# CONFIGURATION MICRO
# ---------------------------
if ENABLE_VOICE and SR_LIB_AVAILABLE:
    def list_microphones():
        return sr.Microphone.list_microphone_names()

    def choose_microphone(parent):
        mics = list_microphones()
        prompt = "Liste des microphones disponibles (index : nom) :\n"
        for i, name in enumerate(mics):
            prompt += f"{i} : {name}\n"
        idx = simpledialog.askinteger("Sélection Micro", f"{prompt}\nEntrez le numéro du micro à utiliser :", parent=parent)
        if idx is not None and 0 <= idx < len(mics):
            return idx
        return None

    def init_recognizer():
        global recognizer, microphone, voice_active
        recognizer = sr.Recognizer()
        try:
            mic_kwargs = {}
            if MICROPHONE_INDEX is not None and MICROPHONE_INDEX >= 0:
                mic_kwargs['device_index'] = MICROPHONE_INDEX
            microphone = sr.Microphone(**mic_kwargs)
            with microphone as source:
                pass
            mic_names = sr.Microphone.list_microphone_names()
            if MICROPHONE_INDEX is not None and 0 <= MICROPHONE_INDEX < len(mic_names):
                selected_name = mic_names[MICROPHONE_INDEX]
                debug_index = MICROPHONE_INDEX
            else:
                selected_name = 'défaut système'
                debug_index = 'défaut'
            print(f"[DEBUG_VOICE] Micro initialisé avec index {debug_index} : {selected_name}")
        except Exception as e:
            microphone = None
            print(f"[DEBUG_VOICE] Impossible d'initialiser le microphone ({e}). Reconnaissance vocale désactivée.")
        voice_active = False

    init_recognizer()

    def listen_commands():
        global voice_active
        print("[DEBUG_VOICE] Thread listen_commands démarré, voice_active =", voice_active)
        while voice_active:
            if microphone is None:
                print("[DEBUG_VOICE] microphone est None, on attend…")
                voice_active = False
                break
            try:
                with microphone as source:
                    if source is None:
                        print("[DEBUG_VOICE] source est None, on désactive la voix.")
                        voice_active = False
                        break
                    print("[DEBUG_VOICE] Ajustement du bruit ambiant…")
                    recognizer.adjust_for_ambient_noise(source)
                    print("[DEBUG_VOICE] J’écoute…")
                    audio = recognizer.listen(source, timeout=5, phrase_time_limit=5)
                    print("[DEBUG_VOICE] Audio capté, en cours de reconnaissance…")
                try:
                    command = recognizer.recognize_google(audio, language="fr-FR").lower()
                    print(f"[DEBUG_VOICE] Reconnu : '{command}'")
                    handle_voice_command(command)
                except sr.UnknownValueError:
                    print("[DEBUG_VOICE] Reconnaissance Google : son incompréhensible")
                except sr.RequestError as e:
                    print(f"[DEBUG_VOICE] Erreur RequestError (connexion Internet ?) : {e}")
            except sr.WaitTimeoutError:
                print("[DEBUG_VOICE] Timeout : aucun son détecté pendant 5s")
            except Exception as e:
                print(f"[DEBUG_VOICE] Exception inattendue dans listen_commands: {e}")
                voice_active = False
                break
            time.sleep(1)
        print("[DEBUG_VOICE] Fin de la boucle listen_commands, voice_active =", voice_active)

    def show_voice_help_direct():
        help_text = (
            "Commandes vocales disponibles :\n"
            " • 'ajouter [nombre] [nom de l'article]'   → ajoute la quantité spécifiée\n"
            " • 'retirer [nombre] [nom de l'article]'   → retire la quantité spécifiée\n"
            " • 'quantité de [nom de l'article]'        → annonce la quantité actuelle\n"
            " • 'générer codebarre pour [nom de l'article]' → génère le code-barres associé\n"
            " • 'aide' ou 'aide vocale'                  → affiche cette aide\n"
            " • 'stop voice' ou 'arrête écoute'         → désactive la reconnaissance vocale\n"
        )
        print(help_text)
        try:
            speak("Voici la liste des commandes vocales disponibles : ")
            for line in help_text.split('\n'):
                if line.strip():
                    speak(line)
        except:
            pass

    def handle_voice_command(command):
        cmd = command.lower()
        try:
            speak(f"Commande reçue : {command}")
        except:
            pass
        if cmd.startswith("aide"):
            show_voice_help_direct()
            return
        if cmd.startswith("ajouter ") or cmd.startswith("ajoute "):
            text = cmd.replace("ajoute ", "ajouter ")
            parts = text.split()
            if len(parts) >= 3:
                try:
                    qty = int(parts[1]); name = " ".join(parts[2:])
                    add_item_by_voice(name, qty)
                except:
                    speak("Commande vocale non comprise pour l’ajout.")
            else:
                speak("Commande vocale non comprise pour l’ajout.")
        elif cmd.startswith("retirer "):
            parts = cmd.split()
            if len(parts) >= 3:
                try:
                    qty = int(parts[1]); name = " ".join(parts[2:])
                    add_item_by_voice(name, -qty)
                except:
                    speak("Commande vocale non comprise pour le retrait.")
            else:
                speak("Commande vocale non comprise pour le retrait.")
        elif "quantité de" in cmd:
            item = cmd.split("quantité de")[-1].strip()
            check_quantity_by_voice(item)
        elif "générer codebarre pour" in cmd or "generer codebarres pour" in cmd:
            if "pour" in cmd:
                item = cmd.split("pour", 1)[1].strip()
                generate_barcode_for_item(item)
            else:
                speak("Commande vocale non comprise pour la génération de code-barres.")
        elif "stop voice" in cmd or "arrête écoute" in cmd or "arrete écoute" in cmd:
            global voice_active
            voice_active = False
            speak("Commande vocale désactivée.")
        else:
            speak("Commande vocale non reconnue.")

    def start_voice_listening():
        global voice_active
        if microphone is None:
            messagebox.showerror("Vocal", "Impossible d'accéder au microphone.")
            return
        if not voice_active:
            voice_active = True
            threading.Thread(target=listen_commands, daemon=True).start()
            speak("Écoute vocale activée.")

    def stop_voice_listening():
        global voice_active
        voice_active = False
        speak("Écoute vocale désactivée.")

else:
    def init_recognizer(): pass
    def listen_commands(): pass
    def show_voice_help_direct(): pass
    def handle_voice_command(command): pass
    def start_voice_listening():
        messagebox.showwarning("Vocal", "Reconnaissance vocale non disponible.")
    def stop_voice_listening(): pass

# ----------------------
# FONCTIONS VOCALES AIDE
# ----------------------
def add_item_by_voice(name, qty):
    conn = None
    change = 0
    final_qty = 0
    try:
        with db_lock:
            conn = sqlite3.connect(DB_PATH, timeout=30)
            cursor = conn.cursor()
            cursor.execute("SELECT id, quantity FROM items WHERE lower(name)=?", (name.lower(),))
            result = cursor.fetchone()
            if result:
                item_id, current_qty = result[0], result[1] or 0
                timestamp = datetime.now().isoformat()
                new_qty = current_qty + qty
                if new_qty < 0:
                    new_qty = 0
                cursor.execute(
                    "UPDATE items SET quantity = ?, last_updated = ? WHERE id = ?",
                    (new_qty, timestamp, item_id)
                )
                change = new_qty - current_qty
                final_qty = new_qty
                if change:
                    movement_type = 'IN' if change > 0 else 'OUT'
                    log_stock_movement(
                        cursor,
                        item_id,
                        change,
                        movement_type,
                        'voice_command',
                        'assistant vocal',
                        note="Commande vocale",
                        timestamp=timestamp,
                    )
            else:
                timestamp = datetime.now().isoformat()
                initial_qty = qty if qty > 0 else 0
                cursor.execute(
                    "INSERT INTO items (name, quantity, last_updated) VALUES (?, ?, ?)",
                    (name, initial_qty, timestamp)
                )
                item_id = cursor.lastrowid
                change = initial_qty
                final_qty = initial_qty
                if initial_qty:
                    log_stock_movement(
                        cursor,
                        item_id,
                        initial_qty,
                        'IN',
                        'voice_command',
                        'assistant vocal',
                        note="Création via commande vocale",
                        timestamp=timestamp,
                    )
            conn.commit()
    except sqlite3.Error as e:
        print(f"[DB Error] add_item_by_voice: {e}")
    finally:
        if conn:
            conn.close()
    if change > 0:
        speak(f"{change} unités ajoutées à {name}. Stock actuel : {final_qty}.")
    elif change < 0:
        speak(f"{abs(change)} unités retirées de {name}. Stock actuel : {final_qty}.")
    else:
        speak(f"Aucune modification pour {name}.")

def check_quantity_by_voice(name):
    conn = None
    try:
        with db_lock:
            conn = sqlite3.connect(DB_PATH, timeout=30)
            cursor = conn.cursor()
            cursor.execute("SELECT quantity FROM items WHERE lower(name)=?", (name.lower(),))
            result = cursor.fetchone()
    except sqlite3.Error as e:
        print(f"[DB Error] check_quantity_by_voice: {e}")
        result = None
    finally:
        if conn:
            conn.close()
    if result:
        qty = result[0]
        speak(f"La quantité de {name} est {qty}.")
    else:
        speak(f"L'article {name} n'existe pas.")

# ----------------------
# GÉNÉRATION DE CODES-BARRES
# ----------------------
def save_barcode_image(barcode_value, article_name):
    if not ENABLE_BARCODE_GENERATION:
        print(f"[DEBUG] save_barcode_image: génération désactivée")
        return None
    if not BARCODE_GENERATOR_LIB:
        print(f"[DEBUG] save_barcode_image: lib python-barcode non trouvée")
        return None

    safe_name = article_name.replace(" ", "_")
    safe_name = "".join(ch for ch in safe_name if ch.isalnum() or ch == "_")
    try:
        print(f"[DEBUG] save_barcode_image: tentative pour '{barcode_value}', fichier='{safe_name}.png'")
        filepath_no_ext = os.path.join(BARCODE_DIR, safe_name)
        writer = ImageWriter()
        options = {
            'write_text': True,
            'text': article_name,
            'font_size': 14,
            'text_distance': 5
        }
        font_path = None
        if sys.platform == "win32":
            possible = os.path.join(os.environ.get('WINDIR', 'C:\\Windows'), 'Fonts', 'arial.ttf')
            if os.path.exists(possible):
                font_path = possible
        if font_path:
            options['font_path'] = font_path

        try:
            barcode_obj = barcode.Code128(barcode_value, writer=writer)
            full_path = barcode_obj.save(filepath_no_ext, options)
            print(f"[DEBUG] save_barcode_image: créé → {full_path}")
            return full_path
        except OSError as e:
            print(f"[ERREUR BARCODE] Échec texte pour '{barcode_value}' ({e}), tentative sans texte.")
            options_no_text = {'write_text': False}
            barcode_obj = barcode.Code128(barcode_value, writer=writer)
            full_path = barcode_obj.save(filepath_no_ext, options_no_text)
            print(f"[DEBUG] save_barcode_image: créé (sans texte) → {full_path}")
            return full_path

    except Exception as e:
        print(f"[ERREUR BARCODE] Impossible de générer '{barcode_value}'. Exception: {e}")
        traceback.print_exc()
        return None

def generate_barcode_for_item(name):
    if not ENABLE_BARCODE_GENERATION:
        speak("La génération de code-barres est désactivée.")
        return
    conn = None
    try:
        with db_lock:
            conn = sqlite3.connect(DB_PATH, timeout=30)
            cursor = conn.cursor()
            cursor.execute("SELECT barcode FROM items WHERE lower(name)=?", (name.lower(),))
            result = cursor.fetchone()
    except sqlite3.Error as e:
        print(f"[DB Error] generate_barcode_for_item: {e}")
        result = None
    finally:
        if conn:
            conn.close()
    if not result or not result[0]:
        speak(f"Impossible de générer : l'article {name} n'existe pas ou n'a pas de code-barres.")
        return
    code = result[0]
    if not BARCODE_GENERATOR_LIB:
        speak("La génération de code-barres n'est pas disponible.")
        return
    filepath = save_barcode_image(code, article_name=name)
    if filepath:
        speak(f"Code-barres généré pour {name} → {filepath}.")
    else:
        speak(f"Erreur lors de la génération du code-barres pour {name}.")

# ----------------------
# BOÎTE DE DIALOGUE AUTHENTIFICATION
# ----------------------
class LoginDialog(tk.Toplevel):
    """
    Dialogue de connexion. Si pas d'utilisateur existant, appelle création.
    Gère 'se souvenir du login'.
    """
    def __init__(self, parent):
        super().__init__(parent)
        self.title("Connexion")
        self.resizable(False, False)
        self.result = False
        self.username = None
        self.role = None
        self.protocol("WM_DELETE_WINDOW", self.on_cancel)

        ttk.Label(self, text="Nom d'utilisateur :").grid(row=0, column=0, padx=10, pady=5, sticky=tk.W)
        self.entry_user = ttk.Entry(self, width=30)
        self.entry_user.grid(row=0, column=1, padx=10, pady=5)
        if LAST_USER:
            self.entry_user.insert(0, LAST_USER)

        ttk.Label(self, text="Mot de passe :").grid(row=1, column=0, padx=10, pady=5, sticky=tk.W)
        self.entry_pwd = ttk.Entry(self, show="*", width=30)
        self.entry_pwd.grid(row=1, column=1, padx=10, pady=5)

        self.var_remember = tk.BooleanVar(value=bool(LAST_USER))
        chk_remember = ttk.Checkbutton(self, text="Se souvenir de moi", variable=self.var_remember)
        chk_remember.grid(row=2, column=0, columnspan=2, padx=10, pady=5, sticky=tk.W)

        btn_frame = ttk.Frame(self)
        btn_frame.grid(row=3, column=0, columnspan=2, pady=10)
        ttk.Button(btn_frame, text="Connexion", command=self.on_login).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Annuler", command=self.on_cancel).pack(side=tk.LEFT, padx=5)

        if not users_exist():
            self.destroy()
            CreateUserDialog(parent)
            return

        self.entry_user.focus()
        self.grab_set()
        self.wait_window(self)

    def on_login(self):
        username = self.entry_user.get().strip()
        password = self.entry_pwd.get().strip()
        if not username or not password:
            messagebox.showerror("Erreur", "Nom d'utilisateur et mot de passe requis.")
            return
        ok, role = verify_user(username, password)
        if ok:
            self.username = username
            self.role = role
            if self.var_remember.get():
                config['Settings']['last_user'] = username
            else:
                config['Settings']['last_user'] = ''
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                config.write(f)
            self.result = True
            self.destroy()
        else:
            messagebox.showerror("Erreur", "Identifiants incorrects.")

    def on_cancel(self):
        self.result = False
        self.destroy()

class CreateUserDialog(tk.Toplevel):
    """
    Dialogue pour créer le premier utilisateur (admin).
    """
    def __init__(self, parent):
        super().__init__(parent)
        self.title("Création administrateur")
        self.resizable(False, False)
        self.result = False
        self.protocol("WM_DELETE_WINDOW", self.on_cancel)

        ttk.Label(self, text="Créer un compte administrateur").grid(row=0, column=0, columnspan=2, padx=10, pady=5)
        ttk.Label(self, text="Nom d'utilisateur :").grid(row=1, column=0, padx=10, pady=5, sticky=tk.W)
        self.entry_user = ttk.Entry(self, width=30)
        self.entry_user.grid(row=1, column=1, padx=10, pady=5)

        ttk.Label(self, text="Mot de passe :").grid(row=2, column=0, padx=10, pady=5, sticky=tk.W)
        self.entry_pwd1 = ttk.Entry(self, show="*", width=30)
        self.entry_pwd1.grid(row=2, column=1, padx=10, pady=5)

        ttk.Label(self, text="Confirmer mot de passe :").grid(row=3, column=0, padx=10, pady=5, sticky=tk.W)
        self.entry_pwd2 = ttk.Entry(self, show="*", width=30)
        self.entry_pwd2.grid(row=3, column=1, padx=10, pady=5)

        btn_frame = ttk.Frame(self)
        btn_frame.grid(row=4, column=0, columnspan=2, pady=10)
        ttk.Button(btn_frame, text="Créer", command=self.on_create).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Annuler", command=self.on_cancel).pack(side=tk.LEFT, padx=5)

        self.entry_user.focus()
        self.grab_set()
        self.wait_window(self)

    def on_create(self):
        username = self.entry_user.get().strip()
        pwd1 = self.entry_pwd1.get().strip()
        pwd2 = self.entry_pwd2.get().strip()
        if not username or not pwd1 or not pwd2:
            messagebox.showerror("Erreur", "Tous les champs sont requis.")
            return
        if pwd1 != pwd2:
            messagebox.showerror("Erreur", "Les mots de passe ne correspondent pas.")
            return
        if create_user(username, pwd1, role='admin'):
            messagebox.showinfo("Succès", "Administrateur créé. Veuillez vous reconnecter.")
            self.result = True
            self.destroy()
            LoginDialog(self.master)
        else:
            messagebox.showerror("Erreur", "Impossible de créer l'utilisateur (nom déjà existant).")

    def on_cancel(self):
        self.result = False
        self.destroy()

# ----------------------
# DIALOGUE GESTION UTILISATEURS (admin)
# ----------------------
class UserManagementDialog(tk.Toplevel):
    """
    Permet à l'admin de gérer les comptes : création, suppression, modification de rôle.
    """
    def __init__(self, parent, current_user_id):
        super().__init__(parent)
        self.title("Gestion des utilisateurs")
        self.resizable(False, False)
        self.current_user_id = current_user_id
        self.result = None

        columns = ('ID', 'Username', 'Role', 'Modules')
        self.user_list = ttk.Treeview(self, columns=columns, show='headings', height=8)
        self.user_list.heading('ID', text='ID'); self.user_list.column('ID', width=40, anchor=tk.CENTER)
        self.user_list.heading('Username', text='Nom d\'utilisateur'); self.user_list.column('Username', width=150)
        self.user_list.heading('Role', text='Rôle'); self.user_list.column('Role', width=80, anchor=tk.CENTER)
        self.user_list.heading('Modules', text='Modules autorisés'); self.user_list.column('Modules', width=220)
        self.user_list.grid(row=0, column=0, columnspan=4, padx=10, pady=5)
        self.load_users()

        ttk.Button(self, text="Ajouter", command=self.add_user).grid(row=1, column=0, padx=10, pady=5)
        ttk.Button(self, text="Supprimer", command=self.delete_user).grid(row=1, column=1, padx=10, pady=5)
        ttk.Button(self, text="Modifier Rôle", command=self.change_role).grid(row=1, column=2, padx=10, pady=5)
        ttk.Button(self, text="Modules", command=self.manage_modules).grid(row=1, column=3, padx=10, pady=5)
        ttk.Button(self, text="Fermer", command=self.on_close).grid(row=2, column=0, columnspan=4, pady=10)

        self.grab_set()
        self.wait_window(self)

    def load_users(self):
        for row in self.user_list.get_children():
            self.user_list.delete(row)
        rows = fetch_all_users()
        for user_id, username, role in rows:
            permissions = get_user_module_permissions(user_id, role=role)
            allowed_labels = [
                MODULE_LABELS.get(module, module.title())
                for module, allowed in permissions.items()
                if allowed
            ]
            modules_text = ', '.join(allowed_labels) if allowed_labels else 'Aucun'
            self.user_list.insert('', tk.END, values=(user_id, username, role, modules_text))

    def add_user(self):
        dlg = AddUserDialog(self)
        if dlg.result:
            username, pwd, role = dlg.result
            if create_user(username, pwd, role):
                self.load_users()
                messagebox.showinfo("Succès", f"Utilisateur '{username}' créé.")
            else:
                messagebox.showerror("Erreur", "Impossible de créer l'utilisateur (nom déjà existant).")

    def delete_user(self):
        sel = self.user_list.selection()
        if not sel:
            messagebox.showwarning("Attention", "Aucun utilisateur sélectionné.")
            return
        vals = self.user_list.item(sel[0])['values']
        user_id, username, role = vals
        if user_id == self.current_user_id:
            messagebox.showerror("Erreur", "Vous ne pouvez pas supprimer votre propre compte.")
            return
        if role == 'admin' and count_admin_users(exclude_user_id=user_id) == 0:
            messagebox.showerror(
                "Erreur",
                "Impossible de supprimer le dernier administrateur actif.",
            )
            return
        if messagebox.askyesno("Confirmer", f"Supprimer l'utilisateur '{username}' ?"):
            if delete_user_by_id(user_id):
                self.load_users()
                messagebox.showinfo("Succès", f"Utilisateur '{username}' supprimé.")
            else:
                messagebox.showerror(
                    "Erreur",
                    "Impossible de supprimer l'utilisateur (vérifiez les permissions).",
                )

    def change_role(self):
        sel = self.user_list.selection()
        if not sel:
            messagebox.showwarning("Attention", "Aucun utilisateur sélectionné.")
            return
        vals = self.user_list.item(sel[0])['values']
        user_id, username, role = vals
        if user_id == self.current_user_id:
            messagebox.showerror("Erreur", "Vous ne pouvez pas modifier votre propre rôle ici.")
            return
        new_role = simpledialog.askstring("Modifier rôle", f"Rôle pour '{username}' (admin / user) :", initialvalue=role, parent=self)
        if new_role and new_role in ('admin','user'):
            if role == 'admin' and new_role != 'admin' and count_admin_users(exclude_user_id=user_id) == 0:
                messagebox.showerror(
                    "Erreur",
                    "Impossible de retirer le dernier administrateur restant.",
                )
                return
            if update_user_role(user_id, new_role):
                self.load_users()
                messagebox.showinfo("Succès", f"Rôle de '{username}' changé en '{new_role}'.")
            else:
                messagebox.showerror(
                    "Erreur",
                    "Impossible de modifier le rôle (vérifiez les permissions).",
                )
        else:
            messagebox.showerror("Erreur", "Rôle invalide. Choisir 'admin' ou 'user'.")

    def manage_modules(self):
        sel = self.user_list.selection()
        if not sel:
            messagebox.showwarning("Attention", "Aucun utilisateur sélectionné.")
            return
        user_id, username, role, _modules = self.user_list.item(sel[0])['values']
        if role == 'admin':
            messagebox.showinfo(
                "Modules",
                "Les administrateurs disposent automatiquement de tous les modules.",
            )
            return
        permissions = get_user_module_permissions(user_id, role=role)
        dialog = ModulePermissionsDialog(self, username, permissions)
        if dialog.result is None:
            return
        if set_user_module_permissions(user_id, dialog.result):
            self.load_users()
            messagebox.showinfo(
                "Succès",
                f"Modules autorisés mis à jour pour '{username}'.",
            )
        else:
            messagebox.showerror(
                "Erreur",
                "Impossible de mettre à jour les permissions de modules.",
            )

    def on_close(self):
        self.destroy()

class AddUserDialog(tk.Toplevel):
    """
    Dialogue pour ajouter un compte utilisateur (admin uniquement).
    """
    def __init__(self, parent):
        super().__init__(parent)
        self.title("Ajouter utilisateur")
        self.resizable(False, False)
        self.result = None
        self.protocol("WM_DELETE_WINDOW", self.on_cancel)

        ttk.Label(self, text="Nom d'utilisateur :").grid(row=0, column=0, padx=10, pady=5, sticky=tk.W)
        self.entry_user = ttk.Entry(self, width=30)
        self.entry_user.grid(row=0, column=1, padx=10, pady=5)

        ttk.Label(self, text="Mot de passe :").grid(row=1, column=0, padx=10, pady=5, sticky=tk.W)
        self.entry_pwd1 = ttk.Entry(self, show="*", width=30)
        self.entry_pwd1.grid(row=1, column=1, padx=10, pady=5)

        ttk.Label(self, text="Confirmer mot de passe :").grid(row=2, column=0, padx=10, pady=5, sticky=tk.W)
        self.entry_pwd2 = ttk.Entry(self, show="*", width=30)
        self.entry_pwd2.grid(row=2, column=1, padx=10, pady=5)

        ttk.Label(self, text="Rôle :").grid(row=3, column=0, padx=10, pady=5, sticky=tk.W)
        self.role_combobox = ttk.Combobox(self, state='readonly', values=('admin','user'), width=28)
        self.role_combobox.grid(row=3, column=1, padx=10, pady=5)
        self.role_combobox.current(1)

        btn_frame = ttk.Frame(self)
        btn_frame.grid(row=4, column=0, columnspan=2, pady=10)
        ttk.Button(btn_frame, text="Créer", command=self.on_create).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Annuler", command=self.on_cancel).pack(side=tk.LEFT, padx=5)

        self.entry_user.focus()
        self.grab_set()
        self.wait_window(self)

    def on_create(self):
        username = self.entry_user.get().strip()
        pwd1 = self.entry_pwd1.get().strip()
        pwd2 = self.entry_pwd2.get().strip()
        role = self.role_combobox.get()
        if not username or not pwd1 or not pwd2:
            messagebox.showerror("Erreur", "Tous les champs sont requis.")
            return
        if pwd1 != pwd2:
            messagebox.showerror("Erreur", "Les mots de passe ne correspondent pas.")
            return
        self.result = (username, pwd1, role)
        self.destroy()

    def on_cancel(self):
        self.result = None
        self.destroy()


class ModulePermissionsDialog(tk.Toplevel):
    """Dialogue permettant de définir les modules autorisés pour un utilisateur."""

    def __init__(self, parent: tk.Misc, username: str, permissions: dict[str, bool]):
        super().__init__(parent)
        self.title(f"Modules - {username}")
        self.resizable(False, False)
        self.result: Optional[dict[str, bool]] = None
        self.protocol("WM_DELETE_WINDOW", self.on_cancel)

        ttk.Label(
            self,
            text=f"Autoriser l'accès aux modules pour {username} :",
        ).grid(row=0, column=0, columnspan=2, padx=10, pady=(10, 5), sticky=tk.W)

        self.vars: dict[str, tk.BooleanVar] = {}
        for index, module in enumerate(AVAILABLE_MODULES, start=1):
            label = MODULE_LABELS.get(module, module.title())
            var = tk.BooleanVar(value=bool(permissions.get(module, False)))
            self.vars[module] = var
            ttk.Checkbutton(self, text=label, variable=var).grid(
                row=index,
                column=0,
                columnspan=2,
                padx=15,
                pady=2,
                sticky=tk.W,
            )

        btn_frame = ttk.Frame(self)
        btn_frame.grid(row=len(AVAILABLE_MODULES) + 1, column=0, columnspan=2, pady=10)
        ttk.Button(btn_frame, text="Enregistrer", command=self.on_confirm).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Annuler", command=self.on_cancel).pack(side=tk.LEFT, padx=5)

        self.grab_set()
        self.wait_window(self)

    def on_confirm(self):
        self.result = {module: var.get() for module, var in self.vars.items()}
        self.destroy()

    def on_cancel(self):
        self.result = None
        self.destroy()


class ClothingItemDialog(tk.Toplevel):
    """Boîte de dialogue pour créer ou modifier un article d'habillement."""

    def __init__(
        self,
        parent: tk.Misc,
        title: str,
        *,
        sizes: Optional[list[str]] = None,
        initial: Optional[dict] = None,
    ) -> None:
        super().__init__(parent)
        self.title(title)
        self.resizable(False, False)
        self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", self.on_cancel)

        self.result: Optional[dict] = None
        self.default_sizes = sizes or []
        initial = initial or {}

        self.var_name = tk.StringVar(value=initial.get('name', ''))
        self.var_barcode = tk.StringVar(value=initial.get('barcode', ''))
        self.var_quantity = tk.StringVar(value=str(initial.get('quantity', 0)))
        initial_unit_cost = initial.get('unit_cost')
        self.var_unit_cost = tk.StringVar(
            value="0.0" if initial_unit_cost is None else f"{float(initial_unit_cost):.2f}"
        )
        reorder = initial.get('reorder_point')
        self.var_reorder_point = tk.StringVar(value="" if reorder in (None, "") else str(reorder))
        self.var_size = tk.StringVar(value=initial.get('size', ''))
        self.var_category = tk.StringVar(value=initial.get('category', ''))
        self.var_supplier_id = tk.IntVar(value=initial.get('preferred_supplier_id') or -1)

        content = ttk.Frame(self, padding=10)
        content.grid(row=0, column=0, sticky="nsew")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        ttk.Label(content, text="Nom :").grid(row=0, column=0, sticky=tk.W, pady=2)
        self.entry_name = ttk.Entry(content, textvariable=self.var_name, width=32)
        self.entry_name.grid(row=0, column=1, sticky=tk.W, pady=2)

        ttk.Label(content, text="Code-Barres :").grid(row=1, column=0, sticky=tk.W, pady=2)
        self.entry_barcode = ttk.Entry(content, textvariable=self.var_barcode, width=32)
        self.entry_barcode.grid(row=1, column=1, sticky=tk.W, pady=2)

        ttk.Label(content, text="Catégorie :").grid(row=2, column=0, sticky=tk.W, pady=2)
        self.category_combobox = ttk.Combobox(
            content,
            state='readonly',
            width=30,
            textvariable=self.var_category,
        )
        self.category_combobox.grid(row=2, column=1, sticky=tk.W, pady=2)
        ttk.Button(content, text="Nouvelle Cat.", command=self.add_category_inline).grid(
            row=2, column=2, padx=5, pady=2
        )

        ttk.Label(content, text="Taille :").grid(row=3, column=0, sticky=tk.W, pady=2)
        self.size_combobox = ttk.Combobox(content, textvariable=self.var_size, width=18, state='normal')
        self.size_combobox.grid(row=3, column=1, sticky=tk.W, pady=2)

        ttk.Label(content, text="Quantité :").grid(row=4, column=0, sticky=tk.W, pady=2)
        self.entry_quantity = ttk.Entry(content, textvariable=self.var_quantity, width=10)
        self.entry_quantity.grid(row=4, column=1, sticky=tk.W, pady=2)

        ttk.Label(content, text="Coût unitaire (€) :").grid(row=5, column=0, sticky=tk.W, pady=2)
        self.entry_unit_cost = ttk.Entry(content, textvariable=self.var_unit_cost, width=10)
        self.entry_unit_cost.grid(row=5, column=1, sticky=tk.W, pady=2)

        ttk.Label(content, text="Seuil de réassort :").grid(row=6, column=0, sticky=tk.W, pady=2)
        self.entry_reorder = ttk.Entry(content, textvariable=self.var_reorder_point, width=10)
        self.entry_reorder.grid(row=6, column=1, sticky=tk.W, pady=2)

        ttk.Label(content, text="Fournisseur préféré :").grid(row=7, column=0, sticky=tk.W, pady=2)
        self.supplier_combobox = ttk.Combobox(content, state='readonly', width=30)
        self.supplier_combobox.grid(row=7, column=1, sticky=tk.W, pady=2)
        ttk.Button(content, text="Rafraîchir", command=self.load_suppliers).grid(
            row=7, column=2, padx=5, pady=2
        )

        button_frame = ttk.Frame(content)
        button_frame.grid(row=8, column=0, columnspan=3, pady=(10, 0))
        ttk.Button(button_frame, text="Valider", command=self.on_ok).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Annuler", command=self.on_cancel).pack(side=tk.LEFT, padx=5)

        self.category_ids: list[int] = []
        self.category_names: list[str] = []
        self.supplier_ids: list[int] = []

        self.load_categories()
        self.load_suppliers()
        self.category_combobox.bind("<<ComboboxSelected>>", lambda _evt: self.update_size_options())
        self.update_size_options()

        self.bind('<Return>', lambda _event: self.on_ok())
        self.bind('<Escape>', lambda _event: self.on_cancel())
        self.entry_name.focus_set()

        self.grab_set()
        self.wait_window(self)

    def load_categories(self) -> None:
        conn = None
        try:
            with db_lock:
                conn = sqlite3.connect(DB_PATH, timeout=30)
                cursor = conn.cursor()
                cursor.execute("SELECT id, name FROM categories ORDER BY name")
                rows = cursor.fetchall()
        except sqlite3.Error:
            rows = []
        finally:
            if conn:
                conn.close()
        self.category_ids = [r[0] for r in rows]
        self.category_names = [r[1] for r in rows]
        self.category_combobox['values'] = self.category_names
        if self.var_category.get() and self.var_category.get() in self.category_names:
            index = self.category_names.index(self.var_category.get())
            self.category_combobox.current(index)
        elif self.category_names:
            self.category_combobox.set('')

    def load_suppliers(self) -> None:
        suppliers = fetch_suppliers()
        self.supplier_ids = [s[0] for s in suppliers]
        supplier_names = [s[1] for s in suppliers]
        self.supplier_combobox['values'] = supplier_names
        initial_id = self.var_supplier_id.get()
        if initial_id != -1 and initial_id in self.supplier_ids:
            self.supplier_combobox.current(self.supplier_ids.index(initial_id))
        elif supplier_names:
            self.supplier_combobox.set('')

    def add_category_inline(self) -> None:
        name = simpledialog.askstring("Nouvelle Catégorie", "Entrez le nom de la nouvelle catégorie :", parent=self)
        if not name:
            return
        note = simpledialog.askstring("Note de catégorie", "Entrez une note (optionnel) :", parent=self)
        sizes_input = simpledialog.askstring(
            "Tailles de la catégorie",
            "Indiquez les tailles séparées par une virgule (optionnel) :",
            parent=self,
        )
        sizes = []
        if sizes_input:
            sizes = [s.strip() for s in sizes_input.split(',') if s.strip()]
        conn = None
        try:
            with db_lock:
                conn = sqlite3.connect(DB_PATH, timeout=30)
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT INTO categories (name, note) VALUES (?, ?)",
                    (name, note.strip() if note and note.strip() else None),
                )
                category_id = cursor.lastrowid
                if sizes:
                    cursor.executemany(
                        "INSERT OR IGNORE INTO category_sizes (category_id, size_label) VALUES (?, ?)",
                        [(category_id, size) for size in sizes],
                    )
                conn.commit()
        except sqlite3.IntegrityError:
            messagebox.showerror("Erreur", "Catégorie existe déjà.", parent=self)
        except sqlite3.Error as exc:
            messagebox.showerror("Erreur BD", f"Impossible d'ajouter catégorie : {exc}", parent=self)
        finally:
            if conn:
                conn.close()
        self.var_category.set(name)
        self.load_categories()
        self.update_size_options()

    def update_size_options(self) -> None:
        idx = self.category_combobox.current()
        if idx is None or idx < 0:
            self.size_combobox.configure(state='normal')
            self.size_combobox['values'] = self.default_sizes
            return
        category_id = self.category_ids[idx]
        sizes = self._fetch_category_sizes(category_id)
        if sizes:
            self.size_combobox.configure(state='readonly')
            self.size_combobox['values'] = sizes
        else:
            self.size_combobox.configure(state='normal')
            self.size_combobox['values'] = self.default_sizes
        if self.var_size.get() not in self.size_combobox['values']:
            self.var_size.set('')

    def _fetch_category_sizes(self, category_id: int) -> list[str]:
        conn = None
        try:
            with db_lock:
                conn = sqlite3.connect(DB_PATH, timeout=30)
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT size_label FROM category_sizes WHERE category_id = ? ORDER BY size_label COLLATE NOCASE",
                    (category_id,),
                )
                return [row[0] for row in cursor.fetchall()]
        except sqlite3.Error:
            return []
        finally:
            if conn:
                conn.close()

    def on_ok(self) -> None:
        name = self.var_name.get().strip()
        barcode_value = self.var_barcode.get().strip()
        quantity_raw = self.var_quantity.get().strip()
        size_value = self.var_size.get().strip() or None
        cat_idx = self.category_combobox.current()
        category_value = None
        if cat_idx is not None and cat_idx >= 0 and cat_idx < len(self.category_names):
            category_value = self.category_names[cat_idx]
        elif self.var_category.get().strip():
            category_value = self.var_category.get().strip()
        supplier_idx = self.supplier_combobox.current()
        supplier_id = self.supplier_ids[supplier_idx] if supplier_idx >= 0 else None

        if not name:
            messagebox.showerror("Erreur", "Le nom de l'article est requis.", parent=self)
            return
        try:
            quantity = int(quantity_raw)
        except (TypeError, ValueError):
            messagebox.showerror("Erreur", "La quantité doit être un entier.", parent=self)
            return
        if quantity < 0:
            messagebox.showerror("Erreur", "La quantité doit être positive ou nulle.", parent=self)
            return
        if barcode_value and not barcode_value.isalnum():
            messagebox.showerror("Erreur", "Le code-barres doit être alphanumérique.", parent=self)
            return
        unit_cost_value: Optional[float]
        unit_cost_raw = self.var_unit_cost.get().strip()
        if unit_cost_raw:
            try:
                unit_cost_value = float(unit_cost_raw)
            except (TypeError, ValueError):
                messagebox.showerror("Erreur", "Le coût unitaire est invalide.", parent=self)
                return
        else:
            unit_cost_value = None
        reorder_raw = self.var_reorder_point.get().strip()
        reorder_value: Optional[int]
        if reorder_raw:
            try:
                reorder_value = int(reorder_raw)
                if reorder_value < 0:
                    raise ValueError
            except ValueError:
                messagebox.showerror(
                    "Erreur",
                    "Le seuil de réassort doit être un entier positif.",
                    parent=self,
                )
                return
        else:
            reorder_value = None

        self.result = {
            'name': name,
            'barcode': barcode_value or None,
            'category': category_value,
            'size': size_value,
            'quantity': quantity,
            'unit_cost': unit_cost_value,
            'reorder_point': reorder_value,
            'preferred_supplier_id': supplier_id,
        }
        self.destroy()

    def on_cancel(self) -> None:
        self.result = None
        self.destroy()


class PharmacyBatchDialog(tk.Toplevel):
    """Boîte de dialogue pour créer un lot pharmaceutique."""

    def __init__(
        self,
        parent: tk.Misc,
        title: str,
        *,
        initial: Optional[dict] = None,
    ) -> None:
        super().__init__(parent)
        self.title(title)
        self.resizable(False, False)
        self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", self.on_cancel)

        self.result: Optional[dict] = None

        initial = initial or {}

        self.var_name = tk.StringVar(value=initial.get('name', ''))
        self.var_lot = tk.StringVar(value=initial.get('lot_number', ''))
        self.var_quantity = tk.StringVar(value=str(initial.get('quantity', 0)))
        expiration_initial = initial.get('expiration_date')
        self.var_expiration = tk.StringVar(
            value=format_display_date(expiration_initial) if expiration_initial else ''
        )
        self.var_barcode = tk.StringVar(value=initial.get('barcode', ''))
        self.var_category = tk.StringVar(value=initial.get('category', ''))
        self.var_dosage = tk.StringVar(value=initial.get('dosage', ''))
        self.var_form = tk.StringVar(value=initial.get('form', ''))
        self.var_storage = tk.StringVar(value=initial.get('storage_condition', ''))
        self.var_prescription = tk.BooleanVar(value=bool(initial.get('prescription_required', False)))

        content = ttk.Frame(self, padding=10)
        content.grid(row=0, column=0, sticky="nsew")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        ttk.Label(content, text="Nom du médicament :").grid(row=0, column=0, sticky=tk.W, pady=2)
        self.entry_name = ttk.Entry(content, textvariable=self.var_name, width=40)
        self.entry_name.grid(row=0, column=1, sticky=tk.W, pady=2)

        ttk.Label(content, text="Numéro de lot :").grid(row=1, column=0, sticky=tk.W, pady=2)
        self.entry_lot = ttk.Entry(content, textvariable=self.var_lot, width=40)
        self.entry_lot.grid(row=1, column=1, sticky=tk.W, pady=2)

        ttk.Label(content, text="Quantité :").grid(row=2, column=0, sticky=tk.W, pady=2)
        self.entry_quantity = ttk.Entry(content, textvariable=self.var_quantity, width=15)
        self.entry_quantity.grid(row=2, column=1, sticky=tk.W, pady=2)

        ttk.Label(content, text="Péremption (JJ/MM/AAAA) :").grid(row=3, column=0, sticky=tk.W, pady=2)
        self.entry_expiration = ttk.Entry(content, textvariable=self.var_expiration, width=20)
        self.entry_expiration.grid(row=3, column=1, sticky=tk.W, pady=2)

        ttk.Label(content, text="Code-barres :").grid(row=4, column=0, sticky=tk.W, pady=2)
        self.entry_barcode = ttk.Entry(content, textvariable=self.var_barcode, width=40)
        self.entry_barcode.grid(row=4, column=1, sticky=tk.W, pady=2)

        ttk.Label(content, text="Catégorie :").grid(row=5, column=0, sticky=tk.W, pady=2)
        self.entry_category = ttk.Entry(content, textvariable=self.var_category, width=40)
        self.entry_category.grid(row=5, column=1, sticky=tk.W, pady=2)

        ttk.Label(content, text="Dosage :").grid(row=6, column=0, sticky=tk.W, pady=2)
        self.entry_dosage = ttk.Entry(content, textvariable=self.var_dosage, width=40)
        self.entry_dosage.grid(row=6, column=1, sticky=tk.W, pady=2)

        ttk.Label(content, text="Forme :").grid(row=7, column=0, sticky=tk.W, pady=2)
        self.entry_form = ttk.Entry(content, textvariable=self.var_form, width=40)
        self.entry_form.grid(row=7, column=1, sticky=tk.W, pady=2)

        ttk.Label(content, text="Condition de stockage :").grid(row=8, column=0, sticky=tk.W, pady=2)
        self.entry_storage = ttk.Entry(content, textvariable=self.var_storage, width=40)
        self.entry_storage.grid(row=8, column=1, sticky=tk.W, pady=2)

        ttk.Checkbutton(
            content,
            text="Ordonnance requise",
            variable=self.var_prescription,
        ).grid(row=9, column=1, sticky=tk.W, pady=2)

        ttk.Label(content, text="Note :").grid(row=10, column=0, sticky=tk.NW, pady=2)
        self.note_text = tk.Text(content, width=40, height=4)
        self.note_text.grid(row=10, column=1, sticky=tk.W, pady=2)
        if initial.get('note'):
            self.note_text.insert('1.0', str(initial['note']))

        button_frame = ttk.Frame(content)
        button_frame.grid(row=11, column=0, columnspan=2, pady=(10, 0))
        ttk.Button(button_frame, text="Valider", command=self.on_ok).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Annuler", command=self.on_cancel).pack(side=tk.LEFT, padx=5)

        self.bind('<Return>', lambda _event: self.on_ok())
        self.bind('<Escape>', lambda _event: self.on_cancel())
        self.entry_name.focus_set()

        self.grab_set()
        self.wait_window(self)

    def on_ok(self):
        name = self.var_name.get().strip()
        lot = self.var_lot.get().strip()
        quantity_raw = self.var_quantity.get().strip()
        expiration_raw = self.var_expiration.get().strip()
        barcode = self.var_barcode.get().strip() or None
        category = self.var_category.get().strip() or None
        dosage = self.var_dosage.get().strip() or None
        form = self.var_form.get().strip() or None
        storage = self.var_storage.get().strip() or None
        note_text = self.note_text.get('1.0', tk.END).strip()
        note = note_text or None

        if not name:
            messagebox.showerror("Erreur", "Le nom du médicament est requis.", parent=self)
            return
        if not lot:
            messagebox.showerror("Erreur", "Le numéro de lot est requis.", parent=self)
            return
        try:
            quantity = int(quantity_raw)
        except (TypeError, ValueError):
            messagebox.showerror("Erreur", "La quantité doit être un entier positif.", parent=self)
            return
        if quantity < 0:
            messagebox.showerror("Erreur", "La quantité doit être positive ou nulle.", parent=self)
            return

        expiration_value: Optional[str]
        if expiration_raw:
            try:
                expiration_value = parse_user_date(expiration_raw)
            except ValueError:
                messagebox.showerror(
                    "Erreur",
                    "Format de date invalide. Utilisez JJ/MM/AAAA.",
                    parent=self,
                )
                return
        else:
            expiration_value = None

        self.result = {
            "name": name,
            "lot_number": lot,
            "quantity": quantity,
            "expiration_date": expiration_value,
            "barcode": barcode,
            "category": category,
            "dosage": dosage,
            "form": form,
            "storage_condition": storage,
            "prescription_required": bool(self.var_prescription.get()),
            "note": note,
        }
        self.destroy()

    def on_cancel(self):
        self.result = None
        self.destroy()


class ColumnManagerDialog(tk.Toplevel):
    """Boîte de dialogue pour ajuster l'ordre et la visibilité des colonnes d'inventaire."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        columns: tuple[str, ...],
        order: list[str],
        hidden: set[str],
        column_labels: Optional[dict[str, str]] = None,
    ) -> None:
        super().__init__(master)
        self.title("Personnalisation des colonnes")
        self.transient(master)
        self.grab_set()
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)

        self.result: Optional[tuple[list[str], set[str]]] = None
        self.default_columns = list(columns)
        self.column_order = list(order)
        self.hidden_columns = set(hidden)
        self.column_labels = column_labels or {}

        main_frame = ttk.Frame(self, padding=10)
        main_frame.grid(row=0, column=0, sticky="nsew")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        ttk.Label(main_frame, text="Ordre d'affichage :").grid(
            row=0,
            column=0,
            columnspan=2,
            sticky=tk.W,
        )

        list_frame = ttk.Frame(main_frame)
        list_frame.grid(row=1, column=0, rowspan=4, sticky="nsew")
        main_frame.rowconfigure(1, weight=1)
        main_frame.columnconfigure(0, weight=1)

        self.listbox = tk.Listbox(
            list_frame,
            exportselection=False,
            height=max(7, len(self.column_order)),
        )
        self.listbox.grid(row=0, column=0, sticky="nsew")
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)

        palette = getattr(master, "current_palette", PALETTE)
        theme_mode = getattr(master, "_theme_mode", "dark")
        _apply_listbox_palette(self.listbox, palette, theme=theme_mode)

        scrollbar = ttk.Scrollbar(
            list_frame,
            orient=tk.VERTICAL,
            command=self.listbox.yview,
        )
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.listbox.configure(yscrollcommand=scrollbar.set)

        button_frame = ttk.Frame(main_frame)
        button_frame.grid(row=1, column=1, rowspan=4, sticky="n", padx=(10, 0))

        btn_up = ttk.Button(button_frame, text="Monter", command=self._move_up)
        btn_down = ttk.Button(button_frame, text="Descendre", command=self._move_down)
        self.toggle_button = ttk.Button(
            button_frame,
            text="Afficher/Masquer",
            command=self._toggle_selected,
        )
        btn_reset = ttk.Button(button_frame, text="Réinitialiser", command=self._reset_defaults)

        btn_up.grid(row=0, column=0, sticky="ew", pady=(0, 5))
        btn_down.grid(row=1, column=0, sticky="ew", pady=(0, 5))
        self.toggle_button.grid(row=2, column=0, sticky="ew", pady=(0, 5))
        btn_reset.grid(row=3, column=0, sticky="ew")

        action_frame = ttk.Frame(self, padding=(10, 0, 10, 10))
        action_frame.grid(row=1, column=0, sticky="e")

        btn_cancel = ttk.Button(action_frame, text="Annuler", command=self._on_cancel)
        btn_ok = ttk.Button(action_frame, text="Enregistrer", command=self._on_validate)
        btn_cancel.grid(row=0, column=0, padx=(0, 5))
        btn_ok.grid(row=0, column=1)

        self.listbox.bind('<<ListboxSelect>>', self._on_selection_changed)
        self.listbox.bind('<Double-Button-1>', lambda _event: self._toggle_selected())
        self.bind('<Return>', lambda _event: self._on_validate())
        self.bind('<Escape>', lambda _event: self._on_cancel())

        self._refresh_listbox()
        if self.column_order:
            self.listbox.selection_set(0)
            self._update_toggle_button()

        self.wait_visibility()
        self.focus_set()

    def _refresh_listbox(self) -> None:
        self.listbox.delete(0, tk.END)
        for col in self.column_order:
            marker = '✓' if col not in self.hidden_columns else '✗'
            label = self.column_labels.get(col, col)
            self.listbox.insert(tk.END, f"[{marker}] {label}")

    def _current_index(self) -> Optional[int]:
        selection = self.listbox.curselection()
        if not selection:
            return None
        return int(selection[0])

    def _move_up(self) -> None:
        idx = self._current_index()
        if idx is None or idx <= 0:
            return
        self.column_order[idx - 1], self.column_order[idx] = (
            self.column_order[idx],
            self.column_order[idx - 1],
        )
        self._refresh_listbox()
        self.listbox.selection_set(idx - 1)
        self._update_toggle_button()

    def _move_down(self) -> None:
        idx = self._current_index()
        if idx is None or idx >= len(self.column_order) - 1:
            return
        self.column_order[idx + 1], self.column_order[idx] = (
            self.column_order[idx],
            self.column_order[idx + 1],
        )
        self._refresh_listbox()
        self.listbox.selection_set(idx + 1)
        self._update_toggle_button()

    def _toggle_selected(self) -> None:
        idx = self._current_index()
        if idx is None:
            return
        column = self.column_order[idx]
        if column in self.hidden_columns:
            self.hidden_columns.remove(column)
        else:
            self.hidden_columns.add(column)
        self._refresh_listbox()
        self.listbox.selection_set(idx)
        self._update_toggle_button()

    def _reset_defaults(self) -> None:
        self.column_order = list(self.default_columns)
        self.hidden_columns.clear()
        self._refresh_listbox()
        if self.column_order:
            self.listbox.selection_clear(0, tk.END)
            self.listbox.selection_set(0)
        self._update_toggle_button()

    def _on_selection_changed(self, _event=None) -> None:
        self._update_toggle_button()

    def _update_toggle_button(self) -> None:
        idx = self._current_index()
        if idx is None:
            self.toggle_button.config(text="Afficher/Masquer", state=tk.DISABLED)
            return
        column = self.column_order[idx]
        label = self.column_labels.get(column, column)
        if column in self.hidden_columns:
            self.toggle_button.config(text=f"Afficher {label}", state=tk.NORMAL)
        else:
            self.toggle_button.config(text=f"Masquer {label}", state=tk.NORMAL)

    def _on_validate(self) -> None:
        visible_columns = [col for col in self.column_order if col not in self.hidden_columns]
        if not visible_columns:
            messagebox.showerror(
                "Colonnes",
                "Sélectionnez au moins une colonne à afficher.",
                parent=self,
            )
            return
        self.result = (list(self.column_order), set(self.hidden_columns))
        self.destroy()

    def _on_cancel(self) -> None:
        self.result = None
        self.destroy()

# ----------------------
# CLASSE PRINCIPALE DE L'APPLICATION
# ----------------------
class StockApp(tk.Tk):
    CLOTHING_SIZES = ["XXS", "XS", "S", "M", "L", "XL", "XXL"]
    SHOE_SIZES = [str(i) for i in range(30, 61)]

    @staticmethod
    def _parse_color(color: str) -> tuple[int, int, int]:
        color = color.lstrip("#")
        if len(color) != 6:
            raise ValueError(color)
        return tuple(int(color[i : i + 2], 16) for i in (0, 2, 4))

    @staticmethod
    def _compose_color(r: float, g: float, b: float) -> str:
        return "#%02x%02x%02x" % (
            max(0, min(255, int(round(r)))),
            max(0, min(255, int(round(g)))),
            max(0, min(255, int(round(b)))),
        )

    def _blend_colors(self, base: str, overlay: str, weight: float) -> str:
        try:
            r1, g1, b1 = self._parse_color(base)
            r2, g2, b2 = self._parse_color(overlay)
        except Exception:
            return overlay if overlay.startswith("#") else base
        w = max(0.0, min(1.0, weight))
        return self._compose_color(
            r1 * (1 - w) + r2 * w,
            g1 * (1 - w) + g2 * w,
            b1 * (1 - w) + b2 * w,
        )

    def _status_colors(self, key: str) -> tuple[str, str]:
        palette = getattr(self, "current_palette", PALETTE)
        base = palette.get(key, key if key.startswith("#") else "#2563eb")
        if not base.startswith("#"):
            base = "#2563eb"
        is_dark = getattr(self, "_theme_mode", "dark") == "dark"
        if is_dark:
            bg_base = palette.get("bg", "#0b1220")
            background = self._blend_colors(bg_base, base, 0.7)
            foreground = "#ffffff"
        else:
            background = self._blend_colors("#ffffff", base, 0.4)
            foreground = palette.get("fg", "#111827")
        return background, foreground

    def _apply_tree_tag_palette(self) -> None:
        if hasattr(self, "clothing_tree"):
            empty_bg, empty_fg = self._status_colors("danger")
            low_bg, low_fg = self._status_colors("warning")
            self.clothing_tree.tag_configure("clothing_empty", background=empty_bg, foreground=empty_fg)
            self.clothing_tree.tag_configure("clothing_low", background=low_bg, foreground=low_fg)
        if hasattr(self, "pharmacy_tree"):
            expired_bg, expired_fg = self._status_colors("danger")
            expiring_bg, expiring_fg = self._status_colors("warning")
            empty_bg, empty_fg = self._status_colors("muted")
            self.pharmacy_tree.tag_configure("pharmacy_expired", background=expired_bg, foreground=expired_fg)
            self.pharmacy_tree.tag_configure("pharmacy_expiring", background=expiring_bg, foreground=expiring_fg)
            self.pharmacy_tree.tag_configure("pharmacy_empty", background=empty_bg, foreground=empty_fg)
        inventory_tree = getattr(self, "tree", None)
        if isinstance(inventory_tree, ttk.Treeview):
            zero_bg, zero_fg = self._status_colors("danger")
            low_bg, low_fg = self._status_colors("warning")
            ok_bg, ok_fg = self._status_colors("success")
            unknown_bg, unknown_fg = self._status_colors("muted")
            inventory_tree.tag_configure("stock_zero", background=zero_bg, foreground=zero_fg)
            inventory_tree.tag_configure("stock_low", background=low_bg, foreground=low_fg)
            inventory_tree.tag_configure("stock_ok", background=ok_bg, foreground=ok_fg)
            inventory_tree.tag_configure("stock_unknown", background=unknown_bg, foreground=unknown_fg)

    def _get_status_icon(self, tags: Iterable[str]) -> Optional[PhotoImage]:
        warning_icon = self._status_icons.get("warning")
        if warning_icon is None:
            return None
        alert_tags = {
            "stock_low",
            "stock_zero",
            "clothing_low",
            "clothing_empty",
            "pharmacy_expiring",
            "pharmacy_expired",
            "pharmacy_empty",
        }
        if any(tag in alert_tags for tag in tags):
            return warning_icon
        return None

    def __init__(
        self,
        current_user,
        current_role,
        current_user_id,
        allowed_modules: Optional[dict[str, bool]] = None,
    ):
        startup_listener.record(
            "Construction de l'interface principale StockApp.",
            level=logging.DEBUG,
        )
        super().__init__()
        self._theme_mode = config.get('Settings', 'theme', fallback='dark')
        try:
            self._font_size = config.getint('Settings', 'font_size')
        except Exception:
            self._font_size = 10
        self.current_palette = apply_theme(self, self._theme_mode, font_size=self._font_size)
        warning_icon = make_icon("warning.png", size=18)
        self._status_icons: dict[str, Optional[PhotoImage]] = {"warning": warning_icon}
        self.current_user = current_user
        self.current_role = current_role
        self.current_user_id = current_user_id
        self.allowed_modules = allowed_modules or {}
        if self.current_role == 'admin':
            self.allowed_modules = {module: True for module in AVAILABLE_MODULES}
        elif not self.allowed_modules:
            self.allowed_modules = default_module_permissions_for_role(self.current_role)
        self.audit_logger = audit_logger

        self.title(f"Gestion Stock Pro - Connecté : {self.current_user} ({self.current_role})")
        self.geometry("950x600")
        self.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.style = ttk.Style(self)
        self.style.theme_use("clam")

        self.low_stock_threshold = config['Settings'].getint(
            'low_stock_threshold',
            fallback=DEFAULT_LOW_STOCK_THRESHOLD
        )

        self.pharmacy_allowed = bool(self.allowed_modules.get('pharmacy', False))
        self.clothing_allowed = bool(self.allowed_modules.get('clothing', False))

        self.pharmacy_enabled = self.pharmacy_allowed and ENABLE_PHARMACY_MODULE
        self.clothing_enabled = self.clothing_allowed and ENABLE_CLOTHING_MODULE

        self.create_menu()
        self.create_toolbar()
        self.create_statusbar()
        self.create_main_frames()
        self._apply_tree_tag_palette()
        startup_listener.record(
            "Menus et composants principaux créés.",
            level=logging.DEBUG,
        )

        try:
            startup_listener.record(
                "Initialisation de la base stock depuis StockApp.",
                level=logging.DEBUG,
            )
            init_stock_db(DB_PATH)
        except Exception as e:
            startup_listener.record(
                f"Échec d'initialisation de la base stock dans StockApp : {e}",
                level=logging.ERROR,
            )
            messagebox.showerror("Erreur BD", f"Impossible d'initialiser la base du stock : {e}")
            self.destroy()
            return

        self.alert_manager = AlertManager(self, threshold=self.low_stock_threshold)
        startup_listener.record("Gestionnaire d'alertes initialisé.", level=logging.DEBUG)

        if ENABLE_VOICE and SR_LIB_AVAILABLE:
            if microphone is None:
                init_recognizer()

    def on_closing(self):
        self.save_clothing_column_preferences()
        self.save_pharmacy_column_preferences()
        if hasattr(self, 'dashboard_job') and self.dashboard_job:
            try:
                self.after_cancel(self.dashboard_job)
            except Exception:
                pass
            self.dashboard_job = None
        pending_refresh = getattr(self, '_pending_dashboard_refresh', None)
        if pending_refresh:
            try:
                self.after_cancel(pending_refresh)
            except Exception:
                pass
            self._pending_dashboard_refresh = None
        if hasattr(self, 'alert_manager') and self.alert_manager:
            self.alert_manager.stop()
        global voice_active
        voice_active = False
        self.destroy()

    def log_user_action(self, message: str, *, level: int = logging.INFO) -> None:
        """Enregistre un événement utilisateur dans le journal d'audit."""

        if not message:
            return
        try:
            self.audit_logger.log(
                level,
                "[utilisateur=%s|role=%s] %s",
                self.current_user,
                self.current_role,
                message,
            )
        except Exception:  # pragma: no cover - journalisation défensive
            logger.debug("Impossible d'enregistrer l'action utilisateur : %s", message, exc_info=True)


    def create_menu(self):
        menubar = tk.Menu(self)

        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Déconnexion", command=self.logout)
        file_menu.add_command(label="Sauvegarder base", command=self.backup_database)
        file_menu.add_separator()
        file_menu.add_command(label="Quitter", command=self.on_closing)
        menubar.add_cascade(label="Fichier", menu=file_menu)

        settings_menu = tk.Menu(menubar, tearoff=0)
        settings_menu.add_command(label="Configuration générale", command=self.open_config_dialog)
        if self.current_role == 'admin' or self.clothing_allowed:
            settings_menu.add_command(label="Gérer Catégories", command=self.open_category_dialog)
        if self.clothing_allowed:
            settings_menu.add_command(
                label="Colonnes Habillement",
                command=self.open_clothing_column_manager,
                state=tk.NORMAL if self.clothing_enabled else tk.DISABLED,
            )
        if self.pharmacy_allowed:
            settings_menu.add_command(
                label="Colonnes Pharmacie",
                command=self.open_pharmacy_column_manager,
                state=tk.NORMAL if self.pharmacy_enabled else tk.DISABLED,
            )
        if self.current_role == 'admin':
            settings_menu.add_command(label="Gérer Utilisateurs", command=self.open_user_management)
        if ENABLE_VOICE and SR_LIB_AVAILABLE:
            settings_menu.add_separator()
            settings_menu.add_command(label="Configurer Micro", command=self.configure_microphone)
            settings_menu.add_separator()
            settings_menu.add_command(label="Aide Vocale", command=self.show_voice_help)
        else:
            settings_menu.add_separator()
            settings_menu.add_command(label="Aide Vocale", state='disabled')
        menubar.add_cascade(label="Paramètres", menu=settings_menu)

        scan_menu = tk.Menu(menubar, tearoff=0)
        scan_state = tk.NORMAL if (self.clothing_enabled or self.pharmacy_enabled) else tk.DISABLED
        scan_menu.add_command(label="Scan Caméra", command=self.scan_camera, state=scan_state)
        menubar.add_cascade(label="Scan", menu=scan_menu)

        module_menu = tk.Menu(menubar, tearoff=0)
        if self.current_role == 'admin' or self.clothing_allowed:
            module_menu.add_command(label="Fournisseurs", command=self.open_supplier_management)
            module_menu.add_command(label="Bons de commande", command=self.open_purchase_orders)
            module_menu.add_command(label="Dotations collaborateurs", command=self.open_collaborator_gear)
        if self.current_role == 'admin':
            module_menu.add_command(label="Approvals en attente", command=self.open_approval_queue)
        self.pharmacy_module_var = tk.BooleanVar(value=self.pharmacy_enabled if self.pharmacy_allowed else False)
        module_menu.add_checkbutton(
            label="Gestion Pharmacie",
            variable=self.pharmacy_module_var,
            command=self.on_toggle_pharmacy_module,
            state=tk.NORMAL if self.pharmacy_allowed else tk.DISABLED,
        )
        self.clothing_module_var = tk.BooleanVar(value=self.clothing_enabled if self.clothing_allowed else False)
        module_menu.add_checkbutton(
            label="Gestion Habillement",
            variable=self.clothing_module_var,
            command=self.on_toggle_clothing_module,
            state=tk.NORMAL if self.clothing_allowed else tk.DISABLED,
        )
        menubar.add_cascade(label="Modules", menu=module_menu)

        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="À propos", command=self.show_about)
        menubar.add_cascade(label="Aide", menu=help_menu)

        self.config(menu=menubar)

    def create_toolbar(self):
        bar = themed_toolbar(self)
        button_specs = [
            ("add", "Nouveau", "Primary.TButton", "plus.png", "Créer un nouvel article"),
            ("edit", "Modifier", "Info.TButton", "edit.png", "Modifier l'article sélectionné"),
            ("delete", "Supprimer", "Danger.TButton", "trash.png", "Supprimer l'article sélectionné"),
            ("stock_in", "Entrée", "Success.TButton", "download.png", "Enregistrer une entrée de stock"),
            ("stock_out", "Sortie", "Warning.TButton", "upload.png", "Enregistrer une sortie de stock"),
        ]
        scan_buttons = [
            ("scan", "Scan Caméra", "Secondary.TButton", "camera.png", "Scanner via la caméra"),
            ("barcode", "Scan Douchette", "Secondary.TButton", "barcode.png", "Scanner via une douchette"),
        ]
        report_buttons = [
            ("report_pdf", "Rapport PDF", "Primary.TButton", "file-pdf.png", "Générer un rapport PDF"),
            ("export", "Export CSV", "Info.TButton", "file-csv.png", "Exporter les données en CSV"),
            ("columns", "Colonnes", "Secondary.TButton", "settings.png", "Configurer les colonnes"),
        ]
        voice_buttons = [
            ("listen", "Écoute", "Secondary.TButton", "voice.png", "Activer la reconnaissance vocale"),
            ("stop_listen", "Stop", "Secondary.TButton", "voice-off.png", "Arrêter la reconnaissance vocale"),
        ]

        self.toolbar_buttons: dict[str, ttk.Button] = {}
        self.toolbar_icons: dict[str, PhotoImage] = {}

        def _add_buttons(button_list):
            for action, label, style_name, icon_name, tooltip in button_list:
                icon = make_icon(icon_name)
                if icon is not None:
                    self.toolbar_icons[action] = icon
                btn = themed_button(
                    bar,
                    text=label,
                    style=style_name,
                    command=lambda action_name=action: self._invoke_toolbar_action(action_name),
                    icon=self.toolbar_icons.get(action),
                )
                btn.configure(state=tk.DISABLED)
                btn.pack(side=tk.LEFT, padx=4, pady=2)
                self.toolbar_buttons[action] = btn
                self._add_tooltip(btn, tooltip)

        _add_buttons(button_specs)
        ttk.Separator(bar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6)
        _add_buttons(scan_buttons)
        ttk.Separator(bar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6)
        _add_buttons(report_buttons)
        ttk.Separator(bar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6)
        _add_buttons(voice_buttons)

        self.toolbar = bar
        self._current_toolbar_handlers: dict[str, Callable[[], None]] = {}

    def _invoke_toolbar_action(self, action: str) -> None:
        handler = self._current_toolbar_handlers.get(action)
        if handler is None:
            return
        handler()

    def _add_tooltip(self, widget: tk.Widget, text: str) -> None:
        if not text:
            return

        state: dict[str, Optional[str | tk.Toplevel]] = {"job": None, "tip": None}

        def _cancel(_event=None) -> None:
            job = state.get("job")
            if job is not None:
                try:
                    self.after_cancel(job)
                except Exception:
                    pass
                state["job"] = None
            tip = state.get("tip")
            if isinstance(tip, tk.Toplevel) and tip.winfo_exists():
                tip.destroy()
            state["tip"] = None

        def _show_tooltip() -> None:
            _cancel()
            try:
                x = widget.winfo_rootx() + widget.winfo_width() // 2
                y = widget.winfo_rooty() + widget.winfo_height() + 10
            except Exception:
                return
            palette = getattr(self, "current_palette", PALETTE)
            tip = tk.Toplevel(widget)
            tip.wm_overrideredirect(True)
            tip.wm_geometry(f"+{x}+{y}")
            tip.configure(background=palette.get("surface", "#111827"))
            label = ttk.Label(
                tip,
                text=text,
                padding=(10, 4),
                background=palette.get("surface", "#111827"),
                foreground=palette.get("fg", "#ffffff"),
            )
            label.pack()
            state["tip"] = tip

        def _schedule(_event=None) -> None:
            _cancel()
            state["job"] = self.after(400, _show_tooltip)

        widget.bind("<Enter>", _schedule, add=True)
        widget.bind("<Leave>", _cancel, add=True)
        widget.bind("<ButtonPress>", _cancel, add=True)

    def _on_notebook_tab_changed(self, _event=None) -> None:
        self.update_toolbar_state()

    def _determine_active_mode(self) -> str:
        if not hasattr(self, "notebook"):
            return "other"
        try:
            current_tab = self.notebook.select()
        except tk.TclError:
            return "other"
        clothing_frame = getattr(self, "clothing_frame", None)
        pharmacy_frame = getattr(self, "pharmacy_frame", None)
        if clothing_frame is not None and current_tab and str(clothing_frame) == current_tab:
            return "clothing"
        if pharmacy_frame is not None and current_tab and str(pharmacy_frame) == current_tab:
            return "pharmacy"
        return "other"

    def update_toolbar_state(self) -> None:
        if not hasattr(self, "toolbar_buttons"):
            return
        if not hasattr(self, "notebook"):
            return

        mode = self._determine_active_mode()

        handlers: dict[str, Callable[[], None]] = {}
        if mode == "clothing":
            handlers = {
                "add": self.open_clothing_register_dialog,
                "edit": self.open_clothing_edit_dialog,
                "delete": self.delete_selected_clothing_item,
                "stock_in": self.adjust_selected_clothing_item,
                "stock_out": self.adjust_selected_clothing_item,
                "scan": self.scan_camera,
                "barcode": self.generate_barcode_dialog,
                "export": self.export_clothing_inventory,
                "columns": self.open_clothing_column_manager,
                "report_pdf": self.generate_pdf_report,
            }
            if ENABLE_VOICE and SR_LIB_AVAILABLE:
                handlers["listen"] = start_voice_listening
                handlers["stop_listen"] = stop_voice_listening
        elif mode == "pharmacy":
            handlers = {
                "add": self.open_pharmacy_register_dialog,
                "edit": self.open_pharmacy_edit_dialog,
                "delete": self.delete_selected_pharmacy_batch,
                "stock_in": self.adjust_selected_pharmacy_batch,
                "stock_out": self.adjust_selected_pharmacy_batch,
                "scan": self.scan_camera,
                "barcode": self.generate_barcode_dialog,
                "columns": self.open_pharmacy_column_manager,
                "report_pdf": self.generate_pdf_report,
            }
            if ENABLE_VOICE and SR_LIB_AVAILABLE:
                handlers["listen"] = start_voice_listening
                handlers["stop_listen"] = stop_voice_listening
        else:
            handlers = {"report_pdf": self.generate_pdf_report}
            if ENABLE_VOICE and SR_LIB_AVAILABLE:
                handlers["listen"] = start_voice_listening
                handlers["stop_listen"] = stop_voice_listening

        available_handlers: dict[str, Callable[[], None]] = {}
        for action, button in self.toolbar_buttons.items():
            handler = handlers.get(action)
            state = tk.DISABLED
            if handler is not None:
                if action in {"listen", "stop_listen"} and not (ENABLE_VOICE and SR_LIB_AVAILABLE):
                    handler = None
                else:
                    state = tk.NORMAL
            if handler is not None:
                available_handlers[action] = handler
            button.config(state=state)

        self._current_toolbar_handlers = available_handlers


    def create_statusbar(self):
        self.status = tk.StringVar()
        self.status.set("Prêt")
        status_bar = ttk.Label(self, textvariable=self.status, style="Status.TLabel", anchor=tk.W)
        status_bar.pack(side=tk.BOTTOM, fill=tk.X)

    def create_main_frames(self):
        main_frame = ttk.Frame(self)
        main_frame.pack(fill=tk.BOTH, expand=True)

        self.notebook = ttk.Notebook(main_frame)
        self.notebook.pack(fill=tk.BOTH, expand=True)

        self.dashboard_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.dashboard_frame, text="Tableau de bord")

        self.clothing_frame: Optional[ttk.Frame] = None
        if self.clothing_enabled:
            self.add_clothing_tab()

        self.pharmacy_frame: Optional[ttk.Frame] = None
        if self.pharmacy_enabled:
            self.add_pharmacy_tab()

        self.notebook.bind("<<NotebookTabChanged>>", self._on_notebook_tab_changed)
        self.update_toolbar_state()

        self.create_dashboard_tab()

    def add_clothing_tab(self) -> None:
        if getattr(self, "clothing_frame", None) is not None:
            return
        self.clothing_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.clothing_frame, text="Habillement")
        self.create_clothing_tab()
        self.update_toolbar_state()

    def remove_clothing_tab(self) -> None:
        frame = getattr(self, "clothing_frame", None)
        if frame is None:
            return
        job = getattr(self, "_clothing_search_job", None)
        if job:
            try:
                self.after_cancel(job)
            except Exception:
                pass
        try:
            self.notebook.forget(frame)
        except tk.TclError:
            pass
        frame.destroy()
        self.clothing_frame = None
        for attr in (
            "clothing_summary_vars",
            "clothing_tree",
            "clothing_item_cache",
            "clothing_search_var",
            "clothing_include_zero_var",
        ):
            if hasattr(self, attr):
                delattr(self, attr)
        self._clothing_search_job = None
        self.update_toolbar_state()

    def create_clothing_tab(self) -> None:
        frame = getattr(self, "clothing_frame", None)
        if frame is None:
            return
        for child in frame.winfo_children():
            child.destroy()
        if clothing_inventory_manager is None:
            ttk.Label(
                frame,
                text="Module habillement indisponible : vérifiez l'installation.",
            ).pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
            return
        try:
            ensure_clothing_inventory_schema()
        except Exception as exc:
            ttk.Label(
                frame,
                text=f"Impossible d'initialiser l'habillement : {exc}",
            ).pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
            return

        self.clothing_summary_vars = {
            'total_items': tk.StringVar(value='0'),
            'total_quantity': tk.StringVar(value='0'),
            'depleted': tk.StringVar(value='0'),
        }

        summary_frame = ttk.LabelFrame(frame, text="Résumé", padding=10)
        summary_frame.pack(fill=tk.X, padx=10, pady=5)
        summary_labels = [
            ("Articles référencés", 'total_items'),
            ("Quantité totale", 'total_quantity'),
            ("Articles épuisés", 'depleted'),
        ]
        for col, (label, key) in enumerate(summary_labels):
            ttk.Label(summary_frame, text=f"{label} :").grid(row=0, column=col * 2, sticky=tk.W, padx=5)
            ttk.Label(summary_frame, textvariable=self.clothing_summary_vars[key]).grid(
                row=0,
                column=col * 2 + 1,
                sticky=tk.W,
                padx=2,
            )

        control_frame = ttk.Frame(frame)
        control_frame.pack(fill=tk.X, padx=10, pady=(0, 5))
        ttk.Label(control_frame, text="Rechercher :").grid(row=0, column=0, padx=5, pady=2, sticky=tk.W)
        self.clothing_search_var = tk.StringVar()
        search_entry = ttk.Entry(control_frame, textvariable=self.clothing_search_var, width=30)
        search_entry.grid(row=0, column=1, padx=5, pady=2, sticky=tk.W)
        search_entry.bind("<Return>", lambda _event: self.refresh_clothing_items())

        self.clothing_include_zero_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            control_frame,
            text="Inclure quantités nulles",
            variable=self.clothing_include_zero_var,
            command=self.refresh_clothing_items,
        ).grid(row=0, column=2, padx=10, pady=2, sticky=tk.W)

        ttk.Button(
            control_frame,
            text="Ajouter article",
            command=self.open_clothing_register_dialog,
        ).grid(row=0, column=3, padx=5, pady=2, sticky=tk.W)
        ttk.Button(
            control_frame,
            text="Modifier",
            command=self.open_clothing_edit_dialog,
        ).grid(row=0, column=4, padx=5, pady=2, sticky=tk.W)
        ttk.Button(
            control_frame,
            text="Supprimer",
            command=self.delete_selected_clothing_item,
        ).grid(row=0, column=5, padx=5, pady=2, sticky=tk.W)
        ttk.Button(
            control_frame,
            text="Ajuster quantité",
            command=self.adjust_selected_clothing_item,
        ).grid(row=0, column=6, padx=5, pady=2, sticky=tk.W)
        ttk.Button(
            control_frame,
            text="Exporter CSV",
            command=self.export_clothing_inventory,
        ).grid(row=0, column=7, padx=5, pady=2, sticky=tk.W)

        control_frame.columnconfigure(8, weight=1)

        tree_container = ttk.Frame(frame)
        tree_container.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))
        columns = (
            "name",
            "barcode",
            "size",
            "category",
            "quantity",
            "reorder_point",
            "unit_cost",
            "supplier",
            "updated_at",
        )
        self.clothing_tree = ttk.Treeview(
            tree_container,
            columns=columns,
            show='tree headings',
            selectmode='browse',
        )
        headings = {
            'name': ("Article", tk.W, 180),
            'barcode': ("Code-Barres", tk.W, 140),
            'size': ("Taille", tk.CENTER, 80),
            'category': ("Catégorie", tk.W, 140),
            'quantity': ("Quantité", tk.CENTER, 90),
            'reorder_point': ("Seuil", tk.CENTER, 90),
            'unit_cost': ("Coût (€)", tk.CENTER, 90),
            'supplier': ("Fournisseur", tk.W, 160),
            'updated_at': ("Dernière MAJ", tk.CENTER, 140),
        }
        for key in columns:
            text, anchor, width = headings[key]
            self.clothing_tree.heading(key, text=text)
            self.clothing_tree.column(key, anchor=anchor, width=width)
        self.clothing_tree.heading('#0', text='', anchor=tk.CENTER)
        self.clothing_tree.column('#0', width=32, stretch=False, anchor=tk.CENTER)
        vsb = ttk.Scrollbar(tree_container, orient=tk.VERTICAL, command=self.clothing_tree.yview)
        hsb = ttk.Scrollbar(tree_container, orient=tk.HORIZONTAL, command=self.clothing_tree.xview)
        self.clothing_tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.clothing_tree.grid(row=0, column=0, sticky='nsew')
        vsb.grid(row=0, column=1, sticky='ns')
        hsb.grid(row=1, column=0, sticky='ew')
        tree_container.columnconfigure(0, weight=1)
        tree_container.rowconfigure(0, weight=1)

        self._apply_tree_tag_palette()
        self.clothing_tree.bind("<Double-1>", self.on_clothing_item_double_click)

        self.clothing_item_cache: dict[str, ClothingItem] = {}
        self._clothing_search_job: Optional[str] = None
        self.clothing_search_var.trace_add('write', self._on_clothing_search_change)

        self.load_clothing_column_preferences()
        self.refresh_clothing_summary()
        self.refresh_clothing_items()
        self.update_toolbar_state()

    def _on_clothing_search_change(self, *_args) -> None:
        job = getattr(self, "_clothing_search_job", None)
        if job:
            try:
                self.after_cancel(job)
            except Exception:
                pass
        self._clothing_search_job = self.after(300, self.refresh_clothing_items)

    def refresh_clothing_items(self) -> None:
        if not hasattr(self, 'clothing_tree'):
            return
        if clothing_inventory_manager is None:
            return
        try:
            items = list_clothing_items(
                search=self.clothing_search_var.get(),
                include_zero=self.clothing_include_zero_var.get(),
            )
        except Exception as exc:
            messagebox.showerror(
                "Erreur",
                f"Impossible de charger l'habillement : {exc}",
                parent=self,
            )
            return
        self.clothing_tree.delete(*self.clothing_tree.get_children())
        self.clothing_item_cache.clear()
        for item in items:
            updated = format_display_datetime(item.updated_at)
            values = (
                item.name,
                item.barcode or '—',
                item.size or '—',
                item.category or '—',
                item.quantity,
                item.reorder_point if item.reorder_point is not None else '—',
                f"{item.unit_cost:.2f}" if item.unit_cost is not None else '—',
                item.preferred_supplier_name or '—',
                updated,
            )
            tags = []
            threshold = item.reorder_point if item.reorder_point is not None else self.low_stock_threshold
            try:
                threshold_val = int(threshold)
            except (TypeError, ValueError):
                threshold_val = self.low_stock_threshold
            if item.quantity <= 0:
                tags.append('clothing_empty')
            elif item.quantity <= threshold_val:
                tags.append('clothing_low')

            insert_kwargs: dict[str, Any] = {
                'parent': '',
                'index': 'end',
                'iid': str(item.id),
                'values': values,
                'text': '',
            }

            if tags:
                insert_kwargs['tags'] = tuple(tags)
            icon = self._get_status_icon(tags)
            if icon is not None:
                insert_kwargs['image'] = icon

            self.clothing_tree.insert(**insert_kwargs)
            self.clothing_item_cache[str(item.id)] = item
        if items:
            self.clothing_tree.yview_moveto(0)

    def refresh_clothing_summary(self) -> None:
        if not hasattr(self, 'clothing_summary_vars'):
            return
        if clothing_inventory_manager is None:
            for var in self.clothing_summary_vars.values():
                var.set('—')
            return
        try:
            summary = summarize_clothing_stock()
        except Exception as exc:
            messagebox.showerror(
                "Erreur",
                f"Impossible de récupérer le résumé habillement : {exc}",
                parent=self,
            )
            for var in self.clothing_summary_vars.values():
                var.set('—')
            return
        self.clothing_summary_vars['total_items'].set(str(summary.get('total_items', 0)))
        self.clothing_summary_vars['total_quantity'].set(str(summary.get('total_quantity', 0)))
        self.clothing_summary_vars['depleted'].set(str(summary.get('depleted', 0)))

    def open_clothing_register_dialog(self) -> None:
        if clothing_inventory_manager is None:
            messagebox.showerror(
                "Module indisponible",
                "La gestion habillement n'est pas disponible sur cette installation.",
                parent=self,
            )
            return
        dialog = ClothingItemDialog(
            self,
            "Nouvel article habillement",
            sizes=self.CLOTHING_SIZES,
        )
        if not dialog.result:
            return
        try:
            register_clothing_item(operator=self.current_user, **dialog.result)
        except Exception as exc:
            messagebox.showerror(
                "Erreur",
                f"Impossible d'enregistrer l'article : {exc}",
                parent=self,
            )
            return
        messagebox.showinfo(
            "Succès",
            "L'article d'habillement a été enregistré avec succès.",
            parent=self,
        )
        self.refresh_clothing_summary()
        self.refresh_clothing_items()

    def open_clothing_edit_dialog(self) -> None:
        if clothing_inventory_manager is None or not hasattr(self, 'clothing_tree'):
            return
        selection = self.clothing_tree.selection()
        if not selection:
            messagebox.showinfo(
                "Sélection requise",
                "Sélectionnez un article à modifier.",
                parent=self,
            )
            return
        item = self.clothing_item_cache.get(selection[0])
        if item is None:
            return
        dialog = ClothingItemDialog(
            self,
            "Modifier article habillement",
            sizes=self.CLOTHING_SIZES,
            initial={
                'name': item.name,
                'barcode': item.barcode,
                'category': item.category,
                'size': item.size,
                'quantity': item.quantity,
                'unit_cost': item.unit_cost,
                'reorder_point': item.reorder_point,
                'preferred_supplier_id': item.preferred_supplier_id,
            },
        )
        if not dialog.result:
            return
        try:
            updated = update_clothing_item(
                item.id,
                operator=self.current_user,
                **dialog.result,
            )
        except Exception as exc:
            messagebox.showerror(
                "Erreur",
                f"Impossible de modifier l'article : {exc}",
                parent=self,
            )
            return
        if updated is None:
            messagebox.showerror(
                "Introuvable",
                "L'article sélectionné est introuvable.",
                parent=self,
            )
            return
        messagebox.showinfo(
            "Succès",
            "L'article a été mis à jour avec succès.",
            parent=self,
        )
        self.refresh_clothing_summary()
        self.refresh_clothing_items()

    def delete_selected_clothing_item(self) -> None:
        if clothing_inventory_manager is None or not hasattr(self, 'clothing_tree'):
            return
        selection = self.clothing_tree.selection()
        if not selection:
            messagebox.showinfo(
                "Sélection requise",
                "Sélectionnez un article à supprimer.",
                parent=self,
            )
            return
        item = self.clothing_item_cache.get(selection[0])
        if item is None:
            return
        if not messagebox.askyesno(
            "Confirmation",
            f"Supprimer l'article '{item.name}' ?",
            parent=self,
        ):
            return
        try:
            success = delete_clothing_item(item.id)
        except Exception as exc:
            messagebox.showerror(
                "Erreur",
                f"Impossible de supprimer l'article : {exc}",
                parent=self,
            )
            return
        if not success:
            messagebox.showerror(
                "Introuvable",
                "L'article sélectionné est introuvable.",
                parent=self,
            )
            return
        messagebox.showinfo(
            "Article supprimé",
            "L'article a été supprimé.",
            parent=self,
        )
        self.refresh_clothing_summary()
        self.refresh_clothing_items()

    def adjust_selected_clothing_item(self) -> None:
        if clothing_inventory_manager is None or not hasattr(self, 'clothing_tree'):
            return
        selection = self.clothing_tree.selection()
        if not selection:
            messagebox.showinfo(
                "Sélection requise",
                "Sélectionnez un article à ajuster.",
                parent=self,
            )
            return
        item = self.clothing_item_cache.get(selection[0])
        if item is None:
            return
        delta_str = simpledialog.askstring(
            "Ajuster quantité",
            "Entrez la variation de quantité (ex: 5 ou -3) :",
            parent=self,
        )
        if delta_str is None:
            return
        try:
            delta = int(delta_str.strip())
        except (TypeError, ValueError):
            messagebox.showerror("Erreur", "Veuillez saisir un entier valide.", parent=self)
            return
        note = simpledialog.askstring(
            "Commentaire",
            "Ajouter un commentaire (optionnel) :",
            parent=self,
        )
        try:
            result = adjust_clothing_item_quantity(
                item.id,
                delta,
                operator=self.current_user,
                note=note or None,
            )
        except ValueError as exc:
            messagebox.showerror("Quantité invalide", str(exc), parent=self)
            return
        except Exception as exc:
            messagebox.showerror(
                "Erreur",
                f"Impossible d'ajuster l'article : {exc}",
                parent=self,
            )
            return
        if not result:
            messagebox.showerror(
                "Introuvable",
                "L'article sélectionné est introuvable.",
                parent=self,
            )
            return
        messagebox.showinfo(
            "Quantité mise à jour",
            f"Nouvelle quantité : {result.quantity}",
            parent=self,
        )
        self.refresh_clothing_summary()
        self.refresh_clothing_items()

    def export_clothing_inventory(self) -> None:
        if not hasattr(self, 'clothing_item_cache'):
            return
        file_path = filedialog.asksaveasfilename(
            title="Exporter l'habillement",
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv"), ("Tous les fichiers", "*.*")],
        )
        if not file_path:
            return
        rows = []
        for item in self.clothing_item_cache.values():
            rows.append(
                (
                    item.name,
                    item.barcode or '',
                    item.size or '',
                    item.category or '',
                    item.quantity,
                    item.reorder_point if item.reorder_point is not None else '',
                    f"{item.unit_cost:.2f}" if item.unit_cost is not None else '',
                    item.preferred_supplier_name or '',
                    format_display_datetime(item.updated_at),
                    item.operator or '',
                )
            )
        headers = (
            "Article",
            "Code-Barres",
            "Taille",
            "Catégorie",
            "Quantité",
            "Seuil",
            "Coût unitaire",
            "Fournisseur",
            "Dernière mise à jour",
            "Dernier opérateur",
        )
        try:
            export_rows_to_csv(file_path, headers, rows)
        except Exception as exc:
            messagebox.showerror(
                "Erreur",
                f"Impossible d'exporter les données : {exc}",
                parent=self,
            )
            return
        messagebox.showinfo(
            "Export terminé",
            f"Export réalisé avec succès : {file_path}",
            parent=self,
        )

    def on_clothing_item_double_click(self, _event=None) -> None:
        if not hasattr(self, 'clothing_tree'):
            return
        selection = self.clothing_tree.selection()
        if not selection:
            return
        item = self.clothing_item_cache.get(selection[0])
        if item is None:
            return
        details = [
            f"Article : {item.name}",
            f"Code-Barres : {item.barcode or '—'}",
            f"Catégorie : {item.category or '—'}",
            f"Taille : {item.size or '—'}",
            f"Quantité : {item.quantity}",
            f"Seuil : {item.reorder_point if item.reorder_point is not None else '—'}",
            f"Coût unitaire : {item.unit_cost:.2f} €" if item.unit_cost is not None else "Coût unitaire : —",
            f"Fournisseur : {item.preferred_supplier_name or '—'}",
            f"Dernière mise à jour : {format_display_datetime(item.updated_at)}",
            f"Dernier opérateur : {item.operator or '—'}",
        ]
        messagebox.showinfo(
            "Détails habillement",
            "\n".join(details),
            parent=self,
        )

    def add_pharmacy_tab(self) -> None:
        if getattr(self, "pharmacy_frame", None) is not None:
            return
        self.pharmacy_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.pharmacy_frame, text="Pharmacie")
        self.create_pharmacy_tab()
        self.update_toolbar_state()

    def remove_pharmacy_tab(self) -> None:
        frame = getattr(self, "pharmacy_frame", None)
        if frame is None:
            return
        job = getattr(self, "_pharmacy_search_job", None)
        if job:
            try:
                self.after_cancel(job)
            except Exception:
                pass
        try:
            self.notebook.forget(frame)
        except tk.TclError:
            pass
        frame.destroy()
        self.pharmacy_frame = None
        for attr in (
            "pharmacy_summary_vars",
            "pharmacy_tree",
            "pharmacy_batch_cache",
            "pharmacy_search_var",
            "pharmacy_include_zero_var",
        ):
            if hasattr(self, attr):
                delattr(self, attr)
        self._pharmacy_search_job = None
        self.update_toolbar_state()

    def on_toggle_pharmacy_module(self) -> None:
        if not self.pharmacy_allowed:
            self.pharmacy_module_var.set(False)
            messagebox.showerror(
                "Accès refusé",
                "Votre profil n'autorise pas l'accès à ce module.",
            )
            return
        enabled = bool(self.pharmacy_module_var.get())
        if enabled == self.pharmacy_enabled:
            return
        self.pharmacy_enabled = enabled
        if enabled:
            self.add_pharmacy_tab()
        else:
            self.remove_pharmacy_tab()
        config['Settings']['enable_pharmacy_module'] = 'true' if enabled else 'false'
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            config.write(f)

    def on_toggle_clothing_module(self) -> None:
        if not self.clothing_allowed:
            self.clothing_module_var.set(False)
            messagebox.showerror(
                "Accès refusé",
                "Votre profil n'autorise pas l'accès à ce module.",
            )
            return
        enabled = bool(self.clothing_module_var.get())
        if enabled == self.clothing_enabled:
            return
        self.clothing_enabled = enabled
        if enabled:
            self.add_clothing_tab()
        else:
            self.remove_clothing_tab()
        config['Settings']['enable_clothing_module'] = 'true' if enabled else 'false'
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            config.write(f)

    def load_clothing_column_preferences(self) -> None:
        if 'ClothingColumns' not in config:
            config['ClothingColumns'] = {
                'order': ','.join(CLOTHING_COLUMN_KEYS),
                'hidden': '',
            }
        _normalize_columns_section(config['ClothingColumns'], CLOTHING_COLUMN_KEYS)
        section = config['ClothingColumns']
        order_values = [col.strip() for col in section.get('order', '').split(',') if col.strip()]
        self.clothing_column_order = [
            col for col in order_values if col in CLOTHING_COLUMN_KEYS
        ]
        for col in CLOTHING_COLUMN_KEYS:
            if col not in self.clothing_column_order:
                self.clothing_column_order.append(col)
        hidden_values = [
            col.strip() for col in section.get('hidden', '').split(',') if col.strip()
        ]
        self.clothing_hidden_columns = {
            col for col in hidden_values if col in CLOTHING_COLUMN_KEYS
        }
        self._apply_clothing_column_preferences()

    def _apply_clothing_column_preferences(self) -> None:
        tree = getattr(self, 'clothing_tree', None)
        if tree is None:
            return
        display_columns = [
            col for col in self.clothing_column_order if col not in self.clothing_hidden_columns
        ]
        if not display_columns:
            self.clothing_hidden_columns.clear()
            display_columns = list(self.clothing_column_order)
        valid_display = [col for col in display_columns if col in CLOTHING_COLUMN_KEYS]
        if not valid_display:
            valid_display = list(CLOTHING_COLUMN_KEYS)
        tree.configure(displaycolumns=valid_display)

    def save_clothing_column_preferences(self) -> None:
        if not hasattr(self, 'clothing_column_order'):
            return
        if 'ClothingColumns' not in config:
            config['ClothingColumns'] = {}
        config['ClothingColumns']['order'] = ','.join(self.clothing_column_order)
        hidden_order = [
            col for col in self.clothing_column_order if col in self.clothing_hidden_columns
        ]
        for col in CLOTHING_COLUMN_KEYS:
            if col in self.clothing_hidden_columns and col not in hidden_order:
                hidden_order.append(col)
        config['ClothingColumns']['hidden'] = ','.join(hidden_order)
        _normalize_columns_section(config['ClothingColumns'], CLOTHING_COLUMN_KEYS)
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            config.write(f)

    def open_clothing_column_manager(self) -> None:
        tree = getattr(self, 'clothing_tree', None)
        if tree is None:
            messagebox.showinfo(
                "Colonnes Habillement",
                "Le tableau d'habillement n'est pas disponible pour le moment.",
                parent=self,
            )
            return
        dialog = ColumnManagerDialog(
            self,
            columns=CLOTHING_COLUMN_KEYS,
            order=list(getattr(self, 'clothing_column_order', CLOTHING_COLUMN_KEYS)),
            hidden=set(getattr(self, 'clothing_hidden_columns', set())),
            column_labels=CLOTHING_COLUMN_LABELS,
        )
        self.wait_window(dialog)
        if dialog.result:
            order, hidden = dialog.result
            normalized_order = [col for col in order if col in CLOTHING_COLUMN_KEYS]
            for col in CLOTHING_COLUMN_KEYS:
                if col not in normalized_order:
                    normalized_order.append(col)
            self.clothing_column_order = normalized_order
            self.clothing_hidden_columns = {
                col for col in hidden if col in CLOTHING_COLUMN_KEYS
            }
            self._apply_clothing_column_preferences()
            self.save_clothing_column_preferences()

    def load_pharmacy_column_preferences(self) -> None:
        if 'PharmacyColumns' not in config:
            config['PharmacyColumns'] = {
                'order': ','.join(PHARMACY_COLUMN_KEYS),
                'hidden': '',
            }
        _normalize_columns_section(config['PharmacyColumns'], PHARMACY_COLUMN_KEYS)
        section = config['PharmacyColumns']
        order_values = [col.strip() for col in section.get('order', '').split(',') if col.strip()]
        self.pharmacy_column_order = [
            col for col in order_values if col in PHARMACY_COLUMN_KEYS
        ]
        for col in PHARMACY_COLUMN_KEYS:
            if col not in self.pharmacy_column_order:
                self.pharmacy_column_order.append(col)
        hidden_values = [
            col.strip() for col in section.get('hidden', '').split(',') if col.strip()
        ]
        self.pharmacy_hidden_columns = {
            col for col in hidden_values if col in PHARMACY_COLUMN_KEYS
        }
        self._apply_pharmacy_column_preferences()

    def _apply_pharmacy_column_preferences(self) -> None:
        tree = getattr(self, 'pharmacy_tree', None)
        if tree is None:
            return
        display_columns = [
            col for col in self.pharmacy_column_order if col not in self.pharmacy_hidden_columns
        ]
        if not display_columns:
            self.pharmacy_hidden_columns.clear()
            display_columns = list(self.pharmacy_column_order)
        valid_display = [col for col in display_columns if col in PHARMACY_COLUMN_KEYS]
        if not valid_display:
            valid_display = list(PHARMACY_COLUMN_KEYS)
        tree.configure(displaycolumns=valid_display)

    def save_pharmacy_column_preferences(self) -> None:
        if not hasattr(self, 'pharmacy_column_order'):
            return
        if 'PharmacyColumns' not in config:
            config['PharmacyColumns'] = {}
        config['PharmacyColumns']['order'] = ','.join(self.pharmacy_column_order)
        hidden_order = [
            col for col in self.pharmacy_column_order if col in self.pharmacy_hidden_columns
        ]
        for col in PHARMACY_COLUMN_KEYS:
            if col in self.pharmacy_hidden_columns and col not in hidden_order:
                hidden_order.append(col)
        config['PharmacyColumns']['hidden'] = ','.join(hidden_order)
        _normalize_columns_section(config['PharmacyColumns'], PHARMACY_COLUMN_KEYS)
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            config.write(f)

    def open_pharmacy_column_manager(self) -> None:
        tree = getattr(self, 'pharmacy_tree', None)
        if tree is None:
            messagebox.showinfo(
                "Colonnes Pharmacie",
                "Le tableau pharmacie n'est pas disponible pour le moment.",
                parent=self,
            )
            return
        dialog = ColumnManagerDialog(
            self,
            columns=PHARMACY_COLUMN_KEYS,
            order=list(getattr(self, 'pharmacy_column_order', PHARMACY_COLUMN_KEYS)),
            hidden=set(getattr(self, 'pharmacy_hidden_columns', set())),
            column_labels=PHARMACY_COLUMN_LABELS,
        )
        self.wait_window(dialog)
        if dialog.result:
            order, hidden = dialog.result
            normalized_order = [col for col in order if col in PHARMACY_COLUMN_KEYS]
            for col in PHARMACY_COLUMN_KEYS:
                if col not in normalized_order:
                    normalized_order.append(col)
            self.pharmacy_column_order = normalized_order
            self.pharmacy_hidden_columns = {
                col for col in hidden if col in PHARMACY_COLUMN_KEYS
            }
            self._apply_pharmacy_column_preferences()
            self.save_pharmacy_column_preferences()

    def open_column_manager(self) -> None:
        mode = self._determine_active_mode()
        if mode == "clothing":
            self.open_clothing_column_manager()
        elif mode == "pharmacy":
            self.open_pharmacy_column_manager()
        else:
            messagebox.showinfo(
                "Colonnes",
                "Sélectionnez l'onglet Habillement ou Pharmacie pour personnaliser les colonnes.",
                parent=self,
            )

    def create_dashboard_tab(self):
        self.dashboard_vars = {
            'total_items': tk.StringVar(value='0'),
            'total_quantity': tk.StringVar(value='0'),
            'stock_value': tk.StringVar(value='0.00 €'),
            'low_stock_count': tk.StringVar(value='0'),
        }

        scope_options: list[str] = []
        if self.pharmacy_allowed and pharmacy_inventory_manager is not None:
            scope_options.append("pharmacy")
        if self.clothing_allowed and clothing_inventory_manager is not None:
            scope_options.append("clothing")
        if not scope_options:
            scope_options.append("general")

        scope_labels = {
            "general": "Inventaire général",
            "pharmacy": MODULE_LABELS.get("pharmacy", "Pharmacie"),
            "clothing": MODULE_LABELS.get("clothing", "Habillement"),
        }
        self._dashboard_scope_label_to_value = {
            scope_labels[value]: value for value in scope_options
        }
        initial_scope_label = scope_labels[scope_options[0]]
        self.dashboard_scope_var = tk.StringVar(value=initial_scope_label)
        self.dashboard_scope_combobox: Optional[ttk.Combobox]
        self._dashboard_scope_values = scope_options

        summary_frame = ttk.Frame(self.dashboard_frame, padding=10)
        summary_frame.pack(fill=tk.X, anchor=tk.N)

        ttk.Label(summary_frame, text="Articles", font=('Segoe UI', 12, 'bold')).grid(row=0, column=0, padx=10, pady=5)
        ttk.Label(summary_frame, textvariable=self.dashboard_vars['total_items']).grid(row=1, column=0, padx=10)

        ttk.Label(summary_frame, text="Quantité totale", font=('Segoe UI', 12, 'bold')).grid(row=0, column=1, padx=10, pady=5)
        ttk.Label(summary_frame, textvariable=self.dashboard_vars['total_quantity']).grid(row=1, column=1, padx=10)

        ttk.Label(summary_frame, text="Valeur estimée", font=('Segoe UI', 12, 'bold')).grid(row=0, column=2, padx=10, pady=5)
        ttk.Label(summary_frame, textvariable=self.dashboard_vars['stock_value']).grid(row=1, column=2, padx=10)

        ttk.Label(summary_frame, text="Stocks faibles", font=('Segoe UI', 12, 'bold')).grid(row=0, column=3, padx=10, pady=5)
        ttk.Label(summary_frame, textvariable=self.dashboard_vars['low_stock_count']).grid(row=1, column=3, padx=10)

        self._dashboard_filter_update_blocked = False
        self.dashboard_selected_category_id = None

        filter_frame = ttk.LabelFrame(self.dashboard_frame, text="Filtres", padding=10)
        filter_frame.pack(fill=tk.X, padx=10, pady=(0, 10))

        column_index = 0
        if len(scope_options) > 1:
            ttk.Label(filter_frame, text="Module :").grid(row=0, column=column_index, padx=5, pady=5, sticky=tk.W)
            column_index += 1
            self.dashboard_scope_combobox = ttk.Combobox(
                filter_frame,
                state='readonly',
                textvariable=self.dashboard_scope_var,
                values=list(self._dashboard_scope_label_to_value.keys()),
                width=20,
            )
            self.dashboard_scope_combobox.grid(row=0, column=column_index, padx=5, pady=5, sticky=tk.W)
            self.dashboard_scope_combobox.set(initial_scope_label)
            self.dashboard_scope_combobox.bind("<<ComboboxSelected>>", self.on_dashboard_scope_change)
            column_index += 1
        else:
            ttk.Label(
                filter_frame,
                text=f"Module : {initial_scope_label}",
            ).grid(row=0, column=column_index, columnspan=2, padx=5, pady=5, sticky=tk.W)
            self.dashboard_scope_combobox = None
            column_index += 2

        ttk.Label(filter_frame, text="Catégorie :").grid(row=0, column=column_index, padx=5, pady=5, sticky=tk.W)
        self.dashboard_category_var = tk.StringVar()
        self.dashboard_category_combobox = ttk.Combobox(
            filter_frame,
            state='readonly',
            textvariable=self.dashboard_category_var,
            width=30,
        )
        self.dashboard_category_combobox.grid(row=0, column=column_index + 1, padx=5, pady=5, sticky=tk.W)
        self.dashboard_category_combobox.bind("<<ComboboxSelected>>", self.on_dashboard_filter_change)

        self.dashboard_category_ids = []
        self.load_dashboard_categories(scope_options[0])

        ttk.Label(filter_frame, text="Période ventes :").grid(row=0, column=column_index + 2, padx=5, pady=5, sticky=tk.W)
        self.dashboard_sales_period_map = {
            "7 jours": 7,
            "14 jours": 14,
            "30 jours": 30,
            "90 jours": 90,
        }
        self.dashboard_sales_period_default_label = "30 jours"
        self.dashboard_sales_period_var = tk.StringVar(value=self.dashboard_sales_period_default_label)
        self.dashboard_sales_period_combobox = ttk.Combobox(
            filter_frame,
            state='readonly',
            textvariable=self.dashboard_sales_period_var,
            values=list(self.dashboard_sales_period_map.keys()),
            width=12,
        )
        self.dashboard_sales_period_combobox.grid(row=0, column=column_index + 3, padx=5, pady=5, sticky=tk.W)
        self.dashboard_sales_period_combobox.set(self.dashboard_sales_period_default_label)
        self.dashboard_sales_period_combobox.bind("<<ComboboxSelected>>", self.on_dashboard_filter_change)

        ttk.Label(filter_frame, text="Historique mouvements :").grid(row=0, column=column_index + 4, padx=5, pady=5, sticky=tk.W)
        self.dashboard_movement_period_map = {
            "7 jours": 7,
            "14 jours": 14,
            "30 jours": 30,
            "60 jours": 60,
        }
        self.dashboard_movement_period_default_label = "14 jours"
        self.dashboard_movement_period_var = tk.StringVar(value=self.dashboard_movement_period_default_label)
        self.dashboard_movement_period_combobox = ttk.Combobox(
            filter_frame,
            state='readonly',
            textvariable=self.dashboard_movement_period_var,
            values=list(self.dashboard_movement_period_map.keys()),
            width=12,
        )
        self.dashboard_movement_period_combobox.grid(row=0, column=column_index + 5, padx=5, pady=5, sticky=tk.W)
        self.dashboard_movement_period_combobox.set(self.dashboard_movement_period_default_label)
        self.dashboard_movement_period_combobox.bind("<<ComboboxSelected>>", self.on_dashboard_filter_change)

        ttk.Button(filter_frame, text="Rafraîchir", command=self.refresh_dashboard).grid(
            row=0,
            column=column_index + 6,
            padx=5,
            pady=5,
        )
        ttk.Button(filter_frame, text="Réinitialiser", command=self.reset_dashboard_filters).grid(
            row=0,
            column=column_index + 7,
            padx=5,
            pady=5,
        )

        for col in (column_index + 1, column_index + 3, column_index + 5):
            filter_frame.grid_columnconfigure(col, weight=1)

        self.dashboard_figure = None
        self.dashboard_canvas = None
        self.dashboard_placeholder_label = None

        if MATPLOTLIB_AVAILABLE and FigureCanvasTkAgg is not None:
            self.dashboard_figure = Figure(figsize=(10, 4), dpi=100)
            self.dashboard_canvas = FigureCanvasTkAgg(self.dashboard_figure, master=self.dashboard_frame)
            self.dashboard_canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        else:
            self.dashboard_figure = None
            self.dashboard_canvas = None
            self.dashboard_placeholder_label = ttk.Label(
                self.dashboard_frame,
                text="Matplotlib n'est pas disponible : visualisation désactivée.",
            )
            self.dashboard_placeholder_label.pack(fill=tk.X, padx=10, pady=10)

        self.dashboard_job = None
        self._pending_dashboard_refresh: Optional[str] = None
        self.refresh_dashboard()

    def create_pharmacy_tab(self):
        if getattr(self, "pharmacy_frame", None) is None:
            return

        for child in self.pharmacy_frame.winfo_children():
            child.destroy()

        if pharmacy_inventory_manager is None:
            ttk.Label(
                self.pharmacy_frame,
                text="Module pharmacie indisponible : vérifiez l'installation.",
                foreground="#721c24",
            ).pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
            return

        try:
            ensure_pharmacy_inventory_schema()
        except Exception as exc:  # pragma: no cover - affichage d'une erreur critique
            ttk.Label(
                self.pharmacy_frame,
                text="Impossible d'initialiser les structures pharmaceutiques.",
                foreground="#721c24",
            ).pack(fill=tk.X, padx=10, pady=(15, 5))
            ttk.Label(
                self.pharmacy_frame,
                text=str(exc),
                wraplength=500,
                foreground="#721c24",
            ).pack(fill=tk.X, padx=10, pady=(0, 15))
            return

        self.pharmacy_summary_vars = {
            "total_batches": tk.StringVar(value="0"),
            "total_quantity": tk.StringVar(value="0"),
            "prescription_required": tk.StringVar(value="0"),
            "prescription_not_required": tk.StringVar(value="0"),
        }

        summary_frame = ttk.LabelFrame(self.pharmacy_frame, text="Résumé", padding=10)
        summary_frame.pack(fill=tk.X, padx=10, pady=(10, 5))

        summary_items = [
            ("Lots suivis", "total_batches"),
            ("Quantité totale", "total_quantity"),
            ("Sous ordonnance", "prescription_required"),
            ("Sans ordonnance", "prescription_not_required"),
        ]
        for column, (title, key) in enumerate(summary_items):
            ttk.Label(summary_frame, text=title, font=("Segoe UI", 11, "bold")).grid(
                row=0, column=column, padx=10, pady=5
            )
            ttk.Label(summary_frame, textvariable=self.pharmacy_summary_vars[key]).grid(
                row=1, column=column, padx=10
            )

        control_frame = ttk.Frame(self.pharmacy_frame)
        control_frame.pack(fill=tk.X, padx=10, pady=5)

        ttk.Label(control_frame, text="Recherche :").grid(row=0, column=0, padx=5, pady=5, sticky=tk.W)
        self.pharmacy_search_var = tk.StringVar()
        search_entry = ttk.Entry(control_frame, textvariable=self.pharmacy_search_var, width=30)
        search_entry.grid(row=0, column=1, padx=5, pady=5, sticky=tk.W)
        search_entry.bind("<Return>", lambda _event: self.refresh_pharmacy_batches())

        self.pharmacy_include_zero_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            control_frame,
            text="Afficher lots vides",
            variable=self.pharmacy_include_zero_var,
            command=self.refresh_pharmacy_batches,
        ).grid(row=0, column=2, padx=5, pady=5, sticky=tk.W)

        ttk.Button(
            control_frame,
            text="Enregistrer lot",
            command=self.open_pharmacy_register_dialog,
        ).grid(row=0, column=3, padx=5, pady=5)

        ttk.Button(
            control_frame,
            text="Ajuster quantité",
            command=self.adjust_selected_pharmacy_batch,
        ).grid(row=0, column=4, padx=5, pady=5)

        ttk.Button(
            control_frame,
            text="Lots à surveiller",
            command=self.show_expiring_pharmacy_batches,
        ).grid(row=0, column=5, padx=5, pady=5)

        control_frame.grid_columnconfigure(1, weight=1)

        tree_container = ttk.Frame(self.pharmacy_frame)
        tree_container.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

        columns = (
            "name",
            "lot",
            "expiration",
            "days_left",
            "quantity",
            "dosage",
            "form",
            "storage",
            "prescription",
        )
        self.pharmacy_tree = ttk.Treeview(
            tree_container,
            columns=columns,
            show="tree headings",
            selectmode="browse",
        )
        headings = {
            "name": "Nom",
            "lot": "Lot",
            "expiration": "Péremption",
            "days_left": "Jours restants",
            "quantity": "Quantité",
            "dosage": "Dosage",
            "form": "Forme",
            "storage": "Condition",
            "prescription": "Ordonnance",
        }
        for key, text in headings.items():
            self.pharmacy_tree.heading(key, text=text)
        self.pharmacy_tree.column("name", width=180, anchor=tk.W)
        self.pharmacy_tree.column("lot", width=120, anchor=tk.W)
        self.pharmacy_tree.column("expiration", width=110, anchor=tk.CENTER)
        self.pharmacy_tree.column("days_left", width=110, anchor=tk.CENTER)
        self.pharmacy_tree.column("quantity", width=90, anchor=tk.CENTER)
        self.pharmacy_tree.column("dosage", width=110, anchor=tk.W)
        self.pharmacy_tree.column("form", width=110, anchor=tk.W)
        self.pharmacy_tree.column("storage", width=150, anchor=tk.W)
        self.pharmacy_tree.column("prescription", width=110, anchor=tk.CENTER)
        self.pharmacy_tree.heading("#0", text="", anchor=tk.CENTER)
        self.pharmacy_tree.column("#0", width=32, stretch=False, anchor=tk.CENTER)

        vsb = ttk.Scrollbar(tree_container, orient=tk.VERTICAL, command=self.pharmacy_tree.yview)
        hsb = ttk.Scrollbar(tree_container, orient=tk.HORIZONTAL, command=self.pharmacy_tree.xview)
        self.pharmacy_tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        self._apply_tree_tag_palette()

        self.pharmacy_tree.bind("<Double-1>", self.on_pharmacy_batch_double_click)

        self.pharmacy_tree.pack(fill=tk.BOTH, expand=True, side=tk.LEFT)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        hsb.pack(side=tk.BOTTOM, fill=tk.X)

        self.pharmacy_batch_cache: dict[str, PharmacyBatch] = {}
        self._pharmacy_search_job: Optional[str] = None
        self.pharmacy_search_var.trace_add('write', self._on_pharmacy_search_change)

        self.load_pharmacy_column_preferences()
        self.refresh_pharmacy_summary()
        self.refresh_pharmacy_batches()
        self.update_toolbar_state()

    def _on_pharmacy_search_change(self, *_args):
        if getattr(self, '_pharmacy_search_job', None):
            try:
                self.after_cancel(self._pharmacy_search_job)
            except Exception:
                pass
        self._pharmacy_search_job = self.after(300, self.refresh_pharmacy_batches)

    def refresh_pharmacy_batches(self):
        if not hasattr(self, 'pharmacy_tree'):
            return
        if pharmacy_inventory_manager is None:
            return
        try:
            batches = list_pharmacy_batches(
                search=self.pharmacy_search_var.get(),
                include_zero=self.pharmacy_include_zero_var.get(),
            )
        except Exception as exc:
            messagebox.showerror(
                "Erreur Pharmacie",
                f"Impossible de charger les lots pharmaceutiques : {exc}",
                parent=self,
            )
            return

        self.pharmacy_tree.delete(*self.pharmacy_tree.get_children())
        self.pharmacy_batch_cache.clear()

        for batch in batches:
            expiration_display = format_display_date(batch.expiration_date)
            if batch.days_left is None:
                days_display = "N/A"
            else:
                days_display = str(batch.days_left)
            values = (
                batch.name,
                batch.lot_number,
                expiration_display,
                days_display,
                batch.quantity,
                batch.dosage or '',
                batch.form or '',
                batch.storage_condition or '',
                "Oui" if batch.prescription_required else "Non",
            )

            tags: list[str] = []
            if batch.quantity <= 0:
                tags.append('pharmacy_empty')
            if batch.days_left is not None:
                if batch.days_left < 0:
                    tags = ['pharmacy_expired']
                elif batch.days_left <= 30:
                    tags.append('pharmacy_expiring')

            insert_kwargs = {
                'iid': str(batch.id),
                'values': values,
                'text': '',
            }
            if tags:
                insert_kwargs['tags'] = tuple(tags)
            icon = self._get_status_icon(tags)
            if icon is not None:
                insert_kwargs['image'] = icon
            self.pharmacy_tree.insert('', 'end', **insert_kwargs)
            self.pharmacy_batch_cache[str(batch.id)] = batch

        if batches:
            self.pharmacy_tree.yview_moveto(0)

    def refresh_pharmacy_summary(self):
        if not hasattr(self, 'pharmacy_summary_vars'):
            return
        if pharmacy_inventory_manager is None:
            for var in self.pharmacy_summary_vars.values():
                var.set('—')
            return
        try:
            summary = summarize_pharmacy_stock()
        except Exception as exc:
            for var in self.pharmacy_summary_vars.values():
                var.set('—')
            messagebox.showerror(
                "Erreur Pharmacie",
                f"Impossible de récupérer le résumé pharmacie : {exc}",
                parent=self,
            )
            return

        self.pharmacy_summary_vars['total_batches'].set(str(summary.get('total_batches', 0)))
        self.pharmacy_summary_vars['total_quantity'].set(str(summary.get('total_quantity', 0)))
        by_prescription = summary.get('by_prescription_requirement', {}) or {}
        self.pharmacy_summary_vars['prescription_required'].set(
            str(by_prescription.get('required', 0))
        )
        self.pharmacy_summary_vars['prescription_not_required'].set(
            str(by_prescription.get('not_required', 0))
        )

    def open_pharmacy_register_dialog(self):
        if pharmacy_inventory_manager is None:
            messagebox.showerror(
                "Module indisponible",
                "La gestion pharmacie n'est pas disponible sur cette installation.",
                parent=self,
            )
            return

        dialog = PharmacyBatchDialog(self, "Nouveau lot pharmacie")
        if not dialog.result:
            return

        try:
            register_pharmacy_batch(operator=self.current_user, **dialog.result)
        except Exception as exc:
            messagebox.showerror(
                "Erreur", f"Impossible d'enregistrer le lot : {exc}", parent=self
            )
            return

        messagebox.showinfo(
            "Succès",
            "Le lot pharmaceutique a été enregistré avec succès.",
            parent=self,
        )
        self.refresh_pharmacy_summary()
        self.refresh_pharmacy_batches()

    def open_pharmacy_edit_dialog(self):
        if pharmacy_inventory_manager is None or not hasattr(self, 'pharmacy_tree'):
            return
        selection = self.pharmacy_tree.selection()
        if not selection:
            messagebox.showinfo(
                "Sélection requise",
                "Sélectionnez un lot à modifier.",
                parent=self,
            )
            return
        batch_id = selection[0]
        try:
            batch_details = get_pharmacy_batch(int(batch_id))
        except Exception as exc:
            messagebox.showerror(
                "Erreur Pharmacie",
                f"Impossible de récupérer le lot : {exc}",
                parent=self,
            )
            return
        if not batch_details:
            messagebox.showerror(
                "Introuvable",
                "Le lot sélectionné est introuvable.",
                parent=self,
            )
            return
        dialog = PharmacyBatchDialog(
            self,
            "Modifier lot pharmacie",
            initial=batch_details,
        )
        if not dialog.result:
            return
        try:
            result = update_pharmacy_batch(
                int(batch_id),
                operator=self.current_user,
                **dialog.result,
            )
        except Exception as exc:
            messagebox.showerror(
                "Erreur Pharmacie",
                f"Impossible de modifier le lot : {exc}",
                parent=self,
            )
            return
        if not result:
            messagebox.showerror(
                "Introuvable",
                "Le lot sélectionné est introuvable.",
                parent=self,
            )
            return
        messagebox.showinfo(
            "Succès",
            "Le lot a été mis à jour avec succès.",
            parent=self,
        )
        self.refresh_pharmacy_summary()
        self.refresh_pharmacy_batches()

    def adjust_selected_pharmacy_batch(self):
        if pharmacy_inventory_manager is None or not hasattr(self, 'pharmacy_tree'):
            return
        selection = self.pharmacy_tree.selection()
        if not selection:
            messagebox.showwarning(
                "Sélection requise",
                "Veuillez sélectionner un lot à ajuster.",
                parent=self,
            )
            return
        batch_id = selection[0]
        batch = self.pharmacy_batch_cache.get(batch_id)
        prompt = "Entrez l'ajustement (positif ou négatif) :"
        if batch is not None:
            prompt = (
                f"Ajustement pour {batch.name} (lot {batch.lot_number})\n"
                "Entrez l'ajustement (positif ou négatif) :"
            )
        delta_str = simpledialog.askstring(
            "Ajuster quantité",
            prompt,
            parent=self,
        )
        if delta_str is None:
            return
        try:
            delta = int(delta_str.strip())
        except (TypeError, ValueError):
            messagebox.showerror(
                "Valeur invalide",
                "Veuillez entrer un entier positif ou négatif.",
                parent=self,
            )
            return
        if delta == 0:
            return

        try:
            result = adjust_pharmacy_batch_quantity(
                int(batch_id),
                delta,
                operator=self.current_user,
            )
        except Exception as exc:
            messagebox.showerror(
                "Erreur",
                f"Impossible d'ajuster le lot : {exc}",
                parent=self,
            )
            return

        if not result:
            messagebox.showerror(
                "Introuvable",
                "Le lot sélectionné est introuvable ou a été supprimé.",
                parent=self,
            )
            return

        messagebox.showinfo(
            "Quantité mise à jour",
            f"Nouvelle quantité du lot : {result['quantity']}",
            parent=self,
        )
        self.refresh_pharmacy_summary()
        self.refresh_pharmacy_batches()

    def delete_selected_pharmacy_batch(self):
        if pharmacy_inventory_manager is None or not hasattr(self, 'pharmacy_tree'):
            return
        selection = self.pharmacy_tree.selection()
        if not selection:
            messagebox.showinfo(
                "Sélection requise",
                "Sélectionnez un lot à supprimer.",
                parent=self,
            )
            return
        batch_id = selection[0]
        batch = self.pharmacy_batch_cache.get(batch_id)
        lot_label = batch.lot_number if batch else batch_id
        if not messagebox.askyesno(
            "Confirmation",
            f"Supprimer le lot {lot_label} ?",
            parent=self,
        ):
            return
        try:
            success = delete_pharmacy_batch(int(batch_id), operator=self.current_user)
        except Exception as exc:
            messagebox.showerror(
                "Erreur Pharmacie",
                f"Impossible de supprimer le lot : {exc}",
                parent=self,
            )
            return
        if not success:
            messagebox.showerror(
                "Introuvable",
                "Le lot sélectionné est introuvable.",
                parent=self,
            )
            return
        messagebox.showinfo(
            "Lot supprimé",
            "Le lot pharmaceutique a été supprimé.",
            parent=self,
        )
        self.refresh_pharmacy_summary()
        self.refresh_pharmacy_batches()

    def show_expiring_pharmacy_batches(self):
        if getattr(self, "pharmacy_frame", None) is None or not hasattr(self, 'pharmacy_tree'):
            return
        if pharmacy_inventory_manager is None:
            messagebox.showerror(
                "Module indisponible",
                "La gestion pharmacie n'est pas disponible sur cette installation.",
                parent=self,
            )
            return
        try:
            batches = list_expiring_pharmacy_batches(within_days=30, include_empty=False)
        except Exception as exc:
            messagebox.showerror(
                "Erreur",
                f"Impossible de récupérer les lots à surveiller : {exc}",
                parent=self,
            )
            return

        if not batches:
            messagebox.showinfo(
                "Information",
                "Aucun lot n'est proche de la péremption dans les 30 prochains jours.",
                parent=self,
            )
            return

        lines = []
        for batch in batches:
            expiration_display = format_display_date(batch.expiration_date)
            if batch.days_left is None:
                days_display = "N/A"
            else:
                days_display = str(batch.days_left)
            lines.append(
                f"{batch.name} - Lot {batch.lot_number}\n"
                f"  Péremption : {expiration_display or '—'} | Jours restants : {days_display} | Qté : {batch.quantity}"
            )

        messagebox.showinfo(
            "Lots proches de la péremption",
            "\n\n".join(lines),
            parent=self,
        )

    def on_pharmacy_batch_double_click(self, _event=None):
        if not hasattr(self, 'pharmacy_tree'):
            return
        selection = self.pharmacy_tree.selection()
        if not selection:
            return
        batch = self.pharmacy_batch_cache.get(selection[0])
        if batch is None:
            return
        expiration_display = format_display_date(batch.expiration_date)
        if batch.days_left is None:
            days_display = "N/A"
        else:
            days_display = str(batch.days_left)
        details = [
            f"Nom : {batch.name}",
            f"Lot : {batch.lot_number}",
            f"Quantité : {batch.quantity}",
            f"Péremption : {expiration_display or '—'} (Jours restants : {days_display})",
            f"Dosage : {batch.dosage or '—'}",
            f"Forme : {batch.form or '—'}",
            f"Condition de stockage : {batch.storage_condition or '—'}",
            f"Ordonnance requise : {'Oui' if batch.prescription_required else 'Non'}",
        ]
        messagebox.showinfo(
            f"Détails - Lot {batch.lot_number}",
            "\n".join(details),
            parent=self,
        )

    def _get_dashboard_scope_value(self) -> str:
        mapping = getattr(self, "_dashboard_scope_label_to_value", {})
        if not mapping:
            return "general"
        label = self.dashboard_scope_var.get() if hasattr(self, "dashboard_scope_var") else ""
        if label in mapping:
            return mapping[label]
        return next(iter(mapping.values()))

    def load_dashboard_categories(self, scope: str = "general"):
        if scope == "clothing":
            self._dashboard_filter_update_blocked = True
            try:
                self.dashboard_category_ids = []
                self.dashboard_category_combobox.config(state="disabled")
                self.dashboard_category_combobox['values'] = ("Toutes",)
                self.dashboard_category_combobox.current(0)
                self.dashboard_category_var.set("Toutes")
                self.dashboard_selected_category_id = None
            finally:
                self._dashboard_filter_update_blocked = False
            return

        conn = None
        rows = []
        try:
            with db_lock:
                conn = sqlite3.connect(DB_PATH, timeout=30)
                cursor = conn.cursor()
                if scope == "pharmacy":
                    cursor.execute(
                        "SELECT DISTINCT categories.id, categories.name "
                        "FROM categories "
                        "JOIN items ON items.category_id = categories.id "
                        "WHERE items.is_medicine = 1 "
                        "ORDER BY categories.name"
                    )
                else:
                    cursor.execute("SELECT id, name FROM categories ORDER BY name")
                rows = cursor.fetchall()
        except sqlite3.Error as exc:
            print(f"[DB Error] load_dashboard_categories: {exc}")
        finally:
            if conn:
                conn.close()

        labels = ["Toutes"]
        ids = [-1]
        for cat_id, name in rows:
            labels.append(name)
            ids.append(cat_id)

        self._dashboard_filter_update_blocked = True
        try:
            self.dashboard_category_combobox.config(state="readonly")
            self.dashboard_category_ids = ids
            self.dashboard_category_combobox['values'] = labels
            if labels:
                self.dashboard_category_combobox.current(0)
                self.dashboard_category_var.set(labels[0])
            else:
                self.dashboard_category_var.set('')
            self.dashboard_selected_category_id = None
        finally:
            self._dashboard_filter_update_blocked = False

    def _update_dashboard_category_selection(self):
        if not hasattr(self, 'dashboard_category_combobox'):
            return
        if self._get_dashboard_scope_value() == "clothing":
            self.dashboard_selected_category_id = None
            return
        try:
            idx = self.dashboard_category_combobox.current()
        except tk.TclError:
            idx = -1
        if idx is None:
            idx = -1
        if idx > 0 and idx < len(getattr(self, 'dashboard_category_ids', [])):
            self.dashboard_selected_category_id = self.dashboard_category_ids[idx]
        else:
            self.dashboard_selected_category_id = None

    def on_dashboard_filter_change(self, event=None):
        if getattr(self, '_dashboard_filter_update_blocked', False):
            return
        self._update_dashboard_category_selection()
        self.refresh_dashboard()

    def reset_dashboard_filters(self):
        self._dashboard_filter_update_blocked = True
        try:
            current_scope = self._get_dashboard_scope_value()
            self.load_dashboard_categories(current_scope)
            if getattr(self, 'dashboard_category_combobox', None) is not None:
                if self.dashboard_category_combobox['values']:
                    self.dashboard_category_combobox.current(0)
                    self.dashboard_category_var.set(self.dashboard_category_combobox['values'][0])
            self.dashboard_selected_category_id = None
            if getattr(self, 'dashboard_sales_period_combobox', None) is not None:
                self.dashboard_sales_period_var.set(self.dashboard_sales_period_default_label)
                self.dashboard_sales_period_combobox.set(self.dashboard_sales_period_default_label)
            if getattr(self, 'dashboard_movement_period_combobox', None) is not None:
                self.dashboard_movement_period_var.set(self.dashboard_movement_period_default_label)
                self.dashboard_movement_period_combobox.set(self.dashboard_movement_period_default_label)
        finally:
            self._dashboard_filter_update_blocked = False
        self.refresh_dashboard()

    def on_dashboard_scope_change(self, _event=None):
        scope = self._get_dashboard_scope_value()
        self.load_dashboard_categories(scope)
        self.refresh_dashboard()

    def load_inventory(self):
        tree = getattr(self, 'tree', None)
        if tree is None:
            return
        entry = getattr(self, 'entry_search', None)
        search_text = entry.get().lower().strip() if entry is not None else ''
        for row in tree.get_children():
            tree.delete(row)
        conn = None
        conn = None
        try:
            with db_lock:
                conn = sqlite3.connect(DB_PATH, timeout=30)
                cursor = conn.cursor()
                base_query = (
                    "SELECT items.id, items.name, items.barcode, categories.name, suppliers.name, items.size, categories.note, items.quantity, items.last_updated, items.reorder_point, items.unit_cost "
                    "FROM items LEFT JOIN categories ON items.category_id = categories.id "
                    "LEFT JOIN suppliers ON suppliers.id = items.preferred_supplier_id"
                )
                if search_text:
                    cursor.execute(
                        base_query + " WHERE lower(items.name) LIKE ? OR items.barcode LIKE ? OR lower(COALESCE(suppliers.name,'')) LIKE ?",
                        (f'%{search_text}%', f'%{search_text}%', f'%{search_text}%')
                    )
                else:
                    cursor.execute(base_query)
                rows = cursor.fetchall()
        except sqlite3.Error as e:
            messagebox.showerror("Erreur BD", f"Impossible de charger l'inventaire : {e}")
            rows = []
        finally:
            if conn:
                conn.close()
        for item in rows:
            (
                item_id,
                name,
                barcode,
                category,
                supplier_name,
                size,
                category_note,
                quantity,
                last_updated,
                reorder_point,
                unit_cost,
            ) = item
            tag = self._get_stock_tag(quantity, reorder_point)
            category_display = category or 'Sans catégorie'
            display_values = (
                item_id,
                name,
                barcode,
                category_display,
                supplier_name or '',
                size,
                category_note or '',
                quantity,
                last_updated,
            )
            insert_kwargs = {
                'parent': '',
                'index': tk.END,
                'values': display_values,
                'tags': (tag,),
                'text': '',
            }
            icon = self._get_status_icon([tag])
            if icon is not None:
                insert_kwargs['image'] = icon
            tree.insert(**insert_kwargs)
        count = len(tree.get_children())
        self.status.set(f"Articles listés : {count}")
        self.request_dashboard_refresh()

    def _get_stock_tag(self, quantity, reorder_point=None):
        """Retourne le tag à appliquer selon la quantité disponible et le seuil défini."""
        try:
            qty = int(quantity)
        except (TypeError, ValueError):
            return 'stock_unknown'
        try:
            if reorder_point is not None:
                threshold = int(reorder_point)
            else:
                threshold = int(self.low_stock_threshold)
        except (TypeError, ValueError):
            threshold = DEFAULT_LOW_STOCK_THRESHOLD
        if qty <= 0:
            return 'stock_zero'
        if qty <= threshold:
            return 'stock_low'
        return 'stock_ok'

    def _get_item_reorder_point(self, item_id):
        conn = None
        try:
            with db_lock:
                conn = sqlite3.connect(DB_PATH, timeout=30)
                cursor = conn.cursor()
                cursor.execute("SELECT reorder_point FROM items WHERE id = ?", (item_id,))
                row = cursor.fetchone()
                if row:
                    return row[0]
        except sqlite3.Error as e:
            print(f"[DB Error] _get_item_reorder_point: {e}")
        finally:
            if conn:
                conn.close()
        return None

    def _maybe_show_low_stock_alert(self, item_id, item_name, new_qty, old_qty, reorder_point=None):
        """Affiche une alerte lorsque le stock passe sous le seuil configuré."""
        try:
            if reorder_point is not None:
                threshold = int(reorder_point)
            else:
                threshold = int(self.low_stock_threshold)
        except (TypeError, ValueError):
            threshold = DEFAULT_LOW_STOCK_THRESHOLD
        try:
            previous_qty = int(old_qty)
        except (TypeError, ValueError):
            previous_qty = None

        if previous_qty is not None and previous_qty > threshold and new_qty <= threshold:
            messagebox.showwarning(
                "Stock faible",
                (
                    f"L'article '{item_name}' est passé sous le seuil de {threshold} unités.\n"
                    f"Stock actuel : {new_qty}."
                ),
            )
            if hasattr(self, 'alert_manager') and self.alert_manager:
                self.alert_manager.dispatch_low_stock_alert(item_id, item_name, new_qty, threshold)

    def refresh_dashboard(self):
        pending_job = getattr(self, "_pending_dashboard_refresh", None)
        if pending_job:
            try:
                self.after_cancel(pending_job)
            except Exception:
                pass
            self._pending_dashboard_refresh = None
        if hasattr(self, '_dashboard_filter_update_blocked') and not getattr(
            self, '_dashboard_filter_update_blocked', False
        ):
            self._update_dashboard_category_selection()

        scope = self._get_dashboard_scope_value()
        category_id = getattr(self, 'dashboard_selected_category_id', None)
        if scope == "clothing":
            category_id = None
        sales_label = getattr(self, 'dashboard_sales_period_var', None)
        sales_choice = sales_label.get() if sales_label is not None else '30 jours'
        sales_days = getattr(self, 'dashboard_sales_period_map', {}).get(sales_choice, 30)
        movement_label = getattr(self, 'dashboard_movement_period_var', None)
        movement_choice = movement_label.get() if movement_label is not None else '14 jours'
        movement_days = getattr(self, 'dashboard_movement_period_map', {}).get(movement_choice, 14)

        metrics = fetch_dashboard_metrics(
            self.low_stock_threshold,
            category_id=category_id,
            sales_days=sales_days,
            movement_days=movement_days,
            module_scope=scope,
        )
        self.dashboard_vars['total_items'].set(str(metrics['total_items']))
        self.dashboard_vars['total_quantity'].set(str(metrics['total_quantity']))
        self.dashboard_vars['stock_value'].set(f"{metrics['stock_value']:.2f} €")
        self.dashboard_vars['low_stock_count'].set(str(metrics['low_stock_count']))

        if self.dashboard_figure and self.dashboard_canvas:
            self.dashboard_figure.clf()
            ax1 = self.dashboard_figure.add_subplot(121)
            top_sales = metrics['top_sales'] or []
            if top_sales:
                names = [row[0] for row in top_sales]
                values = [row[1] for row in top_sales]
                ax1.bar(names, values, color='#1976d2')
                ax1.set_title(f'Top sorties ({sales_days} j)')
                ax1.tick_params(axis='x', rotation=45, labelsize=8)
            else:
                ax1.text(0.5, 0.5, 'Pas de données', ha='center', va='center')
                ax1.set_xticks([])
                ax1.set_yticks([])

            ax2 = self.dashboard_figure.add_subplot(122)
            history = metrics['movement_history'] or []
            if history:
                dates = [row[0] for row in history]
                entries = [row[1] or 0 for row in history]
                exits = [row[2] or 0 for row in history]
                ax2.plot(dates, entries, label='Entrées', marker='o')
                ax2.plot(dates, exits, label='Sorties', marker='o')
                ax2.set_title(f'Mouvements ({movement_days} j)')
                ax2.tick_params(axis='x', rotation=45, labelsize=8)
                ax2.legend()
            else:
                ax2.text(0.5, 0.5, 'Pas d\'historique', ha='center', va='center')
                ax2.set_xticks([])
                ax2.set_yticks([])
            self.dashboard_figure.tight_layout()
            self.dashboard_canvas.draw_idle()

        if hasattr(self, 'dashboard_job') and self.dashboard_job:
            try:
                self.after_cancel(self.dashboard_job)
            except Exception:
                pass
        self.dashboard_job = self.after(60000, self.refresh_dashboard)

    def request_dashboard_refresh(self) -> None:
        if not hasattr(self, 'dashboard_frame'):
            return
        if getattr(self, '_pending_dashboard_refresh', None):
            return

        def _trigger_refresh() -> None:
            self._pending_dashboard_refresh = None
            self.refresh_dashboard()

        self._pending_dashboard_refresh = self.after_idle(_trigger_refresh)

    def apply_saved_column_widths(self):
        """
        Lit la section 'ColumnWidths' dans config.ini et applique aux colonnes existantes.
        """
        if 'ColumnWidths' not in config:
            return
        lower_to_column = {col.lower(): col for col in self.tree['columns']}
        for col_key, val in config['ColumnWidths'].items():
            try:
                width = int(val)
            except (TypeError, ValueError):
                continue
            target = None
            if col_key in self.tree['columns']:
                target = col_key
            else:
                target = lower_to_column.get(col_key.lower())
            if target:
                self.tree.column(target, width=width)

    def save_column_widths(self):
        """
        Sauvegarde les largeurs actuelles des colonnes dans config.ini, section 'ColumnWidths'.
        """
        if not hasattr(self, "tree"):
            return
        if 'ColumnWidths' not in config:
            config['ColumnWidths'] = {}
        section = config['ColumnWidths']
        for key in list(section.keys()):
            del section[key]
        for col in self.tree['columns']:
            width = self.tree.column(col).get('width')
            if width is None:
                continue
            section[col] = str(width)
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            config.write(f)

    def _create_item(
        self,
        name,
        barcode_value,
        category_id,
        size,
        qty,
        unit_cost,
        reorder_point,
        preferred_supplier_id,
        *,
        source="manual_creation",
        log_note="Création article via formulaire",
    ):
        """Insère un article en base et retourne son identifiant ou ``None`` en cas d'erreur."""

        conn = None
        item_id: Optional[int] = None
        try:
            with db_lock:
                conn = sqlite3.connect(DB_PATH, timeout=30)
                cursor = conn.cursor()
                timestamp = datetime.now().isoformat()
                cursor.execute(
                    """
                    INSERT INTO items (
                        name,
                        barcode,
                        category_id,
                        size,
                        quantity,
                        last_updated,
                        unit_cost,
                        reorder_point,
                        preferred_supplier_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        name,
                        barcode_value,
                        category_id,
                        size,
                        qty,
                        timestamp,
                        unit_cost,
                        reorder_point,
                        preferred_supplier_id,
                    ),
                )
                item_id = cursor.lastrowid
                if qty:
                    log_stock_movement(
                        cursor,
                        item_id,
                        qty,
                        'IN',
                        source,
                        self.current_user,
                        note=log_note,
                        timestamp=timestamp,
                    )
                conn.commit()
        except sqlite3.IntegrityError as e:
            messagebox.showerror("Erreur", f"Impossible d'ajouter l'article : {e}")
            return None
        except sqlite3.Error as e:
            messagebox.showerror("Erreur BD", f"Erreur lors de l'ajout : {e}")
            return None
        finally:
            if conn:
                conn.close()

        if item_id is not None:
            self.log_user_action(
                "Création de l'article '%s' (ID %s, quantité initiale %s, catégorie %s)." % (
                    name,
                    item_id,
                    qty,
                    category_id if category_id is not None else "sans catégorie",
                )
            )

        if ENABLE_BARCODE_GENERATION and barcode_value:
            save_barcode_image(barcode_value, article_name=name)
        return item_id

    def open_add_dialog(self):
        dialog = ItemDialog(self, "Ajouter Article")
        item_id = None
        if dialog.result:
            (
                name,
                barcode_value,
                category_id,
                size,
                qty,
                unit_cost,
                reorder_point,
                preferred_supplier_id,
            ) = dialog.result
            item_id = self._create_item(
                name,
                barcode_value,
                category_id,
                size,
                qty,
                unit_cost,
                reorder_point,
                preferred_supplier_id,
                source='manual_creation',
                log_note="Création article via formulaire",
            )
        if item_id:
            self.status.set(f"Article '{name}' ajouté.")
            self.load_inventory()
            self.select_item_in_tree(item_id)

    def open_edit_selected(self):
        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning("Attention", "Aucun article sélectionné.")
            return
        item = self.tree.item(selected)
        id_ = item['values'][0]
        conn = None
        try:
            with db_lock:
                conn = sqlite3.connect(DB_PATH, timeout=30)
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT name, barcode, category_id, size, quantity, unit_cost, reorder_point, preferred_supplier_id
                    FROM items WHERE id = ?
                    """,
                    (id_,),
                )
                row = cursor.fetchone()
        except sqlite3.Error as e:
            messagebox.showerror("Erreur BD", f"Impossible de récupérer l'article : {e}")
            return
        finally:
            if conn:
                conn.close()
        if not row:
            messagebox.showerror("Erreur", "Article introuvable")
            return
        name, barcode_value, category_id, size_value, qty, unit_cost, reorder_point, preferred_supplier_id = row
        try:
            old_qty = int(qty)
        except (TypeError, ValueError):
            old_qty = 0
        dialog = ItemDialog(
            self,
            "Modifier Article",
            name,
            barcode_value,
            category_id,
            size_value,
            qty,
            unit_cost,
            reorder_point,
            preferred_supplier_id,
        )
        if dialog.result:
            (
                new_name,
                new_barcode,
                new_category_id,
                new_size,
                new_qty,
                new_unit_cost,
                new_reorder_point,
                new_preferred_supplier,
            ) = dialog.result
            conn = None
            try:
                with db_lock:
                    conn = sqlite3.connect(DB_PATH, timeout=30)
                    cursor = conn.cursor()
                    timestamp = datetime.now().isoformat()
                    cursor.execute(
                        """
                        UPDATE items
                        SET name = ?, barcode = ?, category_id = ?, size = ?, quantity = ?, last_updated = ?,
                            unit_cost = ?, reorder_point = ?, preferred_supplier_id = ?
                        WHERE id = ?
                        """,
                        (
                            new_name,
                            new_barcode,
                            new_category_id,
                            new_size,
                            new_qty,
                            timestamp,
                            new_unit_cost,
                            new_reorder_point,
                            new_preferred_supplier,
                            id_,
                        )
                    )
                    try:
                        new_qty_int = int(new_qty)
                    except (TypeError, ValueError):
                        new_qty_int = old_qty
                    change = new_qty_int - old_qty
                    if change:
                        movement_type = 'IN' if change > 0 else 'OUT'
                        log_stock_movement(
                            cursor,
                            id_,
                            change,
                            movement_type,
                            'manual_edit',
                            self.current_user,
                            note="Modification via formulaire",
                            timestamp=timestamp,
                        )
                    conn.commit()
                    if change:
                        self.log_user_action(
                            "Modification de l'article '%s' (ID %s) : stock %s → %s (%s%s)." % (
                                new_name,
                                id_,
                                old_qty,
                                new_qty_int,
                                "+" if change > 0 else "",
                                change,
                            )
                        )
                    else:
                        self.log_user_action(
                            "Modification de l'article '%s' (ID %s) sans changement de stock." % (
                                new_name,
                                id_,
                            )
                        )
                    self.status.set(f"Article '{new_name}' mis à jour.")
                    if ENABLE_BARCODE_GENERATION and new_barcode:
                        save_barcode_image(new_barcode, article_name=new_name)
            except sqlite3.IntegrityError as e:
                messagebox.showerror("Erreur", f"Impossible de modifier l'article : {e}")
            except sqlite3.Error as e:
                messagebox.showerror("Erreur BD", f"Erreur lors de la modification : {e}")
            finally:
                if conn:
                    conn.close()
            self.load_inventory()

    def delete_selected(self):
        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning("Attention", "Aucun article sélectionné.")
            return
        item = self.tree.item(selected)
        id_, name = item['values'][0], item['values'][1]
        barcode_value = item['values'][2]
        try:
            current_qty = int(item['values'][5])
        except (TypeError, ValueError):
            current_qty = 0
        if self.current_role != 'admin':
            create_approval_request(
                id_,
                'delete_item',
                current_qty,
                f"Suppression demandée pour {name}",
                self.current_user,
                payload={'item_name': name, 'barcode': barcode_value},
            )
            messagebox.showinfo(
                "Approbation requise",
                "Une demande de suppression a été envoyée à un administrateur.",
            )
            return
        if messagebox.askyesno("Confirmation", f"Supprimer l'article '{name}' ?"):
            conn = None
            try:
                with db_lock:
                    conn = sqlite3.connect(DB_PATH, timeout=30)
                    cursor = conn.cursor()
                    if current_qty:
                        log_stock_movement(
                            cursor,
                            id_,
                            -current_qty,
                            'OUT',
                            'manual_delete',
                            self.current_user,
                            note="Suppression de l'article",
                        )
                    cursor.execute("DELETE FROM items WHERE id = ?", (id_,))
                    conn.commit()
                if ENABLE_BARCODE_GENERATION and barcode_value:
                    safe_name = name.replace(" ", "_")
                    safe_name = "".join(ch for ch in safe_name if ch.isalnum() or ch == "_")
                    filepath = os.path.join(BARCODE_DIR, f"{safe_name}.png")
                    if os.path.exists(filepath):
                        os.remove(filepath)
                self.log_user_action(
                    "Suppression de l'article '%s' (ID %s, quantité retirée %s)." % (
                        name,
                        id_,
                        current_qty,
                    )
                )
                self.status.set(f"Article '{name}' supprimé.")
            except sqlite3.Error as e:
                messagebox.showerror("Erreur BD", f"Erreur lors de la suppression : {e}")
            finally:
                if conn:
                    conn.close()
            self.load_inventory()

    def open_supplier_management(self):
        SupplierManagementDialog(self)

    def open_purchase_orders(self):
        PurchaseOrderManagementDialog(self)

    def open_collaborator_gear(self):
        CollaboratorGearDialog(self)

    def open_approval_queue(self):
        if self.current_role != 'admin':
            messagebox.showerror("Accès refusé", "Seuls les administrateurs peuvent valider les demandes.")
            return
        ApprovalQueueDialog(self)

    def open_stock_adjustment(self, is_entry):
        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning("Attention", "Sélectionnez un article dans la liste.")
            return
        item = self.tree.item(selected)
        values = item.get('values', [])
        if len(values) < 4:
            messagebox.showerror(
                "Stock",
                "Les informations de l'article sélectionné sont incomplètes."
            )
            return
        id_ = values[0]
        name = values[1] if len(values) > 1 else ""
        size_value = values[5] if len(values) > 5 else ""
        qty = values[6] if len(values) > 6 else 0
        try:
            qty = int(qty)
        except (TypeError, ValueError):
            qty = 0
        title = "Entrée de stock" if is_entry else "Sortie de stock"
        prompt = "Quantité à ajouter :" if is_entry else "Quantité à retirer :"
        amount = simpledialog.askinteger(title, prompt, minvalue=1)
        if amount is None:
            return
        note = simpledialog.askstring(title, "Commentaire (optionnel) :")
        if not is_entry and self.current_role != 'admin':
            create_approval_request(
                id_,
                'stock_out',
                amount,
                note,
                self.current_user,
                payload={'item_name': name, 'size': size_value},
            )
            messagebox.showinfo(
                "Approbation requise",
                "Une demande d'approbation a été transmise à un administrateur.",
            )
            return
        delta = amount if is_entry else -amount
        source = 'manual_entry' if is_entry else 'manual_exit'
        result = adjust_item_quantity(
            id_,
            delta,
            operator=self.current_user,
            source=source,
            note=note,
        )
        if not result:
            messagebox.showerror("Stock", "Impossible de mettre à jour la quantité.")
            return
        new_qty, change, old_qty = result
        if change == 0:
            messagebox.showinfo(
                "Stock",
                f"Aucune modification réalisée pour '{name}'. Stock actuel : {new_qty}",
            )
        else:
            action_word = "ajoutées" if change > 0 else "retirées"
            messagebox.showinfo(
                "Stock",
                f"{abs(change)} unités {action_word} pour '{name}'.\nStock : {old_qty} → {new_qty}",
            )
            self.status.set(
                f"{abs(change)} unités {'ajoutées' if change > 0 else 'retirées'} pour '{name}'"
            )
        if change:
            self.log_user_action(
                "Mouvement de stock %s pour l'article '%s' (ID %s) : %s → %s (%s%s) via %s." % (
                    'entrant' if change > 0 else 'sortant',
                    name,
                    id_,
                    old_qty,
                    new_qty,
                    "+" if change > 0 else "",
                    change,
                    source,
                )
            )
        else:
            self.log_user_action(
                "Tentative d'ajustement sans effet pour l'article '%s' (ID %s)." % (
                    name,
                    id_,
                )
            )
        if change < 0:
            reorder_point = self._get_item_reorder_point(id_)
            self._maybe_show_low_stock_alert(id_, name, new_qty, old_qty, reorder_point)
        self.load_inventory()
        self.select_item_in_tree(id_)

    def select_item_in_tree(self, item_id):
        for row_id in self.tree.get_children():
            values = self.tree.item(row_id)['values']
            if values and values[0] == item_id:
                self.tree.selection_set(row_id)
                self.tree.see(row_id)
                return

    def process_barcode(self, code, source='scan'):
        conn = None
        try:
            with db_lock:
                conn = sqlite3.connect(DB_PATH, timeout=30)
                cursor = conn.cursor()
                cursor.execute("SELECT id, name, category_id, size, quantity FROM items WHERE barcode = ?", (code,))
                result = cursor.fetchone()
        except sqlite3.Error as e:
            messagebox.showerror("Erreur BD", f"Erreur traitement code-barres : {e}")
            result = None
        finally:
            if conn:
                conn.close()
        new_item_id = None
        if result:
            id_, name, category_id, size_value, qty = result
            self.select_item_in_tree(id_)
            speak(f"Article {name}, taille {size_value}, quant. {qty}.")
            action = simpledialog.askstring(
                "Action",
                f"Article: {name} (Taille: {size_value})\nQuantité: {qty}\n"
                "Tapez 'ajouter x', 'retirer x', 'modifier' ou 'générer codebarre' :"
            )
            if action:
                tokens = action.split()
                cmd = tokens[0].lower()
                if cmd == 'ajouter' and len(tokens) == 2:
                    try:
                        delta = int(tokens[1])
                        if delta <= 0:
                            raise ValueError
                        update = adjust_item_quantity(
                            id_,
                            delta,
                            operator=self.current_user,
                            source=f'scan_{source}',
                            note="Ajout via scan",
                        )
                        if update:
                            new_qty, change, old_qty = update
                            speak(
                                f"Ajout de {change} unités sur {name}. Nouveau stock : {new_qty}."
                            )
                            self.status.set(
                                f"{change} unités ajoutées à '{name}' (scan)."
                            )
                        else:
                            messagebox.showerror("Stock", "Mise à jour impossible.")
                    except ValueError:
                        messagebox.showerror("Erreur", "Quantité invalide.")
                elif cmd == 'retirer' and len(tokens) == 2:
                    try:
                        delta = int(tokens[1])
                        if delta <= 0:
                            raise ValueError
                        if self.current_role != 'admin':
                            create_approval_request(
                                id_,
                                'stock_out',
                                delta,
                                "Retrait via scan",
                                self.current_user,
                                payload={'item_name': name, 'size': size_value},
                            )
                            messagebox.showinfo(
                                "Approbation requise",
                                "Une demande d'approbation a été créée pour ce retrait.",
                            )
                        else:
                            update = adjust_item_quantity(
                                id_,
                                -delta,
                                operator=self.current_user,
                                source=f'scan_{source}',
                                note="Retrait via scan",
                            )
                            if update:
                                new_qty, change, old_qty = update
                                change_abs = abs(change)
                                speak(
                                    f"Retrait de {change_abs} unités sur {name}. Stock : {new_qty}."
                                )
                                self.status.set(
                                    f"{change_abs} unités retirées de '{name}' (scan)."
                                )
                                if change == 0:
                                    messagebox.showinfo(
                                        "Stock",
                                        "Retrait supérieur au stock disponible : réduction au minimum.",
                                    )
                                if change < 0:
                                    self._maybe_show_low_stock_alert(
                                        id_,
                                        name,
                                        new_qty,
                                        old_qty,
                                        reorder_point,
                                    )
                            else:
                                messagebox.showerror("Stock", "Mise à jour impossible.")
                    except ValueError:
                        messagebox.showerror("Erreur", "Quantité invalide.")
                elif cmd == 'modifier':
                    self.select_item_in_tree(id_)
                    self.open_edit_selected()
                elif cmd == 'générer' and len(tokens) >= 2 and tokens[1] == 'codebarre':
                    save_barcode_image(code, article_name=name)
                    speak(f"Code-barres régénéré pour {name}.")
                else:
                    messagebox.showwarning("Attention", "Action non reconnue.")
            self.load_inventory()
            self.select_item_in_tree(id_)
        else:
            dialog = ItemDialog(
                self,
                "Créer Article (scan)",
                barcode=code,
            )
            if dialog.result:
                (
                    name,
                    barcode_value,
                    category_id,
                    size,
                    qty,
                    unit_cost,
                    reorder_point,
                    preferred_supplier_id,
                ) = dialog.result
                barcode_to_use = barcode_value or code
                new_item_id = self._create_item(
                    name,
                    barcode_to_use,
                    category_id,
                    size,
                    qty,
                    unit_cost,
                    reorder_point,
                    preferred_supplier_id,
                    source=f'scan_{source}',
                    log_note="Création via scan",
                )
                if new_item_id:
                    speak(
                        f"Nouvel article {name}, taille {size or 'N/A'}, stock initial {qty}."
                    )
                    self.status.set(f"Article '{name}' créé via scan.")
        self.load_inventory()
        if result:
            self.select_item_in_tree(id_)
        elif new_item_id:
            self.select_item_in_tree(new_item_id)

    def scan_camera(self):
        if not CAMERA_AVAILABLE:
            messagebox.showwarning("Indisponible", "Scan caméra non disponible.")
            return
        cap = cv2.VideoCapture(CAMERA_INDEX)
        if not cap.isOpened():
            messagebox.showerror("Erreur Caméra", "Impossible d'accéder à la caméra.")
            return
        found_code = None
        speak("Scanner activé. Présentez le code devant la caméra.")
        self.attributes('-disabled', True)
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            barcodes = pyzbar.decode(frame)
            for barcode_item in barcodes:
                barcode_data = barcode_item.data.decode('utf-8')
                found_code = barcode_data
                x, y, w, h = barcode_item.rect.left, barcode_item.rect.top, barcode_item.rect.width, barcode_item.rect.height
                cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)
                cv2.putText(frame, barcode_data, (x, y - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
                break
            cv2.imshow('Scanner Codes-Barres', frame)
            if found_code or cv2.waitKey(1) & 0xFF == ord('q'):
                break
            time.sleep(0.01)
        cap.release()
        cv2.destroyAllWindows()
        self.attributes('-disabled', False)
        if found_code:
            self._handle_scanned_code(found_code)
        else:
            speak("Aucun code-barres détecté.")

    def _handle_scanned_code(self, code: str) -> None:
        normalized = code.strip()
        if not normalized:
            return
        mode = self._determine_active_mode()
        if mode == "clothing":
            self._handle_clothing_scan(normalized)
        elif mode == "pharmacy":
            self._handle_pharmacy_scan(normalized)
        else:
            messagebox.showinfo(
                "Scan", "Sélectionnez l'onglet Habillement ou Pharmacie avant de scanner.", parent=self
            )

    def _handle_clothing_scan(self, code: str) -> None:
        if not hasattr(self, 'clothing_search_var'):
            messagebox.showinfo(
                "Scan Habillement",
                "Le module habillement n'est pas disponible.",
                parent=self,
            )
            return
        self.clothing_search_var.set(code)
        self.refresh_clothing_items()
        tree = getattr(self, 'clothing_tree', None)
        if tree is None:
            return
        target: Optional[str] = None
        for item_id in tree.get_children():
            values = tree.item(item_id).get('values', [])
            if len(values) > 1 and str(values[1]).strip() == code:
                target = item_id
                break
        if target is None:
            children = tree.get_children()
            if not children:
                messagebox.showinfo(
                    "Scan Habillement",
                    f"Aucun article trouvé pour le code {code}.",
                    parent=self,
                )
                self.status.set(f"Aucun article habillement pour {code}")
                return
            target = children[0]
        tree.selection_set(target)
        tree.focus(target)
        tree.see(target)
        self.status.set(f"Article habillement sélectionné pour {code}")

    def _handle_pharmacy_scan(self, code: str) -> None:
        if not hasattr(self, 'pharmacy_search_var'):
            messagebox.showinfo(
                "Scan Pharmacie",
                "Le module pharmacie n'est pas disponible.",
                parent=self,
            )
            return
        self.pharmacy_search_var.set(code)
        self.refresh_pharmacy_batches()
        tree = getattr(self, 'pharmacy_tree', None)
        if tree is None:
            return
        children = tree.get_children()
        if not children:
            messagebox.showinfo(
                "Scan Pharmacie",
                f"Aucun lot trouvé pour le code {code}.",
                parent=self,
            )
            self.status.set(f"Aucun lot pharmacie pour {code}")
            return
        target = children[0]
        tree.selection_set(target)
        tree.focus(target)
        tree.see(target)
        self.status.set(f"Lot pharmacie sélectionné pour {code}")

    def generate_barcode_dialog(self):
        article = simpledialog.askstring("Générer Code-Barres", "Entrez le nom de l'article :")
        if article:
            generate_barcode_for_item(article)

    def export_csv(self):
        file_path = filedialog.asksaveasfilename(defaultextension='.csv', filetypes=[('CSV', '*.csv')])
        if not file_path:
            return
        conn = None
        rows = []
        try:
            with db_lock:
                conn = sqlite3.connect(DB_PATH, timeout=30)
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT items.name, items.barcode, categories.name, suppliers.name, items.size, categories.note, items.quantity, items.last_updated "
                    "FROM items LEFT JOIN categories ON items.category_id = categories.id "
                    "LEFT JOIN suppliers ON suppliers.id = items.preferred_supplier_id"
                )
                rows = cursor.fetchall()
        except sqlite3.Error as e:
            self.log_user_action(
                "Échec d'export CSV (lecture BD) vers %s : %s" % (file_path, e),
                level=logging.ERROR,
            )
            messagebox.showerror("Erreur BD", f"Impossible d'exporter en CSV : {e}")
        finally:
            if conn:
                conn.close()
        try:
            export_rows_to_csv(
                file_path,
                ('Nom', 'Code-Barres', 'Catégorie', 'Fournisseur', 'Taille', 'Note', 'Quantité', 'Dernière MAJ'),
                rows,
            )
            messagebox.showinfo("Export CSV", f"Données exportées vers {file_path}")
            self.status.set(f"Exporté vers {os.path.basename(file_path)}")
            self.log_user_action(
                "Export CSV réalisé vers %s (%s ligne(s))." % (file_path, len(rows))
            )
        except Exception as e:
            self.log_user_action(
                "Échec d'export CSV (écriture fichier) vers %s : %s" % (file_path, e),
                level=logging.ERROR,
            )
            messagebox.showerror("Erreur Fichier", f"Impossible d'écrire le CSV : {e}")

    def report_low_stock(self):
        default_threshold = self.low_stock_threshold
        threshold = simpledialog.askinteger(
            "Seuil",
            f"Afficher articles avec quantité <= : (défaut {default_threshold})",
            minvalue=0
        )
        if threshold is None:
            threshold = default_threshold
        conn = None
        try:
            with db_lock:
                conn = sqlite3.connect(DB_PATH, timeout=30)
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT items.name, items.barcode, categories.name, items.size, categories.note, items.quantity "
                    "FROM items LEFT JOIN categories ON items.category_id = categories.id "
                    "WHERE items.quantity <= ?",
                    (threshold,)
                )
                results = cursor.fetchall()
        except sqlite3.Error as e:
            messagebox.showerror("Erreur BD", f"Impossible de générer le rapport : {e}")
            results = []
        finally:
            if conn:
                conn.close()
        report = '\n'.join(
            [
                f"{r[0]} (Barcode: {r[1]}, Catégorie: {r[2]}, Taille: {r[3]}, Note: {r[4] or ''}, Quantité: {r[5]})"
                for r in results
            ]
        ) or "Aucun article en dessous du seuil."
        messagebox.showinfo("Rapport Stock Faible", report)

    def generate_pdf_report(self):
        if not MATPLOTLIB_AVAILABLE:
            messagebox.showerror(
                "Rapport PDF",
                "Matplotlib est requis pour générer le rapport PDF. Installez la bibliothèque pour utiliser cette fonctionnalité.",
            )
            return
        file_path = filedialog.asksaveasfilename(
            defaultextension='.pdf',
            filetypes=[('PDF', '*.pdf')],
            title="Exporter rapport PDF",
            initialfile=f"rapport_stock_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf",
        )
        if not file_path:
            return

        try:
            with db_lock:
                conn = sqlite3.connect(DB_PATH, timeout=30)
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*), COALESCE(SUM(quantity), 0) FROM items")
                total_items, total_qty = cursor.fetchone()
                cursor.execute(
                    "SELECT COUNT(*) FROM items WHERE quantity <= ?",
                    (self.low_stock_threshold,)
                )
                low_stock_count = cursor.fetchone()[0]
                cursor.execute(
                    "SELECT items.name, COALESCE(categories.name, 'Sans catégorie'), items.quantity "
                    "FROM items LEFT JOIN categories ON items.category_id = categories.id "
                    "WHERE items.quantity <= ? "
                    "ORDER BY items.quantity ASC, items.name LIMIT 10",
                    (self.low_stock_threshold,)
                )
                low_stock_rows = cursor.fetchall()
                cursor.execute(
                    "SELECT COALESCE(categories.name, 'Sans catégorie'), COALESCE(SUM(items.quantity), 0) "
                    "FROM items LEFT JOIN categories ON items.category_id = categories.id "
                    "GROUP BY categories.name ORDER BY SUM(items.quantity) DESC"
                )
                category_rows = cursor.fetchall()
                cursor.execute(
                    "SELECT substr(created_at,1,10) AS jour, "
                    "SUM(CASE WHEN quantity_change > 0 THEN quantity_change ELSE 0 END) AS entrees, "
                    "SUM(CASE WHEN quantity_change < 0 THEN -quantity_change ELSE 0 END) AS sorties "
                    "FROM stock_movements WHERE substr(created_at,1,10) >= ? "
                    "GROUP BY jour ORDER BY jour",
                    ((datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d'),)
                )
                movement_timeline = cursor.fetchall()
                cursor.execute(
                    "SELECT sm.created_at, COALESCE(items.name, 'Article supprimé'), sm.movement_type, "
                    "sm.quantity_change, sm.source, IFNULL(sm.operator, '') "
                    "FROM stock_movements sm "
                    "LEFT JOIN items ON sm.item_id = items.id "
                    "ORDER BY sm.created_at DESC LIMIT 10"
                )
                recent_movements = cursor.fetchall()
        except sqlite3.Error as e:
            self.log_user_action(
                "Échec génération rapport PDF (lecture BD) vers %s : %s" % (file_path, e),
                level=logging.ERROR,
            )
            messagebox.showerror("Rapport PDF", f"Impossible de récupérer les données : {e}")
            return
        finally:
            if conn:
                conn.close()

        try:
            with PdfPages(file_path) as pdf:
                fig, ax = plt.subplots(figsize=(8.27, 11.69))  # A4 portrait
                ax.axis('off')
                ax.set_title('Rapport de stock', fontsize=18, fontweight='bold', pad=20)
                summary_lines = [
                    f"Date du rapport : {datetime.now().strftime('%d/%m/%Y %H:%M')}",
                    f"Articles distincts : {total_items}",
                    f"Quantité totale : {total_qty}",
                    f"Articles sous le seuil ({self.low_stock_threshold}) : {low_stock_count}",
                ]
                ax.text(0.05, 0.88, "\n".join(summary_lines), fontsize=12, va='top')

                if low_stock_rows:
                    table_data = [["Article", "Catégorie", "Quantité"]]
                    for row in low_stock_rows:
                        table_data.append([row[0], row[1], row[2] if row[2] is not None else 0])
                    table = ax.table(
                        cellText=table_data,
                        loc='upper left',
                        cellLoc='left',
                        bbox=[0.05, 0.45, 0.9, 0.35],
                    )
                    table.auto_set_font_size(False)
                    table.set_fontsize(10)
                    ax.text(0.05, 0.82, "Articles sous le seuil", fontsize=14, fontweight='bold')
                else:
                    ax.text(0.05, 0.75, "Aucun article sous le seuil configuré.", fontsize=12)

                if recent_movements:
                    movements_table = [["Date", "Article", "Type", "Δ", "Source", "Opérateur"]]
                    for created_at, item_name, movement_type, change, source, operator in recent_movements:
                        movements_table.append([
                            created_at.replace('T', ' '),
                            item_name,
                            movement_type,
                            change,
                            source,
                            operator or '-'
                        ])
                    table2 = ax.table(
                        cellText=movements_table,
                        loc='lower left',
                        cellLoc='left',
                        bbox=[0.05, 0.05, 0.9, 0.35],
                    )
                    table2.auto_set_font_size(False)
                    table2.set_fontsize(9)
                    ax.text(0.05, 0.42, "Mouvements récents", fontsize=14, fontweight='bold')
                else:
                    ax.text(0.05, 0.38, "Aucun mouvement enregistré.", fontsize=12)

                pdf.savefig(fig, bbox_inches='tight')
                plt.close(fig)

                if category_rows:
                    categories = [row[0] or 'Sans catégorie' for row in category_rows[:10]]
                    values = [row[1] or 0 for row in category_rows[:10]]
                    fig, ax = plt.subplots(figsize=(11.69, 8.27))  # A4 paysage
                    ax.barh(categories[::-1], values[::-1], color='#1976d2')
                    ax.set_xlabel('Quantité totale')
                    ax.set_title('Top catégories par stock disponible')
                    for index, value in enumerate(values[::-1]):
                        ax.text(value, index, f" {value}", va='center', fontsize=10)
                    pdf.savefig(fig, bbox_inches='tight')
                    plt.close(fig)

                if movement_timeline:
                    days = [row[0] for row in movement_timeline]
                    entries = [row[1] or 0 for row in movement_timeline]
                    exits = [row[2] or 0 for row in movement_timeline]
                    fig, ax = plt.subplots(figsize=(11.69, 8.27))
                    ax.plot(days, entries, marker='o', label='Entrées')
                    ax.plot(days, exits, marker='o', label='Sorties')
                    ax.set_title('Mouvements de stock - 30 derniers jours')
                    ax.set_xlabel('Date')
                    ax.set_ylabel('Quantités')
                    ax.legend()
                    ax.grid(True, linestyle='--', alpha=0.5)
                    plt.xticks(rotation=45, ha='right')
                    pdf.savefig(fig, bbox_inches='tight')
                    plt.close(fig)
                else:
                    fig, ax = plt.subplots(figsize=(11.69, 8.27))
                    ax.axis('off')
                    ax.text(0.5, 0.5, "Aucun mouvement enregistré sur les 30 derniers jours.",
                            ha='center', va='center', fontsize=14)
                    pdf.savefig(fig, bbox_inches='tight')
                    plt.close(fig)
        except Exception as e:
            self.log_user_action(
                "Échec génération rapport PDF vers %s : %s" % (file_path, e),
                level=logging.ERROR,
            )
            messagebox.showerror("Rapport PDF", f"Erreur lors de la génération du PDF : {e}")
            return

        messagebox.showinfo("Rapport PDF", f"Rapport généré : {file_path}")
        self.status.set(f"Rapport PDF exporté : {os.path.basename(file_path)}")
        self.log_user_action("Rapport PDF généré vers %s." % file_path)

    def show_about(self):
        messagebox.showinfo("À propos", "Gestion Stock Pro v1.0\n© 2025 Sebastien Cangemi")

    def configure_microphone(self):
        if not (ENABLE_VOICE and SR_LIB_AVAILABLE):
            messagebox.showwarning("Vocal", "Reconnaissance vocale non disponible.")
            return
        global MICROPHONE_INDEX
        idx = choose_microphone(self)
        if idx is not None:
            MICROPHONE_INDEX = idx
            config['Settings']['microphone_index'] = str(idx)
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                config.write(f)
            init_recognizer()
            mic_names = sr.Microphone.list_microphone_names()
            if 0 <= idx < len(mic_names):
                selected = mic_names[idx]
            else:
                selected = f"index {idx}"
            messagebox.showinfo("Micro", f"Micro sélectionné : {selected}")

    def open_config_dialog(self):
        dialog = ConfigDialog(self)
        if dialog.result:
            global CAMERA_INDEX, MICROPHONE_INDEX, TTS_TYPE, ACTIVE_TTS_DRIVER
            config['Settings']['db_path'] = dialog.result['db_path']
            config['Settings']['user_db_path'] = dialog.result['user_db_path']
            config['Settings']['barcode_dir'] = dialog.result['barcode_dir']
            config['Settings']['camera_index'] = str(dialog.result['camera_index'])
            microphone_index = dialog.result['microphone_index']
            config['Settings']['microphone_index'] = '' if microphone_index is None else str(microphone_index)
            config['Settings']['enable_voice'] = str(dialog.result['enable_voice']).lower()
            config['Settings']['enable_tts'] = str(dialog.result['enable_tts']).lower()
            config['Settings']['tts_type'] = dialog.result['tts_type']
            config['Settings']['enable_barcode_generation'] = str(dialog.result['enable_barcode_generation']).lower()
            config['Settings']['low_stock_threshold'] = str(dialog.result['low_stock_threshold'])
            config['Settings']['theme'] = dialog.result['theme']
            config['Settings']['font_size'] = str(dialog.result['font_size'])
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                config.write(f)
            CAMERA_INDEX = dialog.result['camera_index']
            MICROPHONE_INDEX = microphone_index
            TTS_TYPE = dialog.result['tts_type']
            ACTIVE_TTS_DRIVER = dialog.result['tts_type'] if dialog.result['enable_tts'] else None
            try:
                self.low_stock_threshold = int(dialog.result['low_stock_threshold'])
            except (TypeError, ValueError):
                self.low_stock_threshold = DEFAULT_LOW_STOCK_THRESHOLD
            self._theme_mode = dialog.result['theme']
            try:
                self._font_size = int(dialog.result['font_size'])
            except (TypeError, ValueError):
                self._font_size = 10
            self.current_palette = apply_theme(self, self._theme_mode, font_size=self._font_size)
            self._apply_tree_tag_palette()
            self.load_inventory()
            messagebox.showinfo("Paramètres", "Configuration enregistrée. Redémarrez pour certaines options.")

    def open_category_dialog(self):
        dialog = CategoryDialog(self)
        if dialog.result:
            self.load_inventory()

    def open_user_management(self):
        UserManagementDialog(self, self.current_user_id)

    def show_voice_help(self):
        help_text = (
            "Commandes vocales disponibles :\n"
            " • 'ajouter [nombre] [nom de l'article]'   → ajoute la quantité\n"
            " • 'retirer [nombre] [nom de l'article]'   → retire la quantité\n"
            " • 'quantité de [nom de l'article]'        → annonce la quantité\n"
            " • 'générer codebarre pour [nom de l'article]' → génère le code-barres\n"
            " • 'aide' ou 'aide vocale'                  → affiche cette aide\n"
            " • 'stop voice' ou 'arrête écoute'         → désactive la reconnaissance vocale\n"
        )
        messagebox.showinfo("Aide Vocale", help_text)
        try:
            speak("Voici la liste des commandes vocales disponibles : ")
            for line in help_text.split('\n'):
                if line.strip():
                    speak(line)
        except:
            pass

    def backup_database(self):
        default_name = f"backup_gestion_stock_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
        file_path = filedialog.asksaveasfilename(
            title="Sauvegarder bases de données",
            defaultextension=".zip",
            initialfile=default_name,
            filetypes=[("Archive ZIP", "*.zip"), ("Tous fichiers", "*.*")]
        )
        if not file_path:
            return
        try:
            with zipfile.ZipFile(file_path, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
                if os.path.exists(DB_PATH):
                    archive.write(DB_PATH, arcname=os.path.basename(DB_PATH))
                else:
                    raise FileNotFoundError(f"Base stock introuvable : {DB_PATH}")
                if os.path.exists(USER_DB_PATH):
                    archive.write(USER_DB_PATH, arcname=os.path.basename(USER_DB_PATH))
                else:
                    raise FileNotFoundError(f"Base utilisateurs introuvable : {USER_DB_PATH}")
        except Exception as e:
            self.log_user_action(
                "Échec de sauvegarde des bases vers %s : %s" % (file_path, e),
                level=logging.ERROR,
            )
            messagebox.showerror("Erreur Backup", f"Impossible de sauvegarder les bases : {e}")
            return
        messagebox.showinfo("Backup réussi", f"Bases sauvegardées vers : {file_path}")
        self.status.set(f"Backup : {os.path.basename(file_path)}")
        self.log_user_action("Sauvegarde des bases effectuée vers %s." % file_path)

    def logout(self):
        """
        Déconnecte l'utilisateur sans quitter l'application : ferme la fenêtre
        et relance le dialogue de connexion.
        """
        self.log_user_action("Déconnexion de l'application demandée.")
        self.save_column_widths()
        global voice_active
        voice_active = False
        self.destroy()
        root = tk.Tk()
        root.withdraw()
        login = LoginDialog(root)
        if not login.result:
            root.destroy()
            sys.exit(0)
        new_user = login.username
        new_role = login.role
        conn = None
        try:
            with db_lock:
                conn = sqlite3.connect(USER_DB_PATH, timeout=30)
                cursor = conn.cursor()
                cursor.execute("SELECT id FROM users WHERE username = ?", (new_user,))
                uid = cursor.fetchone()[0]
        except:
            uid = None
        finally:
            if conn:
                conn.close()
        root.destroy()
        allowed_modules = get_user_module_permissions(uid, role=new_role)
        app = StockApp(new_user, new_role, uid, allowed_modules=allowed_modules)
        app.mainloop()


class AlertManager:
    """Gère les alertes de stock faible et la génération automatique de propositions."""

    def __init__(self, app, threshold):
        self.app = app
        self.threshold = threshold
        self.running = True
        self.thread = threading.Thread(target=self._worker, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False

    def dispatch_low_stock_alert(self, item_id, item_name, quantity, threshold):
        if has_recent_alert(item_id, within_hours=6):
            return
        message = (
            f"Alerte stock faible pour {item_name} : {quantity} unité(s) restante(s) (seuil {threshold})."
        )
        record_stock_alert(item_id, message, channel='internal', alert_level='low')
        deficit = max(threshold - quantity, 1)
        create_suggested_purchase_order(
            item_id,
            deficit,
            created_by=getattr(self.app, 'current_user', 'system'),
        )
        if self.app and self.app.winfo_exists():
            self.app.after(0, lambda msg=message: self._update_status(msg))

    def _update_status(self, message):
        if hasattr(self.app, 'status'):
            try:
                self.app.status.set(message)
            except Exception:
                pass

    def _worker(self):
        while self.running:
            try:
                self.scan_low_stock()
            except Exception as exc:
                print(f"[AlertManager] Erreur: {exc}")
            for _ in range(60):
                if not self.running:
                    break
                time.sleep(1)

    def scan_low_stock(self):
        conn = None
        try:
            with db_lock:
                conn = sqlite3.connect(DB_PATH, timeout=30)
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT id, name, quantity, COALESCE(reorder_point, ?) as threshold
                    FROM items
                    WHERE quantity <= COALESCE(reorder_point, ?)
                    """,
                    (self.threshold, self.threshold),
                )
                rows = cursor.fetchall()
        except sqlite3.Error as e:
            print(f"[AlertManager] Erreur BD: {e}")
            rows = []
        finally:
            if conn:
                conn.close()

        for item_id, name, qty, threshold in rows:
            if not has_recent_alert(item_id, within_hours=24):
                self.dispatch_low_stock_alert(item_id, name, qty, threshold)


class SupplierFormDialog(tk.Toplevel):
    def __init__(self, parent, title, supplier=None):
        super().__init__(parent)
        self.title(title)
        self.resizable(False, False)
        self.result = None

        self.var_name = tk.StringVar(value=supplier[1] if supplier else '')
        self.var_contact = tk.StringVar(value=supplier[2] if supplier else '')
        self.var_email = tk.StringVar(value=supplier[3] if supplier else '')
        self.var_phone = tk.StringVar(value=supplier[4] if supplier else '')

        ttk.Label(self, text="Nom *:").grid(row=0, column=0, padx=10, pady=5, sticky=tk.W)
        ttk.Entry(self, textvariable=self.var_name, width=40).grid(row=0, column=1, padx=10, pady=5)

        ttk.Label(self, text="Contact :").grid(row=1, column=0, padx=10, pady=5, sticky=tk.W)
        ttk.Entry(self, textvariable=self.var_contact, width=40).grid(row=1, column=1, padx=10, pady=5)

        ttk.Label(self, text="Email :").grid(row=2, column=0, padx=10, pady=5, sticky=tk.W)
        ttk.Entry(self, textvariable=self.var_email, width=40).grid(row=2, column=1, padx=10, pady=5)

        ttk.Label(self, text="Téléphone :").grid(row=3, column=0, padx=10, pady=5, sticky=tk.W)
        ttk.Entry(self, textvariable=self.var_phone, width=40).grid(row=3, column=1, padx=10, pady=5)

        ttk.Label(self, text="Notes :").grid(row=4, column=0, padx=10, pady=5, sticky=tk.NW)
        self.text_notes = tk.Text(self, width=40, height=4)
        self.text_notes.grid(row=4, column=1, padx=10, pady=5)
        if supplier and supplier[5]:
            self.text_notes.insert('1.0', supplier[5])

        btn_frame = ttk.Frame(self)
        btn_frame.grid(row=5, column=0, columnspan=2, pady=10)
        ttk.Button(btn_frame, text="Enregistrer", command=self.on_ok).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Annuler", command=self.on_cancel).pack(side=tk.LEFT, padx=5)

        self.grab_set()
        self.wait_window(self)

    def on_ok(self):
        name = self.var_name.get().strip()
        if not name:
            messagebox.showerror("Fournisseur", "Le nom est obligatoire.", parent=self)
            return
        self.result = (
            name,
            self.var_contact.get().strip(),
            self.var_email.get().strip(),
            self.var_phone.get().strip(),
            self.text_notes.get('1.0', tk.END).strip(),
        )
        self.destroy()

    def on_cancel(self):
        self.destroy()


class SupplierManagementDialog(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.title("Fournisseurs")
        self.geometry("780x480")
        self.suppliers_cache: list[tuple] = []

        search_frame = ttk.Frame(self)
        search_frame.pack(fill=tk.X, padx=10, pady=(10, 0))
        ttk.Label(search_frame, text="Rechercher :").pack(side=tk.LEFT, padx=(0, 5))
        self.search_var = tk.StringVar()
        self.entry_search = ttk.Entry(search_frame, textvariable=self.search_var, width=30)
        self.entry_search.pack(side=tk.LEFT, padx=5)
        self.search_var.trace_add('write', lambda *_: self.refresh())
        ttk.Button(search_frame, text="Exporter CSV", command=self.export_suppliers).pack(side=tk.RIGHT, padx=5)

        columns = ("Nom", "Contact", "Email", "Téléphone", "Créé le")
        tree_frame = ttk.Frame(self)
        tree_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        self.tree = ttk.Treeview(tree_frame, columns=columns, show='headings', selectmode='browse')
        vsb = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.tree.yview)
        hsb = ttk.Scrollbar(tree_frame, orient=tk.HORIZONTAL, command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.tree.grid(row=0, column=0, sticky='nsew')
        vsb.grid(row=0, column=1, sticky='ns')
        hsb.grid(row=1, column=0, sticky='ew')
        tree_frame.columnconfigure(0, weight=1)
        tree_frame.rowconfigure(0, weight=1)
        for col in columns:
            self.tree.heading(col, text=col)
            width = 160 if col == "Nom" else 140
            self.tree.column(col, width=width, anchor=tk.W)
        self.tree.bind('<<TreeviewSelect>>', lambda *_: self.show_selected_details())
        self.tree.bind('<Double-1>', lambda *_: self.edit_supplier())

        detail_frame = ttk.LabelFrame(self, text="Détails du fournisseur")
        detail_frame.pack(fill=tk.X, padx=10, pady=(0, 10))
        self.detail_vars = {
            'contact': tk.StringVar(value=''),
            'email': tk.StringVar(value=''),
            'phone': tk.StringVar(value=''),
            'created_at': tk.StringVar(value=''),
        }
        info_fields = [
            ("Contact", 'contact'),
            ("Email", 'email'),
            ("Téléphone", 'phone'),
            ("Créé le", 'created_at'),
        ]
        for idx, (label, key) in enumerate(info_fields):
            ttk.Label(detail_frame, text=f"{label} :").grid(row=0, column=idx * 2, padx=5, pady=5, sticky=tk.W)
            ttk.Label(detail_frame, textvariable=self.detail_vars[key]).grid(row=0, column=idx * 2 + 1, padx=5, pady=5, sticky=tk.W)

        ttk.Label(detail_frame, text="Notes :").grid(row=1, column=0, padx=5, pady=5, sticky=tk.NW)
        self.note_text = tk.Text(detail_frame, height=4, width=80, state='disabled', wrap=tk.WORD)
        self.note_text.grid(row=1, column=1, columnspan=7, padx=5, pady=5, sticky=tk.EW)
        detail_frame.columnconfigure(1, weight=1)

        btn_frame = ttk.Frame(self)
        btn_frame.pack(fill=tk.X, padx=10, pady=(0, 10))
        ttk.Button(btn_frame, text="Ajouter", command=self.add_supplier).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Modifier", command=self.edit_supplier).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Supprimer", command=self.delete_supplier).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Copier email", command=self.copy_selected_email).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Copier téléphone", command=self.copy_selected_phone).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Ouvrir email", command=self.open_mail_client).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Fermer", command=self.destroy).pack(side=tk.RIGHT, padx=5)

        self.refresh()
        self.after(100, self.entry_search.focus_set)

    def refresh(self):
        selected = self.tree.selection()
        selected_id = selected[0] if selected else None
        for child in self.tree.get_children():
            self.tree.delete(child)
        search = self.search_var.get().strip()
        self.suppliers_cache = fetch_suppliers(search if search else None)
        for supplier in self.suppliers_cache:
            supplier_id, name, contact, email, phone, notes, created_at = supplier
            created_display = format_display_datetime(created_at)
            self.tree.insert(
                '',
                tk.END,
                iid=str(supplier_id),
                values=(name, contact or '', email or '', phone or '', created_display),
            )
        if selected_id and self.tree.exists(selected_id):
            self.tree.selection_set(selected_id)
            self.tree.focus(selected_id)
        elif self.tree.get_children():
            first = self.tree.get_children()[0]
            self.tree.selection_set(first)
            self.tree.focus(first)
        self.show_selected_details()

    def get_selected_supplier_id(self):
        selection = self.tree.selection()
        if not selection:
            return None
        return int(selection[0])

    def get_supplier_from_cache(self, supplier_id):
        return next((s for s in self.suppliers_cache if s[0] == supplier_id), None)

    def show_selected_details(self):
        supplier_id = self.get_selected_supplier_id()
        supplier = self.get_supplier_from_cache(supplier_id) if supplier_id else None
        for key in self.detail_vars:
            self.detail_vars[key].set('')
        self.note_text.configure(state='normal')
        self.note_text.delete('1.0', tk.END)
        self.note_text.configure(state='disabled')
        if not supplier:
            return
        _, name, contact, email, phone, notes, created_at = supplier
        self.detail_vars['contact'].set(contact or '')
        self.detail_vars['email'].set(email or '')
        self.detail_vars['phone'].set(phone or '')
        self.detail_vars['created_at'].set(format_display_datetime(created_at))
        if notes:
            self.note_text.configure(state='normal')
            self.note_text.insert('1.0', notes)
            self.note_text.configure(state='disabled')

    def add_supplier(self):
        dialog = SupplierFormDialog(self, "Ajouter un fournisseur")
        if dialog.result:
            name, contact, email, phone, notes = dialog.result
            result = save_supplier(name, contact, email, phone, notes)
            if result:
                self.refresh()
            else:
                messagebox.showerror("Fournisseurs", "Échec de l'enregistrement.", parent=self)

    def edit_supplier(self):
        supplier_id = self.get_selected_supplier_id()
        if supplier_id is None:
            messagebox.showwarning("Fournisseurs", "Sélectionnez un fournisseur.", parent=self)
            return
        supplier = self.get_supplier_from_cache(supplier_id)
        if not supplier:
            supplier = next((s for s in fetch_suppliers() if s[0] == supplier_id), None)
        if not supplier:
            messagebox.showerror("Fournisseurs", "Fournisseur introuvable.", parent=self)
            return
        dialog = SupplierFormDialog(self, "Modifier le fournisseur", supplier)
        if dialog.result:
            name, contact, email, phone, notes = dialog.result
            if save_supplier(name, contact, email, phone, notes, supplier_id=supplier_id):
                self.refresh()
            else:
                messagebox.showerror("Fournisseurs", "Impossible de mettre à jour le fournisseur.", parent=self)

    def delete_supplier(self):
        supplier_id = self.get_selected_supplier_id()
        if supplier_id is None:
            messagebox.showwarning("Fournisseurs", "Sélectionnez un fournisseur.", parent=self)
            return
        if messagebox.askyesno("Confirmation", "Supprimer ce fournisseur ?", parent=self):
            if delete_supplier(supplier_id):
                self.refresh()
            else:
                messagebox.showerror("Fournisseurs", "Suppression impossible.", parent=self)

    def copy_selected_email(self):
        supplier_id = self.get_selected_supplier_id()
        supplier = self.get_supplier_from_cache(supplier_id) if supplier_id else None
        email = supplier[3] if supplier else ''
        if email:
            self.clipboard_clear()
            self.clipboard_append(email)
            self.parent.status.set(f"Email copié : {email}") if hasattr(self.parent, 'status') else None
        else:
            messagebox.showinfo("Fournisseurs", "Aucun email à copier.", parent=self)

    def copy_selected_phone(self):
        supplier_id = self.get_selected_supplier_id()
        supplier = self.get_supplier_from_cache(supplier_id) if supplier_id else None
        phone = supplier[4] if supplier else ''
        if phone:
            self.clipboard_clear()
            self.clipboard_append(phone)
            self.parent.status.set(f"Téléphone copié : {phone}") if hasattr(self.parent, 'status') else None
        else:
            messagebox.showinfo("Fournisseurs", "Aucun téléphone à copier.", parent=self)

    def open_mail_client(self):
        supplier_id = self.get_selected_supplier_id()
        supplier = self.get_supplier_from_cache(supplier_id) if supplier_id else None
        email = supplier[3] if supplier else ''
        if email:
            webbrowser.open(f"mailto:{email}")
        else:
            messagebox.showinfo("Fournisseurs", "Aucune adresse email disponible.", parent=self)

    def export_suppliers(self):
        file_path = filedialog.asksaveasfilename(defaultextension='.csv', filetypes=[('CSV', '*.csv')])
        if not file_path:
            return
        rows = [
            (name, contact or '', email or '', phone or '', format_display_datetime(created_at), notes or '')
            for _, name, contact, email, phone, notes, created_at in self.suppliers_cache
        ]
        try:
            export_rows_to_csv(
                file_path,
                ('Nom', 'Contact', 'Email', 'Téléphone', 'Créé le', 'Notes'),
                rows,
            )
            messagebox.showinfo("Fournisseurs", f"Export réalisé vers {file_path}", parent=self)
        except Exception as exc:
            messagebox.showerror("Fournisseurs", f"Impossible d'exporter : {exc}", parent=self)


class PurchaseOrderEditor(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.title("Nouveau bon de commande")
        self.geometry("720x480")
        self.result = None
        self.lines = []

        ttk.Label(self, text="Fournisseur :").grid(row=0, column=0, padx=10, pady=5, sticky=tk.W)
        suppliers = fetch_suppliers()
        self.supplier_ids = [s[0] for s in suppliers]
        supplier_names = [s[1] for s in suppliers]
        self.supplier_combobox = ttk.Combobox(self, values=supplier_names, state='readonly', width=40)
        self.supplier_combobox.grid(row=0, column=1, padx=10, pady=5, sticky=tk.W)

        ttk.Label(self, text="Échéance (JJ/MM/AAAA) :").grid(row=1, column=0, padx=10, pady=5, sticky=tk.W)
        self.entry_due = ttk.Entry(self, width=20)
        self.entry_due.grid(row=1, column=1, padx=10, pady=5, sticky=tk.W)

        ttk.Label(self, text="Note :").grid(row=2, column=0, padx=10, pady=5, sticky=tk.NW)
        self.text_note = tk.Text(self, height=4, width=60)
        self.text_note.grid(row=2, column=1, padx=10, pady=5, sticky=tk.W)

        line_frame = ttk.LabelFrame(self, text="Lignes de commande")
        line_frame.grid(row=3, column=0, columnspan=2, padx=10, pady=10, sticky=tk.NSEW)
        self.grid_rowconfigure(3, weight=1)
        self.grid_columnconfigure(1, weight=1)

        cols = ("Article", "Quantité", "Coût unitaire")
        self.line_tree = ttk.Treeview(line_frame, columns=cols, show='headings')
        for col in cols:
            self.line_tree.heading(col, text=col)
            self.line_tree.column(col, anchor=tk.W, width=150)
        self.line_tree.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        add_frame = ttk.Frame(line_frame)
        add_frame.pack(fill=tk.X, padx=5, pady=5)

        ttk.Label(add_frame, text="Article :").grid(row=0, column=0, padx=5, pady=5)
        self.items_lookup = fetch_items_lookup()
        self.item_ids = [i[0] for i in self.items_lookup]
        item_names = [i[1] for i in self.items_lookup]
        self.item_combobox = ttk.Combobox(add_frame, values=item_names, state='readonly', width=30)
        self.item_combobox.grid(row=0, column=1, padx=5, pady=5)

        ttk.Label(add_frame, text="Quantité :").grid(row=0, column=2, padx=5, pady=5)
        self.spin_qty = tk.Spinbox(add_frame, from_=1, to=1000, width=6)
        self.spin_qty.grid(row=0, column=3, padx=5, pady=5)

        ttk.Label(add_frame, text="Coût (€) :").grid(row=0, column=4, padx=5, pady=5)
        self.entry_cost = ttk.Entry(add_frame, width=10)
        self.entry_cost.grid(row=0, column=5, padx=5, pady=5)

        ttk.Button(add_frame, text="Ajouter", command=self.add_line).grid(row=0, column=6, padx=5)
        ttk.Button(add_frame, text="Retirer", command=self.remove_line).grid(row=0, column=7, padx=5)

        btn_frame = ttk.Frame(self)
        btn_frame.grid(row=4, column=0, columnspan=2, pady=10)
        ttk.Button(btn_frame, text="Enregistrer", command=self.on_ok).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Annuler", command=self.on_cancel).pack(side=tk.LEFT, padx=5)

        self.grab_set()
        self.wait_window(self)

    def add_line(self):
        idx = self.item_combobox.current()
        if idx < 0:
            messagebox.showerror("Bon de commande", "Sélectionnez un article.", parent=self)
            return
        try:
            qty = int(self.spin_qty.get())
            if qty <= 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("Bon de commande", "Quantité invalide.", parent=self)
            return
        try:
            cost = float(self.entry_cost.get() or 0)
        except ValueError:
            messagebox.showerror("Bon de commande", "Coût invalide.", parent=self)
            return
        item_id = self.item_ids[idx]
        item_name = self.items_lookup[idx][1]
        self.lines.append({'item_id': item_id, 'item_name': item_name, 'quantity_ordered': qty, 'unit_cost': cost})
        self.line_tree.insert('', tk.END, values=(item_name, qty, f"{cost:.2f}"))

    def remove_line(self):
        selection = self.line_tree.selection()
        if not selection:
            return
        index = self.line_tree.index(selection[0])
        self.line_tree.delete(selection[0])
        if 0 <= index < len(self.lines):
            self.lines.pop(index)

    def on_ok(self):
        if not self.lines:
            messagebox.showerror("Bon de commande", "Ajoutez au moins une ligne.", parent=self)
            return
        supplier_index = self.supplier_combobox.current()
        supplier_id = self.supplier_ids[supplier_index] if supplier_index >= 0 else None
        expected_date = None
        raw_due = self.entry_due.get().strip()
        if raw_due:
            try:
                expected_date = parse_user_date(raw_due)
            except ValueError as exc:
                messagebox.showerror("Bon de commande", str(exc), parent=self)
                return
        self.result = {
            'supplier_id': supplier_id,
            'expected_date': expected_date,
            'note': self.text_note.get('1.0', tk.END).strip(),
            'lines': self.lines,
        }
        self.destroy()

    def on_cancel(self):
        self.destroy()


class PurchaseOrderReceiveDialog(tk.Toplevel):
    def __init__(self, parent, order_id, order_items):
        super().__init__(parent)
        self.title(f"Réception bon #{order_id}")
        self.result = None
        self.vars = []

        ttk.Label(self, text="Quantités à réceptionner").pack(padx=10, pady=10)
        form = ttk.Frame(self)
        form.pack(fill=tk.BOTH, expand=True, padx=10)

        for idx, (line_id, item_name, qty_ordered, qty_received, unit_cost, item_id) in enumerate(order_items):
            remaining = (qty_ordered or 0) - (qty_received or 0)
            remaining = max(remaining, 0)
            var = tk.IntVar(value=remaining)
            self.vars.append((item_id, var, remaining))
            ttk.Label(form, text=f"{item_name} (restant {remaining})").grid(row=idx, column=0, padx=5, pady=5, sticky=tk.W)
            tk.Spinbox(form, from_=0, to=max(remaining, 1000), textvariable=var, width=6).grid(row=idx, column=1, padx=5, pady=5)

        ttk.Label(self, text="Commentaire :").pack(anchor=tk.W, padx=10)
        self.note_text = tk.Text(self, height=3, width=50)
        self.note_text.pack(fill=tk.X, padx=10, pady=5)

        status_frame = ttk.Frame(self)
        status_frame.pack(fill=tk.X, padx=10, pady=5)
        ttk.Label(status_frame, text="Statut :").pack(side=tk.LEFT)
        self.status_var = tk.StringVar(value='RECEIVED')
        ttk.Combobox(status_frame, values=['RECEIVED', 'PARTIAL', 'CANCELLED'], textvariable=self.status_var, state='readonly', width=15).pack(side=tk.LEFT, padx=5)

        btn_frame = ttk.Frame(self)
        btn_frame.pack(pady=10)
        ttk.Button(btn_frame, text="Valider", command=self.on_ok).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Annuler", command=self.destroy).pack(side=tk.LEFT, padx=5)

        self.grab_set()
        self.wait_window(self)

    def on_ok(self):
        receipt_lines = {}
        for item_id, var, remaining in self.vars:
            qty = max(0, min(int(var.get()), remaining))
            if qty:
                receipt_lines[item_id] = qty
        status = self.status_var.get()
        note = self.note_text.get('1.0', tk.END).strip()
        if status == 'CANCELLED':
            if receipt_lines:
                messagebox.showerror(
                    "Bon de commande",
                    "Aucune réception ne peut être enregistrée pour un bon annulé.",
                    parent=self,
                )
                return
            if not note:
                messagebox.showerror(
                    "Bon de commande",
                    "Merci d'indiquer un motif d'annulation.",
                    parent=self,
                )
                return
        self.result = (status, receipt_lines, note)
        self.destroy()


class PurchaseOrderManagementDialog(tk.Toplevel):
    STATUS_FILTERS = {
        'Actifs': 'active',
        'Tous': None,
        'En attente': 'PENDING',
        'Partiels': 'PARTIAL',
        'Réceptionnés': 'RECEIVED',
        'Annulés': 'CANCELLED',
        'Suggérés': 'SUGGESTED',
    }
    STATUS_DISPLAY = {
        'PENDING': 'En attente',
        'PARTIAL': 'Partiel',
        'RECEIVED': 'Réceptionné',
        'CANCELLED': 'Annulé',
        'SUGGESTED': 'Suggéré',
    }

    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.title("Bons de commande")
        self.geometry("880x520")
        self.orders_cache: dict[int, dict] = {}

        filter_frame = ttk.Frame(self)
        filter_frame.pack(fill=tk.X, padx=10, pady=(10, 0))
        ttk.Label(filter_frame, text="Statut :").pack(side=tk.LEFT, padx=(0, 5))
        self.status_var = tk.StringVar(value='Actifs')
        self.status_combobox = ttk.Combobox(
            filter_frame,
            state='readonly',
            textvariable=self.status_var,
            values=list(self.STATUS_FILTERS.keys()),
            width=15,
        )
        self.status_combobox.pack(side=tk.LEFT, padx=5)
        self.status_combobox.bind('<<ComboboxSelected>>', lambda *_: self.refresh())

        ttk.Label(filter_frame, text="Rechercher :").pack(side=tk.LEFT, padx=(15, 5))
        self.search_var = tk.StringVar()
        self.search_entry = ttk.Entry(filter_frame, textvariable=self.search_var, width=30)
        self.search_entry.pack(side=tk.LEFT, padx=5)
        self.search_var.trace_add('write', lambda *_: self.refresh())

        ttk.Button(filter_frame, text="Exporter CSV", command=self.export_orders).pack(side=tk.RIGHT, padx=5)

        columns = ("ID", "Fournisseur", "Statut", "Création", "Échéance", "Réception", "Note")
        tree_frame = ttk.Frame(self)
        tree_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        self.tree = ttk.Treeview(tree_frame, columns=columns, show='headings', selectmode='browse')
        vsb = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.tree.yview)
        hsb = ttk.Scrollbar(tree_frame, orient=tk.HORIZONTAL, command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.tree.grid(row=0, column=0, sticky='nsew')
        vsb.grid(row=0, column=1, sticky='ns')
        hsb.grid(row=1, column=0, sticky='ew')
        tree_frame.columnconfigure(0, weight=1)
        tree_frame.rowconfigure(0, weight=1)
        for col in columns:
            self.tree.heading(col, text=col)
            width = 80 if col == 'ID' else 140
            if col == 'Note':
                width = 200
            self.tree.column(col, width=width, anchor=tk.W)
        self.tree.bind('<<TreeviewSelect>>', lambda *_: self.show_selected_order_details())

        detail_frame = ttk.LabelFrame(self, text="Détails du bon sélectionné")
        detail_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))
        info_frame = ttk.Frame(detail_frame)
        info_frame.pack(fill=tk.X, padx=5, pady=5)
        self.order_detail_vars = {
            'id': tk.StringVar(value=''),
            'supplier': tk.StringVar(value=''),
            'status': tk.StringVar(value=''),
            'created': tk.StringVar(value=''),
            'expected': tk.StringVar(value=''),
            'received': tk.StringVar(value=''),
            'created_by': tk.StringVar(value=''),
        }
        info_fields = [
            ("ID", 'id'),
            ("Fournisseur", 'supplier'),
            ("Statut", 'status'),
            ("Créé le", 'created'),
            ("Échéance", 'expected'),
            ("Réception", 'received'),
            ("Créé par", 'created_by'),
        ]
        for idx, (label, key) in enumerate(info_fields):
            row = idx // 3
            col = (idx % 3) * 2
            ttk.Label(info_frame, text=f"{label} :").grid(row=row, column=col, padx=5, pady=2, sticky=tk.W)
            ttk.Label(info_frame, textvariable=self.order_detail_vars[key]).grid(row=row, column=col + 1, padx=5, pady=2, sticky=tk.W)
        for col in range(6):
            info_frame.columnconfigure(col, weight=1)

        note_label = ttk.Label(detail_frame, text="Note :")
        note_label.pack(anchor=tk.W, padx=5)
        self.order_note_text = tk.Text(detail_frame, height=3, state='disabled', wrap=tk.WORD)
        self.order_note_text.pack(fill=tk.X, padx=5, pady=(0, 5))

        lines_frame = ttk.Frame(detail_frame)
        lines_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        line_columns = ("Article", "Commandé", "Reçu", "Restant", "Coût unitaire")
        self.line_tree = ttk.Treeview(lines_frame, columns=line_columns, show='headings', height=6)
        vsb_lines = ttk.Scrollbar(lines_frame, orient=tk.VERTICAL, command=self.line_tree.yview)
        hsb_lines = ttk.Scrollbar(lines_frame, orient=tk.HORIZONTAL, command=self.line_tree.xview)
        self.line_tree.configure(yscrollcommand=vsb_lines.set, xscrollcommand=hsb_lines.set)
        self.line_tree.grid(row=0, column=0, sticky='nsew')
        vsb_lines.grid(row=0, column=1, sticky='ns')
        hsb_lines.grid(row=1, column=0, sticky='ew')
        lines_frame.columnconfigure(0, weight=1)
        lines_frame.rowconfigure(0, weight=1)
        for col in line_columns:
            width = 180 if col == 'Article' else 110
            self.line_tree.heading(col, text=col)
            self.line_tree.column(col, width=width, anchor=tk.W)

        btn_frame = ttk.Frame(self)
        btn_frame.pack(fill=tk.X, padx=10, pady=(0, 10))
        ttk.Button(btn_frame, text="Créer", command=self.create_order).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Réceptionner", command=self.receive_order).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Annuler", command=self.cancel_order).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Rafraîchir", command=self.refresh).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Fermer", command=self.destroy).pack(side=tk.RIGHT, padx=5)

        self.refresh()

    def get_selected_order_id(self):
        selection = self.tree.selection()
        if not selection:
            return None
        return int(selection[0])

    def refresh(self):
        selected = self.tree.selection()
        selected_id = selected[0] if selected else None
        for child in self.tree.get_children():
            self.tree.delete(child)
        status_label = self.status_var.get()
        status_filter = self.STATUS_FILTERS.get(status_label, None)
        search = self.search_var.get().strip()
        orders = fetch_purchase_orders(status=status_filter, search=search if search else None)
        self.orders_cache.clear()
        for order in orders:
            order_id, created_at, status, expected_date, received_at, supplier_name, note, created_by = order
            display_status = self.STATUS_DISPLAY.get(status, status)
            self.orders_cache[order_id] = {
                'id': order_id,
                'created_at': created_at,
                'status': status,
                'expected_date': expected_date,
                'received_at': received_at,
                'supplier_name': supplier_name,
                'note': note,
                'created_by': created_by,
            }
            self.tree.insert(
                '',
                tk.END,
                iid=str(order_id),
                values=(
                    order_id,
                    supplier_name or 'Non défini',
                    display_status,
                    format_display_datetime(created_at),
                    format_display_date(expected_date),
                    format_display_datetime(received_at),
                    (note or '')[:60],
                ),
            )
        if selected_id and self.tree.exists(selected_id):
            self.tree.selection_set(selected_id)
            self.tree.focus(selected_id)
        elif self.tree.get_children():
            first = self.tree.get_children()[0]
            self.tree.selection_set(first)
            self.tree.focus(first)
        self.show_selected_order_details()

    def show_selected_order_details(self):
        order_id = self.get_selected_order_id()
        order = self.orders_cache.get(order_id) if order_id else None
        for key in self.order_detail_vars:
            self.order_detail_vars[key].set('')
        self.order_note_text.configure(state='normal')
        self.order_note_text.delete('1.0', tk.END)
        self.order_note_text.configure(state='disabled')
        for child in self.line_tree.get_children():
            self.line_tree.delete(child)
        if not order:
            return
        self.order_detail_vars['id'].set(str(order['id']))
        self.order_detail_vars['supplier'].set(order['supplier_name'] or 'Non défini')
        self.order_detail_vars['status'].set(self.STATUS_DISPLAY.get(order['status'], order['status']))
        self.order_detail_vars['created'].set(format_display_datetime(order['created_at']))
        self.order_detail_vars['expected'].set(format_display_date(order['expected_date']))
        self.order_detail_vars['received'].set(format_display_datetime(order['received_at']))
        self.order_detail_vars['created_by'].set(order['created_by'] or '')
        if order['note']:
            self.order_note_text.configure(state='normal')
            self.order_note_text.insert('1.0', order['note'])
            self.order_note_text.configure(state='disabled')
        self.load_order_lines(order['id'])

    def load_order_lines(self, order_id):
        items = fetch_purchase_order_items(order_id)
        for child in self.line_tree.get_children():
            self.line_tree.delete(child)
        for line_id, item_name, qty_ordered, qty_received, unit_cost, item_id in items:
            ordered = qty_ordered or 0
            received = qty_received or 0
            remaining = max(ordered - received, 0)
            cost_display = f"{unit_cost or 0:.2f}"
            self.line_tree.insert(
                '',
                tk.END,
                iid=str(line_id),
                values=(item_name, ordered, received, remaining, cost_display),
            )

    def create_order(self):
        editor = PurchaseOrderEditor(self)
        if not editor.result:
            return
        data = editor.result
        po_id = create_purchase_order(
            data['supplier_id'],
            data['expected_date'],
            data['note'],
            self.parent.current_user,
            data['lines'],
        )
        if po_id:
            messagebox.showinfo("Bon de commande", f"Bon #{po_id} créé.", parent=self)
            self.refresh()
            self.select_order(po_id)
        else:
            messagebox.showerror("Bon de commande", "Échec de la création.", parent=self)

    def receive_order(self):
        order_id = self.get_selected_order_id()
        if order_id is None:
            messagebox.showwarning("Bon de commande", "Sélectionnez un bon.", parent=self)
            return
        items = fetch_purchase_order_items(order_id)
        if not items:
            messagebox.showinfo("Bon de commande", "Aucune ligne à réceptionner.", parent=self)
            return
        dialog = PurchaseOrderReceiveDialog(self, order_id, items)
        if dialog.result:
            status, receipt_lines, note = dialog.result
            success = update_purchase_order_status(
                order_id,
                status,
                self.parent.current_user,
                receipt_lines,
                note,
            )
            if success:
                self.parent.load_inventory()
                self.refresh()
                self.select_order(order_id)
            else:
                messagebox.showerror(
                    "Bon de commande",
                    "La mise à jour du bon a échoué.",
                    parent=self,
                )

    def cancel_order(self):
        order_id = self.get_selected_order_id()
        if order_id is None:
            messagebox.showwarning("Bon de commande", "Sélectionnez un bon.", parent=self)
            return
        if not messagebox.askyesno("Confirmation", "Annuler ce bon de commande ?", parent=self):
            return
        note = simpledialog.askstring("Annulation", "Motif d'annulation :", parent=self)
        if note is None:
            return
        note = note.strip()
        if not note:
            messagebox.showerror(
                "Bon de commande",
                "Le motif d'annulation est obligatoire.",
                parent=self,
            )
            return
        if update_purchase_order_status(order_id, 'CANCELLED', self.parent.current_user, note=note):
            messagebox.showinfo(
                "Bon de commande",
                "Bon annulé avec succès.",
                parent=self,
            )
            self.refresh()
            self.select_order(order_id)
        else:
            messagebox.showerror("Bon de commande", "Impossible d'annuler ce bon.", parent=self)

    def select_order(self, order_id):
        if order_id is None:
            return
        if self.tree.exists(str(order_id)):
            self.tree.selection_set(str(order_id))
            self.tree.focus(str(order_id))
            self.tree.see(str(order_id))
            self.show_selected_order_details()

    def export_orders(self):
        file_path = filedialog.asksaveasfilename(defaultextension='.csv', filetypes=[('CSV', '*.csv')])
        if not file_path:
            return
        rows = []
        for order in self.orders_cache.values():
            rows.append(
                (
                    order['id'],
                    order['supplier_name'] or 'Non défini',
                    self.STATUS_DISPLAY.get(order['status'], order['status']),
                    format_display_datetime(order['created_at']),
                    format_display_date(order['expected_date']),
                    format_display_datetime(order['received_at']),
                    order['created_by'] or '',
                    order['note'] or '',
                )
            )
        try:
            export_rows_to_csv(
                file_path,
                ('ID', 'Fournisseur', 'Statut', 'Création', 'Échéance', 'Réception', 'Créé par', 'Note'),
                rows,
            )
            messagebox.showinfo("Bons de commande", f"Export réalisé vers {file_path}", parent=self)
        except Exception as exc:
            messagebox.showerror("Bons de commande", f"Impossible d'exporter : {exc}", parent=self)
class CollaboratorFormDialog(tk.Toplevel):
    def __init__(self, parent, title, collaborator=None):
        super().__init__(parent)
        self.title(title)
        self.resizable(False, False)
        self.result = None

        fields = [
            ("Nom complet *", 'full_name'),
            ("Service", 'department'),
            ("Fonction", 'job_title'),
            ("Email", 'email'),
            ("Téléphone", 'phone'),
            ("Date embauche", 'hire_date'),
        ]
        self.vars = {}
        for idx, (label, key) in enumerate(fields):
            ttk.Label(self, text=label).grid(row=idx, column=0, padx=10, pady=5, sticky=tk.W)
            value = collaborator[idx + 1] if collaborator else ''
            var = tk.StringVar(value=value or '')
            ttk.Entry(self, textvariable=var, width=40).grid(row=idx, column=1, padx=10, pady=5)
            self.vars[key] = var

        ttk.Label(self, text="Notes").grid(row=len(fields), column=0, padx=10, pady=5, sticky=tk.NW)
        self.text_notes = tk.Text(self, width=40, height=4)
        self.text_notes.grid(row=len(fields), column=1, padx=10, pady=5)
        if collaborator and collaborator[-1]:
            self.text_notes.insert('1.0', collaborator[-1])

        btn_frame = ttk.Frame(self)
        btn_frame.grid(row=len(fields) + 1, column=0, columnspan=2, pady=10)
        ttk.Button(btn_frame, text="Enregistrer", command=self.on_ok).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Annuler", command=self.destroy).pack(side=tk.LEFT, padx=5)

        self.grab_set()
        self.wait_window(self)

    def on_ok(self):
        full_name = self.vars['full_name'].get().strip()
        if not full_name:
            messagebox.showerror("Collaborateur", "Le nom est obligatoire.", parent=self)
            return
        self.result = {key: var.get().strip() for key, var in self.vars.items()}
        self.result['notes'] = self.text_notes.get('1.0', tk.END).strip()
        self.destroy()


class AssignGearDialog(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("Attribuer un équipement")
        self.result = None

        items = fetch_items_lookup(only_clothing=True)
        self.item_ids = [i[0] for i in items]
        item_names = [i[1] for i in items]

        ttk.Label(self, text="Article :").grid(row=0, column=0, padx=10, pady=5, sticky=tk.W)
        self.item_combobox = ttk.Combobox(self, values=item_names, state='readonly', width=35)
        self.item_combobox.grid(row=0, column=1, padx=10, pady=5)

        ttk.Label(self, text="Taille :").grid(row=1, column=0, padx=10, pady=5, sticky=tk.W)
        self.entry_size = ttk.Entry(self, width=20)
        self.entry_size.grid(row=1, column=1, padx=10, pady=5)

        ttk.Label(self, text="Quantité :").grid(row=2, column=0, padx=10, pady=5, sticky=tk.W)
        self.spin_qty = tk.Spinbox(self, from_=1, to=50, width=5)
        self.spin_qty.grid(row=2, column=1, padx=10, pady=5, sticky=tk.W)

        ttk.Label(self, text="Renouvellement (JJ/MM/AAAA) :").grid(row=3, column=0, padx=10, pady=5, sticky=tk.W)
        self.entry_due = ttk.Entry(self, width=20)
        self.entry_due.grid(row=3, column=1, padx=10, pady=5, sticky=tk.W)

        ttk.Label(self, text="Notes :").grid(row=4, column=0, padx=10, pady=5, sticky=tk.NW)
        self.text_notes = tk.Text(self, width=40, height=4)
        self.text_notes.grid(row=4, column=1, padx=10, pady=5)

        btn_frame = ttk.Frame(self)
        btn_frame.grid(row=5, column=0, columnspan=2, pady=10)
        ttk.Button(btn_frame, text="Attribuer", command=self.on_ok).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Annuler", command=self.destroy).pack(side=tk.LEFT, padx=5)

        self.grab_set()
        self.wait_window(self)

    def on_ok(self):
        idx = self.item_combobox.current()
        if idx < 0:
            messagebox.showerror("Dotation", "Sélectionnez un article.", parent=self)
            return
        try:
            qty = int(self.spin_qty.get())
            if qty <= 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("Dotation", "Quantité invalide.", parent=self)
            return
        self.result = {
            'item_id': self.item_ids[idx],
            'size': self.entry_size.get().strip(),
            'quantity': qty,
            'due_date': self.entry_due.get().strip() or None,
            'notes': self.text_notes.get('1.0', tk.END).strip(),
        }
        self.destroy()


class CollaboratorGearDialog(tk.Toplevel):
    STATUS_FILTERS = {
        'Actives': 'active',
        'Toutes': None,
        'Retournées': 'returned',
        'Perdues': 'lost',
        'Endommagées': 'damaged',
    }

    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.title("Dotations collaborateurs")
        self.geometry("960x520")
        self.collaborators_cache: list[tuple] = []
        self.current_gear_cache: list[tuple] = []

        filter_frame = ttk.Frame(self)
        filter_frame.pack(fill=tk.X, padx=10, pady=(10, 0))
        ttk.Label(filter_frame, text="Rechercher collaborateur :").pack(side=tk.LEFT, padx=(0, 5))
        self.collab_search_var = tk.StringVar()
        self.collab_search_entry = ttk.Entry(filter_frame, textvariable=self.collab_search_var, width=30)
        self.collab_search_entry.pack(side=tk.LEFT, padx=5)
        self.collab_search_var.trace_add('write', lambda *_: self.load_collaborators())

        ttk.Label(filter_frame, text="Filtre dotations :").pack(side=tk.LEFT, padx=(15, 5))
        self.status_filter_var = tk.StringVar(value='Actives')
        self.status_filter_combobox = ttk.Combobox(
            filter_frame,
            state='readonly',
            textvariable=self.status_filter_var,
            values=list(self.STATUS_FILTERS.keys()),
            width=18,
        )
        self.status_filter_combobox.pack(side=tk.LEFT, padx=5)
        self.status_filter_combobox.bind('<<ComboboxSelected>>', lambda *_: self.load_gear())

        ttk.Button(filter_frame, text="Exporter collaborateurs", command=self.export_collaborators).pack(side=tk.RIGHT, padx=5)

        main_frame = ttk.Frame(self)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        main_frame.columnconfigure(0, weight=1)
        main_frame.columnconfigure(1, weight=1)
        main_frame.rowconfigure(0, weight=1)

        # Collaborators panel
        collab_panel = ttk.Frame(main_frame)
        collab_panel.grid(row=0, column=0, sticky='nsew', padx=(0, 10))
        collab_columns = ("Nom", "Service", "Fonction")
        self.collab_tree = ttk.Treeview(collab_panel, columns=collab_columns, show='headings', height=12)
        collab_vsb = ttk.Scrollbar(collab_panel, orient=tk.VERTICAL, command=self.collab_tree.yview)
        self.collab_tree.configure(yscrollcommand=collab_vsb.set)
        self.collab_tree.grid(row=0, column=0, sticky='nsew')
        collab_vsb.grid(row=0, column=1, sticky='ns')
        collab_panel.columnconfigure(0, weight=1)
        collab_panel.rowconfigure(0, weight=1)
        for col in collab_columns:
            self.collab_tree.heading(col, text=col)
            width = 160 if col == "Nom" else 140
            self.collab_tree.column(col, width=width, anchor=tk.W)
        self.collab_tree.bind('<<TreeviewSelect>>', lambda *_: (self.show_selected_collaborator_details(), self.load_gear()))
        self.collab_tree.bind('<Double-1>', lambda *_: self.edit_collaborator())

        collab_detail = ttk.LabelFrame(collab_panel, text="Collaborateur")
        collab_detail.grid(row=1, column=0, columnspan=2, sticky='ew', pady=8)
        self.collab_detail_vars = {
            'department': tk.StringVar(value=''),
            'job': tk.StringVar(value=''),
            'email': tk.StringVar(value=''),
            'phone': tk.StringVar(value=''),
            'hire_date': tk.StringVar(value=''),
        }
        detail_fields = [
            ("Service", 'department'),
            ("Fonction", 'job'),
            ("Email", 'email'),
            ("Téléphone", 'phone'),
            ("Embauche", 'hire_date'),
        ]
        for idx, (label, key) in enumerate(detail_fields):
            ttk.Label(collab_detail, text=f"{label} :").grid(row=idx, column=0, padx=5, pady=2, sticky=tk.W)
            ttk.Label(collab_detail, textvariable=self.collab_detail_vars[key]).grid(row=idx, column=1, padx=5, pady=2, sticky=tk.W)
        ttk.Label(collab_detail, text="Notes :").grid(row=len(detail_fields), column=0, padx=5, pady=5, sticky=tk.NW)
        self.collab_notes_text = tk.Text(collab_detail, height=4, width=40, state='disabled', wrap=tk.WORD)
        self.collab_notes_text.grid(row=len(detail_fields), column=1, padx=5, pady=5, sticky=tk.EW)
        collab_detail.columnconfigure(1, weight=1)

        collab_btns = ttk.Frame(collab_panel)
        collab_btns.grid(row=2, column=0, columnspan=2, sticky='w', pady=(5, 0))
        ttk.Button(collab_btns, text="Ajouter", command=self.add_collaborator).pack(side=tk.LEFT, padx=5)
        ttk.Button(collab_btns, text="Modifier", command=self.edit_collaborator).pack(side=tk.LEFT, padx=5)
        ttk.Button(collab_btns, text="Supprimer", command=self.delete_collaborator).pack(side=tk.LEFT, padx=5)

        # Gear panel
        gear_panel = ttk.Frame(main_frame)
        gear_panel.grid(row=0, column=1, sticky='nsew')
        gear_columns = ("Article", "Taille", "Quantité", "Statut", "Échéance")
        self.gear_tree = ttk.Treeview(gear_panel, columns=gear_columns, show='headings', height=12)
        gear_vsb = ttk.Scrollbar(gear_panel, orient=tk.VERTICAL, command=self.gear_tree.yview)
        self.gear_tree.configure(yscrollcommand=gear_vsb.set)
        self.gear_tree.grid(row=0, column=0, sticky='nsew')
        if hasattr(self.parent, "_status_colors"):
            returned_bg, returned_fg = self.parent._status_colors("info")
            lost_bg, lost_fg = self.parent._status_colors("danger")
            damaged_bg, damaged_fg = self.parent._status_colors("warning")
            overdue_bg, overdue_fg = self.parent._status_colors("accent")
            self.gear_tree.tag_configure('gear_returned', background=returned_bg, foreground=returned_fg)
            self.gear_tree.tag_configure('gear_lost', background=lost_bg, foreground=lost_fg)
            self.gear_tree.tag_configure('gear_damaged', background=damaged_bg, foreground=damaged_fg)
            self.gear_tree.tag_configure('gear_overdue', background=overdue_bg, foreground=overdue_fg)
        else:
            self.gear_tree.tag_configure('gear_returned', background='#e0f7fa')
            self.gear_tree.tag_configure('gear_lost', background='#ffebee')
            self.gear_tree.tag_configure('gear_damaged', background='#fff3e0')
            self.gear_tree.tag_configure('gear_overdue', background='#fff8e1')
        gear_vsb.grid(row=0, column=1, sticky='ns')
        gear_panel.columnconfigure(0, weight=1)
        gear_panel.rowconfigure(0, weight=1)
        for col in gear_columns:
            width = 160 if col == "Article" else 110
            self.gear_tree.heading(col, text=col)
            self.gear_tree.column(col, width=width, anchor=tk.W)
        self.gear_tree.bind('<<TreeviewSelect>>', lambda *_: self.show_selected_gear_details())

        gear_detail = ttk.LabelFrame(gear_panel, text="Dotation")
        gear_detail.grid(row=1, column=0, columnspan=2, sticky='ew', pady=8)
        self.gear_detail_vars = {
            'item': tk.StringVar(value=''),
            'status': tk.StringVar(value=''),
            'quantity': tk.StringVar(value=''),
            'issued': tk.StringVar(value=''),
            'due': tk.StringVar(value=''),
            'returned': tk.StringVar(value=''),
        }
        gear_fields = [
            ("Article", 'item'),
            ("Statut", 'status'),
            ("Quantité", 'quantity'),
            ("Attribué", 'issued'),
            ("Échéance", 'due'),
            ("Retour", 'returned'),
        ]
        for idx, (label, key) in enumerate(gear_fields):
            ttk.Label(gear_detail, text=f"{label} :").grid(row=idx, column=0, padx=5, pady=2, sticky=tk.W)
            ttk.Label(gear_detail, textvariable=self.gear_detail_vars[key]).grid(row=idx, column=1, padx=5, pady=2, sticky=tk.W)
        ttk.Label(gear_detail, text="Notes :").grid(row=len(gear_fields), column=0, padx=5, pady=5, sticky=tk.NW)
        self.gear_notes_text = tk.Text(gear_detail, height=4, width=40, state='disabled', wrap=tk.WORD)
        self.gear_notes_text.grid(row=len(gear_fields), column=1, padx=5, pady=5, sticky=tk.EW)
        gear_detail.columnconfigure(1, weight=1)

        gear_btns = ttk.Frame(gear_panel)
        gear_btns.grid(row=2, column=0, columnspan=2, sticky='w', pady=(5, 0))
        ttk.Button(gear_btns, text="Attribuer équipement", command=self.assign_gear).pack(side=tk.LEFT, padx=5)
        ttk.Button(gear_btns, text="Marquer retour", command=self.return_gear).pack(side=tk.LEFT, padx=5)
        ttk.Button(gear_btns, text="Prolonger", command=self.extend_due_date).pack(side=tk.LEFT, padx=5)
        ttk.Button(gear_btns, text="Déclarer perdu", command=lambda: self.mark_gear_status('lost', restock=False)).pack(side=tk.LEFT, padx=5)
        ttk.Button(gear_btns, text="Déclarer endommagé", command=lambda: self.mark_gear_status('damaged', restock=False)).pack(side=tk.LEFT, padx=5)
        ttk.Button(gear_btns, text="Exporter dotations", command=self.export_assignments).pack(side=tk.LEFT, padx=5)

        ttk.Button(self, text="Fermer", command=self.destroy).pack(pady=5)

        self.load_collaborators()

    def load_collaborators(self):
        selected = self.collab_tree.selection()
        selected_id = selected[0] if selected else None
        for child in self.collab_tree.get_children():
            self.collab_tree.delete(child)
        search = self.collab_search_var.get().lower().strip()
        self.collaborators_cache = []
        for collab in fetch_collaborators():
            collab_id, full_name, department, job_title, email, phone, hire_date, notes = collab
            haystack = ' '.join(filter(None, [full_name, department, job_title, email, phone or '', hire_date or ''])).lower()
            if search and search not in haystack:
                continue
            self.collaborators_cache.append(collab)
            self.collab_tree.insert('', tk.END, iid=str(collab_id), values=(full_name, department or '', job_title or ''))
        if selected_id and self.collab_tree.exists(selected_id):
            self.collab_tree.selection_set(selected_id)
            self.collab_tree.focus(selected_id)
        elif self.collab_tree.get_children():
            first = self.collab_tree.get_children()[0]
            self.collab_tree.selection_set(first)
            self.collab_tree.focus(first)
        self.show_selected_collaborator_details()
        self.load_gear()

    def get_selected_collaborator(self):
        selection = self.collab_tree.selection()
        if not selection:
            return None
        return int(selection[0])

    def show_selected_collaborator_details(self):
        collab_id = self.get_selected_collaborator()
        collab = next((c for c in self.collaborators_cache if c[0] == collab_id), None)
        for key in self.collab_detail_vars:
            self.collab_detail_vars[key].set('')
        self.collab_notes_text.configure(state='normal')
        self.collab_notes_text.delete('1.0', tk.END)
        self.collab_notes_text.configure(state='disabled')
        if not collab:
            return
        _, full_name, department, job_title, email, phone, hire_date, notes = collab
        self.collab_detail_vars['department'].set(department or '')
        self.collab_detail_vars['job'].set(job_title or '')
        self.collab_detail_vars['email'].set(email or '')
        self.collab_detail_vars['phone'].set(phone or '')
        self.collab_detail_vars['hire_date'].set(hire_date or '')
        if notes:
            self.collab_notes_text.configure(state='normal')
            self.collab_notes_text.insert('1.0', notes)
            self.collab_notes_text.configure(state='disabled')

    def load_gear(self):
        for child in self.gear_tree.get_children():
            self.gear_tree.delete(child)
        collab_id = self.get_selected_collaborator()
        if not collab_id:
            self.current_gear_cache = []
            self.show_selected_gear_details()
            return
        status_label = self.status_filter_var.get()
        status_filter = self.STATUS_FILTERS.get(status_label, None)
        self.current_gear_cache = fetch_collaborator_gear(collab_id, status=status_filter)
        for gear in self.current_gear_cache:
            gear_id, collab_name, item_name, size, quantity, issued_at, due_date, status, returned_at, notes, item_id, collaborator_id = gear
            tags = []
            if status == 'returned':
                tags.append('gear_returned')
            elif status == 'lost':
                tags.append('gear_lost')
            elif status == 'damaged':
                tags.append('gear_damaged')
            if self._is_overdue(due_date, status):
                tags.append('gear_overdue')
            display_item = item_name if not size else f"{item_name} ({size})"
            self.gear_tree.insert(
                '',
                tk.END,
                iid=str(gear_id),
                values=(display_item, size or '', quantity, status.upper(), format_display_date(due_date)),
                tags=tags,
            )
        if self.gear_tree.get_children():
            self.gear_tree.selection_set(self.gear_tree.get_children()[0])
        self.show_selected_gear_details()

    def _is_overdue(self, due_date, status):
        if not due_date or status != 'issued':
            return False
        try:
            due = datetime.fromisoformat(due_date).date()
        except ValueError:
            try:
                due = datetime.strptime(due_date, '%d/%m/%Y').date()
            except ValueError:
                return False
        return due < datetime.now().date()

    def get_selected_gear(self):
        selection = self.gear_tree.selection()
        if not selection:
            return None
        gear_id = int(selection[0])
        return next((g for g in self.current_gear_cache if g[0] == gear_id), None)

    def show_selected_gear_details(self):
        gear = self.get_selected_gear()
        for key in self.gear_detail_vars:
            self.gear_detail_vars[key].set('')
        self.gear_notes_text.configure(state='normal')
        self.gear_notes_text.delete('1.0', tk.END)
        self.gear_notes_text.configure(state='disabled')
        if not gear:
            return
        gear_id, collab_name, item_name, size, quantity, issued_at, due_date, status, returned_at, notes, item_id, collaborator_id = gear
        display_item = item_name if not size else f"{item_name} ({size})"
        self.gear_detail_vars['item'].set(display_item)
        self.gear_detail_vars['status'].set(status.upper())
        self.gear_detail_vars['quantity'].set(str(quantity))
        self.gear_detail_vars['issued'].set(format_display_datetime(issued_at))
        self.gear_detail_vars['due'].set(format_display_date(due_date))
        self.gear_detail_vars['returned'].set(format_display_datetime(returned_at))
        if notes:
            self.gear_notes_text.configure(state='normal')
            self.gear_notes_text.insert('1.0', notes)
            self.gear_notes_text.configure(state='disabled')

    def add_collaborator(self):
        dialog = CollaboratorFormDialog(self, "Nouveau collaborateur")
        if dialog.result:
            data = dialog.result
            save_collaborator(
                data['full_name'],
                data['department'],
                data['job_title'],
                data['email'],
                data['phone'],
                data['hire_date'],
                data['notes'],
            )
            self.load_collaborators()

    def edit_collaborator(self):
        collab_id = self.get_selected_collaborator()
        if not collab_id:
            messagebox.showwarning("Collaborateurs", "Sélectionnez un collaborateur.", parent=self)
            return
        collab = next((c for c in fetch_collaborators() if c[0] == collab_id), None)
        if not collab:
            messagebox.showerror("Collaborateurs", "Collaborateur introuvable.", parent=self)
            return
        dialog = CollaboratorFormDialog(self, "Modifier collaborateur", collab)
        if dialog.result:
            data = dialog.result
            save_collaborator(
                data['full_name'],
                data['department'],
                data['job_title'],
                data['email'],
                data['phone'],
                data['hire_date'],
                data['notes'],
                collaborator_id=collab_id,
            )
            self.load_collaborators()

    def delete_collaborator(self):
        collab_id = self.get_selected_collaborator()
        if not collab_id:
            messagebox.showwarning("Collaborateurs", "Sélectionnez un collaborateur.", parent=self)
            return
        if messagebox.askyesno("Confirmation", "Supprimer ce collaborateur et ses dotations ?", parent=self):
            delete_collaborator(collab_id)
            self.load_collaborators()

    def assign_gear(self):
        collab_id = self.get_selected_collaborator()
        if not collab_id:
            messagebox.showwarning("Collaborateurs", "Sélectionnez un collaborateur.", parent=self)
            return
        dialog = AssignGearDialog(self)
        if dialog.result:
            data = dialog.result
            try:
                success = assign_collaborator_gear(
                    collab_id,
                    data['item_id'],
                    data['quantity'],
                    data['size'],
                    data['due_date'],
                    data['notes'],
                    operator=self.parent.current_user,
                )
            except ValueError as exc:
                messagebox.showerror("Dotations", str(exc), parent=self)
                return
            if success:
                self.parent.load_inventory()
                self.load_gear()
            else:
                messagebox.showerror("Dotations", "Impossible d'attribuer l'équipement.", parent=self)

    def return_gear(self):
        gear = self.get_selected_gear()
        if not gear:
            messagebox.showwarning("Collaborateurs", "Sélectionnez une dotation.", parent=self)
            return
        gear_id = gear[0]
        quantity = gear[4]
        if messagebox.askyesno("Confirmation", "Confirmer le retour de cet équipement ?", parent=self):
            close_collaborator_gear(gear_id, quantity, self.parent.current_user, status='returned')
            self.parent.load_inventory()
            self.load_gear()

    def extend_due_date(self):
        gear = self.get_selected_gear()
        if not gear:
            messagebox.showwarning("Collaborateurs", "Sélectionnez une dotation.", parent=self)
            return
        gear_id = gear[0]
        new_due = simpledialog.askstring("Prolongation", "Nouvelle échéance (JJ/MM/AAAA) :", parent=self)
        if new_due is None:
            return
        try:
            update_collaborator_gear_due_date(gear_id, new_due, self.parent.current_user)
            self.load_gear()
        except ValueError as exc:
            messagebox.showerror("Collaborateurs", str(exc), parent=self)

    def mark_gear_status(self, status, restock):
        gear = self.get_selected_gear()
        if not gear:
            messagebox.showwarning("Collaborateurs", "Sélectionnez une dotation.", parent=self)
            return
        gear_id = gear[0]
        quantity = gear[4]
        status_label = status.upper()
        if not messagebox.askyesno("Confirmation", f"Confirmer le statut {status_label} ?", parent=self):
            return
        note = simpledialog.askstring("Commentaire", "Ajouter un commentaire :", parent=self)
        close_collaborator_gear(gear_id, quantity, self.parent.current_user, response_note=note, status=status, restock=restock)
        if not restock:
            # Réduire le stock n'est pas ajusté lors des pertes/endommagés
            pass
        self.parent.load_inventory()
        self.load_gear()

    def export_collaborators(self):
        file_path = filedialog.asksaveasfilename(defaultextension='.csv', filetypes=[('CSV', '*.csv')])
        if not file_path:
            return
        rows = [
            (full_name, department or '', job_title or '', email or '', phone or '', hire_date or '', notes or '')
            for _, full_name, department, job_title, email, phone, hire_date, notes in self.collaborators_cache
        ]
        try:
            export_rows_to_csv(
                file_path,
                ('Nom', 'Service', 'Fonction', 'Email', 'Téléphone', 'Embauche', 'Notes'),
                rows,
            )
            messagebox.showinfo("Collaborateurs", f"Export réalisé vers {file_path}", parent=self)
        except Exception as exc:
            messagebox.showerror("Collaborateurs", f"Impossible d'exporter : {exc}", parent=self)

    def export_assignments(self):
        file_path = filedialog.asksaveasfilename(defaultextension='.csv', filetypes=[('CSV', '*.csv')])
        if not file_path:
            return
        rows = []
        for gear in self.current_gear_cache:
            gear_id, collab_name, item_name, size, quantity, issued_at, due_date, status, returned_at, notes, item_id, collaborator_id = gear
            display_item = item_name if not size else f"{item_name} ({size})"
            rows.append(
                (
                    collab_name,
                    display_item,
                    quantity,
                    status.upper(),
                    format_display_datetime(issued_at),
                    format_display_date(due_date),
                    format_display_datetime(returned_at),
                    notes or '',
                )
            )
        try:
            export_rows_to_csv(
                file_path,
                ('Collaborateur', 'Article', 'Quantité', 'Statut', 'Attribué', 'Échéance', 'Retour', 'Notes'),
                rows,
            )
            messagebox.showinfo("Dotations", f"Export réalisé vers {file_path}", parent=self)
        except Exception as exc:
            messagebox.showerror("Dotations", f"Impossible d'exporter : {exc}", parent=self)
class ApprovalQueueDialog(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.title("Demandes d'approbation")
        self.geometry("750x400")

        cols = ("ID", "Article", "Type", "Quantité", "Demandeur", "Commentaire")
        self.tree = ttk.Treeview(self, columns=cols, show='headings')
        for col in cols:
            self.tree.heading(col, text=col)
            width = 80 if col in ('ID', 'Quantité') else 140
            self.tree.column(col, width=width, anchor=tk.W)
        self.tree.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        btn_frame = ttk.Frame(self)
        btn_frame.pack(fill=tk.X, padx=10, pady=5)
        ttk.Button(btn_frame, text="Approuver", command=self.approve).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Refuser", command=self.reject).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Fermer", command=self.destroy).pack(side=tk.RIGHT, padx=5)

        self.refresh()

    def refresh(self):
        for child in self.tree.get_children():
            self.tree.delete(child)
        requests = fetch_approval_requests()
        for req in requests:
            approval_id, item_id, req_type, quantity, note, requested_by, created_at, status, payload = req
            item_name = get_item_name(item_id) if item_id else None
            if payload:
                try:
                    payload_data = json.loads(payload)
                    item_name = payload_data.get('item_name') or item_name
                except json.JSONDecodeError:
                    pass
            self.tree.insert('', tk.END, iid=approval_id, values=(approval_id, item_name or 'N/A', req_type, quantity or '', requested_by, note or ''))
        if not requests:
            self.parent.status.set("Aucune demande en attente")

    def get_selected_request(self):
        selection = self.tree.selection()
        if not selection:
            return None
        approval_id = int(selection[0])
        return next((r for r in fetch_approval_requests() if r[0] == approval_id), None)

    def approve(self):
        req = self.get_selected_request()
        if not req:
            messagebox.showwarning("Approbations", "Sélectionnez une demande.", parent=self)
            return
        approval_id, item_id, req_type, quantity, note, requested_by, created_at, status, payload = req
        response_note = simpledialog.askstring("Approbation", "Commentaire (optionnel) :", parent=self)
        success = False
        if req_type == 'stock_out' and item_id:
            result = adjust_item_quantity(
                item_id,
                -abs(quantity or 0),
                operator=self.parent.current_user,
                source='approval',
                note=f"Approbation demande {approval_id}",
            )
            if result:
                new_qty, change, old_qty = result
                reorder_point = self.parent._get_item_reorder_point(item_id)
                self.parent._maybe_show_low_stock_alert(item_id, get_item_name(item_id) or 'Article', new_qty, old_qty, reorder_point)
                success = True
        elif req_type == 'delete_item' and item_id:
            success = self._delete_item(item_id)
        else:
            success = True
        if success:
            update_approval_request(approval_id, 'approved', self.parent.current_user, response_note)
            self.parent.load_inventory()
            self.refresh()
        else:
            messagebox.showerror("Approbations", "Impossible de traiter la demande.", parent=self)

    def reject(self):
        req = self.get_selected_request()
        if not req:
            messagebox.showwarning("Approbations", "Sélectionnez une demande.", parent=self)
            return
        approval_id = req[0]
        response_note = simpledialog.askstring("Refus", "Motif du refus :", parent=self)
        update_approval_request(approval_id, 'rejected', self.parent.current_user, response_note)
        self.refresh()

    def _delete_item(self, item_id):
        conn = None
        try:
            with db_lock:
                conn = sqlite3.connect(DB_PATH, timeout=30)
                cursor = conn.cursor()
                cursor.execute("SELECT name, quantity, barcode FROM items WHERE id = ?", (item_id,))
                row = cursor.fetchone()
                if not row:
                    return False
                name, quantity, barcode_value = row
                if quantity:
                    log_stock_movement(
                        cursor,
                        item_id,
                        -quantity,
                        'OUT',
                        'approval_delete',
                        self.parent.current_user,
                        note='Suppression approuvée',
                    )
                cursor.execute("DELETE FROM items WHERE id = ?", (item_id,))
                conn.commit()
            if ENABLE_BARCODE_GENERATION and barcode_value:
                safe_name = name.replace(" ", "_")
                safe_name = "".join(ch for ch in safe_name if ch.isalnum() or ch == "_")
                filepath = os.path.join(BARCODE_DIR, f"{safe_name}.png")
                if os.path.exists(filepath):
                    os.remove(filepath)
            return True
        except sqlite3.Error as e:
            print(f"[DB Error] approval delete: {e}")
            return False
        finally:
            if conn:
                conn.close()


# ----------------------
# BOÎTE DE DIALOGUE CONFIGURATION
# ----------------------
class ConfigDialog(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("Configuration générale")
        self.resizable(False, False)
        self.result = None
        self._is_admin = getattr(parent, 'current_role', '') == 'admin'
        self._initial_paths = {
            'db_path': DB_PATH,
            'user_db_path': USER_DB_PATH,
            'barcode_dir': BARCODE_DIR,
        }

        var_db = tk.StringVar(value=DB_PATH)
        var_user_db = tk.StringVar(value=USER_DB_PATH)
        var_barcode = tk.StringVar(value=BARCODE_DIR)
        var_camera = tk.StringVar(value=str(CAMERA_INDEX))
        var_microphone = tk.StringVar(value="" if MICROPHONE_INDEX is None else str(MICROPHONE_INDEX))
        var_enable_voice = tk.BooleanVar(value=ENABLE_VOICE)
        var_enable_tts = tk.BooleanVar(value=ENABLE_TTS)
        var_enable_barcode = tk.BooleanVar(value=ENABLE_BARCODE_GENERATION)
        var_low_stock = tk.IntVar(value=DEFAULT_LOW_STOCK_THRESHOLD)
        var_theme = tk.StringVar(value=config.get('Settings', 'theme', fallback='dark'))
        var_font_size = tk.StringVar(value=str(config.getint('Settings', 'font_size', fallback=10)))
        tts_choices = {value: DEFAULT_TTS_TYPE_LABELS.get(value, value) for value in AVAILABLE_TTS_TYPES}
        if TTS_TYPE not in tts_choices:
            tts_choices[TTS_TYPE] = DEFAULT_TTS_TYPE_LABELS.get(TTS_TYPE, f"Personnalisé ({TTS_TYPE})")
        self.tts_label_to_value = {label: value for value, label in tts_choices.items()}
        initial_tts_label = tts_choices.get(TTS_TYPE, next(iter(tts_choices.values())))
        var_tts_type = tk.StringVar(value=initial_tts_label)

        ttk.Label(self, text="Chemin base stock :").grid(row=0, column=0, sticky=tk.W, padx=10, pady=5)
        entry_db = ttk.Entry(self, textvariable=var_db, width=40)
        entry_db.grid(row=0, column=1, padx=10, pady=5)

        ttk.Label(self, text="Chemin base utilisateurs :").grid(row=1, column=0, sticky=tk.W, padx=10, pady=5)
        entry_user_db = ttk.Entry(self, textvariable=var_user_db, width=40)
        entry_user_db.grid(row=1, column=1, padx=10, pady=5)

        ttk.Label(self, text="Répertoire codes-barres :").grid(row=2, column=0, sticky=tk.W, padx=10, pady=5)
        entry_barcode = ttk.Entry(self, textvariable=var_barcode, width=40)
        entry_barcode.grid(row=2, column=1, padx=10, pady=5)

        if not self._is_admin:
            for entry in (entry_db, entry_user_db, entry_barcode):
                entry.configure(state='readonly')

        ttk.Label(self, text="Index caméra :").grid(row=3, column=0, sticky=tk.W, padx=10, pady=5)
        entry_camera = ttk.Entry(self, textvariable=var_camera, width=5)
        entry_camera.grid(row=3, column=1, sticky=tk.W, padx=10, pady=5)

        ttk.Label(self, text="Index microphone (laisser vide pour défaut) :").grid(row=4, column=0, sticky=tk.W, padx=10, pady=5)
        entry_microphone = ttk.Entry(self, textvariable=var_microphone, width=5)
        entry_microphone.grid(row=4, column=1, sticky=tk.W, padx=10, pady=5)

        ttk.Label(self, text="Thème :").grid(row=5, column=0, sticky=tk.W, padx=10, pady=5)
        combo_theme = ttk.Combobox(
            self,
            textvariable=var_theme,
            values=("dark", "light"),
            state='readonly',
            width=15,
        )
        combo_theme.grid(row=5, column=1, padx=10, pady=5, sticky=tk.W)

        ttk.Label(self, text="Taille police :").grid(row=6, column=0, sticky=tk.W, padx=10, pady=5)
        combo_font = ttk.Combobox(
            self,
            textvariable=var_font_size,
            values=("10", "11", "12", "14"),
            state='readonly',
            width=15,
        )
        combo_font.grid(row=6, column=1, padx=10, pady=5, sticky=tk.W)

        chk_voice = ttk.Checkbutton(self, text="Activer reconnaissance vocale", variable=var_enable_voice)
        chk_voice.grid(row=7, column=0, columnspan=2, padx=10, pady=5, sticky=tk.W)
        chk_tts = ttk.Checkbutton(self, text="Activer synthèse vocale", variable=var_enable_tts)
        chk_tts.grid(row=8, column=0, columnspan=2, padx=10, pady=5, sticky=tk.W)

        ttk.Label(self, text="Type synthèse vocale :").grid(row=9, column=0, sticky=tk.W, padx=10, pady=5)
        combo_tts = ttk.Combobox(
            self,
            textvariable=var_tts_type,
            values=list(self.tts_label_to_value.keys()),
            state='readonly',
            width=40,
        )
        combo_tts.grid(row=9, column=1, padx=10, pady=5, sticky=tk.W)

        chk_barcode = ttk.Checkbutton(self, text="Activer génération de codes-barres", variable=var_enable_barcode)
        chk_barcode.grid(row=10, column=0, columnspan=2, padx=10, pady=5, sticky=tk.W)

        ttk.Label(self, text="Seuil stock faible :").grid(row=11, column=0, sticky=tk.W, padx=10, pady=5)
        entry_threshold = ttk.Entry(self, textvariable=var_low_stock, width=5)
        entry_threshold.grid(row=11, column=1, sticky=tk.W, padx=10, pady=5)

        def _update_tts_state(*_args):
            state = 'readonly' if var_enable_tts.get() else 'disabled'
            combo_tts.configure(state=state)

        var_enable_tts.trace_add('write', lambda *_: _update_tts_state())
        _update_tts_state()

        btn_frame = ttk.Frame(self)
        btn_frame.grid(row=12, column=0, columnspan=2, pady=10)
        ttk.Button(btn_frame, text="OK", command=lambda: self.on_ok(
            var_db, var_user_db, var_barcode, var_camera, var_microphone,
            var_enable_voice, var_enable_tts, var_tts_type, var_enable_barcode, var_low_stock,
            var_theme, var_font_size,
        )).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Annuler", command=self.on_cancel).pack(side=tk.LEFT, padx=5)

        self.grab_set()
        self.wait_window(self)

    def on_ok(
        self,
        var_db,
        var_user_db,
        var_barcode,
        var_camera,
        var_microphone,
        var_enable_voice,
        var_enable_tts,
        var_tts_type,
        var_enable_barcode,
        var_low_stock,
        var_theme,
        var_font_size,
    ):
        camera_raw = var_camera.get().strip()
        microphone_raw = var_microphone.get().strip()
        try:
            camera_index = int(camera_raw) if camera_raw else 0
        except ValueError:
            messagebox.showerror("Configuration", "Index caméra invalide.")
            return
        if microphone_raw:
            try:
                microphone_index = int(microphone_raw)
            except ValueError:
                messagebox.showerror("Configuration", "Index microphone invalide.")
                return
        else:
            microphone_index = None
        selected_label = var_tts_type.get()
        tts_type_value = self.tts_label_to_value.get(selected_label)
        if not tts_type_value:
            messagebox.showerror("Configuration", "Type de synthèse vocale invalide.")
            return
        theme_value = var_theme.get().strip().lower()
        if theme_value not in {"dark", "light"}:
            messagebox.showerror("Configuration", "Thème invalide.")
            return

        font_value = var_font_size.get().strip()
        if font_value not in {"10", "11", "12", "14"}:
            messagebox.showerror("Configuration", "Taille de police invalide.")
            return

        self.result = {
            'db_path': var_db.get().strip(),
            'user_db_path': var_user_db.get().strip(),
            'barcode_dir': var_barcode.get().strip(),
            'camera_index': camera_index,
            'microphone_index': microphone_index,
            'enable_voice': var_enable_voice.get(),
            'enable_tts': var_enable_tts.get(),
            'tts_type': tts_type_value,
            'enable_barcode_generation': var_enable_barcode.get(),
            'low_stock_threshold': var_low_stock.get(),
            'theme': theme_value,
            'font_size': font_value,
        }
        if not self._is_admin:
            for key, value in self._initial_paths.items():
                self.result[key] = value
        self.destroy()

    def on_cancel(self):
        self.destroy()

# ----------------------
# BOÎTE DE DIALOGUE GESTION CATÉGORIES
# ----------------------

class CategoryDialog(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("Gérer Catégories")
        self.resizable(False, False)
        self.result = None

        self.categories: list[tuple[int, str]] = []
        self.current_category_id: Optional[int] = None

        self.category_list = tk.Listbox(self, height=8, width=30)
        self.category_list.grid(row=0, column=0, columnspan=2, padx=10, pady=5, sticky=tk.N)
        self.category_list.bind('<<ListboxSelect>>', self.on_category_select)
        palette = getattr(parent, "current_palette", PALETTE)
        theme_mode = getattr(parent, "_theme_mode", "dark")
        _apply_listbox_palette(self.category_list, palette, theme=theme_mode)

        ttk.Label(self, text="Nouvelle catégorie :").grid(row=1, column=0, sticky=tk.W, padx=10, pady=5)
        self.new_category_var = tk.StringVar()
        entry_new = ttk.Entry(self, textvariable=self.new_category_var, width=20)
        entry_new.grid(row=1, column=1, padx=10, pady=5, sticky=tk.W)

        ttk.Label(self, text="Note :").grid(row=2, column=0, sticky=tk.W, padx=10, pady=5)
        self.new_category_note_var = tk.StringVar()
        ttk.Entry(self, textvariable=self.new_category_note_var, width=20).grid(
            row=2, column=1, padx=10, pady=5, sticky=tk.W
        )

        ttk.Label(self, text="Tailles (séparées par une virgule) :").grid(
            row=3, column=0, padx=10, pady=5, sticky=tk.W
        )
        self.new_category_sizes_var = tk.StringVar()
        ttk.Entry(self, textvariable=self.new_category_sizes_var, width=20).grid(
            row=3, column=1, padx=10, pady=5, sticky=tk.W
        )

        btn_add = ttk.Button(self, text="Ajouter", command=self.add_category)
        btn_add.grid(row=4, column=0, padx=10, pady=5, sticky=tk.W)
        btn_delete = ttk.Button(self, text="Supprimer", command=self.delete_category)
        btn_delete.grid(row=4, column=1, padx=10, pady=5, sticky=tk.W)

        btn_close = ttk.Button(self, text="Fermer", command=self.on_close)
        btn_close.grid(row=5, column=0, columnspan=2, pady=10)

        details_frame = ttk.LabelFrame(self, text="Détails catégorie")
        details_frame.grid(row=0, column=2, rowspan=6, padx=10, pady=5, sticky=tk.N)

        ttk.Label(details_frame, text="Note :").grid(row=0, column=0, padx=5, pady=5, sticky=tk.W)
        self.note_var = tk.StringVar()
        self.note_entry = ttk.Entry(details_frame, textvariable=self.note_var, width=28)
        self.note_entry.grid(row=0, column=1, padx=5, pady=5, sticky=tk.W)
        self.btn_save_note = ttk.Button(details_frame, text="Enregistrer", command=self.save_note)
        self.btn_save_note.grid(row=0, column=2, padx=5, pady=5)

        ttk.Label(details_frame, text="Tailles disponibles :").grid(
            row=1, column=0, columnspan=3, padx=5, pady=(10, 2), sticky=tk.W
        )
        self.size_list = tk.Listbox(details_frame, height=6, width=28)
        self.size_list.grid(row=2, column=0, columnspan=3, padx=5, sticky=tk.W)
        _apply_listbox_palette(self.size_list, palette, theme=theme_mode)

        size_controls = ttk.Frame(details_frame)
        size_controls.grid(row=3, column=0, columnspan=3, padx=5, pady=5, sticky=tk.W)
        self.new_size_var = tk.StringVar()
        self.size_entry = ttk.Entry(size_controls, textvariable=self.new_size_var, width=18)
        self.size_entry.grid(row=0, column=0, padx=5)
        self.btn_add_size = ttk.Button(size_controls, text="Ajouter", command=self.add_size)
        self.btn_add_size.grid(row=0, column=1, padx=5)
        self.btn_delete_size = ttk.Button(size_controls, text="Supprimer", command=self.delete_size)
        self.btn_delete_size.grid(row=0, column=2, padx=5)

        self.load_categories()
        self._set_details_state(False)

        self.grab_set()
        self.wait_window(self)

    def load_categories(self):
        self.category_list.delete(0, tk.END)
        self.categories = []
        conn = None
        try:
            with db_lock:
                conn = sqlite3.connect(DB_PATH, timeout=30)
                cursor = conn.cursor()
                cursor.execute("SELECT id, name FROM categories ORDER BY name")
                rows = cursor.fetchall()
        except sqlite3.Error as e:
            messagebox.showerror("Erreur BD", f"Impossible de charger catégories : {e}")
            rows = []
        finally:
            if conn:
                conn.close()
        for row in rows:
            self.categories.append((row[0], row[1]))
            self.category_list.insert(tk.END, row[1])
        self._set_details_state(False)

    def add_category(self):
        name = self.new_category_var.get().strip()
        if not name:
            messagebox.showerror("Erreur", "Nom de catégorie vide.")
            return
        note = self.new_category_note_var.get().strip()
        sizes_raw = self.new_category_sizes_var.get().strip()
        sizes = [s.strip() for s in sizes_raw.split(',') if s.strip()]
        conn = None
        try:
            with db_lock:
                conn = sqlite3.connect(DB_PATH, timeout=30)
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT INTO categories (name, note) VALUES (?, ?)",
                    (name, note if note else None),
                )
                category_id = cursor.lastrowid
                if sizes:
                    cursor.executemany(
                        "INSERT OR IGNORE INTO category_sizes (category_id, size_label) VALUES (?, ?)",
                        [(category_id, size) for size in sizes],
                    )
                conn.commit()
        except sqlite3.IntegrityError:
            messagebox.showerror("Erreur", "Catégorie existe déjà.")
        except sqlite3.Error as e:
            messagebox.showerror("Erreur BD", f"Impossible d'ajouter catégorie : {e}")
        finally:
            if conn:
                conn.close()
        self.new_category_var.set("")
        self.new_category_note_var.set("")
        self.new_category_sizes_var.set("")
        self.load_categories()
        for idx, (_, cat_name) in enumerate(self.categories):
            if cat_name == name:
                self.category_list.selection_clear(0, tk.END)
                self.category_list.selection_set(idx)
                self.category_list.event_generate('<<ListboxSelect>>')
                break
        self.result = True

    def delete_category(self):
        selection = self.category_list.curselection()
        if not selection:
            messagebox.showwarning("Attention", "Aucune catégorie sélectionnée.")
            return
        category_id, name = self.categories[selection[0]]
        conn = None
        try:
            with db_lock:
                conn = sqlite3.connect(DB_PATH, timeout=30)
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM items WHERE category_id = ?", (category_id,))
                count = cursor.fetchone()[0]
                if count > 0:
                    messagebox.showerror("Erreur", "Articles utilisent cette catégorie.")
                    return
                cursor.execute("DELETE FROM category_sizes WHERE category_id = ?", (category_id,))
                cursor.execute("DELETE FROM categories WHERE id = ?", (category_id,))
                conn.commit()
        except sqlite3.Error as e:
            messagebox.showerror("Erreur BD", f"Impossible de supprimer catégorie : {e}")
        finally:
            if conn:
                conn.close()
        self.load_categories()
        self.result = True

    def on_category_select(self, _event=None):
        selection = self.category_list.curselection()
        if not selection:
            self.current_category_id = None
            self._set_details_state(False)
            return
        idx = selection[0]
        self.current_category_id = self.categories[idx][0]
        self._set_details_state(True)
        self._populate_category_details(self.current_category_id)

    def _populate_category_details(self, category_id: int) -> None:
        note = ''
        sizes: list[str] = []
        conn = None
        try:
            with db_lock:
                conn = sqlite3.connect(DB_PATH, timeout=30)
                cursor = conn.cursor()
                cursor.execute("SELECT note FROM categories WHERE id = ?", (category_id,))
                row = cursor.fetchone()
                if row and row[0]:
                    note = row[0]
                cursor.execute(
                    "SELECT size_label FROM category_sizes WHERE category_id = ? ORDER BY size_label COLLATE NOCASE",
                    (category_id,),
                )
                sizes = [r[0] for r in cursor.fetchall()]
        except sqlite3.Error as e:
            messagebox.showerror("Erreur BD", f"Impossible de charger la catégorie : {e}")
        finally:
            if conn:
                conn.close()
        self.note_var.set(note)
        self.size_list.delete(0, tk.END)
        for size in sizes:
            self.size_list.insert(tk.END, size)

    def _set_details_state(self, enabled: bool) -> None:
        state = 'normal' if enabled else 'disabled'
        self.note_entry.configure(state=state)
        self.btn_save_note.configure(state=state)
        self.size_entry.configure(state=state)
        self.btn_add_size.configure(state=state)
        self.btn_delete_size.configure(state=state)
        if enabled:
            self.size_list.configure(state='normal')
        else:
            self.note_var.set('')
            self.new_size_var.set('')
            self.size_list.configure(state='disabled')
            self.size_list.delete(0, tk.END)

    def save_note(self):
        if self.current_category_id is None:
            return
        note = self.note_var.get().strip()
        conn = None
        try:
            with db_lock:
                conn = sqlite3.connect(DB_PATH, timeout=30)
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE categories SET note = ? WHERE id = ?",
                    (note if note else None, self.current_category_id),
                )
                conn.commit()
        except sqlite3.Error as e:
            messagebox.showerror("Erreur BD", f"Impossible d'enregistrer la note : {e}")
        finally:
            if conn:
                conn.close()

    def add_size(self):
        if self.current_category_id is None:
            return
        size_label = self.new_size_var.get().strip()
        if not size_label:
            messagebox.showerror("Erreur", "Veuillez saisir une taille.")
            return
        conn = None
        try:
            with db_lock:
                conn = sqlite3.connect(DB_PATH, timeout=30)
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT OR IGNORE INTO category_sizes (category_id, size_label) VALUES (?, ?)",
                    (self.current_category_id, size_label),
                )
                conn.commit()
        except sqlite3.Error as e:
            messagebox.showerror("Erreur BD", f"Impossible d'ajouter la taille : {e}")
        finally:
            if conn:
                conn.close()
        self.new_size_var.set('')
        self._populate_category_details(self.current_category_id)

    def delete_size(self):
        if self.current_category_id is None:
            return
        selection = self.size_list.curselection()
        if not selection:
            messagebox.showwarning("Attention", "Aucune taille sélectionnée.")
            return
        size_label = self.size_list.get(selection[0])
        conn = None
        try:
            with db_lock:
                conn = sqlite3.connect(DB_PATH, timeout=30)
                cursor = conn.cursor()
                cursor.execute(
                    "DELETE FROM category_sizes WHERE category_id = ? AND size_label = ?",
                    (self.current_category_id, size_label),
                )
                conn.commit()
        except sqlite3.Error as e:
            messagebox.showerror("Erreur BD", f"Impossible de supprimer la taille : {e}")
        finally:
            if conn:
                conn.close()
        self._populate_category_details(self.current_category_id)

    def on_close(self):
        self.destroy()

# ------------------------------
# BOÎTE DE SÉLECTION DE CATÉGORIE
# ------------------------------
class CategorySelectionDialog(tk.Toplevel):
    def __init__(self, parent, title):
        super().__init__(parent)
        self.title(title)
        self.resizable(False, False)
        self.result = None

        ttk.Label(self, text="Sélectionner une catégorie :").grid(row=0, column=0, padx=10, pady=5, sticky=tk.W)
        self.cat_combobox = ttk.Combobox(self, state='readonly', width=30)
        self.cat_combobox.grid(row=0, column=1, padx=10, pady=5)
        self.load_categories()

        btn_frame = ttk.Frame(self)
        btn_frame.grid(row=1, column=0, columnspan=2, pady=10)
        ttk.Button(btn_frame, text="OK", command=self.on_ok).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Annuler", command=self.on_cancel).pack(side=tk.LEFT, padx=5)

        self.grab_set()
        self.wait_window(self)

    def load_categories(self):
        conn = None
        try:
            with db_lock:
                conn = sqlite3.connect(DB_PATH, timeout=30)
                cursor = conn.cursor()
                cursor.execute("SELECT id, name FROM categories ORDER BY name")
                rows = cursor.fetchall()
        except sqlite3.Error:
            rows = []
        finally:
            if conn:
                conn.close()
        self.category_ids = [r[0] for r in rows]
        self.cat_combobox['values'] = [r[1] for r in rows]
        if rows:
            self.cat_combobox.current(0)

    def on_ok(self):
        idx = self.cat_combobox.current()
        if idx >= 0:
            self.result = self.category_ids[idx]
        self.destroy()

    def on_cancel(self):
        self.destroy()

# --------------------
# DIALOGUE D'ARTICLE
# --------------------
class ItemDialog(tk.Toplevel):
    def __init__(
        self,
        parent,
        title,
        name='',
        barcode='',
        category_id=None,
        size='',
        quantity=0,
        unit_cost=0.0,
        reorder_point=None,
        preferred_supplier_id=None,
    ):
        super().__init__(parent)
        self.title(title)
        self.resizable(False, False)
        self.result = None

        self.var_name = tk.StringVar(value=name)
        self.var_barcode = tk.StringVar(value=barcode)
        self.var_quantity = tk.IntVar(value=quantity)
        self.var_size = tk.StringVar(value=size)
        self.var_unit_cost = tk.DoubleVar(value=unit_cost if unit_cost is not None else 0.0)
        self.var_reorder_point = tk.StringVar(
            value='' if reorder_point is None else str(reorder_point)
        )
        self.var_supplier_id = tk.IntVar(value=preferred_supplier_id if preferred_supplier_id else -1)

        ttk.Label(self, text="Nom :").grid(row=0, column=0, padx=10, pady=5, sticky=tk.W)
        self.entry_name = ttk.Entry(self, textvariable=self.var_name, width=30)
        self.entry_name.grid(row=0, column=1, padx=10, pady=5)

        ttk.Label(self, text="Code-Barres :").grid(row=1, column=0, padx=10, pady=5, sticky=tk.W)
        self.entry_barcode = ttk.Entry(self, textvariable=self.var_barcode, width=30)
        self.entry_barcode.grid(row=1, column=1, padx=10, pady=5)

        ttk.Label(self, text="Catégorie :").grid(row=2, column=0, padx=10, pady=5, sticky=tk.W)
        self.cat_combobox = ttk.Combobox(self, state='readonly', width=28)
        self.cat_combobox.grid(row=2, column=1, padx=10, pady=5)
        self.load_categories()
        if category_id is not None:
            try:
                idx = self.category_ids.index(category_id)
                self.cat_combobox.current(idx)
            except ValueError:
                self.cat_combobox.set('')
        else:
            self.cat_combobox.set('')
        self.cat_combobox.bind("<<ComboboxSelected>>", lambda e: self.update_size_options())

        ttk.Button(self, text="Nouvelle Cat.", command=self.add_category_inline).grid(row=2, column=2, padx=5)

        ttk.Label(self, text="Taille :").grid(row=3, column=0, padx=10, pady=5, sticky=tk.W)
        self.size_combobox = ttk.Combobox(self, state='readonly', textvariable=self.var_size, width=28)
        self.size_combobox.grid(row=3, column=1, padx=10, pady=5)
        self.update_size_options()

        ttk.Label(self, text="Quantité :").grid(row=4, column=0, padx=10, pady=5, sticky=tk.W)
        self.entry_qty = ttk.Entry(self, textvariable=self.var_quantity, width=10)
        self.entry_qty.grid(row=4, column=1, padx=10, pady=5, sticky=tk.W)

        ttk.Label(self, text="Coût unitaire (€) :").grid(row=5, column=0, padx=10, pady=5, sticky=tk.W)
        self.entry_unit_cost = ttk.Entry(self, textvariable=self.var_unit_cost, width=10)
        self.entry_unit_cost.grid(row=5, column=1, padx=10, pady=5, sticky=tk.W)

        ttk.Label(self, text="Seuil de réassort :").grid(row=6, column=0, padx=10, pady=5, sticky=tk.W)
        self.entry_reorder = ttk.Entry(self, textvariable=self.var_reorder_point, width=10)
        self.entry_reorder.grid(row=6, column=1, padx=10, pady=5, sticky=tk.W)

        ttk.Label(self, text="Fournisseur préféré :").grid(row=7, column=0, padx=10, pady=5, sticky=tk.W)
        self.supplier_combobox = ttk.Combobox(self, state='readonly', width=28)
        self.supplier_combobox.grid(row=7, column=1, padx=10, pady=5)
        self.load_suppliers()
        if preferred_supplier_id:
            try:
                idx = self.supplier_ids.index(preferred_supplier_id)
                self.supplier_combobox.current(idx)
            except ValueError:
                self.supplier_combobox.set('')
        else:
            self.supplier_combobox.set('')
        ttk.Button(self, text="Rafraîchir", command=self.load_suppliers).grid(row=7, column=2, padx=5)

        btn_frame = ttk.Frame(self)
        btn_frame.grid(row=8, column=0, columnspan=3, pady=10)
        ttk.Button(btn_frame, text="OK", command=self.on_ok).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Annuler", command=self.on_cancel).pack(side=tk.LEFT, padx=5)

        self.entry_name.focus()
        self.grab_set()
        self.wait_window(self)

    def load_categories(self):
        conn = None
        try:
            with db_lock:
                conn = sqlite3.connect(DB_PATH, timeout=30)
                cursor = conn.cursor()
                cursor.execute("SELECT id, name FROM categories ORDER BY name")
                rows = cursor.fetchall()
        except sqlite3.Error:
            rows = []
        finally:
            if conn:
                conn.close()
        self.category_ids = [r[0] for r in rows]
        self.category_names = [r[1] for r in rows]
        self.cat_combobox['values'] = self.category_names

    def load_suppliers(self):
        suppliers = fetch_suppliers()
        self.supplier_ids = [s[0] for s in suppliers]
        supplier_names = [s[1] for s in suppliers]
        self.supplier_combobox['values'] = supplier_names
        if not suppliers:
            self.supplier_combobox.set('')

    def update_size_options(self):
        idx = self.cat_combobox.current()
        if idx < 0:
            self.size_combobox['values'] = []
            self.var_size.set('')
            self.size_combobox.configure(state='normal')
            return
        category_id = self.category_ids[idx]
        sizes = self._fetch_category_sizes(category_id)
        if sizes:
            self.size_combobox.configure(state='readonly')
            self.size_combobox['values'] = sizes
        else:
            selected_cat = self.category_names[idx].lower()
            fallback = StockApp.SHOE_SIZES if "chaussure" in selected_cat else StockApp.CLOTHING_SIZES
            self.size_combobox.configure(state='normal')
            self.size_combobox['values'] = fallback
        if self.var_size.get() not in self.size_combobox['values']:
            self.var_size.set('')

    def _fetch_category_sizes(self, category_id: int) -> list[str]:
        conn = None
        sizes: list[str] = []
        try:
            with db_lock:
                conn = sqlite3.connect(DB_PATH, timeout=30)
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT size_label FROM category_sizes WHERE category_id = ? ORDER BY size_label COLLATE NOCASE",
                    (category_id,),
                )
                sizes = [row[0] for row in cursor.fetchall()]
        except sqlite3.Error as exc:
            print(f"[DB Error] _fetch_category_sizes: {exc}")
        finally:
            if conn:
                conn.close()
        return sizes

    def add_category_inline(self):
        name = simpledialog.askstring("Nouvelle Catégorie", "Entrez le nom de la nouvelle catégorie :", parent=self)
        if not name:
            return
        note = simpledialog.askstring("Note de catégorie", "Entrez une note (optionnel) :", parent=self)
        sizes_input = simpledialog.askstring(
            "Tailles de la catégorie",
            "Indiquez les tailles séparées par une virgule (optionnel) :",
            parent=self,
        )
        sizes = []
        if sizes_input:
            sizes = [s.strip() for s in sizes_input.split(',') if s.strip()]
        conn = None
        try:
            with db_lock:
                conn = sqlite3.connect(DB_PATH, timeout=30)
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT INTO categories (name, note) VALUES (?, ?)",
                    (name, note.strip() if note and note.strip() else None),
                )
                category_id = cursor.lastrowid
                if sizes:
                    cursor.executemany(
                        "INSERT OR IGNORE INTO category_sizes (category_id, size_label) VALUES (?, ?)",
                        [(category_id, size) for size in sizes],
                    )
                conn.commit()
        except sqlite3.IntegrityError:
            messagebox.showerror("Erreur", "Catégorie existe déjà.")
        except sqlite3.Error as e:
            messagebox.showerror("Erreur BD", f"Impossible d'ajouter catégorie : {e}")
        finally:
            if conn:
                conn.close()
        self.load_categories()

    def on_ok(self):
        name = self.var_name.get().strip()
        barcode_value = self.var_barcode.get().strip()
        qty = self.var_quantity.get()
        cat_index = self.cat_combobox.current()
        category_id = self.category_ids[cat_index] if cat_index >= 0 else None
        size = self.var_size.get().strip()
        supplier_index = self.supplier_combobox.current()
        supplier_id = self.supplier_ids[supplier_index] if supplier_index >= 0 else None

        if not name:
            messagebox.showerror("Erreur", "Le nom est requis.")
            return
        if qty < 0:
            messagebox.showerror("Erreur", "Quantité invalide.")
            return
        if category_id is not None and size == "":
            messagebox.showerror("Erreur", "La taille est requise pour cette catégorie.")
            return
        if barcode_value and not barcode_value.isalnum():
            messagebox.showerror("Erreur", "Le code-barres doit être alphanumérique.")
            return
        try:
            unit_cost = float(self.var_unit_cost.get())
        except (TypeError, ValueError):
            messagebox.showerror("Erreur", "Le coût unitaire est invalide.")
            return
        reorder_value = self.var_reorder_point.get().strip()
        if reorder_value:
            try:
                reorder_point = int(reorder_value)
                if reorder_point < 0:
                    raise ValueError
            except ValueError:
                messagebox.showerror("Erreur", "Le seuil de réassort doit être un entier positif.")
                return
        else:
            reorder_point = None

        self.result = (
            name,
            barcode_value,
            category_id,
            size,
            qty,
            unit_cost,
            reorder_point,
            supplier_id,
        )
        self.destroy()

    def on_cancel(self):
        self.destroy()

# ----------------------
# TESTS (simplifiés)
# ----------------------
def run_tests():
    print("Running tests...")
    test_stock_db = 'stock_test.db'
    test_user_db = 'users_test.db'
    for f in (test_stock_db, test_user_db):
        if os.path.exists(f):
            os.remove(f)
    global DB_PATH, USER_DB_PATH
    original_db_path = DB_PATH
    original_user_db_path = USER_DB_PATH
    DB_PATH = test_stock_db
    USER_DB_PATH = test_user_db
    init_stock_db(DB_PATH)
    init_user_db(USER_DB_PATH)
    try:
        # Tester utilisateur
        pwd_hash = hash_password("testpwd")
        conn_u = sqlite3.connect(test_user_db)
        cursor_u = conn_u.cursor()
        cursor_u.execute("INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)", ("testuser", pwd_hash, "admin"))
        conn_u.commit()
        cursor_u.execute("SELECT password_hash, role FROM users WHERE username = ?", ("testuser",))
        stored_hash, role = cursor_u.fetchone()
        assert stored_hash == pwd_hash and role == "admin", "Utilisateur ou rôle incorrect"
        assert verify_user("testuser", "testpwd")[0], "Vérif échouée"
        assert not verify_user("testuser", "wrongpwd")[0], "Mdp incorrect accepté"
        conn_u.close()

        # Tester catégorie et article
        conn = sqlite3.connect(test_stock_db)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO categories (name) VALUES (?)", ("TestCat",))
        conn.commit()
        cursor.execute("SELECT id FROM categories WHERE name = ?", ("TestCat",))
        cat_id = cursor.fetchone()[0]
        assert cat_id is not None, "Catégorie non créée"

        cursor.execute(
            "INSERT INTO items (name, barcode, category_id, size, quantity, last_updated) VALUES (?, ?, ?, ?, ?, ?)",
            ("TestProduct", "12345", cat_id, "M", 10, datetime.now().isoformat())
        )
        conn.commit()
        cursor.execute("SELECT quantity FROM items WHERE name = ?", ("TestProduct",))
        qty = cursor.fetchone()[0]
        assert qty == 10, f"Doit être 10, got {qty}"
        print("Test insert article passé.")

        cursor.execute("UPDATE items SET quantity = ? WHERE name = ?", (5, "TestProduct"))
        conn.commit()
        cursor.execute("SELECT quantity FROM items WHERE name = ?", ("TestProduct",))
        qty = cursor.fetchone()[0]
        assert qty == 5, f"Doit être 5, got {qty}"
        print("Test update article passé.")

        cursor.execute("PRAGMA index_list('items')")
        indexes = cursor.fetchall()
        assert any('idx_items_name' in idx for idx in indexes), "Index idx_items_name manquant"
        print("Index test passé.")
        conn.close()
    except AssertionError as e:
        print(f"[Test Failure] {e}")
    except Exception as e:
        print(f"[Test Error] {e}\n{traceback.format_exc()}")
    finally:
        DB_PATH = original_db_path
        USER_DB_PATH = original_user_db_path
        for f in (test_stock_db, test_user_db):
            if os.path.exists(f):
                os.remove(f)
    print("All tests completed.")

# ---------------------------
# DÉMARRAGE PRINCIPAL
# ---------------------------
def main(argv=None):
    """Point d'entrée principal de l'application graphique."""
    startup_listener.reset()
    args = sys.argv[1:] if argv is None else list(argv)
    startup_listener.record(
        "Appel de gestion_stock.main.",
        level=logging.DEBUG,
    )
    startup_listener.record(
        "Arguments reçus : %s" % (args if args else "<aucun>"),
        level=logging.DEBUG,
    )
    logger.info("Lancement de gestion_stock.main avec les arguments : %s", args if args else "<aucun>")
    if args and args[0] == '--test':
        logger.info("Exécution du mode test demandé depuis la ligne de commande.")
        run_tests()
        startup_listener.record("Mode test exécuté : arrêt avant le démarrage graphique.")
        startup_listener.stop()
        startup_listener.flush_to_logger(level=logging.DEBUG)
        return 0

    if args and args[0] == '--diagnostics':
        logger.info("Exécution du diagnostic d'environnement demandé depuis la ligne de commande.")
        diagnostics = collect_environment_diagnostics()
        diagnostic_output = format_environment_diagnostics(diagnostics)
        print("Diagnostic de l'environnement :")
        print(diagnostic_output)
        missing_components = [key for key, info in diagnostics.items() if not info.get('ok')]
        if missing_components:
            logger.warning("Composants indisponibles détectés : %s", ", ".join(missing_components))
            startup_listener.record(
                f"Diagnostic terminé – composants manquants : {', '.join(missing_components)}.",
                level=logging.WARNING,
            )
            startup_listener.stop()
            startup_listener.flush_to_logger(level=logging.DEBUG)
            return 1
        startup_listener.record("Diagnostic terminé – tous les composants essentiels sont disponibles.")
        startup_listener.stop()
        startup_listener.flush_to_logger(level=logging.DEBUG)
        return 0

    if not TK_AVAILABLE:
        logger.error("Tkinter est indisponible : arrêt de l'application.")
        print("Erreur : Tkinter non disponible. Le programme ne peut pas démarrer.")
        startup_listener.record(
            "Tkinter indisponible, démarrage interrompu.",
            level=logging.ERROR,
        )
        startup_listener.stop()
        startup_listener.flush_to_logger(level=logging.ERROR)
        return 1

    init_stock_db(DB_PATH)
    init_user_db(USER_DB_PATH)
    logger.info("Initialisation des bases de données terminée.")
    startup_listener.record("Initialisation des bases de données terminée.", level=logging.DEBUG)

    try:
        root = tk.Tk()
    except tk.TclError as exc:
        logger.exception("Impossible d'initialiser l'interface Tkinter.")
        print("Erreur : impossible d'initialiser Tkinter. Vérifiez la disponibilité d'un affichage graphique (DISPLAY).")
        startup_listener.record(
            f"Initialisation Tkinter échouée : {exc}",
            level=logging.ERROR,
        )
        startup_listener.stop()
        startup_listener.flush_to_logger(level=logging.ERROR)
        return 1
    startup_listener.record("Création du conteneur Tkinter racine.", level=logging.DEBUG)
    theme_mode = config.get('Settings', 'theme', fallback='dark')
    try:
        font_pref = config.getint('Settings', 'font_size')
    except Exception:
        font_pref = 10
    apply_theme(root, theme_mode, font_size=font_pref)
    root.withdraw()
    login = LoginDialog(root)
    startup_listener.record("Boîte de dialogue de connexion affichée.", level=logging.DEBUG)
    if not login.result:
        logger.info("Connexion annulée par l'utilisateur depuis la boîte de dialogue de connexion.")
        startup_listener.record("Connexion annulée par l'utilisateur.", level=logging.INFO)
        root.destroy()
        startup_listener.stop()
        startup_listener.flush_to_logger(level=logging.DEBUG)
        return 0

    current_user = login.username
    current_role = login.role
    logger.info("Utilisateur connecté : %s (rôle : %s)", current_user, current_role)
    startup_listener.record(
        f"Utilisateur connecté : {current_user} (rôle : {current_role}).",
        level=logging.INFO,
    )
    current_user_id = None
    conn = None
    try:
        with db_lock:
            conn = sqlite3.connect(USER_DB_PATH, timeout=30)
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM users WHERE username = ?", (current_user,))
            row = cursor.fetchone()
            if row:
                current_user_id = row[0]
                logger.info("Identifiant interne récupéré pour l'utilisateur %s : %s", current_user, current_user_id)
                startup_listener.record(
                    f"Identifiant interne récupéré pour {current_user} : {current_user_id}.",
                    level=logging.DEBUG,
                )
    except sqlite3.Error as exc:
        logger.exception("Erreur lors de la récupération de l'identifiant utilisateur pour %s", current_user)
        print(f"[DB Error] main: {exc}")
        startup_listener.record(
            f"Erreur lors de la récupération de l'identifiant utilisateur : {exc}",
            level=logging.ERROR,
        )
    finally:
        if conn:
            conn.close()

    startup_listener.record("Fermeture de la fenêtre de connexion.", level=logging.DEBUG)
    root.destroy()
    allowed_modules = get_user_module_permissions(current_user_id, role=current_role)
    app = StockApp(current_user, current_role, current_user_id, allowed_modules=allowed_modules)
    logger.info("Lancement de l'interface graphique principale.")
    startup_listener.record("Fenêtre principale initialisée.", level=logging.INFO)
    startup_listener.record(
        "Entrée dans la boucle principale Tkinter : lancement complet.",
        level=logging.INFO,
    )
    startup_listener.stop()
    startup_listener.flush_to_logger(level=logging.DEBUG)
    app.mainloop()
    logger.info("Fermeture de l'application graphique.")
    return 0


if __name__ == '__main__':  # pragma: no cover - compatibilité exécution directe
    sys.exit(main())
