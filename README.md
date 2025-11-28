# Gestion Stock Pro 2.0

Ce dépôt contient la refonte moderne de Gestion Stock Pro articulée autour d'un backend FastAPI, d'un frontend React/Vite et d'un empaquetage desktop via Tauri. L'objectif est de conserver la richesse fonctionnelle de l'application Tkinter historique tout en fournissant une architecture maintenable, testable et prête pour le web.

## Table des matières
1. [Structure du projet](#structure-du-projet)
2. [Aperçu des évolutions 2.0](#aperçu-des-évolutions-20)
3. [Backend](#backend-backend)
4. [Frontend](#frontend-frontend)
5. [Desktop](#desktop-desktoptauri)
6. [Scripts & automatisation](#scripts--automatisation-scripts)
7. [Prérequis](#prérequis)
8. [Installation rapide](#installation-rapide)
9. [Commandes de lancement](#commandes-de-lancement-simplifiées)
10. [Tests & qualité](#tests--qualité)
11. [Fonctionnalités couvertes](#fonctionnalités-couvertes)
12. [Héritage Tkinter & compatibilité](#héritage-tkinter--compatibilité)
13. [Documentation & idées futures](#documentation--idées-futures)
14. [Données de démonstration](#données-de-démonstration)
15. [Roadmap](#roadmap--todo)
16. [Licence](#licence)

## Structure du projet
```
gestion-stock-pro/
├─ backend/            # API FastAPI + WebSocket + services SQLite
├─ frontend/           # SPA React/TypeScript (Vite, Tailwind, shadcn/ui ready)
├─ desktop/tauri/      # Client desktop Tauri lançant le backend local
├─ gestion_stock/      # Version Tkinter historique maintenue pour compatibilité
├─ tests/              # Suite de tests unitaires couvrant l'héritage Tkinter
├─ docs/               # Notes fonctionnelles et suggestions d'évolution
├─ scripts/            # Scripts d'aide au développement et au build
└─ README.md           # Ce document
```

## Aperçu des évolutions 2.0
- **Architecture découplée** : séparation nette des couches backend FastAPI, frontend React/Vite et client desktop Tauri afin de couvrir les usages web, desktop et embarqués.
- **API modernisée** : authentification JWT, WebSockets (caméra/voix) et services spécialisés (stock, fournisseurs, dotations, pharmacie) livrés dans `backend/`.
- **Frontend réactif** : UI sombre, composants modulaires et store Zustand pour une expérience cohérente, responsive et testée avec Vitest.
- **Automatisation renforcée** : scripts Python/Bash/PowerShell pour lancer, tester et packager l'application, plus des workflows de sauvegarde et d'export.
- **Qualité garantie** : suites de tests `backend/tests`, `tests/` (héritage Tkinter) et `frontend` assurant la non-régression des logiques métiers clés.

### Backend (`backend/`)
- `app.py` : application FastAPI, configuration CORS et enregistrement des routes.
- `api/` : routeurs REST (authentification JWT, catalogue, rapports, configuration, sauvegardes, codes-barres).
- `core/` : accès SQLite, modèles Pydantic, services métiers et sécurité (bcrypt + JWT).
- `ws/` : WebSockets pour le scan caméra et les commandes vocales (ack temps réel).
- `assets/barcodes/` : stockage des PNG générés.
- `requirements.txt` : dépendances Python minimales.
- `tests/` : tests pytest couvrant le healthcheck et le flux de connexion.

### Frontend (`frontend/`)
- Vite + React + TypeScript avec Tailwind configuré en mode sombre par défaut.
- `src/app/` : router, store Zustand et gestion du thème (persisté en localStorage).
- `src/features/` : pages Auth, Inventaire, Codes-barres, Rapports, Paramètres, Voix.
- `src/components/` : layout principal, toggle de thème et composants transverses.
- `src/lib/` : instance Axios (JWT-ready), helpers WebSocket et persistance.
- Tests unitaires avec Vitest + Testing Library.

### Desktop (`desktop/tauri/`)
- Configuration Tauri minimaliste (`src-tauri/tauri.conf.json`, `Cargo.toml`).
- `src/main.rs` : lance le backend FastAPI comme processus enfant et le termine proprement.
- Scripts `pnpm tauri dev/build` pour l'intégration continue.

### Scripts & automatisation (`scripts/`)
- `dev.ps1` : bootstrap automatique backend + frontend en développement.
- `build_all.ps1` : pipeline de build (backend tests + build frontend + package Tauri).

## Prérequis
- Python 3.10+
- Node.js 18+ et npm/pnpm
- Rust toolchain (pour Tauri)
- SQLite (fourni par Python)

## Installation rapide
```bash
# Backend
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pytest
uvicorn backend.app:app --reload
```

```bash
# Frontend
cd frontend
npm install
npm run dev
```

```bash
# Desktop
cd desktop/tauri
npm install
npm run tauri dev
```

## Configuration Git
Si le dépôt a été récupéré sans informations de remote (par exemple via une archive ZIP), ajoutez l'origine GitHub avant de lancer
un `git pull` :

```bash
git remote add origin https://github.com/viper1331/Gestion-de-stock.git
git pull --ff-only origin main
```

## Commandes de lancement simplifiées
Si vous souhaitez démarrer rapidement les deux parties sans répéter toutes les étapes manuelles ci-dessus, deux scripts sont
disponibles à la racine du projet :

```bash
# Lance le backend FastAPI (crée l'environnement virtuel si besoin)
./run_backend.sh

# Lance le frontend Vite
./run_frontend.sh
```

Chaque script accepte des variables d'environnement (par ex. `HOST`, `PORT`, `RELOAD`, `SKIP_INSTALL`) pour ajuster le
comportement, mais un simple appel suffit pour lancer les serveurs avec les paramètres par défaut.

## Scripts utiles
- `python scripts/dev.py` : lance simultanément le backend FastAPI (uvicorn) et le frontend Vite. Options : `--no-frontend` pour ne démarrer que l'API et `--port` pour changer le port du backend.
- `python scripts/run_backend.py` : crée/active `.venv`, installe les dépendances, exécute `pytest` puis lance FastAPI (`--host`/`--port`, `--skip-install`, `--skip-tests`).
- `python scripts/run_frontend.py` : exécute `npm install` puis lance Vite (`--host`/`--open`).
- `python scripts/update_repo.py` : récupère les dernières modifications Git, installe automatiquement les dépendances modifiées et laisse tourner les serveurs déjà lancés.
- `pwsh scripts/dev.ps1` : lance FastAPI en mode reload et Vite en parallèle.
- `pwsh scripts/build_all.ps1` : exécute les tests backend, build la SPA et package l'app Tauri.

## Tests & qualité
- **Backend FastAPI** : `cd backend && pytest` pour couvrir les routes d'authentification, permissions, inventaire, sauvegardes et WebSockets.
- **Frontend React** : `cd frontend && npm run test` (Vitest + Testing Library) pour garantir la stabilité des composants et hooks partagés.
- **Héritage Tkinter** : `python -m pytest tests` vérifie les fonctions critiques (`adjust_item_quantity`, gestion utilisateurs, fournisseurs habillement) du module `gestion_stock`. Les tests `tests/test_inventory.py`, `tests/test_backup_manager.py` ou `tests/test_cli.py` servent de documentation vivante sur l'API historique.
- **Linting facultatif** : exécutez `ruff`/`black` côté backend ou `npm run lint` côté frontend si vous souhaitez aligner le style avant contribution.

## Données & configuration
- Bases SQLite créées automatiquement dans `backend/data/` (utilisateurs + stock).
- Fichier `backend/config.example.ini` à copier en `backend/config.ini` pour personnaliser les préférences globales (thème, périphériques audio, etc.) sans générer de conflits Git.
- Sauvegardes disponibles via l'endpoint `/backup/` (zip horodaté des bases).

## Fonctionnalités couvertes

### Administration & sécurité
- Authentification JWT complète (login, refresh, profil `me`).【F:backend/api/auth.py†L27-L60】
- Provision automatique d'un administrateur `admin/admin123` et protection contre sa désactivation ou suppression accidentelle.【F:backend/core/services.py†L144-L188】【F:backend/tests/test_app.py†L392-L460】
- Gestion des utilisateurs (création, mise à jour du rôle/mot de passe, activation) réservée aux administrateurs.【F:backend/api/users.py†L10-L54】
- Droits modulaires fins (`suppliers`, `dotations`, `pharmacy`, etc.) via l'API `/permissions/modules` pour déléguer la vue/l'édition par utilisateur.【F:backend/api/permissions.py†L12-L66】【F:backend/tests/test_app.py†L300-L349】

### Stock & inventaire
- CRUD d'articles avec recherche nom/SKU, tailles, seuils de réapprovisionnement et rattachement à un fournisseur.【F:backend/api/items.py†L12-L42】【F:backend/core/services.py†L309-L358】
- Gestion des catégories et tailles normalisées (tri, suppression des doublons/cases) pour l'habillement.【F:backend/api/categories.py†L11-L41】【F:backend/tests/test_app.py†L549-L597】
- Journal des mouvements (entrées/sorties) avec contrôle des droits et mise à jour du stock en temps réel.【F:backend/api/items.py†L44-L61】【F:backend/core/services.py†L540-L577】
- Création automatique de bons de commande suggérés lorsqu'un article passe sous son seuil et dispose d'un fournisseur, consolidation des quantités sur un ordre existant.【F:backend/core/services.py†L81-L141】【F:backend/tests/test_app.py†L210-L287】
- Modules spécialisés pour l'inventaire véhicules et l'inventaire remises partageant la logique commune (CRUD, catégories, mouvements) et protégés par les mêmes permissions granulaires.【F:backend/app.py†L5-L50】【F:backend/api/vehicle_inventory.py†L1-L112】【F:backend/api/remise_inventory.py†L1-L112】【F:backend/core/services.py†L23-L1132】【F:backend/tests/test_app.py†L1-L1204】

### Fournisseurs & achats
- Module fournisseurs complet (CRUD, consultation, suppression) conditionné par les droits modulaires.【F:backend/api/suppliers.py†L13-L63】
- Stockage des coordonnées (contact, email, téléphone) et liaison aux articles pour déclencher les réapprovisionnements automatiques.【F:backend/core/models.py†L123-L158】【F:backend/core/services.py†L613-L684】

### Dotations & collaborateurs
- Fiches collaborateurs (identité, service, contacts) et allocation d'équipements par collaborateur.【F:backend/api/dotations.py†L15-L67】【F:backend/core/services.py†L687-L858】
- Restitution/restock optionnel lors de la suppression d'une dotation afin de réintégrer le stock.【F:backend/api/dotations.py†L85-L105】【F:backend/tests/test_app.py†L464-L509】

### Pharmacie & consommables
- Inventaire dédié aux produits pharmaceutiques avec dosage, date de péremption et localisation interne.【F:backend/api/pharmacy.py†L15-L57】【F:backend/tests/test_app.py†L512-L546】

### Rapports, exports & sauvegardes
- Rapport « stock bas » filtrable par seuil et export CSV de l'inventaire en un clic.【F:backend/api/reports.py†L15-L26】
- Sauvegarde à la demande des bases SQLite (stock + utilisateurs) en archive ZIP horodatée.【F:backend/api/backup.py†L17-L34】

### Codes-barres & intégrations temps réel
- Génération/suppression de codes-barres PNG Code128 prêts à l'impression.【F:backend/services/barcode.py†L33-L93】
- WebSockets `camera` et `voice` fournissant des accusés JSON pour le scan ou les commandes vocales côté navigateur.【F:backend/ws/camera.py†L9-L17】【F:backend/ws/voice.py†L9-L18】

### Frontend & expérience utilisateur
- SPA React/TypeScript avec thème sombre persistant, store Zustand et helpers Axios/WebSocket centralisés.【F:frontend/src/app/theme.tsx†L1-L36】【F:frontend/src/app/store.ts†L1-L11】【F:frontend/src/lib/api.ts†L1-L23】【F:frontend/src/lib/ws.ts†L1-L6】
- Tests unitaires front (Vitest + Testing Library) et couverture backend (pytest) pour sécuriser les régressions.【F:frontend/package.json†L7-L33】【F:backend/tests/test_app.py†L1-L520】

## Héritage Tkinter & compatibilité
- Le dossier `gestion_stock/` conserve l'application Tkinter d'origine (menus, dialogues, gestion SQLite). Lancez-la directement via `python -m gestion_stock` pour tester une interface poste fixe ou pour comparer le comportement avec la nouvelle stack web.
- Les scripts `build_exe.py` + `GestionStockPro.spec` automatisent la création d'un exécutable Windows via PyInstaller pour cette version historique.
- La suite `tests/` illustre comment piloter les API Tkinter côté Python pur (ex. `tests/test_inventory.py` pour `adjust_item_quantity`, `tests/test_backup_manager.py` pour les sauvegardes locales et `tests/test_cli.py` pour la CLI). Cela garantit que les correctifs appliqués à la refonte n'introduisent pas de régressions dans les installations existantes.

## Documentation & idées futures
- `docs/feature_suggestions.md` centralise les prochaines grosses fonctionnalités (commandes fournisseurs, approbations multi-utilisateurs, alertes multicanal, dashboard temps réel). Inspirez-vous-en pour prioriser les itérations produit.
- `REVIEW.md` décrit les points déjà analysés (typos, robustesse de `init_user_db`, alignement doc/code) et peut servir de check-list lors des revues de code.

## Données de démonstration
Un administrateur `admin/admin123` est généré automatiquement au premier lancement. Créez vos propres comptes via l'API `/auth`.

## Roadmap & TODO
- Finaliser les composants shadcn/ui et DataGrid avancé.
- Intégrer la génération PDF/CSV côté backend ou frontend.
- Ajouter des tests E2E (Playwright/Cypress).
- Mettre en place une CI GitHub Actions (lint + tests + build).

## Licence
Projet livré sans licence explicite. Veuillez contacter l'auteur pour la redistribution.
