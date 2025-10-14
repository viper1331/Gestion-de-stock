# Gestion Stock Pro

Gestion Stock Pro est une application de bureau écrite en Python permettant de gérer un inventaire textile/chaussures avec une interface graphique professionnelle. Elle combine une base de données SQLite, une interface Tkinter et des fonctionnalités avancées comme la gestion des utilisateurs, la génération et la lecture de codes-barres ou encore le pilotage vocal.

## Table des matières
- [Fonctionnalités principales](#fonctionnalités-principales)
- [Architecture technique](#architecture-technique)
- [Prérequis](#prérequis)
- [Installation](#installation)
- [Lancement de l'application](#lancement-de-lapplication)
- [Configuration](#configuration)
- [Bases de données et sauvegardes](#bases-de-données-et-sauvegardes)
- [Utilisation](#utilisation)
  - [Gestion des utilisateurs](#gestion-des-utilisateurs)
  - [Gestion du stock](#gestion-du-stock)
  - [Codes-barres](#codes-barres)
  - [Commande vocale](#commande-vocale)
  - [Exports et rapports](#exports-et-rapports)
- [Création d'un exécutable](#création-dun-exécutable)
- [Dépannage](#dépannage)
- [Licence](#licence)

## Fonctionnalités principales
- Authentification multi-utilisateurs avec rôles `admin` et `user`, mot de passe haché et base de données dédiée aux comptes.【F:gestion_stock.py†L213-L351】【F:gestion_stock.py†L652-L779】
- Interface Tkinter complète : menus Fichier/Paramètres/Stock/Scan/Rapports/Aide, barre d'outils, zone de recherche et tableau d'articles avec mémorisation de la largeur des colonnes.【F:gestion_stock.py†L897-L1041】
- Gestion du catalogue : catégories illimitées, fiches articles (nom, code-barres, catégorie, taille, quantité) avec dialogues d'ajout/modification/suppression et horodatage des mises à jour.【F:gestion_stock.py†L1207-L1337】【F:gestion_stock.py†L1508-L1544】
- Recherche instantanée et filtrage du stock, seuil configurable pour détecter les niveaux faibles et génération de rapports dédiés.【F:gestion_stock.py†L1385-L1446】【F:gestion_stock.py†L1467-L1504】
- Intégration codes-barres : génération d'images (PNG), suppression automatique liée aux articles et scan via douchette ou caméra (OpenCV + pyzbar).【F:gestion_stock.py†L32-L59】【F:gestion_stock.py†L1339-L1382】
- Mode vocal optionnel : reconnaissance des commandes (SpeechRecognition) et synthèse vocale (pyttsx3) pour consulter ou mettre à jour les quantités.【F:gestion_stock.py†L60-L118】【F:gestion_stock.py†L1099-L1170】
- Outils d'administration : export CSV, sauvegarde de la base, dialogue de configuration pour personnaliser chemins, caméra, options vocales et seuils d'alerte.【F:gestion_stock.py†L1390-L1446】【F:gestion_stock.py†L1448-L1490】【F:gestion_stock.py†L1492-L1504】
- Suivi des mouvements d'entrée/sortie avec journal horodaté alimenté par les formulaires, la douchette et les commandes vocales.【F:gestion_stock.py†L181-L214】【F:gestion_stock.py†L1071-L1168】【F:gestion_stock.py†L1235-L1346】
- Génération d'un rapport PDF structuré incluant synthèse, tableaux des stocks critiques, histogramme par catégorie et graphique d'évolution des mouvements.【F:gestion_stock.py†L1496-L1610】

## Architecture technique
- **Langage** : Python 3 avec bibliothèques standard (`sqlite3`, `tkinter`, `configparser`, `threading`, etc.).
- **Base de données** : deux fichiers SQLite distincts (`stock.db` pour l'inventaire, `users.db` pour les comptes) protégés par un verrou (`threading.Lock`).【F:gestion_stock.py†L22-L118】【F:gestion_stock.py†L180-L212】
- **Interface** : Tkinter/ttk, dialogues modaux et Treeview pour afficher les articles.【F:gestion_stock.py†L897-L1205】
- **Fonctionnalités avancées** (facultatives) : OpenCV, pyzbar, python-barcode, SpeechRecognition, pyttsx3.
- **Configuration** : fichier `config.ini` auto-généré contenant paramètres globaux et largeur des colonnes.【F:gestion_stock.py†L21-L103】

## Prérequis
1. Python 3.10 ou supérieur.
2. Tkinter (inclus avec les distributions Python officielles).
3. Dépendances Python :
   ```bash
   pip install opencv-python pyzbar python-barcode[images] Pillow SpeechRecognition pyttsx3 pyaudio
   ```
   - `opencv-python` et `pyzbar` : scan caméra des codes-barres.
   - `python-barcode[images]` + `Pillow` : génération d'images PNG.
   - `SpeechRecognition`, `pyttsx3`, `pyaudio` : reconnaissance et synthèse vocales (optionnelles).
4. Dépendances système :
   - **Windows** : installation automatique via wheels.
   - **Linux/macOS** : installer la bibliothèque native `zbar` pour `pyzbar` (ex. `apt install libzbar0`).

## Installation
```bash
# Cloner le dépôt
git clone https://example.com/Gestion-de-stock.git
cd Gestion-de-stock

# Créer et activer un environnement virtuel (recommandé)
python -m venv .venv
source .venv/bin/activate  # Windows : .venv\Scripts\activate

# Installer les dépendances
pip install --upgrade pip
pip install -r requirements.txt
```

## Lancement de l'application
```bash
python gestion_stock.py
```
Au premier démarrage, l'application initialise les bases SQLite et vous demande de créer un administrateur. Après authentification, la fenêtre principale affiche le tableau des articles, la barre d'outils et les menus.

## Configuration
Un fichier `config.ini` est créé dans le répertoire racine avec deux sections :
- **Settings** : chemins (`db_path`, `user_db_path`, `barcode_dir`), index caméra, options vocales/tts, activation de la génération de codes-barres, seuil d'alerte et dernier utilisateur mémorisé.【F:gestion_stock.py†L24-L72】
- **ColumnWidths** : mémorise automatiquement la largeur des colonnes du tableau.【F:gestion_stock.py†L1059-L1097】

Les paramètres peuvent être modifiés via le menu **Paramètres → Configurer Générales** ou en éditant `config.ini` (l'application réécrit le fichier lors de la fermeture). Certaines options (caméra, voix) nécessitent un redémarrage.【F:gestion_stock.py†L1448-L1478】

## Bases de données et sauvegardes
- `stock.db` : contient les tables `categories` et `items` ainsi qu'un index sur le nom des articles.【F:gestion_stock.py†L160-L210】
- `users.db` : stocke les utilisateurs avec leurs rôles et mots de passe hachés.【F:gestion_stock.py†L213-L351】
- Les deux bases sont créées automatiquement si elles n'existent pas.
- Utilisez **Fichier → Sauvegarder base** pour créer une copie horodatée du fichier de stock. Cette action copie physiquement la base dans l'emplacement choisi.【F:gestion_stock.py†L1470-L1490】

## Utilisation
### Gestion des utilisateurs
- Les administrateurs peuvent ouvrir **Paramètres → Gérer Utilisateurs** pour ajouter, supprimer ou modifier le rôle d'un compte. Impossible de supprimer ou de rétrograder son propre compte par sécurité.【F:gestion_stock.py†L712-L779】
- La boîte de dialogue de connexion propose l'option « Se souvenir de moi » pour pré-remplir le champ utilisateur.【F:gestion_stock.py†L652-L704】

### Gestion du stock
- Ajouter/modifier/supprimer un article depuis la barre d'outils ou le menu **Stock**. Les dialogues permettent de choisir la catégorie, saisir la taille (listes dédiées vêtements/chaussures) et ajuster la quantité.【F:gestion_stock.py†L1207-L1337】
- Les actions **Entrée**/**Sortie** enregistrent automatiquement les mouvements avec commentaire et opérateur, que ce soit depuis la liste ou après un scan code-barres.【F:gestion_stock.py†L1124-L1170】【F:gestion_stock.py†L1235-L1317】
- La zone « Rechercher » filtre instantanément le tableau sur le nom ou le code-barres.【F:gestion_stock.py†L1385-L1446】
- Les colonnes redimensionnées sont mémorisées à la fermeture et restaurées à l'ouverture suivante.【F:gestion_stock.py†L1059-L1097】

### Codes-barres
- La douchette USB simule une saisie clavier dans le champ « Scan Douchette » ; le code est ensuite traité automatiquement.【F:gestion_stock.py†L1339-L1424】
- Le scan caméra ouvre un flux vidéo (OpenCV) et détecte les codes via `pyzbar`. Quitter avec `Q` ou après détection.【F:gestion_stock.py†L1339-L1378】
- La génération crée une image PNG dans le dossier `barcodes/`, nettoyée lorsque l'article est supprimé.【F:gestion_stock.py†L31-L59】【F:gestion_stock.py†L1269-L1337】

### Commande vocale
- Disponible si l'option est activée et si `SpeechRecognition` + microphone fonctionnels. Démarrer/arrêter via la barre d'outils.
- Commandes prises en charge (exemples) :
  - « ajouter 5 chemise blanche »
  - « retirer 2 basket noire »
  - « quantité de chemise blanche »
  - « générer codebarre pour chemise blanche »
  - « stop voice » pour désactiver l'écoute.
- L'application lit également les réponses via `pyttsx3` si activé.【F:gestion_stock.py†L1099-L1170】

### Exports et rapports
- **Fichier → Exporter CSV** : exporte les colonnes principales dans un fichier CSV séparé par des virgules.【F:gestion_stock.py†L1385-L1446】
- **Rapports → Rapport Stock Faible** : affiche les articles sous un seuil choisi (par défaut depuis `config.ini`).【F:gestion_stock.py†L1467-L1504】
- **Rapports → Exporter Rapport PDF** : crée un rapport multi-pages (synthèse, mouvements récents, graphiques) prêt à partager.【F:gestion_stock.py†L1496-L1610】

## Création d'un exécutable
Deux options sont fournies :
1. **Script automatisé (recommandé)** :
   ```bash
   python build_exe.py
   ```
   Ce script met automatiquement à jour `pip`, installe PyInstaller ainsi que toutes les dépendances présentes dans `requirements.txt`, puis lance la génération de l'exécutable via `GestionStockPro.spec`.
2. **PyInstaller (manuel)** :
   ```bash
   pip install -r requirements.txt
   pyinstaller --onefile --windowed --name GestionStockPro gestion_stock.py
   ```
   Le fichier `GestionStockPro.spec` donne un exemple de configuration PyInstaller.【F:GestionStockPro.spec†L1-L33】
3. **Installateur Windows classique** : utiliser `setup.py` avec `python setup.py bdist_wininst` pour générer un installeur `.exe`.【F:setup.py†L1-L28】

## Dépannage
- **Le scan caméra ne fonctionne pas** : vérifier que la caméra est accessible et que `opencv-python` et `pyzbar` sont installés. Sur Linux, installer `libzbar0`.
- **Erreur audio** : `SpeechRecognition` nécessite `pyaudio` (ou `sounddevice` en alternative). Sur Windows, installer `PyAudio` via une roue précompilée.
- **Codes-barres illisibles** : assurer l'installation de `Pillow` et utiliser une imprimante adaptée. Le dossier `barcodes` doit être accessible en écriture.
- **Mot de passe oublié** : supprimer `users.db` pour recréer un administrateur (les comptes seront perdus).

## Licence
© 2025 Sebastien Cangemi. Tous droits réservés. Voir l'en-tête du fichier `gestion_stock.py` pour plus d'informations.【F:gestion_stock.py†L1-L10】
