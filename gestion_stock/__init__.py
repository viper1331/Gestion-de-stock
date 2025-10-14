# -*- coding: utf-8 -*-
# Copyright (c) 2025 Sebastien Cangemi
# Tous droits réservés.
# Gestion Stock Pro - Interface graphique professionnelle
# (version avec base utilisateur séparée/protégée et mémorisation des largeurs de colonnes)
#
# Pour générer un exécutable Windows :
#   pip install -r requirements.txt
#   pyinstaller --onefile --windowed --name GestionStockPro gestion_stock.py

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
default_config = {
    'db_path': 'stock.db',
    'user_db_path': 'users.db',
    'barcode_dir': 'barcodes',
    'camera_index': '0',
    'microphone_index': '',
    'enable_voice': 'true',
    'enable_tts': 'true',
    'enable_barcode_generation': 'true',
    'low_stock_threshold': '5',
    'last_user': ''
}
if not os.path.exists(CONFIG_FILE):
    config['Settings'] = default_config
    config['ColumnWidths'] = {}
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
ENABLE_BARCODE_GENERATION = config['Settings'].getboolean('enable_barcode_generation', fallback=True)
DEFAULT_LOW_STOCK_THRESHOLD = config['Settings'].getint('low_stock_threshold', fallback=5)
LAST_USER = config['Settings'].get('last_user', '')

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

try:
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox, simpledialog
    TK_AVAILABLE = True
except ImportError:
    TK_AVAILABLE = False

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


def adjust_item_quantity(item_id, delta, operator='system', source='manual', note=None):
    """Modifie la quantité d'un article et journalise le mouvement."""
    if delta == 0:
        return None
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
                name TEXT UNIQUE NOT NULL
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
            return True, row[1]
        else:
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


# ------------------------
# FONCTIONS FOURNISSEURS / APPROVISIONNEMENTS
# ------------------------

def fetch_suppliers():
    conn = None
    try:
        with db_lock:
            conn = sqlite3.connect(DB_PATH, timeout=30)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, name, contact_name, email, phone, notes, created_at "
                "FROM suppliers ORDER BY name"
            )
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


def fetch_items_lookup():
    conn = None
    try:
        with db_lock:
            conn = sqlite3.connect(DB_PATH, timeout=30)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT items.id, items.name, COALESCE(items.unit_cost, 0), COALESCE(items.reorder_point, ?) "
                "FROM items ORDER BY items.name",
                (DEFAULT_LOW_STOCK_THRESHOLD,),
            )
            return cursor.fetchall()
    except sqlite3.Error as e:
        print(f"[DB Error] fetch_items_lookup: {e}")
        return []
    finally:
        if conn:
            conn.close()


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
        with db_lock:
            conn = sqlite3.connect(DB_PATH, timeout=30)
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO purchase_orders (supplier_id, status, expected_date, created_at, created_by, note)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (supplier_id, status, expected_date, timestamp, created_by, note),
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


def fetch_purchase_orders(status=None):
    conn = None
    try:
        query = (
            "SELECT purchase_orders.id, purchase_orders.created_at, purchase_orders.status, purchase_orders.expected_date, "
            "purchase_orders.received_at, suppliers.name, purchase_orders.note, purchase_orders.created_by "
            "FROM purchase_orders LEFT JOIN suppliers ON suppliers.id = purchase_orders.supplier_id"
        )
        params = []
        if status:
            query += " WHERE purchase_orders.status = ?"
            params.append(status)
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
        timestamp = datetime.now().isoformat()
        with db_lock:
            conn = sqlite3.connect(DB_PATH, timeout=30)
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE purchase_orders SET status = ?, received_at = ?, note = COALESCE(note, '') || ? WHERE id = ?",
                (status, timestamp if status in ('RECEIVED', 'PARTIAL') else None, f"\n{note}" if note else '', purchase_order_id),
            )
            if receipt_lines:
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
                        (new_qty, timestamp, item_id),
                    )
                    log_stock_movement(
                        cursor,
                        item_id,
                        received_qty,
                        'IN',
                        'purchase_order_receipt',
                        reviewer,
                        note=f"Réception bon #{purchase_order_id}",
                        timestamp=timestamp,
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


def fetch_collaborator_gear(collaborator_id=None):
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
        if collaborator_id:
            query += " WHERE collaborator_gear.collaborator_id = ?"
            params.append(collaborator_id)
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
        with db_lock:
            conn = sqlite3.connect(DB_PATH, timeout=30)
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO collaborator_gear (collaborator_id, item_id, size, quantity, issued_at, due_date, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (collaborator_id, item_id, size, quantity, issued_at, due_date, notes),
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
    except sqlite3.Error as e:
        print(f"[DB Error] assign_collaborator_gear: {e}")
        return False
    finally:
        if conn:
            conn.close()


def close_collaborator_gear(gear_id, quantity, operator, response_note='', status='returned'):
    conn = None
    try:
        returned_at = datetime.now().isoformat()
        with db_lock:
            conn = sqlite3.connect(DB_PATH, timeout=30)
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE collaborator_gear
                SET status = ?, returned_at = ?, notes = COALESCE(notes, '') || ?
                WHERE id = ?
                """,
                (status, returned_at, f"\n{response_note}" if response_note else '', gear_id),
            )
            conn.commit()
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


def fetch_dashboard_metrics(low_stock_threshold):
    conn = None
    try:
        with db_lock:
            conn = sqlite3.connect(DB_PATH, timeout=30)
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*), COALESCE(SUM(quantity),0), COALESCE(SUM(quantity * COALESCE(unit_cost,0)),0) FROM items")
            total_items, total_quantity, stock_value = cursor.fetchone()
            cursor.execute(
                "SELECT COUNT(*) FROM items WHERE quantity <= COALESCE(reorder_point, ?)",
                (low_stock_threshold,),
            )
            low_stock_count = cursor.fetchone()[0]
            cursor.execute(
                """
                SELECT items.name, ABS(SUM(stock_movements.quantity_change)) AS total_movement
                FROM stock_movements
                JOIN items ON items.id = stock_movements.item_id
                WHERE stock_movements.movement_type = 'OUT' AND stock_movements.created_at >= ?
                GROUP BY items.name
                ORDER BY total_movement DESC
                LIMIT 5
                """,
                ((datetime.now() - timedelta(days=30)).isoformat(),),
            )
            top_sales = cursor.fetchall()
            cursor.execute(
                """
                SELECT DATE(substr(created_at, 1, 10)) AS jour,
                       SUM(CASE WHEN movement_type = 'IN' THEN quantity_change ELSE 0 END) AS entrees,
                       SUM(CASE WHEN movement_type = 'OUT' THEN ABS(quantity_change) ELSE 0 END) AS sorties
                FROM stock_movements
                WHERE created_at >= ?
                GROUP BY jour
                ORDER BY jour
                """,
                ((datetime.now() - timedelta(days=14)).isoformat(),),
            )
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
            cursor.execute("UPDATE users SET role = ? WHERE id = ?", (new_role, user_id))
            updated = cursor.rowcount
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
    try:
        tts_engine = pyttsx3.init()
        def speak(text):
            print(f"[SPEAK] {text}")
            try:
                tts_engine.say(text)
                tts_engine.runAndWait()
            except Exception as e:
                print(f"[TTS erreur] {e} | Texte à lire : {text}")
    except Exception as init_err:
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

        self.user_list = ttk.Treeview(self, columns=('ID','Username','Role'), show='headings', height=8)
        self.user_list.heading('ID', text='ID'); self.user_list.column('ID', width=40, anchor=tk.CENTER)
        self.user_list.heading('Username', text='Nom d\'utilisateur'); self.user_list.column('Username', width=150)
        self.user_list.heading('Role', text='Rôle'); self.user_list.column('Role', width=80, anchor=tk.CENTER)
        self.user_list.grid(row=0, column=0, columnspan=3, padx=10, pady=5)
        self.load_users()

        ttk.Button(self, text="Ajouter", command=self.add_user).grid(row=1, column=0, padx=10, pady=5)
        ttk.Button(self, text="Supprimer", command=self.delete_user).grid(row=1, column=1, padx=10, pady=5)
        ttk.Button(self, text="Modifier Rôle", command=self.change_role).grid(row=1, column=2, padx=10, pady=5)
        ttk.Button(self, text="Fermer", command=self.on_close).grid(row=2, column=0, columnspan=3, pady=10)

        self.grab_set()
        self.wait_window(self)

    def load_users(self):
        for row in self.user_list.get_children():
            self.user_list.delete(row)
        rows = fetch_all_users()
        for r in rows:
            self.user_list.insert('', tk.END, values=r)

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
        if messagebox.askyesno("Confirmer", f"Supprimer l'utilisateur '{username}' ?"):
            if delete_user_by_id(user_id):
                self.load_users()
                messagebox.showinfo("Succès", f"Utilisateur '{username}' supprimé.")
            else:
                messagebox.showerror("Erreur", "Impossible de supprimer l'utilisateur.")

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
            if update_user_role(user_id, new_role):
                self.load_users()
                messagebox.showinfo("Succès", f"Rôle de '{username}' changé en '{new_role}'.")
            else:
                messagebox.showerror("Erreur", "Impossible de modifier le rôle.")
        else:
            messagebox.showerror("Erreur", "Rôle invalide. Choisir 'admin' ou 'user'.")

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

# ----------------------
# CLASSE PRINCIPALE DE L'APPLICATION
# ----------------------
class StockApp(tk.Tk):
    CLOTHING_SIZES = ["XXS", "XS", "S", "M", "L", "XL", "XXL"]
    SHOE_SIZES = [str(i) for i in range(30, 61)]

    def __init__(self, current_user, current_role, current_user_id):
        startup_listener.record(
            "Construction de l'interface principale StockApp.",
            level=logging.DEBUG,
        )
        super().__init__()
        self.current_user = current_user
        self.current_role = current_role
        self.current_user_id = current_user_id

        self.title(f"Gestion Stock Pro - Connecté : {self.current_user} ({self.current_role})")
        self.geometry("950x600")
        self.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.style = ttk.Style(self)
        self.style.theme_use("clam")

        self.low_stock_threshold = config['Settings'].getint(
            'low_stock_threshold',
            fallback=DEFAULT_LOW_STOCK_THRESHOLD
        )

        self.create_menu()
        self.create_toolbar()
        self.create_statusbar()
        self.create_main_frames()
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

        # Appliquer largeurs sauvegardées
        self.apply_saved_column_widths()
        startup_listener.record("Largeurs de colonnes restaurées.", level=logging.DEBUG)
        self.load_inventory()
        startup_listener.record("Inventaire initial chargé.", level=logging.DEBUG)

        self.alert_manager = AlertManager(self, threshold=self.low_stock_threshold)
        startup_listener.record("Gestionnaire d'alertes initialisé.", level=logging.DEBUG)

        if ENABLE_VOICE and SR_LIB_AVAILABLE:
            if microphone is None:
                init_recognizer()


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
        create_suggested_purchase_order(item_id, deficit, created_by=getattr(self.app, 'current_user', 'system'))
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

    def on_closing(self):
        self.save_column_widths()
        if hasattr(self, 'dashboard_job') and self.dashboard_job:
            try:
                self.after_cancel(self.dashboard_job)
            except Exception:
                pass
            self.dashboard_job = None
        if hasattr(self, 'alert_manager') and self.alert_manager:
            self.alert_manager.stop()
        global voice_active
        voice_active = False
        self.destroy()

    def create_menu(self):
        menubar = tk.Menu(self)

        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Déconnexion", command=self.logout)
        file_menu.add_separator()
        file_menu.add_command(label="Exporter CSV", command=self.export_csv)
        file_menu.add_separator()
        file_menu.add_command(label="Sauvegarder base", command=self.backup_database)
        file_menu.add_separator()
        file_menu.add_command(label="Quitter", command=self.on_closing)
        menubar.add_cascade(label="Fichier", menu=file_menu)

        settings_menu = tk.Menu(menubar, tearoff=0)
        settings_menu.add_command(label="Configuration générale", command=self.open_config_dialog)
        settings_menu.add_command(label="Gérer Catégories", command=self.open_category_dialog)
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

        stock_menu = tk.Menu(menubar, tearoff=0)
        stock_menu.add_command(label="Ajouter Article", command=self.open_add_dialog)
        stock_menu.add_command(label="Modifier Article", command=self.open_edit_selected)
        stock_menu.add_command(label="Supprimer Article", command=self.delete_selected)
        stock_menu.add_separator()
        stock_menu.add_command(label="Entrée Stock", command=lambda: self.open_stock_adjustment(True))
        stock_menu.add_command(label="Sortie Stock", command=lambda: self.open_stock_adjustment(False))
        stock_menu.add_separator()
        stock_menu.add_command(label="Actualiser", command=self.load_inventory)
        menubar.add_cascade(label="Stock", menu=stock_menu)

        scan_menu = tk.Menu(menubar, tearoff=0)
        scan_menu.add_command(label="Scan Caméra", command=self.scan_camera)
        scan_menu.add_command(label="Scan Douchette", command=lambda: self.entry_scan.focus())
        menubar.add_cascade(label="Scan", menu=scan_menu)

        report_menu = tk.Menu(menubar, tearoff=0)
        report_menu.add_command(label="Rapport Stock Faible", command=self.report_low_stock)
        report_menu.add_command(label="Exporter Rapport PDF", command=self.generate_pdf_report)
        menubar.add_cascade(label="Rapports", menu=report_menu)

        module_menu = tk.Menu(menubar, tearoff=0)
        module_menu.add_command(label="Fournisseurs", command=self.open_supplier_management)
        module_menu.add_command(label="Bons de commande", command=self.open_purchase_orders)
        module_menu.add_command(label="Dotations collaborateurs", command=self.open_collaborator_gear)
        if self.current_role == 'admin':
            module_menu.add_command(label="Approvals en attente", command=self.open_approval_queue)
        menubar.add_cascade(label="Modules", menu=module_menu)

        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="À propos", command=self.show_about)
        menubar.add_cascade(label="Aide", menu=help_menu)

        self.config(menu=menubar)

    def create_toolbar(self):
        toolbar = ttk.Frame(self, padding=5)
        btn_add = ttk.Button(toolbar, text="Ajouter", command=self.open_add_dialog)
        btn_edit = ttk.Button(toolbar, text="Modifier", command=self.open_edit_selected)
        btn_delete = ttk.Button(toolbar, text="Supprimer", command=self.delete_selected)
        btn_stock_in = ttk.Button(toolbar, text="Entrée", command=lambda: self.open_stock_adjustment(True))
        btn_stock_out = ttk.Button(toolbar, text="Sortie", command=lambda: self.open_stock_adjustment(False))
        btn_scan_cam = ttk.Button(toolbar, text="Scan Caméra", command=self.scan_camera)

        if ENABLE_VOICE and SR_LIB_AVAILABLE:
            btn_listen = ttk.Button(toolbar, text="Écoute Micro", command=start_voice_listening)
            btn_stop_listen = ttk.Button(toolbar, text="Arrêter Micro", command=stop_voice_listening)
        else:
            btn_listen = ttk.Button(toolbar, text="Écoute Micro", state='disabled')
            btn_stop_listen = ttk.Button(toolbar, text="Arrêter Micro", state='disabled')

        btn_barcode_gen = ttk.Button(
            toolbar,
            text="Générer Code-Barres",
            command=lambda: self.generate_barcode_dialog()
        )
        btn_export = ttk.Button(toolbar, text="Exporter CSV", command=self.export_csv)

        btn_add.pack(side=tk.LEFT, padx=2)
        btn_edit.pack(side=tk.LEFT, padx=2)
        btn_delete.pack(side=tk.LEFT, padx=2)
        btn_stock_in.pack(side=tk.LEFT, padx=2)
        btn_stock_out.pack(side=tk.LEFT, padx=2)
        btn_scan_cam.pack(side=tk.LEFT, padx=2)
        btn_listen.pack(side=tk.LEFT, padx=2)
        btn_stop_listen.pack(side=tk.LEFT, padx=2)
        btn_barcode_gen.pack(side=tk.LEFT, padx=2)
        btn_export.pack(side=tk.LEFT, padx=2)

        toolbar.pack(fill=tk.X)

    def create_statusbar(self):
        self.status = tk.StringVar()
        self.status.set("Prêt")
        status_bar = ttk.Label(self, textvariable=self.status, relief=tk.SUNKEN, anchor=tk.W)
        status_bar.pack(side=tk.BOTTOM, fill=tk.X)

    def create_main_frames(self):
        main_frame = ttk.Frame(self)
        main_frame.pack(fill=tk.BOTH, expand=True)

        self.notebook = ttk.Notebook(main_frame)
        self.notebook.pack(fill=tk.BOTH, expand=True)

        inventory_frame = ttk.Frame(self.notebook)
        self.notebook.add(inventory_frame, text="Inventaire")

        self.dashboard_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.dashboard_frame, text="Tableau de bord")

        search_frame = ttk.Frame(inventory_frame)
        ttk.Label(search_frame, text="Rechercher :").pack(side=tk.LEFT, padx=5)
        self.entry_search = ttk.Entry(search_frame)
        self.entry_search.pack(side=tk.LEFT, padx=5)
        self.entry_search.bind('<KeyRelease>', lambda e: self.load_inventory())
        search_frame.pack(fill=tk.X, pady=5)

        scan_frame = ttk.Frame(inventory_frame)
        ttk.Label(scan_frame, text="Scanner (douchette) :").pack(side=tk.LEFT, padx=5)
        self.scan_var = tk.StringVar()
        self.entry_scan = ttk.Entry(scan_frame, textvariable=self.scan_var)
        self.entry_scan.pack(side=tk.LEFT, padx=5)
        self.entry_scan.focus()
        global scan_timer_id
        scan_timer_id = None

        def scan_var_callback(*args):
            global scan_timer_id
            if scan_timer_id:
                try:
                    self.after_cancel(scan_timer_id)
                except:
                    pass
            def process_after_delay():
                code = self.scan_var.get().strip()
                if code:
                    self.process_barcode(code, source='douchette')
                self.scan_var.set("")
            scan_timer_id = self.after(300, process_after_delay)

        self.scan_var.trace_add('write', scan_var_callback)
        scan_frame.pack(fill=tk.X, pady=5)

        cols = ('ID', 'Nom', 'Code-Barres', 'Catégorie', 'Taille', 'Quantité', 'Dernière MAJ')
        self.tree = ttk.Treeview(inventory_frame, columns=cols, show='headings', selectmode='browse')
        for col in cols:
            self.tree.heading(col, text=col)
            self.tree.column(col, anchor=tk.CENTER)
        self.tree.pack(fill=tk.BOTH, expand=True)

        # Configuration des couleurs de lignes selon le niveau de stock
        self.tree.tag_configure('stock_zero', background='#f8d7da', foreground='#721c24')
        self.tree.tag_configure('stock_low', background='#fff3cd', foreground='#856404')
        self.tree.tag_configure('stock_ok', background='#e8f5e9', foreground='#1b5e20')
        self.tree.tag_configure('stock_unknown', background='#f0f0f0', foreground='#333333')

        self.create_dashboard_tab()

    def create_dashboard_tab(self):
        self.dashboard_vars = {
            'total_items': tk.StringVar(value='0'),
            'total_quantity': tk.StringVar(value='0'),
            'stock_value': tk.StringVar(value='0.00 €'),
            'low_stock_count': tk.StringVar(value='0'),
        }

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

        if MATPLOTLIB_AVAILABLE and FigureCanvasTkAgg is not None:
            self.dashboard_figure = Figure(figsize=(10, 4), dpi=100)
            self.dashboard_canvas = FigureCanvasTkAgg(self.dashboard_figure, master=self.dashboard_frame)
            self.dashboard_canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        else:
            self.dashboard_figure = None
            self.dashboard_canvas = None
            ttk.Label(
                self.dashboard_frame,
                text="Matplotlib n'est pas disponible : visualisation désactivée.",
            ).pack(fill=tk.X, padx=10, pady=10)

        self.dashboard_job = None
        self.refresh_dashboard()

    def load_inventory(self):
        search_text = self.entry_search.get().lower().strip()
        for row in self.tree.get_children():
            self.tree.delete(row)
        conn = None
        conn = None
        try:
            with db_lock:
                conn = sqlite3.connect(DB_PATH, timeout=30)
                cursor = conn.cursor()
                if search_text:
                    cursor.execute(
                        "SELECT items.id, items.name, items.barcode, categories.name, items.size, items.quantity, items.last_updated, items.reorder_point, items.unit_cost "
                        "FROM items LEFT JOIN categories ON items.category_id = categories.id "
                        "WHERE lower(items.name) LIKE ? OR items.barcode LIKE ?",
                        (f'%{search_text}%', f'%{search_text}%')
                    )
                else:
                    cursor.execute(
                        "SELECT items.id, items.name, items.barcode, categories.name, items.size, items.quantity, items.last_updated, items.reorder_point, items.unit_cost "
                        "FROM items LEFT JOIN categories ON items.category_id = categories.id"
                    )
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
                size,
                quantity,
                last_updated,
                reorder_point,
                unit_cost,
            ) = item
            tag = self._get_stock_tag(quantity, reorder_point)
            display_values = (item_id, name, barcode, category, size, quantity, last_updated)
            self.tree.insert('', tk.END, values=display_values, tags=(tag,))
        count = len(self.tree.get_children())
        self.status.set(f"Articles listés : {count}")
        if self.dashboard_job is None:
            self.refresh_dashboard()

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
        metrics = fetch_dashboard_metrics(self.low_stock_threshold)
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
                ax1.set_title('Top sorties (30j)')
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
                ax2.set_title('Mouvements (14j)')
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

    def apply_saved_column_widths(self):
        """
        Lit la section 'ColumnWidths' dans config.ini et applique aux colonnes existantes.
        """
        if 'ColumnWidths' not in config:
            return
        for col, val in config['ColumnWidths'].items():
            try:
                width = int(val)
                if col in self.tree['columns']:
                    self.tree.column(col, width=width)
            except:
                continue

    def save_column_widths(self):
        """
        Sauvegarde les largeurs actuelles des colonnes dans config.ini, section 'ColumnWidths'.
        """
        if 'ColumnWidths' not in config:
            config['ColumnWidths'] = {}
        for col in self.tree['columns']:
            w = self.tree.column(col)['width']
            config['ColumnWidths'][col] = str(w)
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            config.write(f)

    def open_add_dialog(self):
        dialog = ItemDialog(self, "Ajouter Article")
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
            conn = None
            try:
                with db_lock:
                    conn = sqlite3.connect(DB_PATH, timeout=30)
                    cursor = conn.cursor()
                    timestamp = datetime.now().isoformat()
                    cursor.execute(
                        "INSERT INTO items (name, barcode, category_id, size, quantity, last_updated, unit_cost, reorder_point, preferred_supplier_id) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
                        )
                    )
                    item_id = cursor.lastrowid
                    if qty:
                        log_stock_movement(
                            cursor,
                            item_id,
                            qty,
                            'IN',
                            'manual_creation',
                            self.current_user,
                            note="Création article via formulaire",
                            timestamp=timestamp,
                        )
                    conn.commit()
                    self.status.set(f"Article '{name}' ajouté.")
                    if ENABLE_BARCODE_GENERATION and barcode_value:
                        save_barcode_image(barcode_value, article_name=name)
            except sqlite3.IntegrityError as e:
                messagebox.showerror("Erreur", f"Impossible d'ajouter l'article : {e}")
            except sqlite3.Error as e:
                messagebox.showerror("Erreur BD", f"Erreur lors de l'ajout : {e}")
            finally:
                if conn:
                    conn.close()
            self.load_inventory()

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
        id_, name, _, _, size_value, qty, _ = item['values']
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
            name = simpledialog.askstring("Nouvel Article", f"Code-barres inconnu : {code}\nEntrez le nom :")
            if not name:
                return
            dlg = CategorySelectionDialog(self, "Sélectionner catégorie")
            category_id = dlg.result
            if category_id is None:
                return
            conn = None
            try:
                with db_lock:
                    conn = sqlite3.connect(DB_PATH, timeout=30)
                    cursor = conn.cursor()
                    cursor.execute("SELECT name FROM categories WHERE id = ?", (category_id,))
                    cat_name_db = cursor.fetchone()[0]
            except sqlite3.Error:
                cat_name_db = ""
            finally:
                if conn:
                    conn.close()

            if "chaussure" in cat_name_db.lower():
                size = simpledialog.askstring("Taille Chaussure", f"Taille (30–60) pour {name} :")
            else:
                size = simpledialog.askstring("Taille Vêtement", f"Taille (XXS–XXL) pour {name} :")
            if not size:
                return
            qty = simpledialog.askinteger("Quantité", f"Quantité initiale pour {name} (Taille {size}) :")
            if qty is None:
                return
            new_item_id = None
            conn = None
            try:
                with db_lock:
                    conn = sqlite3.connect(DB_PATH, timeout=30)
                    cursor = conn.cursor()
                    timestamp = datetime.now().isoformat()
                    cursor.execute(
                        "INSERT OR IGNORE INTO items (name, barcode, category_id, size, quantity, last_updated) VALUES (?, ?, ?, ?, ?, ?)",
                        (name, code, category_id, size, qty, timestamp)
                    )
                    if cursor.rowcount:
                        new_item_id = cursor.lastrowid
                        log_stock_movement(
                            cursor,
                            new_item_id,
                            qty,
                            'IN',
                            f'scan_{source}',
                            self.current_user,
                            note="Création via scan",
                            timestamp=timestamp,
                        )
                    conn.commit()
                speak(f"Nouvel article {name}, taille {size}, ajouté.")
                if ENABLE_BARCODE_GENERATION:
                    save_barcode_image(code, article_name=name)
            except sqlite3.IntegrityError:
                messagebox.showerror("Erreur", "Impossible : code-barres déjà existant.")
            except sqlite3.Error as e:
                messagebox.showerror("Erreur BD", f"Erreur lors de l'ajout : {e}")
            finally:
                if conn:
                    conn.close()
        self.load_inventory()
        if result:
            self.select_item_in_tree(id_)
        elif 'new_item_id' in locals() and new_item_id:
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
            self.process_barcode(found_code, source='camera')
        else:
            speak("Aucun code-barres détecté.")

    def generate_barcode_dialog(self):
        article = simpledialog.askstring("Générer Code-Barres", "Entrez le nom de l'article :")
        if article:
            generate_barcode_for_item(article)

    def export_csv(self):
        file_path = filedialog.asksaveasfilename(defaultextension='.csv', filetypes=[('CSV', '*.csv')])
        if not file_path:
            return
        conn = None
        try:
            with db_lock:
                conn = sqlite3.connect(DB_PATH, timeout=30)
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT items.name, items.barcode, categories.name, items.size, items.quantity, items.last_updated "
                    "FROM items LEFT JOIN categories ON items.category_id = categories.id"
                )
                rows = cursor.fetchall()
        except sqlite3.Error as e:
            messagebox.showerror("Erreur BD", f"Impossible d'exporter en CSV : {e}")
            rows = []
        finally:
            if conn:
                conn.close()
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write('Nom,Code-Barres,Catégorie,Taille,Quantité,Dernière MAJ\n')
                for r in rows:
                    f.write(','.join(map(str, r)) + '\n')
            messagebox.showinfo("Export CSV", f"Données exportées vers {file_path}")
            self.status.set(f"Exporté vers {os.path.basename(file_path)}")
        except Exception as e:
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
                    "SELECT items.name, items.barcode, categories.name, items.size, items.quantity "
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
            [f"{r[0]} (Barcode: {r[1]}, Catégorie: {r[2]}, Taille: {r[3]}, Quantité: {r[4]})" for r in results]
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
            messagebox.showerror("Rapport PDF", f"Erreur lors de la génération du PDF : {e}")
            return

        messagebox.showinfo("Rapport PDF", f"Rapport généré : {file_path}")
        self.status.set(f"Rapport PDF exporté : {os.path.basename(file_path)}")

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
            global CAMERA_INDEX, MICROPHONE_INDEX
            config['Settings']['db_path'] = dialog.result['db_path']
            config['Settings']['user_db_path'] = dialog.result['user_db_path']
            config['Settings']['barcode_dir'] = dialog.result['barcode_dir']
            config['Settings']['camera_index'] = str(dialog.result['camera_index'])
            microphone_index = dialog.result['microphone_index']
            config['Settings']['microphone_index'] = '' if microphone_index is None else str(microphone_index)
            config['Settings']['enable_voice'] = str(dialog.result['enable_voice']).lower()
            config['Settings']['enable_tts'] = str(dialog.result['enable_tts']).lower()
            config['Settings']['enable_barcode_generation'] = str(dialog.result['enable_barcode_generation']).lower()
            config['Settings']['low_stock_threshold'] = str(dialog.result['low_stock_threshold'])
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                config.write(f)
            CAMERA_INDEX = dialog.result['camera_index']
            MICROPHONE_INDEX = microphone_index
            try:
                self.low_stock_threshold = int(dialog.result['low_stock_threshold'])
            except (TypeError, ValueError):
                self.low_stock_threshold = DEFAULT_LOW_STOCK_THRESHOLD
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
            messagebox.showerror("Erreur Backup", f"Impossible de sauvegarder les bases : {e}")
            return
        messagebox.showinfo("Backup réussi", f"Bases sauvegardées vers : {file_path}")
        self.status.set(f"Backup : {os.path.basename(file_path)}")

    def logout(self):
        """
        Déconnecte l'utilisateur sans quitter l'application : ferme la fenêtre
        et relance le dialogue de connexion.
        """
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
        app = StockApp(new_user, new_role, uid)
        app.mainloop()

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
        self.geometry("650x400")

        cols = ("Nom", "Contact", "Email", "Téléphone", "Créé le")
        self.tree = ttk.Treeview(self, columns=cols, show='headings')
        for col in cols:
            self.tree.heading(col, text=col)
            self.tree.column(col, width=120, anchor=tk.W)
        self.tree.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        btn_frame = ttk.Frame(self)
        btn_frame.pack(fill=tk.X, padx=10, pady=5)
        ttk.Button(btn_frame, text="Ajouter", command=self.add_supplier).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Modifier", command=self.edit_supplier).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Supprimer", command=self.delete_supplier).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Fermer", command=self.destroy).pack(side=tk.RIGHT, padx=5)

        self.refresh()

    def refresh(self):
        for child in self.tree.get_children():
            self.tree.delete(child)
        for supplier in fetch_suppliers():
            supplier_id, name, contact, email, phone, notes, created_at = supplier
            self.tree.insert('', tk.END, iid=supplier_id, values=(name, contact, email, phone, created_at))

    def add_supplier(self):
        dialog = SupplierFormDialog(self, "Ajouter un fournisseur")
        if dialog.result:
            name, contact, email, phone, notes = dialog.result
            if save_supplier(name, contact, email, phone, notes):
                self.refresh()

    def edit_supplier(self):
        selection = self.tree.selection()
        if not selection:
            messagebox.showwarning("Fournisseurs", "Sélectionnez un fournisseur.", parent=self)
            return
        supplier_id = int(selection[0])
        supplier = next((s for s in fetch_suppliers() if s[0] == supplier_id), None)
        if not supplier:
            messagebox.showerror("Fournisseurs", "Fournisseur introuvable.", parent=self)
            return
        dialog = SupplierFormDialog(self, "Modifier le fournisseur", supplier)
        if dialog.result:
            name, contact, email, phone, notes = dialog.result
            save_supplier(name, contact, email, phone, notes, supplier_id=supplier_id)
            self.refresh()

    def delete_supplier(self):
        selection = self.tree.selection()
        if not selection:
            messagebox.showwarning("Fournisseurs", "Sélectionnez un fournisseur.", parent=self)
            return
        supplier_id = int(selection[0])
        if messagebox.askyesno("Confirmation", "Supprimer ce fournisseur ?", parent=self):
            delete_supplier(supplier_id)
            self.refresh()


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
        self.result = {
            'supplier_id': supplier_id,
            'expected_date': self.entry_due.get().strip() or None,
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
        self.result = (self.status_var.get(), receipt_lines, self.note_text.get('1.0', tk.END).strip())
        self.destroy()


class PurchaseOrderManagementDialog(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.title("Bons de commande")
        self.geometry("780x420")

        cols = ("ID", "Fournisseur", "Statut", "Création", "Échéance", "Note")
        self.tree = ttk.Treeview(self, columns=cols, show='headings')
        for col in cols:
            self.tree.heading(col, text=col)
            width = 80 if col == 'ID' else 140
            self.tree.column(col, width=width, anchor=tk.W)
        self.tree.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        btn_frame = ttk.Frame(self)
        btn_frame.pack(fill=tk.X, padx=10, pady=5)
        ttk.Button(btn_frame, text="Créer", command=self.create_order).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Réceptionner", command=self.receive_order).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Rafraîchir", command=self.refresh).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Fermer", command=self.destroy).pack(side=tk.RIGHT, padx=5)

        self.refresh()

    def refresh(self):
        for child in self.tree.get_children():
            self.tree.delete(child)
        for order in fetch_purchase_orders():
            order_id, created_at, status, expected_date, received_at, supplier_name, note, created_by = order
            supplier_display = supplier_name or 'Non défini'
            self.tree.insert('', tk.END, iid=order_id, values=(order_id, supplier_display, status, created_at, expected_date or '', note or ''))

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
        else:
            messagebox.showerror("Bon de commande", "Échec de la création.", parent=self)

    def receive_order(self):
        selection = self.tree.selection()
        if not selection:
            messagebox.showwarning("Bon de commande", "Sélectionnez un bon.", parent=self)
            return
        order_id = int(selection[0])
        items = fetch_purchase_order_items(order_id)
        if not items:
            messagebox.showinfo("Bon de commande", "Aucune ligne à réceptionner.", parent=self)
            return
        dialog = PurchaseOrderReceiveDialog(self, order_id, items)
        if dialog.result:
            status, receipt_lines, note = dialog.result
            update_purchase_order_status(order_id, status, self.parent.current_user, receipt_lines, note)
            self.parent.load_inventory()
            self.refresh()


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

        items = fetch_items_lookup()
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
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.title("Dotations collaborateurs")
        self.geometry("900x450")

        main_frame = ttk.Frame(self)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        self.collab_tree = ttk.Treeview(main_frame, columns=("Nom", "Service", "Fonction"), show='headings', height=12)
        for col in ("Nom", "Service", "Fonction"):
            self.collab_tree.heading(col, text=col)
            self.collab_tree.column(col, width=150, anchor=tk.W)
        self.collab_tree.bind('<<TreeviewSelect>>', lambda e: self.load_gear())
        self.collab_tree.grid(row=0, column=0, sticky='nsew')

        self.gear_tree = ttk.Treeview(main_frame, columns=("Article", "Taille", "Quantité", "Statut", "Échéance"), show='headings', height=12)
        for col in ("Article", "Taille", "Quantité", "Statut", "Échéance"):
            self.gear_tree.heading(col, text=col)
            width = 140 if col == "Article" else 100
            self.gear_tree.column(col, width=width, anchor=tk.W)
        self.gear_tree.grid(row=0, column=1, sticky='nsew', padx=10)

        main_frame.columnconfigure(0, weight=1)
        main_frame.columnconfigure(1, weight=1)
        main_frame.rowconfigure(0, weight=1)

        left_btns = ttk.Frame(main_frame)
        left_btns.grid(row=1, column=0, pady=5, sticky='w')
        ttk.Button(left_btns, text="Ajouter collaborateur", command=self.add_collaborator).pack(side=tk.LEFT, padx=5)
        ttk.Button(left_btns, text="Modifier", command=self.edit_collaborator).pack(side=tk.LEFT, padx=5)
        ttk.Button(left_btns, text="Supprimer", command=self.delete_collaborator).pack(side=tk.LEFT, padx=5)

        right_btns = ttk.Frame(main_frame)
        right_btns.grid(row=1, column=1, pady=5, sticky='e')
        ttk.Button(right_btns, text="Attribuer équipement", command=self.assign_gear).pack(side=tk.LEFT, padx=5)
        ttk.Button(right_btns, text="Marquer retour", command=self.return_gear).pack(side=tk.LEFT, padx=5)
        ttk.Button(right_btns, text="Rafraîchir", command=self.load_gear).pack(side=tk.LEFT, padx=5)

        ttk.Button(self, text="Fermer", command=self.destroy).pack(pady=5)

        self.load_collaborators()

    def get_selected_collaborator(self):
        selection = self.collab_tree.selection()
        if not selection:
            return None
        return int(selection[0])

    def load_collaborators(self):
        for child in self.collab_tree.get_children():
            self.collab_tree.delete(child)
        for collab in fetch_collaborators():
            collab_id, full_name, department, job_title, email, phone, hire_date, notes = collab
            self.collab_tree.insert('', tk.END, iid=collab_id, values=(full_name, department or '', job_title or ''))
        self.load_gear()

    def load_gear(self):
        for child in self.gear_tree.get_children():
            self.gear_tree.delete(child)
        collab_id = self.get_selected_collaborator()
        if not collab_id:
            return
        for gear in fetch_collaborator_gear(collab_id):
            gear_id, collab_name, item_name, size, quantity, issued_at, due_date, status, returned_at, notes, item_id, collaborator_id = gear
            self.gear_tree.insert('', tk.END, iid=gear_id, values=(item_name, size or '', quantity, status, due_date or ''))

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
            if assign_collaborator_gear(
                collab_id,
                data['item_id'],
                data['quantity'],
                data['size'],
                data['due_date'],
                data['notes'],
                operator=self.parent.current_user,
            ):
                self.parent.load_inventory()
                self.load_gear()

    def return_gear(self):
        selection = self.gear_tree.selection()
        if not selection:
            messagebox.showwarning("Collaborateurs", "Sélectionnez une dotation.", parent=self)
            return
        gear_id = int(selection[0])
        gear = next((g for g in fetch_collaborator_gear() if g[0] == gear_id), None)
        if not gear:
            messagebox.showerror("Collaborateurs", "Dotation introuvable.", parent=self)
            return
        quantity = gear[4]
        if messagebox.askyesno("Confirmation", "Confirmer le retour de cet équipement ?", parent=self):
            close_collaborator_gear(gear_id, quantity, self.parent.current_user, status='returned')
            self.parent.load_inventory()
            self.load_gear()


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

        var_db = tk.StringVar(value=DB_PATH)
        var_user_db = tk.StringVar(value=USER_DB_PATH)
        var_barcode = tk.StringVar(value=BARCODE_DIR)
        var_camera = tk.StringVar(value=str(CAMERA_INDEX))
        var_microphone = tk.StringVar(value="" if MICROPHONE_INDEX is None else str(MICROPHONE_INDEX))
        var_enable_voice = tk.BooleanVar(value=ENABLE_VOICE)
        var_enable_tts = tk.BooleanVar(value=ENABLE_TTS)
        var_enable_barcode = tk.BooleanVar(value=ENABLE_BARCODE_GENERATION)
        var_low_stock = tk.IntVar(value=DEFAULT_LOW_STOCK_THRESHOLD)

        ttk.Label(self, text="Chemin base stock :").grid(row=0, column=0, sticky=tk.W, padx=10, pady=5)
        entry_db = ttk.Entry(self, textvariable=var_db, width=40)
        entry_db.grid(row=0, column=1, padx=10, pady=5)

        ttk.Label(self, text="Chemin base utilisateurs :").grid(row=1, column=0, sticky=tk.W, padx=10, pady=5)
        entry_user_db = ttk.Entry(self, textvariable=var_user_db, width=40)
        entry_user_db.grid(row=1, column=1, padx=10, pady=5)

        ttk.Label(self, text="Répertoire codes-barres :").grid(row=2, column=0, sticky=tk.W, padx=10, pady=5)
        entry_barcode = ttk.Entry(self, textvariable=var_barcode, width=40)
        entry_barcode.grid(row=2, column=1, padx=10, pady=5)

        ttk.Label(self, text="Index caméra :").grid(row=3, column=0, sticky=tk.W, padx=10, pady=5)
        entry_camera = ttk.Entry(self, textvariable=var_camera, width=5)
        entry_camera.grid(row=3, column=1, sticky=tk.W, padx=10, pady=5)

        ttk.Label(self, text="Index microphone (laisser vide pour défaut) :").grid(row=4, column=0, sticky=tk.W, padx=10, pady=5)
        entry_microphone = ttk.Entry(self, textvariable=var_microphone, width=5)
        entry_microphone.grid(row=4, column=1, sticky=tk.W, padx=10, pady=5)

        chk_voice = ttk.Checkbutton(self, text="Activer reconnaissance vocale", variable=var_enable_voice)
        chk_voice.grid(row=5, column=0, columnspan=2, padx=10, pady=5, sticky=tk.W)
        chk_tts = ttk.Checkbutton(self, text="Activer synthèse vocale", variable=var_enable_tts)
        chk_tts.grid(row=6, column=0, columnspan=2, padx=10, pady=5, sticky=tk.W)
        chk_barcode = ttk.Checkbutton(self, text="Activer génération de codes-barres", variable=var_enable_barcode)
        chk_barcode.grid(row=7, column=0, columnspan=2, padx=10, pady=5, sticky=tk.W)

        ttk.Label(self, text="Seuil stock faible :").grid(row=8, column=0, sticky=tk.W, padx=10, pady=5)
        entry_threshold = ttk.Entry(self, textvariable=var_low_stock, width=5)
        entry_threshold.grid(row=8, column=1, sticky=tk.W, padx=10, pady=5)

        btn_frame = ttk.Frame(self)
        btn_frame.grid(row=9, column=0, columnspan=2, pady=10)
        ttk.Button(btn_frame, text="OK", command=lambda: self.on_ok(
            var_db, var_user_db, var_barcode, var_camera, var_microphone,
            var_enable_voice, var_enable_tts, var_enable_barcode, var_low_stock
        )).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Annuler", command=self.on_cancel).pack(side=tk.LEFT, padx=5)

        self.grab_set()
        self.wait_window(self)

    def on_ok(self, var_db, var_user_db, var_barcode, var_camera, var_microphone, var_enable_voice, var_enable_tts, var_enable_barcode, var_low_stock):
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
        self.result = {
            'db_path': var_db.get().strip(),
            'user_db_path': var_user_db.get().strip(),
            'barcode_dir': var_barcode.get().strip(),
            'camera_index': camera_index,
            'microphone_index': microphone_index,
            'enable_voice': var_enable_voice.get(),
            'enable_tts': var_enable_tts.get(),
            'enable_barcode_generation': var_enable_barcode.get(),
            'low_stock_threshold': var_low_stock.get()
        }
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

        self.category_list = tk.Listbox(self, height=8, width=30)
        self.category_list.grid(row=0, column=0, columnspan=2, padx=10, pady=5)
        self.load_categories()

        ttk.Label(self, text="Nouvelle catégorie :").grid(row=1, column=0, sticky=tk.W, padx=10, pady=5)
        self.new_category_var = tk.StringVar()
        entry_new = ttk.Entry(self, textvariable=self.new_category_var, width=20)
        entry_new.grid(row=1, column=1, padx=10, pady=5, sticky=tk.W)

        btn_add = ttk.Button(self, text="Ajouter", command=self.add_category)
        btn_add.grid(row=2, column=0, padx=10, pady=5, sticky=tk.W)
        btn_delete = ttk.Button(self, text="Supprimer", command=self.delete_category)
        btn_delete.grid(row=2, column=1, padx=10, pady=5, sticky=tk.W)

        btn_close = ttk.Button(self, text="Fermer", command=self.on_close)
        btn_close.grid(row=3, column=0, columnspan=2, pady=10)

        self.grab_set()
        self.wait_window(self)

    def load_categories(self):
        self.category_list.delete(0, tk.END)
        conn = None
        try:
            with db_lock:
                conn = sqlite3.connect(DB_PATH, timeout=30)
                cursor = conn.cursor()
                cursor.execute("SELECT name FROM categories ORDER BY name")
                rows = cursor.fetchall()
        except sqlite3.Error as e:
            messagebox.showerror("Erreur BD", f"Impossible de charger catégories : {e}")
            rows = []
        finally:
            if conn:
                conn.close()
        for r in rows:
            self.category_list.insert(tk.END, r[0])

    def add_category(self):
        name = self.new_category_var.get().strip()
        if not name:
            messagebox.showerror("Erreur", "Nom de catégorie vide.")
            return
        conn = None
        try:
            with db_lock:
                conn = sqlite3.connect(DB_PATH, timeout=30)
                cursor = conn.cursor()
                cursor.execute("INSERT INTO categories (name) VALUES (?)", (name,))
                conn.commit()
        except sqlite3.IntegrityError:
            messagebox.showerror("Erreur", "Catégorie existe déjà.")
        except sqlite3.Error as e:
            messagebox.showerror("Erreur BD", f"Impossible d'ajouter catégorie : {e}")
        finally:
            if conn:
                conn.close()
        self.new_category_var.set("")
        self.load_categories()
        self.result = True

    def delete_category(self):
        selection = self.category_list.curselection()
        if not selection:
            messagebox.showwarning("Attention", "Aucune catégorie sélectionnée.")
            return
        name = self.category_list.get(selection[0])
        conn = None
        try:
            with db_lock:
                conn = sqlite3.connect(DB_PATH, timeout=30)
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM items WHERE category_id = (SELECT id FROM categories WHERE name = ?)", (name,))
                count = cursor.fetchone()[0]
                if count > 0:
                    messagebox.showerror("Erreur", "Articles utilisent cette catégorie.")
                    return
                cursor.execute("DELETE FROM categories WHERE name = ?", (name,))
                conn.commit()
        except sqlite3.Error as e:
            messagebox.showerror("Erreur BD", f"Impossible de supprimer catégorie : {e}")
        finally:
            if conn:
                conn.close()
        self.load_categories()
        self.result = True

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
            return
        selected_cat = self.category_names[idx].lower()
        if "chaussure" in selected_cat:
            self.size_combobox['values'] = StockApp.SHOE_SIZES
        else:
            self.size_combobox['values'] = StockApp.CLOTHING_SIZES
        if self.var_size.get() not in self.size_combobox['values']:
            self.var_size.set('')

    def add_category_inline(self):
        name = simpledialog.askstring("Nouvelle Catégorie", "Entrez le nom de la nouvelle catégorie :", parent=self)
        if not name:
            return
        conn = None
        try:
            with db_lock:
                conn = sqlite3.connect(DB_PATH, timeout=30)
                cursor = conn.cursor()
                cursor.execute("INSERT INTO categories (name) VALUES (?)", (name,))
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

    root = tk.Tk()
    startup_listener.record("Création du conteneur Tkinter racine.", level=logging.DEBUG)
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
    app = StockApp(current_user, current_role, current_user_id)
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
