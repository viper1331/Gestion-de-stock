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
import hashlib
from datetime import datetime, timedelta
import traceback
import configparser

# ----------------------------
# Lecture de la configuration
# ----------------------------
CONFIG_FILE = 'config.ini'
config = configparser.ConfigParser()
default_config = {
    'db_path': 'stock.db',
    'user_db_path': 'users.db',
    'barcode_dir': 'barcodes',
    'camera_index': '0',
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
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False

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
    except sqlite3.Error as e:
        print(f"[DB Error] init_user_db: {e}")
    finally:
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

        conn.commit()
    except sqlite3.Error as e:
        print(f"[DB Error] init_stock_db: {e}")
    finally:
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
        conn.close()

def verify_user(username: str, password: str):
    """
    Vérifie les identifiants dans USER_DB_PATH. Retourne (True, role) si succès, sinon (False, None).
    """
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
        conn.close()

def users_exist() -> bool:
    """
    Indique s'il existe au moins un utilisateur dans USER_DB_PATH.
    """
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
        conn.close()

def fetch_all_users():
    """
    Récupère tous les utilisateurs (id, username, role) depuis USER_DB_PATH.
    """
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
        conn.close()

def delete_user_by_id(user_id: int) -> bool:
    """
    Supprime un utilisateur par son ID dans USER_DB_PATH. Retourne True si succès.
    """
    try:
        with db_lock:
            conn = sqlite3.connect(USER_DB_PATH, timeout=30)
            cursor = conn.cursor()
            cursor.execute("DELETE FROM users WHERE id = ?", (user_id,))
            conn.commit()
        return True
    except sqlite3.Error as e:
        print(f"[DB Error] delete_user_by_id: {e}")
        return False
    finally:
        conn.close()

def update_user_role(user_id: int, new_role: str) -> bool:
    """
    Met à jour le rôle d'un utilisateur dans USER_DB_PATH. new_role ∈ {'admin','user'}.
    """
    try:
        with db_lock:
            conn = sqlite3.connect(USER_DB_PATH, timeout=30)
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET role = ? WHERE id = ?", (new_role, user_id))
            conn.commit()
        return True
    except sqlite3.Error as e:
        print(f"[DB Error] update_user_role: {e}")
        return False
    finally:
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
            microphone = sr.Microphone(device_index=CAMERA_INDEX) if CAMERA_INDEX is not None else sr.Microphone()
            with microphone as source:
                pass
            print(f"[DEBUG_VOICE] Micro initialisé avec index {CAMERA_INDEX} : {sr.Microphone.list_microphone_names()[CAMERA_INDEX]}")
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

        try:
            init_stock_db(DB_PATH)
        except Exception as e:
            messagebox.showerror("Erreur BD", f"Impossible d'initialiser la base du stock : {e}")
            self.destroy()
            return

        # Appliquer largeurs sauvegardées
        self.apply_saved_column_widths()
        self.load_inventory()

        if ENABLE_VOICE and SR_LIB_AVAILABLE:
            if microphone is None:
                init_recognizer()

    def on_closing(self):
        self.save_column_widths()
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
        settings_menu.add_command(label="Configurer Générales", command=self.open_config_dialog)
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

        search_frame = ttk.Frame(main_frame)
        ttk.Label(search_frame, text="Rechercher :").pack(side=tk.LEFT, padx=5)
        self.entry_search = ttk.Entry(search_frame)
        self.entry_search.pack(side=tk.LEFT, padx=5)
        self.entry_search.bind('<KeyRelease>', lambda e: self.load_inventory())
        search_frame.pack(fill=tk.X, pady=5)

        scan_frame = ttk.Frame(main_frame)
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
        self.tree = ttk.Treeview(main_frame, columns=cols, show='headings', selectmode='browse')
        for col in cols:
            self.tree.heading(col, text=col)
            self.tree.column(col, anchor=tk.CENTER)
        self.tree.pack(fill=tk.BOTH, expand=True)

        # Configuration des couleurs de lignes selon le niveau de stock
        self.tree.tag_configure('stock_zero', background='#f8d7da', foreground='#721c24')
        self.tree.tag_configure('stock_low', background='#fff3cd', foreground='#856404')
        self.tree.tag_configure('stock_ok', background='#e8f5e9', foreground='#1b5e20')
        self.tree.tag_configure('stock_unknown', background='#f0f0f0', foreground='#333333')

    def load_inventory(self):
        search_text = self.entry_search.get().lower().strip()
        for row in self.tree.get_children():
            self.tree.delete(row)
        try:
            with db_lock:
                conn = sqlite3.connect(DB_PATH, timeout=30)
                cursor = conn.cursor()
                if search_text:
                    cursor.execute(
                        "SELECT items.id, items.name, items.barcode, categories.name, items.size, items.quantity, items.last_updated "
                        "FROM items LEFT JOIN categories ON items.category_id = categories.id "
                        "WHERE lower(items.name) LIKE ? OR items.barcode LIKE ?",
                        (f'%{search_text}%', f'%{search_text}%')
                    )
                else:
                    cursor.execute(
                        "SELECT items.id, items.name, items.barcode, categories.name, items.size, items.quantity, items.last_updated "
                        "FROM items LEFT JOIN categories ON items.category_id = categories.id"
                    )
                rows = cursor.fetchall()
        except sqlite3.Error as e:
            messagebox.showerror("Erreur BD", f"Impossible de charger l'inventaire : {e}")
            rows = []
        finally:
            conn.close()
        for item in rows:
            tag = self._get_stock_tag(item[5])
            self.tree.insert('', tk.END, values=item, tags=(tag,))
        count = len(self.tree.get_children())
        self.status.set(f"Articles listés : {count}")

    def _get_stock_tag(self, quantity):
        """Retourne le tag à appliquer selon la quantité disponible."""
        try:
            qty = int(quantity)
        except (TypeError, ValueError):
            return 'stock_unknown'
        if qty <= 0:
            return 'stock_zero'
        if qty <= self.low_stock_threshold:
            return 'stock_low'
        return 'stock_ok'

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
            name, barcode_value, category_id, size, qty = dialog.result
            try:
                with db_lock:
                    conn = sqlite3.connect(DB_PATH, timeout=30)
                    cursor = conn.cursor()
                    timestamp = datetime.now().isoformat()
                    cursor.execute(
                        "INSERT INTO items (name, barcode, category_id, size, quantity, last_updated) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (name, barcode_value, category_id, size, qty, timestamp)
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
                conn.close()
            self.load_inventory()

    def open_edit_selected(self):
        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning("Attention", "Aucun article sélectionné.")
            return
        item = self.tree.item(selected)
        id_, name, barcode_value, category_name, size_value, qty, _ = item['values']
        try:
            old_qty = int(qty)
        except (TypeError, ValueError):
            old_qty = 0
        category_id = None
        if category_name:
            try:
                with db_lock:
                    conn = sqlite3.connect(DB_PATH, timeout=30)
                    cursor = conn.cursor()
                    cursor.execute("SELECT id FROM categories WHERE name = ?", (category_name,))
                    res = cursor.fetchone()
                    if res:
                        category_id = res[0]
            except sqlite3.Error:
                category_id = None
            finally:
                conn.close()
        dialog = ItemDialog(self, "Modifier Article", name, barcode_value, category_id, size_value, qty)
        if dialog.result:
            new_name, new_barcode, new_category_id, new_size, new_qty = dialog.result
            try:
                with db_lock:
                    conn = sqlite3.connect(DB_PATH, timeout=30)
                    cursor = conn.cursor()
                    timestamp = datetime.now().isoformat()
                    cursor.execute(
                        "UPDATE items SET name = ?, barcode = ?, category_id = ?, size = ?, quantity = ?, last_updated = ? WHERE id = ?",
                        (new_name, new_barcode, new_category_id, new_size, new_qty, timestamp, id_)
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
        if messagebox.askyesno("Confirmation", f"Supprimer l'article '{name}' ?"):
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
                conn.close()
            self.load_inventory()

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
            try:
                with db_lock:
                    conn = sqlite3.connect(DB_PATH, timeout=30)
                    cursor = conn.cursor()
                    cursor.execute("SELECT name FROM categories WHERE id = ?", (category_id,))
                    cat_name_db = cursor.fetchone()[0]
            except sqlite3.Error:
                cat_name_db = ""
            finally:
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
        global CAMERA_INDEX
        idx = choose_microphone(self)
        if idx is not None:
            CAMERA_INDEX = idx
            init_recognizer()
            messagebox.showinfo("Micro", f"Micro sélectionné : {sr.Microphone.list_microphone_names()[CAMERA_INDEX]}")

    def open_config_dialog(self):
        dialog = ConfigDialog(self)
        if dialog.result:
            config['Settings']['db_path'] = dialog.result['db_path']
            config['Settings']['user_db_path'] = dialog.result['user_db_path']
            config['Settings']['barcode_dir'] = dialog.result['barcode_dir']
            config['Settings']['camera_index'] = str(dialog.result['camera_index'])
            config['Settings']['enable_voice'] = str(dialog.result['enable_voice']).lower()
            config['Settings']['enable_tts'] = str(dialog.result['enable_tts']).lower()
            config['Settings']['enable_barcode_generation'] = str(dialog.result['enable_barcode_generation']).lower()
            config['Settings']['low_stock_threshold'] = str(dialog.result['low_stock_threshold'])
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                config.write(f)
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
        default_name = f"backup_stock_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
        file_path = filedialog.asksaveasfilename(
            title="Sauvegarder base de données",
            defaultextension=".db",
            initialfile=default_name,
            filetypes=[("Base SQLite", "*.db"), ("Tous fichiers", "*.*")]
        )
        if not file_path:
            return
        try:
            shutil.copy2(DB_PATH, file_path)
        except Exception as e:
            messagebox.showerror("Erreur Backup", f"Impossible de sauvegarder la base : {e}")
            return
        messagebox.showinfo("Backup réussi", f"Base sauvegardée vers : {file_path}")
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
        try:
            with db_lock:
                conn = sqlite3.connect(USER_DB_PATH, timeout=30)
                cursor = conn.cursor()
                cursor.execute("SELECT id FROM users WHERE username = ?", (new_user,))
                uid = cursor.fetchone()[0]
        except:
            uid = None
        finally:
            conn.close()
        root.destroy()
        app = StockApp(new_user, new_role, uid)
        app.mainloop()

# ----------------------
# BOÎTE DE DIALOGUE CONFIGURATION
# ----------------------
class ConfigDialog(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("Configuration Générales")
        self.resizable(False, False)
        self.result = None

        var_db = tk.StringVar(value=DB_PATH)
        var_user_db = tk.StringVar(value=USER_DB_PATH)
        var_barcode = tk.StringVar(value=BARCODE_DIR)
        var_camera = tk.IntVar(value=CAMERA_INDEX)
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

        chk_voice = ttk.Checkbutton(self, text="Activer reconnaissance vocale", variable=var_enable_voice)
        chk_voice.grid(row=4, column=0, columnspan=2, padx=10, pady=5, sticky=tk.W)
        chk_tts = ttk.Checkbutton(self, text="Activer synthèse vocale", variable=var_enable_tts)
        chk_tts.grid(row=5, column=0, columnspan=2, padx=10, pady=5, sticky=tk.W)
        chk_barcode = ttk.Checkbutton(self, text="Activer génération de codes-barres", variable=var_enable_barcode)
        chk_barcode.grid(row=6, column=0, columnspan=2, padx=10, pady=5, sticky=tk.W)

        ttk.Label(self, text="Seuil stock faible :").grid(row=7, column=0, sticky=tk.W, padx=10, pady=5)
        entry_threshold = ttk.Entry(self, textvariable=var_low_stock, width=5)
        entry_threshold.grid(row=7, column=1, sticky=tk.W, padx=10, pady=5)

        btn_frame = ttk.Frame(self)
        btn_frame.grid(row=8, column=0, columnspan=2, pady=10)
        ttk.Button(btn_frame, text="OK", command=lambda: self.on_ok(
            var_db, var_user_db, var_barcode, var_camera, var_enable_voice, var_enable_tts, var_enable_barcode, var_low_stock
        )).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Annuler", command=self.on_cancel).pack(side=tk.LEFT, padx=5)

        self.grab_set()
        self.wait_window(self)

    def on_ok(self, var_db, var_user_db, var_barcode, var_camera, var_enable_voice, var_enable_tts, var_enable_barcode, var_low_stock):
        self.result = {
            'db_path': var_db.get().strip(),
            'user_db_path': var_user_db.get().strip(),
            'barcode_dir': var_barcode.get().strip(),
            'camera_index': var_camera.get(),
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
            conn.close()
        for r in rows:
            self.category_list.insert(tk.END, r[0])

    def add_category(self):
        name = self.new_category_var.get().strip()
        if not name:
            messagebox.showerror("Erreur", "Nom de catégorie vide.")
            return
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
        try:
            with db_lock:
                conn = sqlite3.connect(DB_PATH, timeout=30)
                cursor = conn.cursor()
                cursor.execute("SELECT id, name FROM categories ORDER BY name")
                rows = cursor.fetchall()
        except sqlite3.Error:
            rows = []
        finally:
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
    def __init__(self, parent, title, name='', barcode='', category_id=None, size='', quantity=0):
        super().__init__(parent)
        self.title(title)
        self.resizable(False, False)
        self.result = None

        self.var_name = tk.StringVar(value=name)
        self.var_barcode = tk.StringVar(value=barcode)
        self.var_quantity = tk.IntVar(value=quantity)
        self.var_category_id = tk.IntVar(value=category_id if category_id is not None else -1)
        self.var_size = tk.StringVar(value=size)

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
            except:
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

        btn_frame = ttk.Frame(self)
        btn_frame.grid(row=5, column=0, columnspan=3, pady=10)
        ttk.Button(btn_frame, text="OK", command=self.on_ok).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Annuler", command=self.on_cancel).pack(side=tk.LEFT, padx=5)

        self.entry_name.focus()
        self.grab_set()
        self.wait_window(self)

    def load_categories(self):
        try:
            with db_lock:
                conn = sqlite3.connect(DB_PATH, timeout=30)
                cursor = conn.cursor()
                cursor.execute("SELECT id, name FROM categories ORDER BY name")
                rows = cursor.fetchall()
        except sqlite3.Error:
            rows = []
        finally:
            conn.close()
        self.category_ids = [r[0] for r in rows]
        self.category_names = [r[1] for r in rows]
        self.cat_combobox['values'] = self.category_names

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
            conn.close()
        self.load_categories()

    def on_ok(self):
        name = self.var_name.get().strip()
        barcode_value = self.var_barcode.get().strip()
        qty = self.var_quantity.get()
        cat_index = self.cat_combobox.current()
        category_id = self.category_ids[cat_index] if cat_index >= 0 else None
        size = self.var_size.get().strip()

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

        self.result = (name, barcode_value, category_id, size, qty)
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
    init_stock_db(test_stock_db)
    init_user_db(test_user_db)
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
        for f in (test_stock_db, test_user_db):
            if os.path.exists(f):
                os.remove(f)
    print("All tests completed.")

# ---------------------------
# DÉMARRAGE PRINCIPAL
# ---------------------------
if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--test':
        run_tests()
    else:
        if not TK_AVAILABLE:
            print("Erreur : Tkinter non disponible. Le programme ne peut pas démarrer.")
            sys.exit(1)

        # Initialiser bases séparées
        init_stock_db(DB_PATH)
        init_user_db(USER_DB_PATH)

        root = tk.Tk()
        root.withdraw()
        login = LoginDialog(root)
        if not login.result:
            root.destroy()
            sys.exit(0)
        current_user = login.username
        current_role = login.role
        try:
            with db_lock:
                conn = sqlite3.connect(USER_DB_PATH, timeout=30)
                cursor = conn.cursor()
                cursor.execute("SELECT id FROM users WHERE username = ?", (current_user,))
                current_user_id = cursor.fetchone()[0]
        except:
            current_user_id = None
        finally:
            conn.close()
        root.destroy()
        app = StockApp(current_user, current_role, current_user_id)
        app.mainloop()
